from pathlib import Path

from typer.testing import CliRunner

from metrics.cli import app

runner = CliRunner()


def test_status_without_config_gives_clean_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "config.yaml" in result.output
    assert "Traceback" not in result.output


def test_status_with_malformed_yaml_gives_clean_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("config.yaml").write_text(": not: valid: [", encoding="utf-8")
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "not valid YAML" in result.output
    assert "Traceback" not in result.output


def test_status_with_missing_required_fields_gives_clean_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("config.yaml").write_text("azure_devops:\n  organization: x\n", encoding="utf-8")
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "invalid or missing settings" in result.output
    assert "project" in result.output
    assert "Traceback" not in result.output


def test_sync_without_pat_gives_clean_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AZDO_PAT", raising=False)
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 1
    assert "AZDO_PAT" in result.output
    assert "Traceback" not in result.output
