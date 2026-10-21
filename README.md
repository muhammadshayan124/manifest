# manifest

Static analysis for [EU AI Act Article 50](https://artificialintelligenceact.eu/article/50/)
transparency obligations (applicable from 2 August 2026). It scans a codebase for two things:

1. **AI interfaces with no AI-disclosure language** (Article 50(1)): a chat or agent
   interface that a person reaches, backed by an LLM call, with nothing in the surrounding
   code telling them they are talking to an AI.
2. **Generated-content pipelines with no labeling step** (Article 50(2)/(4)): image, audio or
   video generation with no attempt to mark the output as machine-detectable AI-generated (the
   Commission's draft Code of Practice names [C2PA Content Credentials](https://c2pa.org/) as
   one such mechanism).

Every finding cites the provision it checks. The reference text is in
[`src/manifest/article50.py`](src/manifest/article50.py).

> **This is a code-review aid, not a compliance certificate.** See
> [What this doesn't do](#what-this-doesnt-do).

## It was tested on real code, and the first version was bad

v0.1 passed its own tests and flagged `asyncio.run` and minified JavaScript bundles on real
projects. Running it on 13 open-source and personal codebases, and reading every finding,
found 14 distinct defects that fixtures could not. The write-up, with per-repo numbers and the
parts that don't flatter the tool, is in
[`docs/real-world-evaluation.md`](docs/real-world-evaluation.md).

| | Findings shown | Correct | False positive | Strict precision |
|---|---|---|---|---|
| v0.1 | 36 | 12 | 19 | 33% |
| v0.2 | 72 | 63 | 2 | 88% |

Honest caveat: I tuned against most of those repos. On four apps I had **not** seen, a chat
interface was found in only one of them at first contact. The document says which fixes
followed and which misses remain.

## Install and use

```bash
pip install -e ".[dev]"

manifest scan path/to/project
manifest scan path/to/project --format sarif > manifest.sarif   # GitHub code scanning
manifest scan path/to/project --format json
manifest scan path/to/project --fail-on likely                  # CI gate
manifest scan path/to/project --include-low-signal              # show hidden findings
```

### Confidence levels

| Level | Meaning | `--fail-on` |
|---|---|---|
| `likely_violation` | Pattern found, no disclosure/labeling signal anywhere nearby | `likely`, `any` |
| `needs_review` | Pattern found, a disclosure signal exists; verify it is really shown | `any` |
| `low_signal` | Private helper, test/demo/benchmark code, or a health/transcription path. Hidden by default | never |

### Suppress a finding on purpose

```python
response = client.chat.completions.create(...)  # manifest: ignore
```

On the call line, the `def` line or a decorator line (`// manifest: ignore` in JS/TS).

### GitHub Action

```yaml
- uses: muhammadshayan124/manifest@master
  with:
    path: .
    fail-on: likely
```

Findings appear in the Security tab and as pull request annotations via SARIF. A pre-commit
hook is also provided (`.pre-commit-hooks.yaml`).

## How detection works

An LLM call is recognised by shape: raw SDK calls (OpenAI chat/responses, Anthropic messages,
Gemini, LiteLLM, Mistral, Bedrock `converse`), LangChain `Chat*` models and runnables
(tracked through aliases, pipelines and `with_structured_output`), agent objects from agno,
crewAI, AutoGen, LangGraph and LlamaIndex, app-level wrappers like `create_chat_completion`,
and raw HTTP to a provider's chat **path** (never the host alone, since a host also serves
audio and image endpoints).

It is reported only where the surrounding code looks like an interface a person reaches: a
route/bot decorator, or a function name whose tokens say chat, bot or assistant. Three
mechanisms keep this from being noisy:

- **Route handlers are traced to the model.** Real apps are `route -> service -> client ->
  SDK`, so a project-level pass follows calls by name (narrowed by the caller's imports) and
  reports the handler with its full chain. Handlers reaching the same call are grouped.
- **Streamlit and Gradio chat scripts** are recognised by `st.chat_input` and friends, since
  they are module-level scripts rather than functions.
- **Probes and internals are demoted, not dropped**: private helpers, test/example/benchmark
  paths, and names like `health`, `benchmark`, `transcribe`, `embed` go to `low_signal`.

Generated content (Article 50(2)) uses the same gating for image/audio/video generation calls,
SDK or raw HTTP, and looks for a watermark/provenance term (`c2pa`, `synthid`, `watermark`,
`iptc`, ...) in the same function.

## What this doesn't do

- **It cannot see runtime.** A `needs_review` result means "a disclosure signal exists
  nearby", not "this is compliant". It cannot tell whether a disclosure is rendered, in a UI a
  person sees, before their first message, or whether a watermark survives re-encoding.
- **Call resolution is by name.** It is a heuristic, not a sound call graph. Dependency
  injection with ambiguous method names defeats it (private-gpt is a documented miss), and an
  agent served by a platform with no route in the repo (chat-langchain) produces no finding.
- **JS/TS is regex and file-level**, so it is a rougher signal than the Python detectors.
- **It does not decide legal questions**: whether a disclosure is "clear and distinguishable",
  whether content is a "deepfake", or who the provider and deployer are. Talk to someone
  qualified before relying on a scan for a compliance decision.

## Development

```bash
pytest          # 93 tests
```

The suite includes a negative control (a batch job that calls a chat API but is not an
interface), a regression test for each defect the real-world runs found, and an end-to-end
check that SARIF output is well formed.

## License

MIT
