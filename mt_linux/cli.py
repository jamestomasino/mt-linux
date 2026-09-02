from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
import uuid

import click

from mt_linux.audio.wav import extract_wav_clip, wav_duration_minutes
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
from mt_linux.models import Attendee, CalendarEvent, MeetingInfo, MeetingReviewEntry, ReviewEntry
from mt_linux.output.enrichment_patch import apply_note_enrichment, get_enriched_at_from_frontmatter
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
from mt_linux.pipeline.identity import _best_sample_segments
from mt_linux.pipeline.job_admin import cleanup_completed_job_audio, remove_job, retry_job
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
    """List pending and failed jobs."""
    store = JobSnapshotStore()
    jobs = [
        job for job in sorted(store.load_all(), key=lambda item: item.created_at, reverse=True)
        if job.status != JobStatus.COMPLETE
    ]
    if not jobs:
        click.echo("No pending or failed jobs.")
        return
    for job in jobs:
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


@jobs.command("retry")
@click.argument("session_ids", nargs=-1, required=True)
def jobs_retry(session_ids: tuple[str, ...]) -> None:
    """Reset failed jobs to pending so they can resume processing."""
    store = JobSnapshotStore()
    review_queue = ReviewQueue()
    meeting_review_queue = MeetingReviewQueue()
    retried = 0
    for session_id in session_ids:
        ok, reason = retry_job(
            session_id,
            review_queue=review_queue,
            meeting_review_queue=meeting_review_queue,
            store=store,
        )
        if ok:
            retried += 1
            click.echo(f"Retried {session_id}")
            continue
        if reason == "not_found":
            click.echo(f"Job not found: {session_id}")
            continue
        if reason == "not_failed":
            click.echo(f"Job is not failed: {session_id}")
            continue
        click.echo(f"Could not retry {session_id}")
    if retried == 0:
        raise SystemExit(1)


@cli.command("tui")
def tui() -> None:
    """Launch the interactive terminal UI."""
    _launch_tui()


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


@cli.command("backfill-speaker-profiles")
@click.option("--dry-run", is_flag=True, help="Show how many historical clips would be added without writing profiles.")
def backfill_speaker_profiles(dry_run: bool) -> None:
    """Rebuild speaker profiles from historical confirmed identities."""
    current = AppConfig.load()
    store = JobSnapshotStore()
    matcher = SpeakerMatcher(
        current.resolve_path(current.speakers.db_path),
        current.speakers.similarity_threshold,
    )
    eligible_confidences = {"voice_profile", "manual_correction"}
    scanned_jobs = 0
    updated_profiles = 0
    added_clips = 0
    skipped_missing_audio = 0
    skipped_missing_segment = 0
    skipped_embedding_failures = 0

    for job in store.load_all():
        scanned_jobs += 1
        if not job.identities or not job.diarization_segments:
            continue
        source_audio_path = _historical_identity_audio_path(job)
        if source_audio_path is None or not source_audio_path.exists():
            matching_identities = [
                identity
                for identity in job.identities
                if identity.confidence in eligible_confidences and identity.label != identity.name
            ]
            skipped_missing_audio += len(matching_identities)
            continue
        for identity in job.identities:
            if identity.confidence not in eligible_confidences:
                continue
            if identity.label == identity.name:
                continue
            best_segments = _best_sample_segments(
                identity.label,
                [segment for segment in (job.transcript_segments or []) if segment.speaker == identity.label],
                job.diarization_segments,
                max_samples=1,
            )
            if not best_segments:
                skipped_missing_segment += 1
                continue
            best_segment = best_segments[0]
            updated_profiles += int(identity.name not in matcher.db)
            with TemporaryDirectory(prefix="mt-linux-backfill-") as temp_dir:
                clip_path = Path(temp_dir) / f"{job.session_id}_{identity.label}.wav"
                extract_wav_clip(source_audio_path, clip_path, best_segment.start, best_segment.end)
                if dry_run:
                    added_clips += 1
                    continue
                try:
                    embedding = matcher.embed_wav(clip_path)
                except RuntimeError:
                    skipped_embedding_failures += 1
                    continue
                matcher.update_profile(identity.name, embedding)
                added_clips += 1

    click.echo(
        f"{'Would backfill' if dry_run else 'Backfilled'} {added_clips} clip(s) "
        f"across {scanned_jobs} job(s)."
    )
    click.echo(f"New profiles discovered: {updated_profiles}")
    if skipped_missing_audio:
        click.echo(f"Skipped {skipped_missing_audio} candidate clip(s) with missing source audio.")
    if skipped_missing_segment:
        click.echo(f"Skipped {skipped_missing_segment} candidate clip(s) without a usable segment.")
    if skipped_embedding_failures:
        click.echo(f"Skipped {skipped_embedding_failures} candidate clip(s) due to embedding errors.")


