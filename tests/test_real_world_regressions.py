"""Regression tests for defects found by running manifest on real code (agno, crewAI,
litellm) rather than on its own fixtures. Each test names the real-world failure it pins.
"""

import json
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from manifest.cli import app
from manifest.detectors import chatbot_disclosure, generated_content, js_heuristic
from manifest.detectors.base import Confidence
from manifest.report import to_sarif
from manifest.scan import scan_path

runner = CliRunner()


def write(tmp_path: Path, name: str, code: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(code), encoding="utf-8")
    return path


# --- generated_content: exact-receiver matching ---------------------------------------


def test_asyncio_run_is_not_a_generative_call(tmp_path):
    """litellm's proxy_cli flagged `asyncio.run(...)` because '.run' was a loose suffix."""
    path = write(tmp_path, "cli.py", """
        import asyncio
        import replicate

        def run_server():
            asyncio.run(main())
    """)
    assert generated_content.scan_file(path) == []


def test_replicate_module_run_is_still_flagged(tmp_path):
    path = write(tmp_path, "gen.py", """
        import replicate

        def make_media(prompt):
            return replicate.run("model", input={"prompt": prompt})
    """)
    assert len(generated_content.scan_file(path)) == 1


def test_replicate_client_run_is_flagged_only_for_a_tracked_client(tmp_path):
    tracked = write(tmp_path, "a.py", """
        import replicate

        client = replicate.Client()

        def make_media(prompt):
            return client.run("model", input={"prompt": prompt})
    """)
    untracked = write(tmp_path, "b.py", """
        import replicate

        def make_media(prompt, runner):
            return runner.run("model")
    """)
    assert len(generated_content.scan_file(tracked)) == 1
    assert generated_content.scan_file(untracked) == []


def test_bare_metadata_no_longer_counts_as_a_labeling_step(tmp_path):
    """'metadata' appears in nearly every function, so it made almost anything look labeled."""
    path = write(tmp_path, "gen.py", """
        import openai

        client = openai.OpenAI()

        def make_image(prompt):
            result = client.images.generate(model="m", prompt=prompt)
            return {"url": result.data[0].url, "metadata": {"prompt": prompt}}
    """)
    findings = generated_content.scan_file(path)
    assert [f.confidence for f in findings] == [Confidence.likely_violation]


def test_new_generation_apis_are_detected(tmp_path):
    path = write(tmp_path, "gen.py", """
        import fal_client
        from elevenlabs.client import ElevenLabs

        eleven = ElevenLabs()

        def a(prompt):
            return fal_client.subscribe("fal-ai/flux", arguments={"prompt": prompt})

        def b(text):
            return eleven.text_to_speech.convert(text=text)
    """)
    assert len(generated_content.scan_file(path)) == 2


# --- chatbot_disclosure: name/decorator matching ---------------------------------------


def test_decorator_substring_does_not_look_like_a_route(tmp_path):
    """The old check searched ast.dump(decorator) for 'get', which matches `@budget_limit`."""
    path = write(tmp_path, "svc.py", """
        import openai

        client = openai.OpenAI()

        @budget_limit(10)
        def generate_report(text):
            return client.chat.completions.create(model="m", messages=[])
    """)
    assert chatbot_disclosure.scan_file(path) == []


@pytest.mark.parametrize("name", ["both_sides", "robot_arm", "target_audience"])
def test_name_tokens_not_substrings(tmp_path, name):
    """'bot' is a substring of both/robot; 'get' of target. Tokens must match whole words."""
    path = write(tmp_path, "svc.py", f"""
        import openai

        client = openai.OpenAI()

        def {name}(text):
            return client.chat.completions.create(model="m", messages=[])
    """)
    assert chatbot_disclosure.scan_file(path) == []


def test_private_helper_is_low_signal_not_a_violation(tmp_path):
    """crewAI's `_handle_tool_use_conversation` is an internal adapter, not an interface."""
    path = write(tmp_path, "adapter.py", """
        import anthropic

        client = anthropic.Anthropic()

        def _handle_tool_use_conversation(msgs):
            return client.messages.create(model="m", messages=msgs)
    """)
    assert [f.confidence for f in chatbot_disclosure.scan_file(path)] == [Confidence.low_signal]


