from pathlib import Path

from mt_linux.config import AppConfig
from mt_linux.models import CalendarEvent
from mt_linux.models import MeetingInfo
from datetime import UTC, datetime
from click.testing import CliRunner

from mt_linux.cli import cli
from mt_linux.models import ReviewEntry, SpeakerIdentity
from mt_linux.output.transcript_patch import (
    apply_meeting_assignment,
    clear_meeting_assignment,
    condense_transcript_turns,
    remove_speaker_label,
    replace_speaker_label,
)
from mt_linux.pipeline.review_queue import ReviewQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore
from mt_linux.pipeline.job import JobStatus, PipelineJob
from tests.helpers import write_test_wav


def test_replace_speaker_label_updates_transcript_and_frontmatter(tmp_path: Path):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
participants:
  - "[[SPEAKER_01]]"
participants_identified:
  - name: "SPEAKER_01"
    confidence: "unidentified"
    review_queued: true
---

**14:30:00** SPEAKER_01: Hello
""",
        encoding="utf-8",
    )
    replace_speaker_label(transcript, "SPEAKER_01", "Alice Smith")
    content = transcript.read_text(encoding="utf-8")
    assert "[[Alice Smith]]: Hello" in content
    assert 'name: "[[Alice Smith]]"' in content
    assert 'confidence: "voice_profile"' in content


def test_replace_speaker_label_dedupes_metadata_when_multiple_labels_map_to_same_person(tmp_path: Path):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
participants:
  - "[[SPEAKER_00]]"
  - "[[SPEAKER_01]]"
participants_identified:
  - name: "SPEAKER_00"
    confidence: "unidentified"
    review_queued: true
  - name: "SPEAKER_01"
    confidence: "unidentified"
    review_queued: true
---

## Participants

| Speaker | Identity | Confidence |
|---------|----------|------------|
| SPEAKER_00 | SPEAKER_00 | unidentified |
| SPEAKER_01 | SPEAKER_01 | unidentified |

---

## Transcript

**14:30:00** SPEAKER_00: Hello

**14:30:05** SPEAKER_01: Hi
""",
        encoding="utf-8",
    )
    replace_speaker_label(transcript, "SPEAKER_00", "Alice Smith")
    replace_speaker_label(transcript, "SPEAKER_01", "Alice Smith")
    content = transcript.read_text(encoding="utf-8")
    assert content.count('  - "[[Alice Smith]]"') == 1
    assert content.count('  - name: "[[Alice Smith]]"') == 1
    assert content.count("| [[Alice Smith]] | [[Alice Smith]] |") == 1


def test_remove_speaker_label_strips_transcript_and_metadata(tmp_path: Path):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
participants:
  - "[[SPEAKER_00]]"
  - "[[SPEAKER_01]]"
participants_identified:
  - name: "SPEAKER_00"
    confidence: "unidentified"
    review_queued: true
  - name: "SPEAKER_01"
    confidence: "unidentified"
    review_queued: true
---

## Participants

| Speaker | Identity | Confidence |
|---------|----------|------------|
| SPEAKER_00 | SPEAKER_00 | unidentified |
| SPEAKER_01 | SPEAKER_01 | unidentified |

---

## Transcript

**14:30:00** SPEAKER_00: static hum

