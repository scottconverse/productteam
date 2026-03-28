# Contributing to ProductTeam

Thanks for your interest in contributing! This guide covers dev setup, testing, and PR guidelines.

## Dev Setup

```bash
# Clone the repo
git clone https://github.com/scottconverse/productteam.git
cd productteam

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
.venv\Scripts\activate           # Windows

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

### Auditors / zip reviewers

If you're reviewing from a zip download (not a git clone), you can install
dependencies without an editable install:

```bash
pip install -r requirements-dev.txt
```

This installs all runtime + test dependencies. The test suite will fail
with a clear error message if any dependency is missing.

## Running Tests

```bash
# Run all tests (excludes live API tests)
pytest tests/ -m "not live"

# Run with coverage
pytest tests/ -m "not live" --cov=productteam --cov-report=term-missing

# Run live tests against Ollama (free, local)
PRODUCTTEAM_TEST_PROVIDER=ollama PRODUCTTEAM_TEST_MODEL=qwen2.5:7b pytest tests/ -m live

# Run live tests against Anthropic
ANTHROPIC_API_KEY="sk-..." pytest tests/ -m live
```

Live tests make real API calls. They're excluded by default and run separately in CI.

## Version Bumping

All version updates go through the bump script to keep 5 locations in sync:

```bash
python bump_version.py 2.5.0          # updates all 5 locations
python bump_version.py 2.5.0 --dry-run # preview changes without writing
```

Locations updated: `pyproject.toml`, `src/productteam/__init__.py`, `docs/index.html`, `docs/architecture.svg`, `CHANGELOG.md`.

## Pull Request Guidelines

1. **One concern per PR.** Bug fix, feature, or refactor — not all three.
2. **Tests required.** If you change behavior, add or update tests. Don't lower coverage.
3. **Run the suite before pushing.** `pytest tests/ -m "not live"` must pass clean.
4. **Keep commits focused.** Write clear commit messages that explain *why*, not just *what*.
5. **No unrelated changes.** Don't reformat files you didn't modify or add drive-by refactors.

## Project Structure

```
src/productteam/
├── cli.py              # CLI commands (run, forge, init, status, recover)
├── supervisor.py       # Pipeline orchestrator, stage dispatch
├── tool_loop.py        # 4-tool agentic runtime (read_file, write_file, run_bash, list_dir)
├── models.py           # Pydantic config models
├── config.py           # TOML config load/save
├── providers/          # LLM provider adapters (Anthropic, OpenAI, Ollama, Gemini)
├── forge/              # Forge daemon, queue, dashboard
└── skills/             # Agent skill prompts (SKILL.md files)
```

## Security

ProductTeam handles API keys and runs LLM-generated shell commands. Security matters here:

- `run_bash` defaults to `shell=False`. Shell features fall back to `shell=True` with a warning.
- Writes to `.claude/` and `.productteam/` are blocked (except `.productteam/sprints/`).
- Credential environment variables are blocked from subprocess access.
- Dependencies are pinned to exact versions.

If you find a security issue, please email scottconverse@gmail.com instead of opening a public issue.

## Code Style

- No strict formatter enforced yet. Match the style of surrounding code.
- Type hints encouraged but not mandatory.
- Keep it simple. No abstractions for one-time operations.
