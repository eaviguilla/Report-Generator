# What a mattpocock/skills update does to a skill edited here

Type: research
Status: open
Map: [Work graph and the architecture review agent](../map.md)

## Question

The skills listed in `skills-lock.json` came from `mattpocock/skills` (commit `663d12d`), each pinned by a hash. If one of them, such as `improve-codebase-architecture`, is edited here, what does the next update do to the edit: overwrite it, warn, skip the skill, or refuse? Which ways of changing a skill's behavior survive updates: editing in place, a local skill or agent that wraps it, a fork, or something the install tool provides?

[How the architecture review files its items](07-how-the-architecture-review-files-its-items.md) depends on this: it decides whether the review agent edits Matt's skill or wraps it.
