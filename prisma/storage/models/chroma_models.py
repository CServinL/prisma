"""Typed shape for ChromaService.status() -- surfaced on app.py's /status route."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ChromaStatus(BaseModel):
    chunks: int
    files_indexed: int
    model: str
    provider: str
    current_activity: Optional[str] = None
    embedding_model_mismatch: bool = False
