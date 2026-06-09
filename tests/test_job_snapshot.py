from datetime import UTC, datetime
from pathlib import Path

from mt_linux.diarization.diarizer import DiarizationSegment
from mt_linux.models import MeetingInfo, TranscriptSegment
from mt_linux.pipeline.job import JobStatus, PipelineJob
from mt_linux.pipeline.snapshot import JobSnapshotStore


def test_job_snapshot_round_trips_staged_outputs(tmp_path: Path):
    store = JobSnapshotStore(tmp_path / "jobs")
    job = PipelineJob(
        session_id="session-1",
        app_audio_path=tmp_path / "app.wav",
        mic_audio_path=tmp_path / "mic.wav",
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
            title="Catch-up",
        ),
        status=JobStatus.DIARIZED,
        transcript_segments=[TranscriptSegment(start=0.0, end=1.0, text="Hello", speaker="SPEAKER_00")],
        app_transcript_segments=[TranscriptSegment(start=0.0, end=1.0, text="Remote", speaker="SPEAKER_01", track="app")],
        mic_transcript_segments=[TranscriptSegment(start=0.5, end=1.5, text="Local", speaker="MIC_SPEAKER", track="mic")],
        diarization_segments=[DiarizationSegment(start=0.0, end=1.0, speaker="SPEAKER_01")],
        summary="Summary text",
    )
    store.save(job)

    restored = store.load_one("session-1")
    assert restored is not None
    assert restored.status == JobStatus.DIARIZED
    assert restored.transcript_segments is not None
    assert restored.transcript_segments[0].text == "Hello"
    assert restored.app_transcript_segments is not None
    assert restored.app_transcript_segments[0].track == "app"
    assert restored.mic_transcript_segments is not None
    assert restored.mic_transcript_segments[0].track == "mic"
    assert restored.diarization_segments is not None
    assert restored.diarization_segments[0].speaker == "SPEAKER_01"
    assert restored.summary == "Summary text"
