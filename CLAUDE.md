# AI Cost Awareness — Standing Instructions

Every LLM call costs real money. These rules apply to all code you write,
review, or suggest in this project. They are not optional.

---

## Token Cost Rules

**Use the cheapest model that does the job.**
Not every task needs Sonnet. Classification, formatting, summarizing,
short outputs, acceptance criteria checks — Haiku handles these fine.
Reserve Sonnet for complex reasoning, multi-step planning, and situations
where output quality demonstrably matters. When suggesting model choices
in code or config, default to the cheaper option and require a reason
to upgrade.

**Conversation history grows quadratically. Truncate it.**
In any tool loop or multi-turn LLM call, the full message history is sent
on every call. By call 100, you're sending 99 prior exchanges as context.
This is the single biggest source of runaway token cost. Any code that
accumulates messages in a list and passes them to an LLM must either:
- Truncate to a sliding window (keep first message + last N exchanges), or
- Explicitly justify why full history is required.
Never let message history grow unboundedly.

**Short prompts. Short outputs. No padding.**
A 30-word structured answer costs a fraction of a 600-word explanation.
When writing system prompts or skill files, instruct the model to be
concise. Remove phrases like "Please provide a detailed explanation of..."
and "Think step by step about all the possible ways..." unless the task
genuinely requires it. Every unnecessary word in a prompt multiplies
across every call that uses it.

**Tool calls compound cost. Set explicit budgets.**
Each tool call in an agentic loop makes a full LLM round-trip. A loop
configured for 150 calls at $0.001/call = $0.15 in a happy path, but
exponentially more with history growth. Any code that uses a tool loop
must have:
- An explicit max_tool_calls limit
- History truncation (see above)
- A test that verifies the call count stays within budget on a mock run

**Cache and reuse results whenever possible.**
If an LLM call produces output that could be used again (a PRD, a sprint
contract, an evaluation report), write it to disk and read it back rather
than regenerating. Regeneration is expensive. Reading a file is free.
The pipeline already does this for artifacts — don't create new code paths
that bypass it by making fresh API calls for information already on disk.

---

## Cost-Aware Code Review Checklist

Before suggesting or approving any code that calls an LLM:

- [ ] Is the model choice justified? (Default to cheapest that works)
- [ ] Is message history bounded? (Sliding window or single-turn)
- [ ] Is the prompt as short as it can be while still being correct?
- [ ] Is there a max_tool_calls or equivalent limit?
- [ ] Is the result cached to disk to avoid regeneration?
- [ ] Is there a token count or cost estimate visible to the user?

If any box is unchecked, flag it before proceeding.

---

## Unit Economics Context

This project targets individual developers and small teams (2-20 people).
The target cost per pipeline run is under $1 for a typical 2-3 sprint
project on Haiku, or under $3 on Sonnet. Any change that risks exceeding
these thresholds requires explicit justification.

Signs a change will blow the budget:
- Raising max_tool_calls without fixing history truncation
- Adding a new LLM call inside an existing loop
- Using a larger model for a task that doesn't require it
- Removing or weakening a truncation or caching mechanism
- Making a stage "more thorough" without a quality level gate

When in doubt, estimate the token cost before implementing. A back-of-
envelope calculation (calls x avg_context_size x price/token) takes
30 seconds and prevents $50 mistakes.

---

## Reference: What $57 Looks Like

In one test session, a simple CLI tool concept burned $57 in API costs.
Root cause: builder_max_tool_calls was raised from 75 to 150 without
fixing message history truncation. At call 150, the model was receiving
~750k tokens of accumulated context per call. Total: 39.9M input tokens
in one day on Haiku.

The fix was a 10-line sliding window function. The lesson is that token
cost in agentic loops is not linear — it is quadratic without truncation.
This is the most important thing to understand about LLM cost in this
codebase.

---

## Model Selection Guide

| Task | Recommended Model | Reason |
|------|------------------|--------|
| Acceptance criteria verification | Haiku | Structured yes/no, low reasoning |
| Code writing (simple) | Haiku | Pattern following, not reasoning |
| Code writing (complex logic) | Sonnet | Multi-step reasoning required |
| PRD writing | Sonnet | Quality of output matters |
| Sprint planning | Sonnet | Decomposition requires reasoning |
| Documentation | Haiku | Template filling, low creativity |
| Design evaluation | Haiku | Checklist application |
| Debugging / architecture | Sonnet | Complex reasoning required |
| Local / free development | Ollama qwen2.5:7b | Zero cost, good enough for iteration |

---

## Pricing Reference (March 2026)

| Model | Input $/MTok | Output $/MTok |
|-------|-------------|---------------|
| claude-haiku-4-5 | $0.80 | $4.00 |
| claude-sonnet-4-6 | $3.00 | $15.00 |
| gpt-4o-mini | $0.15 | $0.60 |
| gpt-4o | $2.50 | $10.00 |
| ollama (local) | $0.00 | $0.00 |

A typical 2-sprint pipeline should cost:
- Haiku: $0.10 - $0.40
- Sonnet: $0.50 - $2.00
- Ollama: Free

If a run exceeds $2 on Haiku or $5 on Sonnet for a simple concept,
something is wrong with the token growth. Investigate before continuing.
