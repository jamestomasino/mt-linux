from datetime import UTC, datetime

from mt_linux.detection.caldav_client import CalDAVCalendarClient


class _FakeValue:
    def __init__(self, value, params=None):
        self.value = value
        self.params = params or {}


class _FakeVEvent:
    def __init__(self, uid, summary, start, end, organizer, attendees):
        self.uid = _FakeValue(uid)
        self.summary = _FakeValue(summary)
        self.dtstart = _FakeValue(start)
        self.dtend = _FakeValue(end)
        self.organizer = _FakeValue(organizer, {"CN": "Alice Smith"})
        self.attendee = [
            _FakeValue("mailto:bob@example.com", {"CN": "Bob"}),
            _FakeValue("mailto:carol@example.com", {"CN": "Carol"}),
        ]


class _FakeICalendar:
    def __init__(self, vevent):
        self.vevent = vevent


class _FakeEvent:
    def __init__(self, vevent):
        self.icalendar_instance = _FakeICalendar(vevent)


class _FakeCalendar:
    def __init__(self, events):
        self.events = events

    def search(self, **kwargs):
        return self.events


def test_caldav_client_picks_event_closest_to_now():
    events = [
        _FakeEvent(
            _FakeVEvent(
                "later",
                "Later Meeting",
                datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                datetime(2026, 6, 7, 15, 30, tzinfo=UTC),
                "mailto:alice@example.com",
                [],
            )
        ),
        _FakeEvent(
            _FakeVEvent(
                "current",
                "Current Meeting",
                datetime(2026, 6, 7, 14, 25, tzinfo=UTC),
                datetime(2026, 6, 7, 14, 55, tzinfo=UTC),
                "mailto:alice@example.com",
                [],
            )
        ),
    ]
    client = CalDAVCalendarClient("https://calendar.example.com")
    client._calendar = _FakeCalendar(events)
    event = client.get_current_meeting(datetime(2026, 6, 7, 14, 30, tzinfo=UTC))
    assert event is not None
    assert event.event_id == "current"
    assert event.organizer == "Alice Smith"
    assert [item.display() for item in event.attendees] == [
        "Bob <bob@example.com>",
        "Carol <carol@example.com>",
    ]


def test_caldav_client_get_attendees():
    event = _FakeEvent(
        _FakeVEvent(
            "current",
            "Current Meeting",
            datetime(2026, 6, 7, 14, 25, tzinfo=UTC),
            datetime(2026, 6, 7, 14, 55, tzinfo=UTC),
            "mailto:alice@example.com",
            [],
        )
    )
    client = CalDAVCalendarClient("https://calendar.example.com")
    client._calendar = _FakeCalendar([event])
    attendees = client.get_attendees("current")
    assert attendees == ["Bob <bob@example.com>", "Carol <carol@example.com>"]
