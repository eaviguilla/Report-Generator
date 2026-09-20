---
description: "Plan a change with the specialists it needs. Runs loremaster and tactician over a shared handoff file, and scribe too when the change reaches the Word pipeline, so the plan is checked against how things actually work before any code is written."
argument-hint: "What you want to build or change"
agent: "agent"
tools: [read, edit, search, agent, todo]
---

Coordinate the `loremaster` and `tactician` agents over a shared file so each one sees the other's work before the plan is final. Bring in `scribe` as well when the change reaches the Word document.

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

## Bring in the scribe when the change reaches the document

Size is one axis. Whether the change touches the Word pipeline is the other, and it is independent:
a one-field change can be entirely a document change, and a large data change can never go near it.

**Add a `scribe` call to round 1 when the change alters what the finished document contains, how it
is laid out, or how a finished document is read back into a draft.** Skip it otherwise. The
question to ask yourself is not "is this big" but "does anything here end up in the `.docx`".

The pipeline is around three thousand lines of Word XML handling plus a stage that only runs on
Windows, and `loremaster` is explicitly told not to cover it. Without `scribe` the planner plans
against a pipeline nobody has read. What that has actually bought, in one change:

- the hardest requirement in the request **did not exist** — the token the value had to fill owned
  its own paragraph rather than sitting mid-sentence, so no inline trickery was needed
- a shared helper **flattens line breaks**, which would have silently joined three values onto one
  line and passed every text assertion
- a value containing `{{` and `}}` **aborts generation**, a risk nobody had asked about
- one of the new values was **per finding, not per report**, which decided where it lived on the model

None of that was reachable from the data layer, and all of it changed the plan.

If an answer from the user later moves work into the pipeline that was not there at round 1 — an
import round trip, a new template — call `scribe` again for round 2 under its own heading, rather
than letting the planner guess.

## The handoff file

Create `docs/plans/<slug>.md`, where `<slug>` is a short kebab-case name for the change. Create `docs/plans/` if it does not exist. This file is the shared workspace for the whole exchange. Do not summarise it in chat instead of writing it; later rounds read it.

Structure, in order:

```markdown
# <Change name>

> **Status:** planning · <today's date>

## Request
<the user's ask, verbatim>

## Round 1 - Oracle: how it works today
## Round 1 - Scribe: the document side   <- only when the change reaches the .docx
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

**Round 1s. Ask the scribe about the document, if the change reaches it.** Invoke `scribe` with the heading *Round 1 - Scribe*. Scope it to the pipeline only and tell it not to repeat what the oracle covered: which template or component carries the affected text, what the token replacement actually does with the value, whether the document can even express what the request asks for, and what a finished document gives back on import. Run it **after** the oracle and **before** the planner, so both reports are on the file when the planner reads it. Sequentially, not in parallel — two agents writing one file can lose each other's section.

**Round 1b. Ask the planner to propose.** Invoke `tactician`. Point it at the handoff file and tell it to read *Round 1 - Oracle*, and *Round 1 - Scribe* where it exists, for itself, treating those findings as established fact and not re-deriving them. It writes its proposal under *Round 1 - Planner*. Do not paste either report into the prompt — the file is right there, and copying it is the cost this design exists to avoid.

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
