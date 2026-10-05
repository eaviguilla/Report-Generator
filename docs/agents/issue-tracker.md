# Issue tracker: Local Markdown

Issues and specs for this repo live as markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`, never a single combined tickets file
- Triage state is recorded as a `Status:` line near the top of each issue file, using the statuses below
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## Statuses

Every work item uses one set of statuses: review items, plans in `docs/plans/`, specs, issues, and wayfinder maps and tickets. Decision records in `docs/adr/` have no status.

| Status | Meaning | Finished |
|---|---|---|
| `needs-triage` | Filed; nobody has looked at it yet | no |
| `needs-info` | Waiting for an answer or a decision before it can move | no |
| `ready-for-agent` | Clear enough for an agent to do alone | no |
| `ready-for-human` | Clear enough, but the user needs to be in the session | no |
| `in-progress` | A session is working on it now | no |
| `done` | Finished | yes |
| `wontfix` | Will not be done: rejected, replaced, or ruled out of scope | yes |

- `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human` and `wontfix` are the triage labels in [triage-labels.md](triage-labels.md). `in-progress` and `done` fill the two states those labels lack.
- Set `done` when an item's own work is finished. That closes it. Finishing the items made from it does not finish it.
- Blocked is not a status. It comes from the `Blocked by:` line and clears when every blocker is finished.

## Next steps

An open item keeps its suggested next steps in its own file, main one first. Whoever last changes the item keeps the list current:

```markdown
## Next steps

1. `/grill-with-docs`: The terms are still unclear.
2. `/prototype`: A rough page would show faster whether the layout works.
```

Each step names one of Matt's skills and gives a short reason. A finished item has no next steps. [next-steps.md](next-steps.md) says which skill fits when.

## Links between items

Three header lines link one item to another. They sit beside `Status:`. In a plan they go inside the status blockquote, and in a decision record under the title. Each holds markdown links.

- `From:` in an item you made from another. Skip it when the folder already says so: an issue in a spec's or map's folder, or in `.scratch/<slug>/` beside `docs/plans/<slug>.md`, came from that file.
- `Blocked by:` in an item that must wait for another. It also takes the numbers or titles of tickets in the same folder.
- `Merged into:` in an item you close because another took over its question or work. Set its status to `wontfix`.

`tools/star_map/star_map.py` draws the work items as the Star Map from these statuses, links and next steps.

When `/triage` finds that a request matches a file in `.out-of-scope/` and decides to let it go ahead:

- If the request is for a different idea, add a `From:` line linking to the out-of-scope file and leave that file in place.
- If you changed your mind about the same idea, copy the file's reasons and Prior requests list into a comment in the request's file, then delete the out-of-scope file. Do not add a `From:` line.

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/` (creating the directory if needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a file with one **child** file per ticket.

- **Map**: `.scratch/<effort>/map.md` (the Notes / Decisions-so-far / Fog body), with a `Status:` line under the title.
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the question in the body. A `Type:` line records the ticket type (`research`/`prototype`/`grilling`/`task`); a `Status:` line records its status. A new ticket starts at `ready-for-agent` when the agent can resolve it alone (research, or a task it does itself), else at `ready-for-human`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when every file it lists is `done` or `wontfix`.
- **Frontier**: scan `.scratch/<effort>/issues/` for files whose status is `ready-for-agent` or `ready-for-human` and that are unblocked; first by number wins.
- **Claim**: set `Status: in-progress` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set `Status: done`, then append a context pointer (gist + link) to the map's Decisions-so-far in `map.md`.
- **Out of scope**: set `Status: wontfix` and add a line to the map's Out of scope section.
