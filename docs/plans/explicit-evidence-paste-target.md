# Explicit evidence paste target

> **Status:** shipped · 2026-09-21 · `e998ab5`

## Request

Pasting a screenshot lands somewhere the tester did not choose, and an image copied from OneNote
often does not paste at all. Make the destination explicit: a paste goes where the tester said it
should go, or nowhere. Tell them what to do when it goes nowhere, in the words this app already uses.

## How it works today, and why it misleads

There is no target. A paste with nothing focused runs one line:

```js
pane?.querySelector('.content-block:not([data-content-type="previous_proof_of_concept"]) .evidence-tile:not(.has-evidence)')?.onpaste?.(event);
```

`querySelector` returns the **first** match in the document, so the image lands in the first empty
evidence image anywhere in the pane — not the one on screen, not the one being looked at. Meanwhile
every empty tile displays *"Drop, paste or click"*, so they all advertise a paste while only one can
accept it. The label is true on exactly one tile and false on the rest.

Two consequences fall out of the same line. `:not(.has-evidence)` means a filled image can never be
pasted over, at all. And the tile's own `onpaste` fires only when the tile has focus, which a
`<label>` does not take, so the fallback is doing nearly all the work in practice.

**The OneNote case is separate and only partly ours.** The handler reads `clipboardData.files` and
nothing else. When OneNote puts HTML and RTF on the clipboard rather than a bitmap, there is no file
to find and the paste is correctly ignored — but silently, which is indistinguishable from the app
being broken. Widening that read is tracked below as out of scope for this change; the message is
what makes the silence stop.

## Decisions

Settled with the owner in conversation; this section is the contract.

### A paste goes to the armed image, or nowhere

| Clipboard holds | Armed? | Result |
|---|---|---|
| Image | yes | Lands in that image, empty or filled |
| Image | **no** | **Nothing** — plus the message below |
| Text, focus in a caption | either | Goes to the caption, untouched |
| Text, focus nowhere | either | Nothing, silently |

Images are routed by the armed image; text is routed by focus. They never compete, because neither
can use the other's destination. **An image wins even while the caret is in a caption** — a text box
cannot hold an image, so honouring focus there would throw the screenshot away.

A clipboard carrying both flavours at once, which is what copying a block from OneNote produces,
resolves to the image. The text is ignored.

### Nothing is armed until the tester arms it

No default, no auto-arm on load. The old fallback is deleted rather than narrowed.

Auto-arming the first empty image was considered and rejected: if the page is scrolled, the armed
image can be off screen, and an image landing somewhere invisible is the original bug wearing a
badge.

### One message, and only this one

> **Click an evidence image first, then paste.**

Shown when an **image** is pasted with nothing armed. Never shown for a text paste, which was never
going to reach an image anyway.

**No notification on a successful paste, ever** — empty or filled. That matches today and was
confirmed twice.

*Evidence image* is the owner's wording, taken from the vocabulary already in the readiness panel
and the generation issues (`"Production evidence image required"`). The word *slot* appears nowhere
in this product and must not appear here.

### Recovery is the undo button that already exists

Replacing a filled image is allowed and produces no message, because `uploadImage` is already
wrapped in `trackMutation` and the existing undo restores both `fragment.evidence_id` and the
evidence record. A bespoke undo toast was proposed and dropped — it would duplicate a working
control.

This holds only because the old record survives: `uploadImage` never calls
`dropUnreferencedEvidence`, so `report.evidence` keeps the previous entry and the server's
`_drop_orphan_evidence` therefore keeps the previous file. Step 7 protects that property.

### After a paste, the highlight advances

To the next empty image in the same evidence set, visibly. When none remain it disarms, so a further
paste gives the message rather than quietly overwriting what was just placed.

### Wording, and "paste" appears only where pasting works

| Image | Reads |
|---|---|
| Empty, not armed | *Click to choose, or drag an image here* |
| **Empty, armed** | ***Ready — press Ctrl+V to paste*** · *or click to browse* |
| Filled, armed | *Press Ctrl+V to replace this image* |
| Filled, not armed | nothing |

