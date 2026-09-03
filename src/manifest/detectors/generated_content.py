"""Article 50(2)/50(4) detector: finds calls to known image/audio/video generation APIs
and checks whether anything resembling a watermarking/labeling step appears nearby in the
same function. Same two-signal gating as chatbot_disclosure.py (known SDK import + known
call shape) to keep false positives down.

Deliberately conservative about what counts as a "labeling step": this can't verify a
C2PA manifest is actually valid or that a watermark survives re-encoding -- it can only
tell you whether the code *attempts* something in that direction. See README.
"""

import ast
from pathlib import Path

from manifest.article50 import GENERATED_CONTENT_MARKING
from manifest.detectors.base import Confidence, Finding
from manifest.detectors.chatbot_disclosure import _FuncScopeVisitor, _dotted_name

_GENERATIVE_SDK_IMPORTS = {"openai", "elevenlabs", "replicate", "runwayml", "stability_sdk"}

_GENERATIVE_CALL_SUFFIXES = (
    "images.generate",       # openai DALL-E
    "image.create",
    "audio.speech.create",   # openai TTS
    "run",                   # replicate.run(...) -- fuzzy, gated by import check below
)

_LABELING_MARKERS = (
    "c2pa", "content_credentials", "watermark", "manifest.embed",
    "piexif", "exif", "metadata", "provenance", "ai-generated", "ai generated",
    "artificially generated",
)


def _imports_generative_sdk(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] in _GENERATIVE_SDK_IMPORTS for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in _GENERATIVE_SDK_IMPORTS:
                return True
    return False


def _is_generative_call(call: ast.Call) -> bool:
    dotted = _dotted_name(call.func).lower()
    return any(dotted.endswith(suffix) for suffix in _GENERATIVE_CALL_SUFFIXES)


def scan_file(path: Path) -> list[Finding]:
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    if not _imports_generative_sdk(tree):
        return []

    source_lines = source.splitlines()
    visitor = _FuncScopeVisitor()
    visitor.visit(tree)

    findings: list[Finding] = []
    for func, calls in visitor.calls_by_func.items():
        gen_calls = [c for c in calls if _is_generative_call(c)]
        if not gen_calls:
            continue

        # Check both string literals and plain source text of the function body for
        # labeling markers -- a watermark call is often a bare function call with no
        # string literal at all (e.g. embed_watermark(image)), so literals-only misses it.
        func_source = "\n".join(
            source_lines[func.lineno - 1 : (func.end_lineno or func.lineno)]
        ).lower()
        has_labeling = any(marker in func_source for marker in _LABELING_MARKERS)

        call = gen_calls[0]
        snippet = source_lines[call.lineno - 1].strip() if 0 < call.lineno <= len(source_lines) else ""
        findings.append(
            Finding(
                file=str(path),
                line=call.lineno,
                provision=GENERATED_CONTENT_MARKING,
                confidence=Confidence.needs_review if has_labeling else Confidence.likely_violation,
                detail=(
                    f"'{func.name}' calls {_dotted_name(call.func)}, a generative-content API. "
                    + ("A labeling/watermarking-related term was found in this function -- verify it actually marks the output as machine-detectable AI-generated."
                       if has_labeling else
                       "No watermarking/labeling/metadata step found anywhere in this function.")
                ),
                snippet=snippet,
            )
        )
    return findings
