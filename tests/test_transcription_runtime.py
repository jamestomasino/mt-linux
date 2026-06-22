from mt_linux.transcription.runtime import resolve_device


def test_resolve_device_prefers_cuda_when_auto(monkeypatch):
    monkeypatch.setattr("mt_linux.transcription.runtime.cuda_available", lambda: True)
    assert resolve_device("auto") == "cuda"
    assert resolve_device("") == "cuda"


def test_resolve_device_falls_back_to_cpu_when_auto_and_cuda_missing(monkeypatch):
    monkeypatch.setattr("mt_linux.transcription.runtime.cuda_available", lambda: False)
    assert resolve_device("auto") == "cpu"


def test_resolve_device_keeps_explicit_choice(monkeypatch):
    monkeypatch.setattr("mt_linux.transcription.runtime.cuda_available", lambda: True)
    assert resolve_device("cpu") == "cpu"
    assert resolve_device("cuda") == "cuda"
