# How the architecture review files its items

Type: grilling
Status: open
Blocked by: 02, 03, 04
Map: [Work graph and the architecture review agent](../map.md)

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
