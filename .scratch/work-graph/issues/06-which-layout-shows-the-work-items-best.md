# Which layout shows the work items best

Type: prototype
Status: done
Blocked by: 03
Map: [Star Map and the architecture review](../map.md)

## Question

How should the work graph look? Build two or three very different layouts of the real work items on one throwaway page with a switcher, following the UI branch of `/prototype`, and let the user pick one.

- **Layouts to try.** A force-directed graph, like `app/graphify-out/graph.html`; a left-to-right flow by stage (idea, plan or spec, tickets); swimlanes, one lane per thread.
- **Every layout has** the click panel: description, status, and the next steps, main one first, each with its reason and a working copy button. The settled rules are in [Which next steps a work item suggests, and what the copy button copies](01-next-steps-and-the-copied-command.md).
- **Statuses.** How the seven official statuses look, how finished items step back, how a blocked item shows what it waits for, and how a merged item points to the one that took it over. Also show a separate, informational cue when all direct children are finished; this does not change the parent's explicit status, as settled in [Does a spec or map take its status from its tickets?](04-does-a-spec-or-map-take-its-status-from-its-tickets.md).
- **Data.** The node types and the three kinds of link from [What a work item is, and how a link is recorded](03-what-a-work-item-is-and-how-a-link-is-recorded.md), written into the prototype by hand; the generator does not exist yet. Commits are not nodes; try whether the panel should list the commits that changed an item's file.
- **Check in the user's browser** that the page works when opened from disk, and that copying works there.
- **Note** which graph library each layout needs, and whether it can be copied into the repo. This feeds the open question about the library in the map's "Not yet specified".

Capture the prototype as `/prototype` says (a throwaway branch, out of main) without switching this checkout's branch.

## Answer

Settled with the user on 2026-10-03, through `/prototype`. The prototype lived on a throwaway branch, which the user had deleted once the built Star Map replaced it. Its commits were `269e159`, with all three layouts and the three line styles, and `707bec0`, with only the chosen star map.

### Layout

