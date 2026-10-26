"""The declarative description of an AI system that the classifier, checklist and documentation
generator all read. A YAML file you keep in the repo next to the code.

Validation is strict on purpose: an unknown key or a mistyped Annex III point is an error, not
a silent default, because a silently ignored field is exactly how a system gets classified as
lower-risk than it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from manifest.act import data


class ProfileError(ValueError):
    pass


ROLES = ("provider", "deployer", "both")


@dataclass
class SystemProfile:
    name: str
    version: str = ""
    provider: str = ""
    role: str = "provider"
    intended_purpose: str = ""
    # scope (Art. 2, Art. 3(1))
    is_ai_system: bool = True
    eu_nexus: bool = True  # placed on the EU market, put into service in the EU, or its output used in the EU
    scope_exemption: str = "none"
    # prohibited practices (Art. 5)
    prohibited_declared: list[str] = field(default_factory=list)
    prohibited_exception_claimed: list[str] = field(default_factory=list)
    # high-risk (Art. 6, Annex I, Annex III)
    annex_iii: list[str] = field(default_factory=list)
    profiling: bool = False
    derogation_conditions: list[str] = field(default_factory=list)
    no_significant_risk: bool = False
    annex_i_safety_component: bool = False
    annex_i_third_party_assessment: bool = False
    # transparency (Art. 50)
    interacts_with_persons: bool = False
    obviously_ai: bool = False
    generates_synthetic_content: bool = False
    emotion_or_biometric_categorisation: bool = False
    deepfake: bool = False
    public_interest_text: bool = False
    # general-purpose AI models (Ch. V)
    gpai_model: bool = False
    training_flops: float | None = None
    open_source: bool = False
    # answers used to pre-fill the Annex IV document
    documentation: dict[str, str] = field(default_factory=dict)


def _check_keys(where: str, raw: dict[str, Any], allowed: set[str]) -> None:
    unknown = set(raw) - allowed
    if unknown:
        raise ProfileError(f"{where}: unknown key(s) {sorted(unknown)}; allowed: {sorted(allowed)}")


def _section(raw: dict[str, Any], key: str, allowed: set[str]) -> dict[str, Any]:
    sec = raw.get(key) or {}
    if not isinstance(sec, dict):
        raise ProfileError(f"'{key}' must be a mapping")
    _check_keys(key, sec, allowed)
    return sec


def _ids(where: str, values: Any, valid: set[str]) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ProfileError(f"{where} must be a list")
    vals = [str(v) for v in values]
    bad = [v for v in vals if v not in valid]
    if bad:
        raise ProfileError(f"{where}: unknown id(s) {bad}; valid: {sorted(valid)}")
    return vals


def _bool(where: str, v: Any, default: bool) -> bool:
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ProfileError(f"{where} must be true or false, got {v!r}")
    return v


def parse_profile(raw: Any) -> SystemProfile:
    if not isinstance(raw, dict):
        raise ProfileError("profile must be a YAML mapping")
    _check_keys("profile", raw, {"name", "version", "provider", "role", "intended_purpose", "scope",
                                 "prohibited_practices", "high_risk", "transparency", "gpai", "documentation"})
    if not raw.get("name"):
        raise ProfileError("'name' is required")
    role = raw.get("role", "provider")
    if role not in ROLES:
        raise ProfileError(f"role must be one of {ROLES}, got {role!r}")

    scope = _section(raw, "scope", {"is_ai_system", "eu_nexus", "exemption"})
    exemption = scope.get("exemption", "none") or "none"
    if exemption != "none" and exemption not in data.OUT_OF_SCOPE:
        raise ProfileError(f"scope.exemption must be 'none' or one of {sorted(data.OUT_OF_SCOPE)}, got {exemption!r}")

    pp = _section(raw, "prohibited_practices", {"declared", "exception_claimed"})
    declared = _ids("prohibited_practices.declared", pp.get("declared"), set(data.PROHIBITED))
    claimed = _ids("prohibited_practices.exception_claimed", pp.get("exception_claimed"), set(data.PROHIBITED))
    stray = [c for c in claimed if c not in declared]
    if stray:
        raise ProfileError(f"prohibited_practices.exception_claimed {stray} must also appear in 'declared'")
    no_exception = [c for c in claimed if data.PROHIBITED[c].exception is None]
    if no_exception:
        raise ProfileError(f"Article 5(1)({no_exception[0]}) has no exception to claim")

    hr = _section(raw, "high_risk", {"annex_iii", "profiling_of_natural_persons", "annex_i", "derogation"})
    annex_i = hr.get("annex_i") or {}
    _check_keys("high_risk.annex_i", annex_i, {"safety_component", "third_party_assessment_required"})
    der = hr.get("derogation") or {}
    _check_keys("high_risk.derogation", der, {"conditions", "no_significant_risk"})

    tr = _section(raw, "transparency", {"interacts_with_natural_persons", "obviously_ai", "generates_synthetic_content",
                                        "emotion_or_biometric_categorisation", "deepfake", "public_interest_text"})
    gp = _section(raw, "gpai", {"is_gpai_model", "training_compute_flops", "open_source_license"})
    flops = gp.get("training_compute_flops")
    if isinstance(flops, str):
        # YAML 1.1 (PyYAML) reads 3.0e25 -- no sign on the exponent -- as a string, not a float.
        try:
            flops = float(flops)
        except ValueError:
            flops = None
            raise ProfileError("gpai.training_compute_flops must be a number (e.g. 3.0e24)") from None
    if flops is not None and (isinstance(flops, bool) or not isinstance(flops, (int, float))):
        raise ProfileError("gpai.training_compute_flops must be a number (e.g. 3.0e24)")

    docs = raw.get("documentation") or {}
    if not isinstance(docs, dict):
        raise ProfileError("'documentation' must be a mapping of Annex IV section id -> text")
    valid_sections = {s.id for s in data.ANNEX_IV}
    _ids("documentation keys", list(docs), valid_sections)

    return SystemProfile(
        name=str(raw["name"]), version=str(raw.get("version", "")), provider=str(raw.get("provider", "")),
        role=role, intended_purpose=str(raw.get("intended_purpose", "")),
        is_ai_system=_bool("scope.is_ai_system", scope.get("is_ai_system"), True),
        eu_nexus=_bool("scope.eu_nexus", scope.get("eu_nexus"), True),
        scope_exemption=exemption,
        prohibited_declared=declared, prohibited_exception_claimed=claimed,
        annex_iii=_ids("high_risk.annex_iii", hr.get("annex_iii"), set(data.ANNEX_III_POINTS)),
        profiling=_bool("high_risk.profiling_of_natural_persons", hr.get("profiling_of_natural_persons"), False),
        derogation_conditions=_ids("high_risk.derogation.conditions", der.get("conditions"), set(data.DEROGATION_CONDITIONS)),
        no_significant_risk=_bool("high_risk.derogation.no_significant_risk", der.get("no_significant_risk"), False),
        annex_i_safety_component=_bool("high_risk.annex_i.safety_component", annex_i.get("safety_component"), False),
        annex_i_third_party_assessment=_bool(
            "high_risk.annex_i.third_party_assessment_required", annex_i.get("third_party_assessment_required"), False),
        interacts_with_persons=_bool("transparency.interacts_with_natural_persons", tr.get("interacts_with_natural_persons"), False),
        obviously_ai=_bool("transparency.obviously_ai", tr.get("obviously_ai"), False),
        generates_synthetic_content=_bool("transparency.generates_synthetic_content", tr.get("generates_synthetic_content"), False),
        emotion_or_biometric_categorisation=_bool(
            "transparency.emotion_or_biometric_categorisation", tr.get("emotion_or_biometric_categorisation"), False),
        deepfake=_bool("transparency.deepfake", tr.get("deepfake"), False),
        public_interest_text=_bool("transparency.public_interest_text", tr.get("public_interest_text"), False),
        gpai_model=_bool("gpai.is_gpai_model", gp.get("is_gpai_model"), False),
        training_flops=float(flops) if flops is not None else None,
        open_source=_bool("gpai.open_source_license", gp.get("open_source_license"), False),
        documentation={str(k): str(v) for k, v in docs.items() if v is not None},
    )


def load_profile(path: str | Path) -> SystemProfile:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileError(f"{path}: invalid YAML: {exc}") from exc
    return parse_profile(raw)


def template_yaml() -> str:
    """An annotated starting point listing every valid id, so nobody has to guess a value."""
    art5 = "\n".join(f"#   {p.id}: {p.title}" for p in data.PROHIBITED.values())
    a3 = "\n".join(f"#   {pid}: {text[:78]}" for pid, text in data.ANNEX_III_POINTS.items())
    der = "\n".join(f"#   {k}: {v}" for k, v in data.DEROGATION_CONDITIONS.items())
    ex = "\n".join(f"#   {k}: {v}" for k, v in data.OUT_OF_SCOPE.items())
    return f"""# manifest system profile -- facts about your system, which `manifest act` turns into a classification.
