"""Formats findings as a terminal table (rich) or JSON. Both formats carry the same
disclaimer -- this is a review aid, not a compliance certificate.
"""

import json
import re
from pathlib import Path

from rich.console import Console
from rich.table import Table

from manifest.detectors.base import Confidence, Finding

DISCLAIMER = (
    "manifest flags code patterns for human/legal review against EU AI Act Article 50. "
    "It does not certify compliance, and a clean scan is not a legal guarantee -- static "
    "analysis cannot verify a disclosure is actually shown to a user at runtime, or that "
    "a watermark survives re-encoding. See README's \"What this doesn't do\" section."
)


_ORDER = {Confidence.likely_violation: 0, Confidence.needs_review: 1, Confidence.low_signal: 2}
_SARIF_LEVEL = {
    Confidence.likely_violation: "warning",
    Confidence.needs_review: "note",
    Confidence.low_signal: "note",
}
_INFO_URI = "https://github.com/muhammadshayan124/manifest"


def split_by_visibility(findings: list[Finding], include_low_signal: bool) -> tuple[list[Finding], int]:
    """Returns (findings to show, number of low_signal findings hidden)."""
    if include_low_signal:
        return findings, 0
    shown = [f for f in findings if f.confidence != Confidence.low_signal]
    return shown, len(findings) - len(shown)


def _rule_id(citation: str) -> str:
    """'Article 50(4), second subparagraph' -> 'AIA-50-4-2'; 'Article 50(1)' -> 'AIA-50-1'."""
    match = re.search(r"50\((\d)\)", citation)
    base = f"AIA-50-{match.group(1)}" if match else "AIA-50"
    return base + ("-2" if "second subparagraph" in citation else "")


def to_sarif(findings: list[Finding]) -> str:
    """SARIF 2.1.0, so results show up in GitHub code scanning (Security tab + PR annotations)."""
    rules: dict[str, dict] = {}
    results = []
    for f in findings:
        rid = _rule_id(f.provision.citation)
        rules.setdefault(
            rid,
            {
                "id": rid,
                "name": f.provision.citation.replace(" ", ""),
                "shortDescription": {"text": f"EU AI Act {f.provision.citation}"},
                "fullDescription": {"text": f.provision.summary},
                "helpUri": "https://artificialintelligenceact.eu/article/50/",
                "properties": {"obligation_holder": f.provision.who},
            },
        )
        path = Path(f.file)
        try:
            uri = path.resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            uri = path.as_posix()
        results.append(
            {
                "ruleId": rid,
                "level": _SARIF_LEVEL[f.confidence],
                "message": {"text": f.detail},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": uri},
                            "region": {"startLine": f.line, "snippet": {"text": f.snippet}},
                        }
                    }
                ],
                "properties": {"confidence": f.confidence.value},
            }
        )
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "manifest",
                        "informationUri": _INFO_URI,
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif, indent=2)


def to_json(findings: list[Finding], hidden_low_signal: int = 0) -> str:
    return json.dumps(
        {
            "disclaimer": DISCLAIMER,
            "finding_count": len(findings),
            "hidden_low_signal_count": hidden_low_signal,
            "findings": [
                {
                    "file": f.file,
                    "line": f.line,
                    "citation": f.provision.citation,
                    "who": f.provision.who,
                    "confidence": f.confidence.value,
                    "detail": f.detail,
                    "snippet": f.snippet,
                }
                for f in findings
            ],
        },
        indent=2,
    )


def _print_hidden_note(console: Console, hidden_low_signal: int) -> None:
    if hidden_low_signal:
        console.print(
            f"[dim]{hidden_low_signal} low-signal finding(s) hidden "
            "(private helpers, test/demo code). Use --include-low-signal to show them.[/dim]"
        )


def print_table(findings: list[Finding], console: Console | None = None, hidden_low_signal: int = 0) -> None:
    console = console or Console()

    if not findings:
        console.print("[green]No candidate Article 50 issues found.[/green]")
        _print_hidden_note(console, hidden_low_signal)
        console.print(f"[dim]{DISCLAIMER}[/dim]")
        return

    table = Table(title="manifest -- EU AI Act Article 50 findings")
    table.add_column("Confidence", style="bold")
    table.add_column("Citation")
    table.add_column("Location")
    table.add_column("Detail", overflow="fold")

    # Likely violations first -- the ones that most need attention.
    ordered = sorted(findings, key=lambda f: _ORDER[f.confidence])
    styles = {Confidence.likely_violation: "red", Confidence.needs_review: "yellow", Confidence.low_signal: "dim"}
    for f in ordered:
        style = styles[f.confidence]
        table.add_row(
            f"[{style}]{f.confidence.value}[/{style}]",
            f.provision.citation,
            f"{f.file}:{f.line}",
            f.detail,
        )

    console.print(table)
    _print_hidden_note(console, hidden_low_signal)
    console.print(f"\n[dim]{DISCLAIMER}[/dim]")
