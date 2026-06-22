# mt-linux

`mt-linux` is a Linux-native meeting transcriber for desktop meeting apps. It runs as a `systemd --user` service, detects active meetings from audio activity, records app audio plus microphone audio, transcribes the session, applies diarization and speaker matching when available, and writes Obsidian-friendly Markdown notes with YAML frontmatter.

The current design is focused on:

- Linux desktop use with PipeWire/Pulse compatibility
- Background operation with CLI control
- Obsidian-compatible transcript output
- Local XDG storage for recordings, profiles, queues, and state
- Review workflows for unresolved speakers and ambiguous calendar matches

## What It Does

`mt-linux` can:

- detect active meetings from Zoom/Teams/Meet-style audio activity
- enrich sessions from Google Calendar or CalDAV
- rank overlapping calendar candidates and flag ambiguous matches
- record separate app and mic WAV files
- transcribe imported or recorded WAV files
- process jobs in resumable stages so transcription and diarization do not have to restart from scratch after an interruption
- match known speakers from stored voice profiles
- queue speaker review for unknown voices
- queue meeting review when the calendar match is ambiguous
- export generated Markdown notes as a JSONL corpus

## Repository Layout

Important paths in the repo:

- `mt_linux/`: application package
- `systemd/mt-linux.service`: user service unit
- `scripts/setup.sh`: local install/bootstrap helper
- `tests/`: automated coverage

Important runtime paths outside the repo:

- `~/.config/mt-linux/config.toml`: local config
- `~/.local/share/mt-linux/audio/`: recorded WAV files
- `~/.local/share/mt-linux/speakers.json`: speaker profile database
- `~/.local/share/mt-linux/review-samples/`: temporary speaker review clips
- `~/.local/share/mt-linux/review_queue.json`: speaker review queue
- `~/.local/share/mt-linux/meeting_review_queue.json`: meeting review queue
- `~/.local/share/mt-linux/jobs/`: persisted pipeline jobs
- `~/.local/state/mt-linux/daemon_state.json`: daemon state snapshot
- `~/.local/state/mt-linux/control_request.json`: one-shot manual control request file

## Installation

Recommended runtime install on Ubuntu and other externally-managed Python systems:

```bash
pipx install --force --editable .
scripts/setup.sh
```

Recommended development environment in the repo checkout:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

If you want the heavier tooling in the repo-local environment as well, use:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

If you are already working inside your own virtualenv, editable `pip` install is also fine:

```bash
python3 -m pip install -e .
```

Why `pipx` is the default:

- Ubuntu system Python commonly blocks direct editable installs with PEP 668
- `pipx` installs `mt-ctl` and `mt-linux` into isolated user environments
- the console scripts are then available on `~/.local/bin`
- it is the right target for the `systemd` user service

The setup script:

- installs the package with `pipx`
- copies the `systemd` user service
- creates local config/data/state directories
- runs local bootstrap
- runs `mt-ctl doctor`

Recommended split:

- use `pipx` for the installed app and the `systemd` user service
- use `.venv` for repo-local development, tests, and ad hoc scripts
- avoid installing directly into the system Python

## Dependencies

The default install is intended to provide the full local runtime:

- `faster-whisper` for transcription
- `pyannote.audio` for diarization
- `resemblyzer` for speaker matching
- Google Calendar and CalDAV client libraries

Some features still require credentials or model access configuration after install:

- Google OAuth client credentials and token
- Hugging Face token for `pyannote/speaker-diarization-3.1`
- optional Ollama setup if you want local LLM summaries

Useful system packages on Ubuntu-like systems:

```bash
sudo apt install -y pipewire-bin pipewire-pulse pulseaudio-utils libnotify-bin ffmpeg sox
```

## Configuration

Configuration lives at `~/.config/mt-linux/config.toml`.

Show current config:

```bash
mt-ctl config show
```

Set values:

```bash
mt-ctl config set speakers.mic_speaker_name "Your Name"
mt-ctl config set output.folder "${SYNCTHING_PATH}/transcripts"
```

Paths support environment-variable expansion, so values like `${SYNCTHING_PATH}/transcripts` are valid.

Common settings:

- `output.folder`: Markdown output directory
- `output.vault_root`: optional Obsidian vault root for relative audio paths
- `audio.mic_device_name`: physical microphone source name to record
- `audio.system_source_name`: optional explicit system-audio monitor source
- `speakers.mic_speaker_name`: your display name
- `detection.grace_period_seconds`: how long to keep a meeting alive after audio drops
- `calendar.backend`: `google`, `caldav`, or `none`
- `calendar.lookup_window_minutes`: candidate lookup window
- `transcription.model`: Whisper model name
- `transcription.device`: `auto`, `cuda`, or `cpu`
- `diarization.hf_token`: Hugging Face token for pyannote
- `protocol.enabled`: enable or disable local LLM summary generation

Audio capture behavior:

- the microphone track should point at a real hardware input source, not a virtual loopback source
- on meeting start, `mt-linux` tries to capture the meeting app's specific playback sink first
- if app-specific sink detection fails, it falls back to the current default sink monitor so recording still succeeds
- if `audio.system_source_name` is set, that source is used directly instead of auto-detection
- if a different meeting app or PID appears, `mt-linux` now forces an immediate handoff instead of waiting for the full grace period

## Calendar Configuration

Google Calendar:

```bash
mt-ctl auth google
```

CalDAV example:

