from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid

import click

from mt_linux.audio.wav import wav_duration_minutes
from mt_linux.bootstrap import bootstrap_local_config
from mt_linux.cleanup import cleanup_runtime_artifacts
from mt_linux.config import AppConfig
from mt_linux.control import build_request, wait_for_result, write_request
from mt_linux.corpus import export_markdown_corpus
from mt_linux.daemon import MeetingPipeline
from mt_linux.detection.calendar_lookup import CalendarLookupService
from mt_linux.detection.google_auth import run_google_auth
from mt_linux.diarization.speaker_matcher import SpeakerMatcher
from mt_linux.doctor import run_doctor, summarize_results
from mt_linux.enrichment.service import enrich_note, entity_notes_root, sync_entity_catalog
from mt_linux.models import Attendee, CalendarEvent, MeetingInfo, MeetingReviewEntry
from mt_linux.output.enrichment_patch import apply_note_enrichment
from mt_linux.output.markdown import output_path_for, slugify
from mt_linux.output.note_content import parse_note_content
from mt_linux.output.protocol_refresh import refresh_summary_from_transcript
from mt_linux.output.transcript_patch import (
    apply_meeting_assignment,
    clear_meeting_assignment,
    remove_speaker_label,
    replace_speaker_label,
)
from mt_linux.paths import STATE_FILE, ensure_directories
from mt_linux.pipeline.job import JobStatus, PipelineJob
from mt_linux.pipeline.job_admin import remove_job
from mt_linux.pipeline.meeting_review_queue import MeetingReviewQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore
from mt_linux.pipeline.review_queue import ReviewQueue
from mt_linux.review.meeting_review_context import format_candidate_summary, format_transcript_preview


@click.group()
def cli() -> None:
    """mt-linux control CLI."""


@cli.command()
def start() -> None:
    """Start the systemd user service."""
    subprocess.run(["systemctl", "--user", "start", "mt-linux.service"], check=False)


@cli.command()
def stop() -> None:
    """Stop the systemd user service."""
    subprocess.run(["systemctl", "--user", "stop", "mt-linux.service"], check=False)


@cli.command()
def status() -> None:
    """Show daemon status."""
    if STATE_FILE.exists():
        click.echo(STATE_FILE.read_text(encoding="utf-8"))
    else:
        click.echo("No daemon state has been written yet.")


@cli.group()
def record() -> None:
    """Control manual recordings."""


@record.command("start")
@click.option("--title", default="", help="Optional title for the recording session.")
@click.option("--app", default="manual", help="Logical app/source label, e.g. slack or meet.")
def record_start(title: str, app: str) -> None:
    request = build_request("start", title=title, app=app)
    try:
        write_request(request)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    result = wait_for_result(request.request_id)
    if result is None:
        raise click.ClickException("Timed out waiting for the daemon to start manual recording.")
    if result.status != "ok":
        raise click.ClickException(result.message)
    click.echo(result.message)
    if result.session_id:
        click.echo(f"Session: {result.session_id}")


@record.command("stop")
def record_stop() -> None:
    request = build_request("stop")
    try:
        write_request(request)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    result = wait_for_result(request.request_id)
    if result is None:
        raise click.ClickException("Timed out waiting for the daemon to stop manual recording.")
    if result.status != "ok":
        raise click.ClickException(result.message)
    click.echo(result.message)
    if result.session_id:
        click.echo(f"Queued job: {result.session_id}")


@record.command("status")
def record_status() -> None:
    if not STATE_FILE.exists():
        click.echo("No daemon state has been written yet.")
        return
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    active = state.get("active_meeting")
    if not active:
        click.echo("No active recording session.")
        return
    click.echo(
        f"{active.get('session_id', '')}  {active.get('detection_method', '')}  "
        f"{active.get('app', '')}  {active.get('title', '')}"
    )


