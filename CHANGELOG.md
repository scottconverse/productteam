# Changelog

## [2.1.0] - 2026-03-26

### Changed
- **Planner reclassified as doer** — now uses the tool loop to write sprint YAML files directly to `.productteam/sprints/` via `write_file`. Previously a thinker that produced correct YAML as text but couldn't write to disk, causing the build loop to silently skip.
- **PRD Writer runs headlessly** — detects automated context and skips clarifying questions and review phases. Applies sensible defaults instead of asking 7 questions nobody will answer.
- **Planner runs headlessly** — proceeds without asking for human confirmation in auto-approve mode.
- **Sprint scoping tightened** — "large" scope banned, only small (1-3 files) and medium (4-8 files) allowed. Sprints must be completable in 30-40 tool calls. 10KB YAML size limit.
- **Design Evaluator** — single-pass evaluation with clear escalation instead of fake retry loop that couldn't route back to Doc Writer.
- Timeout defaults bumped: stage 120→300s, builder 300→600s, new `planner_timeout_seconds` (600s)
- `_run_tool_loop_stage` accepts optional `timeout_seconds` override
- Thinker/doer classification updated across README, landing page, and architecture SVG

### Added
- `max_sprints` config field (default 8) — bounds the number of sprint contracts the Planner produces, making timeout predictable
- `planner_timeout_seconds` config field (default 600) — separate timeout for the Planner's multi-file tool loop
- Loud failure when no sprint YAML files found after plan completes (was a silent skip)
- Doc Writer guard — skips when no sprints have passed evaluation
- `require_evaluator` config field now wired — when false, build loop auto-passes without evaluation
- GatesConfig fields wired — `prd_approval`, `sprint_approval`, `ship_approval` individually control their respective gates
- `_read_artifact` warns on missing artifact path or file
- Schema version validated on `state.json` load
- `handoffs/` directory created by `init_project`
- PRD Writer Rule 10: no invented product names — uses placeholder `[PRODUCT NAME]` when concept doesn't specify one

### Fixed
- `os.system()` replaced with `asyncio.create_subprocess_exec` in `_gate`
- `run_bash` credential filtering hardened — blocks `env | grep`, `/proc/environ`, `echo $SECRET`; fixes `poetry env use` false positive; constants moved to module level
- `read_file` 100KB size cap with truncation notice
- Doer stages now use `builder_timeout_seconds` (was incorrectly using `stage_timeout_seconds`)
- Doc Writer stuck status was silently ignored — now gates pipeline
- Context summarizer includes MEDIUM findings (was CRITICAL/HIGH only)
- Evaluator SKILL.md paths fixed: `.claude/` → `.productteam/`

### Infrastructure
- Publish workflow runs tests before build (pytest gate)
- Test workflow adds `--cov --cov-fail-under=80` and Python 3.13
- 225 unit tests + 6 live integration tests passing

### Known Issues
- Planner sprint sizing needs calibration — produces 9-15KB sprints with 20-31 deliverables; target is 5-8 deliverables under 6KB. Tracked for next session.

## [2.0.2] - 2026-03-26

### Changed
- **Evaluator reclassified as doer** — now runs via tool loop with file access and test execution, instead of receiving only the Builder's text summary
- **Doc Writer reclassified as doer** — now reads actual source files before writing documentation, instead of hallucinating from the concept string alone
- Thinker/doer table updated in README, landing page, and architecture SVG to reflect new classifications
- Architecture SVG reorganized: thinker section (3 agents), doer section (4 agents) with shared tool sandbox

### Added
- `productteam test` command — runs offline unit tests by default
- `productteam test --live` — runs live integration tests against real APIs with safety warnings (masked API key display, cost warning panel, cheapest-model default)
- `_run_tool_loop_stage()` method in Supervisor for dispatching doer stages
- 6 live integration tests (provider smoke, thinker stage, tool loop read/write, build-evaluate round-trip)
- 19 dashboard endpoint tests (`/api/submit` happy path, empty concept, oversized body, malformed header, approve/reject, job listing)
- 5 full pipeline integration tests (multi-sprint end-to-end, fail-stops-pipeline, resume-skips-completed, sprint sequencing)
- `tests/conftest.py` with shared `live_provider` and `live_project` fixtures
- `live` pytest marker for API-calling tests

### Fixed
- XSS vulnerability in dashboard — all user-supplied values now escaped via `escapeHtml()` before innerHTML insertion
- Content-Length cap (4KB) and validation on `/api/submit` — malformed headers return 400, oversized bodies return 413
- Missing `import os` in supervisor.py — `_gate()` edit mode no longer crashes with NameError
- Operator precedence bug in `_run_single_step` — `sprint` arg no longer silently ignored when sprint list is empty
- Sprint path mismatch — Builder skill now uses `.productteam/sprints/` matching the Supervisor
- `builder_timeout_seconds` now wired into `run_tool_loop()` via `stage_timeout_seconds`
- Design evaluation stage now invoked in `Supervisor.run()` when `require_design_review` is enabled
- LAN IP detection uses UDP socket method instead of unreliable `socket.gethostbyname()`
- Removed unused `import time` from supervisor.py

### Meta
- Test count: 207 unit tests + 6 live integration tests (up from ~150)
- Version synced across pyproject.toml, `__init__.py`, docs/index.html, docs/architecture.svg

## [2.0.1] - 2026-03-26

### Added
- Dashboard submit form — submit Forge ideas from any device on your LAN via `http://<your-ip>:7654`
- Dashboard binds to `0.0.0.0` by default (configurable via `[forge] status_host`)
- `/api/submit` endpoint on Forge dashboard
- Technical architecture requirement added to doc-writer skill — all products now produce an architecture SVG and component descriptions

### Changed
- Version bumped to 2.0.1 across all files

## [2.0.0] - 2026-03-26

### Added
- Multi-provider LLM abstraction layer (Anthropic, OpenAI, Ollama, Gemini)
- Supervisor agent — real pipeline orchestration with `productteam run`
- Thinker/doer architecture — single API calls for planning stages, tool-use loop for builder stages
- Tool-use loop (`tool_loop.py`) — 4 tools (read_file, write_file, run_bash, list_dir) with security constraints
- Forge — phone-to-product pipeline with file queue, daemon, dashboard, and notifications
- `productteam doctor` — 11-check diagnostic command with `--json` and `--no-network` flags
- Incremental rebuilds — skip passed sprints, `--rebuild` flag for force rebuild
- State persistence via `state.json` with resume capability
- Stuck detection — timeout, loop detection, max tool call limits
- Approval gates with interactive y/N/edit prompt
- Architecture SVG diagram (`docs/architecture.svg`)
- Landing page with CLI commands, Forge section, Design Evaluator panel, provider badges
- GitHub Actions workflows for testing and PyPI publishing
- Comprehensive test suite (10 test files)

### Changed
- `productteam run` now executes the full pipeline (previously printed manual instructions)
- README rewritten with full CLI reference, thinker/doer documentation, and architecture section
- Doc-writer skill updated to require technical architecture section for all products
