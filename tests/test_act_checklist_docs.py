from pathlib import Path

import pytest

from manifest.act import checklist as cl
from manifest.act import data, docs
from manifest.act.classify import classify
from manifest.act.profile import load_profile, parse_profile
from manifest.scan import scan_path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "act"
FIXTURES = ROOT / "tests" / "fixtures" / "python"


def hr_profile(**docs_answers):
    return parse_profile({"name": "S", "version": "1.0", "provider": "P", "intended_purpose": "do things",
                          "high_risk": {"annex_iii": ["4a"], "profiling_of_natural_persons": True},
                          "transparency": {"interacts_with_natural_persons": True},
                          "documentation": docs_answers})


# -- checklist ---------------------------------------------------------------------------------

def test_build_creates_one_todo_item_per_requirement():
    c = classify(hr_profile())
    ck = cl.build(c)
    assert [i.id for i in ck.items] == c.requirement_ids()
    assert {i.status for i in ck.items} == {"todo"}
    assert ck.progress == (0, len(ck.items))


def test_regenerating_keeps_recorded_progress_and_reports_dropped_items():
    ck = cl.build(classify(hr_profile()))
    ck.get("art9").status = "done"
    ck.get("art9").evidence = "docs/risk-register.md"
    ck.get("art10").notes = "waiting on data team"
    # the profile changes: no longer high-risk, so the high-risk items disappear
    minimal = cl.build(classify(parse_profile({"name": "S", "transparency": {"interacts_with_natural_persons": True}})), ck)
    assert {i.id for i in minimal.items} == {"art4", "art50_1"}
    assert "art9" in minimal.dropped and "art10" in minimal.dropped
    # and if it flips back, the earlier answers are not magically restored (they were dropped on purpose)
    again = cl.build(classify(hr_profile()), minimal)
    assert again.get("art9").status == "todo"


def test_progress_ignores_not_applicable_items():
    ck = cl.build(classify(hr_profile()))
    total = len(ck.items)
    ck.get("art12").status = "not_applicable"
    ck.get("art9").status, ck.get("art9").evidence = "done", "x"
    assert ck.progress == (1, total - 1)


def test_save_and_load_round_trip(tmp_path):
    ck = cl.build(classify(hr_profile()))
    ck.get("art9").status, ck.get("art9").evidence = "done", "link"
    f = tmp_path / "ck.yaml"
    cl.save(ck, f)
    back = cl.load(f)
    assert [(i.id, i.status, i.evidence) for i in back.items] == [(i.id, i.status, i.evidence) for i in ck.items]
    assert back.tier == "high_risk" and back.system == "S"


