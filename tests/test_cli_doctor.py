from click.testing import CliRunner

from mt_linux.cli import cli
from mt_linux.doctor import CheckResult


def test_cli_doctor_exits_nonzero_on_failures(monkeypatch):
    monkeypatch.setattr(
        "mt_linux.cli.run_doctor",
        lambda config: [CheckResult("audio.recorder", "fail", "missing")],
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 1
    assert "[FAIL] audio.recorder: missing" in result.output
