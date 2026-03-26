# Changelog

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
