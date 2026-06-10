from datetime import datetime, timedelta
from pathlib import Path

from mt_linux.config import AppConfig
from mt_linux.enrichment.models import ActionItem, NoteEnrichment
from mt_linux.models import Attendee, CalendarEvent, MeetingInfo, SpeakerIdentity, TranscriptSegment
from mt_linux.output.markdown import render_meeting_markdown
from mt_linux.pipeline.job import PipelineJob


def test_render_meeting_markdown_contains_frontmatter_and_transcript(tmp_path: Path):
    config = AppConfig()
    config.output.folder = str(tmp_path)
    config.speakers.mic_speaker_name = "James Tomasino"
    meeting_info = MeetingInfo(
        app="zoom",
        pid=1,
        detection_method="import",
        start_time=datetime(2026, 6, 7, 14, 30),
        title="Weekly Standup",
        calendar_event=CalendarEvent(
            event_id="abc123",
            title="Weekly Standup",
            start_time=datetime(2026, 6, 7, 14, 30),
            end_time=datetime(2026, 6, 7, 15, 0),
            organizer="Alice Smith",
            attendees=[Attendee(name="Alice Smith", email="alice@example.com")],
        ),
    )
    job = PipelineJob(
        session_id="session-1",
        app_audio_path=tmp_path / "app.wav",
        mic_audio_path=tmp_path / "mic.wav",
        meeting_info=meeting_info,
    )
    rendered = render_meeting_markdown(
        job,
        config,
        transcript_segments=[TranscriptSegment(start=5, end=7, text="Hello there", speaker="SPEAKER_00")],
        identities=[SpeakerIdentity(label="SPEAKER_00", name="James Tomasino", confidence="mic_track")],
        summary="Short summary",
    )
    assert 'title: "Weekly Standup"' in rendered.content
    assert "[[James Tomasino]]" in rendered.content
    assert "**14:30:05**" in rendered.content


def test_render_meeting_markdown_merges_consecutive_segments_from_same_speaker(tmp_path: Path):
    config = AppConfig()
    config.output.folder = str(tmp_path)
    meeting_info = MeetingInfo(
        app="zoom",
        pid=1,
        detection_method="import",
        start_time=datetime(2026, 6, 7, 14, 30),
        title="Weekly Standup",
    )
    job = PipelineJob(
        session_id="session-2",
        app_audio_path=tmp_path / "app.wav",
        mic_audio_path=tmp_path / "mic.wav",
        meeting_info=meeting_info,
    )
    rendered = render_meeting_markdown(
        job,
        config,
        transcript_segments=[
            TranscriptSegment(start=5, end=7, text="Hello", speaker="SPEAKER_00"),
            TranscriptSegment(start=7, end=9, text="there again", speaker="SPEAKER_00"),
            TranscriptSegment(start=9, end=11, text="Reply", speaker="SPEAKER_01"),
        ],
        identities=[
            SpeakerIdentity(label="SPEAKER_00", name="James Tomasino", confidence="mic_track"),
            SpeakerIdentity(label="SPEAKER_01", name="Alice Smith", confidence="voice_profile"),
        ],
        summary="Short summary",
    )
    assert "**14:30:05** [[James Tomasino]]: Hello there again" in rendered.content
    assert rendered.content.count("[[James Tomasino]]:") == 1
    assert "**14:30:09** [[Alice Smith]]: Reply" in rendered.content


def test_render_meeting_markdown_includes_enrichment_sections_and_frontmatter(tmp_path: Path):
    config = AppConfig()
    config.output.folder = str(tmp_path)
    entities = tmp_path / "entities.toml"
    entities.write_text(
        """
[projects."P10 Operations"]
aliases = ["p10 operations"]

[brands."Paratek / TYMLOS"]
aliases = ["tymlos"]
clients = ["Paratek"]

[clients."Abbott"]
aliases = ["abbott"]

[clients."Paratek"]
aliases = ["paratek"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config.enrichment.entity_catalog_path = str(entities)
    meeting_info = MeetingInfo(
        app="zoom",
        pid=1,
        detection_method="import",
        start_time=datetime(2026, 6, 7, 14, 30),
        title="Weekly Standup",
    )
    job = PipelineJob(
        session_id="session-3",
        app_audio_path=tmp_path / "app.wav",
        mic_audio_path=tmp_path / "mic.wav",
        meeting_info=meeting_info,
    )
    enrichment = NoteEnrichment(
        key_points=["Discussion of Abbott permissions"],
        decisions=["Add Ava and Brenda to the top-level share"],
        action_items=[ActionItem(owner="James Tomasino", text="update the onboarding doc")],
        open_questions=["Can Mike review the current access rules?"],
        links_mentioned=["https://example.com/doc"],
        related_projects=["P10 Operations"],
        related_brands=["Paratek / TYMLOS"],
        related_clients=["Abbott"],
        tags=["abbott", "permissions"],
    )
    rendered = render_meeting_markdown(
        job,
        config,
        transcript_segments=[TranscriptSegment(start=5, end=7, text="Hello there", speaker="SPEAKER_00")],
        identities=[SpeakerIdentity(label="SPEAKER_00", name="James Tomasino", confidence="mic_track")],
        summary="Short summary about Tymlos",
        enrichment=enrichment,
    )
    assert 'session_id: "session-3"' in rendered.content
    assert 'related_projects:\n  - "P10 Operations"' in rendered.content
    assert 'related_brands:\n  - "Paratek / TYMLOS"' in rendered.content
    assert 'related_clients:\n  - "Abbott"' in rendered.content
    assert "## Key Points" in rendered.content
    assert "Short summary about [[Paratek / TYMLOS]]" in rendered.content
    assert "- Discussion of [[Abbott]] permissions" in rendered.content
    assert "## Open Questions" in rendered.content
    assert "- Can Mike review the current access rules?" in rendered.content
