from __future__ import annotations

import json
import subprocess


def create_virtual_sink(sink_name: str) -> tuple[str, str]:
    result = subprocess.run(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            f"sink_name={sink_name}",
            f"sink_properties=device.description={sink_name}",
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    module_id = result.stdout.strip()
    return f"{sink_name}.monitor", module_id


def route_app_to_sink(app_pid: int, sink_name: str) -> None:
    result = subprocess.run(["pw-dump"], capture_output=True, check=True, text=True)
    nodes = json.loads(result.stdout)
    for node in nodes:
        props = node.get("info", {}).get("props", {})
        if str(props.get("application.process.id")) != str(app_pid):
            continue
        node_id = node.get("id")
        if node_id is None:
            continue
        subprocess.run(
            [
                "pw-cli",
                "set-param",
                str(node_id),
                "Props",
                f"{{ target.object = {sink_name} }}",
            ],
            check=False,
        )


def unload_module(module_id: str) -> None:
    subprocess.run(["pactl", "unload-module", module_id], check=False)
