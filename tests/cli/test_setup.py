from typer.testing import CliRunner

from tiqr.cli.commands import app


def _key(text):
    return next(
        line.split("=", 1)[1] for line in text.splitlines() if line.startswith("TIQR_SECRET_KEY=")
    )


def test_setup_command_is_idempotent_and_never_prints_key(tmp_path, monkeypatch):
    runner = CliRunner()

    first = runner.invoke(app, ["setup"])
    second = runner.invoke(app, ["setup"])

    key = _key((tmp_path / ".env.local").read_text(encoding="utf-8"))
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "Wrote TIQR_SECRET_KEY" in first.output
    assert "nothing to do" in second.output
    assert "Database initialized" in first.output
    assert (tmp_path / "tiqr_ticket.db").exists()
    assert key not in first.output
    assert key not in second.output
