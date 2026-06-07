from pathlib import Path

from mt_linux.audio.commands import build_default_mic_record_command, build_source_record_command


def test_build_source_record_command_for_pw_record():
    command = build_source_record_command("pw-record", "mt-linux.monitor", Path("/tmp/app.wav"))
    assert command[:3] == ["pw-record", "--target", "mt-linux.monitor"]
    assert command[-1] == "/tmp/app.wav"


def test_build_default_mic_record_command_for_parecord():
    command = build_default_mic_record_command(
        "parecord",
        Path("/tmp/mic.wav"),
        device_name="alsa_input.usb",
    )
    assert "--device" in command
    assert "alsa_input.usb" in command
    assert command[-1] == "/tmp/mic.wav"
