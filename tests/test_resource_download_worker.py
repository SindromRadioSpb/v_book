"""Tests for resource download worker checksum behavior."""

import hashlib
from pathlib import Path

from app.ui.workers import ResourceDownloadWorker


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload
        self._offset = 0
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size: int) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_resources_manager_download_verifies_checksum(monkeypatch, tmp_path):
    payload = b"sample-resource-bytes"
    checksum = hashlib.sha256(payload).hexdigest()
    target = tmp_path / "resource.bin"
    finished = []
    errors = []

    def _fake_urlopen(_request, timeout=0):
        _ = timeout
        return _FakeResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    worker = ResourceDownloadWorker(
        resource_id="test_resource",
        url="https://example.invalid/resource.bin",
        dest_path=target,
        checksum=checksum,
    )
    worker.finished.connect(lambda data: finished.append(data))
    worker.error.connect(lambda msg: errors.append(msg))
    worker.run()

    assert not errors
    assert finished and finished[0]["ok"] is True
    assert target.exists()
    assert target.read_bytes() == payload


def test_resources_manager_download_checksum_mismatch(monkeypatch, tmp_path):
    payload = b"sample-resource-bytes"
    target = tmp_path / "resource.bin"
    finished = []
    errors = []

    def _fake_urlopen(_request, timeout=0):
        _ = timeout
        return _FakeResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    worker = ResourceDownloadWorker(
        resource_id="test_resource",
        url="https://example.invalid/resource.bin",
        dest_path=target,
        checksum="deadbeef",
    )
    worker.finished.connect(lambda data: finished.append(data))
    worker.error.connect(lambda msg: errors.append(msg))
    worker.run()

    assert not finished
    assert errors
    assert not target.exists()