def test_load_rejects_an_invalid_status(tmp_path):
    f = tmp_path / "ck.yaml"
    f.write_text("system: s\ntier: t\nitems:\n  - {id: art9, status: finished}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="status must be one of"):
        cl.load(f)


def test_done_without_evidence_is_a_problem():
    ck = cl.build(classify(hr_profile()))
    ck.get("art9").status = "done"
    [msg] = cl.problems(ck)
    assert "without evidence" in msg
    ck.get("art9").evidence = "docs/risk-register.md"
    assert cl.problems(ck) == []


def test_open_items_only_fail_when_asked_to():
    ck = cl.build(classify(hr_profile()))
    assert cl.problems(ck) == []
    assert len(cl.problems(ck, fail_on="open")) == len(ck.items)


def test_scanner_contradicts_a_done_article_50_item():
    c = classify(parse_profile({"name": "S", "transparency": {"interacts_with_natural_persons": True}}))
    ck = cl.build(c)
    cl.apply_scan(ck, scan_path(FIXTURES / "noncompliant_chatbot.py"))
    item = ck.get("art50_1")
    assert "1 likely_violation" in item.scan and item.status == "todo"  # the scan never sets a status itself
    item.status, item.evidence = "done", "we added a banner"
    [msg] = cl.problems(ck)
    assert "scanner still reports 1 likely violation" in msg


def test_a_compliant_fixture_does_not_contradict_done():
    ck = cl.build(classify(parse_profile({"name": "S", "transparency": {"interacts_with_natural_persons": True}})))
    cl.apply_scan(ck, scan_path(FIXTURES / "compliant_chatbot.py"))
    ck.get("art50_1").status, ck.get("art50_1").evidence = "done", "banner screenshot"
    assert cl.problems(ck) == []
    assert "0 likely_violation" in ck.get("art50_1").scan


def test_no_findings_is_recorded_as_not_proof():
    ck = cl.build(classify(parse_profile({"name": "S", "transparency": {"interacts_with_natural_persons": True}})))
    cl.apply_scan(ck, [])
    assert "not proof of compliance" in ck.get("art50_1").scan


# -- documentation -----------------------------------------------------------------------------

def test_high_risk_document_has_every_annex_iv_section_and_a_todo_for_each_gap():
    p = hr_profile()
    md, comp = docs.render(p, classify(p))
    for s in data.ANNEX_IV:
        assert f"## {s.id}. {s.title}" in md
    assert comp.total == 23 and comp.filled == 1  # only 1a is derivable from the profile
    assert docs.count_todos(md) == len(comp.missing) == 22


def test_profile_answers_fill_sections_and_raise_completeness():
    p = hr_profile(**{"2d": "Resumes from 2019-2024, de-identified.", "5": "See risk register."})
    md, comp = docs.render(p, classify(p))
    assert "Resumes from 2019-2024" in md and comp.filled == 3
    assert "2d" not in comp.missing and "5" not in comp.missing
    assert 0 < comp.percent < 100 and not comp.complete


def test_a_fully_answered_profile_is_complete_with_no_todos():
    answers = {s.id: f"answer {s.id}" for s in data.ANNEX_IV}
    p = hr_profile(**answers)
    md, comp = docs.render(p, classify(p))
    assert comp.complete and comp.percent == 100 and docs.count_todos(md) == 0


def test_prefill_is_marked_and_never_overrides_an_explicit_answer():
    p = hr_profile()
    md, _ = docs.render(p, classify(p))
    assert "Provider: P" in md and "pre-filled from the profile" in md
    explicit = hr_profile(**{"1a": "Our own wording."})
    md2, _ = docs.render(explicit, classify(explicit))
    assert "Our own wording." in md2 and "Provider: P" not in md2 and "pre-filled" not in md2


def test_sections_link_to_checklist_items_and_scan_summary():
    p = hr_profile()
    c = classify(p)
    ck = cl.build(c)
    ck.get("art9").status, ck.get("art9").evidence = "done", "risk-register.md"
    md, _ = docs.render(p, c, ck, scan_path(FIXTURES / "noncompliant_chatbot.py"))
    assert "Related checklist item: `art9`" in md and "risk-register.md" in md
    assert "Static scan: 1 likely violation" in md


def test_derogated_system_gets_the_article_6_4_record_not_annex_iv():
    p = load_profile(EXAMPLES / "cv-redaction-tool.yaml")
    md, comp = docs.render(p, classify(p))
    assert comp is None and "Article 6(4) assessment record" in md
    assert "procedural_task" not in md and "narrow procedural task" in md
    assert docs.count_todos(md) == 2


@pytest.mark.parametrize("example", ["internal-code-assistant", "support-chatbot", "foundation-model"])
def test_other_tiers_say_annex_iv_is_not_required(example):
    p = load_profile(EXAMPLES / f"{example}.yaml")
    md, comp = docs.render(p, classify(p))
    assert comp is None and "no Annex IV file is required" in md


def test_count_todos_ignores_prose_that_merely_contains_the_word():
    assert docs.count_todos("We have no TODO items left.\nTODO: fill this\nTODO\n  TODO: indented") == 3
