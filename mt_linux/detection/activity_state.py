from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass
class ActivityTransition:
    started: tuple[str, int, int] | None = None
    ended: tuple[str, int, int] | None = None


class MeetingActivityState:
    def __init__(self, grace_period_seconds: int = 15):
        self.grace_period = timedelta(seconds=grace_period_seconds)
        self.active: tuple[str, int, int] | None = None
        self.last_seen_active_at: datetime | None = None

    def update(
        self,
        observed_active: tuple[str, int, int] | None,
        now: datetime | None = None,
    ) -> ActivityTransition:
        current_time = now or datetime.now(UTC)
        if observed_active is not None:
            self.last_seen_active_at = current_time
            if self.active is None:
                self.active = observed_active
                return ActivityTransition(started=observed_active)
            self.active = observed_active
            return ActivityTransition()

        if self.active is None or self.last_seen_active_at is None:
            return ActivityTransition()
        if current_time - self.last_seen_active_at < self.grace_period:
            return ActivityTransition()
        ended = self.active
        self.active = None
        self.last_seen_active_at = None
        return ActivityTransition(ended=ended)
