import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from manifest.cli import app

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "act"
FIXTURES = ROOT / "tests" / "fixtures" / "python"

EXPECTED_TIERS = {
    "credit-scoring": "high_risk",
    "cv-redaction-tool": "not_high_risk_documented",
    "cv-screener": "high_risk",
    "foundation-model": "transparency",
    "internal-code-assistant": "minimal",
    "social-scoring": "prohibited",
    "support-chatbot": "transparency",
    "workplace-fatigue-monitor": "high_risk",
}


def run(*args):
    return runner.invoke(app, ["act", *map(str, args)])


@pytest.mark.parametrize("name, tier", sorted(EXPECTED_TIERS.items()))
def test_each_example_classifies_as_documented(name, tier):
    r = run("classify", EXAMPLES / f"{name}.yaml", "--json")
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["tier"] == tier


def test_every_example_has_an_expected_tier():
    assert {p.stem for p in EXAMPLES.glob("*.yaml")} == set(EXPECTED_TIERS)


def test_json_output_shape():
    d = json.loads(run("classify", EXAMPLES / "foundation-model.yaml", "--json").output)
    assert d["gpai"] is True and d["gpai_systemic_risk"] is True
    assert {"art52", "art55", "art53a"} <= {r["id"] for r in d["requirements"]}
    assert all({"date", "what"} <= set(x) for x in d["dates"])


def test_human_output_names_the_tier_and_the_caveats():
    out = run("classify", EXAMPLES / "cv-screener.yaml").output
    assert "HIGH RISK" in out and "Annex III" in out and "Official Journal" in out.replace("\n", " ")


def test_bad_profile_exits_2_with_a_message(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("name: x\nhigh_risk:\n  annex_iii: [99]\n", encoding="utf-8")
    r = run("classify", f)
    assert r.exit_code == 2 and "unknown id" in r.output
    assert run("classify", tmp_path / "missing.yaml").exit_code == 2


def test_init_writes_a_working_template_and_refuses_to_overwrite(tmp_path):
    f = tmp_path / "sys.yaml"
    assert run("init", "--out", f).exit_code == 0
    assert run("classify", f, "--json").exit_code == 0
    again = run("init", "--out", f)
    assert again.exit_code == 2 and "exists" in again.output
    assert run("init", "--out", f, "--force").exit_code == 0


def test_checklist_lifecycle(tmp_path):
    prof, ck = EXAMPLES / "cv-screener.yaml", tmp_path / "ck.yaml"
    r = run("checklist", prof, "--file", ck)
    assert r.exit_code == 0 and ck.exists() and "applicable items done" in r.output

    refused = run("mark", "art9", "done", "--file", ck)
    assert refused.exit_code == 2 and "without --evidence" in refused.output
    assert run("mark", "art9", "done", "--file", ck, "--evidence", "docs/risk.md").exit_code == 0
    assert run("mark", "art99", "done", "--file", ck, "--evidence", "x").exit_code == 2
    assert run("mark", "art9", "finished", "--file", ck).exit_code == 2

    # progress survives regeneration
    run("checklist", prof, "--file", ck)
    items = {i["id"]: i for i in yaml.safe_load(ck.read_text(encoding="utf-8"))["items"]}
    assert items["art9"]["status"] == "done" and items["art9"]["evidence"] == "docs/risk.md"

    # default --check passes (open items are not an error) but --fail-on open fails
    assert run("checklist", prof, "--file", ck, "--check").exit_code == 0
    assert run("checklist", prof, "--file", ck, "--check", "--fail-on", "open").exit_code == 1
    assert run("checklist", prof, "--file", ck, "--fail-on", "sometimes").exit_code == 2


def test_check_catches_done_without_evidence_edited_by_hand(tmp_path):
    prof, ck = EXAMPLES / "cv-screener.yaml", tmp_path / "ck.yaml"
    run("checklist", prof, "--file", ck)
    doc = yaml.safe_load(ck.read_text(encoding="utf-8"))
    doc["items"][1]["status"] = "done"
    ck.write_text(yaml.safe_dump(doc), encoding="utf-8")
    r = run("checklist", prof, "--file", ck, "--check")
    assert r.exit_code == 1 and "without evidence" in r.output


def test_scan_contradiction_fails_check(tmp_path):
    prof, ck = EXAMPLES / "support-chatbot.yaml", tmp_path / "ck.yaml"
    run("checklist", prof, "--file", ck, "--scan", FIXTURES / "noncompliant_chatbot.py")
    run("mark", "art50_1", "done", "--file", ck, "--evidence", "we added a banner")
    r = run("checklist", prof, "--file", ck, "--scan", FIXTURES / "noncompliant_chatbot.py", "--check")
    assert r.exit_code == 1 and "scanner still reports" in r.output


def test_docs_generation_and_completeness_gate(tmp_path):
    out = tmp_path / "doc.md"
    r = run("docs", EXAMPLES / "cv-screener.yaml", "--out", out)
    assert r.exit_code == 0 and out.exists() and "Annex IV completeness: 4/23" in r.output
    assert run("docs", EXAMPLES / "cv-screener.yaml", "--out", out, "--check").exit_code == 1
    assert run("docs", out.parent / "x.yaml", "--out", out).exit_code == 2


def test_docs_check_file_counts_todos_in_an_edited_document(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("## 1a\nDone.\nTODO: still missing\n", encoding="utf-8")
    assert run("docs", EXAMPLES / "cv-screener.yaml", "--check-file", f).exit_code == 1
    f.write_text("## 1a\nDone.\n", encoding="utf-8")
    assert run("docs", EXAMPLES / "cv-screener.yaml", "--check-file", f).exit_code == 0


def test_docs_for_a_tier_without_annex_iv(tmp_path):
    r = run("docs", EXAMPLES / "support-chatbot.yaml", "--out", tmp_path / "d.md", "--check")
    assert r.exit_code == 0 and "not required" in r.output


def test_timeline_prints_dates_and_the_caveat():
    out = run("timeline").output.replace("\n", " ")
    assert "2027-12-02" in out and "Digital Omnibus" in out and "Official Journal" in out


def test_existing_scan_command_still_works():
    r = runner.invoke(app, ["scan", str(FIXTURES / "noncompliant_chatbot.py"), "--json"])
    assert r.exit_code == 0 and json.loads(r.output)["finding_count"] == 1
