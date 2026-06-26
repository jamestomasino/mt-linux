"""Tests for protocol context file injection."""
from datetime import UTC, datetime
from pathlib import Path

from mt_linux.config import ProtocolConfig
from mt_linux.models import MeetingInfo
from mt_linux.protocol.ollama_generator import OllamaProtocolGenerator


def test_load_context_returns_file_content(tmp_path: Path):
    context_path = tmp_path / "context.txt"
    context_path.write_text("We are a dev shop building internal tools.", encoding="utf-8")

    config = ProtocolConfig(context_file=str(context_path))
    gen = OllamaProtocolGenerator(config)

    content = gen._load_context()
    assert "We are a dev shop building internal tools." in content


def test_load_context_returns_empty_when_no_file_configured():
    config = ProtocolConfig(context_file="")
    gen = OllamaProtocolGenerator(config)

    assert gen._load_context() == ""


def test_load_context_returns_empty_when_file_missing(tmp_path: Path):
    config = ProtocolConfig(context_file=str(tmp_path / "missing.txt"))
    gen = OllamaProtocolGenerator(config)

    assert gen._load_context() == ""


def test_load_context_expands_user_path(tmp_path: Path, monkeypatch):
    context_path = tmp_path / "ctx.txt"
    context_path.write_text("home context", encoding="utf-8")
    # Fake ~ expansion to tmp_path
    monkeypatch.setattr(Path, "expanduser", lambda self: tmp_path / "ctx.txt")

    config = ProtocolConfig(context_file="~/ctx.txt")
    gen = OllamaProtocolGenerator(config)

    assert "home context" in gen._load_context()


def test_build_user_message_includes_context():
    meeting_info = MeetingInfo(
        app="teams",
        pid=1,
        detection_method="import",
        start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
        title="Standup",
    )
    transcript = "Alice: update"
    context = "Team of 5 engineers."

    msg = OllamaProtocolGenerator._build_user_message(meeting_info, transcript, context)
    assert "Meeting: Standup" in msg
    assert "## Background Context" in msg
    assert "Team of 5 engineers." in msg
    assert "## Transcript" in msg
    assert "Alice: update" in msg


def test_build_user_message_without_context():
    meeting_info = MeetingInfo(
        app="zoom",
        pid=1,
        detection_method="import",
        start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
        title="Call",
    )

    msg = OllamaProtocolGenerator._build_user_message(meeting_info, "hello", "")
    assert "Meeting: Call" in msg
    assert "## Background Context" not in msg
    assert "## Transcript" in msg


def test_build_user_message_multiline_context():
    meeting_info = MeetingInfo(
        app="zoom",
        pid=1,
        detection_method="import",
        start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
    )
    context = "Line 1\nLine 2\nLine 3"

    msg = OllamaProtocolGenerator._build_user_message(meeting_info, "transcript", context)
    assert "Line 1" in msg
    assert "Line 2" in msg
    assert "Line 3" in msg