def test_route_decorated_private_function_is_still_a_violation(tmp_path):
    path = write(tmp_path, "app.py", """
        import openai
        from fastapi import FastAPI

        app = FastAPI()
        client = openai.OpenAI()

        @app.post("/ask")
        def _handler(q):
            return client.chat.completions.create(model="m", messages=[])
    """)
    assert [f.confidence for f in chatbot_disclosure.scan_file(path)] == [Confidence.likely_violation]


def test_health_check_route_is_low_signal(tmp_path):
    """litellm's `health_services_endpoint` is a route that calls a model to probe it."""
    path = write(tmp_path, "health.py", """
        import litellm
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/health/services")
        async def health_services_endpoint():
            return await litellm.acompletion(model="m", messages=[])
    """)
    assert [f.confidence for f in chatbot_disclosure.scan_file(path)] == [Confidence.low_signal]


# --- chatbot_disclosure: current API shapes (recall) -----------------------------------


@pytest.mark.parametrize(
    "setup, call",
    [
        ("import openai\nclient = openai.OpenAI()", "client.responses.create(model='m', input='x')"),
        ("import litellm", "litellm.completion(model='m', messages=[])"),
        ("import litellm", "await litellm.acompletion(model='m', messages=[])"),
        ("import anthropic\nclient = anthropic.Anthropic()", "client.messages.stream(model='m', messages=[])"),
        ("from google import genai\nclient = genai.Client()", "client.models.generate_content(model='m', contents='x')"),
        ("from langchain_openai import ChatOpenAI\nllm = ChatOpenAI()", "llm.invoke('x')"),
        ("from langchain_anthropic import ChatAnthropic\nllm = ChatAnthropic()", "await llm.ainvoke('x')"),
        ("from agno.agent import Agent\nbot_agent = Agent()", "await bot_agent.arun('x')"),
        ("from crewai import Crew\ncrew = Crew()", "crew.kickoff()"),
    ],
)
def test_current_api_shapes_are_detected(tmp_path, setup, call):
    path = write(tmp_path, "svc.py", f"{setup}\n\nasync def chat_endpoint():\n    return {call}\n")
    assert len(chatbot_disclosure.scan_file(path)) == 1


def test_self_attribute_chat_model_is_tracked(tmp_path):
    path = write(tmp_path, "bot.py", """
        from langchain_openai import ChatOpenAI

        class SupportBot:
            def __init__(self):
                self.llm = ChatOpenAI()

            def chat(self, text):
                return self.llm.invoke(text)
    """)
    assert len(chatbot_disclosure.scan_file(path)) == 1


def test_invoke_on_an_unrelated_object_is_not_a_chat_call(tmp_path):
    path = write(tmp_path, "svc.py", """
        import openai

        def chat_endpoint(task_queue):
            return task_queue.invoke("work")
    """)
    assert chatbot_disclosure.scan_file(path) == []


def test_agent_methods_need_an_agent_framework_import(tmp_path):
    path = write(tmp_path, "svc.py", """
        import openai
        from mylib import Agent

        helper = Agent()

        def chat_endpoint():
            return helper.run("x")
    """)
    assert chatbot_disclosure.scan_file(path) == []


def test_bedrock_converse_detected_but_not_a_method_named_converse_on_self(tmp_path):
    bedrock = write(tmp_path, "a.py", """
        import boto3

        runtime = boto3.client("bedrock-runtime")

        def chat_endpoint(msgs):
            return runtime.converse(modelId="m", messages=msgs)
    """)
    own_method = write(tmp_path, "b.py", """
        import boto3

        class Chatter:
            def converse(self):
                return 1

            def chat_endpoint(self):
                return self.converse()
    """)
    assert len(chatbot_disclosure.scan_file(bedrock)) == 1
    assert chatbot_disclosure.scan_file(own_method) == []


# --- chatbot_disclosure: disclosure defined once at module level -----------------------


def test_module_level_disclosure_constant_counts(tmp_path):
    path = write(tmp_path, "bot.py", """
        import openai

        client = openai.OpenAI()
        WELCOME = "Hi! You are chatting with an AI assistant."

        def chat_endpoint(q):
            reply = client.chat.completions.create(model="m", messages=[])
            return WELCOME, reply
    """)
    assert [f.confidence for f in chatbot_disclosure.scan_file(path)] == [Confidence.needs_review]


