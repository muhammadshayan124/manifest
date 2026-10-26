"""Structured reference data for the EU AI Act (Regulation (EU) 2024/1689).

Everything the classifier, checklist and documentation generator know about the Act lives in
this one module, so each rule traces back to a citable provision and there is a single place
to update when the text or the timeline changes.

Sources, read on 2026-10-26 from artificialintelligenceact.eu (an unofficial but faithful
reproduction of the Official Journal text): Article 5, Article 6, Article 53, Article 113,
Annex III, Annex IV. Article and Annex numbering follows the published Regulation.

Two honest caveats that belong with the data, not buried in a README:

* Dates. The site shows the application dates *as amended by the "Digital Omnibus"* package.
  Whether that package has been formally published in the Official Journal was not settled in
  the sources available when this was written. Treat every date here as "as listed on the
  source, on the as_of date" and confirm before relying on it (see `TIMELINE_NOTE`).
* This is structured data about a statute, not legal advice. Whether a given system falls
  into a category is a legal judgement that depends on facts and on guidance that is still
  being issued (the Commission's high-risk classification guidelines were due 2 Feb 2026).
"""

from __future__ import annotations

from dataclasses import dataclass

AS_OF = "2026-10-26"
SOURCE = "https://artificialintelligenceact.eu"
ART51_SYSTEMIC_FLOPS = 1e25  # Art. 51(2): presumption of high-impact capabilities; verify against the Official Journal


# --------------------------------------------------------------------------------------
# Article 5: prohibited practices
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Practice:
    id: str  # "a".."h" = Art. 5(1)(a)..(h)
    title: str
    summary: str
    exception: str | None = None

    @property
    def citation(self) -> str:
        return f"Article 5(1)({self.id})"


PROHIBITED: dict[str, Practice] = {p.id: p for p in [
    Practice("a", "Manipulative or deceptive techniques",
             "Subliminal, purposefully manipulative or deceptive techniques that materially distort behaviour "
             "by appreciably impairing informed decision-making, causing or likely to cause significant harm."),
    Practice("b", "Exploiting vulnerabilities",
             "Exploiting vulnerabilities due to age, disability or a specific social or economic situation to "
             "materially distort behaviour, causing or likely to cause significant harm."),
    Practice("c", "Social scoring",
             "Evaluating or classifying people over time by social behaviour or personal characteristics, where "
             "the score leads to detrimental treatment in unrelated contexts or unjustified/disproportionate treatment."),
    Practice("d", "Predicting criminal offences from profiling",
             "Risk assessments predicting that a person will commit a criminal offence based solely on profiling "
             "or personality traits.",
             exception="Systems supporting human assessment of involvement in criminal activity that is already "
                       "based on objective, verifiable facts directly linked to it."),
    Practice("e", "Untargeted scraping for facial recognition databases",
             "Creating or expanding facial recognition databases through untargeted scraping of facial images "
             "from the internet or CCTV footage."),
    Practice("f", "Emotion inference in workplace or education",
             "Inferring emotions of people in the workplace or in educational institutions.",
             exception="Use intended for medical or safety reasons."),
    Practice("g", "Biometric categorisation of sensitive attributes",
             "Categorising individuals by biometric data to infer race, political opinions, trade union "
             "membership, religious or philosophical beliefs, sex life or sexual orientation.",
             exception="Labelling or filtering of lawfully acquired biometric datasets, or categorising biometric "
                       "data in law enforcement."),
    Practice("h", "Real-time remote biometric identification for law enforcement",
             "'Real-time' remote biometric identification in publicly accessible spaces for law enforcement.",
             exception="Narrow exceptions (targeted victim/missing-person searches, specific imminent threats, "
                       "serious-offence suspects) with prior judicial or independent authorisation (Art. 5(2)-(4))."),
]}


# --------------------------------------------------------------------------------------
# Annex III: high-risk use cases (Article 6(2))
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Area:
    id: str
    title: str
    points: dict[str, str]  # point id -> description
    qualifier: str | None = None