@cli.group(invoke_without_command=True)
@click.pass_context
def jobs(ctx: click.Context) -> None:
    """Manage jobs."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(jobs_list)


@jobs.command("list")
def jobs_list() -> None:
    """List persisted jobs."""
    store = JobSnapshotStore()
    pending = store.load_pending()
    if not pending:
        click.echo("No pending jobs.")
        return
    for job in pending:
        click.echo(f"{job.session_id}  {job.status.value}  {job.meeting_info.title or job.meeting_info.app}")


@jobs.command("log")
@click.argument("session_id", required=False)
@click.option("--limit", default=20, show_default=True, help="Limit displayed history entries.")
def jobs_log(session_id: str | None, limit: int) -> None:
    """Show job history."""
    store = JobSnapshotStore()
    job = store.load_one(session_id) if session_id else None
    if job is None:
        jobs = sorted(store.load_all(), key=lambda item: item.created_at, reverse=True)
        if not jobs:
            click.echo("No jobs found.")
            return
        if session_id:
            raise click.ClickException(f"Job not found: {session_id}")
        job = jobs[0]
    click.echo(f"{job.session_id}  {job.status.value}  {job.meeting_info.title or job.meeting_info.app}")
    history = job.history[-limit:]
    for event in history:
        click.echo(f"{event.at.isoformat()}  {event.status}  {event.message}")


@jobs.command("cancel")
@click.argument("session_ids", nargs=-1, required=True)
@click.option("--delete-audio", is_flag=True, help="Delete app/mic/mix recordings for the canceled job.")
def jobs_cancel(session_ids: tuple[str, ...], delete_audio: bool) -> None:
    """Remove one or more persisted jobs from the queue."""
    store = JobSnapshotStore()
    review_queue = ReviewQueue()
    meeting_review_queue = MeetingReviewQueue()
    canceled = 0
    for session_id in session_ids:
        removed, deleted_paths = remove_job(
            session_id,
            delete_audio=delete_audio,
            review_queue=review_queue,
            meeting_review_queue=meeting_review_queue,
            store=store,
        )
        if not removed:
            click.echo(f"Job not found: {session_id}")
            continue
        canceled += 1
        detail = f" and deleted {len(deleted_paths)} file(s)" if deleted_paths else ""
        click.echo(f"Canceled {session_id}{detail}")
    if canceled == 0:
        raise SystemExit(1)


@cli.command()
def doctor() -> None:
    """Check runtime and config."""
    results = run_doctor(AppConfig.load())
    for item in results:
        click.echo(f"[{item.status.upper()}] {item.name}: {item.detail}")
    ok, warn, fail = summarize_results(results)
    click.echo(f"Summary: {ok} ok, {warn} warn, {fail} fail")
    if fail:
        raise SystemExit(1)


@cli.command("bootstrap-config")
def bootstrap_config() -> None:
    """Create local directories."""
    notes = bootstrap_local_config(AppConfig.load())
    for note in notes:
        click.echo(note)


@cli.command("process-jobs")
def process_jobs() -> None:
    """Process queued jobs."""
    store = JobSnapshotStore()
    pending = store.load_pending()
    if not pending:
        click.echo("No pending jobs.")
        return
    pipeline = MeetingPipeline(AppConfig.load(), store=store)
    for job in pending:
        while job.status not in {JobStatus.COMPLETE, JobStatus.FAILED}:
            asyncio.run(pipeline.process(job))
        click.echo(f"Processed {job.session_id}")


@cli.command("cleanup")
@click.option("--dry-run", is_flag=True, help="Show what would be removed without deleting anything.")
@click.option(
    "--include-job-history",
    is_flag=True,
    help="Also remove completed and failed job snapshot files before cleaning orphans.",
)
def cleanup(dry_run: bool, include_job_history: bool) -> None:
    """Remove orphaned runtime artifacts."""
    store = JobSnapshotStore()
    review_queue = ReviewQueue()
    result = cleanup_runtime_artifacts(
        dry_run=dry_run,
        include_job_history=include_job_history,
        store=store,
        review_queue=review_queue,
    )
    if result.removed_job_snapshots:
        for path in result.removed_job_snapshots:
            click.echo(f"{'Would remove' if dry_run else 'Removed'} job snapshot: {path}")
    if result.removed_paths:
        for path in result.removed_paths:
            click.echo(f"{'Would remove' if dry_run else 'Removed'} artifact: {path}")
    if not result.removed_job_snapshots and not result.removed_paths:
        click.echo("Nothing to clean up.")


@cli.group()
def config() -> None:
    """Manage configuration."""


@config.command("show")
def config_show() -> None:
    ensure_directories()
    current = AppConfig.load()
    current.save()
    from mt_linux.paths import CONFIG_FILE

    click.echo(CONFIG_FILE.read_text(encoding="utf-8"))


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    current = AppConfig.load()
    current.set_value(key, value)
    current.save()
    click.echo(f"Updated {key}")


@config.command("list-devices")
def config_list_devices() -> None:
    try:
        import sounddevice as sd
    except ImportError:
        click.echo("sounddevice is not installed.")
        return
    for device in sd.query_devices():
        click.echo(device["name"])


@cli.command()
@click.argument("name")
@click.argument("audio_file", type=click.Path(path_type=Path, exists=True))
def enroll(name: str, audio_file: Path) -> None:
    """Add a speaker profile."""
    current = AppConfig.load()
    matcher = SpeakerMatcher(
        current.resolve_path(current.speakers.db_path),
        current.speakers.similarity_threshold,
    )
    embedding = matcher.embed_wav(audio_file)
    matcher.update_profile(name, embedding)
    click.echo(f"Enrolled {name}")


@cli.group(invoke_without_command=True)
@click.pass_context
def review(ctx: click.Context) -> None:
    """Review unidentified speakers."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(review_run, session_id="")


