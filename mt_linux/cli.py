from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
import shutil
import subprocess
import uuid

import click

from mt_linux.audio.wav import wav_duration_minutes
from mt_linux.bootstrap import bootstrap_local_config
from mt_linux.config import AppConfig
from mt_linux.corpus import export_markdown_corpus
from mt_linux.daemon import MeetingPipeline
from mt_linux.detection.google_auth import run_google_auth
from mt_linux.diarization.speaker_matcher import SpeakerMatcher
from mt_linux.doctor import run_doctor, summarize_results
from mt_linux.models import Attendee, CalendarEvent, MeetingInfo
from mt_linux.output.markdown import output_path_for
from mt_linux.output.transcript_patch import (
    apply_meeting_assignment,
    clear_meeting_assignment,
    replace_speaker_label,
)
from mt_linux.paths import STATE_FILE, ensure_directories
from mt_linux.pipeline.job import PipelineJob
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


@cli.command()
def jobs() -> None:
    """List persisted jobs."""
    store = JobSnapshotStore()
    pending = store.load_pending()
    if not pending:
        click.echo("No pending jobs.")
        return
    for job in pending:
        click.echo(f"{job.session_id}  {job.status.value}  {job.meeting_info.title or job.meeting_info.app}")


@cli.command()
def doctor() -> None:
    """Validate local runtime requirements and config."""
    results = run_doctor(AppConfig.load())
    for item in results:
        click.echo(f"[{item.status.upper()}] {item.name}: {item.detail}")
    ok, warn, fail = summarize_results(results)
    click.echo(f"Summary: {ok} ok, {warn} warn, {fail} fail")
    if fail:
        raise SystemExit(1)


@cli.command("bootstrap-config")
def bootstrap_config() -> None:
    """Create local runtime directories based on the current config."""
    notes = bootstrap_local_config(AppConfig.load())
    for note in notes:
        click.echo(note)


@cli.command("process-jobs")
def process_jobs() -> None:
    """Process pending jobs without running the long-lived daemon."""
    store = JobSnapshotStore()
    pending = store.load_pending()
    if not pending:
        click.echo("No pending jobs.")
        return
    pipeline = MeetingPipeline(AppConfig.load(), store=store)
    for job in pending:
        asyncio.run(pipeline.process(job))
        click.echo(f"Processed {job.session_id}")


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
    queue = ReviewQueue()
    entries = queue.load()
    if session_id:
        entries = [entry for entry in entries if entry.session_id == session_id]
    if not entries:
        click.echo("No review entries found.")
        return
    for entry in entries:
        click.echo(f"Meeting: {entry.meeting_title or 'Untitled'} ({entry.meeting_date.isoformat()})")
        click.echo(f"Speaker: {entry.speaker_label}")
        _play_sample(entry.sample_path)
        choice = click.prompt("Name (leave empty to skip)", default="", show_default=False)
        if not choice:
            continue
        replace_speaker_label(entry.transcript_path, entry.speaker_label, choice)
        queue.remove(entry.session_id, entry.speaker_label)
        if entry.sample_path.exists():
            entry.sample_path.unlink()
        click.echo(f"Identified as {choice}")


@cli.group("review-meetings", invoke_without_command=True)
@click.pass_context
def review_meetings(ctx: click.Context) -> None:
    """Review ambiguous meeting assignments."""
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
        for index, candidate in enumerate(entry.candidates, start=1):
            click.echo(
                f"{index}) {candidate.title} "
                f"{format_candidate_summary(candidate, entry.detected_start_time or candidate.start_time)}"
            )
            if candidate.attendees:
                click.echo(f"   attendees: {', '.join(attendee.display() for attendee in candidate.attendees[:5])}")
        click.echo("n) None of these / ad-hoc meeting")
        raw_choice = click.prompt("Select event number, n, or blank to skip", default="", show_default=False)
        if not raw_choice:
            continue
        if raw_choice.lower() == "n":
            clear_meeting_assignment(
                entry.transcript_path,
                candidates=entry.candidates,
                reason="external",
            )
            queue.remove(entry.session_id)
            click.echo("Marked as non-calendar / ad-hoc meeting")
            continue
        if not raw_choice.isdigit():
            click.echo("Invalid choice; expected an event number, n, or blank.")
            continue
        choice_index = int(raw_choice) - 1
        if choice_index < 0 or choice_index >= len(entry.candidates):
            click.echo("Invalid choice; event number is out of range.")
            continue
        candidate = entry.candidates[choice_index]
        apply_meeting_assignment(
            entry.transcript_path,
            selected_event=candidate,
            candidates=entry.candidates,
            ambiguous=False,
        )
        queue.remove(entry.session_id)
        click.echo(f"Assigned to {candidate.title}")


@cli.command()
@click.argument("audio_file", type=click.Path(path_type=Path, exists=True))
@click.option("--title", default="")
@click.option("--app", default="import")
def import_(audio_file: Path, title: str, app: str) -> None:
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
    current = AppConfig.load()
    output_dir = current.resolve_path(current.output.folder)
    try:
        corpus_path = export_markdown_corpus(output_dir, format_name=format_name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(str(corpus_path))


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
