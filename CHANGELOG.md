# Changelog

## [2.5.7] - 2026-03-27

### Fixed
- Version sync: all 5 version locations now consistent (was 2.5.4 in __init__.py and architecture.svg while other files said 2.5.6)

## [2.5.6] - 2026-03-27

### Fixed
- **Budget breaker cost formula now includes cached tokens** — Cost calculation now accounts for `cache_creation_input_tokens` (1.25x rate) and `cache_read_input_tokens` (0.1x rate), not just `input_tokens`. Without this fix, the budget breaker saw ~$0 when caching was active because `input_tokens` drops to ~300 once the cache is warm.
- **All remaining skill files padded above cache threshold** — Planner, prd-writer, doc-writer, and evaluator-design skill files now exceed the 4,096 token minimum required for Anthropic prompt caching. Previously only builder and evaluator were padded.

## [2.5.5] - 2026-03-27

### Added
- **`--budget` CLI flag with cost circuit breaker** — Sets a maximum dollar spend for a pipeline run (default: $2.00). When cumulative cost exceeds the limit, `BudgetExceededError` kills the pipeline mid-loop. All work completed so far is saved to disk. Configurable via `budget_usd` in `productteam.toml`.
- **Cache threshold validation on startup** — Pipeline refuses to run if skill prompts are below the model's minimum cacheable token count (4,096 for Haiku 4.5, 1,024 for Sonnet). Prevents silent cache misses that inflate costs.
- **23 new tests for cost controls** — Budget breaker, cache threshold validation, and BudgetExceededError behavior.

### Changed
- **Builder and evaluator skill files padded** — Skill files padded with useful reference content to exceed cache thresholds, ensuring prompt caching activates on every call.

## [2.5.4] - 2026-03-27

### Added
- **`_setup_project_env()` on Supervisor** — Creates `.venv` and installs project dependencies (via `pip install -e .` or `pip install -r requirements.txt`) before agent stages run. Zero token cost. Eliminates the $13 eval loop problem where agents burned hundreds of tool calls trying to install packages themselves.
- **Prompt caching enabled** — Anthropic API requests now send system prompts with `cache_control: {"type": "ephemeral"}`. Calls 2-75 in a tool loop hit cache on the system prompt, reducing input token costs ~88% on repeated calls.

### Changed
- **Evaluator loop detection tightened to 3** — With deps pre-installed, the evaluator has no reason to make 5 identical calls. Reverted to window of 3 for evaluator stages, kept 8 for doc writer, 5 for builder.
- **Builder and evaluator skills no longer install deps** — Skills updated to say "do not run pip install" since the Supervisor handles it. Prevents double-install and wasted tool calls.

## [2.5.3] - 2026-03-27

### Fixed
- **Evaluator installs dependencies before testing** — Evaluator was running `pytest` without installing project dependencies, getting `ModuleNotFoundError`, returning NEEDS_WORK, triggering infinite build-evaluate loops. Now installs deps exactly once via `pip install -e .` or `pip install -r requirements.txt` before running tests. Same fix applied to Builder skill.
- **Supervisor injects dependency hint into eval prompt** — When `requirements.txt`, `pyproject.toml`, or `setup.py` exists, the evaluator prompt now includes an explicit instruction to install dependencies before testing.
- **Evaluator max tool calls raised to 25** — With dep installation + test execution + file reads, 15 calls was too tight for standard quality. Raised to 25 to accommodate the install-then-test workflow.

## [2.5.2] - 2026-03-27

### Fixed
- **Build stage token counts now correctly accumulated** — `_build_evaluate_loop` was creating `StageResult` objects without populating token counts from inner `ToolLoopResult`. Builder + evaluator tokens are now summed across all loops.
- **Design evaluator now respects quality level** — Quality gate (`standard`/`thorough`/`strict`) was injected into the build evaluator but not the design evaluator. Design eval was running full adversarial evaluation (791K input tokens) regardless of quality setting. Now gated, with `standard` targeting 8-12 tool calls.
- **Doc writer loop detection window increased** — Loop detection was triggering after 3 consecutive identical calls, too aggressive for the doc writer which legitimately reads the same file multiple times. Default window increased from 3 to 5, with doc writer using 8. Window is now configurable via `loop_detection_window` parameter.
- **Box-drawing characters banned from evaluator reports** — Design evaluator now instructed to use plain YAML only. Box-drawing characters caused Windows encoding errors and inflated token counts.
- **Cache hit fields now tracked** — Anthropic provider now extracts `cache_creation_input_tokens` and `cache_read_input_tokens` from the SDK response. These propagate through `ToolLoopResult`, `StageResult`, and appear in the post-run cost summary.

## [2.5.0] - 2026-03-27