_LAW = "where permitted by Union or national law"
ANNEX_III: dict[str, Area] = {a.id: a for a in [
    Area("1", "Biometrics", {
        "1a": "Remote biometric identification (excluding verification that only confirms a claimed identity)",
        "1b": "Biometric categorisation based on sensitive or protected attributes",
        "1c": "Emotion recognition",
    }, _LAW),
    Area("2", "Critical infrastructure", {
        "2": "Safety components in managing and operating critical digital infrastructure, road traffic, "
             "or the supply of water, gas, heating or electricity",
    }),
    Area("3", "Education and vocational training", {
        "3a": "Determining access or admission, or assigning people to education and training institutions",
        "3b": "Evaluating learning outcomes, including when used to steer the learning process",
        "3c": "Assessing the level of education a person will receive or can access",
        "3d": "Monitoring and detecting prohibited student behaviour during tests",
    }),
    Area("4", "Employment, workers' management and access to self-employment", {
        "4a": "Recruitment or selection, including targeted job advertising, filtering applications, evaluating candidates",
        "4b": "Decisions affecting work-related relationships (promotion, termination), task allocation based on "
              "personal traits or behaviour, monitoring and evaluating performance",
    }),
    Area("5", "Access to essential private and public services and benefits", {
        "5a": "Public authorities evaluating eligibility for essential public assistance benefits and services, "
              "and granting, reducing, revoking or reclaiming them",
        "5b": "Evaluating creditworthiness or establishing credit scores (excluding financial fraud detection)",
        "5c": "Risk assessment and pricing for life and health insurance",
        "5d": "Evaluating and classifying emergency calls, dispatching or prioritising emergency first response, "
              "and emergency healthcare patient triage",
    }),
    Area("6", "Law enforcement", {
        "6a": "Assessing the risk of a person becoming a victim of criminal offences",
        "6b": "Polygraphs or similar tools",
        "6c": "Evaluating the reliability of evidence in investigation or prosecution",
        "6d": "Assessing the risk of offending or re-offending (not solely on profiling), or assessing personality "
              "traits or past criminal behaviour",
        "6e": "Profiling of natural persons in detecting, investigating or prosecuting criminal offences",
    }, _LAW),
    Area("7", "Migration, asylum and border control management", {
        "7a": "Polygraphs or similar tools used by competent public authorities",
        "7b": "Assessing security, irregular-migration or health risks posed by a person entering a Member State",
        "7c": "Assisting the examination of asylum, visa or residence-permit applications and related complaints",
        "7d": "Detecting, recognising or identifying persons in migration, asylum or border control "
              "(excluding travel document verification)",
    }, _LAW),
    Area("8", "Administration of justice and democratic processes", {
        "8a": "Assisting a judicial authority in researching and interpreting facts and law and applying it to facts",
        "8b": "Influencing the outcome of an election or referendum, or voting behaviour "
              "(excluding tools used only for administrative or logistical campaign organisation)",
    }),
]}
ANNEX_III_POINTS: dict[str, str] = {pid: text for a in ANNEX_III.values() for pid, text in a.points.items()}

# Article 6(3) derogation conditions (an Annex III system is NOT high-risk if it poses no significant
# risk AND fulfils at least one of these) -- except that profiling of natural persons is always high-risk.
DEROGATION_CONDITIONS: dict[str, str] = {
    "procedural_task": "6(3)(a): performs a narrow procedural task",
    "improves_human_result": "6(3)(b): improves the result of a previously completed human activity",
    "detects_patterns": "6(3)(c): detects decision-making patterns or deviations without replacing or "
                        "influencing a completed human assessment, absent proper human review",
    "preparatory_task": "6(3)(d): performs a preparatory task to an assessment relevant to Annex III use cases",
}

OUT_OF_SCOPE: dict[str, str] = {
    "military": "Art. 2(3): exclusively military, defence or national-security purposes",
    "research": "Art. 2(6): developed and put into service for the sole purpose of scientific research",
    "pre_market_rd": "Art. 2(8): research, testing or development before placing on the market (not real-world testing)",
    "personal": "Art. 2(10): personal, non-professional use by a natural person deployer",
}


# --------------------------------------------------------------------------------------
# Requirements, by regime
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Requirement:
    id: str
    citation: str
    title: str
    role: str  # provider | deployer | both
    summary: str
    evidence_hint: str