**14:30:05** SPEAKER_01: Hello
""",
        encoding="utf-8",
    )
    remove_speaker_label(transcript, "SPEAKER_00")
    content = transcript.read_text(encoding="utf-8")
    assert '[[SPEAKER_00]]' not in content
    assert 'name: "SPEAKER_00"' not in content
    assert "| SPEAKER_00 |" not in content
    assert "SPEAKER_00: static hum" not in content
    assert "SPEAKER_01: Hello" in content


def test_apply_meeting_assignment_updates_calendar_frontmatter(tmp_path: Path):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
title: "Old Title"
duration_minutes: 10
organizer: ""
calendar_event_id: ""
calendar_match_confidence: "ambiguous"
calendar_review_queued: true
calendar_candidate_event_ids:
  - ""
calendar_attendees:
  - ""
calendar_candidates:
  - id: ""
---
""",
        encoding="utf-8",
    )
    apply_meeting_assignment(
        transcript,
        selected_event=CalendarEvent(
            event_id="event-1",
            title="Weekly Standup",
            start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
            end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
            organizer="Alice Smith",
            attendees=[],
            conferencing_type="zoom",
            response_status="accepted",
        ),
        candidates=[
            CalendarEvent(
                event_id="event-1",
                title="Weekly Standup",
                start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                organizer="Alice Smith",
                attendees=[],
                conferencing_type="zoom",
                response_status="accepted",
            ),
            CalendarEvent(
                event_id="event-2",
                title="Other Meeting",
                start_time=datetime(2026, 6, 7, 14, 31, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                organizer="Bob Jones",
                attendees=[],
                conferencing_type="zoom",
                response_status="tentative",
            )
        ],
        ambiguous=False,
    )
    content = transcript.read_text(encoding="utf-8")
    assert 'calendar_event_id: "event-1"' in content
    assert 'calendar_review_queued: false' in content
    assert 'title: "Weekly Standup"' in content
    assert "duration_minutes: 30" in content
    assert '  - "event-1"' in content
    assert '  - "event-2"' not in content
    assert 'title: "Other Meeting"' not in content


def test_clear_meeting_assignment_marks_transcript_external(tmp_path: Path):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
title: "Wrong Calendar Meeting"
duration_minutes: 45
organizer: "[[Alice Smith]]"
calendar_event_id: "event-1"
calendar_match_confidence: "ambiguous"
calendar_review_queued: true
calendar_candidate_event_ids:
  - "event-1"
calendar_attendees:
  - "Alice Smith <alice@example.com>"
calendar_candidates:
  - id: "event-1"
    title: "Weekly Standup"
    conferencing: "zoom"
    response_status: "accepted"
---
""",
        encoding="utf-8",
    )
    clear_meeting_assignment(
        transcript,
        candidates=[
            CalendarEvent(
                event_id="event-1",
                title="Weekly Standup",
                start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                conferencing_type="zoom",
                response_status="accepted",
            )
        ],
    )
    content = transcript.read_text(encoding="utf-8")
    assert 'calendar_event_id: ""' in content
    assert 'calendar_match_confidence: "external"' in content
    assert 'calendar_review_queued: false' in content
    assert 'organizer: ""' in content
    assert 'title: "Ad Hoc Meeting"' in content
    assert "duration_minutes: 0" in content


def test_condense_transcript_turns_merges_adjacent_same_speaker_blocks(tmp_path: Path):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
title: "Meeting"
---

## Transcript

**14:30:00** [[Alice Smith]]: Hello

**14:30:05** [[Alice Smith]]: there

**14:30:10** [[Bob Jones]]: Hi

**14:30:15** [[Bob Jones]]: back

---
""",
        encoding="utf-8",
    )
    condense_transcript_turns(transcript)
    content = transcript.read_text(encoding="utf-8")
    assert "**14:30:00** [[Alice Smith]]: Hello there" in content
    assert "**14:30:10** [[Bob Jones]]: Hi back" in content
    assert content.count("**14:30:") == 2


