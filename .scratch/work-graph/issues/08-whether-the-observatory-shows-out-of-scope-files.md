# Whether the observatory shows out-of-scope files

Type: grilling
Status: done
Map: [Observatory and the architecture review](../map.md)

## Question

When `/triage` turns down a feature idea, it writes one file for that idea in `.out-of-scope/`. The file says why, and its Prior requests list names every request that asked for the idea. Does the observatory show these out-of-scope files, and if it does, how does a request link to one?

## Answer

Settled with the user on 2026-10-03, through `/grilling` and `/domain-modeling`.

### What an out-of-scope file is

[Matt's triage instructions](../../../.claude/skills/triage/OUT-OF-SCOPE.md) keep one file per turned-down idea, not one per request, so a later request for the same idea joins the same file. Only `/triage` writes them, and only for a feature request it turns down. A bug, or a request for something already built, gets no file. None exist yet.

The architecture review never writes one. When you turn down one of its recommendations for a reason a later review needs, [its instructions](../../../.claude/skills/improve-codebase-architecture/SKILL.md) offer a decision record instead, and the observatory already shows decision records. The spec this map leads to therefore does not depend on this answer, and the observatory change is built on its own.

### When the observatory shows one

- An out-of-scope file is a node with no status, like a decision record. The observatory draws it only while an open item names it in a `From:` line. Open means any status except `done` and `wontfix`. A file named only by finished items, or by nothing, stays off the page.
- The link is the existing "came from" link, a `From:` line in the request, which is the newer item. [The previous-proof-of-concept import issue](../../import-previous-poc-environments/issues/01-previous-poc-headings-read-as-current-environments.md) names decision record 0001 the same way.
- The out-of-scope file goes into the request's `context:`, so the session that takes up the request reads why a similar idea was turned down.
- A fourth kind of link, such as `Turned down before:`, would state the meaning exactly. It would also need a new line style, a new rule for sessions and a legend entry, and the panel can say the same thing in words.
- Two other answers were dropped. Leaving these files off the page would keep the old reasons out of a similar request's `context:`. Showing every file would mean reading links from the Prior requests list in a file's body, which [What a work item is, and how a link is recorded](03-what-a-work-item-is-and-how-a-link-is-recorded.md) ruled out.

### What triage does with a matching request

When `/triage` finds that a new request matches an out-of-scope file, you give one of three answers.

| Answer | The request | The out-of-scope file |
|---|---|---|
| Still no | closes as `wontfix` and joins the file's Prior requests list | stays; the page does not draw it |
| A different idea | goes ahead, with a `From:` line naming the file | stays; the page draws it while the request is open |
| You changed your mind | goes ahead, with the file's reasons and Prior requests list copied into a comment; no `From:` line | deleted, as Matt's instructions say |

Copying before deleting keeps the old reasons with the request, in one step taken by the session that made the decision. Keeping the file until the request finished was dropped. It needed a "being reconsidered" line in the file, and a cleanup that a later session would have to remember.

### For the build

Built through [Show out-of-scope files on the observatory](../../observatory/issues/01-show-out-of-scope-files.md), separate from the architecture review spec. The observatory learns to draw these files, and `docs/agents/issue-tracker.md` gains the rules for a request that goes ahead.