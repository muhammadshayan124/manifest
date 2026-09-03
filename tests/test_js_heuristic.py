from pathlib import Path

from manifest.detectors import js_heuristic
from manifest.detectors.base import Confidence

FIXTURES = Path(__file__).parent / "fixtures" / "js"


def test_flags_tsx_chat_with_no_disclosure():
    findings = js_heuristic.scan_file(FIXTURES / "noncompliant_chat.tsx")
    assert len(findings) == 1
    assert findings[0].confidence == Confidence.likely_violation


def test_downgrades_when_disclosure_text_present_in_file():
    findings = js_heuristic.scan_file(FIXTURES / "compliant_chat.tsx")
    assert len(findings) == 1
    assert findings[0].confidence == Confidence.needs_review


def test_ignores_non_js_extensions():
    assert js_heuristic.scan_file(Path(__file__).parent / "fixtures" / "python" / "noncompliant_chatbot.py") == []
