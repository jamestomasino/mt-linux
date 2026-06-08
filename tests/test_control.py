import json

from mt_linux.control import ControlRequest, build_request, read_request, write_request


def test_control_request_round_trip(tmp_path):
    path = tmp_path / "control.json"
    request = ControlRequest(
        request_id="req-1",
        action="start",
        title="Ad Hoc",
        app="slack",
        created_at="2026-06-08T12:00:00+00:00",
    )
    write_request(request, path=path)
    restored = read_request(path=path)
    assert restored == request


def test_build_request_populates_identity():
    request = build_request("stop")
    assert request.action == "stop"
    assert request.request_id
    payload = request.to_dict()
    assert payload["created_at"]
    json.dumps(payload)
