# ProductTeam — Future Features & Known Debt

Items tracked for future releases. Nothing here is blocking v2.3.x.

---

## v3.0 — Security Hardening

Source: PE security review, March 2026.

These changes harden the tool loop sandbox without reducing the Builder's ability to build software. Ordered by priority.

### 1. `shell=False` in `run_bash` subprocess

**Current:** `subprocess.run(command, shell=True)` — the command string is interpreted by the shell, enabling injection if the LLM constructs a command with metacharacters in user-supplied values.

**Fix:** Switch to `shell=False` with `shlex.split()`. Commands using shell features (pipes, redirects, `&&` chains) need detection and either splitting into separate calls or an explicit fallback to shell mode with a logged warning.

**Cost:** None for normal commands. Shell-feature commands need parsing.

### 2. Strip credentials from subprocess environment

**Current:** `run_bash` inherits the full environment including `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AWS_*`, `GH_TOKEN`, etc. Any command the Builder runs can read them.

**Fix:** Build a sanitized env copy before launching subprocesses. Strip variables matching `*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `AWS_*`. Log which variables were stripped (not their values) for debugging. The pipeline itself still accesses keys through the provider layer.

**Cost:** None. The Builder doesn't need API keys to write Python or run tests. Opt-in exceptions for specific variables can be added via config if a build tool legitimately needs credentials (e.g., private package registries).

### 3. Write restrictions on `.claude/` and `.productteam/`

**Current:** `write_file` can write anywhere in the project directory, including `.claude/skills/*.md` (rewriting agent prompts for the next run) and `.productteam/state.json` (corrupting pipeline state).

**Fix:** Block writes to `.claude/` and `.productteam/` from the tool loop. Exception: the Planner needs write access to `.productteam/sprints/` — allowlist that specific path.

**Cost:** None for normal building. Prevents a compromised or confused LLM from modifying its own instructions.

### 4. `read_file` path restrictions

**Current:** `_validate_path` checks for `../` traversal but doesn't restrict reads within the project directory. If the project root is set broadly, the Builder can read `~/.ssh/config`, `~/.aws/credentials`, or `.env` files.

**Fix:** Restrict `read_file` to the project directory tree. Block reads of known sensitive patterns (`.env`, `*.pem`, `*.key`, `credentials*`) unless explicitly allowlisted.

### 5. Tiered command allowlist for `run_bash`

**Current:** Any command is allowed as long as it passes the credential filter denylist. The Builder can run arbitrary system commands.

**Fix:** Two modes:
- **Default (safe):** Allowlist of common build operations — `python`, `pip`, `npm`, `cargo`, `go`, `make`, `pytest`, `git` (read-only). Anything else prompts for approval or is blocked.
- **Unrestricted:** Current behavior, enabled via `productteam.toml` with a clear warning. For projects that need `docker build`, `alembic`, or ecosystem-specific tooling.

**Cost:** Real tradeoff. Default mode limits generality. The tiered approach preserves it as an opt-in.

---

## Test Coverage Gaps

Current: 80.2% (272 tests). These are the remaining untested areas.

### cli.py (64% coverage)

- **Forge commands** (submit, status, approve, reject, logs) — require mocking `FileQueue` and async daemon
- **Doctor command** — diagnostic checks for Python version, provider keys, project structure
- **Test command** — pytest argument assembly and subprocess dispatch
- **Config set/get** — TOML manipulation paths

### scaffold.py (78% coverage)

- Status command state parsing — `state.json` deserialization with sprint extraction
- Directory scan fallback when `state.json` is incomplete

### supervisor.py interactive gate (lines 333-366)

- `Prompt.ask()` user input loop — requires mocking Rich prompts
- Editor launch path (`asyncio.create_subprocess_exec` for EDITOR)

### Gemini provider (85% coverage)

- Tool call parsing loop (lines 82-94) — multi-tool response handling not fully exercised

---

## Supply Chain Security

### Dependency pinning

Current `pyproject.toml` uses `>=` version ranges. A compromised upstream dependency gets pulled in on fresh installs. Pin to exact versions and consider hash verification.

### PyPI account hygiene

- Enable 2FA on PyPI account
- Review publish access
- Configure trusted publisher (OIDC) to replace token-based uploads
- Monitor GitHub Actions for unexpected workflow runs

### Context

Active PyPI supply chain campaign (TeamPCP, March 2026) targeting developer tools that handle API keys. ProductTeam is a credible target profile.

---

## Platform & CI

### Python 3.14 support

Developing on 3.14 locally but CI only tests 3.11-3.13. Either add 3.14 to the matrix or declare an upper bound.

### Windows `run_bash` subprocess handling

The `WinError 6` (invalid handle) issue in `subprocess.run(capture_output=True)` is handled with a structured error response, but the root cause (pytest capture conflicting with subprocess capture on Windows) means the happy path isn't fully exercised on Windows CI. The `shell=False` fix (v3.0 item 1) may resolve this as a side effect.

---

## Polish

### CONTRIBUTING.md

Not required but expected for an open-source project. Contribution guidelines, development setup, test running instructions.

### `your-username` placeholder scan

Automated test exists for ProductTeam's own docs but should also run against generated project artifacts to catch the Doc Writer producing placeholder URLs.

### Version bump automation

Four files need updating on every release (pyproject.toml, `__init__.py`, architecture.svg, index.html). A bump script or single-source-of-truth version would prevent the stale `v2.1.0` in index.html that was caught manually.
