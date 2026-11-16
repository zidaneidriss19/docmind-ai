from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]


app = FastAPI(title="DocMind AI")


@app.get("/health", tags=["health"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")
