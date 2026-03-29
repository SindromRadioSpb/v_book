from __future__ import annotations

from app.infra.nlp_engines import stanza_subprocess_worker
from app.services.nlp_runtime import stanza_probe_worker


class _FakeStream:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def reconfigure(self, **kwargs):
        self.calls.append(dict(kwargs))


def test_stanza_subprocess_worker_forces_utf8_stdio(monkeypatch):
    fake_in = _FakeStream()
    fake_out = _FakeStream()
    fake_err = _FakeStream()

    monkeypatch.setattr(stanza_subprocess_worker.sys, "stdin", fake_in)
    monkeypatch.setattr(stanza_subprocess_worker.sys, "stdout", fake_out)
    monkeypatch.setattr(stanza_subprocess_worker.sys, "stderr", fake_err)

    stanza_subprocess_worker._configure_stdio_for_json_protocol()

    for stream in (fake_in, fake_out, fake_err):
        assert stream.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_stanza_probe_worker_forces_utf8_stdio(monkeypatch):
    fake_in = _FakeStream()
    fake_out = _FakeStream()
    fake_err = _FakeStream()

    monkeypatch.setattr(stanza_probe_worker.sys, "stdin", fake_in)
    monkeypatch.setattr(stanza_probe_worker.sys, "stdout", fake_out)
    monkeypatch.setattr(stanza_probe_worker.sys, "stderr", fake_err)

    stanza_probe_worker._configure_stdio_for_json_protocol()

    for stream in (fake_in, fake_out, fake_err):
        assert stream.calls == [{"encoding": "utf-8", "errors": "replace"}]
