"""Shared Finding shape every detector produces. Deliberately not a pass/fail verdict --
`confidence` and `needs_review` are explicit because static analysis can find a candidate
pattern (an LLM call, a generation API call) but can't verify a human actually sees a
disclosure at runtime. Every finding says so. See README's "what this doesn't do" section
before treating output as a compliance certificate.
"""

from dataclasses import dataclass
from enum import Enum

from manifest.article50 import Provision


class Confidence(str, Enum):
    likely_violation = "likely_violation"  # pattern matched, no disclosure signal found nearby
    needs_review = "needs_review"          # pattern matched, a disclosure signal WAS found -- verify it's real


@dataclass
class Finding:
    file: str
    line: int
    provision: Provision
    confidence: Confidence
    detail: str          # what was found (e.g. the API call) and why it triggered
    snippet: str = ""     # the offending line, for context in the report
