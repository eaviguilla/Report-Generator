# Work graph and the architecture review agent

## Destination

A spec, written with `/to-spec`, for two pieces of tooling:

- the **work graph**: a page generated from this repo's work items that shows them as linked nodes, with a detail panel, next steps, and a copy button for each next step;
- an **architecture review agent** that files its recommendations into `.scratch/` as review items, each with a status and a next step.

Building starts after this map closes, through `/to-tickets` and `/implement`.

## Notes

**What this is.** Tooling for this repo's own planning records. It is not part of VulnReport, so nothing under `app/`, `resources/` or the app's tests changes.

**Names.** These stay out of `GLOSSARY.md`, which covers the report domain only.

| Name | Meaning |
|---|---|
| work graph | the page |
| work item | one node with a status: a review item, plan, spec, issue, or wayfinder map or ticket |
| decision record | a node with no status; it records a decision and is shown for reference |
| link | a connection between two nodes |
| next step | one of Matt's skills suggested for an open work item, with a short reason; an item can have several, and the first is the main one |
| context | the items one step up from a work item, the ones it came from; a copied command lists them after `context:` |
| finished | a work item whose status is `done` or `wontfix`; it has no next steps |
| review item | one recommendation from an architecture review |

**What the user asked for.**

- Work items as nodes, linked where they are related, for example a feature to its spec to its tickets.
- Clicking a node shows its description, its status and its suggested next steps.
- Each next step has a copy button. Pasted into a new session, the text starts with the skill or agent to call, and explains the work or points to the file.
- Prototypes of the visuals before the real page.
- Separate from the app, but tracked in git.
- The architecture review files its recommendations into `.scratch/` by itself. A later review adds to the same report instead of creating a new one. Every item carries a status and a next step, such as "call `/grill-with-docs` next".
- A grilling before the review agent is written with `/writing-for-agents`.

**Settled while charting.**

- This map ends at decisions; nothing is built inside it.
- One graph. Unrelated threads show as separate groups, and items connect only where a real link exists.
- The markdown files are the record (`.scratch/`, `docs/plans/`, `docs/adr/`); the page is generated from them.
- "Function" in the user's request means a feature or an idea, not a code function.
- The starting set is the items created since mattpocock/skills was installed (commit `663d12d`, 2026-10-02 00:32) that link to at least one other item. `docs/plans/split-release-into-burp-and-default.md` is in it.
- The tool lives in `tools/work-graph/`, tracked in git. One Python script, standard library only, reads the records and the git log, writes one HTML page and opens it. Every run rebuilds the page; the built file is gitignored. Neither release script ships it: both package only `app/`, `resources/` and a few root files.

**Skills.** Grilling tickets: `/grilling` and `/domain-modeling`. Prototype tickets: `/prototype`, UI branch. Research tickets: `/research`. `/writing-for-agents` belongs to the build, after this map closes.

**Working rules.**

- Other sessions work in this same checkout. Never edit their uncommitted files and never switch this checkout's branch.
- Never push unless the user asks in that turn.
- Until the build moves them to the official statuses, this map's tickets keep the tracker's current words (`open`, `claimed`, `resolved`), because `/wayfinder` reads them from `docs/agents/issue-tracker.md`.

**Assets.**

- [2026-10-02 architecture review report](../architecture-review/2026-10-02-report.html): the first review, copied unchanged out of a temp folder. Its four recommendations are the first review items.

## Decisions so far

- [Which next steps a work item suggests, and what the copy button copies](issues/01-next-steps-and-the-copied-command.md): an open item lists one or more next steps in its file, main one first, each with a reason; the copy is `/<skill> <item> context: <items one step up>`; one official set of seven statuses for every work item; a guide to choosing a skill goes in `docs/agents/next-steps.md`.

## Not yet specified

- Adding links to the existing files, once the link rules exist.
- Whether `/triage`, `/to-tickets` and `/wayfinder` should record links as they create items, and whether that means changing Matt's skills.
- Which graph library the page uses, and whether it is copied into the repo or loaded from the internet. The review report loads Tailwind from a CDN; the graphify page loads vis-network from unpkg.

## Out of scope

- Any change to the app: `app/`, `resources/`, the app's tests.
- Code-level nodes such as functions or classes. The graphify graph already covers code.
- Items created before the install commit `663d12d`.
- Building the page or writing the review agent inside this map.
