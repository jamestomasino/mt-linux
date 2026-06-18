from datetime import UTC, datetime

from mt_linux.config import AppConfig
from mt_linux.models import CalendarEvent, MeetingInfo, SpeakerIdentity
from mt_linux.pipeline.job import JobStatus, PipelineJob
from mt_linux.tui import (
    DashboardState,
    DashboardStateLoad,
    build_sidebar_rows,
    filter_jobs_for_view,
    format_action_log,
    format_dashboard_banner,
    format_config_value,
    format_job_details,
    get_config_value,
    is_state_stale,
    load_dashboard_state,
)


def _job(
    tmp_path,
    session_id: str,
    *,
    status: JobStatus,
    title: str,
    with_candidates: bool = False,
    with_speaker_review: bool = False,
) -> PipelineJob:
    return PipelineJob(
        session_id=session_id,
        app_audio_path=tmp_path / f"{session_id}-app.wav",
        mic_audio_path=tmp_path / f"{session_id}-mic.wav",
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 11, 13, 0, tzinfo=UTC),
            title=title,
            calendar_candidates=[
                CalendarEvent(
                    event_id="event-1",
                    title="Weekly Sync",
                    start_time=datetime(2026, 6, 11, 13, 0, tzinfo=UTC),
                    end_time=datetime(2026, 6, 11, 13, 30, tzinfo=UTC),
                    conferencing_type="zoom",
                )
            ]
            if with_candidates
            else [],
            calendar_review_queued=with_candidates,
            calendar_match_confidence="ambiguous" if with_candidates else "matched",
        ),
        identities=[
            SpeakerIdentity(
                label="SPEAKER_00",
                name="Alice Smith",
                confidence="voice_profile",
                review_queued=with_speaker_review,
            )
        ],
        status=status,
        error="The read operation timed out" if status == JobStatus.FAILED else None,
    )


def test_tui_helpers_format_job_details_and_filters(tmp_path):
    config = AppConfig()
    config.output.folder = str(tmp_path)
    queue_job = _job(tmp_path, "session-queue", status=JobStatus.TRANSCRIBING, title="Queue Job")
    failed_job = _job(tmp_path, "session-failed", status=JobStatus.FAILED, title="Retry Me")
    meeting_job = _job(
        tmp_path,
        "session-meeting",
        status=JobStatus.COMPLETE,
        title="Match Me",
        with_candidates=True,
    )
    speaker_job = _job(
        tmp_path,
        "session-speaker",
        status=JobStatus.COMPLETE,
        title="Name Me",
        with_speaker_review=True,
    )
    recent_job = _job(tmp_path, "session-recent", status=JobStatus.COMPLETE, title="Done")
    state = DashboardState(
        active_job="session-queue",
        queue_depth=2,
        queued_jobs=("session-queue", "session-failed"),
        active_meeting_title="Live Meeting",
        active_meeting_app="zoom",
    )
    jobs = [recent_job, speaker_job, meeting_job, failed_job, queue_job]

    rendered = format_job_details(failed_job, config, state)

    assert "Retry Me" in rendered
    assert "Status: failed" in rendered
    assert "Error: The read operation timed out" in rendered
    assert "Queued Position: 2" in rendered
    assert get_config_value(config, "output.folder") == str(tmp_path)
    assert format_config_value(["zoom", "teams"]) == "zoom, teams"
    assert format_config_value(True) == "true"

    sidebar_rows = build_sidebar_rows(jobs, state)
    assert [(row.key, row.count) for row in sidebar_rows] == [
        ("queue", 2),
        ("failed", 1),
        ("meeting_review", 1),
        ("speaker_review", 1),
        ("recent", 3),
    ]

    assert [job.session_id for job in filter_jobs_for_view(jobs, state, "queue")] == [
        "session-queue",
        "session-failed",
    ]
    assert [job.session_id for job in filter_jobs_for_view(jobs, state, "failed")] == ["session-failed"]
    assert [job.session_id for job in filter_jobs_for_view(jobs, state, "meeting_review")] == ["session-meeting"]
    assert [job.session_id for job in filter_jobs_for_view(jobs, state, "speaker_review")] == ["session-speaker"]
    assert [job.session_id for job in filter_jobs_for_view(jobs, state, "recent")] == [
        "session-recent",
        "session-speaker",
        "session-meeting",
    ]


def test_tui_load_dashboard_state_reads_queue_fields(tmp_path):
    state_path = tmp_path / "daemon_state.json"
    state_path.write_text(
        """
{
  "active_job": "session-1",
  "queue_depth": 3,
  "queued_jobs": ["session-2", "session-3"],
  "active_meeting": {
    "title": "Current Meeting",
    "app": "zoom"
  }
}
""".strip(),
        encoding="utf-8",
    )

    loaded = load_dashboard_state(state_path)

    assert loaded.state.active_job == "session-1"
    assert loaded.state.queue_depth == 3
    assert loaded.state.queued_jobs == ("session-2", "session-3")
    assert loaded.state.active_meeting_title == "Current Meeting"
    assert loaded.state.active_meeting_app == "zoom"
    assert loaded.error == ""
    assert loaded.age_seconds is not None


def test_tui_stale_and_banner_helpers():
    load = DashboardStateLoad(
        state=DashboardState(active_job="session-1", queue_depth=1),
        age_seconds=20.0,
    )

    assert is_state_stale(load)
    assert format_action_log(["12:00:00 Retried session-1", "12:01:00 Canceled session-2"], compact=True).count("\n") == 1
    banner = format_dashboard_banner(
        compact=True,
        refreshed_at=datetime(2026, 6, 11, 16, 0, tzinfo=UTC),
        state_load=load,
        config_error="Config load failed: broken",
    )
    assert "compact" in banner
    assert "Config load failed: broken" in banner
