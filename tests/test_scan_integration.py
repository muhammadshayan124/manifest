from pathlib import Path

from manifest.scan import scan_path

FIXTURES = Path(__file__).parent / "fixtures"


def test_scans_whole_fixture_dir_and_finds_expected_mix():
    findings = scan_path(FIXTURES)
    # 4 real findings expected across python+js fixtures: noncompliant_chatbot,
    # compliant_chatbot, noncompliant_image_gen, compliant_image_gen, noncompliant_chat.tsx,
    # compliant_chat.tsx -- 6 total; negative_control produces none.
    assert len(findings) == 6

    citations = {f.provision.citation for f in findings}
    assert citations == {"Article 50(1)", "Article 50(2)"}


def test_scanning_a_single_file_works():
    findings = scan_path(FIXTURES / "python" / "noncompliant_chatbot.py")
    assert len(findings) == 1


def test_scanning_empty_dir_returns_no_findings(tmp_path):
    assert scan_path(tmp_path) == []
