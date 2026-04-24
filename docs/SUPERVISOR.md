<!-- supervisor-card: generated (safe to overwrite; delete this line if you hand-edit) -->
# ProductTeam Supervisor Card

One-page operating guide for Scott. Everything on this card is grounded in the
actual repo at `C:\Users\scott\OneDrive\Desktop\Claude\productteam-v2` as of
`pyproject.toml` version **2.6.3**.

---

## 1. Before every session (30 seconds)

Skim, in this order:

1. `pyproject.toml` — confirm the current version line (`version = "2.6.3"`
   today) and the pinned dependency list. This is the source of truth for
   every other version surface.
2. `CHANGELOG.md` — top entry tells you what the last push shipped and
   whether a release is mid-flight.
3. `git log --oneline -10` — look for dangling `bump:` or `fix:` commits
   that weren't paired with a PyPI push.
4. `CLAUDE.md` (repo root) — the AI Cost Awareness standing instructions.
   Re-read if any work will touch an LLM call, a tool loop, or a new stage.
5. Any work-in-progress YAMLs under `templates/` or `skills/*/` — these
   often indicate a pipeline change in flight.
6. `tests/test_cost_controls.py` — if the last session touched cost logic,
   know what's already covered before estimating blast radius.

---

## 2. During the session — what you actually do

1. **Estimate cost first.** Before any command that hits a live LLM
   (`productteam run`, live test runs, Forge daemon smoke tests), invoke
   the `cost-monitor` skill in *estimate* mode. Target is <$1/pipeline on
   Haiku, <$3 on Sonnet. If an estimate exceeds that, stop and investigate
   history truncation before running.
2. **Tests.** Primary command from repo root: `pytest -m "not live"`
   (18 test modules under `tests/`, including `test_cost_controls.py`,
   `test_tool_loop.py`, `test_integration_pipeline.py`). Live-API tests
   only on major releases: `pytest -m live`.
3. **Lint/type.** `pyproject.toml` does not configure ruff or mypy, so no
   auto-lint gate exists. If you add one this sprint, wire it into
   `.github/workflows/ci.yml` in the same commit.
4. **Stress-test aggregation.** After any significant pipeline change
   (orchestrator, tool loop, history truncation, model choice), invoke the
   `stress-test-agg` skill to compare pass-rate / loop-efficiency /
   verdicts across project variants before calling the change done.
5. **Release = PyPI + GitHub, always paired.** Standing rule. Use the
   `pypi-release` skill (one command, ten gated stages) — never push the
   git tag without uploading to PyPI in the same motion.

---

## 3. Hard rules active on this project

Numbered from `~/.claude/CLAUDE.md`. The ones that fire hardest on
ProductTeam are starred.

- **1 Read before you write.** Read the file before editing; re-read after.
- **2 Run before you declare done.\*** Pipeline changes silently break
  agent loops — paste actual `pytest` output, not "it should work."
- **3 Tests for logic changes.** Every logic change updates/adds a test
  under `tests/` using the existing pytest + pytest-asyncio setup.
- **4a Never skip tests.** No `pytest.mark.skip` without an explicit,
  logged un-skip plan in the same turn.
- **4 No secrets in client code.** Anthropic / USPTO keys never committed;
  `.gitignore` already covers `.env`.
- **5 Challenge bad requirements.** Especially ones that raise
  `max_tool_calls` or add an LLM call inside an existing loop.
- **6 Work incrementally.** Small verified steps — pipeline code is where
  "built it all, now testing" burns hundreds of dollars.
- **7 No wasteful operations.\*\*\*** Pipeline cost is a blocking concern.
  Truncate history, cache artifacts to disk, default to Haiku, don't
  regenerate outputs already on disk. See `CLAUDE.md` §Token Cost Rules.
- **8 Stay in scope.** Report adjacent issues, don't fix them inline.
- **9 Documentation Gate.\*** Six artifacts must exist before any `git
  push` / `gh release`: `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `LICENSE`, `.gitignore`, `docs/index.html`. Hook blocks the push at
  exit 2. `docs/index.html` is already present.
- **10 Subagent Obligation.** 2+ non-overlapping scopes → dispatch
  parallel subagents. 3rd inline Edit/Write in a turn is blocked.
  Override phrase: `override rule 10` (user-only, 60s one-shot).
- **11 Commit-Size Acknowledgment Gate.** Not yet wired in this repo
  (validation phase in civiccore only). Expect it later — big commits
  will need a bracketed token like `[LARGE-CHANGE]` or `[REFACTOR]`.

---

## 4. Four-pass gate

See `coder-ui-qa-test` skill.

---

## 5. Good session ending — ProductTeam-specific checklist

Finished work on ProductTeam looks like **all** of the following:

- [ ] `pytest -m "not live"` green; full unedited terminal output pasted.
- [ ] If logic changed a live-API path: `pytest -m live` green on at least
      one provider, cost logged.
- [ ] **Version bumped everywhere.** Use `python bump_version.py` if it
      still works, then verify manually: `pyproject.toml`,
      `src/productteam/__init__.py`, `README.md`, `docs/index.html`
      footer, `docs/ProductTeam-Architecture.pdf` cover. Recent history
      shows 5 separate "version sync" fix commits — do not ship until
      every surface agrees.
- [ ] `CHANGELOG.md` has a user-facing entry under the new version,
      Keep-a-Changelog format (Added / Changed / Fixed / Security).
- [ ] All 6 doc artifacts current: `README.md`, `CHANGELOG.md`,
      `CONTRIBUTING.md`, `LICENSE`, `.gitignore`, `docs/index.html`.
      If architecture changed: regenerate `docs/ProductTeam-Architecture.pdf`
      via `docs/build_pdf.py`.
- [ ] **Cost monitoring confirms no per-pipeline regression.** Run
      `cost-monitor` in *analyze* mode against the last full pipeline; a
      Haiku run stays under $1, a Sonnet run stays under $3. A regression
      is a blocking issue, not a note for later.
- [ ] Stress-test aggregation green if pipeline logic moved.
- [ ] **GitHub push and PyPI push paired.** Standing rule — invoke
      `pypi-release` skill; never a bare `git push` on a version commit.
- [ ] Scott has explicitly approved the push in this conversation turn
      (no self-certified releases).