def test_review_run_refreshes_summary_for_changed_session(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
title: "Meeting"
---

## Summary

Old summary

---

## Transcript

**14:30:00** SPEAKER_01: Hello there
""",
        encoding="utf-8",
    )
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"wav")
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queue.add(
        ReviewEntry(
            session_id="session-1",
            speaker_label="SPEAKER_01",
            sample_path=sample,
            calendar_attendees=[],
            meeting_title="Meeting",
            meeting_date=datetime(2026, 6, 9).date(),
            transcript_path=transcript,
        )
    )
    refreshed: list[str] = []
    monkeypatch.setattr("mt_linux.cli.ReviewQueue", lambda: queue)
    monkeypatch.setattr("mt_linux.cli._play_sample", lambda _path: None)
    monkeypatch.setattr(
        "mt_linux.cli._refresh_job_summary",
        lambda _store, _config, session_id: refreshed.append(session_id) or True,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["review", "run"], input="Alice Smith\n", env={})
    assert result.exit_code == 0
    assert refreshed == ["session-1"]


def test_review_run_can_remove_noise_entry(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
title: "Meeting"
participants:
  - "[[SPEAKER_01]]"
participants_identified:
  - name: "SPEAKER_01"
    confidence: "unidentified"
    review_queued: true
---

## Summary

Old summary

---

## Participants

| Speaker | Identity | Confidence |
|---------|----------|------------|
| SPEAKER_01 | SPEAKER_01 | unidentified |

---

## Transcript

**14:30:00** SPEAKER_01: hiss
""",
        encoding="utf-8",
    )
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"wav")
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queue.add(
        ReviewEntry(
            session_id="session-1",
            speaker_label="SPEAKER_01",
            sample_path=sample,
            calendar_attendees=[],
            meeting_title="Meeting",
            meeting_date=datetime(2026, 6, 9).date(),
            transcript_path=transcript,
        )
    )
    refreshed: list[str] = []
    monkeypatch.setattr("mt_linux.cli.ReviewQueue", lambda: queue)
    monkeypatch.setattr("mt_linux.cli._play_sample", lambda _path: None)
    monkeypatch.setattr(
        "mt_linux.cli._refresh_job_summary",
        lambda _store, _config, session_id: refreshed.append(session_id) or True,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["review", "run"], input="x\n", env={})
    assert result.exit_code == 0
    assert "Removed SPEAKER_01 as noise" in result.output
    assert refreshed == ["session-1"]
    content = transcript.read_text(encoding="utf-8")
    assert "SPEAKER_01: hiss" not in content


