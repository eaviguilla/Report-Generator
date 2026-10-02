# Which layout shows the work items best

Type: prototype
Status: open
Blocked by: 03
Map: [Work graph and the architecture review agent](../map.md)

## Question

How should the work graph look? Build two or three very different layouts of the real work items on one throwaway page with a switcher, following the UI branch of `/prototype`, and let the user pick one.

- **Layouts to try.** A force-directed graph, like `app/graphify-out/graph.html`; a left-to-right flow by stage (idea, plan or spec, tickets, commits); swimlanes, one lane per thread.
- **Every layout has** the click panel: description, status, and the next steps, main one first, each with its reason and a working copy button. The settled rules are in [Which next steps a work item suggests, and what the copy button copies](01-next-steps-and-the-copied-command.md).
- **Statuses.** How the seven official statuses look, how finished items step back, and how a blocked item shows what it waits for. This moved here from [Does a spec or map take its status from its tickets?](04-does-a-spec-or-map-take-its-status-from-its-tickets.md)
- **Data.** The item types and links from [What a work item is, and how a link is recorded](03-what-a-work-item-is-and-how-a-link-is-recorded.md), written into the prototype by hand; the generator does not exist yet.
- **Check in the user's browser** that the page works when opened from disk, and that copying works there.
- **Note** which graph library each layout needs, and whether it can be copied into the repo. This feeds the open question about the library in the map's "Not yet specified".

Capture the prototype as `/prototype` says (a throwaway branch, out of main) without switching this checkout's branch.
