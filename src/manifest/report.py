"""Formats findings as a terminal table (rich) or JSON. Both formats carry the same
disclaimer -- this is a review aid, not a compliance certificate.
"""

import json
from dataclasses import asdict

from rich.console import Console
from rich.table import Table

from manifest.detectors.base import Confidence, Finding

DISCLAIMER = (
    "manifest flags code patterns for human/legal review against EU AI Act Article 50. "
    "It does not certify compliance, and a clean scan is not a legal guarantee -- static "
    "analysis cannot verify a disclosure is actually shown to a user at runtime, or that "
    "a watermark survives re-encoding. See README's \"What this doesn't do\" section."
)


def to_json(findings: list[Finding]) -> str:
    return json.dumps(
        {
            "disclaimer": DISCLAIMER,
            "finding_count": len(findings),
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


def print_table(findings: list[Finding], console: Console | None = None) -> None:
    console = console or Console()

    if not findings:
        console.print("[green]No candidate Article 50 issues found.[/green]")
        console.print(f"[dim]{DISCLAIMER}[/dim]")
        return

    table = Table(title="manifest -- EU AI Act Article 50 findings")
    table.add_column("Confidence", style="bold")
    table.add_column("Citation")
    table.add_column("Location")
    table.add_column("Detail", overflow="fold")

    # Likely violations first -- the ones that most need attention.
    ordered = sorted(findings, key=lambda f: f.confidence != Confidence.likely_violation)
    for f in ordered:
        style = "red" if f.confidence == Confidence.likely_violation else "yellow"
        table.add_row(
            f"[{style}]{f.confidence.value}[/{style}]",
            f.provision.citation,
            f"{f.file}:{f.line}",
            f.detail,
        )

    console.print(table)
    console.print(f"\n[dim]{DISCLAIMER}[/dim]")