R = Requirement
HIGH_RISK_PROVIDER: list[Requirement] = [
    R("art9", "Article 9", "Risk management system", "provider",
      "A continuous, documented risk management process across the lifecycle: identify, estimate, evaluate and "
      "mitigate risks to health, safety and fundamental rights; test against defined metrics.",
      "Risk register, residual-risk acceptance, test plan and results"),
    R("art10", "Article 10", "Data and data governance", "provider",
      "Training, validation and testing data governed for relevance, representativeness, error-freeness and "
      "bias examination; document provenance, collection, cleaning and labelling.",
      "Data sheets, bias analysis, data lineage"),
    R("art11", "Article 11 / Annex IV", "Technical documentation", "provider",
      "Documentation drawn up before placing on the market and kept up to date, containing at least the Annex IV elements.",
      "Output of `manifest act docs`, completed and reviewed"),
    R("art12", "Article 12", "Record-keeping (automatic logs)", "provider",
      "The system technically allows automatic recording of events over its lifetime, enough to identify risk "
      "situations and support post-market monitoring.",
      "Logging design, sample logs, retention configuration"),
    R("art13", "Article 13", "Transparency and instructions for use", "provider",
      "Enough transparency for deployers to interpret output and use it appropriately; instructions for use "
      "covering purpose, accuracy, limitations, oversight measures.",
      "Instructions for use document"),
    R("art14", "Article 14", "Human oversight", "provider",
      "Designed so natural persons can effectively oversee it during use, understand its limits, avoid automation "
      "bias, interpret output, override or stop it.",
      "Oversight design, UI evidence, override/stop mechanism test"),
    R("art15", "Article 15", "Accuracy, robustness and cybersecurity", "provider",
      "Appropriate and declared accuracy levels, resilience to errors and to attempts by third parties to alter "
      "use or performance.",
      "Accuracy metrics, robustness and security test reports"),
    R("art16", "Article 16", "General provider obligations", "provider",
      "Ensure compliance with Section 2; indicate provider name and contact on the system; have a QMS; keep "
      "documentation and logs; run conformity assessment; draw up the declaration; affix CE marking; register.",
      "Compliance matrix across Articles 9-15 and 17-22"),
    R("art17", "Article 17", "Quality management system", "provider",
      "A documented QMS covering compliance strategy, design and testing procedures, data management, risk "
      "management, post-market monitoring, incident reporting and accountability.",
      "QMS manual and procedures"),
    R("art18", "Article 18", "Documentation keeping", "provider",
      "Keep the technical documentation, QMS documentation and declaration of conformity available to authorities "
      "for 10 years after the system is placed on the market.",
      "Retention policy and archive location"),
    R("art19", "Article 19", "Automatically generated logs", "provider",
      "Keep logs under the provider's control for a period appropriate to the purpose, at least six months.",
      "Log retention configuration"),
    R("art20", "Article 20", "Corrective actions and duty of information", "provider",
      "Take corrective action (bring into conformity, withdraw, disable or recall) and inform distributors, "
      "deployers and authorities when the system is or may be non-compliant.",
      "Corrective-action procedure"),
    R("art43", "Article 43", "Conformity assessment", "provider",
      "Complete the applicable conformity assessment procedure (internal control or notified body, depending on "
      "the Annex III point and use of harmonised standards) before placing on the market.",
      "Assessment record or notified-body certificate"),
    R("art47", "Article 47", "EU declaration of conformity", "provider",
      "Draw up and keep a written, machine-readable EU declaration of conformity for each high-risk system.",
      "Signed declaration"),
    R("art48", "Article 48", "CE marking", "provider",
      "Affix the CE marking (visibly, legibly, indelibly; digitally for digital-only systems).",
      "Marking evidence"),
    R("art49", "Article 49", "Registration in the EU database", "provider",
      "Register the system (and the provider) in the EU database before placing on the market or putting into service.",
      "Registration reference"),
    R("art72", "Article 72", "Post-market monitoring", "provider",
      "A system, proportionate to the risk, to actively collect and analyse performance data over the lifetime "
      "and evaluate continuous compliance, based on a post-market monitoring plan.",
      "Monitoring plan and review cadence"),
    R("art73", "Article 73", "Serious incident reporting", "provider",
      "Report serious incidents to the market surveillance authorities within the prescribed time limits.",
      "Incident-response and reporting procedure"),
]

HIGH_RISK_DEPLOYER: list[Requirement] = [
    R("art26", "Article 26", "Deployer obligations", "deployer",
      "Use per the instructions for use; assign human oversight to competent, trained persons; ensure input data "
      "is relevant; monitor operation and report risks and incidents; keep logs under your control for at least "
      "six months; inform workers' representatives and affected persons where required.",
      "Deployment procedure, oversight assignment, log retention"),
    R("art27", "Article 27", "Fundamental rights impact assessment (conditional)", "deployer",
      "Required before first use for deployers that are public bodies or private entities providing public "
      "services, and for deployers of Annex III 5(b) (credit scoring) and 5(c) (life/health insurance) systems.",
      "FRIA document, notification to the market surveillance authority"),
    R("art86", "Article 86", "Right to explanation of individual decision-making", "deployer",
      "Affected persons subject to a decision based mainly on the output of certain Annex III systems that has "
      "legal or similarly significant effects may request a clear explanation of the system's role.",
      "Explanation process and template"),
]