def _historical_identity_audio_path(job: PipelineJob) -> Path | None:
    if job.app_transcript_segments is not None:
        return job.app_audio_path
    if job.imported_audio_path is not None:
        return job.imported_audio_path
    if job.app_audio_path.exists() and job.mic_audio_path.exists():
        if job.app_audio_path.resolve() == job.mic_audio_path.resolve():
            return job.app_audio_path
        mix_path = job.app_audio_path.with_name(f"{job.session_id}_mix.wav")
        if mix_path.exists():
            return mix_path
    return None


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
        transcript_path = _resolve_review_transcript_path(entry, store, current)
        job = store.load_one(entry.session_id)
        meeting_when = entry.meeting_date.isoformat()
        meeting_title = entry.meeting_title
        if job is not None:
            meeting_when = f"{meeting_when} {job.meeting_info.start_time.strftime('%H:%M')}"
            meeting_title = job.meeting_info.title or meeting_title
        click.echo(f"Meeting: {meeting_title or 'Untitled'} ({meeting_when})")
        click.echo(f"Speaker: {entry.speaker_label}")
        playback = _play_sample(entry.sample_path)
        try:
            choice = click.prompt("Name, x to remove as noise, or blank to skip", default="", show_default=False)
        finally:
            _stop_sample_playback(playback)
        if not choice:
            continue
        note_updated = False
        if transcript_path.exists():
            if choice.lower() == "x":
                remove_speaker_label(transcript_path, entry.speaker_label)
                action_message = f"Removed {entry.speaker_label} as noise"
            else:
                replace_speaker_label(transcript_path, entry.speaker_label, choice)
                action_message = f"Identified as {choice}"
            note_updated = True
        else:
            if choice.lower() == "x":
                action_message = f"Removed {entry.speaker_label} as noise (transcript missing; skipped note update)"
            else:
                action_message = f"Identified as {choice} (transcript missing; skipped note update)"
        _apply_review_choice_to_job(store, entry, choice)
        if choice.lower() != "x":
            warning = _update_speaker_profile_from_review(current, entry, choice)
            if warning:
                click.echo(warning)
        queue.remove(entry.session_id, entry.speaker_label)
        if entry.sample_path.exists():
            entry.sample_path.unlink()
        changed_sessions.add(entry.session_id)
        entry.transcript_path = transcript_path
        changed_entries.setdefault(entry.session_id, []).append(entry)
        click.echo(action_message)
        if not note_updated:
            click.echo(f"Warning: transcript not found at {transcript_path}")
    for changed_session in sorted(changed_sessions):
        if not _refresh_job_summary(store, current, changed_session):
            fallback_entry = changed_entries[changed_session][0]
            if _refresh_summary_for_path(
                fallback_entry.transcript_path,
                current,
                fallback_entry.meeting_title or "Meeting",
            ):
                click.echo(f"Refreshed summary for {fallback_entry.meeting_title or changed_session}")
        job = store.load_one(changed_session)
        if job is not None:
            cleanup_completed_job_audio(
                job,
                keep_audio=current.output.keep_audio,
                review_queue=queue,
            )


def _resolve_review_transcript_path(
    entry: ReviewEntry | MeetingReviewEntry,
    store: JobSnapshotStore,
    config: AppConfig,
) -> Path:
    if entry.transcript_path.exists():
        return entry.transcript_path
    job = store.load_one(entry.session_id)
    current_path = output_path_for(job, config) if job is not None else None
    if current_path is not None and current_path.exists():
        return current_path

    timestamp_prefix = ""
    search_directories = [entry.transcript_path.parent]
    if job is not None:
        timestamp_prefix = f"{job.meeting_info.start_time:%Y-%m-%d_%H-%M}"
        if current_path is not None and current_path.parent not in search_directories:
            search_directories.append(current_path.parent)
    else:
        match = re.match(r"^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2})_", entry.transcript_path.name)
        if match:
            timestamp_prefix = match.group(1)

    if timestamp_prefix:
        candidates = getattr(entry, "candidates", [])
        for directory in search_directories:
            candidate_matches = {
                directory / f"{timestamp_prefix}_{slugify(candidate.title)}.md"
                for candidate in candidates
                if (directory / f"{timestamp_prefix}_{slugify(candidate.title)}.md").exists()
            }
            if len(candidate_matches) == 1:
                return candidate_matches.pop()
            timestamp_matches = list(directory.glob(f"{timestamp_prefix}_*.md"))
            if len(timestamp_matches) == 1:
                return timestamp_matches[0]
    return entry.transcript_path