@review.command("list")
def review_list() -> None:
    queue = ReviewQueue()
    entries = queue.load()
    if not entries:
        click.echo("Review queue is empty.")
        return
    for entry in entries:
        click.echo(f"{entry.session_id} {entry.speaker_label} {entry.meeting_title or ''}")


@review.command("run")
@click.option("--session", "session_id", default="")
def review_run(session_id: str) -> None:
    current = AppConfig.load()
    store = JobSnapshotStore()
    queue = ReviewQueue()
    entries = queue.load()
    if session_id:
        entries = [entry for entry in entries if entry.session_id == session_id]
    if not entries:
        click.echo("No review entries found.")
        return
    changed_sessions: set[str] = set()
    changed_entries: dict[str, list[ReviewEntry]] = {}
    for entry in entries:
        original_transcript_path = entry.transcript_path
        click.echo(f"Meeting: {entry.meeting_title or 'Untitled'} ({entry.meeting_date.isoformat()})")
        click.echo(f"Speaker: {entry.speaker_label}")
        _play_sample(entry.sample_path)
        choice = click.prompt("Name, x to remove as noise, or blank to skip", default="", show_default=False)
        if not choice:
            continue
        if choice.lower() == "x":
            remove_speaker_label(entry.transcript_path, entry.speaker_label)
            action_message = f"Removed {entry.speaker_label} as noise"
        else:
            replace_speaker_label(entry.transcript_path, entry.speaker_label, choice)
            action_message = f"Identified as {choice}"
        queue.remove(entry.session_id, entry.speaker_label)
        if entry.sample_path.exists():
            entry.sample_path.unlink()
        changed_sessions.add(entry.session_id)
        changed_entries.setdefault(entry.session_id, []).append(entry)
        click.echo(action_message)
    for changed_session in sorted(changed_sessions):
        if _refresh_job_summary(store, current, changed_session):
            continue
        fallback_entry = changed_entries[changed_session][0]
        if _refresh_summary_for_path(
            fallback_entry.transcript_path,
            current,
            fallback_entry.meeting_title or "Meeting",
        ):
            click.echo(f"Refreshed summary for {fallback_entry.meeting_title or changed_session}")


