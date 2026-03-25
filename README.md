# ProductTeam

**A product development pipeline powered by specialized AI agents.**

Turn a product concept into shipping code. PRD → Plan → Build → Evaluate → Document → Ship.

## The Idea

Every modern software team has specialized roles: product managers write specs, engineers build, QA tests, designers review, technical writers document. ProductTeam encodes these roles as AI agent skills with a key insight from Anthropic's research: **separate the builder from the judge.**

The Builder can never declare its own work "done." Only the Evaluator can. This GAN-inspired loop (generator + discriminator) produces measurably better output than a single agent working alone.

## The Pipeline

```
  Product Manager (human)
      | "I want a tool that does X"
      v
 +--------------+
 |  PRD WRITER  |  --> Structured PRD document
 +--------------+
      | User approves PRD
      v
 +--------------+
 |   PLANNER    |  --> Sprint contracts with testable acceptance criteria
 +--------------+
      | User approves sprint scope
      v
 +--------------+       +----------------+
 |   BUILDER    | ----> |  UI BUILDER    |   (if visual deliverables)
 +--------------+       +----------------+
      |                       |
      v                       v
 +--------------+       +--------------------+
 |  EVALUATOR   |       | DESIGN EVALUATOR   |
 +--------------+       +--------------------+
      |                       |
      +--- PASS <-------------+
      |
      v
 +--------------+
 |  DOC WRITER  |  --> README, landing page, PDF, changelog
 +--------------+
      |
      v
      SHIP
```

## The Team (8 Skills)

| Skill | Role | What It Does |
|-------|------|-------------|
| `prd-writer` | Product Manager | Takes a concept, asks clarifying questions, researches competitors, produces a structured PRD |
| `planner` | Tech Lead | Reads PRD, decomposes into sprint contracts with testable acceptance criteria |
| `builder` | Engineer | Implements sprint contracts, writes tests, declares "ready for review" (never "done") |
| `ui-builder` | Frontend Engineer | Specialized builder for visual work: landing pages, dashboards, web UIs |
| `evaluator` | QA Engineer | Verifies code against sprint contract, runs tests, tries to break things, grades PASS/NEEDS_WORK/FAIL |
| `evaluator-design` | Design Reviewer | Grades visual artifacts on Coherence, Originality, Craft, and Functionality (1-5 scale) |
| `doc-writer` | Technical Writer | Reads code (never fabricates), produces README, landing page, PDF, changelog |
| `orchestrator` | Project Manager | Routes work, manages build-evaluate loops, enforces approval gates, writes handoff artifacts |

## Quick Start

### Option 1: Full pipeline (start from a concept)

```
/productteam "I want a CLI tool that estimates API costs for LLM prompts"
```

The Orchestrator will route your concept through PRD Writer, Planner, Builder, Evaluator, and Doc Writer automatically, pausing at three approval gates for your input.

### Option 2: Jump into the pipeline at any stage

```
/productteam plan docs/PRD.md           # Skip to Planner with an existing PRD
/productteam build .claude/sprints/sprint-001.yaml   # Skip to Builder
/productteam eval .claude/sprints/sprint-001.yaml    # Skip to Evaluator
/productteam docs                       # Skip to Doc Writer for current project
/productteam status                     # Show current pipeline state
```

### Option 3: Drop skills into any project

Copy the `skills/` directory into your project's `.claude/skills/` directory and use individual skills without the full pipeline.

## How It Works

### Three Approval Gates

The pipeline runs automatically between gates. You only stop three times:

| Gate | When | Prompt |
|------|------|--------|
| PRD Approval | PRD Writer produces a PRD | "Does this capture your intent?" |
| Sprint Approval | Planner produces sprint contracts | "Does this scope look right?" |
| Ship Approval | All evaluations pass | "Ready to commit/push/publish?" |

### The Build-Evaluate Loop

```
Builder implements --> Evaluator reviews --> PASS? --> Done
                                        --> NEEDS_WORK? --> Back to Builder (max 3 loops)
                                        --> FAIL? --> Escalate to human
```

- The Builder declares "ready for review" -- never "done"
- The Evaluator is skeptical by default: assumes code is broken until proven otherwise
- Maximum 3 loops per sprint. If loop 3 still fails, the plan is wrong, not the implementation
- The Orchestrator escalates to the user with the full evaluation history

### Structured Artifacts

All state lives in files, not conversation memory. The next session can pick up where the last one left off.

```
.productteam/
  prds/           PRD documents
  sprints/        Sprint contracts (YAML)
  evaluations/    Evaluation reports (YAML)
  handoffs/       Session handoff artifacts (YAML)
```

Templates for these artifacts live in `templates/`.

## What Makes This Different

| Other Multi-Agent Systems | ProductTeam |
|--------------------------|-------------|
| Agents self-evaluate | Separate skeptical judge (Evaluator) that assumes code is broken |
| "Done" when builder says so | "Done" only when Evaluator grades PASS |
| State in conversation memory | State in structured YAML files that persist across sessions |
| All agents or nothing | Drop in only the skills you need |
| Complex setup (databases, hooks, scripts) | Just markdown files in a directory |
| Single design standard | Two evaluators: code quality (Evaluator) and visual quality (Design Evaluator) |

## Proven Results

Built and tested on the prompttools project (7 Python packages):

- **755 tests** across 6 packages -- all written and verified through the pipeline
- **7 real bugs** caught by Evaluators that Builders missed
- **Planners identified gaps** in every package they analyzed
- **All 6 packages** passed Evaluator review
- **Design Evaluator** graded landing pages on Coherence, Originality, Craft, and Functionality

## Installation

Copy the `skills/` directory into your project:

```bash
cp -r productteam/skills/ your-project/.claude/skills/
```

Or clone and symlink:

```bash
git clone https://github.com/scottconverse/productteam.git
ln -s /path/to/productteam/skills your-project/.claude/skills
```

## Project Structure

```
productteam/
  skills/
    prd-writer/SKILL.md
    planner/SKILL.md
    builder/SKILL.md
    ui-builder/SKILL.md
    evaluator/SKILL.md
    evaluator-design/SKILL.md
    doc-writer/SKILL.md
    orchestrator/SKILL.md
  templates/
    sprint-contract.yaml
    evaluation-report.yaml
    handoff-artifact.yaml
  docs/
    index.html            Landing page
  README.md
  LICENSE
```

## License

MIT

## Author

Scott Converse
