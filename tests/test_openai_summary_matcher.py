from datetime import UTC, datetime
import sys
import types

from mt_linux.config import OpenAIConfig
from mt_linux.detection.openai_summary_matcher import OpenAISummaryMatcher
from mt_linux.models import CalendarEvent, MeetingInfo


def test_openai_summary_matcher_returns_high_confidence_choice(monkeypatch):
    config = OpenAIConfig(enabled=True, api_key="test-key", model="gpt-test")
    matcher = OpenAISummaryMatcher(config)
    candidates = [
        CalendarEvent(
            event_id="event-1",
            title="James/Brandon-Weekly 1:1",
            start_time=datetime(2026, 6, 9, 17, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 9, 17, 30, tzinfo=UTC),
            response_status="accepted",
        )
    ]

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"event_id":"event-1","confidence":"high",'
                                '"rationale":"Names line up.","ordered_event_ids":["event-1"]}'
                            )
                        }
                    }
                ]
            }

    fake_httpx = types.SimpleNamespace(post=lambda *args, **kwargs: _Response())
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    decision = matcher.match(
        "James and Brandon discussed weekly priorities.",
        MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 9, 17, 41, tzinfo=UTC),
        ),
        candidates,
    )
    assert decision.event_id == "event-1"
    assert decision.confidence == "high"
    assert decision.ordered_event_ids == ["event-1"]
