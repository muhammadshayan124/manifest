"""Walks a directory, dispatches each file to the detectors that apply to its extension,
and aggregates findings. No detector logic lives here -- this is just routing, plus
skipping files nobody wrote by hand.

Skipping generated output matters on real repos: scanning litellm flagged minified Next.js
bundles under `_next/static/chunks/` because a bundled file trivially "imports an LLM SDK
and contains a chat-completion-shaped call".
"""

import fnmatch
from collections.abc import Iterator
from pathlib import Path

from manifest.detectors import (
    chatbot_disclosure,
    generated_content,
    js_heuristic,
    reach,
)
from manifest.detectors.base import Confidence, Finding

_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build",
    ".next", "_next", "out", "site-packages", ".tox", ".mypy_cache", ".pytest_cache",
    ".nuxt", ".svelte-kit", "coverage", "vendor", "target",
}
# Code under these directories, or matching these names, is demo/test/benchmark code. A
# pattern match there is not a deployed interface, so it is demoted to `low_signal`
# (hidden by default) rather than dropped: `--include-low-signal` still shows it.
_DEMO_DIRS = {"tests", "test", "__tests__", "examples", "example", "cookbook", "benchmarks", "benchmark", "evals", "docs"}
_DEMO_FILE_PATTERNS = ("test_*.py", "*_test.py", "conftest.py", "*.test.ts", "*.test.tsx", "*.spec.ts", "*.spec.tsx")
_GENERATED_SUFFIXES = (".min.js", ".bundle.js", ".chunk.js", ".d.ts")
_JS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}
_MAX_PY_BYTES = 2_000_000
_MAX_JS_BYTES = 1_500_000
_MINIFIED_LINE_LENGTH = 2000


def is_generated(path: Path) -> bool:
    """Minified/bundled/declaration files and anything too large to be hand-written source."""
    name = path.name.lower()
    if name.endswith(_GENERATED_SUFFIXES):
        return True
    try:
        size = path.stat().st_size
    except OSError:
        return True
    if path.suffix == ".py":
        return size > _MAX_PY_BYTES
    if path.suffix in _JS_EXTENSIONS:
        if size > _MAX_JS_BYTES:
            return True
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return any(len(line) > _MINIFIED_LINE_LENGTH for line in fh.read(200_000).splitlines())
    return False


def is_demo_or_test(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts[:-1] if root.is_dir() else ()
    except ValueError:
        parts = ()
    return bool(_DEMO_DIRS.intersection(p.lower() for p in parts)) or any(
        fnmatch.fnmatch(path.name.lower(), pat) for pat in _DEMO_FILE_PATTERNS
    )


def _demote(findings: list[Finding]) -> list[Finding]:
    for f in findings:
        f.confidence = Confidence.low_signal
        f.detail = "[demo/test/benchmark code] " + f.detail
    return findings


def scan_path(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    paths = [root] if root.is_file() else _walk(root)

    all_facts: list[chatbot_disclosure.FuncFacts] = []
    demo_files: set[str] = set()
    for path in paths:
        demo = is_demo_or_test(path, root)
        if path.suffix == ".py" and not is_generated(path):
            facts = chatbot_disclosure.analyze_file(path)
            all_facts.extend(facts)
            file_findings = chatbot_disclosure.direct_findings(facts) + generated_content.scan_file(path)
        elif path.suffix in _JS_EXTENSIONS and not is_generated(path):
            file_findings = js_heuristic.scan_file(path)
        else:
            continue
        if demo:
            demo_files.add(str(path))
        findings.extend(_demote(file_findings) if demo else file_findings)

    # Handlers in demo/test files are demoted like any other finding in those files.
    for finding in reach.indirect_findings(all_facts):
        findings.extend(_demote([finding]) if finding.file in demo_files else [finding])

    return findings


def _walk(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path
