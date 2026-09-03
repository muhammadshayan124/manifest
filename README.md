# manifest

Static analysis for [EU AI Act Article 50](https://artificialintelligenceact.eu/article/50/)
transparency obligations — applies from 2 August 2026. Scans a codebase for two things:

1. **Chatbot/AI-agent interfaces with no AI-disclosure language** (Article 50(1)) — a
   user-facing chat endpoint calling an LLM API, with nothing in the surrounding code
   telling the user they're talking to an AI.
2. **Generated-content pipelines with no watermarking/labeling step** (Article 50(2)/(4))
   — an image/audio/video generation call with no attempt to mark the output as
   machine-detectable AI-generated (the EU's draft Code of Practice on Transparency names
   [C2PA Content Credentials](https://c2pa.org/) as one such mechanism).

Every finding cites the exact provision it's checking against — see
[`src/manifest/article50.py`](src/manifest/article50.py) for the reference text this is
grounded in.

## What this doesn't do

**This is a code-review aid, not a compliance certificate.** A few things worth being
direct about:

- Static analysis can find a *candidate* pattern — an LLM call wired into what looks like
  a chat endpoint, a generation call with no nearby labeling code. It cannot verify a
  disclosure is actually *rendered* to a user at runtime, in a UI they'll actually see,
  before their first message. A `needs_review` result means "a disclosure signal exists
  somewhere nearby" — not "this is compliant." Confirm that yourself.
- It cannot verify a watermark is *effective* — that it survives re-encoding, cropping, or
  compression the way Article 50(2) requires ("effective, reliable, robust"). It can only
  tell you whether the code *attempts* something in that direction.
- The Python detectors use real AST parsing and are scoped to the enclosing function,
  which is precise but narrow — a disclosure shown via a totally separate code path (a
  frontend banner with no corresponding backend string, for instance) won't be seen. The
  JS/TS detector is regex-based and file-scoped, which trades precision for coverage of
  the other half of most LLM apps' stacks — see
  [`js_heuristic.py`](src/manifest/detectors/js_heuristic.py)'s docstring for why.
- A clean scan is not legal advice. Whether a given disclosure is "clear and
  distinguishable," or whether specific content counts as a "deepfake" under the Act's
  definition, are legal judgment calls this tool doesn't make. Talk to someone qualified
  before relying on a scan result for an actual compliance decision.

## Install

```bash
python -m venv .venv
./.venv/Scripts/pip install -e ".[dev]"
```

## Use

```bash
manifest scan path/to/your/project
manifest scan path/to/file.py --json                 # machine-readable output
manifest scan path/to/your/project --fail-on-findings # non-zero exit for CI
```

## Test

```bash
pytest
```

14 tests, including a negative control (`negative_control_batch_job.py`) that proves the
user-facing gating actually suppresses false positives on a non-user-facing LLM call, not
just that the detector fires on any LLM SDK usage.

## How detection works, briefly

Two signals have to both be true before anything gets flagged, deliberately, to keep
false positives down:

- **Chatbot detector**: the file imports a known LLM SDK (OpenAI, Anthropic, etc.) *and*
  a call matches a known chat-completion shape (`chat.completions.create`,
  `messages.create`, ...) *and* the enclosing function looks user-facing (a web-framework
  route decorator, or a function/class name containing "chat"/"bot"/"assistant"/
  "conversation"). A bare LLM call in a batch script with none of those signals is not
  flagged — Article 50(1) only applies to systems that interact directly with a natural
  person, and that's a real, deliberate scope boundary, not an oversight.
- **Generated-content detector**: same two-signal shape, checking for a generative-API
  call (image/audio/video generation) and a nearby labeling/watermarking-related term.

See [`article50.py`](src/manifest/article50.py) for the exact provisions cited, and the
`detectors/` module docstrings for the reasoning behind each detector's scope.
