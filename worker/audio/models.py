"""Worker de áudio — modelos da ingestão (FASE 3B)."""

from typing import Optional

from pydantic import BaseModel, Field


class AudioJobRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=100)
    source_url: str = Field(min_length=1, max_length=2048)


class AudioMetadata(BaseModel):
    path: str = ""
    bytes: int = 0
    content_type: Optional[str] = None
    duration: Optional[float] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    codec: Optional[str] = None
    format: Optional[str] = None


class NormalizedAudioMetadata(BaseModel):
    path: str = ""
    bytes: int = 0
    duration: Optional[float] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    codec: Optional[str] = None
    format: Optional[str] = None


class NormalizeRequest(BaseModel):
    source_path: str = Field(min_length=1, max_length=4096)
