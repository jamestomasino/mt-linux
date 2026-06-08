import subprocess

import pytest

from mt_linux.audio.pulse import (
    get_default_sink_name,
    get_preferred_system_capture_source_name,
    get_system_capture_source_name,
)


def test_get_default_sink_name_reads_pactl_output(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout="bluez_output.AC_80_0A_14_01_9F.1\n",
            stderr="",
        ),
    )
    assert get_default_sink_name() == "bluez_output.AC_80_0A_14_01_9F.1"


def test_get_default_sink_name_raises_when_missing(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, stdout="", stderr="no sink"),
    )
    with pytest.raises(RuntimeError):
        get_default_sink_name()


def test_get_system_capture_source_name_prefers_explicit_source():
    assert get_system_capture_source_name("alsa_output.example.monitor") == "alsa_output.example.monitor"


def test_get_preferred_system_capture_source_name_uses_app_sink_when_found(monkeypatch):
    monkeypatch.setattr(
        "mt_linux.audio.pulse._pactl_json_list",
        lambda kind: (
            [
                {
                    "sink": 30919,
                    "properties": {
                        "application.process.id": "4242",
                    },
                }
            ]
            if kind == "sink-inputs"
            else [
                {
                    "index": 30919,
                    "properties": {"node.name": "bluez_output.AC_80_0A_14_01_9F.1"},
                }
            ]
        ),
    )
    assert (
        get_preferred_system_capture_source_name(4242)
        == "bluez_output.AC_80_0A_14_01_9F.1.monitor"
    )


def test_get_preferred_system_capture_source_name_falls_back_to_default_monitor(monkeypatch):
    monkeypatch.setattr("mt_linux.audio.pulse._pactl_json_list", lambda kind: [])
    monkeypatch.setattr("mt_linux.audio.pulse.get_system_capture_source_name", lambda: "@DEFAULT_MONITOR@")
    assert get_preferred_system_capture_source_name(4242, retries=1) == "@DEFAULT_MONITOR@"