def _apply_review_choice_to_job(store: JobSnapshotStore, entry: ReviewEntry, choice: str) -> None:
    job = store.load_one(entry.session_id)
    if job is None or job.identities is None:
        return
    updated = False
    kept = []
    for identity in job.identities:
        if identity.label != entry.speaker_label:
            kept.append(identity)
            continue
        updated = True
        if choice.lower() == "x":
            continue
        identity.name = choice
        identity.confidence = "voice_profile"
        identity.review_queued = False
        kept.append(identity)
    if not updated:
        return
    job.identities = kept
    job.add_event(
        f"Speaker review: removed {entry.speaker_label} as noise"
        if choice.lower() == "x"
        else f"Speaker review: identified {entry.speaker_label} as {choice}"
    )
    store.save(job)


def _update_speaker_profile_from_review(config: AppConfig, entry: ReviewEntry, choice: str) -> str:
    if not entry.sample_path.exists():
        return ""
    matcher = SpeakerMatcher(
        config.resolve_path(config.speakers.db_path),
        config.speakers.similarity_threshold,
    )
    try:
        embedding = matcher.embed_wav(entry.sample_path)
    except RuntimeError as exc:
        return f"Warning: could not update speaker profile for {choice}: {exc}"
    matcher.update_profile(choice, embedding)
    return ""


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
    current = AppConfig.load()
    store = JobSnapshotStore()
    queue = MeetingReviewQueue()
    entries = queue.load()
    if session_id:
        entries = [entry for entry in entries if entry.session_id == session_id]
    if not entries:
        click.echo("No meeting review entries found.")
        return
    for entry in entries:
        original_transcript_path = _resolve_review_transcript_path(entry, store, current)
        if original_transcript_path != entry.transcript_path:
            _update_meeting_review_entry_paths(queue, entry.session_id, original_transcript_path)
            entry.transcript_path = original_transcript_path
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
@click.option(
    "--since",
    default=None,
    type=click.DateTime(formats=["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"]),
    help="Only process notes enriched before this date (or not enriched at all).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Re-enrich notes even if they already have an enriched_at timestamp.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show which notes would be processed without making changes.",
)
def enrich_notes(limit: int, since: datetime | None, force: bool, dry_run: bool) -> None:
    """Backfill note enrichment."""
    current = AppConfig.load()
    sync_entity_catalog(current)
    output_dir = current.resolve_path(current.output.folder)
    notes = sorted(output_dir.glob("*.md"))
    processed = 0
    skipped = 0
    for path in notes:
        parsed = parse_note_content(path.read_text(encoding="utf-8"))
        if not parsed.transcript:
            continue

        # Parse enriched_at once from already-read content
        enriched_at = get_enriched_at_from_frontmatter(parsed.frontmatter)

        # Skip already-enriched notes unless --force or --since is set
        if not force and since is None and enriched_at is not None:
            skipped += 1
            continue

        # With --since, skip notes enriched after the cutoff
        if since is not None and enriched_at is not None:
            # Ensure timezone-aware comparison
            since_aware = since.replace(tzinfo=UTC) if since.tzinfo is None else since
            try:
                enriched_dt = datetime.fromisoformat(enriched_at)
                if enriched_dt.tzinfo is None:
                    enriched_dt = enriched_dt.replace(tzinfo=UTC)
                if enriched_dt >= since_aware:
                    skipped += 1
                    continue
            except ValueError:
                pass  # Unparseable timestamp; process anyway

        if dry_run:
            status = f"enriched: {enriched_at}" if enriched_at else "not enriched"
            click.echo(f"[dry-run] Would enrich {path.name} ({status})")
            processed += 1
        else:
            enrichment = enrich_note(parsed.summary, parsed.transcript, current)
            apply_note_enrichment(path, enrichment, current)
            processed += 1
            click.echo(f"Enriched {path.name}")

        if limit and processed >= limit:
            break

    if processed == 0:
        click.echo("No transcript notes found.")
    else:
        click.echo(f"Processed: {processed}, Skipped: {skipped}")


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


def _launch_tui() -> None:
    from mt_linux.tui import run_tui

    try:
        run_tui()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc


def _play_sample(path: Path) -> subprocess.Popen[bytes] | None:
    player = shutil.which("paplay") or shutil.which("aplay")
    if player:
        return subprocess.Popen([player, str(path)])
    return None


def _stop_sample_playback(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    except ProcessLookupError:
        pass


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
