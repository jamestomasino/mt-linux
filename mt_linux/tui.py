from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mt_linux.config import AppConfig
from mt_linux.models import CalendarEvent
from mt_linux.output.markdown import output_path_for
from mt_linux.output.transcript_patch import apply_meeting_assignment, clear_meeting_assignment
from mt_linux.paths import STATE_FILE
from mt_linux.pipeline.job import JobStatus, PipelineJob
from mt_linux.pipeline.job_admin import remove_job, retry_job
from mt_linux.pipeline.meeting_review_queue import MeetingReviewQueue
from mt_linux.pipeline.review_queue import ReviewQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore


@dataclass(frozen=True)
class SettingField:
    key: str
    label: str
    help_text: str


@dataclass(frozen=True)
class SidebarSection:
    key: str
    label: str
    help_text: str


@dataclass(frozen=True)
class SidebarRow:
    key: str
    label: str
    count: int
    help_text: str


@dataclass(frozen=True)
class DashboardState:
    active_job: str = ""
    queue_depth: int = 0
    queued_jobs: tuple[str, ...] = ()
    active_meeting_title: str = ""
    active_meeting_app: str = ""


@dataclass(frozen=True)
class DashboardStateLoad:
    state: DashboardState
    error: str = ""
    age_seconds: float | None = None


SETTINGS_FIELDS = [
    SettingField("calendar.lookup_window_minutes", "Lookup Window", "Calendar lookup window in minutes."),
    SettingField("protocol.enabled", "Protocol Generation", "Enable or disable protocol summary generation."),
    SettingField("openai.enabled", "OpenAI Matching", "Use OpenAI to refine calendar matches."),
    SettingField("enrichment.enabled", "Note Enrichment", "Generate follow-on note enrichment sections."),
    SettingField("output.keep_audio", "Keep Audio", "Keep captured WAV files after processing."),
    SettingField("transcription.language", "Transcription Language", "Language hint passed to transcription."),
    SettingField("transcription.model", "Transcription Model", "Whisper model to use for transcription."),
    SettingField("speakers.mic_speaker_name", "Mic Speaker Name", "Preferred display name for the local microphone."),
    SettingField("detection.apps_to_watch", "Apps To Watch", "Comma-separated app/process names to detect."),
    SettingField("output.folder", "Output Folder", "Directory for generated meeting notes."),
]


SIDEBAR_SECTIONS = [
    SidebarSection("queue", "Live Queue", "Daemon-backed live queue order and active processing context."),
    SidebarSection("failed", "Failed", "Jobs that need manual attention or retry."),
    SidebarSection("meeting_review", "Meeting Review", "Jobs with ambiguous or pending calendar matching."),
    SidebarSection("speaker_review", "Speaker Review", "Jobs with unresolved speaker identities."),
    SidebarSection("recent", "Recent Completed", "Most recent finished jobs for context and follow-up actions."),
]


def load_dashboard_jobs(store: JobSnapshotStore) -> list[PipelineJob]:
    return sorted(store.load_all(), key=lambda item: item.created_at, reverse=True)


