from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import time
import uuid

from mt_linux.paths import CONTROL_REQUEST_FILE, STATE_FILE, ensure_directories


@dataclass
class ControlRequest:
    request_id: str
    action: str
    title: str = ""
    app: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, str]:
        data = asdict(self)
        if not data["created_at"]:
            data["created_at"] = datetime.now(UTC).isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "ControlRequest":
        return cls(
            request_id=data["request_id"],
            action=data["action"],
            title=data.get("title", ""),
            app=data.get("app", ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class ControlResult:
    request_id: str
    status: str
    message: str
    session_id: str = ""
    recorded_at: str = ""

    def to_dict(self) -> dict[str, str]:
        data = asdict(self)
        if not data["recorded_at"]:
            data["recorded_at"] = datetime.now(UTC).isoformat()
        return data


def build_request(action: str, *, title: str = "", app: str = "") -> ControlRequest:
    return ControlRequest(
        request_id=str(uuid.uuid4()),
        action=action,
        title=title,
        app=app,
    )


def write_request(request: ControlRequest, path: Path = CONTROL_REQUEST_FILE) -> Path:
    ensure_directories()
    if path.exists():
        raise RuntimeError("Another control request is already pending.")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(request.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def read_request(path: Path = CONTROL_REQUEST_FILE) -> ControlRequest | None:
    if not path.exists():
        return None
    return ControlRequest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def clear_request(path: Path = CONTROL_REQUEST_FILE) -> None:
    if path.exists():
        path.unlink()


def wait_for_result(request_id: str, *, timeout_seconds: float = 15.0, poll_seconds: float = 0.2) -> ControlResult | None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if STATE_FILE.exists():
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            result = state.get("last_control_result")
            if isinstance(result, dict) and result.get("request_id") == request_id:
                return ControlResult(
                    request_id=result["request_id"],
                    status=result["status"],
                    message=result["message"],
                    session_id=result.get("session_id", ""),
                    recorded_at=result.get("recorded_at", ""),
                )
        time.sleep(poll_seconds)
    return None
