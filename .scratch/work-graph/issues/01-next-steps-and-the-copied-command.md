# Which next steps a work item suggests, and what the copy button copies

Type: grilling
Status: resolved
Map: [Work graph and the architecture review agent](../map.md)

## Question

For each work item, which next steps does the page suggest, and what exact text does the copy button produce?

Charting first asked a research question here: how Claude Code and Copilot start a skill or agent from pasted text. The user dropped it as a rabbit hole. A slash command with arguments already starts a skill in both tools; this grilling was itself started in Copilot as `/grill-with-docs` with arguments. The ticket became a grilling and absorbed [What the copy button puts on the clipboard](05-what-the-copy-button-copies.md).

## Answer

Settled with the user on 2026-10-02, through `/grill-with-docs`.

### Next steps

- An open work item has one or more next steps. Each names one of Matt's skills and gives a short reason, and the first is the main suggestion. Local agents are not suggested.
- A finished item has no next steps, so it has nothing to copy.
- The session that last changed an item keeps the item's next steps in its file:

  ```markdown
  ## Next steps

  1. `/grill-with-docs`: There are still unclear definitions of how a node looks before implementation.
  2. `/prototype`: A rough page would show faster whether the layout works.
  ```

- A rule in `docs/agents/issue-tracker.md` tells every session to keep that list current; Matt's skills read that file before writing to the tracker. The page never works out next steps by itself: an open item without the list shows "no next steps written".

### The copied command

- `/<skill> <item> context: <item> <item>`, and nothing else. Paths are relative to the repository root. The item file names only the skill; the page adds the paths.
- The context is the items one step up, the ones the item came from: an issue's plan or spec, a ticket's map, a plan's review item. Not the items made from it, and not code files, which the item's own file already names. An item with nothing above it gets no `context:` part.
- `context:` stops a skill from taking a context file for the work. `/implement`'s only instruction is "Implement the work described by the user in the spec or tickets", so given bare paths it could build a whole plan instead of the one issue.
- The same text works in Claude Code and in Copilot.

### Official statuses

Every work item uses one set: review items, plans, specs, issues, wayfinder maps and wayfinder tickets.

| Status | Meaning | Finished |
|---|---|---|
| `needs-triage` | Filed; nobody has looked at it yet | no |
| `needs-info` | Waiting for an answer or a decision before it can move | no |
| `ready-for-agent` | Clear enough for an agent to do alone | no |
| `ready-for-human` | Clear enough, but the user needs to be in the session | no |
| `in-progress` | A session is working on it now | no |
| `done` | Finished | yes |
| `wontfix` | Will not be done: rejected, replaced, or ruled out of scope | yes |

- `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human` and `wontfix` are Matt's triage words unchanged (`docs/agents/triage-labels.md`), so his skills keep writing them. `in-progress` and `done` fill the two states his local tracker has no word for.
- The old words retire.
  - Plans: `planning` → `needs-info`, `agreed` → `ready-for-agent`, `in progress` → `in-progress`, `shipped` → `done`, `superseded` and `abandoned` → `wontfix`.
  - Wayfinder tickets: unclaimed → `ready-for-human` (grilling, prototype, a task that needs the user) or `ready-for-agent` (research, a task the agent does alone); `claimed` → `in-progress`; `resolved` → `done`.
- `done` also closes a plain issue. Today the local tracker defines a finished state only for wayfinder tickets, and `/implement` only commits.
- Decision records have no status. They record a decision, not work to do, and the page shows them for reference.
- Blocked is not a status. It comes from the `Blocked by:` line and clears when the blocker is finished.

### Choosing a next step

This guide goes into `docs/agents/next-steps.md`, linked from `docs/agents/issue-tracker.md`. It was drafted from each skill's own description.

| Skill | Suggest it when |
|---|---|
| `/grill-with-docs` | The goal is known but the shape is not: terms, rules or the approach are unclear. It records decisions and terms as they are settled. |
| `/prototype` | The open question is how something looks or behaves, and a rough working version would answer it faster than talking. |
| `/research` | A decision waits on a fact from outside the repo, such as how a library or a tool behaves. |
| `/wayfinder` | The work is too big or too unclear for one session: many decisions that depend on each other. |
| `/to-spec` | The decisions are made and need writing down as one spec before building. It asks no new questions. |
| `/to-tickets` | A spec or plan is bigger than one session's build and needs splitting into tickets. |
| `/implement` | The item is small and clear enough to build now, or it is one ticket from a spec. It runs `/code-review` at the end. |
| `/implement-spec` | A spec is split into tickets, and the user wants all of them built in one run on one branch. |
| `/triage` | A new bug report or request that nobody has evaluated. |
| `/diagnosing-bugs` | Something is broken or slow and the cause is unknown. |

Typical routes:

- Small and clear: `/implement`.
- Goal known, shape unclear: `/grill-with-docs` → `/to-spec` → `/to-tickets` → `/implement`.
- Too big for one session: `/wayfinder` → `/to-spec` → `/to-tickets` → `/implement`.
- A bug: `/triage`, or `/diagnosing-bugs` when the cause is unknown, then `/implement`.

`/to-spec` and `/to-tickets` do not fill gaps: `/to-spec` writes down what is already decided, and `/to-tickets` splits it. When information is missing, a step that gathers it comes first.

### For the build

- Change the files that define the old status words: `.github/copilot-instructions.md`, `CLAUDE.md`, `.github/prompts/plan-change.prompt.md`, the invader and loremaster agents in both `.github/agents/` and `.claude/agents/`, and `docs/agents/issue-tracker.md`. Move every plan's status line, and this map's tickets, to the new words. No script or test reads the old words (checked on 2026-10-02).
- Add the close rule and the next-steps rule to `docs/agents/issue-tracker.md`, and write `docs/agents/next-steps.md`.

### Handed on

- Links need a direction, from an item to the one it came from: [What a work item is, and how a link is recorded](03-what-a-work-item-is-and-how-a-link-is-recorded.md).
- When a spec or map is finished: [Does a spec or map take its status from its tickets?](04-does-a-spec-or-map-take-its-status-from-its-tickets.md)
- How the seven statuses look on the page: [Which layout shows the work items best](06-which-layout-shows-the-work-items-best.md).
