# ProductTeam

**A structured AI software delivery pipeline for small projects. Run free with local models or fast with cloud APIs.**

ProductTeam turns a product concept into a PRD, sprint plan, implementation passes, evaluation passes, and documentation. It is designed for supervised use, with state persistence, recovery tools, and optional approval gates. You describe a concept in plain English. Seven AI agents handle the stages — with three human approval gates where you confirm intent, scope, and readiness. Choose between free local AI (Ollama) or fast cloud APIs (Anthropic, OpenAI, Google Gemini) -- an interactive wizard helps you pick.

The builder never grades its own work. A separate, skeptical evaluator reads the code, runs the tests, and tries to break things. Code ships only when the evaluator says PASS — not when the builder says "done."

```bash
pip install productteam
```

Supports **Anthropic Claude**, **OpenAI**, **Ollama** (free, local), and **Google Gemini** through provider adapters. OpenAI-compatible local servers (LM Studio, vLLM) may work but depend on how closely they match the expected tool-calling API shapes.

![Tests](https://github.com/scottconverse/productteam/actions/workflows/test.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/productteam)
![Python](https://img.shields.io/pypi/pyversions/productteam)
![License](https://img.shields.io/pypi/l/productteam)

---

## Forge: Local Job Queue and Dashboard

Forge is a file-backed local job queue with a lightweight dashboard. Submit pipeline jobs from the CLI or dashboard, monitor progress, and inspect logs.

The daemon runs the full pipeline headlessly with auto-approve — PRD, plan, build, evaluate, document. Gates are bypassed in the current daemon path. Forge is best understood as a local batch runner and status UI, not a remote approval system. Remote gate approval is planned for a future release.

```bash
# Start the daemon + dashboard
productteam forge --listen --dashboard

# Dashboard: http://localhost:7654
```

Two ways to submit ideas: the dashboard UI or the CLI (`productteam forge "idea"`).

The dashboard is a zero-dependency single-page app served by Python's stdlib — no React, no build step, no npm. It shows job status, live log tailing, and job results.

---

## The Pipeline

```
You: "I want a tool that does X"
  │
  ▼
PRD Writer  →  Planner  →  Builder ↔ Evaluator  →  Doc Writer  →  Ship
                              (max 3 loops)
```

**Three approval gates** — you stop exactly three times:

| Gate | When | You Decide |
|------|------|-----------|
| PRD Approval | After PRD is written | "Does this capture my intent?" |
| Sprint Approval | After sprints are planned | "Does this scope look right?" |
| Ship Approval | After all evaluations pass | "Ready to push?" |

Everything between gates runs autonomously.

---

## The Core Insight: Separate the Builder from the Judge

Most AI coding tools let the agent build something and then declare it done. That's like letting a student grade their own exam.

ProductTeam uses a GAN-inspired architecture: the **Builder** writes code and declares "ready for review." The **Evaluator** — a separate agent with a separate prompt, separate context, and a skeptical default posture — reads the source, runs the tests, verifies acceptance criteria, and tries to break things. It grades PASS, NEEDS_WORK, or FAIL. If NEEDS_WORK, findings route back to the Builder automatically. Maximum 3 loops. After loop 3, the plan is wrong — not the implementation.

The Builder can never ship its own code. Only the Evaluator can.

---

## Thinker/Doer Architecture

Not all stages need the same capabilities. ProductTeam splits work into two cognitive modes:

**Thinker stages** (PRD Writer, Design Evaluator) take context in and produce a text artifact out. One LLM call. No filesystem access. Works with any provider.

**Doer stages** (Planner, Builder, UI Builder, Evaluator, Doc Writer) use an agentic tool-use loop with exactly four tools: `read_file`, `write_file`, `run_bash`, `list_dir`. The LLM calls tools, the supervisor executes them, results go back to the LLM, repeat until the agent finishes.

This means thinker stages are cheap and fast. Doer stages are powerful but cost more tokens. The split is deliberate — it's the difference between a meeting and a work session.

---

## The Doc Writer Reads Code. It Never Fabricates.

In 2026, hallucinated documentation is a real problem. ProductTeam's Doc Writer is a doer stage — it reads every source file via `read_file` before writing a single line of documentation. If a function doesn't exist in the code, it doesn't appear in the docs. READMEs, changelogs, and landing pages are generated from what the code actually does, not what the LLM imagines it does.

---

## Use Only What You Need

You don't have to run the full pipeline. Each agent is a standalone markdown skill file. Drop in the ones you need, skip the ones you don't.

Want just the Evaluator as a QA agent against your existing codebase? Use just that skill. Want the PRD Writer as a thinking tool without building anything? Use just that. Want the full pipeline? Run `productteam run`.

| Skill | Role | What It Does |
|-------|------|-------------|
| `prd-writer` | Product Manager | Converts concept to structured PRD |
| `planner` | Tech Lead | Decomposes PRD into sprint contracts |
| `builder` | Engineer | Implements code via tool-use loop |
| `ui-builder` | Frontend Engineer | Builds visual artifacts via tool-use loop |
| `evaluator` | QA Engineer | Verifies code against sprint contract |
| `evaluator-design` | Design Reviewer | Grades visual work on 4 dimensions |
| `doc-writer` | Technical Writer | Writes README, docs, changelog from code |
| `orchestrator` | Project Manager | Routes work, manages loops and gates |

---

## Two Ways to Run

ProductTeam supports two AI paths. The interactive wizard (`productteam` with no arguments) walks you through selecting one.

| | Local AI (Ollama) | Cloud AI |
|---|---|---|
| **Cost** | Free | Standard API costs |
| **Speed** | ~20 min/step | Faster with cloud models |
| **Setup** | Install Ollama, pull a model | Set an API key |
| **Recommended models** | gpt-oss:20b (primary), devstral:24b (backup) | Claude Haiku, GPT-4o-mini, Gemini Flash |
| **Providers** | Ollama | Anthropic, OpenAI, Google Gemini |
| **Internet required** | No | Yes |

**Local models are free but slower.** Each pipeline step takes roughly 20 minutes on a 20B parameter model, so a full project takes hours. Cloud APIs are significantly faster.

When using Ollama, ProductTeam auto-tunes for local execution: timeouts are increased, design review is skipped, and approval gates are set to auto-approve.

---

## Quick Start

```bash
# Install
pip install productteam

# Launch the interactive wizard (recommended)
productteam
```

The wizard walks you through everything: describe your concept, choose Local AI or Cloud AI, and go. It remembers your last choice -- one keystroke to reuse it next time.

Cloud API keys are stored locally in `~/.productteam/prefs.json` and never sent anywhere except to the provider you chose.

**Power-user alternative** -- skip the wizard and run directly:

```bash
# Set up your provider (pick one)
export ANTHROPIC_API_KEY=sk-ant-...     # Anthropic
export OPENAI_API_KEY=sk-...            # OpenAI
# Or use Ollama (free, local): ollama serve

# Initialize a project
productteam init

# Configure your provider
productteam config set pipeline.provider anthropic
# Or: openai, ollama, gemini

# Run the full pipeline
productteam run "a CLI tool that estimates LLM API costs"

# Resume from where you left off
productteam run

# Recover a stuck pipeline
productteam recover

# Check your environment
productteam doctor

# Test if an Ollama model can run the pipeline
productteam preflight
```

---

## Safety and Recovery

ProductTeam runs LLM-generated shell commands on your machine. That's inherently risky. Here's how it's mitigated:

**Path validation** — All file operations are locked to the project directory. No `../` traversal, no absolute paths.

**Environment isolation** — Builder subprocesses receive a minimal allowlisted environment (PATH, HOME, TMP, locale). API keys, tokens, and credentials from the parent process are not forwarded. A `PRODUCTTEAM_SANDBOXED=1` marker is set.

**Command filtering** — Known credential-adjacent paths (`.ssh/`, `.aws/`, `/proc/environ`) are blocked. Note: `run_bash` falls back to `shell=True` when commands use pipes, redirects, or other shell features. This is a convenience tradeoff — the command denylist provides defense-in-depth but is not a hard sandbox boundary.

**Loop detection** — If the LLM calls the same tool with identical arguments three consecutive times, the loop breaks automatically.

**Tool call limits** — Maximum 75 tool calls per doer run (configurable). After that, the stage stops and escalates.

**State persistence** — `state.json` is written on every state change. Crash at any point, resume with `productteam run`. If a stage gets stuck, `productteam recover` resets it and re-enters the pipeline.

**Timeouts** — Every stage has a configurable timeout. Default: 300s for thinkers, 600s for doers.

---

## CLI Reference

| Command | What It Does |
|---------|-------------|
| `productteam` | Launch the interactive wizard |
| `productteam preflight` | Test whether an Ollama model can run the pipeline |
| `productteam init` | Initialize a project directory |
| `productteam run "concept"` | Run the full pipeline |
| `productteam run` | Resume from current state |
| `productteam run --auto-approve` | Headless / CI mode |
| `productteam run --budget 1.50` | Set cost limit (default $2.00) |
| `productteam run --step prd` | Run only a specific stage |
| `productteam recover` | Reset stuck stages and re-run |
| `productteam status` | Show pipeline status |
| `productteam doctor` | Check environment and config |
| `productteam config set KEY VALUE` | Set configuration |
| `productteam test` | Run the test suite |
| `productteam test --live` | Run live integration tests |
| `productteam forge "idea"` | Submit an idea to the Forge queue |
| `productteam forge --listen --dashboard` | Start the Forge daemon + dashboard |
| `productteam forge status [JOB-ID]` | Check job status |

---

## Cost

**ProductTeam can run entirely free using Ollama.** No API key, no cloud account, no bill. Local models are slower (~20 min per pipeline step, so a full project takes hours) but cost nothing.

For cloud APIs, ProductTeam makes LLM calls at every pipeline stage. Cloud runs are deeper and faster but incur standard API access costs. Actual cost depends on concept complexity, quality level, and model choice.

| Path | Model | Est. Cost |
|------|-------|-----------|
| Local AI | Ollama (gpt-oss:20b) | Free |
| Cloud AI | Claude Haiku | Standard API costs |
| Cloud AI | Claude Sonnet | Standard API costs |

Costs scale with:
- **Concept complexity** — more features = more sprints = more tokens
- **Quality level** — `strict` costs 3-5x more than `standard`
- **Model choice** — Haiku is ~4x cheaper than Sonnet per token

**Cost circuit breaker (v2.5.5+):**
The `--budget` flag sets a hard dollar limit on a pipeline run. When cumulative cost exceeds the limit, `BudgetExceededError` kills the pipeline mid-loop and saves all work to disk. Default: $2.00.

```bash
productteam run "my idea" --budget 1.50   # kill if cost exceeds $1.50
```

You can also set it permanently in `productteam.toml`:

```toml
[pipeline]
budget_usd = 2.00
```

**To minimize cost:**
- Use `quality = "standard"` in `productteam.toml` (default)
- Use Haiku or a local Ollama model for development iteration
- Use `productteam run --dry-run` to estimate cost before running
- Use Sonnet with `quality = "thorough"` for release candidates

**To see what you spent:**
After each run, ProductTeam prints token usage and estimated cost.

---

## Configuration

All configuration lives in `productteam.toml`:

```toml
[pipeline]
provider = "anthropic"          # anthropic | openai | ollama | gemini
model = "claude-sonnet-4-6"
max_loops = 3                   # build-evaluate iterations (increase for complex features)
max_sprints = 8                 # max sprint contracts
quality = "standard"            # standard | thorough | strict (controls eval depth + cost)
builder_max_tool_calls = 75     # tool call limit per doer run
budget_usd = 2.00               # cost circuit breaker (kills pipeline if exceeded)
auto_approve = false            # true for headless/CI mode
auto_install_deps = false       # auto pip install project deps (runs install-time code)

[gates]
prd_approval = true
sprint_approval = true
ship_approval = true

[forge]
queue_backend = "file"          # file-backed local queue
notification_backend = "none"   # none | webhook
status_host = "127.0.0.1"      # default: localhost only
status_port = 7654
```

---

## Who This Is For

**Solo founders and indie hackers** who can describe a product but want structured, auditable AI execution instead of chatting with a coding assistant.

**Small product teams** who want an opinionated delivery pipeline — PRD → Sprint → Build → Evaluate → Document → Ship — with human gates at every strategic decision point.

**Anyone who's tired of AI coding tools that grade their own homework.** The evaluator loop is the difference between "the AI said it's done" and "the AI proved it works."

---

## What This Is Not

This is not an IDE plugin. It's not autocomplete. It's not a chatbot you pair-program with.

This is a supervised pipeline that produces a project directory with code, tests, and documentation. You interact at three gates in interactive mode, or run headlessly with `--auto-approve`. Human review of output is expected.

Best suited today for small greenfield projects and tightly scoped feature work (1-10 files per sprint, up to 8 sprints) where shell execution inside the project directory is acceptable.

---

## License

MIT

## Author

Scott Converse
