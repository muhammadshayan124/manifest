"""`manifest act ...`: classify a system, track conformity, generate Annex IV documentation."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from manifest.act import checklist as cl
from manifest.act import data, docs
from manifest.act.classify import Classification, classify
from manifest.act.profile import (
    ProfileError,
    SystemProfile,
    load_profile,
    template_yaml,
)
from manifest.scan import scan_path

act_app = typer.Typer(
    help="EU AI Act toolkit: classify a system's risk tier, track a conformity checklist, generate Annex IV documentation. "
    "Not legal advice.",
    no_args_is_help=True,
)
console = Console(highlight=False)
DEFAULT_CHECKLIST = Path("manifest-checklist.yaml")


def _load(profile: Path) -> tuple[SystemProfile, Classification]:
    try:
        p = load_profile(profile)
    except (ProfileError, OSError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    return p, classify(p)


@act_app.command()
def init(
    out: Annotated[Path, typer.Option(help="Where to write the annotated template")] = Path("manifest-system.yaml"),
    force: Annotated[bool, typer.Option(help="Overwrite an existing file")] = False,
) -> None:
    """Write an annotated system profile to fill in."""
    if out.exists() and not force:
        console.print(f"[red]{out} exists; use --force to overwrite[/red]")
        raise typer.Exit(2)
    out.write_text(template_yaml(), encoding="utf-8")
    console.print(f"wrote {out}. Fill it in, then run: manifest act classify {out}")


@act_app.command("classify")
def classify_cmd(
    profile: Annotated[Path, typer.Argument(help="System profile YAML")],
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output")] = False,
) -> None:
    """Classify the system and list what the Act asks of it."""
    _, c = _load(profile)
    if as_json:
        print(json.dumps({
            "system": c.system, "tier": c.tier, "reasons": [asdict(r) for r in c.reasons],
            "requirements": [{"id": r.id, "citation": r.citation, "title": r.title, "role": r.role} for r in c.requirements],
            "transparency": c.transparency, "gpai": c.gpai, "gpai_systemic_risk": c.gpai_systemic, "warnings": c.warnings,
            "dates": [{"date": d, "what": t} for d, t in c.dates],
        }, indent=2))
        return
    colour = {"prohibited": "red", "high_risk": "red", "not_high_risk_documented": "yellow", "transparency": "yellow"}.get(c.tier, "green")
    extra = (" + GPAI model duties" + (" (systemic risk presumed)" if c.gpai_systemic else "")) if c.gpai else ""
    console.print(f"[bold]{c.system}[/bold]: [{colour}]{c.tier.replace('_', ' ').upper()}[/{colour}]{extra}")
    for r in c.reasons:
        console.print(f"  [dim]{r.citation}[/dim]  {r.text}")
    if c.requirements:
        t = Table(title="What applies to you")
        for col in ("id", "citation", "requirement", "role"):
            t.add_column(col)
        for r in c.requirements:
            t.add_row(r.id, r.citation, r.title, r.role)
        console.print(t)
    if c.dates:
        console.print("[bold]When[/bold]")
        for d, text in c.dates:
            console.print(f"  {d}  {text}")
    for w in c.warnings:
        console.print(f"[yellow]note:[/yellow] {w}")


@act_app.command("checklist")
def checklist_cmd(
    profile: Annotated[Path, typer.Argument(help="System profile YAML")],
    file: Annotated[Path, typer.Option(help="Checklist file (created, then kept in sync)")] = DEFAULT_CHECKLIST,
    scan: Annotated[Path | None, typer.Option(help="Run the Article 50 code scanner on this path and attach the result")] = None,
    check: Annotated[bool, typer.Option(help="Exit 1 if the checklist is inconsistent (see --fail-on)")] = False,
    fail_on: Annotated[str, typer.Option(help="inconsistent (default) or open")] = "inconsistent",
) -> None:
    """Create or sync the conformity checklist, merging recorded progress by item id."""
    if fail_on not in ("inconsistent", "open"):
        console.print("[red]--fail-on must be 'inconsistent' or 'open'[/red]")
        raise typer.Exit(2)
    _, c = _load(profile)
    existing = cl.load(file) if file.exists() else None
    checklist = cl.build(c, existing)
    if scan is not None:
        cl.apply_scan(checklist, scan_path(scan))
    cl.save(checklist, file)

    t = Table(title=f"{c.system} ({c.tier.replace('_', ' ')})")
    for col in ("id", "citation", "requirement", "status", "evidence", "scan"):
        t.add_column(col, overflow="fold")
    style = {"done": "green", "not_applicable": "dim", "in_progress": "yellow", "todo": "red"}
    for it in checklist.items:
        t.add_row(it.id, it.citation, it.title, f"[{style[it.status]}]{it.status}[/{style[it.status]}]", it.evidence, it.scan)
    console.print(t)
    done, total = checklist.progress
    console.print(f"{done}/{total} applicable items done. Saved to {file}")
    if checklist.dropped:
        console.print(f"[yellow]no longer applicable after the profile change (removed): {', '.join(checklist.dropped)}[/yellow]")
    issues = cl.problems(checklist, fail_on)
    for i in issues:
        console.print(f"[red]problem:[/red] {i}")
    if check and issues:
        raise typer.Exit(1)


@act_app.command()
def mark(
    item: Annotated[str, typer.Argument(help="Item id, e.g. art9")],
    status: Annotated[str, typer.Argument(help="todo | in_progress | done | not_applicable")],
    file: Annotated[Path, typer.Option(help="Checklist file")] = DEFAULT_CHECKLIST,
    evidence: Annotated[str, typer.Option(help="Link or path proving it (required for done)")] = "",
    notes: Annotated[str, typer.Option(help="Free-text note")] = "",
) -> None:
    """Record progress on one checklist item."""
    if status not in cl.STATUSES:
        console.print(f"[red]status must be one of {cl.STATUSES}[/red]")
        raise typer.Exit(2)
    if not file.exists():
        console.print(f"[red]{file} not found; run `manifest act checklist` first[/red]")
        raise typer.Exit(2)
    checklist = cl.load(file)
    try:
        it = checklist.get(item)
    except KeyError as exc:
        console.print(f"[red]{exc.args[0]}; known ids: {', '.join(i.id for i in checklist.items)}[/red]")
        raise typer.Exit(2) from exc
    if status == "done" and not (evidence or it.evidence).strip():
        console.print("[red]refusing to mark done without --evidence[/red]")
        raise typer.Exit(2)
    it.status = status
    if evidence:
        it.evidence = evidence
    if notes:
        it.notes = notes
    cl.save(checklist, file)
    console.print(f"{it.id}: {status}")


@act_app.command("docs")
def docs_cmd(
    profile: Annotated[Path, typer.Argument(help="System profile YAML")],
    out: Annotated[Path, typer.Option(help="Where to write the Markdown")] = Path("technical-documentation.md"),
    scan: Annotated[Path | None, typer.Option(help="Include an Article 50 scan summary")] = None,
    checklist_file: Annotated[Path | None, typer.Option("--checklist", help="Link sections to checklist items")] = None,
    check: Annotated[bool, typer.Option(help="Exit 1 if Annex IV sections are unanswered in the profile")] = False,
    check_file: Annotated[Path | None, typer.Option(help="Instead: exit 1 if this edited Markdown still has TODO markers")] = None,
) -> None:
    """Generate the Annex IV technical-documentation scaffold and report completeness."""
    if check_file is not None:
        n = docs.count_todos(check_file.read_text(encoding="utf-8"))
        console.print(f"{n} TODO marker(s) in {check_file}")
        raise typer.Exit(1 if n else 0)
    p, c = _load(profile)
    findings = scan_path(scan) if scan is not None else None
    checklist = cl.load(checklist_file) if checklist_file and checklist_file.exists() else None
    md, comp = docs.render(p, c, checklist, findings, today=date.today().isoformat())
    out.write_text(md, encoding="utf-8")
    console.print(f"wrote {out}")
    if comp is None:
        console.print(f"classified {c.tier.replace('_', ' ')}: " + (
            "wrote the Article 6(4) record template" if c.tier == "not_high_risk_documented"
            else "Annex IV documentation is not required for this tier"))
        return
    console.print(f"Annex IV completeness: {comp.filled}/{comp.total} ({comp.percent:.0f}%)")
    if comp.missing:
        console.print("unanswered: " + ", ".join(comp.missing))
    if check and not comp.complete:
        raise typer.Exit(1)


@act_app.command()
def timeline() -> None:
    """Application dates, with their source and the caveat that goes with them."""
    t = Table(title="EU AI Act application dates")
    for col in ("date", "what applies", "source"):
        t.add_column(col, overflow="fold")
    for d, text, src in data.TIMELINE:
        t.add_row(d, text, src)
    console.print(t)
    console.print(f"[yellow]{data.TIMELINE_NOTE}[/yellow]")
