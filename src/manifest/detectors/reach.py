"""Project-level pass: which route handlers *reach* an LLM call through other functions?

Real applications are almost never `route -> SDK call`. They are `route -> service ->
client wrapper -> SDK call`, so a purely per-function scan reports nothing on the apps it
is most needed for (found by running manifest on three real apps: each had a route and an
LLM call, and none was reported).

How it works, and where it is deliberately approximate:

- Calls are resolved by *simple callee name* (`foo()` and `obj.foo()` both resolve to
  functions named `foo`) across the whole scanned project. There is no import or type
  resolution, so this is a heuristic, not a sound call graph.
- To keep name collisions from fabricating paths, a callee name only counts if it is
  defined by at most `MAX_DEFINITIONS` functions in the project. `run` or `get`, defined
  everywhere, is ignored rather than guessed at. A name defined more often than that is
  resolved only among definitions in modules the *calling file imports* (or its own file),
  and only if that narrows it to `MAX_DEFINITIONS` or fewer.
- Handlers that reach the same LLM call are reported once, listing the others, so an app
  with twenty endpoints in front of one `generate_chat_completion` yields one finding.
- Only route-decorated handlers become findings. They are the one strong, structural sign
  of an interface a person reaches; reporting every function that happens to reach an LLM
  would flood the output with internals.
- Search depth is capped at `MAX_DEPTH` hops.

Each finding names the full chain so a reviewer can verify or reject it in seconds.
"""

from collections import defaultdict

from manifest.article50 import CHATBOT_DISCLOSURE
from manifest.detectors._ast import dotted_name, name_tokens
from manifest.detectors.base import Confidence, Finding
from manifest.detectors.chatbot_disclosure import (
    FuncFacts,
    has_disclosure,
    is_probe_name,
)

MAX_DEPTH = 4
MAX_DEFINITIONS = 3
_CONVERSATIONAL = {"chat", "chats", "bot", "assistant", "conversation", "converse", "copilot", "message", "messages"}


def _imports_file(imported: frozenset[str], file: str) -> bool:
    """True if one of the imported dotted modules names this file (suffix match on the path)."""
    posix = file.replace(chr(92), "/")
    if posix.endswith("/__init__.py"):
        stem = posix[: -len("/__init__.py")]
    else:
        stem = posix.removesuffix(".py")
    return any(stem == m.replace(".", "/") or stem.endswith("/" + m.replace(".", "/")) for m in imported)


def _candidates(caller: FuncFacts, defs: list[FuncFacts]) -> list[FuncFacts]:
    if len(defs) <= MAX_DEFINITIONS:
        return defs
    visible = [d for d in defs if d.file == caller.file or _imports_file(caller.imported, d.file)]
    return visible if 0 < len(visible) <= MAX_DEFINITIONS else []


def _reaching_paths(facts: list[FuncFacts]) -> dict[int, list[FuncFacts]]:
    """id(function) -> chain from that function down to one that calls an LLM directly."""
    by_name: dict[str, list[FuncFacts]] = defaultdict(list)
    for f in facts:
        by_name[f.name].append(f)

    reaching: dict[int, list[FuncFacts]] = {id(f): [f] for f in facts if f.chat_call is not None}
    for _ in range(MAX_DEPTH):
        grew = False
        for f in facts:
            if id(f) in reaching:
                continue
            for callee in sorted(f.callees):
                if callee.startswith("__"):
                    continue
                defs = _candidates(f, by_name.get(callee, []))
                target = next((d for d in defs if d is not f and id(d) in reaching), None)
                if target is not None:
                    reaching[id(f)] = [f, *reaching[id(target)]]
                    grew = True
                    break
        if not grew:
            break
    return reaching


def _is_conversational(name: str) -> bool:
    return bool(set(name_tokens(name)) & _CONVERSATIONAL)


def indirect_findings(facts: list[FuncFacts]) -> list[Finding]:
    reaching = _reaching_paths(facts)
    entries: list[tuple[FuncFacts, list[FuncFacts]]] = [
        (f, path)
        for f in facts
        if (path := reaching.get(id(f))) is not None
        and len(path) >= 2
        and f.has_route
        and not f.suppressed
    ]

    groups: dict[tuple[str, int], list[tuple[FuncFacts, list[FuncFacts]]]] = defaultdict(list)
    for entry, path in entries:
        terminal = path[-1]
        line = terminal.chat_call.lineno if terminal.chat_call else 0
        groups[(terminal.file, line)].append((entry, path))

    findings: list[Finding] = []
    for members in groups.values():
        # The handler that is most obviously a conversation represents the group.
        members.sort(key=lambda m: (not _is_conversational(m[0].name), m[0].file, m[0].lineno))
        f, path = members[0]
        others = [m[0] for m in members[1:]]

        terminal = path[-1]
        chain = " -> ".join(p.qualname for p in path)
        sdk_call = dotted_name(terminal.chat_call.func) if terminal.chat_call else "an LLM call"
        terminal_file = terminal.file.replace(chr(92), "/").rsplit("/", 1)[-1]
        where = f"{terminal_file}:{terminal.chat_call.lineno if terminal.chat_call else '?'}"
        # A disclosure counts if it appears anywhere along the chain: the handler may
        # return it, or the service layer may prepend it.
        disclosed = any(has_disclosure(p.text) for p in path)

        # A health/test/benchmark/transcription name anywhere on the chain means the path
        # exists to probe, measure or transform, not to converse with a person.
        if f.tier == "probe" or any(is_probe_name(p.name) for p in path):
            confidence = Confidence.low_signal
        else:
            confidence = Confidence.needs_review if disclosed else Confidence.likely_violation

        also = ""
        if others:
            shown = ", ".join(o.name for o in others[:5])
            more = f" and {len(others) - 5} more" if len(others) > 5 else ""
            also = f" {len(others)} other route handler(s) reach the same call: {shown}{more}."

        findings.append(
            Finding(
                file=f.file,
                line=f.lineno,
                provision=CHATBOT_DISCLOSURE,
                confidence=confidence,
                detail=(
                    f"Route handler '{f.name}' reaches an LLM call: {chain} ({sdk_call} in {where}).{also} "
                    "Resolved by function name across the project (heuristic) -- verify the chain. "
                    + (
                        "AI-disclosure language was found along this chain -- verify it's actually shown to the user before/at first interaction."
                        if disclosed
                        else "No AI-disclosure language (e.g. 'AI assistant', 'chatbot') found anywhere along this chain."
                    )
                ),
                snippet=f.def_snippet,
            )
        )
    return findings
