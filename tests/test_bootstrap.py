from pathlib import Path

from mt_linux.bootstrap import bootstrap_local_config
from mt_linux.config import AppConfig


def test_bootstrap_local_config_creates_runtime_directories(tmp_path: Path):
    config = AppConfig()
    config.output.folder = str(tmp_path / "transcripts")
    config.speakers.db_path = str(tmp_path / "data" / "speakers.json")
    notes = bootstrap_local_config(config)
    assert (tmp_path / "transcripts").exists()
    assert (tmp_path / "data").exists()
    assert len(notes) == 2
