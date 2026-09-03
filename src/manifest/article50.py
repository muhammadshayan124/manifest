"""Reference text for the specific EU AI Act Article 50 provisions this tool checks
against. Kept as one small, citable module rather than scattered strings, so every
finding traces back to the exact obligation it's flagging -- and so this is the one place
to update if the Commission's guidelines/Code of Practice clarify wording.

Grounded in the Act's actual text and the Commission's published guidance as of the
research done for this project (Sept 2026) -- not paraphrased from memory. Sources:
artificialintelligenceact.eu/article/50/, digital-strategy.ec.europa.eu's Article 50 FAQ,
and the Commission's draft Code of Practice on Transparency of AI-generated Content
(which names C2PA Content Credentials as an example machine-readable marking mechanism).

Applies from 2 August 2026. Note: some sources describe a narrower deferral specifically
for the machine-readable marking/detection sub-obligation (to 2 December 2026) layered on
top of the general 2 August 2026 application date for Article 50 as a whole -- this tool
doesn't take a position on which date controls for your situation; that's a legal
question, not a static-analysis one.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Provision:
    citation: str
    who: str  # "provider" or "deployer" -- the Act assigns obligations to different roles
    summary: str


CHATBOT_DISCLOSURE = Provision(
    citation="Article 50(1)",
    who="provider",
    summary=(
        "Providers of AI systems intended to interact directly with natural persons "
        "(chatbots, AI agents, avatars) must ensure the natural person is informed they "
        "are interacting with an AI system -- unless this is obvious to a reasonably "
        "well-informed, observant, and circumspect person given the circumstances of use."
    ),
)

GENERATED_CONTENT_MARKING = Provision(
    citation="Article 50(2)",
    who="provider",
    summary=(
        "Providers of AI systems generating synthetic audio, image, video, or text "
        "content must ensure the outputs are marked in a machine-readable format and "
        "detectable as artificially generated or manipulated, using technical solutions "
        "that are effective, interoperable, robust, and reliable as far as technically "
        "feasible (the Commission's draft Code of Practice names C2PA Content "
        "Credentials as one such mechanism)."
    ),
)

DEEPFAKE_DISCLOSURE = Provision(
    citation="Article 50(4)",
    who="deployer",
    summary=(
        "Deployers of an AI system that generates or manipulates image, audio, or video "
        "content constituting a deepfake must disclose that the content has been "
        "artificially generated or manipulated -- to the affected natural person, on "
        "first exposure at the latest, in a clear and distinguishable manner."
    ),
)

PUBLIC_INTEREST_TEXT_DISCLOSURE = Provision(
    citation="Article 50(4), second subparagraph",
    who="deployer",
    summary=(
        "Deployers of an AI system generating or manipulating text published to inform "
        "the public on matters of public interest must disclose that the text has been "
        "artificially generated or manipulated -- unless the content has undergone a "
        "human review or editorial control process and a natural or legal person holds "
        "editorial responsibility for its publication."
    ),
)
