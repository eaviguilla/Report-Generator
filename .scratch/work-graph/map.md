# Star Map and the architecture review

Status: in-progress

## Destination

A spec, written with `/to-spec`, for two pieces of tooling:

- the **Star Map**: a page generated from this repo's work items that shows them as linked nodes, with a detail panel, next steps, and a copy button for each next step;
- the **architecture review**, `/improve-codebase-architecture`, changed so that it files its recommendations into `.scratch/` as review items, each with a status and next steps.

The Star Map was built on 2026-10-03 in `tools/star_map/`, ahead of the spec, because the user asked for it. The official statuses and the rules that keep next steps and links current followed the same day. The spec now covers only the architecture review change, built after this map closes through `/to-tickets` and `/implement`.

## Notes

**What this is.** Tooling for this repo's own planning records. It is not part of VulnReport, so nothing under `app/`, `resources/` or the app's tests changes.

**Names.** These stay out of `GLOSSARY.md`, which covers the report domain only.

| Name | Meaning |
|---|---|
| Star Map | the page |
| work item | one node with a status: a review item, plan, spec, issue, or wayfinder map or ticket |
| decision record | a node with no status; it records a decision and is shown for reference |
| out-of-scope file | a file `/triage` writes in `.out-of-scope/` for each feature idea it turns down; a node with no status, drawn only while an open work item came from it |
| link | a connection from one node to another, of one of three kinds: came from, blocked by, or merged into |
| thread | the nodes joined by links, drawn as one group; the item at its top, where the idea was first written down, stands for the feature |
| next step | one of Matt's skills suggested for an open work item, with a short reason; an item can have several, and the first is the main one |
| context | the items a work item needs: the ones it came from, the ones blocking it, and the ones merged into it; a copied command lists them after `context:` |
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

- This map ends at decisions; nothing is built inside it, except the Star Map, which the user asked for early.
- One graph. Unrelated threads show as separate groups, and items connect only where a real link exists.
- The markdown files are the record (`.scratch/`, `docs/plans/`, `docs/adr/`); the page is generated from them.
- "Function" in the user's request means a feature or an idea, not a code function.
- The starting set is every item created since mattpocock/skills was installed (commit `663d12d`, 2026-10-02 00:32), linked or not, as [What a work item is, and how a link is recorded](issues/03-what-a-work-item-is-and-how-a-link-is-recorded.md) settled. `docs/plans/split-release-into-burp-and-default.md` is in it.
- The tool lives in `tools/star_map/`, tracked in git. One Python script, standard library only, reads the records and the git log, writes one HTML page and opens it. Every run rebuilds the page; the built file is gitignored. Neither release script ships it: both package only `app/`, `resources/` and a few root files.

**Skills.** Grilling tickets: `/grilling` and `/domain-modeling`. Prototype tickets: `/prototype`, UI branch. Research tickets: `/research`. `/writing-for-agents` belongs to the build, after this map closes.

**Working rules.**

- Other sessions work in this same checkout. Never edit their uncommitted files and never switch this checkout's branch.
- Never push unless the user asks in that turn.
- This map's tickets use the official statuses, which `docs/agents/issue-tracker.md` defines for `/wayfinder`.

**Assets.**

- [2026-10-02 architecture review report](../architecture-review/2026-10-02-report.html): the first review, copied unchanged out of a temp folder. Its four recommendations are the first review items.

## Decisions so far

- [Which next steps a work item suggests, and what the copy button copies](issues/01-next-steps-and-the-copied-command.md): an open item lists one or more next steps in its file, main one first, each with a reason; the copy is `/<skill> <item> context: <items one step up>`; one official set of seven statuses for every work item; a guide to choosing a skill goes in `docs/agents/next-steps.md`.
- [How the architecture review files its items](issues/07-how-the-architecture-review-files-its-items.md): edit step 2 of Matt's `/improve-codebase-architecture` in place so it publishes to `.scratch/architecture-review/`, one review item per recommendation plus one `report.html` that each review adds a section to; git covers the update risk, so [What a mattpocock/skills update does to a skill edited here](issues/02-what-a-skills-update-does-to-a-local-edit.md) closed unneeded.
- [What a work item is, and how a link is recorded](issues/03-what-a-work-item-is-and-how-a-link-is-recorded.md): the path gives a node its type, and the top item of a thread stands for the feature; commits are neither nodes nor links; every item since `663d12d` shows, linked or not; three links, each one header line, are came from (the folder or `From:`), `Blocked by:` and `Merged into:`, and `context:` lists all three; rules in `docs/agents/issue-tracker.md`, the plan rules and `ADR-FORMAT.md` tell sessions to write them.

- [Does a spec or map take its status from its tickets?](issues/04-does-a-spec-or-map-take-its-status-from-its-tickets.md): statuses stay explicit; the graph may separately show when all direct children are finished, without propagating status, including from a spec to its originating review item.
- [Which layout shows the work items best](issues/06-which-layout-shows-the-work-items-best.md): a force-directed star map on a dark sky, one kind of star per status and a cloud per thread; links told apart by colour and dashes; the page is the Star Map, in `tools/star_map/`; no commit list and no library.
- [Whether the Star Map shows out-of-scope files](issues/08-whether-the-star-map-shows-out-of-scope-files.md): a file `/triage` writes in `.out-of-scope/` is a node with no status, drawn only while an open item names it in a `From:` line, and it goes into that item's `context:`; when you change your mind about a turned-down idea, triage copies its reasons into the request and deletes the file; built on its own through [Show out-of-scope files on the Star Map](../star-map/issues/01-show-out-of-scope-files.md), because the spec does not depend on it.

## Not yet specified

## Out of scope

- Any change to the app: `app/`, `resources/`, the app's tests.
- Code-level nodes such as functions or classes. The graphify graph already covers code.
- Items created before the install commit `663d12d`.
- Changing the review skill inside this map. The Star Map was the one exception, built at the user's request.

## Next steps

1. `/to-spec`: Every decision is settled. Write the spec for the architecture review change.
