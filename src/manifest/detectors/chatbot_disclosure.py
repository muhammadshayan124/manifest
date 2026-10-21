"""Article 50(1) detector: finds LLM calls wired into what looks like a user-facing
interface, and checks whether AI-disclosure language appears in the same function.

Two things must hold to flag anything, to keep false positives down:

1. The file imports a known LLM SDK or agent framework, AND a call matches a known
   chat-completion shape (raw SDK call, LiteLLM, a tracked LangChain `Chat*` model, or a
   tracked agent object from an agent framework).
2. The enclosing function looks user-facing: a web/bot route decorator, or a name whose
   *tokens* include chat/bot/assistant/etc. A bare LLM call in a batch job with neither
   signal is not flagged. That is a deliberate false-negative trade, because Article 50(1)
   only applies to systems that interact directly with natural persons.

A private helper (`_name`) that matches only on its name, with no route decorator, is
reported as `low_signal` and hidden by default: on real framework code those were nearly
all internal adapters, not interfaces a person talks to.

Suppress a finding on purpose with `# manifest: ignore` on the call line or the `def` line.
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from manifest.article50 import CHATBOT_DISCLOSURE
from manifest.detectors._ast import (
    HTTP_CLIENT_MODULES,
    FuncScopeVisitor,
    decorator_names,
    dotted_name,
    http_target_text,
    imported_modules,
    imports_any,
    is_suppressed,
    local_strings,
    name_tokens,
    tracked_receivers,
)
from manifest.detectors.base import Confidence, Finding

_SDK_MODULES = (
    "openai", "anthropic", "google.generativeai", "google.genai", "vertexai", "litellm",
    "ollama", "mistralai", "cohere", "groq", "together", "instructor", "boto3",
    "langchain", "langchain_core", "langchain_openai", "langchain_anthropic",
    "langchain_community", "langchain_google_genai", "langchain_mistralai",
    "langchain_ollama", "langchain_aws", "langgraph", "agno", "crewai", "autogen",
    "autogen_agentchat", "pydantic_ai", "smolagents", "llama_index",
)
_AGENT_FRAMEWORKS = (
    "agno", "crewai", "autogen", "autogen_agentchat", "pydantic_ai", "smolagents", "langgraph", "langchain",
)

# Matched as a dotted-name suffix on a '.' boundary, so `client.chat.completions.create`
# and `chat.completions.create` match but `self.generate_content_cache` does not.
_CHAT_CALL_SUFFIXES = (
    "chat.completions.create", "chat.completions.parse", "chat.completions.stream",
    "chatcompletion.create",
    "responses.create", "responses.parse", "responses.stream",
    "messages.create", "messages.stream",
    "generate_content", "generate_content_async", "generate_content_stream",
    "chat.complete", "chat.stream",
)
_EXACT_CALLS = {"litellm.completion", "litellm.acompletion", "ollama.chat"}

# Production code often skips the SDK and POSTs to the provider directly (found in a real
# treasury app calling api.anthropic.com via `requests`, and in open-webui). A chat call is
# identified by its *path*, never by the host alone: matching on `api.openai.com` or
# `api.mistral.ai` also matched image generation and audio transcription, which are
# different obligations (or none).
_CHAT_ENDPOINT_PATHS = (
    "/chat/completions", "/v1/messages", "/v1/responses", ":generatecontent",
    ":streamgeneratecontent", "/api/chat",
)

_CHAT_MODEL_CTOR = re.compile(
    r"^(Azure)?Chat[A-Z][A-Za-z0-9]*$|^(init|load|get|create|make|build)_?(chat_?)?(model|llm)$", re.IGNORECASE
)
_CHAT_MODEL_METHODS = {"invoke", "ainvoke", "stream", "astream", "batch", "abatch"}
_RUNNABLE_DERIVATIONS = frozenset(
    {"bind_tools", "bind", "with_structured_output", "with_config", "with_retry", "with_fallbacks"}
)
# Convention-based fallback for a model that arrives as a parameter or is built by code the
# scanner cannot see: `.invoke`/`.ainvoke` on a receiver whose name ends like one of these,
# in a file that imports LangChain, is almost always a Runnable doing model work.
_RUNNABLE_RECEIVER_SUFFIXES = ("llm", "model", "chain", "agent", "graph")
# LlamaIndex exposes chat through methods on an `llm` / `*_engine` object.
_LLAMAINDEX_METHODS = {
    "chat", "achat", "stream_chat", "astream_chat", "chat_with_tools", "astream_chat_with_tools",
    "complete", "acomplete", "stream_complete", "astream_complete",
}
_LLAMAINDEX_RECEIVER_SUFFIXES = ("llm", "engine")
# Streamlit/Gradio chat apps are module-level scripts; these calls are the user-facing signal.
_UI_CHAT_SIGNAL_SUFFIXES = ("chat_input", "chat_message", "chatinterface", "chatbot")
_UI_MODULES = ("streamlit", "gradio")
# App-level wrappers named after the OpenAI call they hide, e.g. gpt-researcher's
# `create_chat_completion(...)`.
_CHAT_WRAPPER_NAME = re.compile(r"^(a?create|a?get)_chat_(completion|response)s?(_with_tools)?$")

_AGENT_CTORS = {
    "Agent", "Team", "Crew", "AssistantAgent", "create_react_agent", "create_agent",
    "initialize_agent", "AgentExecutor", "create_tool_calling_agent", "create_openai_tools_agent",
    "create_openai_functions_agent", "create_structured_chat_agent",
}
_AGENT_METHODS = {
    "run", "arun", "print_response", "aprint_response", "kickoff", "kickoff_async",
    "run_sync", "run_stream", "invoke", "ainvoke", "stream", "astream",
}

_USER_FACING_TOKENS = {
    "chat", "chats", "chatbot", "chatting", "bot", "assistant", "conversation",
    "converse", "copilot",
}
# Tokens that say a function exists to probe, measure or analyse rather than to talk to a
# person. Found by reading false positives on real code: `health_services_endpoint`,
# `track_conversation_topics`, `*_conversation_compare_*`, `_run_test_chat_completion`.
_NON_INTERACTIVE_TOKENS = {
    "health", "healthcheck", "readiness", "liveness", "ping", "probe", "test", "tests",
    "mock", "benchmark", "compare", "comparison", "simulate", "simulation", "eval",
    "evaluate", "evaluation", "track", "tracker", "analyze", "analyzer", "classify",
    "summarize", "summarise", "summary", "token", "tokens", "counter", "count",
    # Model calls that exist to transform media or text for indexing, not to converse.
    "transcribe", "transcription", "transcribing", "embed", "embedding", "embeddings",
    "ocr", "tts", "stt", "speech", "audio", "rerank", "reranker",
}
_ROUTE_DECORATORS = {
    "route", "get", "post", "put", "patch", "delete", "websocket", "api_route",
    "message_handler", "callback_query_handler", "on_message", "command", "event",
    "message", "action", "slash_command",
}
# A bare `@get`/`@post` is a Litestar-style route, but a bare `@patch` is almost always
# `unittest.mock.patch`; the HTTP verb only counts as a route on an object (`@app.patch`).
_BARE_ROUTE_DECORATORS = {"get", "post", "put", "delete", "route", "websocket"}
_NOT_ROUTE_RECEIVERS = {"mock", "unittest", "pytest", "functools", "contextlib"}


def _is_route_decorator(dotted: str) -> bool:
    *receiver, final = dotted.split(".")
    if _NOT_ROUTE_RECEIVERS.intersection(receiver):
        return False
    return final in (_ROUTE_DECORATORS if receiver else _BARE_ROUTE_DECORATORS)


def _has_route(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_is_route_decorator(d) for d in decorator_names(func))

_DISCLOSURE_PHRASES = (
    "ai assistant", "artificial intelligence", "chatbot", "chat bot",
    "you are chatting with", "you're chatting with", "you are talking to",
    "automated assistant", "automated system", "virtual assistant",
    "ai-powered", "powered by ai", "this is an ai", "talking to an ai",
    "generated by ai", "not a human", "an ai, not a human", "ai chat",
)


def _imports_llm_sdk(tree: ast.Module) -> bool:
    return imports_any(imported_modules(tree), _SDK_MODULES)


def _is_raw_llm_http_call(call: ast.Call, names: dict[str, str]) -> bool:
    """`requests.post("https://api.anthropic.com/v1/messages", ...)`-style calls, with the
    URL either inline or held in a variable assigned earlier in the same function."""
    text = http_target_text(call, names)
    return any(path in text for path in _CHAT_ENDPOINT_PATHS) or ("cohere" in text and "/chat" in text)


def _is_chat_call(
    call: ast.Call,
    modules: set[str],
    chat_models: set[str],
    agents: set[str],
    names: dict[str, str] | None = None,
) -> bool:
    dotted = dotted_name(call.func)
    low = dotted.lower()
    if _is_raw_llm_http_call(call, names or {}):
        return True
    if low in _EXACT_CALLS:
        return True
    if any(low == s or low.endswith("." + s) for s in _CHAT_CALL_SUFFIXES):
        return True
    if "boto3" in modules and low.endswith((".converse", ".converse_stream")):
        return not low.startswith(("self.", "cls."))
    receiver, _, method = dotted.rpartition(".")
    if _CHAT_WRAPPER_NAME.match(method):
        return True
    if (
        method in _LLAMAINDEX_METHODS
        and "llama_index" in " ".join(modules)
        and receiver.rpartition(".")[2].lower().endswith(_LLAMAINDEX_RECEIVER_SUFFIXES)
    ):
        return True
    if method in _CHAT_MODEL_METHODS and (
        receiver in chat_models
        or (
            any(m.startswith("langchain") or m == "langgraph" for m in modules)
            and receiver.rpartition(".")[2].lower().endswith(_RUNNABLE_RECEIVER_SUFFIXES)
        )
    ):
        return True
    return method in _AGENT_METHODS and receiver in agents


def _facing_tier(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """'public' if a route decorator or a public name signals a user-facing interface;
    'private' if only a leading-underscore helper's name does; 'probe' if the name says it
    exists to test/measure/analyse; None if nothing suggests an interface."""
    tokens = set(name_tokens(func.name))
    has_route = _has_route(func)
    if not has_route and _CHAT_WRAPPER_NAME.match(func.name):
        return None  # `create_chat_completion` *is* the LLM wrapper layer, not an interface
    has_name_signal = bool(tokens & _USER_FACING_TOKENS)
    if not (has_route or has_name_signal):
        return None  # no interface signal at all: never report, whatever the name says
    if tokens & _NON_INTERACTIVE_TOKENS:
        return "probe"
    if has_route:
        return "public"
    return "private" if func.name.startswith("_") else "public"


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    consts: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    consts[target.id] = node.value.value
    return consts


def _function_text(func: ast.AST, visitor: FuncScopeVisitor, consts: dict[str, str]) -> str:
    """The function's string literals plus any module-level string constants it reads, so a
    disclosure defined once as `WELCOME = "You are chatting with an AI"` still counts."""
    parts = list(visitor.literals_by_func.get(func, []))
    parts.extend(
        consts[n.id] for n in ast.walk(func) if isinstance(n, ast.Name) and n.id in consts
    )
    return " ".join(parts).lower()


@dataclass
class FuncFacts:
    """Everything the direct and the call-graph passes need to know about one function."""

    file: str
    name: str
    qualname: str
    lineno: int
    decorator_linenos: list[int]
    has_route: bool
    tier: str | None
    chat_call: ast.Call | None
    callees: frozenset[str]
    text: str
    suppressed: bool
    call_snippet: str
    def_snippet: str
    imported: frozenset[str] = frozenset()


def _qualnames(tree: ast.Module) -> dict[ast.AST, str]:
    names: dict[ast.AST, str] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = f"{prefix}{child.name}"
                names[child] = qual
                visit(child, qual + ".")
            else:
                visit(child, prefix)

    visit(tree, "")
    return names


def _callee_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def analyze_file(path: Path) -> list[FuncFacts]:
    """One FuncFacts per function. Callee names are collected for every file, SDK import or
    not, because a route handler usually lives in a file that never touches an SDK."""
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    modules = imported_modules(tree)
    # An HTTP-client import is enough to look for raw provider calls; an SDK import enables
    # the SDK call shapes. Receiver tracking below only matters for SDK files.
    sdk_file = imports_any(modules, _SDK_MODULES) or imports_any(modules, HTTP_CLIENT_MODULES)
    chat_models = (
        tracked_receivers(tree, lambda c: bool(_CHAT_MODEL_CTOR.match(c)), _RUNNABLE_DERIVATIONS)
        if sdk_file
        else set()
    )
    agents = (
        tracked_receivers(tree, lambda c: c in _AGENT_CTORS, _RUNNABLE_DERIVATIONS)
        if imports_any(modules, _AGENT_FRAMEWORKS)
        else set()
    )

    source_lines = source.splitlines()
    visitor = FuncScopeVisitor()
    visitor.visit(tree)
    consts = _module_string_constants(tree)
    qualnames = _qualnames(tree)
    ui_chat = imports_any(modules, _UI_MODULES) and any(
        dotted_name(c.func).lower().endswith(_UI_CHAT_SIGNAL_SUFFIXES)
        for c in ast.walk(tree)
        if isinstance(c, ast.Call)
    )

    def line(n: int) -> str:
        return source_lines[n - 1].strip() if 0 < n <= len(source_lines) else ""

    facts: list[FuncFacts] = []
    for func, calls in visitor.calls_by_func.items():
        names = local_strings(func, consts)
        chat_calls = (
            [c for c in calls if _is_chat_call(c, modules, chat_models, agents, names)]
            if sdk_file
            else []
        )
        decorator_lines = [d.lineno for d in func.decorator_list]
        first = chat_calls[0] if chat_calls else None
        tier = _facing_tier(func)
        # In a Streamlit/Gradio chat app, any helper that reaches the model serves the chat UI.
        if tier is None and ui_chat and first is not None and not is_probe_name(func.name):
            tier = "public"
        facts.append(
            FuncFacts(
                file=str(path),
                name=func.name,
                qualname=qualnames.get(func, func.name),
                lineno=func.lineno,
                decorator_linenos=decorator_lines,
                has_route=_has_route(func),
                tier=tier,
                chat_call=first,
                callees=frozenset(n for c in calls if (n := _callee_name(c))),
                text=_function_text(func, visitor, consts),
                suppressed=is_suppressed(
                    source_lines, *([first.lineno] if first else []), func.lineno, *decorator_lines
                ),
                call_snippet=line(first.lineno) if first else "",
                def_snippet=line(func.lineno),
                imported=frozenset(modules),
            )
        )

    if ui_chat and sdk_file:
        names = local_strings(tree, consts)
        module_chat = [
            c for c in visitor.module_calls if _is_chat_call(c, modules, chat_models, agents, names)
        ]
        if module_chat:
            first = module_chat[0]
            facts.append(
                FuncFacts(
                    file=str(path),
                    name="<module>",
                    qualname="<module>",
                    lineno=first.lineno,
                    decorator_linenos=[],
                    has_route=False,
                    tier="public",
                    chat_call=first,
                    callees=frozenset(n for c in visitor.module_calls if (n := _callee_name(c))),
                    text=" ".join([*visitor.module_literals, *consts.values()]).lower(),
                    suppressed=is_suppressed(source_lines, first.lineno),
                    call_snippet=line(first.lineno),
                    def_snippet=line(first.lineno),
                    imported=frozenset(modules),
                )
            )
    return facts


def is_probe_name(name: str) -> bool:
    return bool(set(name_tokens(name)) & _NON_INTERACTIVE_TOKENS)


def has_disclosure(text: str) -> bool:
    return any(p in text for p in _DISCLOSURE_PHRASES)


_QUALIFIERS = {
    "private": "is a private helper whose name suggests a chat interface (internal adapter?); "
    "check whether a public entry point exposes it to a person. ",
    "probe": "has a name suggesting a health check, test, benchmark or analysis step rather than "
    "an interface a person talks to. ",
    "public": "looks user-facing (function name/decorator suggests a chat interface). ",
}
_DISCLOSED = (
    "AI-disclosure language was found in this function's strings -- verify it's actually shown "
    "to the user before/at first interaction."
)
_NOT_DISCLOSED = "No AI-disclosure language (e.g. 'AI assistant', 'chatbot') found anywhere in this function."


def direct_findings(facts: list[FuncFacts]) -> list[Finding]:
    findings: list[Finding] = []
    for f in facts:
        if f.chat_call is None or f.tier is None or f.suppressed:
            continue
        disclosed = has_disclosure(f.text)
        if f.tier in ("private", "probe"):
            confidence = Confidence.low_signal
        else:
            confidence = Confidence.needs_review if disclosed else Confidence.likely_violation
        findings.append(
            Finding(
                file=f.file,
                line=f.chat_call.lineno,
                provision=CHATBOT_DISCLOSURE,
                confidence=confidence,
                detail=(
                    f"'{f.name}' calls {dotted_name(f.chat_call.func)} and {_QUALIFIERS[f.tier]}"
                    + (_DISCLOSED if disclosed else _NOT_DISCLOSED)
                ),
                snippet=f.call_snippet,
            )
        )
    return findings


def scan_file(path: Path) -> list[Finding]:
    return direct_findings(analyze_file(path))