# --- suppression -----------------------------------------------------------------------


def test_ignore_comment_on_call_line(tmp_path):
    path = write(tmp_path, "bot.py", """
        import openai

        client = openai.OpenAI()

        def chat_endpoint(q):
            return client.chat.completions.create(model="m", messages=[])  # manifest: ignore
    """)
    assert chatbot_disclosure.scan_file(path) == []


def test_ignore_comment_on_def_line_and_on_decorator(tmp_path):
    on_def = write(tmp_path, "a.py", """
        import openai

        client = openai.OpenAI()

        def chat_endpoint(q):  # manifest: ignore
            return client.chat.completions.create(model="m", messages=[])
    """)
    on_decorator = write(tmp_path, "b.py", """
        import replicate

        @cached  # manifest: ignore
        def make(prompt):
            return replicate.run("m")
    """)
    assert chatbot_disclosure.scan_file(on_def) == []
    assert generated_content.scan_file(on_decorator) == []


def test_ignore_comment_in_js(tmp_path):
    path = write(tmp_path, "chat.ts", """
        import OpenAI from "openai";
        const r = await client.chat.completions.create({}); // manifest: ignore
    """)
    assert js_heuristic.scan_file(path) == []


# --- scan: generated files and demo/test paths -----------------------------------------


def test_minified_and_bundled_js_is_skipped(tmp_path):
    """litellm's `_next/static/chunks/*.js` bundles were flagged as chat interfaces."""
    bundle = 'import OpenAI from "openai";' + "x=1;" * 1000 + "client.chat.completions.create({});"
    write(tmp_path, "static/app.min.js", bundle)
    write(tmp_path, "out/_next/static/chunks/abc.js", bundle)
    write(tmp_path, "src/wide.js", bundle)  # no marker in name or path: caught by line length
    assert scan_path(tmp_path) == []


def test_hand_written_js_is_still_scanned(tmp_path):
    write(tmp_path, "src/chat.ts", 'import OpenAI from "openai";\nawait c.chat.completions.create({});\n')
    assert len(scan_path(tmp_path)) == 1


@pytest.mark.parametrize("rel", ["examples/chat.py", "tests/chat.py", "benchmarks/chat.py", "chat_test.py", "test_chat.py"])
def test_demo_and_test_code_is_demoted_not_dropped(tmp_path, rel):
    write(tmp_path, rel, """
        import openai

        client = openai.OpenAI()

        def chat_endpoint(q):
            return client.chat.completions.create(model="m", messages=[])
    """)
    assert [f.confidence for f in scan_path(tmp_path)] == [Confidence.low_signal]


def test_scanning_a_directory_named_examples_does_not_demote_everything(tmp_path):
    """Only sub-paths below the scan root count; the root itself is the user's choice."""
    root = tmp_path / "examples"
    write(root, "chat.py", """
        import openai

        client = openai.OpenAI()

        def chat_endpoint(q):
            return client.chat.completions.create(model="m", messages=[])
    """)
    assert [f.confidence for f in scan_path(root)] == [Confidence.likely_violation]


# --- CLI / SARIF -----------------------------------------------------------------------


def _vulnerable_app(tmp_path: Path) -> Path:
    write(tmp_path, "app.py", """
        import openai
        from fastapi import FastAPI

        app = FastAPI()
        client = openai.OpenAI()

        @app.post("/chat")
        def chat_endpoint(q):
            return client.chat.completions.create(model="m", messages=[])

        def _internal_chat_helper(q):
            return client.chat.completions.create(model="m", messages=[])
    """)
    return tmp_path


def test_low_signal_hidden_by_default_and_shown_on_request(tmp_path):
    root = _vulnerable_app(tmp_path)
    default = json.loads(runner.invoke(app, ["scan", str(root), "--format", "json"]).stdout)
    assert default["finding_count"] == 1
    assert default["hidden_low_signal_count"] == 1

    shown = json.loads(runner.invoke(app, ["scan", str(root), "--format", "json", "--include-low-signal"]).stdout)
    assert shown["finding_count"] == 2
    assert shown["hidden_low_signal_count"] == 0


