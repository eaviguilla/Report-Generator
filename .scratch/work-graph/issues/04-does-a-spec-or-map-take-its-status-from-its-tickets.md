# Does a spec or map take its status from its tickets?

Type: grilling
Status: done
Blocked by: 03
Map: [Star Map and the architecture review](../map.md)

## Question

When a spec or a wayfinder map has tickets, does its status follow theirs, or does a session set it by hand?

- **Why it matters.** A finished item has no next steps, so the page must know when a spec or map is finished. Nothing marks one today: `/to-tickets` says not to modify the parent issue, and `/implement-spec` closes each ticket but not the spec.
- **One level up.** A review item that became a spec: is it finished when the spec is?
- **Options to weigh.** The page works the status out from the items made from it, for example every ticket finished means the parent is `done`; a session sets the parent by hand; or the page only flags a parent whose tickets are all finished.

Charting first asked here which statuses each item has and what next step each suggests. [Which next steps a work item suggests, and what the copy button copies](01-next-steps-and-the-copied-command.md) settled both, with one official set of statuses, and left this question. How the statuses look moved to [Which layout shows the work items best](06-which-layout-shows-the-work-items-best.md).

Waits for [What a work item is, and how a link is recorded](03-what-a-work-item-is-and-how-a-link-is-recorded.md): this needs the links between an item and the items made from it.

## Answer

Settled with the user on 2026-10-03.

- Every work item's status is set explicitly. Finishing its child items does not change the parent's status.
- The graph may show a separate completion cue when all of an item's direct children are `done` or `wontfix`. This cue is informational and does not set the parent's status.
- A review item that produced a spec remains independently statused. Finishing the spec does not finish the review item; each is marked finished when its own outcome is complete.
