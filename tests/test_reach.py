"""Project-level call-graph pass and raw-HTTP LLM detection. Both exist because running
manifest on three real apps found LLM calls it never reported: the handler never touches
the SDK (route -> service -> wrapper), or the code never uses an SDK at all.
"""

import textwrap
from pathlib import Path

from manifest.detectors import chatbot_disclosure
from manifest.detectors.base import Confidence
from manifest.scan import scan_path


def write(tmp_path: Path, name: str, code: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(code), encoding="utf-8")
    return path


def _three_layer_app(tmp_path: Path, handler_body: str = "return answer_question(q)") -> None:
    write(tmp_path, "api.py", f"""
        from fastapi import FastAPI
        from service import answer_question

        app = FastAPI()

        @app.post("/query")
        def query(q):
            {handler_body}
    """)
    write(tmp_path, "service.py", """
        from llm_client import LLMClient

        def answer_question(q):
            return LLMClient().complete(q)
    """)
    write(tmp_path, "llm_client.py", """
        import anthropic

        class LLMClient:
            def __init__(self):
                self._c = anthropic.Anthropic()

            def complete(self, q):
                return self._c.messages.create(model="m", messages=[{"role": "user", "content": q}])
    """)


def test_route_reaching_an_llm_through_two_layers_is_reported_with_its_chain(tmp_path):
    _three_layer_app(tmp_path)
    findings = [f for f in scan_path(tmp_path) if f.file.endswith("api.py")]
    assert len(findings) == 1
    f = findings[0]
    assert f.confidence == Confidence.likely_violation
    assert "query -> answer_question -> LLMClient.complete" in f.detail
    assert "messages.create" in f.detail
    assert f.line == 8  # the route handler, so a SARIF annotation lands on the interface


def test_route_that_does_not_reach_an_llm_is_not_reported(tmp_path):
    _three_layer_app(tmp_path, handler_body="return {'ok': True}")
    assert [f for f in scan_path(tmp_path) if f.file.endswith("api.py")] == []


def test_non_route_function_reaching_an_llm_is_not_reported_indirectly(tmp_path):
    """Only route-decorated handlers become indirect findings; internals would flood output."""
    write(tmp_path, "a.py", """
        from b import llm_call

        def helper(q):
            return llm_call(q)
    """)
    write(tmp_path, "b.py", """
        import anthropic

        def llm_call(q):
            return anthropic.Anthropic().messages.create(model="m", messages=[])
    """)
    assert [f for f in scan_path(tmp_path) if f.file.endswith("a.py")] == []


def test_ambiguous_callee_names_are_ignored(tmp_path):
    """A name defined in more than MAX_DEFINITIONS places cannot be resolved honestly."""
    write(tmp_path, "api.py", """
        from fastapi import FastAPI

        app = FastAPI()

        @app.post("/go")
        def go(x):
            return run(x)
    """)
    write(tmp_path, "llm.py", """
        import anthropic

        def run(x):
            return anthropic.Anthropic().messages.create(model="m", messages=[])
    """)
    for i in range(3):
        write(tmp_path, f"other{i}.py", "def run(x):\n    return x\n")
    assert [f for f in scan_path(tmp_path) if f.file.endswith("api.py")] == []


def test_disclosure_anywhere_on_the_chain_downgrades_to_needs_review(tmp_path):
    _three_layer_app(tmp_path)
    (tmp_path / "service.py").write_text(
        textwrap.dedent("""
            from llm_client import LLMClient

            def answer_question(q):
                return "You are chatting with an AI assistant. " + LLMClient().complete(q)
        """),
        encoding="utf-8",
    )
    findings = [f for f in scan_path(tmp_path) if f.file.endswith("api.py")]
    assert [f.confidence for f in findings] == [Confidence.needs_review]


def test_health_route_reaching_an_llm_is_low_signal(tmp_path):
    write(tmp_path, "api.py", """
        from fastapi import FastAPI
        from llm import ping_model

        app = FastAPI()

        @app.get("/health")
        def health():
            return ping_model()
    """)
    write(tmp_path, "llm.py", """
        import anthropic

        def ping_model():
            return anthropic.Anthropic().messages.create(model="m", messages=[])
    """)
    assert [f.confidence for f in scan_path(tmp_path) if f.file.endswith("api.py")] == [Confidence.low_signal]


def test_chain_depth_is_capped(tmp_path):
    """route -> f1 -> f2 -> f3 -> f4 -> f5 -> LLM is beyond MAX_DEPTH and is not reported."""
    names = ["route_fn", "f1", "f2", "f3", "f4", "f5", "leaf"]
    write(tmp_path, "api.py", """
        from fastapi import FastAPI

        app = FastAPI()

        @app.post("/x")
        def route_fn(q):
            return f1(q)
    """)
    for a, b in zip(names[1:-1], names[2:]):
        write(tmp_path, f"{a}.py", f"def {a}(q):\n    return {b}(q)\n")
    write(tmp_path, "leaf.py", """
        import anthropic

        def leaf(q):
            return anthropic.Anthropic().messages.create(model="m", messages=[])
    """)
    assert [f for f in scan_path(tmp_path) if f.file.endswith("api.py")] == []


def test_a_route_that_calls_the_sdk_directly_is_reported_once_not_twice(tmp_path):
    write(tmp_path, "api.py", """
        import anthropic
        from fastapi import FastAPI

        app = FastAPI()
        client = anthropic.Anthropic()

        @app.post("/chat")
        def chat(q):
            return client.messages.create(model="m", messages=[])
    """)
    assert len(scan_path(tmp_path)) == 1


def test_suppression_on_the_route_applies_to_the_indirect_finding(tmp_path):
    _three_layer_app(tmp_path)
    path = tmp_path / "api.py"
    path.write_text(path.read_text(encoding="utf-8").replace('@app.post("/query")', '@app.post("/query")  # manifest: ignore'), encoding="utf-8")
    assert [f for f in scan_path(tmp_path) if f.file.endswith("api.py")] == []


# --- raw HTTP ---------------------------------------------------------------------------


def test_requests_post_to_a_provider_endpoint_is_an_llm_call(tmp_path):
    path = write(tmp_path, "svc.py", """
        import requests

        def chat_endpoint(msgs):
            return requests.post("https://api.anthropic.com/v1/messages", json={"messages": msgs})
    """)
    assert len(chatbot_disclosure.scan_file(path)) == 1


def test_httpx_with_a_keyword_url_and_fstring(tmp_path):
    path = write(tmp_path, "svc.py", """
        import httpx

        async def chat_endpoint(model, msgs):
            async with httpx.AsyncClient() as c:
                return await c.post(url=f"https://api.openai.com/v1/chat/completions?m={model}", json=msgs)
    """)
    assert len(chatbot_disclosure.scan_file(path)) == 1


def test_http_post_to_an_unrelated_url_is_not_an_llm_call(tmp_path):
    path = write(tmp_path, "svc.py", """
        import requests

        def chat_endpoint(msgs):
            return requests.post("https://example.com/api/webhook", json=msgs)
    """)
    assert chatbot_disclosure.scan_file(path) == []


def test_http_get_to_a_provider_host_is_not_a_chat_call(tmp_path):
    """Listing models is a GET; only request-sending verbs count."""
    path = write(tmp_path, "svc.py", """
        import requests

        def chat_models():
            return requests.get("https://api.openai.com/v1/models")
    """)
    assert chatbot_disclosure.scan_file(path) == []
