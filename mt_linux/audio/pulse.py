from __future__ import annotations

import json
import subprocess
import time


def get_default_sink_name() -> str:
    result = subprocess.run(
        ["pactl", "get-default-sink"],
        capture_output=True,
        text=True,
        check=False,
    )
    sink_name = result.stdout.strip()
    if result.returncode != 0 or not sink_name:
        raise RuntimeError("Could not determine default sink from pactl")
    return sink_name


def get_system_capture_source_name(explicit_source_name: str = "") -> str:
    source_name = explicit_source_name.strip()
    if source_name:
        return source_name
    return f"{get_default_sink_name()}.monitor"


def get_preferred_system_capture_source_name(
    app_pid: int,
    explicit_source_name: str = "",
    retries: int = 6,
    retry_delay_seconds: float = 0.5,
) -> str:
    source_name = explicit_source_name.strip()
    if source_name:
        return source_name
    for attempt in range(max(retries, 1)):
        sink_name = _sink_name_for_app_pid(app_pid)
        if sink_name:
            return f"{sink_name}.monitor"
        if attempt < retries - 1:
            time.sleep(retry_delay_seconds)
    return get_system_capture_source_name()


def _sink_name_for_app_pid(app_pid: int) -> str | None:
    sink_inputs = _pactl_json_list("sink-inputs")
    sink_index = None
    for item in sink_inputs:
        props = item.get("properties", {})
        if str(props.get("application.process.id", "")) == str(app_pid):
            sink_index = item.get("sink")
            break
    if sink_index is None:
        return None
    sinks = _pactl_json_list("sinks")
    for sink in sinks:
        if sink.get("index") == sink_index:
            props = sink.get("properties", {})
            return props.get("node.name") or sink.get("name")
    return None


def _pactl_json_list(kind: str) -> list[dict]:
    result = subprocess.run(
        ["pactl", "-f", "json", "list", kind],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return data
    return []