DEROGATED: list[Requirement] = [
    R("art6_4", "Article 6(4)", "Document the 'not high-risk' assessment", "provider",
      "A provider that concludes its Annex III system is not high-risk must document that assessment before "
      "placing it on the market or putting it into service, and provide it to authorities on request.",
      "Assessment record (`manifest act docs` produces a template)"),
    R("art49_2", "Article 49(2)", "Register the derogated system", "provider",
      "Such a provider must still register the system in the EU database.",
      "Registration reference"),
]

LITERACY = R("art4", "Article 4", "AI literacy", "both",
             "Take measures to ensure a sufficient level of AI literacy of staff and others operating or using "
             "AI systems on your behalf, considering their knowledge, context and the people affected.",
             "Training records")

TRANSPARENCY: dict[str, Requirement] = {r.id: r for r in [
    R("art50_1", "Article 50(1)", "Tell people they are interacting with an AI system", "provider",
      "Design AI systems that interact directly with people so they are informed it is an AI system, unless "
      "obvious from the circumstances.", "Disclosure in the UI/flow; `manifest scan` findings"),
    R("art50_2", "Article 50(2)", "Mark synthetic content as machine-readable", "provider",
      "Mark outputs of systems generating synthetic audio, image, video or text in a machine-readable format "
      "and make them detectable as artificially generated, using effective, interoperable, robust, reliable "
      "technical solutions as far as technically feasible.", "Watermarking/provenance (e.g. C2PA); `manifest scan` findings"),
    R("art50_3", "Article 50(3)", "Inform people exposed to emotion recognition or biometric categorisation", "deployer",
      "Deployers of emotion recognition or biometric categorisation systems inform the exposed natural persons "
      "and process personal data in line with the GDPR.", "Notice at point of exposure"),
    R("art50_4", "Article 50(4)", "Disclose deepfakes and AI-generated public-interest text", "deployer",
      "Deployers disclose that deepfake content is artificially generated or manipulated, and that AI-generated "
      "or manipulated text published to inform the public on matters of public interest is AI-generated "
      "(unless human-reviewed under editorial responsibility).", "Labelling at first exposure"),
]}

GPAI_PROVIDER: list[Requirement] = [
    R("art53a", "Article 53(1)(a)", "GPAI technical documentation", "provider",
      "Draw up and keep up to date documentation of the model, including training, testing and evaluation "
      "results (Annex XI), and provide it to the AI Office on request.", "Model documentation"),
    R("art53b", "Article 53(1)(b)", "Information for downstream providers", "provider",
      "Provide information and documentation (Annex XII minimum) to providers integrating the model.",
      "Downstream integration documentation"),
    R("art53c", "Article 53(1)(c)", "Copyright compliance policy", "provider",
      "Put in place a policy to comply with EU copyright law, including identifying and respecting rights "
      "reservations (Directive (EU) 2019/790).", "Copyright policy"),
    R("art53d", "Article 53(1)(d)", "Public summary of training content", "provider",
      "Publish a sufficiently detailed summary of the content used for training, following the AI Office template.",
      "Published training-data summary"),
]
GPAI_SYSTEMIC: list[Requirement] = [
    R("art52", "Article 52", "Notify the Commission (systemic risk)", "provider",
      "Notify the Commission without delay, and in any event within two weeks, once the systemic-risk threshold "
      "is met or known to be met.", "Notification record"),
    R("art55", "Article 55", "Systemic-risk obligations", "provider",
      "Model evaluation including adversarial testing, assess and mitigate systemic risks, track and report "
      "serious incidents, and ensure adequate cybersecurity.", "Evaluation reports, incident process"),
]
OPEN_SOURCE_NOTE = (
    "Art. 53(2): a model released under a free and open-source licence with publicly available weights, "
    "architecture and usage information is exempt from 53(1)(a) and (b) only -- never from (c) and (d), and "
    "not at all if it has systemic risk."
)


# --------------------------------------------------------------------------------------
# Annex IV: technical documentation
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class DocSection:
    id: str
    ref: str  # e.g. "Annex IV 2(d)"
    title: str
    prompt: str