# The classification is only as good as these answers. This is not legal advice.
name: My AI system
version: "0.1.0"
provider: Example Corp          # who places it on the market / puts it into service
role: provider                  # provider | deployer | both
intended_purpose: "Describe what the system is for, in one or two sentences."

scope:
  is_ai_system: true            # Art. 3(1): infers from input how to generate outputs that can influence environments
  eu_nexus: true                # placed on the EU market, put into service in the EU, or output used in the EU
  exemption: none               # none, or one of:
{ex}

prohibited_practices:           # Art. 5 -- declare any that apply to your system
  declared: []                  # ids:
{art5}
  exception_claimed: []         # subset of 'declared' for which you rely on the Article's own exception

high_risk:
  annex_iii: []                 # use cases from Annex III (Art. 6(2)); ids:
{a3}
  profiling_of_natural_persons: false   # profiling always keeps an Annex III system high-risk (Art. 6(3))
  derogation:                   # Art. 6(3): claim only if the system poses no significant risk of harm
    conditions: []              # any of:
{der}
    no_significant_risk: false
  annex_i:                      # Art. 6(1): product-safety route
    safety_component: false
    third_party_assessment_required: false

transparency:                   # Art. 50
  interacts_with_natural_persons: false
  obviously_ai: false           # true if it is obvious to a reasonably well-informed person that they deal with an AI
  generates_synthetic_content: false
  emotion_or_biometric_categorisation: false
  deepfake: false
  public_interest_text: false   # AI-generated text published to inform the public on matters of public interest

gpai:                           # Chapter V -- only if you provide a general-purpose AI model
  is_gpai_model: false
  training_compute_flops: null  # e.g. 3.0e24; above 1e25 triggers the systemic-risk presumption (Art. 51(2))
  open_source_license: false

documentation: {{}}             # optional pre-filled Annex IV answers, keyed by section id (e.g. 1a, 2d, 9)
"""
