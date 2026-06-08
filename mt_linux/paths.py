from __future__ import annotations

import os
from pathlib import Path


def _xdg_dir(env_var: str, default_suffix: str) -> Path:
    base = os.environ.get(env_var)
    if base:
        return Path(base).expanduser()
    return Path.home() / default_suffix


CONFIG_DIR = _xdg_dir("XDG_CONFIG_HOME", ".config") / "mt-linux"
DATA_DIR = _xdg_dir("XDG_DATA_HOME", ".local/share") / "mt-linux"
STATE_DIR = _xdg_dir("XDG_STATE_HOME", ".local/state") / "mt-linux"

CONFIG_FILE = CONFIG_DIR / "config.toml"
JOBS_DIR = DATA_DIR / "jobs"
REVIEW_QUEUE_FILE = DATA_DIR / "review_queue.json"
MEETING_REVIEW_QUEUE_FILE = DATA_DIR / "meeting_review_queue.json"
REVIEW_SAMPLES_DIR = DATA_DIR / "review-samples"
SPEAKERS_DB_FILE = DATA_DIR / "speakers.json"
STATE_FILE = STATE_DIR / "daemon_state.json"
CONTROL_REQUEST_FILE = STATE_DIR / "control_request.json"


def ensure_directories() -> None:
    for path in (CONFIG_DIR, DATA_DIR, STATE_DIR, JOBS_DIR, REVIEW_SAMPLES_DIR):
        path.mkdir(parents=True, exist_ok=True)
