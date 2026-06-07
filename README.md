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

## Installation

Recommended install on Ubuntu and other externally-managed Python systems:

```bash
pipx install --force --editable .
scripts/setup.sh
```

If you are working inside your own virtualenv, editable `pip` install is also fine:

```bash
python3 -m pip install -e .
```

Development extras in a virtualenv:

```bash
python3 -m pip install -e '.[dev]'
```

Why `pipx` is the default:

- Ubuntu system Python commonly blocks direct editable installs with PEP 668
- `pipx` installs `mt-ctl` and `mt-linux` into isolated user environments
- the console scripts are then available on `~/.local/bin`

The setup script:

- installs the package with `pipx`
- copies the `systemd` user service
- creates local config/data/state directories
- runs local bootstrap
- runs `mt-ctl doctor`

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
- `speakers.mic_speaker_name`: your display name
- `calendar.backend`: `google`, `caldav`, or `none`
- `calendar.lookup_window_minutes`: candidate lookup window
- `transcription.model`: Whisper model name
- `diarization.hf_token`: Hugging Face token for pyannote
- `protocol.enabled`: enable or disable local LLM summary generation

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
mt-ctl jobs
mt-ctl process-jobs
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

## Runtime Notes

- Heavy runtime integrations are imported lazily in code paths, but the intended install now includes the full local transcription/diarization/calendar stack by default.
- Recordings, review clips, speaker profiles, and job snapshots are intentionally stored under XDG data paths, not in your transcript directory.
- `mt-ctl doctor` is the fastest way to see what is missing on a new machine.

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