def load_dashboard_state(path: Path = STATE_FILE) -> DashboardStateLoad:
    if not path.exists():
        return DashboardStateLoad(state=DashboardState(), error="Daemon state file not found.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return DashboardStateLoad(state=DashboardState(), error=f"Failed to read daemon state: {exc}")
    active_meeting = data.get("active_meeting") or {}
    queued_jobs = tuple(
        item for item in data.get("queued_jobs", []) if isinstance(item, str) and item
    )
    age_seconds = None
    try:
        age_seconds = max(datetime.now(UTC).timestamp() - path.stat().st_mtime, 0.0)
    except OSError:
        age_seconds = None
    return DashboardStateLoad(
        state=DashboardState(
            active_job=str(data.get("active_job") or ""),
            queue_depth=int(data.get("queue_depth") or 0),
            queued_jobs=queued_jobs,
            active_meeting_title=str(active_meeting.get("title") or ""),
            active_meeting_app=str(active_meeting.get("app") or ""),
        ),
        age_seconds=age_seconds,
    )


def job_needs_speaker_review(job: PipelineJob) -> bool:
    return any(identity.review_queued for identity in (job.identities or []))


def job_needs_meeting_review(job: PipelineJob) -> bool:
    info = job.meeting_info
    return bool(info.calendar_review_queued or info.calendar_candidates)


def build_sidebar_rows(jobs: list[PipelineJob], state: DashboardState) -> list[SidebarRow]:
    failed = [job for job in jobs if job.status == JobStatus.FAILED]
    meeting_review = [job for job in jobs if job_needs_meeting_review(job)]
    speaker_review = [job for job in jobs if job_needs_speaker_review(job)]
    completed = [job for job in jobs if job.status == JobStatus.COMPLETE][:15]
    return [
        SidebarRow(
            "queue",
            "Live Queue",
            state.queue_depth,
            (
                f"Active job: {state.active_job or 'none'} | "
                f"Active meeting: {state.active_meeting_title or state.active_meeting_app or 'none'}"
            ),
        ),
        SidebarRow("failed", "Failed", len(failed), "Retry or inspect failed jobs."),
        SidebarRow(
            "meeting_review",
            "Meeting Review",
            len(meeting_review),
            "Assign the correct calendar event or mark as ad hoc.",
        ),
        SidebarRow(
            "speaker_review",
            "Speaker Review",
            len(speaker_review),
            "Jobs with unresolved speakers still queued for review.",
        ),
        SidebarRow("recent", "Recent Completed", len(completed), "Longer-term history and post-processing context."),
    ]


def filter_jobs_for_view(jobs: list[PipelineJob], state: DashboardState, view_key: str) -> list[PipelineJob]:
    if view_key == "queue":
        by_id = {job.session_id: job for job in jobs}
        ordered = [by_id[session_id] for session_id in state.queued_jobs if session_id in by_id]
        if state.active_job and state.active_job in by_id and by_id[state.active_job] not in ordered:
            ordered.insert(0, by_id[state.active_job])
        return ordered
    if view_key == "failed":
        return [job for job in jobs if job.status == JobStatus.FAILED]
    if view_key == "meeting_review":
        return [job for job in jobs if job_needs_meeting_review(job)]
    if view_key == "speaker_review":
        return [job for job in jobs if job_needs_speaker_review(job)]
    if view_key == "recent":
        return [job for job in jobs if job.status == JobStatus.COMPLETE][:15]
    return jobs


def get_config_value(config: AppConfig, dotted_key: str) -> Any:
    target: Any = config
    for part in dotted_key.split("."):
        target = getattr(target, part)
    return target


def format_config_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def format_job_details(job: PipelineJob, config: AppConfig, state: DashboardState | None = None) -> str:
    return format_job_details_for_mode(job, config, state=state, compact=False)


def format_job_details_for_mode(
    job: PipelineJob,
    config: AppConfig,
    *,
    state: DashboardState | None = None,
    compact: bool,
) -> str:
    transcript_path = output_path_for(job, config)
    info = job.meeting_info
    event = info.calendar_event
    lines = [
        f"Title: {info.title or info.app}",
        f"Session: {job.session_id}",
        f"Status: {job.status.value}",
        f"App: {info.app}",
        f"Start: {info.start_time.isoformat()}",
        f"Transcript: {transcript_path}",
        f"Calendar Match: {info.calendar_match_confidence}",
        f"Candidates: {len(info.calendar_candidates)}",
    ]
    if state is not None:
        lines.extend(
            [
                f"Queue Active: {'yes' if state.active_job == job.session_id else 'no'}",
                f"Queued Position: {queued_position(state, job.session_id)}",
            ]
        )
    if compact:
        if job.error:
            lines.append(f"Error: {job.error}")
        if info.calendar_candidates:
            lines.append(f"Candidate Titles: {', '.join(candidate.title for candidate in info.calendar_candidates[:3])}")
        if job.history:
            entry = job.history[-1]
            lines.append(f"Last Event: [{entry.status}] {entry.message}")
        return "\n".join(lines)
    if job.error:
        lines.extend(["", f"Error: {job.error}"])
    if event is not None:
        lines.extend(
            [
                "",
                "Matched Event:",
                f"  {event.title}",
                f"  {event.start_time.isoformat()} -> {event.end_time.isoformat()}",
                f"  Organizer: {event.organizer or 'unknown'}",
            ]
        )
    if info.calendar_candidates:
        lines.extend(["", "Calendar Candidates:"])
        for candidate in info.calendar_candidates[:8]:
            lines.append(
                f"  - {candidate.title} [{candidate.conferencing_type or 'unknown'}] "
                f"{candidate.start_time.isoformat()}"
            )
    if job.identities:
        lines.extend(["", "Speakers:"])
        for identity in job.identities[:8]:
            queue_flag = " pending-review" if identity.review_queued else ""
            lines.append(f"  - {identity.label}: {identity.name} ({identity.confidence}){queue_flag}")
    if job.history:
        lines.extend(["", "Recent History:"])
        for entry in job.history[-8:]:
            lines.append(f"  - {entry.at.isoformat()} [{entry.status}] {entry.message}")
    return "\n".join(lines)


def queued_position(state: DashboardState, session_id: str) -> str:
    if state.active_job == session_id:
        return "active"
    if session_id in state.queued_jobs:
        return str(state.queued_jobs.index(session_id) + 1)
    return "-"


def format_queue_summary(state: DashboardState) -> str:
    queued = ", ".join(state.queued_jobs[:8]) or "empty"
    return (
        f"Active Meeting: {state.active_meeting_title or state.active_meeting_app or 'none'}\n"
        f"Active Job: {state.active_job or 'none'}\n"
        f"Queue Depth: {state.queue_depth}\n"
        f"Queued Jobs: {queued}"
    )


def is_state_stale(load: DashboardStateLoad, *, threshold_seconds: float = 15.0) -> bool:
    return load.age_seconds is not None and load.age_seconds > threshold_seconds


def format_action_log(actions: list[str], *, compact: bool = False) -> str:
    if not actions:
        return "No recent actions."
    items = actions[-3:] if compact else actions[-8:]
    return "\n".join(f"- {item}" for item in items)


def format_dashboard_banner(
    *,
    compact: bool,
    refreshed_at: datetime | None,
    state_load: DashboardStateLoad,
    config_error: str,
) -> str:
    refreshed = refreshed_at.astimezone(UTC).strftime("%H:%M:%S UTC") if refreshed_at else "never"
    parts = [f"Refreshed {refreshed}"]
    if compact:
        parts.append("compact")
    if state_load.error:
        parts.append(state_load.error)
    elif is_state_stale(state_load):
        age = int(state_load.age_seconds or 0)
        parts.append(f"daemon state stale ({age}s)")
    if config_error:
        parts.append(config_error)
    return " | ".join(parts)


def run_tui() -> None:
    try:
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.containers import Horizontal, Vertical
        from textual.screen import ModalScreen, Screen
        from textual.widgets import DataTable, Footer, Header, Input, Static
    except ImportError as exc:
        raise RuntimeError("Textual is not installed. Reinstall mt-linux to use `mt-ctl tui`.") from exc

    class ConfirmScreen(ModalScreen[bool]):
        BINDINGS = [
            Binding("y", "confirm", "Yes"),
            Binding("n", "cancel", "No"),
            Binding("escape", "cancel", "Cancel"),
        ]

        def __init__(self, prompt: str) -> None:
            super().__init__()
            self.prompt = prompt

        def compose(self) -> ComposeResult:
            yield Vertical(
                Static(self.prompt, id="dialog-title"),
                Static("Press y to confirm or n to cancel.", id="dialog-help"),
                id="dialog",
            )

        def action_confirm(self) -> None:
            self.dismiss(True)

        def action_cancel(self) -> None:
            self.dismiss(False)

    class InputScreen(ModalScreen[str | None]):
        BINDINGS = [Binding("escape", "cancel", "Cancel")]

        def __init__(self, title: str, *, value: str = "", placeholder: str = "") -> None:
            super().__init__()
            self.title = title
            self.value = value
            self.placeholder = placeholder

        def compose(self) -> ComposeResult:
            yield Vertical(
                Static(self.title, id="dialog-title"),
                Input(value=self.value, placeholder=self.placeholder, id="dialog-input"),
                Static("Press Enter to save or Esc to cancel.", id="dialog-help"),
                id="dialog",
            )

        def on_mount(self) -> None:
            self.query_one("#dialog-input", Input).focus()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            self.dismiss(event.value)

        def action_cancel(self) -> None:
            self.dismiss(None)

    class MeetingChoiceScreen(ModalScreen[tuple[str, CalendarEvent | None] | None]):
        BINDINGS = [Binding("enter", "select", "Select"), Binding("escape", "cancel", "Cancel")]

        def __init__(self, current_title: str, candidates: list[CalendarEvent]) -> None:
            super().__init__()
            self.current_title = current_title
            self.candidates = candidates
            self.row_map: list[tuple[str, CalendarEvent | None]] = [("external", None)]

        def compose(self) -> ComposeResult:
            yield Vertical(
                Static(f"Assign Meeting: {self.current_title}", id="dialog-title"),
                DataTable(id="meeting-choice-table"),
                Static("", id="dialog-help"),
                id="meeting-choice-dialog",
            )

        def on_mount(self) -> None:
            table = self.query_one("#meeting-choice-table", DataTable)
            table.cursor_type = "row"
            table.add_columns("Choice", "Type", "When", "Organizer")
            table.add_row("None of these / ad hoc", "external", "", "", height=1)
            for candidate in self.candidates:
                self.row_map.append(("candidate", candidate))
                table.add_row(
                    candidate.title,
                    candidate.conferencing_type or "unknown",
                    candidate.start_time.isoformat(timespec="minutes"),
                    candidate.organizer or "",
                    height=1,
                )
            self._update_help()

        def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
            if event.data_table.id == "meeting-choice-table":
                self._update_help()

        def _update_help(self) -> None:
            row = self.query_one("#meeting-choice-table", DataTable).cursor_row
            kind, candidate = self.row_map[row]
            if kind == "external":
                message = "Leave the meeting detached from the calendar and keep the current title."
            else:
                assert candidate is not None
                attendees = ", ".join(attendee.display() for attendee in candidate.attendees[:5]) or "No attendees"
                message = (
                    f"{candidate.title} | {candidate.response_status or 'unknown'} | "
                    f"{candidate.conferencing_type or 'unknown'} | {attendees}"
                )
            self.query_one("#dialog-help", Static).update(message)

        def action_select(self) -> None:
            row = self.query_one("#meeting-choice-table", DataTable).cursor_row
            self.dismiss(self.row_map[row])

        def action_cancel(self) -> None:
            self.dismiss(None)

    class SettingsScreen(Screen[None]):
        BINDINGS = [
            Binding("escape", "close", "Back"),
            Binding("enter", "edit_selected", "Edit"),
            Binding("t", "toggle_selected", "Toggle"),
        ]

        def __init__(self, config: AppConfig) -> None:
            super().__init__()
            self.config = config
            self.row_map: list[SettingField] = list(SETTINGS_FIELDS)

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Horizontal(DataTable(id="settings-table"), Static("", id="settings-detail"), id="settings-body")
            yield Static("", id="settings-status")
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#settings-table", DataTable)
            table.cursor_type = "row"
            table.add_columns("Setting", "Value")
            self._refresh_table()

        def _refresh_table(self) -> None:
            table = self.query_one("#settings-table", DataTable)
            current_row = min(table.cursor_row, max(len(self.row_map) - 1, 0)) if table.row_count else 0
            table.clear(columns=False)
            for field in self.row_map:
                table.add_row(field.label, format_config_value(get_config_value(self.config, field.key)))
            if table.row_count:
                table.move_cursor(row=current_row)
            self._update_detail()

        def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
            if event.data_table.id == "settings-table":
                self._update_detail()

        def _selected_field(self) -> SettingField | None:
            table = self.query_one("#settings-table", DataTable)
            if table.row_count == 0:
                return None
            return self.row_map[table.cursor_row]

        def _update_detail(self) -> None:
            field = self._selected_field()
            if field is None:
                self.query_one("#settings-detail", Static).update("No settings available.")
                self.query_one("#settings-status", Static).update("")
                return
            value = format_config_value(get_config_value(self.config, field.key))
            self.query_one("#settings-detail", Static).update(
                f"{field.label}\n\nKey: {field.key}\nValue: {value}\n\n{field.help_text}"
            )
            self.query_one("#settings-status", Static).update(
                "Enter edits the selected value. T toggles booleans. Esc returns to the dashboard."
            )

        async def action_edit_selected(self) -> None:
            field = self._selected_field()
            if field is None:
                return
            current_value = get_config_value(self.config, field.key)
            if isinstance(current_value, bool):
                self.config.set_value(field.key, "false" if current_value else "true")
                self.config.save()
                self._refresh_table()
                self.notify(f"Updated {field.key}")
                return
            result = await self.app.push_screen_wait(
                InputScreen(
                    f"Edit {field.label}",
                    value=format_config_value(current_value),
                    placeholder=field.help_text,
                )
            )
            if result is None:
                return
            self.config.set_value(field.key, result)
            self.config.save()
            self._refresh_table()
            self.notify(f"Updated {field.key}")

        def action_toggle_selected(self) -> None:
            field = self._selected_field()
            if field is None:
                return
            current_value = get_config_value(self.config, field.key)
            if not isinstance(current_value, bool):
                self.notify("Selected setting is not a boolean.")
                return
            self.config.set_value(field.key, "false" if current_value else "true")
            self.config.save()
            self._refresh_table()
            self.notify(f"Toggled {field.key}")

        def action_close(self) -> None:
            self.app.pop_screen()

    class MtDashboard(App[None]):
        CSS = """
        Screen {
            layout: vertical;
        }
        #body, #settings-body {
            height: 1fr;
        }
        #sidebar-table {
            width: 28;
        }
        #jobs-table {
            width: 56;
        }
        #job-detail, #settings-detail {
            padding: 1 2;
            border: round $accent;
        }
        #sidebar-detail {
            height: 5;
            padding: 1 1;
            border: round $secondary;
        }
        #activity-log {
            height: 8;
            padding: 1 1;
            border: round $warning;
        }
        #center-pane {
            width: 1fr;
            layout: vertical;
        }
        #jobs-title {
            height: 3;
            padding: 1 1;
            text-style: bold;
        }
        #status-bar, #settings-status {
            height: 2;
            background: $boost;
            color: $text;
            padding: 0 1;
        }
        #dialog, #meeting-choice-dialog {
            width: 80;
            height: auto;
            padding: 1 2;
            border: round $accent;
            background: $surface;
            margin: 5 10;
        }
        #dialog-title {
            text-style: bold;
            margin-bottom: 1;
        }
        #dialog-help {
            margin-top: 1;
            color: $text-muted;
        }
        """
        BINDINGS = [
            Binding("q", "quit", "Quit"),
            Binding("tab", "cycle_focus", "Next Pane"),
            Binding("r", "retry_selected", "Retry"),
            Binding("x", "cancel_selected", "Cancel"),
            Binding("c", "recheck_calendar", "Recheck"),
            Binding("m", "assign_meeting", "Assign"),
            Binding("s", "settings", "Settings"),
            Binding("l", "refresh_jobs", "Refresh"),
            Binding("1", "show_queue", "Queue"),
            Binding("2", "show_failed", "Failed"),
            Binding("3", "show_meeting_review", "Meet"),
            Binding("4", "show_speaker_review", "Speaker"),
            Binding("5", "show_recent", "Recent"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self.config = AppConfig.load()
            self.store = JobSnapshotStore()
            self.review_queue = ReviewQueue()
            self.meeting_review_queue = MeetingReviewQueue()
            self.jobs: list[PipelineJob] = []
            self.filtered_jobs: list[PipelineJob] = []
            self.dashboard_state = DashboardState()
            self.dashboard_state_load = DashboardStateLoad(state=DashboardState())
            self.sidebar_rows: list[SidebarRow] = []
            self.current_view = "queue"
            self.refresh_interval_seconds = 2.0
            self.last_refresh_at: datetime | None = None
            self.config_error = ""
            self.action_log: list[str] = []
            self.compact_mode = False

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Horizontal(
                Vertical(
                    DataTable(id="sidebar-table"),
                    Static("", id="sidebar-detail"),
                    Static("", id="activity-log"),
                    id="sidebar-pane",
                ),
                Vertical(Static("", id="jobs-title"), DataTable(id="jobs-table"), id="center-pane"),
                Static("", id="job-detail"),
                id="body",
            )
            yield Static("", id="status-bar")
            yield Footer()

        def on_mount(self) -> None:
            sidebar = self.query_one("#sidebar-table", DataTable)
            sidebar.cursor_type = "row"
            sidebar.add_columns("View", "Count")
            jobs_table = self.query_one("#jobs-table", DataTable)
            jobs_table.cursor_type = "row"
            jobs_table.add_columns("Session", "Status", "Title", "Match", "Candidates", "Queue")
            self.set_interval(self.refresh_interval_seconds, self.refresh_jobs)
            self.refresh_jobs()

        def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
            if event.data_table.id == "sidebar-table":
                self._sync_view_from_sidebar()
            self._update_detail_and_status()

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            if event.data_table.id == "sidebar-table":
                self._sync_view_from_sidebar()
                self._refresh_jobs_table()

        def action_cycle_focus(self) -> None:
            current = self.focused
            if current is self.query_one("#sidebar-table", DataTable):
                self.query_one("#jobs-table", DataTable).focus()
                return
            self.query_one("#sidebar-table", DataTable).focus()

        def action_show_queue(self) -> None:
            self._set_current_view("queue")

        def action_show_failed(self) -> None:
            self._set_current_view("failed")

        def action_show_meeting_review(self) -> None:
            self._set_current_view("meeting_review")

        def action_show_speaker_review(self) -> None:
            self._set_current_view("speaker_review")

        def action_show_recent(self) -> None:
            self._set_current_view("recent")

        def refresh_jobs(self) -> None:
            self.compact_mode = self.size.width < 170
            try:
                self.config = AppConfig.load()
                self.config_error = ""
            except Exception as exc:
                self.config_error = f"Config load failed: {exc}"
            self.jobs = load_dashboard_jobs(self.store)
            self.dashboard_state_load = load_dashboard_state()
            self.dashboard_state = self.dashboard_state_load.state
            self.last_refresh_at = datetime.now(UTC)
            self.sidebar_rows = build_sidebar_rows(self.jobs, self.dashboard_state)
            self._refresh_sidebar()
            self._refresh_jobs_table()
            self._update_action_log()

        def _refresh_sidebar(self) -> None:
            table = self.query_one("#sidebar-table", DataTable)
            current_row = self._sidebar_index_for_view(self.current_view)
            table.clear(columns=False)
            for row in self.sidebar_rows:
                table.add_row(row.label, str(row.count))
            if table.row_count:
                table.move_cursor(row=min(current_row, table.row_count - 1))
            self._sync_view_from_sidebar()

        def _sidebar_index_for_view(self, view_key: str) -> int:
            for index, row in enumerate(self.sidebar_rows):
                if row.key == view_key:
                    return index
            return 0

        def _sync_view_from_sidebar(self) -> None:
            table = self.query_one("#sidebar-table", DataTable)
            if not self.sidebar_rows or table.row_count == 0:
                return
            self.current_view = self.sidebar_rows[table.cursor_row].key
            self._update_sidebar_detail()

        def _update_sidebar_detail(self) -> None:
            detail = self.query_one("#sidebar-detail", Static)
            if self.current_view == "queue":
                detail.update(format_queue_summary(self.dashboard_state))
                return
            row = next((item for item in self.sidebar_rows if item.key == self.current_view), None)
            if row is None:
                detail.update("")
                return
            detail.update(f"{row.label}\n\n{row.help_text}")

        def _update_action_log(self) -> None:
            self.query_one("#activity-log", Static).update(
                "Action Log\n\n" + format_action_log(self.action_log, compact=self.compact_mode)
            )

        def _refresh_jobs_table(self) -> None:
            table = self.query_one("#jobs-table", DataTable)
            current_session = self._selected_job().session_id if self._selected_job() is not None else ""
            self.filtered_jobs = filter_jobs_for_view(self.jobs, self.dashboard_state, self.current_view)
            title_map = {
                "queue": "Live Queue",
                "failed": "Failed Jobs",
                "meeting_review": "Meeting Review Targets",
                "speaker_review": "Speaker Review Targets",
                "recent": "Recent Completed Jobs",
            }
            self.query_one("#jobs-title", Static).update(
                f"{title_map.get(self.current_view, 'Jobs')} ({len(self.filtered_jobs)})"
            )
            table.clear(columns=False)
            target_row = 0
            for index, job in enumerate(self.filtered_jobs):
                queue_label = queued_position(self.dashboard_state, job.session_id)
                table.add_row(
                    job.session_id,
                    job.status.value,
                    job.meeting_info.title or job.meeting_info.app,
                    job.meeting_info.calendar_match_confidence,
                    str(len(job.meeting_info.calendar_candidates)),
                    queue_label,
                )
                if job.session_id == current_session:
                    target_row = index
            if table.row_count:
                table.move_cursor(row=min(target_row, table.row_count - 1))
            self._update_detail_and_status()

        def _set_current_view(self, view_key: str) -> None:
            self.current_view = view_key
            sidebar = self.query_one("#sidebar-table", DataTable)
            if self.sidebar_rows and sidebar.row_count:
                sidebar.move_cursor(row=self._sidebar_index_for_view(view_key))
            self._update_sidebar_detail()
            self._refresh_jobs_table()
            self.query_one("#jobs-table", DataTable).focus()

        def _selected_job(self) -> PipelineJob | None:
            table = self.query_one("#jobs-table", DataTable)
            if not self.filtered_jobs or table.row_count == 0:
                return None
            return self.filtered_jobs[table.cursor_row]

        def _update_detail_and_status(self) -> None:
            job = self._selected_job()
            detail = self.query_one("#job-detail", Static)
            status = self.query_one("#status-bar", Static)
            if job is None:
                detail.update("No jobs found for this view.")
                status.update(
                    format_dashboard_banner(
                        compact=self.compact_mode,
                        refreshed_at=self.last_refresh_at,
                        state_load=self.dashboard_state_load,
                        config_error=self.config_error,
                    )
                    + "\nTab switch panes | 1-5 views | L refresh | S settings | Q quit"
                )
                return
            detail.update(
                format_job_details_for_mode(
                    job,
                    self.config,
                    state=self.dashboard_state,
                    compact=self.compact_mode,
                )
            )
            status_parts = ["Tab panes", "1-5 views", "L refresh", "S settings", "X cancel", "C recheck"]
            if job.status == JobStatus.FAILED:
                status_parts.append("R retry")
            if job.meeting_info.calendar_candidates:
                status_parts.append("M assign")
            if job_needs_speaker_review(job):
                status_parts.append("Speaker review pending")
            status.update(
                format_dashboard_banner(
                    compact=self.compact_mode,
                    refreshed_at=self.last_refresh_at,
                    state_load=self.dashboard_state_load,
                    config_error=self.config_error,
                )
                + "\n"
                + " | ".join(status_parts[:6]) + "\n"
                + f"Active:{self.dashboard_state.active_job or 'none'} Queue:{self.dashboard_state.queue_depth} "
                f"Meeting:{self.dashboard_state.active_meeting_title or self.dashboard_state.active_meeting_app or 'none'}"
            )

        def _log_action(self, message: str) -> None:
            stamped = f"{datetime.now(UTC).strftime('%H:%M:%S')} {message}"
            self.action_log.append(stamped)
            self.action_log = self.action_log[-30:]
            self._update_action_log()

        async def action_refresh_jobs(self) -> None:
            self.refresh_jobs()

        async def action_retry_selected(self) -> None:
            job = self._selected_job()
            if job is None:
                return
            ok, reason = await asyncio.to_thread(
                retry_job,
                job.session_id,
                review_queue=self.review_queue,
                meeting_review_queue=self.meeting_review_queue,
                store=self.store,
            )
            if not ok:
                self.notify("Selected job is not retryable." if reason == "not_failed" else "Retry failed.")
                return
            self.refresh_jobs()
            self._log_action(f"Retried {job.session_id}")
            self.notify(f"Retried {job.session_id}")

        async def action_cancel_selected(self) -> None:
            job = self._selected_job()
            if job is None:
                return
            confirm = await self.push_screen_wait(
                ConfirmScreen(f"Cancel job {job.session_id} ({job.meeting_info.title or job.meeting_info.app})?")
            )
            if not confirm:
                return
            removed, _deleted_paths = await asyncio.to_thread(
                remove_job,
                job.session_id,
                review_queue=self.review_queue,
                meeting_review_queue=self.meeting_review_queue,
                store=self.store,
            )
            if not removed:
                self.notify("Job snapshot no longer exists.")
                return
            self.refresh_jobs()
            self._log_action(f"Canceled {job.session_id}")
            self.notify(f"Canceled {job.session_id}")

        async def action_recheck_calendar(self) -> None:
            job = self._selected_job()
            if job is None:
                return
            from mt_linux.cli import _calendar_lookup_service, _recheck_job_calendar

            outcome = await asyncio.to_thread(
                _recheck_job_calendar,
                self.store,
                self.meeting_review_queue,
                self.config,
                _calendar_lookup_service(self.config, 0),
                job,
            )
            self.refresh_jobs()
            self._log_action(f"{job.session_id}: {outcome}")
            self.notify(f"{job.session_id}: {outcome}")

        async def action_assign_meeting(self) -> None:
            job = self._selected_job()
            if job is None:
                return
            candidates = job.meeting_info.calendar_candidates
            if not candidates:
                self.notify("Selected job has no calendar candidates.")
                return
            choice = await self.push_screen_wait(
                MeetingChoiceScreen(job.meeting_info.title or job.meeting_info.app, candidates)
            )
            if choice is None:
                return
            kind, candidate = choice
            transcript_path = output_path_for(job, self.config)
            if kind == "external":
                from mt_linux.cli import _clear_job_meeting_assignment

                _clear_job_meeting_assignment(job, title=job.meeting_info.title or "Ad Hoc Meeting")
                self.store.save(job)
                if transcript_path.exists():
                    clear_meeting_assignment(
                        transcript_path,
                        candidates=job.meeting_info.calendar_candidates,
                        reason="external",
                        title=job.meeting_info.title or "Ad Hoc Meeting",
                    )
                self.refresh_jobs()
                self._log_action(f"Marked {job.session_id} as ad hoc")
                self.notify(f"Marked {job.session_id} as ad hoc")
                return
            assert candidate is not None
            from mt_linux.cli import _apply_job_meeting_assignment, _rename_transcript_path_for_title

            _apply_job_meeting_assignment(job, candidate)
            self.store.save(job)
            if transcript_path.exists():
                apply_meeting_assignment(
                    transcript_path,
                    selected_event=candidate,
                    candidates=job.meeting_info.calendar_candidates,
                    ambiguous=False,
                )
                expected_path = output_path_for(job, self.config)
                if expected_path != transcript_path:
                    _rename_transcript_path_for_title(transcript_path, candidate.title)
            self.refresh_jobs()
            self._log_action(f"Assigned {candidate.title} to {job.session_id}")
            self.notify(f"Assigned {candidate.title}")

        def action_settings(self) -> None:
            self.push_screen(SettingsScreen(self.config))

    MtDashboard().run()
