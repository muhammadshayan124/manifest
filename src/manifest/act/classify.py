"""Deterministic risk-tier classification from a declared system profile.

This encodes the *structure* of the Act's classification logic, not a legal opinion:

    out of scope -> prohibited (Art. 5) -> high-risk (Art. 6: Annex I product route, or an Annex III
    use case unless the Art. 6(3) derogation holds and there is no profiling) -> not high-risk but
    documented (Art. 6(4)) -> transparency duties (Art. 50) -> minimal.

General-purpose AI model duties (Chapter V) and AI literacy (Art. 4) are layered on top, because
they run alongside the tiers rather than being a tier. Every result carries the citation that
produced it, and every judgement call is surfaced as a warning rather than resolved silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from manifest.act import data
from manifest.act.data import Requirement
from manifest.act.profile import SystemProfile

# When an Article 5 exception is claimed, what permitted use remains? Each lands in an Annex III point.
_EXCEPTION_FALLS_TO_ANNEX_III = {"d": "6d", "f": "1c", "g": "1b", "h": "1a"}

TIERS = ("out_of_scope", "prohibited", "high_risk", "not_high_risk_documented", "transparency", "gpai_model", "minimal")


@dataclass(frozen=True)
class Reason:
    citation: str
    text: str


@dataclass
class Classification:
    system: str
    tier: str
    reasons: list[Reason] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    transparency: list[str] = field(default_factory=list)  # triggered Art. 50 ids, e.g. "art50_1"
    gpai: bool = False  # also a provider of a general-purpose AI model (Chapter V runs alongside the tier)
    gpai_systemic: bool = False
    warnings: list[str] = field(default_factory=list)
    dates: list[tuple[str, str]] = field(default_factory=list)

    @property
    def high_risk(self) -> bool:
        return self.tier == "high_risk"

    def requirement_ids(self) -> list[str]:
        return [r.id for r in self.requirements]


def _applies(req_role: str, profile_role: str) -> bool:
    return req_role == "both" or profile_role in (req_role, "both")


def _timeline_for(dates: set[str]) -> list[tuple[str, str]]:
    return [(d, text) for d, text, _ in data.TIMELINE if d in dates]


def classify(p: SystemProfile) -> Classification:
    out = Classification(system=p.name, tier="minimal")
    add = out.reasons.append
    reqs: dict[str, Requirement] = {}
    dates: set[str] = set()

    # -- scope -----------------------------------------------------------------------------
    if p.scope_exemption != "none":
        out.tier = "out_of_scope"
        add(Reason("Article 2", f"Declared exemption: {data.OUT_OF_SCOPE[p.scope_exemption]}"))
        out.warnings.append("Exemptions are read narrowly; a dual-use or later-repurposed system can fall back into scope.")
        return out
    if not p.eu_nexus:
        out.tier = "out_of_scope"
        add(Reason("Article 2(1)", "No EU nexus declared: not placed on the EU market, not put into service in the EU, "
                                   "and output not used in the Union."))
        return out
    if not p.is_ai_system and not p.gpai_model:
        out.tier = "out_of_scope"
        add(Reason("Article 3(1)", "Declared not to be an 'AI system' (a machine-based system that infers, from input, "
                                   "how to generate outputs that can influence physical or virtual environments)."))
        out.warnings.append("Whether a system meets the definition is a legal question; the Commission has issued guidelines on it.")
        return out

    # -- prohibited practices --------------------------------------------------------------
    implied_annex_iii: set[str] = set()
    prohibited = []
    for pid in p.prohibited_declared:
        practice = data.PROHIBITED[pid]
        if pid in p.prohibited_exception_claimed:
            implied = _EXCEPTION_FALLS_TO_ANNEX_III.get(pid)
            if implied:
                implied_annex_iii.add(implied)
            out.warnings.append(
                f"{practice.citation}: you rely on the exception ({practice.exception}). Exceptions are narrow and "
                f"fact-specific: get legal review before shipping. The permitted remainder is treated as high-risk."
            )
        else:
            prohibited.append(practice)
    if prohibited:
        out.tier = "prohibited"
        for pr in prohibited:
            add(Reason(pr.citation, f"{pr.title}: {pr.summary}"))
        dates.add("2025-02-02")
        out.dates = _timeline_for(dates)
        out.warnings.append("A prohibited practice may not be placed on the market, put into service or used in the EU.")
        return out
    dates.add("2025-02-02")  # Art. 4 AI literacy
    reqs[data.LITERACY.id] = data.LITERACY

    # -- high-risk -------------------------------------------------------------------------
    points = sorted(set(p.annex_iii) | implied_annex_iii)
    route_annex_i = p.annex_i_safety_component and p.annex_i_third_party_assessment
    if p.annex_i_safety_component and not p.annex_i_third_party_assessment:
        out.warnings.append("Annex I safety component declared without a third-party conformity assessment requirement: "
                            "Art. 6(1) needs both, so this route is not triggered.")

    derogated = False
    if points:
        profiling_override = p.profiling
        claims_derogation = bool(p.derogation_conditions) or p.no_significant_risk
        full_claim = bool(p.derogation_conditions) and p.no_significant_risk
        if claims_derogation and not full_claim:
            out.warnings.append("Derogation is only partly claimed (it needs both at least one Art. 6(3)(a)-(d) condition "
                                "and a conclusion of no significant risk): treated as high-risk.")
        derogated = full_claim and not profiling_override and not route_annex_i
        if full_claim and profiling_override:
            out.warnings.append("Profiling of natural persons: the Art. 6(3) derogation never applies, so the system stays high-risk.")
        for pt in points:
            area = data.ANNEX_III[pt[0]]
            add(Reason(f"Annex III {pt[0]}" if pt == pt[0] else f"Annex III {pt[0]}({pt[1:]})", data.ANNEX_III_POINTS[pt]))
            if area.qualifier:
                out.warnings.append(f"Annex III area {area.id} ({area.title}) applies {area.qualifier}.")

    if route_annex_i:
        add(Reason("Article 6(1)", "Safety component of (or itself) a product under Annex I harmonisation legislation that "
                                   "requires third-party conformity assessment."))
        dates.add("2028-08-02")
    high_risk_by_iii = bool(points) and not derogated
    if high_risk_by_iii:
        add(Reason("Article 6(2)", "Annex III use case" + (" with profiling of natural persons" if p.profiling else "")))
        dates.add("2027-12-02")

    if route_annex_i or high_risk_by_iii:
        out.tier = "high_risk"
        if _applies("provider", p.role):
            for r in data.HIGH_RISK_PROVIDER:
                reqs[r.id] = r
        if _applies("deployer", p.role):
            for r in data.HIGH_RISK_DEPLOYER:
                reqs[r.id] = r
        out.warnings.append("Annex III 5(b)/(c) (credit, life/health insurance) and public-sector deployers also owe a "
                            "fundamental rights impact assessment (Art. 27)." if _applies("deployer", p.role) else
                            "Deployers of your system carry the Art. 26/27/86 duties; your instructions for use enable them.")
    elif derogated:
        out.tier = "not_high_risk_documented"
        add(Reason("Article 6(3)", "Annex III use case, but the provider concludes it poses no significant risk and relies on: "
                   + "; ".join(data.DEROGATION_CONDITIONS[c] for c in p.derogation_conditions)))
        out.warnings.append("Art. 6(4): this conclusion must be documented before placing on the market, and the system "
                            "still has to be registered. Authorities can challenge it.")
        if _applies("provider", p.role):
            for r in data.DEROGATED:
                reqs[r.id] = r

    # -- transparency ----------------------------------------------------------------------
    triggers = []
    if p.interacts_with_persons and not p.obviously_ai:
        triggers.append("art50_1")
    if p.generates_synthetic_content:
        triggers.append("art50_2")
    if p.emotion_or_biometric_categorisation:
        triggers.append("art50_3")
    if p.deepfake or p.public_interest_text:
        triggers.append("art50_4")
    if p.interacts_with_persons and p.obviously_ai:
        out.warnings.append("Art. 50(1) not triggered because you declare AI interaction is obvious from the circumstances; "
                            "that exception is judged from the perspective of a reasonably well-informed, observant person.")
    for tid in triggers:
        req = data.TRANSPARENCY[tid]
        if _applies(req.role, p.role):
            reqs[tid] = req
        else:
            out.warnings.append(f"{req.citation} falls on deployers of your system; provide what they need to comply.")
        out.transparency.append(tid)
        add(Reason(req.citation, req.title))
    if triggers:
        dates.add("2026-08-02")
        if out.tier == "minimal":
            out.tier = "transparency"

    # -- general-purpose AI models ---------------------------------------------------------
    if p.gpai_model:
        dates.add("2025-08-02")
        systemic = p.training_flops is not None and p.training_flops > data.ART51_SYSTEMIC_FLOPS
        out.gpai = True
        out.gpai_systemic = systemic
        add(Reason("Chapter V", "Provider of a general-purpose AI model"
                   + (f"; training compute {p.training_flops:.2e} FLOPs exceeds the 1e25 presumption threshold (Art. 51(2))"
                      if systemic else "")))
        if _applies("provider", p.role):
            exempt = p.open_source and not systemic
            for r in data.GPAI_PROVIDER:
                if exempt and r.id in ("art53a", "art53b"):
                    continue
                reqs[r.id] = r
            if exempt:
                out.warnings.append(data.OPEN_SOURCE_NOTE)
            if systemic:
                for r in data.GPAI_SYSTEMIC:
                    reqs[r.id] = r
        else:
            out.warnings.append("GPAI model obligations fall on the model provider, not on a deployer.")
        if p.training_flops is None:
            out.warnings.append("training_compute_flops not given: the systemic-risk presumption could not be evaluated.")
        out.warnings.append("A model placed on the market before 2 Aug 2025 has until 2 Aug 2027 to comply (Art. 111(3); verify).")
        if out.tier == "minimal":
            out.tier = "gpai_model"

    out.requirements = list(reqs.values())
    out.dates = _timeline_for(dates)
    out.warnings.append("Dates reflect the source named in `manifest act timeline`; confirm against the Official Journal.")
    return out
