from datetime import UTC, datetime
from pathlib import Path

from mt_linux.config import AppConfig
from mt_linux.models import MeetingInfo
from mt_linux.output.protocol_refresh import (
    extract_protocol_transcript,
    refresh_summary_from_transcript,
    replace_summary_section,
    sanitize_summary_placeholders,
)


def test_extract_protocol_transcript_preserves_speaker_names():
    content = """## Summary

Old summary

---

## Transcript

**13:50:12** [[Syd Bizovi]]: Hello there

**13:50:20** [[James Tomasino]]: Sounds good
"""
    transcript = extract_protocol_transcript(content)
    assert transcript == "[[Syd Bizovi]]: Hello there\n[[James Tomasino]]: Sounds good"


def test_replace_summary_section_updates_only_summary():
    content = """## Summary

Old summary

---

## Transcript

**13:50:12** [[Syd Bizovi]]: Hello there
"""
    updated = replace_summary_section(content, "New summary")
    assert "## Summary\n\nNew summary\n\n---\n" in updated
    assert "[[Syd Bizovi]]: Hello there" in updated


def test_refresh_summary_from_transcript_rewrites_note(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """## Summary

Old summary

---

## Transcript

**13:50:12** [[Syd Bizovi]]: Hello there

**13:50:20** [[James Tomasino]]: Sounds good
""",
        encoding="utf-8",
    )
    config = AppConfig()
    config.protocol.enabled = True
    entities = tmp_path / "entities.toml"
    entities.write_text(
        """
[clients."Abbott"]
aliases = ["abbott"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config.enrichment.enabled = True
    config.enrichment.entity_catalog_path = str(entities)
    meeting_info = MeetingInfo(
        app="manual",
        pid=0,
        detection_method="manual",
        start_time=datetime(2026, 6, 9, 13, 50, tzinfo=UTC),
        title="Ops Huddle",
    )

    def _fake_generate(self, prompt_text, meeting):
        assert "[[Syd Bizovi]]: Hello there" in prompt_text
        assert "[[James Tomasino]]: Sounds good" in prompt_text
        assert meeting.title == "Ops Huddle"
        return "Updated summary about Abbott"

    monkeypatch.setattr("mt_linux.output.protocol_refresh.OllamaProtocolGenerator.generate", _fake_generate)

    assert refresh_summary_from_transcript(transcript, config, meeting_info) is True
    content = transcript.read_text(encoding="utf-8")
    assert "Updated summary about [[Abbott]]" in content
    assert "Old summary" not in content


def test_sanitize_summary_placeholders_removes_placeholder_actor():
    summary = """**Action Items**

* [Name] will create the onboarding doc
* [Person] will add access
1. [TBD] will follow up
"""
    cleaned = sanitize_summary_placeholders(summary)
    assert "[Name]" not in cleaned
    assert "[Person]" not in cleaned
    assert "[TBD]" not in cleaned
    assert "* create the onboarding doc" in cleaned
