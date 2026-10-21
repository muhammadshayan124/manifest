"""Shared AST helpers for the Python detectors.

Everything here exists because an earlier, cruder version produced false positives on real
code (scanning agno, crewAI and litellm). In particular:

- decorators are matched by their real attribute name, never by substring-searching
  `ast.dump(...)`: the substring "get" matches `@budget(...)`, "target", "widget" and so on.
- function names are tokenised, so `both_sides` and `robot_arm` do not match "bot".
- receivers are tracked by *assignment* (`llm = ChatOpenAI(...)`, `self.llm = ...`) so that
  `llm.invoke(...)` can be recognised without matching every `.invoke` in the world.
"""

import ast
import re
from collections import defaultdict
from collections.abc import Callable, Iterable

SUPPRESSION_MARKER = "manifest: ignore"


def dotted_name(node: ast.AST) -> str:
    """Reconstruct 'client.chat.completions.create' from a Call node's func attribute chain."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


class FuncScopeVisitor(ast.NodeVisitor):
    """Collects calls and string literals per enclosing function (ast has no parent
    pointers, so a stack of the current function(s) does the job). Calls at module level
    are intentionally not collected: scripts and demos that call a model at import time
    are not deployed user-facing interfaces.
    """

    def __init__(self) -> None:
        self.func_stack: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self.calls_by_func: dict[ast.AST, list[ast.Call]] = defaultdict(list)
        self.literals_by_func: dict[ast.AST, list[str]] = defaultdict(list)
        # Calls and strings outside any function. Normally ignored (a script that calls a
        # model at import time is not a deployed interface), but a Streamlit/Gradio app *is*
        # a module-level script, so the chat detector needs them when a UI signal is present.
        self.module_calls: list[ast.Call] = []
        self.module_literals: list[str] = []

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Register every function, even one that makes no calls: the project-level pass
        # counts how many places define a name, and a call-free `def run` still counts.
        self.calls_by_func.setdefault(node, [])
        # Decorators, default values and annotations are evaluated in the *enclosing* scope,
        # so `@router.post("/v1/messages")` must not count as a call made by the handler it
        # decorates (it was being read as an HTTP POST to a provider endpoint).
        for decorator in node.decorator_list:
            self.visit(decorator)
        self.visit(node.args)
        if node.returns is not None:
            self.visit(node.returns)
        self.func_stack.append(node)
        for statement in node.body:
            self.visit(statement)
        self.func_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)

    def visit_Call(self, node: ast.Call) -> None:
        if self.func_stack:
            self.calls_by_func[self.func_stack[-1]].append(node)
        else:
            self.module_calls.append(node)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            if self.func_stack:
                self.literals_by_func[self.func_stack[-1]].append(node.value)
            else:
                self.module_literals.append(node.value)


def imported_modules(tree: ast.Module) -> set[str]:
    """Every dotted module path imported anywhere in the file ('openai', 'google.genai', ...).

    `from google import genai` records both 'google' and 'google.genai': the second form is
    what actually identifies the SDK, and missing it hid the current Gemini client entirely.
    """
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def imports_any(modules: Iterable[str], prefixes: Iterable[str]) -> bool:
    """True if any imported module equals, or is a submodule of, one of `prefixes`."""
    prefix_list = tuple(prefixes)
    return any(m == p or m.startswith(p + ".") for m in modules for p in prefix_list)


def tracked_receivers(
    tree: ast.Module,
    is_constructor: Callable[[str], bool],
    derivations: frozenset[str] = frozenset(),
) -> set[str]:
    """Dotted names assigned from a call whose callable's final segment satisfies
    `is_constructor`: `llm = ChatOpenAI()` -> {"llm"}, `self.llm = ChatOpenAI()` -> {"self.llm"}.

    The set is then closed under three kinds of re-binding, because real code rarely calls
    the object it constructed: plain aliases (`self.llm = llm`), pipelines
    (`chain = prompt | llm`), and derivations (`llm.with_structured_output(...)`, any method
    named in `derivations`). Flow-insensitive on purpose: it only has to beat matching every
    `.invoke` call, and a rebinding that defeats it just produces a missed finding.
    """
    assignments: list[tuple[list[ast.expr], ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            assignments.append((node.targets, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            assignments.append(([node.target], node.value))

    def targets_of(targets: list[ast.expr]) -> set[str]:
        return {name for t in targets if (name := dotted_name(t))}

    def mentions_tracked(value: ast.expr, tracked: set[str]) -> bool:
        if isinstance(value, (ast.Name, ast.Attribute)):
            return dotted_name(value) in tracked
        if isinstance(value, ast.BinOp) and isinstance(value.op, ast.BitOr):
            return mentions_tracked(value.left, tracked) or mentions_tracked(value.right, tracked)
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
            return value.func.attr in derivations and dotted_name(value.func.value) in tracked
        return False

    receivers: set[str] = set()
    for targets, value in assignments:
        if isinstance(value, ast.Call):
            constructor = dotted_name(value.func).rsplit(".", 1)[-1]
            if constructor and is_constructor(constructor):
                receivers |= targets_of(targets)

    while True:
        grew = {
            name
            for targets, value in assignments
            if mentions_tracked(value, receivers)
            for name in targets_of(targets)
        } - receivers
        if not grew:
            return receivers
        receivers |= grew


def decorator_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Lower-cased dotted name of each decorator, call arguments dropped:
    `@app.get("/x")` -> {"app.get"}, `@patch("a")` -> {"patch"}."""
    names: set[str] = set()
    for dec in func.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = dotted_name(target).lower()
        if name:
            names.add(name)
    return names


_TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")


def name_tokens(name: str) -> list[str]:
    """'handleChatMessage' / 'handle_chat_message' -> ['handle', 'chat', 'message']."""
    return [t.lower() for t in _TOKEN_SPLIT.split(name) if t]


def is_suppressed(source_lines: list[str], *linenos: int) -> bool:
    """A `# manifest: ignore` comment on any of the given 1-based lines suppresses a finding."""
    for lineno in linenos:
        if 0 < lineno <= len(source_lines) and SUPPRESSION_MARKER in source_lines[lineno - 1].lower():
            return True
    return False


def string_parts(node: ast.AST, names: dict[str, str]) -> list[str]:
    """String constants inside `node`, plus the text of any plain variable it mentions whose
    assigned strings are known (`url = f"{base}/chat/completions"` ... `session.post(url)`)."""
    parts: list[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            parts.append(n.value)
        elif isinstance(n, ast.Name) and n.id in names:
            parts.append(names[n.id])
    return parts


def local_strings(scope: ast.AST, base: dict[str, str]) -> dict[str, str]:
    """Name -> concatenated string constants assigned to it anywhere in `scope`, over `base`."""
    known = dict(base)
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            text = " ".join(string_parts(node.value, {}))
            if text:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        known[target.id] = known.get(target.id, "") + " " + text
    return known


def http_target_text(call: ast.Call, names: dict[str, str]) -> str:
    """Lower-cased text of a request call's URL-ish arguments, resolving plain variables."""
    method = dotted_name(call.func).rpartition(".")[2].lower()
    if method not in HTTP_METHODS:
        return ""
    url_args = list(call.args[:2]) + [
        k.value for k in call.keywords if k.arg in {"url", "endpoint", "method"} or k.arg is None
    ]
    return " ".join(part for arg in url_args for part in string_parts(arg, names)).lower()


HTTP_METHODS = {"post", "request", "stream", "send", "put"}
HTTP_CLIENT_MODULES = ("requests", "httpx", "aiohttp", "urllib3")
