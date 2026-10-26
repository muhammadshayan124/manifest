"""The reference data must match the statute's structure, and the profile parser must reject bad input
loudly: a silently ignored field is how a system gets classified as lower-risk than it is."""

from datetime import date
from pathlib import Path

import pytest
import yaml

from manifest.act import data
from manifest.act.profile import (
    ProfileError,
    load_profile,
    parse_profile,
    template_yaml,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "act"


def test_article_5_has_points_a_to_h():
    assert list(data.PROHIBITED) == list("abcdefgh")
    assert data.PROHIBITED["f"].citation == "Article 5(1)(f)"


def test_article_5_exceptions_are_exactly_where_the_text_has_them():
    with_exception = {k for k, v in data.PROHIBITED.items() if v.exception}
    assert with_exception == {"d", "f", "g", "h"}


def test_annex_iii_structure_matches_the_published_annex():
    assert list(data.ANNEX_III) == [str(i) for i in range(1, 9)]
    counts = {a.id: len(a.points) for a in data.ANNEX_III.values()}
    assert counts == {"1": 3, "2": 1, "3": 4, "4": 2, "5": 4, "6": 5, "7": 4, "8": 2}
    assert len(data.ANNEX_III_POINTS) == 25
    assert set(data.ANNEX_III_POINTS) >= {"1a", "2", "4a", "5b", "6e", "7d", "8b"}


def test_annex_iii_law_enforcement_style_qualifiers():
    qualified = {a.id for a in data.ANNEX_III.values() if a.qualifier}
    assert qualified == {"1", "6", "7"}  # "where permitted by Union or national law"


def test_annex_iv_sections():
    ids = [s.id for s in data.ANNEX_IV]
    assert len(ids) == len(set(ids)) == 23
    assert {i[0] for i in ids} == set("123456789")
    assert [i for i in ids if i.startswith("2")] == ["2a", "2b", "2c", "2d", "2e", "2f", "2g", "2h"]
    assert [i for i in ids if i.startswith("1")] == [f"1{c}" for c in "abcdefgh"]


def test_requirement_ids_are_unique_across_every_regime():
    every = [*data.HIGH_RISK_PROVIDER, *data.HIGH_RISK_DEPLOYER, *data.DEROGATED, data.LITERACY,
             *data.TRANSPARENCY.values(), *data.GPAI_PROVIDER, *data.GPAI_SYSTEMIC]
    ids = [r.id for r in every]
    assert len(ids) == len(set(ids))
    assert all(r.role in ("provider", "deployer", "both") for r in every)


def test_high_risk_provider_set_covers_the_core_requirements():
    ids = {r.id for r in data.HIGH_RISK_PROVIDER}
    assert {"art9", "art10", "art11", "art12", "art13", "art14", "art15", "art17", "art43", "art47", "art48", "art49", "art72", "art73"} <= ids


def test_timeline_is_ordered_valid_dates_and_carries_its_caveat():
    dates = [date.fromisoformat(d) for d, _, _ in data.TIMELINE]
    assert dates == sorted(dates)
    assert "Official Journal" in data.TIMELINE_NOTE and data.AS_OF in data.TIMELINE_NOTE


# -- profile parsing ---------------------------------------------------------------------------

def test_template_is_a_valid_profile_with_conservative_defaults():
    p = parse_profile(yaml.safe_load(template_yaml()))
    assert p.name == "My AI system" and p.role == "provider"
    assert not p.annex_iii and not p.prohibited_declared and not p.gpai_model


def test_every_bundled_example_parses():
    files = sorted(EXAMPLES.glob("*.yaml"))
    assert len(files) >= 8
    for f in files:
        load_profile(f)


@pytest.mark.parametrize(
    "raw, match",
    [
        ({}, "'name' is required"),
        ({"name": "x", "surprise": 1}, "unknown key"),
        ({"name": "x", "role": "regulator"}, "role must be one of"),
        ({"name": "x", "high_risk": {"annex_iii": ["9z"]}}, "unknown id"),
        ({"name": "x", "high_risk": {"annex_iii": "4a"}}, "must be a list"),
        ({"name": "x", "high_risk": {"typo": 1}}, "unknown key"),
        ({"name": "x", "prohibited_practices": {"declared": ["z"]}}, "unknown id"),
        ({"name": "x", "prohibited_practices": {"exception_claimed": ["f"]}}, "must also appear in 'declared'"),
        ({"name": "x", "prohibited_practices": {"declared": ["c"], "exception_claimed": ["c"]}}, "has no exception"),
        ({"name": "x", "scope": {"exemption": "vibes"}}, "scope.exemption"),
        ({"name": "x", "transparency": {"deepfake": "yes"}}, "must be true or false"),
        ({"name": "x", "gpai": {"training_compute_flops": "lots"}}, "must be a number"),
        ({"name": "x", "documentation": {"99": "text"}}, "unknown id"),
        ({"name": "x", "documentation": ["not", "a", "map"]}, "must be a mapping"),
        (["not", "a", "mapping"], "must be a YAML mapping"),
    ],
)
def test_bad_profiles_are_rejected_with_a_useful_message(raw, match):
    with pytest.raises(ProfileError, match=match):
        parse_profile(raw)


def test_invalid_id_message_lists_the_valid_choices():
    with pytest.raises(ProfileError) as e:
        parse_profile({"name": "x", "high_risk": {"annex_iii": ["4z"]}})
    assert "4a" in str(e.value) and "8b" in str(e.value)


def test_scientific_notation_without_an_exponent_sign_is_accepted():
    # PyYAML (YAML 1.1) reads 3.0e25 as a string; the parser must not make users write 3.0e+25.
    assert yaml.safe_load("x: 3.0e25")["x"] == "3.0e25"
    p = parse_profile({"name": "m", "gpai": {"is_gpai_model": True, "training_compute_flops": "3.0e25"}})
    assert p.training_flops == 3.0e25
    assert parse_profile({"name": "m", "gpai": {"training_compute_flops": 1e24}}).training_flops == 1e24


def test_invalid_yaml_file_is_a_profile_error(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text("name: [unclosed", encoding="utf-8")
    with pytest.raises(ProfileError, match="invalid YAML"):
        load_profile(f)
