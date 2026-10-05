# Show out-of-scope files on the Star Map

Status: done
From: [Whether the Star Map shows out-of-scope files](../../work-graph/issues/08-whether-the-star-map-shows-out-of-scope-files.md)

## What to build

`/triage` writes one file per turned-down feature idea in `.out-of-scope/`. The Star Map should draw such a file while an open work item came from it, and the tracker rules should tell `/triage` sessions when to write that link. The ticket this came from gives the reasons.

In `tools/star_map/`:

- Read `.out-of-scope/*.md` as nodes with no status, like decision records.
- Draw one only while an open item names it in a `From:` line. Open means any status except `done` and `wontfix`. A file named only by finished items, or by nothing, gets no star.
- Give it the decision record's four-pointed shape in a colour no other star uses, so a turned-down idea is not mistaken for a decision that stands, and add it to the legend.
- A `From:` line naming an out-of-scope file no longer warns that it "is not a work item or decision record". The file goes into the item's `context:`, and the panel says that an idea like this was turned down before.

In `docs/agents/issue-tracker.md`, which Matt's skills read before writing to the tracker, add what happens when `/triage` lets a request go ahead even though it matches an out-of-scope file:

- If it is a different idea, the request gets a `From:` line naming the out-of-scope file, and the file stays.
- If you changed your mind about the idea, copy the file's reasons and Prior requests list into a comment in the request's file, then delete the out-of-scope file, as Matt's instructions say. The request gets no `From:` line.

Cover the new reading rules in `tests.test_star_map`: the star shows while an open item came from the file, goes once that item finishes, and the file sits in `context:` without a warning.

## Next steps

## Answer

Implemented. The Star Map reads `.out-of-scope/*.md` as statusless nodes and draws each only while an open work item links it with `From:`. The detail panel lists the file as context and says the idea was turned down before. Its star uses a distinct pink four-point shape and has its own legend entry.

The issue tracker now tells `/triage` to keep and link the file when proceeding with a different idea, or copy its reasons and Prior requests into a comment and delete it when the decision changes. The latter case has no `From:` link.
