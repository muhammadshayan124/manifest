"""Classification behaviour, one rule at a time. Each case is a fact pattern a reader can check
against the cited provision."""

import pytest

from manifest.act import data
from manifest.act.classify import classify
from manifest.act.profile import SystemProfile, parse_profile


def prof(**kw) -> SystemProfile:
    base = {"name": "sys", "role": "provider"}
    sections = {k: kw.pop(k) for k in ("scope", "prohibited_practices", "high_risk", "transparency", "gpai") if k in kw}
    return parse_profile({**base, **kw, **sections})


def ids(c) -> set[str]:
    return set(c.requirement_ids())


# -- scope -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("exemption", sorted(data.OUT_OF_SCOPE))
def test_declared_scope_exemptions_take_the_system_out_of_scope(exemption):
    c = classify(prof(scope={"exemption": exemption}))
    assert c.tier == "out_of_scope" and c.reasons[0].citation == "Article 2"
    assert c.requirements == []


def test_no_eu_nexus_is_out_of_scope():
    assert classify(prof(scope={"eu_nexus": False})).tier == "out_of_scope"


def test_not_an_ai_system_is_out_of_scope_but_a_gpai_model_is_not_excused_by_that_flag():
    assert classify(prof(scope={"is_ai_system": False})).tier == "out_of_scope"
    assert classify(prof(scope={"is_ai_system": False}, gpai={"is_gpai_model": True})).tier == "gpai_model"


# -- Article 5 -------------------------------------------------------------------------------------

@pytest.mark.parametrize("pid", ["a", "b", "c", "e", "g", "h", "d", "f"])
def test_each_declared_prohibited_practice_makes_the_system_prohibited(pid):
    c = classify(prof(prohibited_practices={"declared": [pid]}))
    assert c.tier == "prohibited"
    assert c.reasons[0].citation == f"Article 5(1)({pid})"
    assert c.requirements == []


@pytest.mark.parametrize("pid, implied", [("d", "6"), ("f", "1"), ("g", "1"), ("h", "1")])
def test_a_claimed_article_5_exception_leaves_a_high_risk_system_and_demands_legal_review(pid, implied):
    c = classify(prof(prohibited_practices={"declared": [pid], "exception_claimed": [pid]}))
    assert c.tier == "high_risk"
    assert any(r.citation.startswith(f"Annex III {implied}") for r in c.reasons)
    assert any("legal review" in w for w in c.warnings)


def test_one_unexcused_practice_still_prohibits_even_if_another_claims_an_exception():
    c = classify(prof(prohibited_practices={"declared": ["c", "f"], "exception_claimed": ["f"]}))
    assert c.tier == "prohibited"


# -- Annex III / Article 6 -------------------------------------------------------------------------

@pytest.mark.parametrize("point", sorted(data.ANNEX_III_POINTS))
def test_every_annex_iii_point_is_high_risk(point):
    c = classify(prof(high_risk={"annex_iii": [point]}))
    assert c.tier == "high_risk"
    assert any(r.citation.startswith(f"Annex III {point[0]}") for r in c.reasons)
    assert "art9" in ids(c) and "art43" in ids(c)


def test_law_enforcement_migration_and_biometrics_carry_the_where_permitted_qualifier():
    for point in ("1a", "6a", "7b"):
        c = classify(prof(high_risk={"annex_iii": [point]}))
        assert any("where permitted by Union or national law" in w for w in c.warnings), point
    assert not any("where permitted" in w for w in classify(prof(high_risk={"annex_iii": ["4a"]})).warnings)


def test_full_derogation_without_profiling_is_not_high_risk_but_must_be_documented_and_registered():
    c = classify(prof(high_risk={"annex_iii": ["4a"], "derogation": {"conditions": ["procedural_task"], "no_significant_risk": True}}))
    assert c.tier == "not_high_risk_documented"
    assert ids(c) == {"art4", "art6_4", "art49_2"}
    assert any("Art. 6(4)" in w for w in c.warnings)


def test_profiling_always_defeats_the_derogation():
    c = classify(prof(high_risk={"annex_iii": ["4a"], "profiling_of_natural_persons": True,
                                 "derogation": {"conditions": ["procedural_task"], "no_significant_risk": True}}))
    assert c.tier == "high_risk"
    assert any("derogation never applies" in w for w in c.warnings)


@pytest.mark.parametrize("der", [
    {"conditions": ["procedural_task"], "no_significant_risk": False},
    {"conditions": [], "no_significant_risk": True},
])
def test_a_partial_derogation_claim_is_not_enough(der):
    c = classify(prof(high_risk={"annex_iii": ["4a"], "derogation": der}))
    assert c.tier == "high_risk" and any("partly claimed" in w for w in c.warnings)


def test_annex_i_route_needs_both_a_safety_component_and_a_third_party_assessment():
    both = classify(prof(high_risk={"annex_i": {"safety_component": True, "third_party_assessment_required": True}}))
    assert both.tier == "high_risk" and any(r.citation == "Article 6(1)" for r in both.reasons)
    assert any(d == "2028-08-02" for d, _ in both.dates)
    only = classify(prof(high_risk={"annex_i": {"safety_component": True}}))
    assert only.tier == "minimal" and any("Art. 6(1) needs both" in w for w in only.warnings)