def test_review_run_refreshes_summary_by_transcript_path_when_job_missing(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
title: "Meeting"
---

## Summary

Old summary

---

## Transcript

**14:30:00** SPEAKER_01: Hello there
""",
        encoding="utf-8",
    )
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"wav")
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queue.add(
        ReviewEntry(
            session_id="session-missing",
            speaker_label="SPEAKER_01",
            sample_path=sample,
            calendar_attendees=[],
            meeting_title="Meeting",
            meeting_date=datetime(2026, 6, 9).date(),
            transcript_path=transcript,
        )
    )
    refreshed_paths: list[Path] = []
    monkeypatch.setattr("mt_linux.cli.ReviewQueue", lambda: queue)
    monkeypatch.setattr("mt_linux.cli._play_sample", lambda _path: None)
    monkeypatch.setattr("mt_linux.cli._refresh_job_summary", lambda _store, _config, _session_id: False)
    monkeypatch.setattr(
        "mt_linux.cli._refresh_summary_for_path",
        lambda path, _config, title: refreshed_paths.append(path) or True,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["review", "run"], input="Alice Smith\n", env={})
    assert result.exit_code == 0
    assert refreshed_paths == [transcript]


def test_review_run_uses_current_job_transcript_path_when_queue_path_is_stale(tmp_path: Path, monkeypatch):
    class FakePlayback:
        stopped = False

        def poll(self):
            return None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout=None):
            return 0

    playback = FakePlayback()
    stale_transcript = tmp_path / "old-name.md"
    current_transcript = tmp_path / "2026-06-09_14-30_meeting.md"
    current_transcript.write_text(
        """---
title: "Meeting"
participants:
  - "[[SPEAKER_01]]"
participants_identified:
  - name: "SPEAKER_01"
    confidence: "unidentified"
    review_queued: true
---

## Summary

Old summary

---

## Participants

| Speaker | Identity | Confidence |
|---------|----------|------------|
| SPEAKER_01 | SPEAKER_01 | unidentified |

---

## Transcript

**14:30:00** SPEAKER_01: Hello there
""",
        encoding="utf-8",
    )
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"wav")
    store = JobSnapshotStore(tmp_path / "jobs")
    job = PipelineJob(
        session_id="session-1",
        app_audio_path=tmp_path / "app.wav",
        mic_audio_path=tmp_path / "mic.wav",
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 9, 14, 30),
            title="Meeting",
        ),
        identities=[
            SpeakerIdentity(
                label="SPEAKER_01",
                name="SPEAKER_01",
                confidence="unidentified",
                review_queued=True,
            )
        ],
        status=JobStatus.COMPLETE,
    )
    store.save(job)
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queue.add(
        ReviewEntry(
            session_id="session-1",
            speaker_label="SPEAKER_01",
            sample_path=sample,
            calendar_attendees=[],
            meeting_title=None,
            meeting_date=datetime(2026, 6, 9).date(),
            transcript_path=stale_transcript,
        )
    )
    cfg = AppConfig()
    cfg.output.folder = str(tmp_path)
    refreshed: list[str] = []
    monkeypatch.setattr("mt_linux.cli.ReviewQueue", lambda: queue)
    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: cfg)
    monkeypatch.setattr("mt_linux.cli._play_sample", lambda _path: playback)
    monkeypatch.setattr(
        "mt_linux.cli._refresh_job_summary",
        lambda _store, _config, session_id: refreshed.append(session_id) or True,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["review", "run"], input="Alice Smith\n", env={})
    assert result.exit_code == 0
    assert "Meeting: Meeting (2026-06-09 14:30)" in result.output
    assert playback.stopped is True
    assert "Identified as Alice Smith" in result.output
    assert refreshed == ["session-1"]
    content = current_transcript.read_text(encoding="utf-8")
    assert "[[Alice Smith]]" in content
    updated = store.load_one("session-1")
    assert updated is not None
    assert updated.identities is not None
    assert updated.identities[0].name == "Alice Smith"
    assert updated.identities[0].confidence == "voice_profile"
    assert updated.identities[0].review_queued is False


def test_review_run_deletes_recorded_audio_after_last_speaker_is_resolved(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "2026-06-09_14-30_meeting.md"
    transcript.write_text(
        """---
title: "Meeting"
participants:
  - "[[SPEAKER_01]]"
participants_identified:
  - name: "SPEAKER_01"
    confidence: "unidentified"
    review_queued: true
---

## Summary

Old summary

---

## Transcript

**14:30:00** SPEAKER_01: Hello there
""",
        encoding="utf-8",
    )
    app_audio = write_test_wav(tmp_path / "audio" / "session-1_app.wav", seconds=1)
    mic_audio = write_test_wav(tmp_path / "audio" / "session-1_mic.wav", seconds=1)
    mixed_audio = tmp_path / "audio" / "session-1_mix.wav"
    write_test_wav(mixed_audio, seconds=1)
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"wav")
    store = JobSnapshotStore(tmp_path / "jobs")
    job = PipelineJob(
        session_id="session-1",
        app_audio_path=app_audio,
        mic_audio_path=mic_audio,
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 9, 14, 30),
            title="Meeting",
        ),
        identities=[
            SpeakerIdentity(
                label="SPEAKER_01",
                name="SPEAKER_01",
                confidence="unidentified",
                review_queued=True,
            )
        ],
        status=JobStatus.COMPLETE,
        summary="Old summary",
    )
    store.save(job)
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queue.add(
        ReviewEntry(
            session_id="session-1",
            speaker_label="SPEAKER_01",
            sample_path=sample,
            calendar_attendees=[],
            meeting_title="Meeting",
            meeting_date=datetime(2026, 6, 9).date(),
            transcript_path=transcript,
        )
    )
    cfg = AppConfig()
    cfg.output.folder = str(tmp_path)
    cfg.output.keep_audio = False
    monkeypatch.setattr("mt_linux.cli.ReviewQueue", lambda: queue)
    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: cfg)
    monkeypatch.setattr("mt_linux.cli._play_sample", lambda _path: None)
    monkeypatch.setattr("mt_linux.cli._refresh_job_summary", lambda *_args, **_kwargs: True)
    runner = CliRunner()
    result = runner.invoke(cli, ["review", "run"], input="Alice Smith\n", env={})
    assert result.exit_code == 0
    assert "Identified as Alice Smith" in result.output
    assert not app_audio.exists()
    assert not mic_audio.exists()
    assert not mixed_audio.exists()


def test_review_run_updates_speaker_profile_from_confirmed_review(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
title: "Meeting"
---

## Transcript

**14:30:00** SPEAKER_01: Hello there
""",
        encoding="utf-8",
    )
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"wav")
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queue.add(
        ReviewEntry(
            session_id="session-1",
            speaker_label="SPEAKER_01",
            sample_path=sample,
            calendar_attendees=[],
            meeting_title="Meeting",
            meeting_date=datetime(2026, 6, 9).date(),
            transcript_path=transcript,
        )
    )
    cfg = AppConfig()
    cfg.speakers.db_path = str(tmp_path / "speakers.json")
    profile_updates: list[tuple[str, object]] = []

    class _FakeMatcher:
        def __init__(self, db_path, similarity_threshold):
            self.db_path = db_path
            self.similarity_threshold = similarity_threshold

        def embed_wav(self, wav_path):
            assert wav_path == sample
            return [1.0, 0.0]

        def update_profile(self, name, embedding):
            profile_updates.append((name, embedding))

    monkeypatch.setattr("mt_linux.cli.ReviewQueue", lambda: queue)
    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: cfg)
    monkeypatch.setattr("mt_linux.cli.SpeakerMatcher", _FakeMatcher)
    monkeypatch.setattr("mt_linux.cli._play_sample", lambda _path: None)
    monkeypatch.setattr("mt_linux.cli._refresh_job_summary", lambda *_args, **_kwargs: True)
    runner = CliRunner()
    result = runner.invoke(cli, ["review", "run"], input="Alice Smith\n", env={})
    assert result.exit_code == 0
    assert "Identified as Alice Smith" in result.output
    assert profile_updates == [("Alice Smith", [1.0, 0.0])]


