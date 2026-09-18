---
description: "Plan a change with both specialists. Runs loremaster and tactician over a shared handoff file so the plan is checked against how data actually works before any code is written."
argument-hint: "What you want to build or change"
agent: "agent"
tools: [read, edit, search, agent, todo]
---

Coordinate the `loremaster` and `tactician` agents over a shared file so each one sees the other's work before the plan is final.

Subagents cannot message each other directly; each runs once and returns a single report. You are the messenger. The handoff file is what gives them a common memory, and the round trip below is what makes the exchange real rather than two opinions stapled together.

## Subagents write their own sections

**Tell every subagent to write its findings straight into the handoff file, and to return you a short
summary rather than the whole report.** Give it the exact path and the exact heading to write under.

This is the difference between a cheap exchange and an expensive one. A full oracle report runs to
tens of thousands of characters; routing four of those through your context so you can retype them
into the file costs the whole budget twice over and risks garbling them on the way. The file is the
artifact. You need only enough back to decide what happens next.

What you should get back from a subagent:

- confirmation of which heading it wrote under
- the handful of findings that change your next move — contradictions, blockers, open questions
- nothing it has already written to the file

You still read the file when you need the detail. You just do not carry it.

## Scale the rounds to the change

The full exchange is four subagent calls. Most changes do not need four. Judge the size **before**
you start and say which you picked and why:

| Size | Looks like | Run |
|---|---|---|
| **Small** | One file, no new field, no rule with a JavaScript twin. You could describe the diff in a sentence. | **No exchange at all.** Say so and implement it. A plan document costs more than the change. |
| **Medium** | A few files, or one rule that exists on both sides, but no schema change. | **Round 1 only** — oracle, then planner. Go to round 2 *only* if the planner's risk table has a `RISK` row, or it contradicts the oracle. |
| **Large** | A new or changed field, a migration, a new page or route, or anything touching how a report is saved. | **Both rounds, always.** This is the case the exchange was built for. |

When in doubt, start at medium. Escalating after round 1 costs one extra call; running four calls on
a one-line change wastes all of them.

## The handoff file

Create `docs/plans/<slug>.md`, where `<slug>` is a short kebab-case name for the change. Create `docs/plans/` if it does not exist. This file is the shared workspace for the whole exchange. Do not summarise it in chat instead of writing it; later rounds read it.

Structure, in order:

```markdown
# <Change name>

> **Status:** planning · <today's date>

## Request
<the user's ask, verbatim>

## Round 1 - Oracle: how it works today
## Round 1 - Planner: proposal and open questions
## Round 2 - Oracle: verdict on the proposal
## Round 2 - Planner: revised plan
## Answers
## Agreed plan
```

### The status line

One of `planning`, `agreed`, `in progress`, `shipped`, `superseded`, `abandoned`. Set it to
`planning` when you create the file and to `agreed` when you write *Agreed plan*. Anything past that
belongs to whoever implements it, not to this prompt.

When a plan reaches `shipped`, the line carries the commit and a short prose note of anything that
deviated from the plan — a step dropped, a requirement discovered during execution, a different
solution than the one agreed. The deviations are the part worth reading later:

```markdown
> **Status:** shipped · 2026-09-15 · `acd047a`
>
> Steps 0-8 done, except step 0's parity tests, which became three behavioural browser tests.
> One requirement was added during execution and is not described below: unchecking an app type
> now purges it from memory, behind a confirm dialog that counts exactly what goes.
```

## The exchange

**Round 1a. Ask the oracle what exists.** Invoke `loremaster`. Give it the request, the handoff file path, and the heading *Round 1 - Oracle*, and tell it to write its report there itself. Ask specifically: which parts of the data layer this touches, the invariants that constrain it, what the existing drafts on disk look like in this area, and which of the involved rules exist in both Python and JavaScript.

**Round 1b. Ask the planner to propose.** Invoke `tactician`. Point it at the handoff file and tell it to read *Round 1 - Oracle* for itself, treating those findings as established fact and not re-deriving them. It writes its proposal under *Round 1 - Planner*. Do not paste the oracle's report into the prompt — the file is right there, and copying it is the cost this design exists to avoid.

**Decide whether round 2 is needed.** Read what the planner wrote. Run round 2 when the change is large, when the risk table has a `RISK` row, or when the planner contradicts the oracle. Otherwise record in the file that round 2 was skipped and why, and go straight to the questions.

**Round 2a. Send the proposal back to the oracle.** Invoke `loremaster` again, pointing it at the planner's section and the heading *Round 2 - Oracle*. Ask it to check each claim against source and answer three things:
- Which risk rows are wrong, in either direction: marked `clear` but actually a risk, or marked `RISK` but already handled by existing code.
- Which files the planner missed, particularly the second half of any rule that exists on both sides.
- Whether the proposed shape breaks any existing `draft.json` on disk.

**Round 2b. Revise.** If the oracle contradicted anything, invoke `tactician` once more to read the verdict and revise under *Round 2 - Planner*. If the oracle confirmed everything, record that and skip this step.

**Then ask the user.** Collect the open questions from both rounds, drop duplicates, and put them to the user with the ask-questions tool. Record the replies under *Answers*.

**Settle it.** Write *Agreed plan*: the ordered steps, each with its files, its test, and the invariant it protects. This section must be readable on its own, without the rounds above it.

Write each step as an unticked checkbox, `- [ ] **Step N — ...**`, so the document can later show how
far it got. Then set the status line to `agreed`.

## Rules for you as coordinator

- **Open the file with a status line and close it with one.** `planning` on creation, `agreed` once
  *Agreed plan* is written. A plan with no status is one nobody can tell the state of six months on.

- **Do not arbitrate.** When the two disagree, the oracle wins on what the code does and the planner wins on what to do about it. If they conflict on fact, open the file yourself and settle it with a quote.
- **Do not let the planner skip the risk table.** An empty or all-clear table on a change that touches report data means it did not look. Send it back.
- **Do not start implementing.** This prompt ends at an agreed plan. Implementation is a separate request.
- **Keep the file honest.** Record what was rejected and why, not only what survived. The next person needs the reasoning more than the conclusion.

Relevant background for both agents: [docs/DATA_MAP.md](../../docs/DATA_MAP.md).
