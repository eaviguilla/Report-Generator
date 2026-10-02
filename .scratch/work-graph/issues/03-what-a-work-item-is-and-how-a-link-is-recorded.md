# What a work item is, and how a link is recorded

Type: grilling
Status: open
Map: [Work graph and the architecture review agent](../map.md)

## Question

Which files become work items on the work graph, and how does the generator find the links between them?

- **Item types.** Review item; plan (`docs/plans/*.md`); spec (`.scratch/<slug>/spec.md`); issue (`.scratch/<slug>/issues/NN-*.md`); wayfinder map and ticket (`.scratch/<effort>/map.md` and its `issues/`). Decision records (`docs/adr/*.md`) are nodes without a status, shown for reference, as [Which next steps a work item suggests, and what the copy button copies](01-next-steps-and-the-copied-command.md) settled. Is a feature (the "function" in the user's "function, then spec, then ticket") an item of its own, the `.scratch/<slug>/` folder, or the plan?
- **Commits.** Nodes on the graph, or a list inside an item's panel? If commits are not nodes, `split-release-into-burp-and-default` loses its only link: does it stay?
- **Link rules.** Which of these count: same folder; same slug (`docs/plans/report-acceptance.md` and `.scratch/report-acceptance/`); a markdown link from one item file to another; an explicit `Links:` line. Rules that need no edits matter, because other sessions' uncommitted files, such as `docs/plans/no-findings-report.md`, cannot be edited from here.
- **Direction.** A copied command lists the items one step up, the ones an item came from, after `context:`. So every link must say which side came from which. Which link rules give a direction (a ticket in a map's folder came from the map), and is there any link without one?
- **New items.** The starting set is the items created since `663d12d` that link to something. For items made later: is the cutoff a fixed commit in the script, and does an item with no link yet stay hidden or show apart from the rest?

Test the answer on the real items: the report-acceptance plan and its four issues; decision record 0001, commit `89744e6` and the previous-proof-of-concept import issue; the no-findings plan and decision record 0002; the four review items in [the 2026-10-02 review report](../../architecture-review/2026-10-02-report.html); this map and its tickets.
