"""Article 50(2)/50(4) detector: finds calls to known image/audio/video generation APIs
and checks whether anything resembling a watermarking/labeling step appears in the same
function. Same two-signal gating as chatbot_disclosure.py (known SDK import + known call
shape) to keep false positives down.

Deliberately conservative about what counts as a "labeling step": this can't verify a
C2PA manifest is valid or that a watermark survives re-encoding. It can only tell you
whether the code *attempts* something in that direction. See README.

Call shapes are matched on dotted-name boundaries or against a tracked client object,
never as a bare `run`/`generate` suffix: an earlier version matched `.run` loosely and
flagged `asyncio.run(...)` in a CLI entry point on real code.

Suppress a finding on purpose with `# manifest: ignore` on the call line or the `def` line.
"""

import ast
from pathlib import Path

from manifest.article50 import GENERATED_CONTENT_MARKING
from manifest.detectors._ast import (
    HTTP_CLIENT_MODULES,
    FuncScopeVisitor,
    dotted_name,
    http_target_text,
    imported_modules,
    imports_any,
    is_suppressed,
    local_strings,
    tracked_receivers,
)
from manifest.detectors.base import Confidence, Finding

_GENERATIVE_SDK_MODULES = (
    "openai", "elevenlabs", "replicate", "runwayml", "stability_sdk", "fal_client",
    "google.genai", "vertexai",
)

_GENERATIVE_CALL_SUFFIXES = (
    "images.generate", "images.edit", "images.create_variation", "image.create",  # openai
    "audio.speech.create",                                                         # openai TTS
    "text_to_speech.convert", "text_to_speech.convert_as_stream",                  # elevenlabs
    "models.generate_images", "models.generate_videos",                            # google genai
    "videos.create",
)
_EXACT_CALLS = {
    "replicate.run", "replicate.async_run", "replicate.stream",
    "fal_client.run", "fal_client.subscribe", "fal_client.submit",
}
# Raw HTTP to a generation endpoint, found by path (open-webui calls /images/generations
# through aiohttp with no SDK involved).
_GENERATION_PATHS = ("/images/generations", "/images/edits", "/audio/speech", "/text-to-speech", "/v1/video")
_REPLICATE_CLIENT_METHODS = {"run", "async_run", "stream"}

# `metadata` and bare `exif` are deliberately absent: `metadata` appears in nearly every
# function and made almost anything look labeled; `exif` is kept only via 'piexif'.
_LABELING_MARKERS = (
    "c2pa", "content_credentials", "contentcredentials", "watermark", "synthid",
    "manifest.embed", "piexif", "iptc", "xmp", "provenance", "ai-generated",
    "ai generated", "artificially generated",
)


def _is_generative_call(call: ast.Call, replicate_clients: set[str], names: dict[str, str] | None = None) -> bool:
    dotted = dotted_name(call.func)
    low = dotted.lower()
    if low in _EXACT_CALLS:
        return True
    target = http_target_text(call, names or {})
    if target and any(path in target for path in _GENERATION_PATHS):
        return True
    if any(low == s or low.endswith("." + s) for s in _GENERATIVE_CALL_SUFFIXES):
        return True
    receiver, _, method = dotted.rpartition(".")
    return method in _REPLICATE_CLIENT_METHODS and receiver in replicate_clients


def scan_file(path: Path) -> list[Finding]:
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    modules = imported_modules(tree)
    if not (imports_any(modules, _GENERATIVE_SDK_MODULES) or imports_any(modules, HTTP_CLIENT_MODULES)):
        return []

    replicate_clients = tracked_receivers(tree, lambda c: c == "Client") if imports_any(modules, ("replicate",)) else set()

    source_lines = source.splitlines()
    visitor = FuncScopeVisitor()
    visitor.visit(tree)

    findings: list[Finding] = []
    for func, calls in visitor.calls_by_func.items():
        names = local_strings(func, {})
        gen_calls = [c for c in calls if _is_generative_call(c, replicate_clients, names)]
        if not gen_calls:
            continue

        call = gen_calls[0]
        decorator_lines = [d.lineno for d in func.decorator_list]
        if is_suppressed(source_lines, call.lineno, func.lineno, *decorator_lines):
            continue

        # Check plain source text of the function body, not only string literals: a
        # watermark call is often a bare function call with no literal at all
        # (e.g. embed_watermark(image)).
        func_source = "\n".join(source_lines[func.lineno - 1 : (func.end_lineno or func.lineno)]).lower()
        has_labeling = any(marker in func_source for marker in _LABELING_MARKERS)

        snippet = source_lines[call.lineno - 1].strip() if 0 < call.lineno <= len(source_lines) else ""
        findings.append(
            Finding(
                file=str(path),
                line=call.lineno,
                provision=GENERATED_CONTENT_MARKING,
                confidence=Confidence.needs_review if has_labeling else Confidence.likely_violation,
                detail=(
                    f"'{func.name}' calls {dotted_name(call.func)}, a generative-content API. "
                    + (
                        "A labeling/watermarking-related term was found in this function -- verify it actually marks the output as machine-detectable AI-generated."
                        if has_labeling
                        else "No watermarking/labeling/provenance step found anywhere in this function."
                    )
                ),
                snippet=snippet,
            )
        )
    return findings
