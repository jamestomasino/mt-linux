from __future__ import annotations

import shutil
import subprocess


def notify(title: str, message: str) -> None:
    command = shutil.which("notify-send")
    if not command:
        return
    subprocess.run([command, title, message], check=False)
