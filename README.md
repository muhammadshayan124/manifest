# manifest

Two tools for the [EU AI Act](https://artificialintelligenceact.eu/): a **code scanner** for Article 50
transparency obligations, and a **toolkit** that classifies a system's risk tier, tracks a conformity checklist and
generates Annex IV technical documentation ([jump to the toolkit](#eu-ai-act-toolkit-manifest-act)).

The scanner is static analysis for [EU AI Act Article 50](https://artificialintelligenceact.eu/article/50/)
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

## EU AI Act toolkit (`manifest act`)

The scanner answers "does this code disclose that it is an AI?". The toolkit answers the questions that come before and
after: *which rules apply to this system, what is left to do, and is the paperwork complete?* It works from a small
YAML profile of facts about your system that lives in the repo next to the code.

```bash
manifest act init                              # annotated profile listing every valid Annex III / Article 5 id
manifest act classify system.yaml              # tier, the provisions behind it, what applies, and when
manifest act checklist system.yaml --scan src  # conformity checklist, with the code scanner attached
manifest act mark art9 done --evidence docs/risk-register.md
manifest act docs system.yaml --check          # Annex IV scaffold; exit 1 while sections are unanswered
manifest act timeline                          # application dates, with their source and caveat
```

**Classify** walks the Act's own decision order: out of scope (Art. 2) -> prohibited (Art. 5, all eight points) ->
high-risk (Art. 6: the Annex I product route, or any of the 25 Annex III use cases, unless the Art. 6(3) derogation
holds and the system does no profiling) -> "not high-risk, but document it" (Art. 6(4)) -> Article 50 transparency ->
minimal. General-purpose AI model duties (Art. 51-55, with the 1e25 FLOP presumption and the open-source exemption's
limits) and AI literacy (Art. 4) are layered on top. Duties are split by role: a deployer of a high-risk system gets
Articles 26, 27 and 86; a provider gets Articles 9-20, 43, 47-49, 72 and 73.

```text
$ manifest act classify examples/act/cv-screener.yaml
CV Screener: HIGH RISK
  Annex III 4(a)  Recruitment or selection, including targeted job advertising, filtering applications...
  Article 6(2)    Annex III use case with profiling of natural persons
```

**Checklist** items carry a status and evidence, and are merged by id when the profile changes, so progress is never
wiped. Two rules stop it becoming theatre: an item cannot be `done` without evidence, and an Article 50 item cannot
be `done` while the scanner still reports a likely violation for it. Open items are reported but do not fail a build by
default (`--fail-on open` is there for when you want it strict).

**Docs** lays out all 23 Annex IV sections, pre-fills only what the profile really knows, links each section to its
checklist item, and counts the sections still marked `TODO`. It never writes filler: a scaffold that says TODO in the
right place beats prose invented to fill a gap. A system relying on the Art. 6(3) derogation gets the Art. 6(4)
assessment-record template instead.

Eight example profiles in [`examples/act/`](examples/act/) cover every tier, including a claimed Article 5 exception
and a systemic-risk model. Details, sources and limits: [`docs/eu-ai-act-toolkit.md`](docs/eu-ai-act-toolkit.md).

> **Not legal advice, and only as good as the facts you declare.** Classification is a legal judgement that depends on
> facts and on guidance still being issued. The toolkit makes the structure explicit and auditable; it does not decide
> for you. Application dates are reproduced from a secondary source and may not reflect the final Official Journal text.

## It was tested on real code, and the first version was bad

v0.1 passed its own tests and flagged `asyncio.run` and minified JavaScript bundles on real
projects. Running it on 13 open-source and personal codebases, and reading every finding,
found 14 distinct defects that fixtures could not (a 15th, an order-dependent depth cap, was found later by CI on Linux). The write-up, with per-repo numbers and the
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
pytest          # 235 tests
```

The suite includes a negative control (a batch job that calls a chat API but is not an
interface), a regression test for each defect the real-world runs found, and an end-to-end
check that SARIF output is well formed.

## License

MIT
