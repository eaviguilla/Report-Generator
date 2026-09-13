---
description: "Plan a change with both specialists. Runs data-oracle and change-planner over a shared handoff file so the plan is checked against how data actually works before any code is written."
argument-hint: "What you want to build or change"
agent: "agent"
tools: [read, edit, search, agent, todo]
---

Coordinate the `data-oracle` and `change-planner` agents over a shared file so each one sees the other's work before the plan is final.

Subagents cannot message each other directly; each runs once and returns a single report. You are the messenger. The handoff file is what gives them a common memory, and the round trip below is what makes the exchange real rather than two opinions stapled together.

## The handoff file

Create `docs/plans/<slug>.md`, where `<slug>` is a short kebab-case name for the change. Create `docs/plans/` if it does not exist. This file is the shared workspace for the whole exchange. Do not summarise it in chat instead of writing it; later rounds read it.

Structure, in order:

```markdown
# <Change name>

## Request
<the user's ask, verbatim>

## Round 1 - Oracle: how it works today
## Round 1 - Planner: proposal and open questions
## Round 2 - Oracle: verdict on the proposal
## Round 2 - Planner: revised plan
## Answers
## Agreed plan
```

## The exchange

**Round 1a. Ask the oracle what exists.** Invoke `data-oracle`. Give it the request and ask specifically: which parts of the data layer this touches, the invariants that constrain it, what the existing drafts on disk look like in this area, and which of the involved rules exist in both Python and JavaScript. Write its report into *Round 1 - Oracle* verbatim, keeping its evidence links.

**Round 1b. Ask the planner to propose.** Invoke `change-planner`. Pass the request **and the full text of the oracle's findings**, instructing it to treat those findings as established fact and not re-derive them. Write its output into *Round 1 - Planner*.

**Round 2a. Send the proposal back to the oracle.** Invoke `data-oracle` again. Give it the planner's blast radius, data-risk table, and plan, and ask it to check each claim against source. It must answer three things:
- Which risk rows are wrong, in either direction: marked `clear` but actually a risk, or marked `RISK` but already handled by existing code.
- Which files the planner missed, particularly the second half of any rule that exists on both sides.
- Whether the proposed shape breaks any existing `draft.json` on disk.

Write the verdict into *Round 2 - Oracle*.

**Round 2b. Revise.** If the oracle contradicted anything, invoke `change-planner` once more with the verdict and have it revise. Write the result into *Round 2 - Planner*. If the oracle confirmed everything, record that and skip this step.

**Then ask the user.** Collect the open questions from both rounds, drop duplicates, and put them to the user with the ask-questions tool. Record the replies under *Answers*.

**Settle it.** Write *Agreed plan*: the ordered steps, each with its files, its test, and the invariant it protects. This section must be readable on its own, without the rounds above it.

## Rules for you as coordinator

- **Do not arbitrate.** When the two disagree, the oracle wins on what the code does and the planner wins on what to do about it. If they conflict on fact, open the file yourself and settle it with a quote.
- **Do not let the planner skip the risk table.** An empty or all-clear table on a change that touches report data means it did not look. Send it back.
- **Do not start implementing.** This prompt ends at an agreed plan. Implementation is a separate request.
- **Keep the file honest.** Record what was rejected and why, not only what survived. The next person needs the reasoning more than the conclusion.

Relevant background for both agents: [docs/DATA_MAP.md](../../docs/DATA_MAP.md).