Today's *"Drop, paste or click"* is replaced. The shortcut is spelled per platform — `Ctrl+V` on
Windows, `⌘V` on macOS. The deployment target is Windows and development is on macOS, so hardcoding
either reads wrong on the machine that was not tested.

### Not changing how images are named

Raised and withdrawn. `original_name` keeps its current behaviour on every path.

## Agreed plan

Eight steps. The tree works after each. Nothing here needs Microsoft Word, and nothing touches the
report schema, `provision`, or any Python rule with a JavaScript twin.

- [x] **Step 1 — Track the armed evidence image**

  `app/web/static/app.js`: a `pasteTargetId` holding a `frag_id`, declared beside `reviewTargetId`
  in `continuousEditor()`. It must be an id and not an element, because `render()` rebuilds the pane
  on every caption keystroke and an element reference would be orphaned — the same reason
  `expandedContentTypes` stores types. Cleared when `selectedFindingUid` changes.

  *Test:* none on its own; proved by steps 2 and 3.
  *Invariant:* the value survives a rerender.

- [x] **Step 2 — Arm on click and on focus**

  Clicking anywhere on an evidence card arms it; Tab to the tile arms it. The tile already carries
  `tabIndex = 0`, so keyboard focus needs wiring only.

  The `<label>` conflict is not a conflict: clicking the thumb opens the file picker **and** arms the
  card, and cancelling the picker leaves it armed. Arming must be additive — the caption input, the
  spine buttons and the remove control keep their existing click behaviour.

  *Test:* `tests/test_browser.py` — clicking a card marks it armed; clicking a second moves the mark;
  the caption still takes focus and still accepts typing.
  *Invariant:* no existing control loses its click.

- [x] **Step 3 — Route the paste by what is on the clipboard**

  Replace the document-level fallback. An image reaches the armed image; with nothing armed it
  reaches nothing and the message appears. A text paste is untouched, including inside a caption.

  Keep the `event.defaultPrevented` guard: a rich-text editor that already consumed the paste has
  cancelled it.

  *Test:* the full matrix from *Decisions*, following the existing clipboard-paste browser tests that
  drive `window.heldEvidenceUploads`.
  *Invariant:* with nothing armed, **no image is imported anywhere** — asserted on `report.evidence`
  and on the saved draft, not only on the screen.

- [x] **Step 4 — Allow replacing, and advance after a paste**

  Drop `:not(.has-evidence)` from the target rule, so a filled image can be armed and pasted over.
  After a paste lands, move `pasteTargetId` to the next empty image in the same set; disarm when
  there is none.

  Previous Proof of Concept can now be armed deliberately. Its old exclusion existed to stop a stray
  paste reaching last year's evidence; with no implicit routing there are no stray pastes.

  *Test:* pasting over a filled image replaces it; two pastes fill two images rather than one twice;
  a third paste with the set full shows the message.
  *Invariant:* nothing is replaced that was not armed.

- [x] **Step 5 — Rewrite the tile copy and show the armed state**

  The four states above, plus a visible mark on the armed card. `app/web/static/taste.css` and
  `app/web/static/overrides.css`.

  **Ring precedence must be decided here.** A tile can already be ringed by `.is-incomplete` and by
  `showReviewTarget`. Armed is a third, and three rings on one element need a defined order or the
  card looks broken.

  *Test:* none — CSS is exempt under the repo's scope map.
  *Verification:* screenshot the four states, and diff the armed card's computed outline against a
  neighbouring card read out of the page rather than against constants.

- [x] **Step 6 — Spell the shortcut per platform**

  `Ctrl+V` on Windows, `⌘V` on macOS, in both the tile copy and the message.

  *Test:* a browser assertion that the rendered text matches the running platform, so neither reading
  can regress unnoticed on the platform nobody tested.

- [x] **Step 7 — Stop undo orphaning an evidence file**

  Undo an image replace, then redo: undo removes the new record from `report.evidence` and saves,
  `Workspace._drop_orphan_evidence` then deletes that PNG as unreferenced, and redo restores metadata
  pointing at a file that is gone. `Report.validate_references` does not catch it — it checks that
  referenced ids exist in the metadata, never that the file does.

  This is a pre-existing fault, reachable today only by deliberately re-uploading over a filled
  image. Step 4 makes it reachable with one keystroke, which is why it is folded in rather than
  listed.

  *Test:* `tests/test_browser.py` — replace, undo, redo, and assert the image still renders and the
  file still exists.
  *Invariant:* no undo or redo sequence leaves a fragment pointing at a missing file.

