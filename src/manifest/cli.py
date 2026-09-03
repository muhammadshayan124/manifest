from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from manifest.report import print_table, to_json
from manifest.scan import scan_path

app = typer.Typer(
    help="Static analysis for EU AI Act Article 50 transparency obligations. "
    "Flags candidate compliance gaps for human review -- see README before relying on it."
)
console = Console()


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
    json_output: Annotated[bool, typer.Option("--json", help="Output JSON instead of a table")] = False,
    fail_on_findings: Annotated[bool, typer.Option(help="Exit non-zero if anything is flagged (for CI)")] = False,
) -> None:
    """Scan a file or directory for Article 50 transparency gaps."""
    if not path.exists():
        console.print(f"[red]No such path: {path}[/red]")
        raise typer.Exit(code=2)

    findings = scan_path(path)

    if json_output:
        print(to_json(findings))
    else:
        print_table(findings, console)

    if fail_on_findings and findings:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
