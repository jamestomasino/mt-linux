from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
import os
from pathlib import Path
from typing import Any
import tomllib

from mt_linux.paths import CONFIG_FILE, CONFIG_DIR, SPEAKERS_DB_FILE, ensure_directories


@dataclass
class AudioConfig:
    mic_device_name: str = ""
    app_audio_backend: str = "pipewire"
    system_source_name: str = ""


@dataclass
class DetectionConfig:
    poll_interval_seconds: int = 5
    grace_period_seconds: int = 5
    apps_to_watch: list[str] = field(
        default_factory=lambda: ["zoom", "teams", "webex", "meet", "slack"]
    )
    require_process_match: bool = True


@dataclass
class CalendarConfig:
    enabled: bool = True
    backend: str = "google"
    credentials_path: str = str(CONFIG_DIR / "google_credentials.json")
    token_path: str = str(CONFIG_DIR / "google_token.json")
    lookup_window_minutes: int = 10
    caldav_url: str = ""
    caldav_username: str = ""
    caldav_password: str = ""
    caldav_calendar_name: str = ""


@dataclass
class TranscriptionConfig:
    engine: str = "faster-whisper"
    model: str = "large-v3-turbo"
    device: str = "auto"
    compute_type: str = "int8"
    language: str = ""


@dataclass
class DiarizationConfig:
    enabled: bool = True
    hf_token: str = ""
    backend: str = "pyannote"


@dataclass
class SpeakersConfig:
    db_path: str = str(SPEAKERS_DB_FILE)
    similarity_threshold: float = 0.82
    mic_speaker_name: str = ""


@dataclass
class ProtocolConfig:
    enabled: bool = False
    endpoint: str = "http://localhost:11434/v1/chat/completions"
    model: str = "llama3.1"
    prompt_path: str = ""
    language: str = "en"
    use_gpu: bool = True


@dataclass
class OpenAIConfig:
    enabled: bool = False
    api_key: str = ""
    endpoint: str = "https://api.openai.com/v1/chat/completions"
    model: str = ""


@dataclass
class EnrichmentConfig:
    enabled: bool = True
    entity_catalog_path: str = str(CONFIG_DIR / "entities.toml")
    entity_notes_root: str = ""


@dataclass
class OutputConfig:
    folder: str = str(Path.home() / "Documents/meetings")
    vault_root: str = ""
    tag_style: str = "flat"
    keep_audio: bool = True
    audio_subfolder: str = "audio"


@dataclass
class AppConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    calendar: CalendarConfig = field(default_factory=CalendarConfig)
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    diarization: DiarizationConfig = field(default_factory=DiarizationConfig)
    speakers: SpeakersConfig = field(default_factory=SpeakersConfig)
    protocol: ProtocolConfig = field(default_factory=ProtocolConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    enrichment: EnrichmentConfig = field(default_factory=EnrichmentConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> "AppConfig":
        ensure_directories()
        if not path.exists():
            config = cls()
            config.save(path)
            return config
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        return _merge_dataclass(cls(), data)

    def save(self, path: Path = CONFIG_FILE) -> None:
        ensure_directories()
        path.write_text(_to_toml(asdict(self)), encoding="utf-8")

    def set_value(self, dotted_key: str, raw_value: str) -> None:
        parts = dotted_key.split(".")
        target: Any = self
        for part in parts[:-1]:
            target = getattr(target, part)
        leaf = parts[-1]
        current = getattr(target, leaf)
        setattr(target, leaf, _coerce_value(raw_value, current))

    def resolve_path(self, raw_path: str) -> Path:
        return expand_path(raw_path)


def expand_path(raw_path: str) -> Path:
    return Path(os.path.expandvars(raw_path)).expanduser()


def _merge_dataclass(instance: Any, data: dict[str, Any]) -> Any:
    for field_info in fields(instance):
        name = field_info.name
        if name not in data:
            continue
        current = getattr(instance, name)
        incoming = data[name]
        if is_dataclass(current):
            setattr(instance, name, _merge_dataclass(current, incoming))
        else:
            setattr(instance, name, incoming)
    return instance


def _coerce_value(raw: str, current: Any) -> Any:
    if isinstance(current, bool):
        return raw.lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int) and not isinstance(current, bool):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    if isinstance(current, list):
        return [part.strip() for part in raw.split(",") if part.strip()]
    return raw


def _to_toml(data: dict[str, Any], prefix: str = "") -> str:
    lines: list[str] = []
    scalars: list[tuple[str, Any]] = []
    tables: list[tuple[str, dict[str, Any]]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            tables.append((key, value))
        else:
            scalars.append((key, value))
    if prefix:
        lines.append(f"[{prefix}]")
    for key, value in scalars:
        lines.append(f"{key} = {_toml_value(value)}")
    if scalars and tables:
        lines.append("")
    for index, (key, value) in enumerate(tables):
        full_prefix = f"{prefix}.{key}" if prefix else key
        lines.append(_to_toml(value, full_prefix).rstrip())
        if index != len(tables) - 1:
            lines.append("")
    return "\n".join(line for line in lines if line is not None).rstrip() + "\n"


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
