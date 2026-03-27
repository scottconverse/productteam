# ProductTeam

**Your AI product team. Describe what you want. Wake up to shipping code.**

ProductTeam is an autonomous software delivery pipeline. You describe a product concept in plain English. Eight specialized AI agents write the PRD, plan the sprints, build the code, evaluate the results, write the docs, and ship — with three human approval gates where you confirm intent, scope, and readiness.

The builder never grades its own work. A separate, skeptical evaluator reads the code, runs the tests, and tries to break things. Code ships only when the evaluator says PASS — not when the builder says "done."

```bash
pip install productteam
```

Works with **Anthropic Claude**, **OpenAI**, **Ollama** (free, local), **Google Gemini**, **LM Studio**, and **vLLM**. No vendor lock-in. No Claude Code required.

![Tests](https://github.com/scottconverse/productteam/actions/workflows/test.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/productteam)
![Python](https://img.shields.io/pypi/pyversions/productteam)
![License](https://img.shields.io/pypi/l/productteam)

---

## Forge: Submit From Your Phone, Ship While You Sleep

**This is the headline feature.** Start the Forge daemon on your workstation. Open the dashboard on your phone. Type a product idea. Hit "Forge it." Go to bed.

The daemon runs the full pipeline headlessly — PRD, plan, build, evaluate, document. When a gate needs your approval, you get a Slack notification (or webhook). Tap approve on your phone. The pipeline continues. You wake up to a built, tested, documented codebase.

```bash
# Start the daemon + dashboard
productteam forge --listen --dashboard --lan

# Dashboard: http://localhost:7654
# From phone: http://192.168.1.42:7654
```

Three ways to submit ideas: your phone's browser, the CLI (`productteam forge "idea"`), or a GitHub Issue with the `productteam-forge` label.

The dashboard is a zero-dependency single-page app served by Python's stdlib — no React, no build step, no npm. It shows job status, live log tailing, and approve/reject buttons for every gate.

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

## Quick Start

```bash
# Install
pip install productteam

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
```

---

## Safety and Recovery

ProductTeam runs LLM-generated shell commands on your machine. That's inherently risky. Here's how it's mitigated:

**Path validation** — All file operations are locked to the project directory. No `../` traversal, no absolute paths.

**Credential isolation** — Sensitive environment variables (`*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `AWS_*`) are stripped from the subprocess environment before commands run. The Builder cannot read your API keys.

**Command filtering** — Known credential-adjacent paths (`.ssh/`, `.aws/`, `/proc/environ`) are blocked.

**Loop detection** — If the LLM calls the same tool with identical arguments three consecutive times, the loop breaks automatically.

**Tool call limits** — Maximum 75 tool calls per doer run (configurable). After that, the stage stops and escalates.

**State persistence** — `state.json` is written on every state change. Crash at any point, resume with `productteam run`. If a stage gets stuck, `productteam recover` resets it and re-enters the pipeline.

**Timeouts** — Every stage has a configurable timeout. Default: 300s for thinkers, 600s for doers.

---

## CLI Reference

| Command | What It Does |
|---------|-------------|
| `productteam init` | Initialize a project directory |
| `productteam run "concept"` | Run the full pipeline |
| `productteam run` | Resume from current state |
| `productteam run --auto-approve` | Headless / CI mode |
| `productteam run --step prd` | Run only a specific stage |
| `productteam recover` | Reset stuck stages and re-run |
| `productteam status` | Show pipeline status |
| `productteam doctor` | Check environment and config |
| `productteam config set KEY VALUE` | Set configuration |
| `productteam test` | Run the test suite |
| `productteam test --live` | Run live integration tests |
| `productteam forge "idea"` | Submit an idea to Forge |
| `productteam forge --listen --dashboard` | Start the Forge daemon |
| `productteam forge status [JOB-ID]` | Check job status |
| `productteam forge approve JOB-ID` | Approve a gate |

---

## Configuration

All configuration lives in `productteam.toml`:

```toml
[pipeline]
provider = "anthropic"          # anthropic | openai | ollama | gemini
model = "claude-sonnet-4-6"
max_loops = 3                   # build-evaluate iterations (increase for complex features)
max_sprints = 8                 # max sprint contracts
builder_max_tool_calls = 75     # tool call limit per doer run
auto_approve = false            # true for headless/CI mode

[gates]
prd_approval = true
sprint_approval = true
ship_approval = true

[forge]
queue_backend = "file"          # file | github_issues
notification_backend = "none"   # none | webhook | slack
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

This is an autonomous pipeline that runs in the background and produces a project directory with code, tests, and documentation. You interact at three gates. Everything else is automatic.

For small-to-medium projects (1-10 files per sprint, up to 8 sprints), it works well today. For large enterprise codebases with 30+ existing modules, you'll want to wait for the vector search integration in v3.

---

## License

MIT

## Author

Scott Converse
