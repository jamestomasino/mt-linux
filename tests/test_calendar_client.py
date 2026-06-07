from datetime import UTC, datetime

from mt_linux.detection.calendar_client import GoogleCalendarClient


class _FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _FakeEvents:
    def __init__(self, items, lookup_item):
        self.items = items
        self.lookup_item = lookup_item

    def list(self, **kwargs):
        return _FakeExecute({"items": self.items})

    def get(self, **kwargs):
        return _FakeExecute(self.lookup_item)


class _FakeService:
    def __init__(self, items, lookup_item):
        self._events = _FakeEvents(items, lookup_item)

    def events(self):
        return self._events


def test_google_calendar_client_picks_event_closest_to_now():
    items = [
        {
            "id": "later",
            "summary": "Later Meeting",
            "start": {"dateTime": "2026-06-07T15:00:00Z"},
            "end": {"dateTime": "2026-06-07T15:30:00Z"},
            "organizer": {"displayName": "Alice"},
            "description": "https://princeton.zoom.us/j/456",
            "attendees": [{"displayName": "Bob", "email": "bob@example.com", "self": True, "responseStatus": "tentative"}],
        },
        {
            "id": "current",
            "summary": "Current Meeting",
            "start": {"dateTime": "2026-06-07T14:25:00Z"},
            "end": {"dateTime": "2026-06-07T14:55:00Z"},
            "organizer": {"displayName": "Alice"},
            "description": "https://princeton.zoom.us/j/123",
            "attendees": [{"displayName": "Bob", "email": "bob@example.com", "self": True, "responseStatus": "accepted"}],
        },
    ]
    client = GoogleCalendarClient("creds.json", "token.json")
    client._service = _FakeService(items, items[1])
    event = client.get_current_meeting(datetime(2026, 6, 7, 14, 30, tzinfo=UTC))
    assert event is not None
    assert event.event_id == "current"
    assert event.attendees[0].display() == "Bob <bob@example.com>"
    assert event.conferencing_type == "zoom"
    assert event.response_status == "accepted"


def test_google_calendar_client_get_attendees():
    item = {
        "id": "current",
        "summary": "Current Meeting",
        "start": {"dateTime": "2026-06-07T14:25:00Z"},
        "end": {"dateTime": "2026-06-07T14:55:00Z"},
        "attendees": [{"displayName": "Bob", "email": "bob@example.com"}],
    }
    client = GoogleCalendarClient("creds.json", "token.json")
    client._service = _FakeService([item], item)
    attendees = client.get_attendees("current")
    assert attendees == ["Bob <bob@example.com>"]
