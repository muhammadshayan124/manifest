from pathlib import Path

from typer.testing import CliRunner

from manifest.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_empty_result_renders_table_format(tmp_path):
    # Regression: the empty-result path called a helper that did not exist.
    result = runner.invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "No candidate Article 50 issues" in result.output


def test_fail_on_likely_exits_nonzero_when_a_likely_violation_exists():
    result = runner.invoke(app, ["scan", str(FIXTURES), "--fail-on", "likely"])
    assert result.exit_code != 0


def test_fail_on_likely_passes_on_clean_dir(tmp_path):
    result = runner.invoke(app, ["scan", str(tmp_path), "--fail-on", "likely"])
    assert result.exit_code == 0


def test_json_and_sarif_formats_parse(tmp_path):
    import json

    for fmt in ("json", "sarif"):
        result = runner.invoke(app, ["scan", str(FIXTURES), "--format", fmt])
        assert result.exit_code == 0, result.output
        json.loads(result.output)
