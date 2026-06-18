from datetime import UTC, datetime, timedelta

from mt_linux.detection.activity_state import MeetingActivityState


def test_activity_state_waits_for_grace_period_before_end():
    state = MeetingActivityState(grace_period_seconds=15)
    start = datetime(2026, 6, 7, 14, 30, tzinfo=UTC)
    first = state.update(("zoom", 100, 1), now=start)
    assert first.started == ("zoom", 100, 1)

    no_end = state.update(None, now=start + timedelta(seconds=10))
    assert no_end.ended is None

    ended = state.update(None, now=start + timedelta(seconds=16))
    assert ended.ended == ("zoom", 100, 1)


def test_activity_state_ignores_repeated_same_activity():
    state = MeetingActivityState(grace_period_seconds=15)
    start = datetime(2026, 6, 7, 14, 30, tzinfo=UTC)
    state.update(("zoom", 100, 1), now=start)
    repeated = state.update(("zoom", 100, 1), now=start + timedelta(seconds=5))
    assert repeated.started is None
    assert repeated.ended is None


def test_activity_state_does_not_restart_when_stream_identity_changes_mid_meeting():
    state = MeetingActivityState(grace_period_seconds=15)
    start = datetime(2026, 6, 7, 14, 30, tzinfo=UTC)
    first = state.update(("zoom", 100, 1), now=start)
    assert first.started == ("zoom", 100, 1)
    changed = state.update(("zoom", 100, 2), now=start + timedelta(seconds=5))
    assert changed.started is None
    assert changed.ended is None


def test_activity_state_switches_immediately_when_meeting_process_changes():
    state = MeetingActivityState(grace_period_seconds=15)
    start = datetime(2026, 6, 7, 14, 30, tzinfo=UTC)
    first = state.update(("zoom", 100, 1), now=start)
    assert first.started == ("zoom", 100, 1)

    switched = state.update(("teams", 200, 9), now=start + timedelta(seconds=5))
    assert switched.ended == ("zoom", 100, 1)
    assert switched.started == ("teams", 200, 9)