def test_json_flag_is_still_supported(tmp_path):
    out = runner.invoke(app, ["scan", str(_vulnerable_app(tmp_path)), "--json"]).stdout
    assert json.loads(out)["finding_count"] == 1


def test_fail_on_modes(tmp_path):
    root = str(_vulnerable_app(tmp_path))
    assert runner.invoke(app, ["scan", root]).exit_code == 0
    assert runner.invoke(app, ["scan", root, "--fail-on", "likely"]).exit_code == 1
    assert runner.invoke(app, ["scan", root, "--fail-on", "any"]).exit_code == 1
    assert runner.invoke(app, ["scan", root, "--fail-on-findings"]).exit_code == 1
    assert runner.invoke(app, ["scan", str(tmp_path / "nope")]).exit_code == 2


def test_fail_on_likely_ignores_needs_review(tmp_path):
    write(tmp_path, "app.py", """
        import openai

        client = openai.OpenAI()

        def chat_endpoint(q):
            msg = "You are chatting with an AI assistant"
            return msg, client.chat.completions.create(model="m", messages=[])
    """)
    assert runner.invoke(app, ["scan", str(tmp_path), "--fail-on", "likely"]).exit_code == 0
    assert runner.invoke(app, ["scan", str(tmp_path), "--fail-on", "any"]).exit_code == 1