def test_review_run_warns_when_transcript_is_missing(tmp_path: Path, monkeypatch):
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"wav")
    store = JobSnapshotStore(tmp_path / "jobs")
    job = PipelineJob(
        session_id="session-1",
        app_audio_path=tmp_path / "app.wav",
        mic_audio_path=tmp_path / "mic.wav",
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 9, 14, 30),
            title="Meeting",
        ),
        identities=[
            SpeakerIdentity(
                label="SPEAKER_01",
                name="SPEAKER_01",
                confidence="unidentified",
                review_queued=True,
            )
        ],
        status=JobStatus.COMPLETE,
    )
    store.save(job)
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queue.add(
        ReviewEntry(
            session_id="session-1",
            speaker_label="SPEAKER_01",
            sample_path=sample,
            calendar_attendees=[],
            meeting_title="Meeting",
            meeting_date=datetime(2026, 6, 9).date(),
            transcript_path=tmp_path / "missing.md",
        )
    )
    refreshed_paths: list[Path] = []
    monkeypatch.setattr("mt_linux.cli.ReviewQueue", lambda: queue)
    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    monkeypatch.setattr("mt_linux.cli._play_sample", lambda _path: None)
    monkeypatch.setattr("mt_linux.cli._refresh_job_summary", lambda _store, _config, _session_id: False)
    monkeypatch.setattr(
        "mt_linux.cli._refresh_summary_for_path",
        lambda path, _config, _title: refreshed_paths.append(path) or False,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["review", "run"], input="Helene Golombek\n", env={})
    assert result.exit_code == 0
    assert "transcript missing; skipped note update" in result.output
    assert "Warning: transcript not found at" in result.output
    updated = store.load_one("session-1")
    assert updated is not None
    assert updated.identities is not None
    assert updated.identities[0].name == "Helene Golombek"
    assert updated.identities[0].confidence == "voice_profile"
    assert updated.identities[0].review_queued is False
    assert queue.load() == []
    assert refreshed_paths == [tmp_path / "missing.md"]


def test_refresh_summary_for_job_appends_history(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
title: "Meeting"
---

## Summary

Updated summary

---

## Transcript

**14:30:00** Alice Smith: Hello there
""",
        encoding="utf-8",
    )
    store = JobSnapshotStore(tmp_path / "jobs")
    job = PipelineJob(
        session_id="session-1",
        app_audio_path=tmp_path / "app.wav",
        mic_audio_path=tmp_path / "mic.wav",
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 9),
            title="Meeting",
        ),
        status=JobStatus.COMPLETE,
    )
    store.save(job)
    monkeypatch.setattr("mt_linux.cli.refresh_summary_from_transcript", lambda *_args, **_kwargs: True)
    from mt_linux.cli import _refresh_summary_for_job

    assert _refresh_summary_for_job(store, job, transcript, AppConfig()) is True
    reloaded = store.load_one("session-1")
    assert reloaded is not None
    messages = [event.message for event in reloaded.history]
    assert "Summary refresh requested after speaker review" in messages
    assert "Summary refreshed after speaker review" in messages
