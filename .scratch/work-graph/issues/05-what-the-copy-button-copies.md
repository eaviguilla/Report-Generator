# What the copy button puts on the clipboard

Type: grilling
Status: resolved
Map: [Work graph and the architecture review agent](../map.md)

## Question

What exact text does the copy button produce for a next step, so that pasting it into a new chat starts the right skill or agent on the right file?

- **The user's words.** The prompt "starts with the skill or agent to call and either explains or points to the file".
- **Charting's recommendation.** First line: the slash command, or a sentence naming the agent. Then the file path, then one line saying what the session should do. Point to the file instead of pasting its contents, so the new session reads the current version.
- **To decide.** One text for both Claude Code and Copilot, or one per tool; what else the prompt carries, such as the map path for a wayfinder ticket; how long it may get.

## Answer

Merged into [Which next steps a work item suggests, and what the copy button copies](01-next-steps-and-the-copied-command.md), which settled the copied command with the user on 2026-10-02.
