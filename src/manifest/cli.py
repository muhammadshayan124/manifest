from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from manifest.act.cli import act_app
from manifest.detectors.base import Confidence
from manifest.report import print_table, split_by_visibility, to_json, to_sarif
from manifest.scan import scan_path

app = typer.Typer(
    help="Static analysis for EU AI Act Article 50 transparency obligations. "
    "Flags candidate compliance gaps for human review -- see README before relying on it."
)
console = Console()
app.add_typer(act_app, name="act")


class OutputFormat(str, Enum):
    table = "table"
    json = "json"
    sarif = "sarif"


class FailOn(str, Enum):
    none = "none"
    likely = "likely"  # fail only on likely_violation: the findings with no disclosure signal at all
    any = "any"        # fail on every shown finding, including needs_review


@app.callback()
def _main() -> None:
    """Present so Typer keeps 'scan' as an explicit subcommand -- with only one command
    registered and no callback, Typer silently auto-promotes it to the default (so
    `manifest scan <path>` would fail with a confusing "unexpected extra argument", and
    only bare `manifest <path>` would work). Caught by actually running the CLI, not just
    the underlying functions -- keeping the interface `manifest scan <path>` on purpose,
    since it reads better and leaves room for future subcommands.
    """


@app.command()
def scan(
    path: Annotated[Path, typer.Argument(help="File or directory to scan")] = Path("."),
    output_format: Annotated[OutputFormat, typer.Option("--format", help="Output format; sarif feeds GitHub code scanning")] = OutputFormat.table,
    json_output: Annotated[bool, typer.Option("--json", help="Shorthand for --format json")] = False,
    include_low_signal: Annotated[bool, typer.Option(help="Also show low_signal findings (private helpers matched by name only)")] = False,
    fail_on: Annotated[FailOn, typer.Option(help="Exit non-zero when findings of this kind exist (for CI)")] = FailOn.none,
    fail_on_findings: Annotated[bool, typer.Option(help="Deprecated alias for --fail-on any")] = False,
) -> None:
    """Scan a file or directory for Article 50 transparency gaps."""
    if not path.exists():
        console.print(f"[red]No such path: {path}[/red]")
        raise typer.Exit(code=2)

    if json_output:
        output_format = OutputFormat.json
    if fail_on_findings:
        fail_on = FailOn.any

    shown, hidden = split_by_visibility(scan_path(path), include_low_signal)

    if output_format == OutputFormat.json:
        print(to_json(shown, hidden_low_signal=hidden))
    elif output_format == OutputFormat.sarif:
        print(to_sarif(shown))
    else:
        print_table(shown, console, hidden_low_signal=hidden)

    likely = any(f.confidence == Confidence.likely_violation for f in shown)
    if (fail_on == FailOn.any and shown) or (fail_on == FailOn.likely and likely):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