def test_sarif_output_is_well_formed(tmp_path, monkeypatch):
    root = _vulnerable_app(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["scan", str(root), "--format", "sarif", "--include-low-signal"])
    sarif = json.loads(result.stdout)

    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "manifest"
    assert {r["id"] for r in run["tool"]["driver"]["rules"]} == {"AIA-50-1"}

    levels = sorted(r["level"] for r in run["results"])
    assert levels == ["note", "warning"]  # low_signal -> note, likely_violation -> warning
    for r in run["results"]:
        loc = r["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "app.py"  # relative + forward slashes for code scanning
        assert loc["region"]["startLine"] > 0
        assert r["ruleId"] == "AIA-50-1"


def test_sarif_rule_ids_cover_every_provision():
    from manifest.article50 import (
        CHATBOT_DISCLOSURE,
        DEEPFAKE_DISCLOSURE,
        GENERATED_CONTENT_MARKING,
        PUBLIC_INTEREST_TEXT_DISCLOSURE,
    )
    from manifest.detectors.base import Finding
    from manifest.report import _rule_id

    ids = {
        _rule_id(p.citation)
        for p in (CHATBOT_DISCLOSURE, GENERATED_CONTENT_MARKING, DEEPFAKE_DISCLOSURE, PUBLIC_INTEREST_TEXT_DISCLOSURE)
    }
    assert ids == {"AIA-50-1", "AIA-50-2", "AIA-50-4", "AIA-50-4-2"}
    assert json.loads(to_sarif([]))["runs"][0]["results"] == []
    _ = Finding  # imported to document the type being serialised


# --- second round, from scanning gpt-researcher / chat-langchain / vercel/ai-chatbot ----


def test_mock_patch_is_not_a_route_decorator(tmp_path):
    """gpt-researcher's tests were reported as 'route handlers': 'patch' (HTTP PATCH) collided
    with unittest.mock.patch. The verb only counts on an object, and never on mock/unittest."""
    path = write(tmp_path, "test_it.py", """
        import litellm
        from unittest.mock import patch
        import unittest.mock

        @patch("a.b")
        def chat_one():
            return litellm.completion(model="m", messages=[])

        @unittest.mock.patch("a.b")
        def chat_two():
            return litellm.completion(model="m", messages=[])
    """)
    facts = chatbot_disclosure.analyze_file(path)
    assert [f.has_route for f in facts] == [False, False]


def test_real_http_patch_route_still_counts(tmp_path):
    path = write(tmp_path, "app.py", """
        import litellm
        from fastapi import FastAPI

        app = FastAPI()

        @app.patch("/thing")
        def update_thing():
            return litellm.completion(model="m", messages=[])
    """)
    assert [f.confidence for f in chatbot_disclosure.scan_file(path)] == [Confidence.likely_violation]


def test_llm_wrapper_functions_are_not_reported_as_interfaces(tmp_path):
    """`create_chat_completion` is the LLM layer itself; the word 'chat' in its name does not
    make it something a person talks to."""
    path = write(tmp_path, "llm.py", """
        import openai

        client = openai.OpenAI()

        def create_chat_completion(messages):
            return client.chat.completions.create(model="m", messages=messages)
    """)
    assert chatbot_disclosure.scan_file(path) == []


def test_calls_to_an_app_level_chat_wrapper_count_as_llm_calls(tmp_path):
    path = write(tmp_path, "svc.py", """
        import openai
        from utils import create_chat_completion

        async def chat_endpoint(q):
            return await create_chat_completion(messages=[q])
    """)
    assert len(chatbot_disclosure.scan_file(path)) == 1


def test_tracking_follows_aliases_pipelines_and_derivations(tmp_path):
    path = write(tmp_path, "bot.py", """
        from langchain_openai import ChatOpenAI

        class Bot:
            def __init__(self):
                base = ChatOpenAI()
                self.llm = base
                self.structured = base.with_structured_output(dict)
                self.chain = prompt | base

            def chat_a(self, q):
                return self.llm.invoke(q)

            def chat_b(self, q):
                return self.structured.invoke(q)

            def chat_c(self, q):
                return self.chain.invoke(q)
    """)
    assert len(chatbot_disclosure.scan_file(path)) == 3


def test_runnable_named_receiver_in_a_langchain_file_counts(tmp_path):
    """chat-langchain builds models in helpers and calls `self.llm.ainvoke` / `structured_llm.ainvoke`."""
    path = write(tmp_path, "mw.py", """
        from langchain_core.messages import HumanMessage

        class Responder:
            async def chat_reply(self, q):
                return await self.llm.ainvoke(q)
    """)
    assert len(chatbot_disclosure.scan_file(path)) == 1


def test_ainvoke_on_unrelated_receiver_in_a_langchain_file_does_not_count(tmp_path):
    path = write(tmp_path, "mw.py", """
        from langchain_core.tools import tool

        async def chat_reply(q, search_tool):
            return await search_tool.ainvoke(q)
    """)
    assert chatbot_disclosure.scan_file(path) == []


def test_decorator_call_is_not_attributed_to_the_decorated_function(tmp_path):
    """litellm's `@router.post("/v1/messages")` was read as an HTTP POST to a provider
    endpoint made *by* the handler, flagging ~10 unrelated endpoints."""
    path = write(tmp_path, "endpoints.py", """
        import httpx
        from fastapi import APIRouter

        router = APIRouter()

        @router.post("/v1/messages")
        async def count_things(request):
            return {"ok": True}

        @router.post("/v1/chat/completions")
        async def chat_completion(request):
            return {"ok": True}
    """)
    assert chatbot_disclosure.scan_file(path) == []


def test_default_argument_calls_belong_to_the_enclosing_scope(tmp_path):
    path = write(tmp_path, "svc.py", """
        import litellm

        def chat_endpoint(q, reply=litellm.completion(model="m", messages=[])):
            return reply
    """)
    assert chatbot_disclosure.scan_file(path) == []


def test_probe_name_anywhere_on_the_chain_demotes_it(tmp_path):
    write(tmp_path, "cli.py", """
        import click
        from runner import _run_test_chat_completion

        @click.command()
        def run_server():
            return _run_test_chat_completion()
    """)
    write(tmp_path, "runner.py", """
        import openai

        def _run_test_chat_completion():
            return openai.OpenAI().chat.completions.create(model="m", messages=[])
    """)
    confidences = [f.confidence for f in scan_path(tmp_path) if f.file.endswith("cli.py")]
    assert confidences == [Confidence.low_signal]


# --- third round: held-out apps (open-webui, private-gpt, streamlit/llm-examples) --------


@pytest.mark.parametrize(
    "url",
    [
        "https://api.mistral.ai/v1/audio/transcriptions",
        "https://api.openai.com/v1/images/generations",
        "https://api.openai.com/v1/embeddings",
        "https://api.openai.com/v1/models",
    ],
)
def test_provider_host_alone_does_not_make_a_chat_call(tmp_path, url):
    """open-webui's audio transcription (Mistral) and image generation (OpenAI) were reported
    as chat calls because the check matched the provider host rather than the chat path."""
    path = write(tmp_path, "svc.py", f"""
        import aiohttp

        async def chat_endpoint(session, payload):
            return await session.post("{url}", json=payload)
    """)
    assert chatbot_disclosure.scan_file(path) == []


def test_chat_url_held_in_a_variable_is_resolved(tmp_path):
    path = write(tmp_path, "svc.py", """
        import aiohttp

        async def generate_chat_completion(base, payload):
            url = f"{base}/chat/completions"
            async with aiohttp.ClientSession() as session:
                return await session.request(method="POST", url=url, json=payload)
    """)
    assert len(chatbot_disclosure.scan_file(path)) == 1


def test_variable_is_only_resolved_within_its_own_function(tmp_path):
    path = write(tmp_path, "svc.py", """
        import requests

        def other():
            url = "https://x.test/chat/completions"
            return url

        def chat_endpoint(url, payload):
            return requests.post(url, json=payload)
    """)
    assert chatbot_disclosure.scan_file(path) == []


def test_raw_http_image_generation_is_a_generated_content_finding(tmp_path):
    path = write(tmp_path, "img.py", """
        import aiohttp

        async def image_generations(session, payload):
            return await session.post("https://api.openai.com/v1/images/generations", json=payload)
    """)
    findings = generated_content.scan_file(path)
    assert [f.provision.citation for f in findings] == ["Article 50(2)"]


def test_llamaindex_chat_methods_on_an_llm_or_engine(tmp_path):
    path = write(tmp_path, "svc.py", """
        from llama_index.core.llms import LLM

        async def chat_endpoint(run, msgs):
            return await run.llm.astream_chat_with_tools(msgs)
    """)
    assert len(chatbot_disclosure.scan_file(path)) == 1


def test_llamaindex_chat_method_on_an_unrelated_receiver_is_ignored(tmp_path):
    path = write(tmp_path, "svc.py", """
        from llama_index.core.llms import LLM

        async def chat_endpoint(session, msgs):
            return await session.chat(msgs)
    """)
    assert chatbot_disclosure.scan_file(path) == []


def test_streamlit_module_level_chat_app_is_detected(tmp_path):
    """Streamlit apps are scripts: the model call sits at module level, next to st.chat_input."""
    path = write(tmp_path, "Chatbot.py", """
        import streamlit as st
        from openai import OpenAI

        client = OpenAI()

        if prompt := st.chat_input():
            response = client.chat.completions.create(model="m", messages=[{"role": "user", "content": prompt}])
            st.chat_message("assistant").write(response.choices[0].message.content)
    """)
    findings = chatbot_disclosure.scan_file(path)
    assert [f.confidence for f in findings] == [Confidence.likely_violation]
    assert "<module>" in findings[0].detail


def test_module_level_model_call_without_a_ui_chat_signal_is_still_ignored(tmp_path):
    path = write(tmp_path, "script.py", """
        import streamlit as st
        from openai import OpenAI

        client = OpenAI()
        summary = client.chat.completions.create(model="m", messages=[])
        st.write(summary)
    """)
    assert chatbot_disclosure.scan_file(path) == []


def test_streamlit_disclosure_string_is_recognised(tmp_path):
    path = write(tmp_path, "Chatbot.py", """
        import streamlit as st
        from openai import OpenAI

        client = OpenAI()
        st.caption("You are chatting with an AI assistant")

        if prompt := st.chat_input():
            client.chat.completions.create(model="m", messages=[])
    """)
    assert [f.confidence for f in chatbot_disclosure.scan_file(path)] == [Confidence.needs_review]


def test_langchain_legacy_initialize_agent_is_tracked(tmp_path):
    """streamlit/llm-examples' search chat builds `initialize_agent([...], llm)` then `.run(...)`."""
    path = write(tmp_path, "page.py", """
        import streamlit as st
        from langchain.agents import initialize_agent
        from langchain.chat_models import ChatOpenAI

        llm = ChatOpenAI()
        search_agent = initialize_agent([], llm)

        if prompt := st.chat_input():
            response = search_agent.run(prompt)
    """)
    assert len(chatbot_disclosure.scan_file(path)) == 1
