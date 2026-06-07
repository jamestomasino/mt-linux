from __future__ import annotations

from pathlib import Path

from mt_linux.config import AppConfig


def bootstrap_local_config(config: AppConfig) -> list[str]:
    config.resolve_path(config.output.folder).mkdir(parents=True, exist_ok=True)
    config.resolve_path(config.speakers.db_path).parent.mkdir(parents=True, exist_ok=True)
    return [
        f"output folder: {config.resolve_path(config.output.folder)}",
        f"speaker db dir: {config.resolve_path(config.speakers.db_path).parent}",
    ]