### Added
- **Conversation history truncation** — Tool loops now keep only the initial task + last 10 exchanges when calling the LLM. Prevents O(n²) token growth that was the root cause of $57 pipeline runs. Total input tokens reduced ~7x for a typical 75-call loop.
- **Token tracking** — All providers now return input/output token counts. `ToolLoopResult`, `StageResult`, and `SupervisorResult` accumulate tokens. Post-run summary shows total tokens and estimated cost.
- **Cost estimate in `--dry-run`** — `productteam run --dry-run` now prints estimated token usage and cost for each supported model before making any API calls.
- **Quality levels** — New `quality` config option (`standard`/`thorough`/`strict`) controls evaluator depth. `standard` (default) skips adversarial testing and aims for 10-15 tool calls. `strict` preserves the old full-adversarial behavior.
- **Cost section in README** — Documents expected costs, cost-saving tips, and model comparison.

### Changed
- **`builder_max_tool_calls` reverted to 75** — The raise to 150 was the wrong fix for the token growth problem. With truncation, 75 is correct.

### Fixed
- **`run_bash` subprocess encoding** — Uses `encoding="utf-8"` explicitly, fixing Windows `UnicodeDecodeError` on LLM output with Unicode characters.

## [2.4.4] - 2026-03-27

### Fixed
- **Verdict parsing priority** — Evaluator's final text verdict now overrides earlier YAML verdicts. Fixes pipeline getting stuck when evaluator writes NEEDS_WORK in early analysis YAML but concludes PASS in final text.
- **Verdict pattern matching** — `_parse_verdict` now matches any "verdict:" line format (not just YAML keys), catching "VERDICT: PASS" prose.
- **Builder max_calls proceeds to evaluation** — When builder hits tool call limit, the evaluator now assesses partial work instead of the pipeline stopping cold.
- **subprocess UTF-8 encoding** — `run_bash` now uses `encoding="utf-8"` explicitly, fixing `UnicodeDecodeError` on Windows when LLM output contains box-drawing/emoji characters.
- **builder_max_tool_calls raised to 150** — Previous default of 75 was insufficient for complex sprints.

### Reverted
- **FAIL verdict stays terminal** — Reverted attempt to make FAIL retry. FAIL means "re-plan, don't re-build."
- **Doc/design stages stay terminal on stuck** — Reverted silent partial completion. Stuck means stuck.

## [2.4.3] - 2026-03-27

### Fixed
- **Build-evaluate FAIL retry** — FAIL verdict on non-final loops now retries with evaluator feedback instead of terminating immediately. Only the final loop's FAIL is terminal.
- **Evaluator feedback passed to builder** — Builder now receives the evaluator's previous feedback on retry loops, enabling targeted fixes instead of blind rebuilds.
- **Doc writer project orientation** — Doc writer now receives a file listing of the project, preventing it from exploring wrong paths (`/tmp`, `/root`) and getting stuck in write loops.

## [2.4.2] - 2026-03-26

### Added
- **`bump_version.py`** — Script to update version across all 5 locations from a single argument. Prevents stale version strings.
- **`CONTRIBUTING.md`** — Dev setup, test running, PR guidelines for open source contributors.
- **`doc_writer_max_tool_calls` config** — Separate tool call limit for the doc_writer stage (default: 100), independent of builder_max_tool_calls (75). Doc writer needs more calls to read all source files before writing docs.

### Fixed
- **Ollama tool-use round-trips** — Ollama provider now converts Anthropic-format tool_use/tool_result messages to Ollama's native format. Fixes 400 errors on multi-turn tool loops.

## [2.4.1] - 2026-03-26

