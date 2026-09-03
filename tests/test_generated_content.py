from pathlib import Path

from manifest.detectors import generated_content
from manifest.detectors.base import Confidence

FIXTURES = Path(__file__).parent / "fixtures" / "python"


def test_flags_generation_with_no_labeling():
    findings = generated_content.scan_file(FIXTURES / "noncompliant_image_gen.py")
    assert len(findings) == 1
    assert findings[0].confidence == Confidence.likely_violation
    assert findings[0].provision.citation == "Article 50(2)"


def test_downgrades_to_needs_review_when_labeling_step_present():
    findings = generated_content.scan_file(FIXTURES / "compliant_image_gen.py")
    assert len(findings) == 1
    assert findings[0].confidence == Confidence.needs_review


def test_ignores_files_with_no_generative_sdk_import(tmp_path):
    f = tmp_path / "plain.py"
    f.write_text("def make_thing():\n    return 42\n")
    assert generated_content.scan_file(f) == []
