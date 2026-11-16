from contextlib import contextmanager
from functools import lru_cache
from os import environ
from pathlib import Path
from shutil import copyfileobj
from typing import BinaryIO, Protocol
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


class StorageError(Exception):
    pass


class ObjectStorage(Protocol):
    def put(self, key: str, source: BinaryIO, size: int) -> None: ...
    def open(self, key: str) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...


@contextmanager
def s3_errors():
    try:
        yield
    except (BotoCoreError, ClientError) as exc:
        raise StorageError("S3 request failed") from exc


class S3Storage:
    def __init__(self, bucket: str, endpoint: str | None) -> None:
        self.bucket = bucket
        with s3_errors():
            self.client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                config=Config(
                    connect_timeout=5,
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                    read_timeout=30,
                    retries={"mode": "standard", "total_max_attempts": 2},
                    s3={"addressing_style": "path"} if endpoint else None,
                ),
            )

    def put(self, key: str, source: BinaryIO, size: int) -> None:
        with s3_errors():
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=source,
                ContentLength=size,
                ContentType="application/pdf",
            )

    def open(self, key: str) -> BinaryIO:
        with s3_errors():
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]

    def delete(self, key: str) -> None:
        with s3_errors():
            self.client.delete_object(Bucket=self.bucket, Key=key)


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path(self, key: str) -> Path:
        owner, document = key.removesuffix(".pdf").split("/")
        return self.root / str(UUID(owner)) / f"{UUID(document)}.pdf"

    def put(self, key: str, source: BinaryIO, _size: int) -> None:
        target = self.path(key)
        staged = target.with_suffix(".tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with staged.open("wb") as stream:
                copyfileobj(source, stream)
            staged.replace(target)
        except OSError as exc:
            raise StorageError("Local write failed") from exc

    def open(self, key: str) -> BinaryIO:
        try:
            return self.path(key).open("rb")
        except OSError as exc:
            raise StorageError("Local read failed") from exc

    def delete(self, key: str) -> None:
        target = self.path(key)
        try:
            target.unlink(missing_ok=True)
            target.with_suffix(".tmp").unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError("Local delete failed") from exc


@lru_cache
def get_storage() -> ObjectStorage:
    backend = environ.get("DOCMIND_STORAGE_BACKEND", "s3")
    if backend == "local":
        root = Path(__file__).resolve().parents[3] / ".docmind-data" / "documents"
        return LocalStorage(Path(environ.get("DOCMIND_STORAGE_DIR", root)))
    if backend == "s3" and (bucket := environ.get("DOCMIND_S3_BUCKET")):
        return S3Storage(bucket, environ.get("DOCMIND_S3_ENDPOINT"))
    raise StorageError("Object storage is not configured")
