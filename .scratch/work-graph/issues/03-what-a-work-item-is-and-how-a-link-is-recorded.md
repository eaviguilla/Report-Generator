# What a work item is, and how a link is recorded

Type: grilling
Status: resolved
Map: [Observatory and the architecture review](../map.md)

## Question

Which files become work items on the work graph, and how does the generator find the links between them?

- **Item types.** Review item; plan (`docs/plans/*.md`); spec (`.scratch/<slug>/spec.md`); issue (`.scratch/<slug>/issues/NN-*.md`); wayfinder map and ticket (`.scratch/<effort>/map.md` and its `issues/`). Decision records (`docs/adr/*.md`) are nodes without a status, shown for reference, as [Which next steps a work item suggests, and what the copy button copies](01-next-steps-and-the-copied-command.md) settled. Is a feature (the "function" in the user's "function, then spec, then ticket") an item of its own, the `.scratch/<slug>/` folder, or the plan?
- **Commits.** Nodes on the graph, or a list inside an item's panel? If commits are not nodes, `split-release-into-burp-and-default` loses its only link: does it stay?
- **Link rules.** Which of these count: same folder; same slug (`docs/plans/report-acceptance.md` and `.scratch/report-acceptance/`); a markdown link from one item file to another; an explicit `Links:` line. Rules that need no edits matter, because other sessions' uncommitted files, such as `docs/plans/no-findings-report.md`, cannot be edited from here.
- **Direction.** A copied command lists the items one step up, the ones an item came from, after `context:`. So every link must say which side came from which. Which link rules give a direction (a ticket in a map's folder came from the map), and is there any link without one?
- **New items.** The starting set is the items created since `663d12d` that link to something. For items made later: is the cutoff a fixed commit in the script, and does an item with no link yet stay hidden or show apart from the rest?

Test the answer on the real items: the report-acceptance plan and its four issues; decision record 0001, commit `89744e6` and the previous-proof-of-concept import issue; the no-findings plan and decision record 0002; the four review items in [the 2026-10-02 review report](../../architecture-review/2026-10-02-report.html); this map and its tickets.

## Answer

Settled with the user on 2026-10-03, through `/grilling` and `/domain-modeling`.

### Nodes

Work items are review items, plans, specs, issues, and wayfinder maps and tickets. Decision records are nodes without a status. The generator reads the type from the path:

| Path | Node |
|---|---|
| `.scratch/architecture-review/issues/NN-*.md` | review item |
| `docs/plans/*.md` | plan |
| `.scratch/<slug>/spec.md` | spec |
| `.scratch/<slug>/map.md` | wayfinder map |
| `.scratch/<slug>/issues/NN-*.md`, in a folder that has a `map.md` | wayfinder ticket |
| any other `.scratch/<slug>/issues/NN-*.md` | issue |
| `docs/adr/NNNN-*.md` | decision record |

- A feature has no node of its own. Items joined by links form a thread, drawn as one group. The item at the top of a thread, where the idea was first written down, stands for the feature. In the report-acceptance thread that is review item 02, then the plan, then its four issues.
- These are not nodes: a `.scratch/<slug>/` folder, the review's `report.html` (each review item links to its section), research notes and prototypes kept in a folder, reference docs such as `docs/DATA_MAP.md`, code, and commits.
- Commits never make a link. Commit `f6c215d` added both the no-findings plan and this whole map, so a link by commit would join two unrelated threads. Whether an item's panel lists the commits that changed its file is a question for [Which layout shows the work items best](06-which-layout-shows-the-work-items-best.md).

### Which items show

- Every work item and decision record created since `663d12d` shows. The script holds that commit as one constant, and an item counts when its file did not exist at that commit. A new item shows on the next run, committed or not.
- An item with no link shows as a group of its own. Hiding unlinked items would hide open work: the split-release plan, whose status line still says `in progress`, the previous-proof-of-concept import issue, and review items 03 and 04 once they are filed. This drops "that link to at least one other item" from the starting set recorded while charting.

### Links

There are three kinds of link. Each one is a header line, written once, in one of the two items. The generator never reads links in the body, because a body link does not say which relation it means.

| Link | Meaning | Recorded as | Goes into the `context:` of |
|---|---|---|---|
| came from | this item was made from that one | the folder, or `From:` in the newer item | the newer item |
| blocked by | that item must finish first, because this one needs its result | `Blocked by:` in the waiting item | the waiting item |
| merged into | this item closed because another took over its question or work; its status becomes `wontfix` | `Merged into:` in the closed item | the item that took it over |

- **Folder.** An issue in `.scratch/<slug>/issues/` came from that folder's `spec.md` or `map.md`. In a folder with neither, it came from `docs/plans/<slug>.md` when that plan exists. So `/to-tickets` and `/wayfinder` record where their tickets came from without writing a line.
- **Lines.** `From:`, `Blocked by:` and `Merged into:` sit beside `Status:` with the item's other header lines. In a plan they go inside the status blockquote, and in a decision record under the title. They hold markdown links. `Blocked by:` also takes the numbers or titles of tickets in the same folder, plain or bold, as `/wayfinder` and `/to-tickets` write it.
- **Direction.** The name of the line gives each link its direction. Text such as "handed on", "as 01 settled" or "see" makes no link. The tickets that use it already share a thread through their map, and the map sums up and links each resolved ticket.
- **Context.** A copied command's `context:` lists the items a work item needs: the ones it came from, the ones blocking it, and the ones merged into it. This widens the "items it came from" of [Which next steps a work item suggests, and what the copy button copies](01-next-steps-and-the-copied-command.md). Items made from it stay out.
- **Targets outside the graph.** A line that names an item created before `663d12d` still puts that item into `context:`, but the page does not draw it. A line that names a missing file, or a file that is not a node, shows a warning on the item.

### Tested on the real items

| Item | Link | Recorded by |
|---|---|---|
| the four report-acceptance issues | came from `docs/plans/report-acceptance.md` | the folder |
| this map's seven tickets | came from `map.md` | the folder |
| tickets 04 and 06 | blocked by ticket 03 | `Blocked by: 03`, already written |
| `docs/plans/report-acceptance.md` | came from review item 02 | a `From:` line, added once the review items are filed |
| decision record 0002 | came from `docs/plans/no-findings-report.md` | a `From:` line, to add |
| the previous-proof-of-concept import issue | came from decision record 0001 | a `From:` line, to add |
| ticket 05 | merged into ticket 01 | a `Merged into:` line, to add |
| ticket 02 | merged into ticket 07 | a `Merged into:` line, to add |
| the split-release and no-findings plans, this map, review items 01, 03 and 04 | none | nothing to add |

The import issue was committed in the same second as the supporting-image change, `89744e6`, and its notes say it was kept separate from that change. The change has no plan or issue, so decision record 0001 is its only record. The record states the print rule that import works backwards from.

### Who writes the lines

- `/to-tickets` and `/wayfinder` need nothing new. The folder records where their tickets came from, and both already write `Blocked by:`.
- `docs/agents/issue-tracker.md` gets a rule beside the next-steps rule: write `From:` when you make an item from another, and `Merged into:` when you close an item into another. `/to-spec`, `/triage` and the other skills that write to the tracker read that file.
- The "Implementing a plan" part of `.github/copilot-instructions.md` gets the same rule for plans.
- `.claude/skills/domain-modeling/ADR-FORMAT.md` gets an optional `From:` line under the title, edited in place, because `/domain-modeling` reads neither file.

### For the build

- Build the generator with the node table, the folder rule, the three lines in their plain, bold and blockquote forms, the cutoff constant, and the warnings.
- Add the lines listed in the table above. The `Map:` lines in this map's tickets and the "From" sentence that ends each report-acceptance issue can stay, because the folder already covers them.
- Write the three rules.

### Handed on

- How blocked and merged items look, and whether the panel lists commits: [Which layout shows the work items best](06-which-layout-shows-the-work-items-best.md).
- Whether a spec or map is finished when its tickets are, now that the links say which items came from it: [Does a spec or map take its status from its tickets?](04-does-a-spec-or-map-take-its-status-from-its-tickets.md)
