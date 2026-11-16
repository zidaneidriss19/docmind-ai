from datetime import UTC, datetime, timedelta
from hashlib import sha256
from os import environ
from secrets import token_urlsafe
from typing import Annotated, Literal
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import APIError
from app.models import AuthSession, User
from app.rate_limit import client_address, enforce

ACCESS_COOKIE = "docmind_access"
REFRESH_COOKIE = "docmind_refresh"
ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=7)
passwords = PasswordHasher()
dummy_hash = passwords.hash(token_urlsafe(32))
Database = Annotated[Session, Depends(get_db)]


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Annotated[EmailStr, Field(max_length=254)]
    password: Annotated[SecretStr, Field(min_length=1, max_length=128)]


class Registration(Credentials):
    password: Annotated[SecretStr, Field(min_length=12, max_length=128)]


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: EmailStr
    role: Literal["USER", "ADMIN"]
    created_at: datetime


def require_same_origin_request(
    request: Request,
    marker: Annotated[
        str | None,
        Header(
            alias="X-DocMind-Request", description="Enter 1 for same-origin mutations."
        ),
    ] = None,
) -> None:
    # Cross-origin scripts need a successful CORS preflight to send this header.
    # HTML forms cannot set it. The API does not enable cross-origin requests.
    if marker != "1" or request.headers.get("sec-fetch-site") == "cross-site":
        raise APIError(403, "CSRF_REJECTED", "A same-origin request is required.")


auth = APIRouter(
    prefix="/auth",
    tags=["authentication"],
    dependencies=[Depends(require_same_origin_request)],
)
users = APIRouter(prefix="/users", tags=["users"])


def digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def session_required() -> APIError:
    return APIError(401, "SESSION_REQUIRED", "Sign in to continue.")


def cookie_secure() -> bool:
    return environ.get("DOCMIND_COOKIE_SECURE", "true").lower() != "false"


def issue_cookies(response: Response, row: AuthSession, now: datetime) -> None:
    access, refresh = token_urlsafe(32), token_urlsafe(32)
    row.access_hash, row.refresh_hash = digest(access), digest(refresh)
    row.access_expires_at = min(now + ACCESS_TTL, row.refresh_expires_at)

    for name, token, expiry in (
        (ACCESS_COOKIE, access, row.access_expires_at),
        (REFRESH_COOKIE, refresh, row.refresh_expires_at),
    ):
        response.set_cookie(
            name,
            token,
            max_age=max(0, int((expiry - now).total_seconds())),
            httponly=True,
            secure=cookie_secure(),
            samesite="strict",
        )
    response.headers["Cache-Control"] = "no-store"


@auth.post("/register", status_code=201)
def register(
    payload: Registration, db: Database, response: Response, request: Request
) -> UserProfile:
    enforce(db, "register-ip", client_address(request), 30, 600)
    email = payload.email.casefold()
    if len(email) > 254:
        raise APIError(422, "VALIDATION_ERROR", "The normalized email is too long.")
    user = User(
        email=email, password_hash=passwords.hash(payload.password.get_secret_value())
    )
    try:
        with db.begin():
            db.add(user)
            db.flush()
            profile = UserProfile.model_validate(user)
    except IntegrityError as exc:
        if (
            getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            != "uq_users_email_lower"
        ):
            raise
        raise APIError(
            409, "EMAIL_ALREADY_REGISTERED", "This email is already registered."
        ) from exc
    response.headers["Cache-Control"] = "no-store"
    return profile


@auth.post("/login")
def login(
    payload: Credentials, db: Database, response: Response, request: Request
) -> UserProfile:
    address = client_address(request)
    enforce(db, "login-ip", address, 60, 600)
    enforce(db, "login-account-ip", f"{address}|{payload.email.casefold()}", 5, 60)
    email = payload.email.casefold()
    with db.begin():
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        try:
            passwords.verify(
                user.password_hash if user is not None else dummy_hash,
                payload.password.get_secret_value(),
            )
        except VerifyMismatchError:
            raise APIError(
                401, "INVALID_CREDENTIALS", "Invalid email or password."
            ) from None
        if user is None:
            raise APIError(401, "INVALID_CREDENTIALS", "Invalid email or password.")

        now = datetime.now(UTC)
        db.execute(
            delete(AuthSession).where(
                AuthSession.user_id == user.id, AuthSession.refresh_expires_at <= now
            )
        )
        row = AuthSession(user_id=user.id, refresh_expires_at=now + REFRESH_TTL)
        issue_cookies(response, row, now)
        db.add(row)
        return UserProfile.model_validate(user)


@auth.post("/refresh")
def refresh(request: Request, db: Database, response: Response) -> UserProfile:
    if not (token := request.cookies.get(REFRESH_COOKIE)):
        raise session_required()
    with db.begin():
        row = db.scalar(
            select(AuthSession)
            .where(AuthSession.refresh_hash == digest(token))
            .with_for_update()
        )
        now = datetime.now(UTC)
        if row is None or row.refresh_expires_at <= now:
            raise session_required()
        user = db.get_one(User, row.user_id)
        issue_cookies(response, row, now)
        return UserProfile.model_validate(user)


@auth.post("/logout", status_code=204)
def logout(request: Request, db: Database) -> Response:
    tokens = [
        predicate
        for name, column in (
            (ACCESS_COOKIE, AuthSession.access_hash),
            (REFRESH_COOKIE, AuthSession.refresh_hash),
        )
        if (token := request.cookies.get(name))
        for predicate in (column == digest(token),)
    ]
    if tokens:
        with db.begin():
            db.execute(delete(AuthSession).where(or_(*tokens)))

    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(
            name, httponly=True, secure=cookie_secure(), samesite="strict"
        )
    return response


def current_user(request: Request, db: Database) -> UserProfile:
    if not (token := request.cookies.get(ACCESS_COOKIE)):
        raise session_required()
    now = datetime.now(UTC)
    user = db.scalar(
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.access_hash == digest(token),
            AuthSession.access_expires_at > now,
        )
    )
    if user is None:
        raise session_required()
    return UserProfile.model_validate(user)


CurrentUser = Annotated[UserProfile, Depends(current_user)]


@users.get("/me")
def me(user: CurrentUser, response: Response) -> UserProfile:
    response.headers["Cache-Control"] = "no-store"
    return user
