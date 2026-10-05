# Choosing a next step

An open work item lists its next steps in a `## Next steps` section of its own file, main one first, as
[issue-tracker.md](issue-tracker.md) describes. Each step names one of Matt's skills and says why in one
short sentence. The Star Map, `tools/star_map/star_map.py`, turns each step into a command to
copy: `/<skill> <item> context: <items it needs>`.

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
- Goal known, shape unclear: `/grill-with-docs`, then `/to-spec`, `/to-tickets` and `/implement`.
- Too big for one session: `/wayfinder`, then `/to-spec`, `/to-tickets` and `/implement`.
- A bug: `/triage`, or `/diagnosing-bugs` when the cause is unknown, then `/implement`.

`/to-spec` and `/to-tickets` do not fill gaps. `/to-spec` writes down what is already decided, and
`/to-tickets` splits it. When information is missing, a step that gathers it comes first.