def test_derogation_does_not_rescue_a_system_that_is_also_high_risk_via_annex_i():
    c = classify(prof(high_risk={"annex_iii": ["4a"], "derogation": {"conditions": ["procedural_task"], "no_significant_risk": True},
                                 "annex_i": {"safety_component": True, "third_party_assessment_required": True}}))
    assert c.tier == "high_risk"


def test_high_risk_dates_depend_on_the_route():
    assert ("2027-12-02" in {d for d, _ in classify(prof(high_risk={"annex_iii": ["4a"]})).dates})


# -- roles -----------------------------------------------------------------------------------------

PROVIDER_ONLY = {"art9", "art10", "art11", "art43", "art47", "art48", "art49", "art72", "art73"}
DEPLOYER_ONLY = {"art26", "art27", "art86"}


@pytest.mark.parametrize("role, has, lacks", [
    ("provider", PROVIDER_ONLY, DEPLOYER_ONLY),
    ("deployer", DEPLOYER_ONLY, PROVIDER_ONLY),
    ("both", PROVIDER_ONLY | DEPLOYER_ONLY, set()),
])
def test_high_risk_duties_follow_the_role(role, has, lacks):
    got = ids(classify(prof(role=role, high_risk={"annex_iii": ["5b"]})))
    assert has <= got and not (lacks & got)


# -- Article 50 ------------------------------------------------------------------------------------

def test_each_transparency_flag_triggers_its_own_provision():
    cases = {"interacts_with_natural_persons": "art50_1", "generates_synthetic_content": "art50_2"}
    for flag, tid in cases.items():
        c = classify(prof(transparency={flag: True}))
        assert c.tier == "transparency" and c.transparency == [tid] and tid in ids(c)
    for flag, tid in {"emotion_or_biometric_categorisation": "art50_3", "deepfake": "art50_4", "public_interest_text": "art50_4"}.items():
        c = classify(prof(role="deployer", transparency={flag: True}))
        assert c.transparency == [tid] and tid in ids(c)


def test_obvious_ai_interaction_suppresses_50_1_with_an_explanation():
    c = classify(prof(transparency={"interacts_with_natural_persons": True, "obviously_ai": True}))
    assert c.tier == "minimal" and "art50_1" not in ids(c)
    assert any("obvious" in w for w in c.warnings)


def test_a_provider_is_told_when_a_transparency_duty_falls_on_its_deployers():
    c = classify(prof(role="provider", transparency={"deepfake": True}))
    assert "art50_4" not in ids(c) and "art50_4" in c.transparency
    assert any("falls on deployers" in w for w in c.warnings)


def test_a_high_risk_system_keeps_its_tier_and_still_lists_transparency():
    c = classify(prof(high_risk={"annex_iii": ["5b"]}, transparency={"interacts_with_natural_persons": True}))
    assert c.tier == "high_risk" and "art50_1" in ids(c) and "art9" in ids(c)


# -- general-purpose AI ----------------------------------------------------------------------------

def test_gpai_below_the_threshold_has_no_systemic_duties():
    c = classify(prof(gpai={"is_gpai_model": True, "training_compute_flops": 5e24}))
    assert c.tier == "gpai_model" and c.gpai and not c.gpai_systemic
    assert {"art53a", "art53b", "art53c", "art53d"} <= ids(c) and not ({"art52", "art55"} & ids(c))


def test_gpai_above_the_threshold_is_presumed_systemic():
    c = classify(prof(gpai={"is_gpai_model": True, "training_compute_flops": 3e25}))
    assert c.gpai_systemic and {"art52", "art55"} <= ids(c)


def test_the_threshold_itself_is_not_exceeded():
    assert not classify(prof(gpai={"is_gpai_model": True, "training_compute_flops": 1e25})).gpai_systemic


def test_unknown_compute_is_flagged_not_assumed():
    c = classify(prof(gpai={"is_gpai_model": True}))
    assert not c.gpai_systemic and any("training_compute_flops not given" in w for w in c.warnings)


def test_open_source_exempts_only_53a_and_53b_and_never_for_systemic_risk():
    c = classify(prof(gpai={"is_gpai_model": True, "training_compute_flops": 1e24, "open_source_license": True}))
    assert not ({"art53a", "art53b"} & ids(c)) and {"art53c", "art53d"} <= ids(c)
    sys_ = classify(prof(gpai={"is_gpai_model": True, "training_compute_flops": 5e25, "open_source_license": True}))
    assert {"art53a", "art53b", "art53c", "art53d", "art52", "art55"} <= ids(sys_)


def test_gpai_duties_do_not_land_on_a_pure_deployer():
    c = classify(prof(role="deployer", gpai={"is_gpai_model": True, "training_compute_flops": 5e25}))
    assert not ({"art53a", "art55"} & ids(c)) and any("model provider" in w for w in c.warnings)


# -- general ---------------------------------------------------------------------------------------

def test_minimal_systems_still_owe_ai_literacy_and_get_a_date_for_it():
    c = classify(prof())
    assert c.tier == "minimal" and ids(c) == {"art4"} and ("2025-02-02", data.TIMELINE[0][1]) in c.dates


def test_every_result_carries_the_date_caveat():
    assert any("Official Journal" in w for w in classify(prof()).warnings)


def test_classification_is_deterministic():
    p = prof(high_risk={"annex_iii": ["4a", "5b"], "profiling_of_natural_persons": True}, transparency={"deepfake": True})
    a, b = classify(p), classify(p)
    assert (a.tier, a.reasons, a.requirement_ids(), a.warnings) == (b.tier, b.reasons, b.requirement_ids(), b.warnings)