### Security
- **Dashboard binds to 127.0.0.1 by default** — Previously bound to 0.0.0.0, exposing the unauthenticated dashboard to the local network. Added `--lan` flag to opt into LAN access with a printed warning.
- **run_bash defaults to shell=False** — Uses `shlex.split()` to prevent shell injection from LLM-constructed commands. Falls back to `shell=True` only when shell features (pipes, redirects, chains) are detected.
- **Write restrictions on .claude/ and .productteam/** — Builder can no longer write to `.claude/` (agent prompt rewriting) or `.productteam/` (pipeline state corruption). Exception: `.productteam/sprints/` remains writable for Planner.
- **Dependencies pinned to exact versions** — All runtime dependencies use `==` instead of `>=` ranges to prevent supply chain attacks via compromised upstream packages.

### Fixed
- **Ollama tool-use round-trips** — Ollama provider now converts Anthropic-format tool_use/tool_result messages to Ollama's native format (role: "tool", tool_calls). Fixes 400 errors on multi-turn tool loops.

## [2.3.2] - 2026-03-26

### Changed
- **Updated README** — Rewrote for public release: clearer structure, Forge headline feature, safety section, CLI reference, configuration guide.
- **Updated landing page** — New `docs/index.html` with Forge hero section, pipeline visualization, comparison table, and getting started guide.
- **Updated PyPI description** — Now matches the README tagline.

## [2.3.1] - 2026-03-26

### Fixed
- **Architecture SVG not rendering on PyPI** — README used a relative path (`docs/architecture.svg`) which doesn't resolve on PyPI. Changed to absolute GitHub raw URL.

## [2.3.0] - 2026-03-26

### Added
- **Forge daemon stage visibility** — `Supervisor.run()` accepts a `stage_callback` parameter. The Forge daemon passes a callback that updates `current_stage` in the queue at the start of each stage, so the dashboard shows real-time pipeline progress instead of `"-"` throughout the run.
- **Configurable skills directory** — `skills_dir` field in `[pipeline]` config (default: `.claude/skills`). Users who move their skills directory or use non-standard layouts can set this in `productteam.toml`. Error messages now suggest checking `skills_dir` when a skill is not found.
- **Design evaluator verdict disk fallback** — when the design evaluator's text response has no parseable verdict, the supervisor checks `eval-*-design.yaml` files on disk. Same pattern as the build evaluator fallback added in v2.2.0. Fixes pipelines reporting "stuck" when the design evaluation actually passed.

### Fixed
- **`run_bash` WinError production handling** — `_execute_tool` now catches `OSError` separately from generic exceptions, returning a structured JSON error with a descriptive message instead of an opaque crash on Windows when subprocess handles are invalid.
- **Windows credential filter gaps** — `_validate_command` now blocks PowerShell (`$env:`, `Get-ChildItem Env:`) and .NET (`[System.Environment]::GetEnvironmentVariable`) environment access patterns, matching the existing Unix credential filters.
- **`run_bash` tests on Windows** — `test_execute_run_bash` and `test_execute_run_bash_timeout` now use `python -c` on Windows instead of `echo`/`sleep` which depend on Unix shell builtins. Tests pass on all platforms.
- **Doc Writer termination validated** — the prompt-based termination instruction ("stop after writing all files") was confirmed working under live conditions. The Doc Writer exits naturally within the stage timeout. No `max_tool_calls` cap was needed.

### Infrastructure
- 270 unit tests passing on Windows and Linux (up from 239)
- Coverage restored to 80% (was 75.8%): mocked provider `complete_with_tools` tests for Gemini/Ollama/OpenAI, supervisor error path and artifact tests, credential filter tests
- CI matrix expanded: Windows (`windows-latest`) added alongside Ubuntu for all Python versions
- Windows credential filter tests added for PowerShell and .NET environment access patterns
- Full pipeline validated end-to-end with fresh `productteam init` + `productteam run` on the bmark reference project

## [2.2.0] - 2026-03-26

### Added
- **`productteam recover` command** — reads state.json, identifies stuck/running stages, resets them to pending, re-enters pipeline at the stuck stage. Supports `--yes` for non-interactive use. Replaces manual state.json editing after timeouts.
- **Planner sprint sizing examples** — SKILL.md now includes 2 concrete examples of correctly-sized sprints (small + medium) and an anti-pattern example. Establishes 5-8 deliverable floor/ceiling per sprint.
- **Verdict parsing disk fallback** — when the Evaluator's text response has no parseable verdict, the supervisor checks `.productteam/evaluations/*.yaml` files written by the Evaluator via write_file. Prevents every sprint returning needs_work when the Evaluator writes structured YAML to disk but its text summary lacks the verdict key. **Note:** This bug existed since the Evaluator became a doer stage in v2.1.0. Any evaluation verdicts from live runs prior to this fix are unreliable — the Evaluator may have written PASS to disk while the supervisor recorded needs_work.
- **Builder tool budget guidance** — SKILL.md now includes explicit budget: write all files first, test once, then fix. Prevents the Builder from spending all tool calls on exploration.

### Changed
- `builder_max_tool_calls` default raised from 50 to 75 — 50 was too tight for real sprints with test-fix cycles
- Planner YAML size limit tightened from 10KB to 6KB
- Planner deliverable definition tightened: "one file with one purpose" — not a subsystem or feature area
- `run_bash` tool description updated: tells the model Python/pip are available on PATH

### Fixed
- **`run_bash` Python PATH injection** — Python executable directory and project `.venv/Scripts` (or `bin` on Linux/macOS) added to subprocess PATH. Fixes Windows environments where bash shells (MSYS2/Git Bash) can't find Python. Cross-platform safe.
- Inline `import sys` in tool_loop.py moved to module level

### Infrastructure
- 231 unit tests + 6 live integration tests passing
- Verdict disk fallback covered by `test_build_evaluate_disk_fallback_finds_pass`
- Recover command covered by 5 tests (no state, no concept, no stuck, identifies stuck, resets with --yes)

## [2.1.0] - 2026-03-26

### Changed
- **Planner reclassified as doer** — now uses the tool loop to write sprint YAML files directly to `.productteam/sprints/` via `write_file`. Previously a thinker that produced correct YAML as text but couldn't write to disk, causing the build loop to silently skip.
- **PRD Writer runs headlessly** — detects automated context and skips clarifying questions and review phases. Applies sensible defaults instead of asking 7 questions nobody will answer.
- **Planner runs headlessly** — proceeds without asking for human confirmation in auto-approve mode.
- **Sprint scoping tightened** — "large" scope banned, only small (1-3 files) and medium (4-8 files) allowed. Sprints must be completable in 30-40 tool calls. 6KB YAML size limit.
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
- 231 unit tests + 6 live integration tests passing

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