- [x] **Step 8 — Documentation, in the same change**

  `docs/DATA_MAP.md`: that `pasteTargetId` is client-only and never persisted; that arming is the
  sole route by which a pasted image reaches a fragment; and the undo-and-evidence-file relationship
  from step 7, which is the kind of thing otherwise rediscovered as a bug.

  This file: status to `shipped` with the date and commit, checkboxes ticked, and the deviations
  paragraph.

### What this change deliberately does not do

- **No widening of the clipboard read.** `clipboardData.items` and a `data:` URI fallback in
  `text/html` would recover two more OneNote cases; a `file:///` reference and an RTF-only clipboard
  cannot be recovered by any web page, and never will be. Worth its own change once the message makes
  the failures visible enough to judge how often they happen.
- **No change to image naming.** Raised and withdrawn.
- **No notification on a successful paste.**
- **No auto-arming**, on load or otherwise.
- **No new undo mechanism.** The existing button is the recovery path.
- **No schema change**, no new model field, no Python rule with a JavaScript twin.

## What deviated

**Two faults were caught by looking at the running app, not by a test.** Both would have shipped.

- **The platform check read `Ctrl+V` on macOS.** `navigator.userAgentData.platform` returns
  `"macOS"`, and the test was `/Mac|iPhone|iPad/` — case-sensitive, so it never matched. Now `/i`.
  This is exactly the failure the step warned about, and it is worth noting that it was found by
  reading the rendered text out of the page rather than by any assertion.
- **The armed ring was drawn twice**, once by `border-color` and once by an inset shadow. Only the
  border remains, with a soft outer glow.

**The armed wording is shorter than agreed.** *"Ready — press ⌘V to paste"* wrapped inside the 148px
thumbnail column and stranded "paste" on its own line. It now reads *"Press ⌘V to paste"*; the ring
already says "ready", and spending a line saying it twice was what caused the wrap. Measured after
the change: the tile is 110px armed and 110px resting, so arming causes **no layout shift**.

**The filled tile's hint sits in the facts row, not the thumbnail**, because a filled thumbnail holds
the image and has no room.

**Disarming is done in one place instead of three.** The plan said to clear on finding change, which
meant patching three `selectedFindingUid` assignments. Instead `refreshPasteHints` clears the target
when the pane no longer shows that tile, which also covers a collapsed section and a deleted image —
cases the agreed wording would have missed.

**Two existing tests asserted the behaviour this change removes**, and were rewritten rather than
deleted. `test_pasting_with_nothing_focused_fills_the_first_empty_slot` is now
`test_pasting_with_nothing_armed_imports_nothing` and asserts the opposite, on the saved draft as
well as the screen. `test_pasting_a_screenshot_attaches_it_as_evidence` asserted that an empty tile
says "paste"; it now asserts an unarmed tile does **not** and an armed one does.

**The routing test creates its own second empty image.** The fixture has one, and with one image
"landed in the armed image" and "landed in the first empty image" are the same event. It clicks *Add
another screenshot* rather than skipping, which is what it did first and which proved nothing.

**Both routing tests were falsified before being trusted.** The old first-empty-tile routing was
temporarily restored and the two tests were re-run: both failed. Without that check the sub-second
pass was indistinguishable from a test that asserts nothing.

**Step 5's verification was numeric rather than a computed-style diff.** Heights were measured armed
and resting, and the hint text for all four states was read out of the live page. The outline values
themselves were compared by eye against a neighbouring card rather than numerically.

**Not committed.** The working tree also holds unrelated work — `app/models.py`, `app/docx_*.py`,
`app/web/static/manager.js` and a separate plan — so this change was left staged for its owner to
commit rather than swept in with someone else's.

**2026-09-21 follow-up:** Step 3's `event.defaultPrevented` guard was removed because it dropped
an image pasted from a focused rich-text editor; upload completion now also removes both replaced
and deleted-target evidence records when no remaining fragment references them.