- The page is a force-directed graph drawn as a star map, after the star map in [rengwu/wayfinder-maps](https://github.com/rengwu/wayfinder-maps) and its [design notes](https://github.com/rengwu/wayfinder-maps/blob/main/docs/starmap-design.md). The flow by stage and the lanes by thread were tried and dropped.
- Each thread gets its own small force layout, and the threads are packed in rows, so groups never overlap. A fixed seed gives the same records the same layout on every run.
- Each thread sits in a faint coloured cloud named after its top item, and the top item is the biggest star in it. An item with no link is a lone star.
- The sky is dark, with three layers of background stars that move at different speeds when you pan. Scrolling zooms, dragging pans or moves a star, and Fit brings everything back. Labels shrink less than the map when you zoom. Hovering a star dims everything not linked to it.
- Clicking a star opens the side panel: description, status, next steps with the main one first and a Copy button each, the context items, and the items made from it. A bar at the top counts the items by status.

### Stars

| Status | Star |
|---|---|
| `needs-triage` | plain white, flickering; nobody has classified it yet |
| `needs-info` | lavender in a slow haze; clouded until someone answers |
| `ready-for-agent` | bright cyan, pulsing |
| `ready-for-human` | bright gold, pulsing |
| `in-progress` | orange, with two turning orbit rings and a small moon |
| `done` | small and dim green; burned down |
| `wontfix` | tiny grey, with an empty ring |
| decision record | four-pointed pale gold sparkle, steady, no status |

- The two ready kinds are the brightest, because they are what can be picked up now. Finished items shrink and dim, and their names fade.
- A blocked item keeps its status colour but dims, gets a red dashed ring, and its name gains "waits for ticket 03" in red.
- When everything made from an item is finished, a thin green ring with a tick appears around it. The star keeps its own status colour, as [Does a spec or map take its status from its tickets?](04-does-a-spec-or-map-take-its-status-from-its-tickets.md) settled.

### Links

Colour and dashes, chosen over colour only and dashes only.

| Link | Line |
|---|---|
| came from | thin solid silver, with an arrow halfway toward the newer item; dots of light drift along it while the newer item is open |
| blocked by, blocker open | dashed red, with an arrow into the waiting item |
| blocked by, blocker finished | dashed dim grey |
| merged into | dotted pink, with an arrow into the item that took it over |

The pattern alone tells the three kinds apart, so the page still works for colour-blind readers, and red shows only while a block is in force.

### Name, commits and library

- **Name.** The page is the Star Map. It was first named the observatory, chosen over star chart, lodestar and keeping "work graph", and the user renamed it Star Map on 2026-10-05. The tool's folder is `tools/star_map/`. The effort folder `.scratch/work-graph/` keeps its name, because every ticket links to it.
- **Commits.** The panel lists no commits. The page tracks the work items still needed to finish, and commit subjects mislead: commit `f6c215d`, about no-findings reports, added this whole map.
- **Library.** None. The prototype is SVG and CSS animation written by hand, loads nothing from the internet, and opens from disk. vis-network, the graphify page's library, is one 702,611-byte file under Apache-2.0 or MIT and could be copied in, but nothing needs it. This settles the map's open question about a graph library.

### Opened from disk

In VS Code's built-in browser the page loads from a `file:` URL, the address keeps the layout and the selected item, and Copy works through the Clipboard API. If a browser refuses that, the page falls back to the older copy command, then selects the text for Cmd+C or Ctrl+C. Safari, Firefox and the Windows browsers are not checked. Animation stops when the system asks for reduced motion.

### For the build

- Build the Star Map from the prototype's design. Do not copy its code, which has no tests and holds hand-written items.
- Name the page Star Map, the tool `star_map.py`, and its folder `tools/star_map/`.
- Check Copy from disk in the default browser on macOS and on Windows.

## Comments

- 2026-10-03: Prototype built at `.scratch/work-graph/prototype/layouts.html`, uncommitted, waiting for the user's pick. Three layouts: A is a graph with one force layout per thread, B is a left-to-right flow by stage, and C is lanes by thread with status columns. The bar's Data menu shows two real states besides today: ticket 03 still open, so tickets 04 and 06 show as blocked, and ticket 06 resolved, so the map shows the cue for everything made from it being finished. Review items are not filed yet, so their paths and statuses are samples, and every next step is written by hand. In VS Code's built-in browser, opened from disk, the URL updates and Copy works through the Clipboard API. The user's own browser is not checked yet.
- 2026-10-03: The user picked layout A, the graph, and asked for a less plain look, taking ideas from the star map in [rengwu/wayfinder-maps](https://github.com/rengwu/wayfinder-maps). A is now a star map: a dark sky, one kind of star per status, a faint nebula per thread named after its top item, and curved links with an arrow halfway. A Lines menu in the bar switches between colour and dashes, colour only, and dashes only. Still no library, only SVG and CSS animation. Waiting for the user's choice of line style.
- 2026-10-03: The user picked colour and dashes for the lines. Next the user decides the page's name; "work graph" is the current one.
- 2026-10-03: The user named the page and dropped the commit list. The prototype went to a throwaway branch and left the working tree. Resolved.
- 2026-10-03: The user asked to keep only the star map. Commit `707bec0` on the branch drops the flow and lanes layouts, the line-style menu and the commit list.
- 2026-10-03: The user asked to build the Star Map now, ahead of the spec. `tools/star_map/star_map.py` reads the work item files and writes `star_map.html` from `page.html`, and `tests/test_star_map.py` covers its reading rules. One change from "For the build": the drawing code in `page.html` is the prototype's, cleaned up, because it was already checked in the browser. The hand-written items are gone. The same build added a status line to the map, the four link lines ticket 03 listed, and next steps in the eight open items.
- 2026-10-03: The user had the prototype branch deleted. It was never pushed.
- 2026-10-05: The user renamed the page from Observatory to Star Map. The tool, its test and the build ticket's folder moved to `tools/star_map/star_map.py`, `tests/test_star_map.py` and `.scratch/star-map/`.
