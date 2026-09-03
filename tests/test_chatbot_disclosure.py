from pathlib import Path

from manifest.detectors import chatbot_disclosure
from manifest.detectors.base import Confidence

FIXTURES = Path(__file__).parent / "fixtures" / "python"


def test_flags_chatbot_with_no_disclosure():
    findings = chatbot_disclosure.scan_file(FIXTURES / "noncompliant_chatbot.py")
    assert len(findings) == 1
    assert findings[0].confidence == Confidence.likely_violation
    assert findings[0].provision.citation == "Article 50(1)"


def test_downgrades_to_needs_review_when_disclosure_text_present():
    findings = chatbot_disclosure.scan_file(FIXTURES / "compliant_chatbot.py")
    assert len(findings) == 1
    assert findings[0].confidence == Confidence.needs_review


def test_does_not_flag_non_user_facing_batch_job():
    findings = chatbot_disclosure.scan_file(FIXTURES / "negative_control_batch_job.py")
    assert findings == []


def test_ignores_files_with_no_llm_sdk_import(tmp_path):
    f = tmp_path / "plain.py"
    f.write_text("def chat():\n    return 'hello'\n")
    assert chatbot_disclosure.scan_file(f) == []


def test_handles_syntax_errors_gracefully(tmp_path):
    f = tmp_path / "broken.py"
    f.write_text("def chat(:\n    this is not valid python\n")
    assert chatbot_disclosure.scan_file(f) == []
