"""Unit tests for the shared bounded-upload-read helper -- both upload
routes in this codebase used to read an UploadFile's entire body in one
call before any size check ran (see TODO.md, now closed)."""
import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile

from prisma.server.upload_utils import read_upload_bounded, read_upload_bounded_async


def test_read_upload_bounded_accepts_a_file_under_the_cap():
    data = b"x" * 100
    upload = UploadFile(filename="small.bin", file=io.BytesIO(data))
    assert read_upload_bounded(upload, max_bytes=1024) == data


def test_read_upload_bounded_rejects_a_file_over_the_cap():
    data = b"x" * 2000
    upload = UploadFile(filename="big.bin", file=io.BytesIO(data))
    with pytest.raises(HTTPException) as exc:
        read_upload_bounded(upload, max_bytes=1024)
    assert exc.value.status_code == 413


def test_read_upload_bounded_rejects_before_buffering_the_whole_file():
    # Regression target: the bug this closes is buffering the ENTIRE body
    # before any check runs. Confirms the read stops (raises) partway
    # through a much-larger-than-cap stream, not after fully consuming it.
    class CountingStream(io.BytesIO):
        read_calls = 0

        def read(self, n=-1):
            CountingStream.read_calls += 1
            return super().read(n)

    data = b"x" * (10 * 1024 * 1024)  # 10MB
    upload = UploadFile(filename="huge.bin", file=CountingStream(data))
    with pytest.raises(HTTPException) as exc:
        read_upload_bounded(upload, max_bytes=1024 * 1024)  # 1MB cap
    assert exc.value.status_code == 413
    # 1MB cap / 1MB chunk size -- should reject on the second chunk, not
    # after reading all ~10 chunks the full file would take.
    assert CountingStream.read_calls <= 2


def test_read_upload_bounded_async_accepts_a_file_under_the_cap():
    data = b"x" * 100
    upload = UploadFile(filename="small.bin", file=io.BytesIO(data))
    result = asyncio.run(read_upload_bounded_async(upload, max_bytes=1024))
    assert result == data


def test_read_upload_bounded_async_rejects_a_file_over_the_cap():
    data = b"x" * 2000
    upload = UploadFile(filename="big.bin", file=io.BytesIO(data))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_upload_bounded_async(upload, max_bytes=1024))
    assert exc.value.status_code == 413
