"""Walks a directory, dispatches each file to the detectors that apply to its extension,
and aggregates findings. No detector logic lives here -- this is just routing.
"""

from pathlib import Path

from manifest.detectors import chatbot_disclosure, generated_content, js_heuristic
from manifest.detectors.base import Finding

_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"}


def scan_path(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    paths = [root] if root.is_file() else _walk(root)

    for path in paths:
        if path.suffix == ".py":
            findings.extend(chatbot_disclosure.scan_file(path))
            findings.extend(generated_content.scan_file(path))
        elif path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            findings.extend(js_heuristic.scan_file(path))

    return findings


def _walk(root: Path):
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        yield path
