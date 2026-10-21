# Real-world evaluation

manifest v0.1 passed its own 14 tests and found nothing wrong with itself. Pointing it at real
code is what showed how little that meant. This document records what happened, including the
parts that don't flatter the tool.

## Method

I ran the scanner on 13 open-source or personal codebases and read **every** finding in the
default view, labelling it by hand:

- **Correct**: the flagged code is a chat/agent interface a person reaches, or a call to a
  generative-content API whose output can reach a user (the pattern the provision describes).
- **Arguable**: AI-backed code that reaches users but is not a chat interface (the finding
  carries the right provision for the wrong reason, or the obligation sits elsewhere).
- **False positive**: the flagged code is plainly not what the rule describes.

v0.1 means the original commit (`aeef3ec`), re-run on identical inputs from a separate
worktree. Nothing below is quoted from memory.

## Headline

| | Findings shown | Correct | Arguable | False positive | Strict precision |
|---|---|---|---|---|---|
| v0.1 | 36 | 12 | 5 | 19 | **33%** |
| v0.2 | 72 | 63 | 7 | 2 | **88%** |

Across the 9 codebases that contain a known chat interface, v0.1 reported one on 2 of them;
v0.2 reports one on 7. The two it still misses are described under *Known limits*.

## Per-codebase

Development set: the repos I iterated on.

| Codebase | v0.1 | v0.2 | Notes |
|---|---|---|---|
| gpt-researcher | 0 | 1 | Three chat routes reach one LLM call; reported once with the others listed |
| vercel/ai-chatbot (TS) | 6 | 6 | 1 chat route, 5 AI-generation files (JS is file-level, so rougher) |
| chat-langchain | 0 | 0 | **Miss.** Agents are served by LangGraph's platform; no route exists in the repo |
| agno `cookbook/` | 0 | 11 | 9 chat-style demos; 2 false positives (`research_assistant_agent`, a simulation harness) |
| agno `libs/` | 4 | 10 | All generation-tool wrappers with no labeling step |
| crewAI `src/` | 2 | 0 | v0.1's 2 were internal provider adapters; now `low_signal`, hidden |
| litellm `proxy/` | 7 | 4 | v0.1's 7 were all false positives (see below); now 4 genuine AI features |
| sentinel (mine) | 0 | 1 | `/query` route traced through `run_agent` to `messages.create` |
| ADAMS (mine) | 0 | 1 | `chat` route traced four hops to a raw `requests.post` to Anthropic |

Held-out set: **four apps I had not looked at**, scanned and recorded *before* fixing anything
found there.

| Codebase | v0.1 | v0.2 at first contact | v0.2 after fixes |
|---|---|---|---|
| Chainlit cookbook | 7 | 19 | 25 (all real `on_message` handlers + one TTS call) |
| streamlit/llm-examples | 2 | 0 | 3 (all three chat pages) |
| private-gpt | 8 | 0 | 0 |
| open-webui | 0 | 0 | 10 |

At first contact only 1 of the 4 apps had its chat interface found, by either version. v0.1's
"findings" on llm-examples and private-gpt were all test functions. After I fixed the three
shapes that caused the misses (Streamlit module-level scripts, URLs held in variables,
LlamaIndex chat methods, plus LangChain's legacy `initialize_agent`) those repos stopped being held out, so the right-hand column is a
development number, not a generalisation estimate. The honest generalisation figure is the
middle column: **1 of 4 unseen apps**.

## What the real code taught me (all fixed, each with a regression test)

Every item here was invisible to the fixtures I wrote myself.

1. **`.run` matched `asyncio.run`.** litellm's CLI entry point was flagged as a generative-content API.
2. **Build output was scanned.** Minified Next.js bundles in `_next/static/chunks/` were flagged as chat interfaces.
3. **Decorators matched by substring.** The check searched `ast.dump(...)` for `get`, which matches `@budget_limit(...)`.
4. **Names matched by substring.** `bot` matches `both_sides` and `robot_arm`.
5. **Library internals reported as interfaces.** crewAI's `_handle_tool_use_conversation` is an adapter, not something a person talks to.
6. **`patch` collided with `unittest.mock.patch`.** Every mocked test looked like an HTTP PATCH route.
7. **Decorator calls were attributed to the decorated function.** `@router.post("/v1/messages")` was read as the handler POSTing to a provider, flagging ten unrelated endpoints.
8. **Provider *host* markers matched non-chat endpoints.** Audio transcription and image generation were reported as chat. A chat call is identified by its path.
9. **`from google import genai` was invisible.** The module was recorded as `google`, so the current Gemini SDK was never recognised.
10. **Functions with no calls were not counted.** That undercounted how many places define a name, which defeated the ambiguity guard in the call-graph pass.
11. **`metadata` counted as a labeling step.** It appears in nearly every function, so almost anything looked labeled.
12. **Wrapper functions were reported as interfaces.** `create_chat_completion` is the LLM layer, not a chat UI.
13. **Streamlit and Gradio chat apps were skipped entirely.** They are module-level scripts, which the function-scoped design ignored.
14. **The architecture most real apps use was unseen.** `route -> service -> client wrapper -> SDK` was reported as nothing. The call-graph pass (`detectors/reach.py`) fixes this.
15. **The depth cap depended on file order.** Found by CI, not by any real repository: the same test passed on Windows and failed on Linux. `MAX_DEPTH` was meant to cap a chain at a number of hops, but chains were extended in place, so a chain could grow several hops in one pass whenever callees were scanned before callers. The search is now level-synchronous and facts are processed in a fixed order. All development and held-out counts above were re-run afterwards and did not change.

## Known limits

- **Name-based call resolution.** Calls resolve by simple function name across the project,
  narrowed by the caller's imports when a name is defined in more than three places. It is a
  heuristic, not a sound call graph. Dependency-injection-heavy code defeats it: private-gpt's
  route reaches `ChatService.chat`, then dead-ends where the service calls its engine through
  an interface with ambiguous method names.
- **No route in the repo, no finding.** Agents served by a platform (LangGraph Platform, for
  chat-langchain) expose no handler to anchor on.
- **JS/TS is regex and file-level.** Expect noise there (see ai-chatbot).
- **A finding is not a violation.** Whether a disclosure is shown, and whether it is clear
  enough, is a runtime and legal question. See the README.

## Caveats on this evaluation

- Thirteen codebases is a small sample, and I chose them. They skew toward Python agent code.
- I labelled findings myself, once. A second reviewer would likely move a few "correct" and
  "arguable" calls.
- I tuned the detectors against most of these repositories. Only the first-contact held-out
  column is an unbiased measurement, and it covers four apps.
- Precision here counts findings, not applications. A repo with twenty chat handlers weighs
  more than one with one.
