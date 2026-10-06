"""Worker de áudio — modelos Pydantic (FASE 3A: fundação)."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    ok: bool = True
    service: str = "audio-worker"
    device: str = "cpu"


class TestJobRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=100)


class TestJobResponse(BaseModel):
    accepted: bool = True
    job_id: str = ""
    status: str = "queued"
