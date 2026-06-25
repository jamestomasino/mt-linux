import os

from mt_linux.config import AppConfig, expand_path
from mt_linux.paths import DATA_DIR


def test_expand_path_resolves_env_and_home(monkeypatch):
    monkeypatch.setenv("SYNCTHING_PATH", "/tmp/sync-root")
    resolved = expand_path("${SYNCTHING_PATH}/transcripts")
    assert str(resolved) == "/tmp/sync-root/transcripts"

    home_resolved = expand_path("~/notes")
    assert str(home_resolved).endswith("/notes")


def test_speaker_db_defaults_to_xdg_data_dir():
    config = AppConfig()
    assert config.speakers.db_path == str(DATA_DIR / "speakers.json")


def test_output_audio_is_deleted_by_default_after_processing():
    config = AppConfig()
    assert config.output.keep_audio is False
