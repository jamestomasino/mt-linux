from __future__ import annotations

import re


BROWSER_MEETING_TITLE_PATTERNS = [
    r"Google Meet",
    r"^Meet - ",
]


def is_meeting_title(title: str) -> bool:
    return any(re.search(pattern, title, re.IGNORECASE) for pattern in BROWSER_MEETING_TITLE_PATTERNS)
