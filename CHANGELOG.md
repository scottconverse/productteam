# Changelog

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
