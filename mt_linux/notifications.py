from __future__ import annotations

import shutil
import subprocess


def notify(title: str, message: str, *, urgency: str = "normal") -> None:
    command = shutil.which("notify-send")
    if not command:
        return
    subprocess.run([command, "-u", urgency, title, message], check=False)