@cli.group("review-meetings", invoke_without_command=True)
@click.pass_context
def review_meetings(ctx: click.Context) -> None:
    """Review meeting matches."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(review_meetings_run, session_id="")


@review_meetings.command("list")
def review_meetings_list() -> None:
    queue = MeetingReviewQueue()
    entries = queue.load()
    if not entries:
        click.echo("Meeting review queue is empty.")
        return
    for entry in entries:
        click.echo(f"{entry.session_id} {entry.meeting_title or ''} ({len(entry.candidates)} candidates)")


@review_meetings.command("run")
@click.option("--session", "session_id", default="")
def review_meetings_run(session_id: str) -> None:
    queue = MeetingReviewQueue()
    entries = queue.load()
    if session_id:
        entries = [entry for entry in entries if entry.session_id == session_id]
    if not entries:
        click.echo("No meeting review entries found.")
        return
    for entry in entries:
        original_transcript_path = entry.transcript_path
        click.echo(f"Meeting: {entry.meeting_title or 'Untitled'} ({entry.meeting_date.isoformat()})")
        click.echo(
            f"Detected: app={entry.app or 'unknown'} "
            f"start={entry.detected_start_time.isoformat() if entry.detected_start_time else 'unknown'} "
            f"duration={entry.recording_duration_minutes}m"
        )
        if entry.identified_speakers:
            click.echo(f"Speakers: {', '.join(entry.identified_speakers)}")
        preview = format_transcript_preview(entry)
        if preview:
            click.echo("Transcript preview:")
            for line in preview:
                click.echo(f"  {line}")
        if not entry.candidates:
            click.echo("No plausible calendar candidates were found.")
        for index, candidate in enumerate(entry.candidates, start=1):
            click.echo(
                f"{index}) {candidate.title} "
                f"{format_candidate_summary(candidate, entry.detected_start_time or candidate.start_time)}"
            )
            if candidate.attendees:
                click.echo(f"   attendees: {', '.join(attendee.display() for attendee in candidate.attendees[:5])}")
        outcome = _prompt_meeting_assignment(
            entry.candidates,
            current_title=entry.meeting_title or "Ad Hoc Meeting",
        )
        if outcome is None:
            continue
        if outcome["kind"] == "external":
            clear_meeting_assignment(
                original_transcript_path,
                candidates=entry.candidates,
                reason="external",
                title=outcome["title"],
            )
            renamed_path = _rename_transcript_path_for_title(original_transcript_path, outcome["title"])
            _update_meeting_review_entry_paths(queue, entry.session_id, renamed_path)
            queue.remove(entry.session_id)
            click.echo("Marked as non-calendar / ad-hoc meeting")
            continue
        candidate = outcome["candidate"]
        apply_meeting_assignment(
            original_transcript_path,
            selected_event=candidate,
            candidates=entry.candidates,
            ambiguous=False,
        )
        _rename_transcript_path_for_title(original_transcript_path, candidate.title)
        queue.remove(entry.session_id)
        click.echo(f"Assigned to {candidate.title}")


@review_meetings.command("recent")
@click.option("--limit", default=10, show_default=True)
def review_meetings_recent(limit: int) -> None:
    store = JobSnapshotStore()
    config = AppConfig.load()
    jobs = sorted(store.load_all(), key=lambda job: job.created_at, reverse=True)[:limit]
    if not jobs:
        click.echo("No recent meetings found.")
        return
    for index, job in enumerate(jobs, start=1):
        candidate_count = len(job.meeting_info.calendar_candidates)
        click.echo(
            f"{index}) {job.meeting_info.title or job.meeting_info.app} "
            f"[{job.status.value}] ({candidate_count} matches)"
        )
    raw_choice = click.prompt("Select meeting number or blank to skip", default="", show_default=False)
    if not raw_choice:
        return
    if not raw_choice.isdigit():
        raise click.ClickException("Invalid choice; expected a meeting number or blank.")
    job_index = int(raw_choice) - 1
    if job_index < 0 or job_index >= len(jobs):
        raise click.ClickException("Invalid choice; meeting number is out of range.")
    job = jobs[job_index]
    click.echo(f"Meeting: {job.meeting_info.title or 'Untitled'} ({job.meeting_info.start_time.date().isoformat()})")
    click.echo(
        f"Detected: app={job.meeting_info.app or 'unknown'} "
        f"start={job.meeting_info.start_time.isoformat()} "
        f"status={job.status.value}"
    )
    for index, candidate in enumerate(job.meeting_info.calendar_candidates, start=1):
        click.echo(
            f"{index}) {candidate.title} "
            f"{format_candidate_summary(candidate, job.meeting_info.start_time)}"
        )
        if candidate.attendees:
            click.echo(f"   attendees: {', '.join(attendee.display() for attendee in candidate.attendees[:5])}")
    outcome = _prompt_meeting_assignment(
        job.meeting_info.calendar_candidates,
        current_title=job.meeting_info.title or "Ad Hoc Meeting",
    )
    if outcome is None:
        return
    transcript_path = output_path_for(job, config)
    if outcome["kind"] == "external":
        _clear_job_meeting_assignment(job, title=outcome["title"])
        store.save(job)
        new_transcript_path = output_path_for(job, config)
        if transcript_path.exists():
            clear_meeting_assignment(
                transcript_path,
                candidates=job.meeting_info.calendar_candidates,
                reason="external",
                title=outcome["title"],
            )
            if new_transcript_path != transcript_path:
                new_transcript_path = _rename_transcript_path_for_title(transcript_path, outcome["title"])
        click.echo("Marked as non-calendar / ad-hoc meeting")
        return
    candidate = outcome["candidate"]
    _apply_job_meeting_assignment(job, candidate)
    store.save(job)
    new_transcript_path = output_path_for(job, config)
    if transcript_path.exists():
        apply_meeting_assignment(
            transcript_path,
            selected_event=candidate,
            candidates=job.meeting_info.calendar_candidates,
            ambiguous=False,
        )
        if new_transcript_path != transcript_path:
            _rename_transcript_path_for_title(transcript_path, candidate.title)
    click.echo(f"Assigned to {candidate.title}")


@review_meetings.command("recheck")
@click.option("--session", "session_ids", multiple=True, help="Specific session IDs to recheck.")
@click.option("--window", type=int, default=0, show_default=True, help="Override calendar lookup window in minutes.")
def review_meetings_recheck(session_ids: tuple[str, ...], window: int) -> None:
    current = AppConfig.load()
    store = JobSnapshotStore()
    queue = MeetingReviewQueue()
    service = _calendar_lookup_service(current, window)
    jobs = _select_meeting_recheck_jobs(store, queue, session_ids)
    if not jobs:
        click.echo("No meetings found to recheck.")
        return
    for job in jobs:
        outcome = _recheck_job_calendar(store, queue, current, service, job)
        click.echo(f"{job.session_id}: {outcome}")


@cli.command("import")
@click.argument("audio_file", type=click.Path(path_type=Path, exists=True))
@click.option("--title", default="")
@click.option("--app", default="import")
def import_(audio_file: Path, title: str, app: str) -> None:
    """Import an audio file."""
    ensure_directories()
    current = AppConfig.load()
    start_time = datetime.now(UTC)
    meeting_info = MeetingInfo(
        app=app,
        pid=0,
        detection_method="import",
        start_time=start_time,
        title=title or audio_file.stem,
        calendar_event=CalendarEvent(
            event_id=str(uuid.uuid4()),
            title=title or audio_file.stem,
            start_time=start_time,
            end_time=start_time + timedelta(minutes=wav_duration_minutes(audio_file)),
            organizer=current.speakers.mic_speaker_name,
            attendees=[Attendee(name=current.speakers.mic_speaker_name)] if current.speakers.mic_speaker_name else [],
        ),
    )
    job = PipelineJob(
        session_id=str(uuid.uuid4()),
        app_audio_path=audio_file,
        mic_audio_path=audio_file,
        imported_audio_path=audio_file,
        meeting_info=meeting_info,
    )
    JobSnapshotStore().save(job)
    click.echo(f"Imported {audio_file} as job {job.session_id}")
    click.echo(f"Expected output: {output_path_for(job, current)}")


@cli.command("export-corpus")
@click.option("--format", "format_name", default="jsonl")
def export_corpus(format_name: str) -> None:
    """Export transcript corpus."""
    current = AppConfig.load()
    output_dir = current.resolve_path(current.output.folder)
    try:
        corpus_path = export_markdown_corpus(output_dir, format_name=format_name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(str(corpus_path))


@cli.command("enrich-notes")
@click.option("--limit", default=0, show_default=True, help="Limit the number of notes to process.")
def enrich_notes(limit: int) -> None:
    """Backfill note enrichment."""
    current = AppConfig.load()
    sync_entity_catalog(current)
    output_dir = current.resolve_path(current.output.folder)
    notes = sorted(output_dir.glob("*.md"))
    processed = 0
    for path in notes:
        parsed = parse_note_content(path.read_text(encoding="utf-8"))
        if not parsed.transcript:
            continue
        enrichment = enrich_note(parsed.summary, parsed.transcript, current)
        apply_note_enrichment(path, enrichment, current)
        processed += 1
        click.echo(f"Enriched {path.name}")
        if limit and processed >= limit:
            break
    if processed == 0:
        click.echo("No transcript notes found.")


@cli.command("sync-entities")
def sync_entities() -> None:
    """Generate entity catalog from vault notes."""
    current = AppConfig.load()
    target = sync_entity_catalog(current)
    root = entity_notes_root(current)
    click.echo(f"Entity notes: {root}")
    click.echo(f"Catalog: {target}")


@cli.group()
def auth() -> None:
    """Authentication helpers."""


@auth.command("google")
def auth_google() -> None:
    current = AppConfig.load()
    try:
        token_path = run_google_auth(
            current.resolve_path(current.calendar.credentials_path),
            current.resolve_path(current.calendar.token_path),
        )
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(str(token_path))


def _play_sample(path: Path) -> None:
    player = shutil.which("paplay") or shutil.which("aplay")
    if player:
        subprocess.run([player, str(path)], check=False)


def _refresh_job_summary(store: JobSnapshotStore, config: AppConfig, session_id: str) -> bool:
    job = store.load_one(session_id)
    if job is None:
        return False
    transcript_path = output_path_for(job, config)
    if not transcript_path.exists():
        return False
    refreshed = _refresh_summary_for_job(store, job, transcript_path, config)
    if refreshed:
        click.echo(f"Refreshed summary for {job.meeting_info.title or session_id}")
    return refreshed


def _refresh_summary_for_path(path: Path, config: AppConfig, title: str) -> bool:
    meeting_info = MeetingInfo(
        app="manual",
        pid=0,
        detection_method="manual",
        start_time=datetime.now(UTC),
        title=title,
    )
    return refresh_summary_from_transcript(path, config, meeting_info)


def _refresh_summary_for_job(
    store: JobSnapshotStore,
    job: PipelineJob,
    transcript_path: Path,
    config: AppConfig,
) -> bool:
    job.add_event("Summary refresh requested after speaker review")
    store.save(job)
    refreshed = refresh_summary_from_transcript(transcript_path, config, job.meeting_info)
    if refreshed:
        job.summary = _read_summary_section(transcript_path)
        job.add_event("Summary refreshed after speaker review")
        store.save(job)
    return refreshed


def _calendar_lookup_service(config: AppConfig, window: int) -> CalendarLookupService:
    lookup_config = deepcopy(config.calendar)
    if window > 0:
        lookup_config.lookup_window_minutes = window
    return CalendarLookupService(lookup_config, config.openai)


def _select_meeting_recheck_jobs(
    store: JobSnapshotStore,
    queue: MeetingReviewQueue,
    session_ids: tuple[str, ...],
) -> list[PipelineJob]:
    if session_ids:
        jobs: list[PipelineJob] = []
        for session_id in session_ids:
            job = store.load_one(session_id)
            if job is not None:
                jobs.append(job)
        return jobs
    queued_ids = {entry.session_id for entry in queue.load()}
    jobs: list[PipelineJob] = []
    for job in sorted(store.load_all(), key=lambda item: item.created_at, reverse=True):
        title = (job.meeting_info.title or "").strip().lower()
        app = job.meeting_info.app.strip().lower()
        generic_unmatched = (
            job.status == JobStatus.COMPLETE
            and job.meeting_info.calendar_match_confidence == "none"
            and title in {"", app}
        )
        if job.session_id in queued_ids or generic_unmatched:
            jobs.append(job)
    return jobs


def _recheck_job_calendar(
    store: JobSnapshotStore,
    queue: MeetingReviewQueue,
    config: AppConfig,
    service: CalendarLookupService,
    job: PipelineJob,
) -> str:
    transcript_path = output_path_for(job, config)
    original_title = job.meeting_info.title
    generic_title = not original_title or original_title.strip().lower() == job.meeting_info.app.strip().lower()
    updated_info = deepcopy(job.meeting_info)
    updated_info.calendar_event = None
    updated_info.calendar_candidates = []
    updated_info.calendar_match_confidence = "none"
    updated_info.calendar_review_queued = False
    if generic_title:
        updated_info.title = None
    updated_info = service.enrich(updated_info)
    if job.summary:
        updated_info = service.refine_with_summary(
            updated_info,
            job.summary,
            window_minutes=max(window_override_or_default(service), 0),
        )
    if updated_info.calendar_match_confidence == "ambiguous" and generic_title:
        updated_info.title = original_title
    if updated_info.calendar_match_confidence == "none" and generic_title:
        updated_info.title = original_title or job.meeting_info.app
    job.meeting_info = updated_info
    if updated_info.calendar_event and updated_info.calendar_match_confidence == "matched":
        method_prefix = "OpenAI summary recheck" if updated_info.calendar_match_method == "openai_summary" else "Calendar recheck"
        job.add_event(f"{method_prefix} matched '{updated_info.calendar_event.title}'")
        store.save(job)
        if transcript_path.exists():
            apply_meeting_assignment(
                transcript_path,
                selected_event=updated_info.calendar_event,
                candidates=updated_info.calendar_candidates or [updated_info.calendar_event],
                ambiguous=False,
            )
            _rename_transcript_path_for_title(transcript_path, updated_info.calendar_event.title)
        queue.remove(job.session_id)
        return f"matched {updated_info.calendar_event.title}"
    if updated_info.calendar_review_queued:
        _queue_meeting_review_entry(queue, config, job)
        candidate_count = len(updated_info.calendar_candidates)
        if candidate_count:
            method_prefix = "OpenAI summary recheck" if updated_info.calendar_match_method == "openai_summary" else "Calendar recheck"
            job.add_event(f"{method_prefix} queued meeting review with {candidate_count} candidate(s)")
        else:
            method_prefix = "OpenAI summary recheck" if updated_info.calendar_match_method == "openai_summary" else "Calendar recheck"
            job.add_event(f"{method_prefix} queued unmatched meeting review")
        store.save(job)
        return f"queued review ({candidate_count} candidates)"
    queue.remove(job.session_id)
    job.add_event("Calendar recheck found no candidates")
    store.save(job)
    return "no candidates found"


def window_override_or_default(service: CalendarLookupService) -> int:
    return service.config.lookup_window_minutes


def _queue_meeting_review_entry(queue: MeetingReviewQueue, config: AppConfig, job: PipelineJob) -> None:
    transcript_path = output_path_for(job, config)
    audio_path = job.imported_audio_path or job.app_audio_path
    queue.add(
        MeetingReviewEntry(
            session_id=job.session_id,
            transcript_path=transcript_path,
            selected_event_id=job.meeting_info.calendar_event.event_id if job.meeting_info.calendar_event else "",
            candidates=job.meeting_info.calendar_candidates,
            meeting_title=job.meeting_info.title,
            meeting_date=job.meeting_info.start_time.date(),
            app=job.meeting_info.app,
            detected_start_time=job.meeting_info.start_time,
            recording_duration_minutes=wav_duration_minutes(audio_path),
            identified_speakers=sorted({identity.name for identity in (job.identities or []) if identity.name}),
            transcript_preview=[
                f"{segment.speaker}: {segment.text.strip()}"
                for segment in (job.transcript_segments or [])[:5]
                if segment.text.strip()
            ],
        )
    )


def _read_summary_section(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    match = re.search(r"## Summary\n\n(.*?)\n\n---\n", content, flags=re.S)
    return match.group(1).strip() if match else ""


def _prompt_meeting_assignment(candidates: list[CalendarEvent], current_title: str) -> dict | None:
    click.echo("n) None of these / ad-hoc meeting")
    raw_choice = click.prompt("Select event number, n, or blank to skip", default="", show_default=False)
    if not raw_choice:
        return None
    if raw_choice.lower() == "n":
        manual_title = click.prompt(
            f'Manual title (leave blank for "{current_title}")',
            default="",
            show_default=False,
        )
        return {
            "kind": "external",
            "title": manual_title or current_title,
        }
    if not raw_choice.isdigit():
        click.echo("Invalid choice; expected an event number, n, or blank.")
        return None
    choice_index = int(raw_choice) - 1
    if choice_index < 0 or choice_index >= len(candidates):
        click.echo("Invalid choice; event number is out of range.")
        return None
    return {
        "kind": "candidate",
        "candidate": candidates[choice_index],
    }


def _clear_job_meeting_assignment(job: PipelineJob, title: str) -> None:
    job.meeting_info.title = title
    job.meeting_info.calendar_event = None
    job.meeting_info.calendar_match_confidence = "external"
    job.meeting_info.calendar_review_queued = False


def _apply_job_meeting_assignment(job: PipelineJob, candidate: CalendarEvent) -> None:
    job.meeting_info.title = candidate.title
    job.meeting_info.calendar_event = candidate
    job.meeting_info.calendar_match_confidence = "matched"
    job.meeting_info.calendar_review_queued = False


def _rename_transcript_path_for_title(path: Path, title: str) -> Path:
    if not path.exists():
        return path
    parts = path.name.split("_", 2)
    if len(parts) != 3:
        return path
    new_name = f"{parts[0]}_{parts[1]}_{slugify(title)}.md"
    new_path = path.with_name(new_name)
    if new_path == path:
        return path
    path.rename(new_path)
    return new_path


def _update_meeting_review_entry_paths(queue: MeetingReviewQueue, session_id: str, transcript_path: Path) -> None:
    entries = queue.load()
    changed = False
    for entry in entries:
        if entry.session_id != session_id:
            continue
        entry.transcript_path = transcript_path
        changed = True
    if changed:
        queue.save(entries)
