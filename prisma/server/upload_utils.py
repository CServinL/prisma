"""Shared file-upload guard.

Reads an `UploadFile`'s body in bounded chunks and rejects mid-stream the
moment a size cap is exceeded, instead of buffering the whole body first.
`Content-Length` alone isn't trusted as the guard: it can be missing or
wrong under chunked transfer encoding, so this counts real bytes read.
"""
from __future__ import annotations

from fastapi import HTTPException, UploadFile

# 50MB -- generous for a PDF companion or a chat attachment (the two
# current callers), nowhere near what would risk pressuring the process.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_CHUNK_SIZE = 1024 * 1024


def _too_large(max_bytes: int) -> HTTPException:
    return HTTPException(status_code=413, detail=f"file too large (max {max_bytes} bytes)")


def read_upload_bounded(file: UploadFile, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """Synchronous read via `file.file` (the underlying SpooledTemporaryFile)
    -- for sync `def` routes that can't `await`. See notes_routes.py's
    upload_source_companion() for why that route is deliberately sync."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = file.file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise _too_large(max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)


async def read_upload_bounded_async(file: UploadFile, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """Async counterpart for `async def` routes that do no CPU-bound work
    of their own (e.g. app.py's upload_chat_attachment())."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise _too_large(max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)