```toml
[calendar]
enabled = true
backend = "caldav"
caldav_url = "https://calendar.example.com/remote.php/dav/"
caldav_username = "you@example.com"
caldav_password = "secret"
caldav_calendar_name = "Work"
```

Calendar matching behavior:

- events without conferencing links are ignored
- platform match is preferred
- accepted events are preferred
- time proximity is used as a fallback
- unresolved conflicts are marked ambiguous and sent to meeting review

## First Run

Recommended sequence:

```bash
mt-ctl doctor
mt-ctl config set speakers.mic_speaker_name "Your Name"
mt-ctl auth google
systemctl --user enable --now mt-linux.service
```

For CalDAV, configure `calendar.backend = "caldav"` and related credentials instead of running Google auth.

Use `systemctl --user`, not `sudo systemctl`, because `mt-linux` is a per-user desktop service and needs access to your user session, PipeWire session, and local credentials.

## CLI Usage

Core control:

```bash
mt-ctl start
mt-ctl stop
mt-ctl status
mt-ctl record start --title "Ad Hoc" --app slack
mt-ctl record stop
mt-ctl record status
mt-ctl jobs
mt-ctl jobs list
mt-ctl jobs cancel <session_id>
mt-ctl jobs cancel --delete-audio <session_id>
mt-ctl process-jobs
mt-ctl cleanup
mt-ctl cleanup --dry-run
mt-ctl cleanup --include-job-history
```

Diagnostics and setup:

```bash
mt-ctl doctor
mt-ctl bootstrap-config
mt-ctl config show
mt-ctl config set output.folder "${SYNCTHING_PATH}/transcripts"
mt-ctl config list-devices
```

Audio import and corpus export:

```bash
mt-ctl import meeting.wav --title "Weekly Standup"
mt-ctl export-corpus --format jsonl
```

Manual ad-hoc recording:

- `mt-ctl record start` asks the running daemon to begin recording immediately, even without auto-detection
- use `--app` to label the source, such as `slack`, `meet`, or `manual`
- use `--title` to set a better session name for the eventual transcript
- `mt-ctl record stop` stops the manual session and queues it for normal staged processing
- `mt-ctl record status` shows the currently active recording session, whether it was auto-detected or started manually

Queued processing behavior:

- pending jobs are persisted under `~/.local/share/mt-linux/jobs/`
- transcription and diarization are treated as separate persisted stages
- if the daemon or machine is interrupted after transcription completes, the restored job resumes from the diarization stage instead of rerunning Whisper
- `mt-ctl process-jobs` also respects this staged behavior and will continue jobs through to completion

Speaker profile management:

```bash
mt-ctl enroll "Alice Smith" sample.wav
mt-ctl review
mt-ctl review list
mt-ctl review run --session <session_id>
```

Meeting assignment review:

```bash
mt-ctl review-meetings
mt-ctl review-meetings list
mt-ctl review-meetings run --session <session_id>
```

Shell completion for `bash`:

```bash
eval "$(_MT_CTL_COMPLETE=bash_source mt-ctl)"
```

For persistent completion in a login-shell setup, add a guarded version of that line to your shell profile.

## Review Workflows

### Speaker Review

Unknown speakers are added to a review queue with short sample clips. During review you can:

- replay the sample
- assign a real name
- update the transcript inline
- grow the speaker profile database over time

### Meeting Review

If multiple calendar events are plausible, `mt-linux` stores all strong candidates and marks the transcript as ambiguous.

During `review-meetings` you see:

- detected app
- detected start time
- recording duration
- identified speakers
- a short transcript preview
- each candidate’s title, conferencing type, response status, start-time delta, organizer, attendee count, attendee preview, and conferencing link domain

You can:

- choose the correct calendar event
- reject all candidates as `None of these / ad-hoc meeting`

Rejecting all candidates clears the event binding and marks the session as an external or ad-hoc meeting instead of forcing a bad calendar assignment.

## Output

Generated notes are Markdown files with YAML frontmatter intended for Obsidian. Frontmatter includes:

- title/date/time
- app
- participants
- organizer
- `calendar_event_id`
- `calendar_match_confidence`
- candidate calendar events when ambiguous
- audio file references
- transcription metadata

The transcript body includes timestamped speaker turns and optional LLM-generated summary sections.

Recorded app audio and mic audio are kept as separate WAV files. For transcription and diarization, `mt-linux` mixes those tracks into a temporary processing WAV so both your voice and remote participants are present in the transcript path.

## Runtime Notes

- Heavy runtime integrations are imported lazily in code paths, but the intended install now includes the full local transcription/diarization/calendar stack by default.
- Recordings, review clips, speaker profiles, and job snapshots are intentionally stored under XDG data paths, not in your transcript directory.
- `mt-ctl doctor` is the fastest way to see what is missing on a new machine.
- `mt-ctl jobs cancel` removes persisted queue entries; use `--delete-audio` if you also want the app/mic/mix recordings removed.
- `mt-ctl cleanup` removes orphaned runtime artifacts. By default it only removes unreferenced WAVs and stale review samples. `--include-job-history` also removes completed and failed job snapshot files before cleaning their now-orphaned audio.

## Testing

Run the test suite with:

```bash
pytest -q
```

Current automated coverage focuses on:

- config and path handling
- queue persistence
- Markdown output
- meeting/session lifecycle
- calendar matching and review queues
- speaker matching and review flows
- CLI review behavior
