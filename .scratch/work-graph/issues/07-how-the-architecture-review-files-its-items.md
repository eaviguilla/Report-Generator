# How the architecture review files its items

Type: grilling
Status: done
Map: [Observatory and the architecture review](../map.md)

## Question

When `/improve-codebase-architecture` runs again, how do its recommendations become review items in `.scratch/`, and how is the cumulative review report made?

- **The user's words.** File the recommendations into `.scratch/` automatically; a later review adds to the same HTML instead of creating a new one; every item has a status and a next step, such as "call `/grill-with-docs` next"; grill before the agent is written with `/writing-for-agents`.
- **Settled elsewhere.** Review items use the official statuses and start at `needs-triage`. Whoever files an item writes its `## Next steps`, for example `/grill-with-docs` first. See [Which next steps a work item suggests, and what the copy button copies](01-next-steps-and-the-copied-command.md).
- **Wrap or edit.** A local agent or skill that runs Matt's skill and then files the items, or an edit to Matt's skill. [What a mattpocock/skills update does to a skill edited here](02-what-a-skills-update-does-to-a-local-edit.md) says which is safe. Local agents live twice, in `.github/agents/` and `.claude/agents/`, kept in step by hand.
- **Where items go.** One folder for every review, such as `.scratch/architecture-review/`, numbered across reviews, each item saying which review found it.
- **What an item holds.** The first report has, per recommendation, a problem, a solution, wins, and a before-and-after diagram: [the 2026-10-02 review report](../../architecture-review/2026-10-02-report.html).
- **Found again.** When a later review finds something already filed: update that item, or file a new one?
- **The report.** A view of the work graph with items grouped by review, or a page of its own generated from the items; and what becomes of the first report file.
- **The first four items.** Recommendations 1 and 2 are done (commits `37593ea` and `af37291`, plan `docs/plans/report-acceptance.md`), 3 is open, 4 is partly done.

Waits for [What a mattpocock/skills update does to a skill edited here](02-what-a-skills-update-does-to-a-local-edit.md), [What a work item is, and how a link is recorded](03-what-a-work-item-is-and-how-a-link-is-recorded.md) and [Does a spec or map take its status from its tickets?](04-does-a-spec-or-map-take-its-status-from-its-tickets.md)

## Answer

Settled with the user on 2026-10-03, without waiting for [What a work item is, and how a link is recorded](03-what-a-work-item-is-and-how-a-link-is-recorded.md) or [Does a spec or map take its status from its tickets?](04-does-a-spec-or-map-take-its-status-from-its-tickets.md): the answer does not depend on how links are recorded, and the one status question it raises stays with ticket 04.

### Why this is a task

A review's results should land in `.scratch/`, organized, instead of outside the repo. One instruction in Matt's skill sends them out: step 2 of `.claude/skills/improve-codebase-architecture/SKILL.md` writes the HTML report "to the OS temp directory so nothing lands in the repo", as a fresh timestamped file on every run. His other skills, such as `/to-spec`, `/to-tickets` and `/triage`, publish to the issue tracker, which `docs/agents/issue-tracker.md` routes into `.scratch/`.

### Edit Matt's skill in place

Change that one instruction so the review publishes to the tracker like his other skills. The user keeps typing `/improve-codebase-architecture`, and his other steps stay as they are.

Git tracks the skill's files, so an update that undid the edit would show up as a modified `SKILL.md` before it is committed. That made [What a mattpocock/skills update does to a skill edited here](02-what-a-skills-update-does-to-a-local-edit.md) unnecessary.

Rejected:

- A skill of our own that wraps Matt's. It cannot start his, which has `disable-model-invocation: true`, and reading his file and following it leaves the agent two documents to reconcile.
- A full copy with our changes. It would miss his later updates.
- A line in `CLAUDE.md` and `.github/copilot-instructions.md`. It competes with the skill's own instruction, so the agent may skip it, and it costs context in every chat.
- An agent file. An agent hands back one message, so it cannot hold the grilling the review ends with.

### What every review produces

```
.scratch/architecture-review/
  report.html          one page; each review adds a dated section at the top
  issues/
    NN-<slug>.md       one review item per recommendation, numbered across reviews
```

- **One review item per recommendation.** It holds the report card's files, problem, solution, benefits and strength, and links to its section in `report.html`. It starts at `Status: needs-triage` with a `## Next steps` list, following [Which next steps a work item suggests, and what the copy button copies](01-next-steps-and-the-copied-command.md).
- **One report that grows.** The new review becomes a dated section at the top of `report.html`, above the earlier reviews. The before-and-after diagrams live there.
- **No duplicates.** A recommendation already filed and still open gets a "found again" line with the review's date in its existing file. One whose earlier item is finished is filed as a new item that links to the old one.
- **Grilling as before.** His grilling step runs unchanged. When a grilling settles a recommendation, that session updates the item's status and next steps.

### For the build

- Edit step 2 of `.claude/skills/improve-codebase-architecture/SKILL.md`, and `HTML-REPORT.md` where its scaffold assumes one review per page. Write the change with `/writing-for-agents`, stating where the results go.
- File the 2026-10-02 review: its four recommendations become review items 01 to 04, and [its report](../../architecture-review/2026-10-02-report.html) becomes the first section of `report.html`. Recommendations 1 and 2 are `done` (commits `37593ea` and `af37291`, plan `docs/plans/report-acceptance.md`); 3 is `needs-triage`; 4 is partly done, so the session that files it sets its status and next steps from what remains.

### Handed on

- Whether a review item is finished once the spec made from it is: [Does a spec or map take its status from its tickets?](04-does-a-spec-or-map-take-its-status-from-its-tickets.md)
