from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import shutil
import subprocess

from mt_linux.config import AppConfig
from mt_linux.transcription.runtime import cuda_available, resolve_device


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def run_doctor(config: AppConfig) -> list[CheckResult]:
    results: list[CheckResult] = []
    results.extend(_check_paths(config))
    results.extend(_check_audio_runtime())
    results.extend(_check_transcription_runtime(config))
    results.extend(_check_diarization_runtime(config))
    results.extend(_check_calendar_runtime(config))
    return results


def summarize_results(results: list[CheckResult]) -> tuple[int, int, int]:
    ok = sum(1 for item in results if item.status == "ok")
    warn = sum(1 for item in results if item.status == "warn")
    fail = sum(1 for item in results if item.status == "fail")
    return ok, warn, fail


def _check_paths(config: AppConfig) -> list[CheckResult]:
    results = []
    output_dir = config.resolve_path(config.output.folder)
    speaker_db = config.resolve_path(config.speakers.db_path)
    results.append(_writable_path_check("output.folder", output_dir))
    results.append(_writable_path_check("speakers.db_path", speaker_db.parent))
    return results


def _check_audio_runtime() -> list[CheckResult]:
    results = []
    pactl = shutil.which("pactl")
    pw_dump = shutil.which("pw-dump")
    recorder = shutil.which("pw-record") or shutil.which("parecord")
    results.append(
        CheckResult("audio.pactl", "ok" if pactl else "warn", pactl or "pactl not found")
    )
    results.append(
        CheckResult("audio.pw-dump", "ok" if pw_dump else "warn", pw_dump or "pw-dump not found")
    )
    results.append(
        CheckResult(
            "audio.recorder",
            "ok" if recorder else "fail",
            recorder or "Neither pw-record nor parecord is available",
        )
    )
    results.append(_command_probe("audio.server", ["pactl", "info"]))
    return results


def _check_transcription_runtime(config: AppConfig) -> list[CheckResult]:
    results = [_module_check("transcription.faster_whisper", "faster_whisper", required=True)]
    if config.transcription.engine != "faster-whisper":
        results.append(CheckResult("transcription.engine", "warn", f"Unsupported engine: {config.transcription.engine}"))
    else:
        results.append(CheckResult("transcription.engine", "ok", config.transcription.model))
    requested_device = config.transcription.device
    resolved_device = resolve_device(requested_device)
    if requested_device.strip().lower() == "cpu" and cuda_available():
        results.append(
            CheckResult(
                "transcription.device",
                "warn",
                'Configured for cpu while CUDA is available. Set transcription.device to "auto" or "cuda".',
            )
        )
    elif requested_device.strip().lower() == "cuda" and not cuda_available():
        results.append(
            CheckResult(
                "transcription.device",
                "warn",
                'Configured for cuda but CUDA is not available. Falling back requires transcription.device = "auto" or "cpu".',
            )
        )
    else:
        detail = f"{requested_device or 'auto'} -> {resolved_device}"
        results.append(CheckResult("transcription.device", "ok", detail))
    return results


def _check_diarization_runtime(config: AppConfig) -> list[CheckResult]:
    results = []
    if not config.diarization.enabled:
        results.append(CheckResult("diarization.enabled", "warn", "Diarization is disabled"))
        return results
    results.append(_module_check("diarization.pyannote", "pyannote.audio", required=True))
    results.append(_module_check("diarization.resemblyzer", "resemblyzer", required=True))
    results.append(
        CheckResult(
            "diarization.device",
            "ok",
            "cuda" if cuda_available() else "cpu",
        )
    )
    if config.diarization.hf_token:
        results.append(CheckResult("diarization.hf_token", "ok", "Configured"))
    else:
        results.append(CheckResult("diarization.hf_token", "warn", "Not configured"))
    return results


def _check_calendar_runtime(config: AppConfig) -> list[CheckResult]:
    results = []
    if not config.calendar.enabled or config.calendar.backend == "none":
        return [CheckResult("calendar.enabled", "warn", "Calendar enrichment disabled")]
    if config.calendar.backend == "google":
        results.append(_module_check("calendar.google_auth", "google_auth_oauthlib", required=True))
        token_path = config.resolve_path(config.calendar.token_path)
        results.append(
            CheckResult(
                "calendar.google_token",
                "ok" if token_path.exists() else "warn",
                str(token_path) if token_path.exists() else f"Missing token at {token_path}",
            )
        )
        return results
    if config.calendar.backend == "caldav":
        results.append(_module_check("calendar.caldav", "caldav", required=True))
        status = "ok" if config.calendar.caldav_url else "warn"
        detail = config.calendar.caldav_url or "caldav_url is not configured"
        results.append(CheckResult("calendar.caldav_url", status, detail))
        return results
    return [CheckResult("calendar.backend", "warn", f"Unknown backend: {config.calendar.backend}")]


def _module_check(name: str, module_name: str, required: bool) -> CheckResult:
    try:
        found = importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        found = False
    if found:
        return CheckResult(name, "ok", module_name)
    return CheckResult(name, "fail" if required else "warn", f"{module_name} not installed")


def _writable_path_check(name: str, path: Path) -> CheckResult:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return CheckResult(name, "fail", str(exc))
    return CheckResult(name, "ok", str(path))


def _command_probe(name: str, command: list[str]) -> CheckResult:
    executable = shutil.which(command[0])
    if not executable:
        return CheckResult(name, "warn", f"{command[0]} not found")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return CheckResult(name, "ok", (result.stdout.strip() or "available")[:120])
    detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
    return CheckResult(name, "warn", detail[:120])