ANNEX_IV: list[DocSection] = [
    DocSection("1a", "Annex IV 1(a)", "Intended purpose, provider and version", "Intended purpose, provider name, system version."),
    DocSection("1b", "Annex IV 1(b)", "Interaction with other hardware, software and AI systems", "How the system interacts with other hardware/software, including other AI systems."),
    DocSection("1c", "Annex IV 1(c)", "Software/firmware versions and update requirements", "Versions of relevant software or firmware; any update requirements."),
    DocSection("1d", "Annex IV 1(d)", "Forms of placing on the market", "Software package, API, embedded in hardware, download, etc."),
    DocSection("1e", "Annex IV 1(e)", "Intended hardware", "Hardware the system is intended to run on."),
    DocSection("1f", "Annex IV 1(f)", "External features, markings, internal layout (where a product component)", "Photographs or illustrations of external features, markings and internal layout, if a product component."),
    DocSection("1g", "Annex IV 1(g)", "User interface", "Basic description of the user interface provided to the deployer."),
    DocSection("1h", "Annex IV 1(h)", "Instructions for use", "Instructions for use for the deployer, and installation instructions where relevant."),
    DocSection("2a", "Annex IV 2(a)", "Development methods and steps", "Methods and steps used for development, including use of pre-trained systems or tools from third parties."),
    DocSection("2b", "Annex IV 2(b)", "Design specifications", "General logic, algorithms, key design choices, optimisation goals, trade-offs, classification choices, what the system is designed to optimise for."),
    DocSection("2c", "Annex IV 2(c)", "System architecture and computational resources", "Architecture, how components build on each other, computational resources used to develop, train, test and validate."),
    DocSection("2d", "Annex IV 2(d)", "Data requirements and data governance", "Training methodologies and techniques, datasets used (provenance, scope, main characteristics), how data was obtained, labelled and cleaned."),
    DocSection("2e", "Annex IV 2(e)", "Human oversight assessment", "Assessment of the human oversight measures needed (Art. 14), including technical measures to facilitate output interpretation."),
    DocSection("2f", "Annex IV 2(f)", "Pre-determined changes and continuous compliance", "Pre-determined changes to the system and its performance, with technical solutions ensuring continuous compliance."),
    DocSection("2g", "Annex IV 2(g)", "Validation and testing", "Validation and testing procedures, data used and main characteristics, metrics for accuracy, robustness and compliance, test logs and reports."),
    DocSection("2h", "Annex IV 2(h)", "Cybersecurity measures", "Cybersecurity measures put in place."),
    DocSection("3", "Annex IV 3", "Monitoring, functioning and control", "Capabilities and limitations incl. accuracy for specific groups; foreseeable unintended outcomes and risks to health, safety, fundamental rights, discrimination; human oversight measures; input data specifications."),
    DocSection("4", "Annex IV 4", "Appropriateness of performance metrics", "Why the chosen performance metrics are appropriate for this system."),
    DocSection("5", "Annex IV 5", "Risk management system", "Detailed description of the risk management system (Art. 9)."),
    DocSection("6", "Annex IV 6", "Relevant changes through the lifecycle", "Relevant changes made by the provider to the system through its lifecycle."),
    DocSection("7", "Annex IV 7", "Standards applied", "List of harmonised standards applied (in full or part), or descriptions of the solutions adopted where none were applied, including other standards or specifications."),
    DocSection("8", "Annex IV 8", "EU declaration of conformity", "A copy of the EU declaration of conformity (Art. 47)."),
    DocSection("9", "Annex IV 9", "Post-market performance evaluation", "The system used to evaluate performance in the post-market phase, including the post-market monitoring plan (Art. 72)."),
]


# --------------------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------------------

TIMELINE: list[tuple[str, str, str]] = [
    ("2025-02-02", "Chapters I-II: scope, AI literacy (Art. 4) and prohibited practices (Art. 5) apply", "Art. 113(a)"),
    ("2025-08-02", "General-purpose AI obligations (Ch. V), governance (Ch. VII) and penalties (Ch. XII) apply", "Art. 113(b)"),
    ("2026-08-02", "General application, including Article 50 transparency obligations", "Art. 113"),
    ("2026-12-02", "Prohibitions added to Art. 5(1) (points (ba), (bb)) and Art. 5(1a)-(1b) apply (as amended)", "Art. 113 as amended"),
    ("2027-12-02", "Annex III high-risk obligations apply (as amended; previously 2 Aug 2026)", "Art. 113 as amended"),
    ("2028-08-02", "Annex I (product-safety) high-risk obligations apply (as amended; previously 2 Aug 2027)", "Art. 113 as amended"),
]
TIMELINE_NOTE = (
    f"Dates are as listed on {SOURCE} on {AS_OF}, reflecting the 'Digital Omnibus' amendments. Whether the "
    "amendments have been formally published in the Official Journal was not confirmed when this was written. "
    "Check the Official Journal text before relying on any date."
)
