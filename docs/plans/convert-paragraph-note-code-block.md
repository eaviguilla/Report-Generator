# Convert between paragraph, note and code block

> **Status:** shipped · 2026-09-18 · `7da8d7d`

## Request

> create an option for paragraph, note, and code block to be changed to each other. like, if there
> is an existing paragraph fragment with value inside, and the user wants to make it a code block,
> have an option for that user to change the fragment type to note or code block. same with note and
> codeblock. only these three. no changes for numbered list and bullet list.

## Round 1 - Oracle: how it works today

### 1. The three models

All three live in [app/models.py](../../app/models.py), Pydantic v2, `schema_version` `"1.4"`.

| | `ParagraphFragment` | `NoteFragment` | `CodeFragment` |
|---|---|---|---|
| declared at | models.py#L81-L85 | models.py#L109-L112 | models.py#L124-L128 |
| `frag_id` | `StableId` (required) | `StableId` (required) | `StableId` (required) |
| `type` | `Literal["paragraph"]` | `Literal["note"]` | `Literal["code_block"]` |
| payload | `runs: list[Run] = Field(default_factory=list)` | `runs: list[Run] = Field(default_factory=list)` | `text: str = ""` |
| extra | `generated: Literal["status_conclusion","resolved_remediation"] \| None = None` | — | `caption: str \| None = None` |

`Run` (models.py#L74-L78): `text: str` required, plus `bold`, `italic`, `underline`, each `bool = False`.

Paragraph and note carry rich text as `runs`; code carries flat `text: str`. Shapes are identical
between paragraph and note **except** `generated`. Shared fields for note↔code: `frag_id` and `type`
only.

**No validators** on any of the three. The union is **discriminated** (models.py#L137):

```python
Fragment = Annotated[ParagraphFragment | ListFragment | TableFragment | NoteFragment | ImageFragment | CodeFragment | InstanceTitleFragment, Field(discriminator="type")]
```

### 2. How type is decided on load

A true tagged union. Pydantic reads `type`, picks the one class whose `Literal` matches, validates
against that class alone. A missing or unknown `type` fails immediately with a tag error.

**Extra keys are silently dropped.** No model in `app/` sets `model_config`, so `extra="ignore"`
applies. A `type: "code_block"` object carrying `runs` validates as `CodeFragment`, has `runs`
discarded, and is written back without it by workspace.py#L367.

The client then catches up: `applyCanonicalReport` → `reconcileCanonicalObject`, whose leaf branch is
`if (canonicalValue === undefined) delete live[key]` (app.js#L468). Fragments match by `frag_id`
first (`stableItemKey`, app.js#L422). So a stale `runs` key on a code block survives in browser
memory until the save round-trips, then vanishes.

> ⚠️ **Sharpest edge in the area.** In that window client and server disagree about the fragment's
> shape, and the readiness panel branches on key *presence*, not on `type` — see §5.

### 3. What is lost, per direction

| Conversion | Lost |
|---|---|
| **paragraph → note** | `generated`. `runs` transfer verbatim — **lossless for text and formatting**. |
| **note → paragraph** | nothing. |
| **paragraph → code_block** | **all run structure**: every bold/italic/underline flag and the run boundaries. Plus `generated`. |
| **code_block → paragraph** | **`caption`**. `text` becomes a single plain `Run`. |
| **note → code_block** | **all run structure**. |
| **code_block → note** | **`caption`**. |

Formatting into `code_block` has no home downstream either: docx_report.py#L956-L969 builds the code
component from `[Run(text=fragment.text)]`, a single run with all flags `False`. A multi-run paragraph
with **no** formatting flattens losslessly. **`CodeFragment` has no `language` field.**

### 4. Server-side rules keyed on type

**Converting the only paragraph in `description` does NOT make the server recreate one, and does not
mark the finding incomplete.** `provision`'s seeding loop is gated (report_service.py#L220) on the
section being **wholly empty**; `generation_issues` tests emptiness, never type; `finding_is_complete`
never looks at fragments at all.

Remaining branches:

| Location | Effect of a conversion |
|---|---|
| docx_report.py#L119-L123 | Converting a conclusion paragraph holding the default sentence to a **note** makes this issue stop firing; the sentence still prints, now with the `Note:` prefix. |
| docx_report.py#L125-L126 vs #L141-L142 | Paragraph/note produce `"{content.type} text is required"`; code produces `"{fragment.type} text is required"`. **Different wording**, so a conversion changes the readiness list. |
| report_service.py#L185 `content_has_work` | **Converting a boilerplate paragraph to a note makes it count as tester work.** A section a status change would have dropped is then carried. |
| report_service.py#L233-L244 | A resolved finding's remediation is **replaced wholesale**; any conversion there is wiped on the next PUT. UI-locked, so only reachable by hand-editing. |
| report_service.py#L245-L272 | **The one real provisioning collision.** See below. |
| workspace.py#L284-L292 | `load_path` legacy repair reads `fragments[0].get("runs", [])`; a converted code block yields `""` and stops matching `RESOLVED_REMEDIATION`. Harmless today. |
| docx_import.py#L128,L138,L283-L306 | Import-only. Note import **already discards run formatting**. |

**The `in_conclusion` collision, plainly.** `provision` runs from `provision_report` on **every PUT**.
If `in_conclusion` holds no `ParagraphFragment`, it unshifts a fresh empty one (report_service.py#L259).
So converting the only conclusion paragraph to a note leaves **two** fragments: an empty paragraph the
server just created, plus your note — and the empty paragraph then blocks generation. `syncConclusion`
(app.js#L1012-L1018) does the same thing client-side before any save. Note app.js#L113 already
restricts `in_conclusion` to `["paragraph","note"]`, so `code_block` is not offered there.

### 5. Client-side rules keyed on type

**The deletion guard** (app.js#L1242-L1255) with `requiresFragment = ["description",
"recommended_remediation", "in_conclusion"]` (app.js#L115): Delete is disabled when
`content.fragments.length === 1`. **It counts fragments and ignores `type` entirely**, so a type
conversion is invisible to it — the correct outcome, since `provision` only seeds into empty sections.

| Location | Branch |
|---|---|
| app.js#L113 | `allowed` — `paragraph` is **not** offered in either proof-of-concept section; `code_block` is **not** offered in `in_conclusion`. A conversion menu must honour this or it can create a fragment the Add menu forbids. |
| app.js#L2719 | `newFragment` — the **only** fragment constructor. |
| app.js#L3029 | `renderFragment` picks the editor by **`fragment.runs` truthiness, not by type**. Toolbar suppressed for notes via `fragment.type !== "note"`. |
| app.js#L1001, L1012-L1028, L1072, L1082, L3682-L3722 | `defaultSpanIn`, `syncConclusion`, the conclusion offers — all **paragraph-only**. |
| app.js#L1300-L1305 | `pocLastStep` accepts `numbered_list`, `bulleted_list` and **`note`**, but **deliberately not `code_block`**. **Converting a PoC note to a code block silently withdraws it as a conclusion-offer source; the reverse silently makes one eligible.** |
| app.js#L1332-L1340 | `normalizedSection` includes `type`, `runs`, `text` and `caption`, so any conversion **changes the section fingerprint** and can re-open an answered library offer. |

**Shape-vs-type hazard in the readiness panel.** app.js#L3304 and #L3322 branch on **key presence**,
not `type`. A code block still carrying a non-empty `runs` array would be judged complete by the
client while Python reports `"code_block text is required"`. **A conversion must delete the source
payload key, not merely add the target one.** Treat as a hard requirement.

### 6. Twins a conversion must respect

Five rules exist in both languages and must change together:

1. **Conclusion paragraph selection and re-insertion** — `provision` ⟷ `syncConclusion`. **Highest risk.**
2. **Readiness / generation issues** — `generation_issues` (isinstance) ⟷ `fragmentIssues` (key presence).
3. **Whether a section holds tester work** — `content_has_work` ⟷ `contentHasWork`. Both exempt boilerplate only when it is a paragraph.
4. **Section emptiness** — count-based, conversion-neutral.
5. **Provisioning seeds** — both gate on the section being empty.

**None of these needs changing to stay correct.** `allowed` (app.js#L113) is **not** a twin — Python
deliberately does not enforce section membership. If the conversion menu reuses `allowed` it stays
client-only and adds no twin; hard-coding its own list would create a second copy for no gain.

### 7. What is on disk

Twelve `draft.json` files. `paragraph` **69**, `note` **14**, `code_block` **3** (86 total).

**Formatting:** exactly **7** runs across all drafts carry any flag. **All 7 are `bold`; not a single
`italic: true` or `underline: true` exists anywhere.** Of those, **one** is genuine tester emphasis in
a `description` paragraph (Fragment_Coverage_Demo → `v_critical_d1`); five are the app's own
`Open`/`Resolved` word in `in_conclusion` (where `code_block` is not offered, so the realistic
conversion is paragraph→note, which is lossless); one is a table header cell. **Zero notes on disk
carry any formatting.**

**Captions:** all **3 of 3** code blocks on disk carry a caption. **So caption loss on
code_block→paragraph/note would hit 100% of the code blocks currently saved — a stronger result than
the formatting concern.**

> ⚠️ Caveat not smoothed over: formatted runs were enumerated exhaustively (7 hits, all inspected).
> Multi-run-but-plain paragraphs were **not** counted, deliberately — they flatten losslessly.

### 8. Identity and ordering

`frag_id` uniqueness is **report-wide and enforced on load** (models.py#L369-L393); a violation
demotes the draft to the manager's legacy list. `repair_duplicate_fragment_ids` never reads `type`,
so a conversion keeping `frag_id` is invisible to it.

Nothing points at a `frag_id` expecting a particular type: evidence links run fragment→evidence via
`ImageFragment.evidence_id` only; `Scope` holds no fragment reference; readiness "go to" resolves
`[data-fragment-id]` type-agnostically; captions are positional in both directions.

**Keep the same `frag_id`.** `stableItemKey` prefers `frag_id` over `type`, so keeping it preserves
the Go-to arrow, the save reconciliation path and the undo item key. Changing it would make the
server's version look like a different fragment. Ordering is positional and unaffected.

### 9. DOCX rendering

| Type | Behaviour |
|---|---|
| **paragraph** | `_render_multiline_text_component` — preserves each run's formatting, splits at `\r`/`\n` into one paragraph per line. |
| **note** | Identical, plus continuation lines have the leading `Note:` prefix stripped so a multi-line note does not print `Note:` on every line. |
| **code_block** | **Two components.** `_render_caption_component(...)` then `_render_text_component(..., [Run(text=fragment.text)])`. Newlines held together inside one paragraph, not split. |

**The caption is confirmed as a code_block-only concept.** `_render_caption_component` is invoked for
`CodeFragment` (#L957) and `TableFragment` (#L1201) **only**, and every rendered caption gets
`_keep_with_next` so it cannot be orphaned across a page break. Paragraph and note components have
nowhere to put it.

### Invariants in play

| Invariant | What breaks if violated |
|---|---|
| `frag_id` unique report-wide | Draft unloadable, demoted to legacy list. |
| `type` must match a union tag | Validation error on load — **not** repairable by the duplicate-id path. A typo'd type string strands the draft with no in-app recovery. |
| Undeclared keys dropped silently | A conversion leaving a stale payload key loses it with no signal, one save later. |
| The three printed sections never empty | Count-based, conversion-safe. |
| `in_conclusion` always holds a `ParagraphFragment` | Converting the last conclusion paragraph gets a fresh empty one inserted beside it, which then blocks generation. |
| A resolved finding's remediation is exactly one generated paragraph | Any conversion there is discarded on the next PUT. |

### Map drift corrected

DATA_MAP §12 described `deletionBlockedReason` as guarding `description` and
`recommended_remediation`; the source branches on `requiresFragment`, which is **three** sections —
`in_conclusion` too. Corrected, plus a note that the guard is blind to a type change.


## Round 1 - Planner: proposal and open questions

**Two things the planner found that the oracle's summary implies but does not state outright, and
both change the design:** `CodeFragment.caption` has **no editor UI at all** (the only caption input
in app.js#L2843 is `evidence-caption`, for images), and the generation gate on the default conclusion
sentence is `isinstance(fragment, ParagraphFragment)`-gated on **both** sides (docx_report.py#L120,
app.js#L1002).

### Understanding

A pure client-side mutation of shapes the server already accepts: no new field, no new literal, no
migration, **no Python change**. The difficulty is that the three types are not interchangeable to the
code around them — `runs` vs `text` decide readiness on both sides, `ParagraphFragment` specifically
is what `provision` re-inserts and what two generation gates key on, and `caption` is content the
tester cannot see.

### Blast radius

| File | Function / rule | What changes |
|---|---|---|
| app.js#L1242 | new `CONVERTIBLE_TYPES`, `conversionTargets`, `conversionBlockedReason`, `convertFragment`, sited after `deletionBlockedReason` | One owner of which conversions exist and what each does to payload keys |
| app.js#L2982 | `renderFragment` | Renders the control into `.fragment-head` via `moveUp.before(...)` |
| app.js#L113 | `allowed` | **Read, not changed.** Reused for conversion targets, so no second membership list |
| taste.css#L2559, L2587, L2620 | `.fragment-head` sizing + hover-reveal groups | Add `.fragment-convert` to three existing selector lists |
| docs/DATA_MAP.md | §6, §12 | Record client-only status, the blocks, the deliberate offer re-open |
| tests/test_browser.py | new tests | 5 new tests |
| models.py, report_service.py, docx_report.py | — | **No change** — stated as a decision, not an omission |

### Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write | clear | No new mutation path; rides the existing full PUT carrying `saved_at` |
| Lost update | clear | Python untouched, so no read-modify-write added |
| Orphan reference | **clear (conditional)** | Only because `frag_id` is kept. Reminting would dangle every `fragmentId` held by an already-rendered readiness panel |
| Silent stranding | **RISK** | Converting the boilerplate conclusion paragraph to a note silences **both** halves of the default-sentence gate, since each is `ParagraphFragment`-gated. The report would generate with the app's own sentence printed as the tester's conclusion. Mitigated by step 3 |
| Schema break | clear | All three types already in the union, no new keys; a `load_path` repair would be actively wrong |
| Request/response asymmetry | **RISK** | Leaving `runs` on a `code_block` means the client judges it complete while `generation_issues` says `code_block text is required`, until the round-trip. Deleting the source key is a hard requirement of step 1 |
| Rule drift | clear | Zero Python changes; `allowed` already client-only and deliberately not a twin |
| Navigation trap | clear | No new required field or gate |
| Derived-state fight | **RISK** | `provision` + `syncConclusion` re-insert an empty paragraph when `in_conclusion` holds none — delete it and the next save puts it back. Separately `content_has_work` exempts boilerplate only for `ParagraphFragment`. Both mitigated by step 3 |
| Backup exhaustion | clear | `scheduleSave()` only queues; holds only while conversion never calls `save()` directly |
| Undo integrity *(added)* | clear (conditional) | `diff`/`applyChanges` carry `beforePresent`/`afterPresent`. A `<select>` is not an `activeTextEntry`, so `focusout` finalizes in-flight typing first — step 1 makes that explicit with `finalizeTextTransaction()` |
| Library-offer reopen *(added)* | **RISK, accepted** | `normalizedSection` includes `type`, so every conversion re-opens an answered offer. Unlike `continue_numbering`, a type change **is** content, so this is correct — pinned by step 7 |
| PoC conclusion-offer coupling *(added)* | **RISK, accepted** | `pocLastStep` reads notes but deliberately not code blocks. No good mitigation — the tester chose to call it a note. Pinned by step 7 |

### UI shape

A `<select class="fragment-convert">` whose first option is a placeholder reading `Change type…`,
resetting after use. **Two identical precedents exist in the same file**: the add-fragment menu
(app.js#L3859) and the table column remover (app.js#L3921). Buttons would add three more 22px
controls to a head row already holding six; a custom menu is new machinery for a two-item list.

**Not replacing the `.tag`** — it is the DOM anchor for both the formatting toolbar and the
list-continue toggle, and `taste.css` styles `.fragment-head > .tag` in four rule groups.

**Insertion:** `moveUp.before(control)` just before `return card`. `.fragment-move-up` carries
`margin-left: auto`, so the control lands at the end of the left cluster regardless of the toolbar.

**Lossy and lossless look identical** — the dialog warns at the moment of choice, so the head row
stays readable. Annotating an option with "(loses formatting)" would put a scary label on a
conversion that loses nothing for 68 of 69 paragraphs on disk. The control renders **disabled with a
`title`** when blocked, matching how Delete announces `deletionBlockedReason` rather than vanishing.

### Lossy-conversion handling

| Direction | Recommendation |
|---|---|
| paragraph ↔ note | **No prompt.** Lossless. Worth one comment: bold survives into a note but becomes uneditable, since the toolbar is withheld from notes — a hidden control, not lost data |
| paragraph/note → code_block, no formatting | **No prompt.** 68 of 69 paragraphs, 14 of 14 notes. A dialog here trains the tester to click through the one that matters |
| paragraph/note → code_block, formatting present | **`vrDialog.confirm`**, gated on `runs.some(r => r.bold \|\| r.italic \|\| r.underline)`. Name the loss, not the act |
| code_block → paragraph/note, caption present | **`vrDialog.confirm` quoting the caption verbatim.** Strongest case in the change: **the editor has no caption input for code blocks**, so every caption came from `docx_import` and the tester has never seen it. The dialog is the only place it is ever shown |
| code_block → paragraph/note, no caption | **No prompt** |

Not worth a dialog: a multi-line code block renders as one held-together block, while the same text as
a paragraph splits on newlines. `.rich` is `white-space: pre-wrap`, so the editor shows this honestly.

### The `in_conclusion` problem

**Recommendation: forbid it narrowly — block only the last remaining `paragraph` in `in_conclusion`**,
title "In Conclusion always keeps one paragraph," echoing `deletionBlockedReason`. A section holding
two paragraphs can still convert one.

Rejected: *accepting the extra paragraph* is not a cosmetic wart but a **save loop** — it blocks
generation, the tester deletes it, the next PUT restores it. *Changing the twin* costs three rules
across two languages (`syncConclusion` would stop re-deriving the sentence, `generation_issues` would
need widening or the stranding risk reopens, `content_has_work` is `ParagraphFragment`-typed too) to
buy a `Note:` prefix. `allowed.in_conclusion` already offers `note` in the **Add** menu, so nothing is
taken away.

### Plan

1. **The conversion, one owner** — app.js after `deletionBlockedReason`. To `code_block`: set `text` = joined runs, `caption` = null; **delete `runs`, `generated`**. To paragraph/note: set `runs` = `text ? [{text}] : []`; **delete `text`, `caption`**. `frag_id` never touched, `generated` never set, `finalizeTextTransaction()` first, `scheduleSave()` never `save()`. *Invariant: a converted fragment carries exactly the keys its model declares at the instant of conversion, not after the next save.*
2. **The control** — `renderFragment`, not rendered when `conversionTargets` is empty. *Invariant: lists, tables, images and instance titles are untouched.*
3. **The blocks** — `conversionBlockedReason`: `fragment.generated` set, `isDefaultStatusConclusion` true, or the only `paragraph` in `in_conclusion`. *Invariant: nothing `provision` or `syncConclusion` re-derives can change type.*
4. **The two lossy confirmations** — inside the change handler, via `vrDialog.confirm`. *Invariant: no destructive conversion without an answer, and no dialog on a lossless one — the second half is what keeps the first meaningful.*
5. **Head-row styling** — three selector lists in taste.css. *Tests: none.*
6. **Data map** — §6/§12.
7. **Pin the two accepted couplings** — deliberate mirror of `test_ticking_continue_numbering_does_not_disturb_a_dismissed_library_offer`.

### What the planner would not do

- **Mint a new `frag_id`** — dangles readiness `fragmentId`s, loses the Go-to target, turns one reconciled item into delete-plus-insert.
- **Leave the source key in place** — `extra="ignore"` makes it *look* harmless; what it buys is a window where the editor is green and Generate is blocked with no explanation.
- **Prepend a dropped caption to the text** — writes prose the tester never typed, from a field they could never see.
- **Widen the four rules so a note can be a conclusion** — converts a zero-Python feature into a four-rule twin change.
- **Add a `language` field** — nothing asks for it, real migration, no caller.
- **Exclude `type` from `normalizedSection`** — a much larger behaviour change than this feature.


## Round 2 - Oracle: verdict on the proposal

> "Most of the plan holds. Three things in it are wrong, and one of them is a silent data-loss path."

### A. Risk rows that are wrong

**`Schema break — clear` → WRONG, this is a real risk.** There *is* a repair in `load_path`, it runs
on **every load**, it is **type-blind**, and a converted fragment can fall into it.
workspace.py#L283-L295 checks `recommended_remediation` for a section holding exactly one fragment,
with no `generated` marker, whose joined `runs` equal `RESOLVED_REMEDIATION`. It never tests `type`.
On a non-resolved finding it does `fragments[0]["runs"] = []` and **rewrites the draft to disk**.
Step 3 blocks conversion when `fragment.generated` is set — exactly the key this repair requires to be
*absent*. So legacy unmarked boilerplate is convertible, and converting it to a `note` carries it into
a repair that blanks its runs on the next server load, with no dialog and no undo entry.

**`Request/response asymmetry — RISK` → premise wrong, conclusion accidentally right.** The
round-trip really does delete the stale key (`extra='ignore'`, then `reconcileCanonicalObject`'s
`delete live[key]`). Once step 1 deletes `runs`, this is mitigated by construction. Its value is as a
rejected-design note, not a risk.

**`Derived-state fight — RISK` → right, but step 3's mitigation has a hole.** `isDefaultStatusConclusion`
requires the paragraph be *nothing but* the sentence (`span[0] === 0 && span[1] === text.trimEnd().length`,
app.js#L1002-L1006). But the rule that keeps the sentence **current** is `hasDefaultStatusConclusion`,
which only tests `span !== null` (app.js#L1008), and that is what `syncConclusion` uses to find the
paragraph to rewrite. The Python twin is identical. So a paragraph reading *"We confirmed remediation.
The finding "Foo" is Resolved."* passes step 3's block, converts to a note, and from that moment
**neither twin can re-derive the sentence** on a title or status change — the conclusion permanently
names the old title, silently. **Step 3 must block on `hasDefaultStatusConclusion`, not
`isDefaultStatusConclusion`.**

**Correct as marked:** stale write, lost update, orphan reference, silent stranding, navigation trap,
backup exhaustion, library-offer reopen, PoC coupling, undo integrity. `Rule drift — clear` reaches
the right verdict by the wrong reasoning: the exposure is step 3's two guards, which are client-only
defences over **twinned** server behaviour — the same shape `deletionBlockedReason` already has.

### B. What the planner missed

**1. `rerender()` — the big one.** Step 1 never calls it, and **every other fragment-mutating handler
in `renderFragment` does** (delete #L2990, `moveFragment` #L2995, continue-numbering #L3086, evidence
environment #L2868, every table structural edit). Without it, after paragraph→code_block the card
still shows the **rich contenteditable**, whose `onChange` is `runs => {fragment.runs = runs;
changed();}`. The editor body is chosen by `if (fragment.runs)`, **not by `fragment.type`**. So the
next keystroke re-adds `runs` to a `code_block`, the server ignores it, and reconciliation deletes it
on the save response — **everything the tester typed into that stale editor vanishes on the next
autosave.** `rerender` is already the third parameter of `renderFragment`: one missing call.

**2. `generated` is not deleted on the →paragraph/note arm.** The server dumps every optional field
explicitly, so after the first save every paragraph carries `generated: null`. Converting to a note
leaves `generated: null` on a `NoteFragment`, which declares no such field. Harmless, but it falsifies
step 1's own invariant and adds a no-op key to every conversion's undo diff. **Delete `generated` on
both arms.**

**3. The second half of the `in_conclusion` floor is Python.** Step 3's block is client-only, but the
rule it defends is a genuine twin: `syncConclusion` (app.js#L1018-L1021) and `provision`
(report_service.py#L258-L259). The blast radius lists report_service.py as "no change" — correct, but
it should be **named as the enforcing half**.

**4. CSS needs a fourth and fifth selector list, and 22px is not the real height.** taste.css re-styles
`.fragment-head` children ~500 lines later and that block wins the cascade: L3192-L3199 sizes head
**buttons** to **20px**. A `<select>` is not a `button`, so it escapes that and lands on the 22px rule
— 2px taller than every button beside it. L2510-L2513 gives head controls `border-radius:
var(--radius-sm)`; a bare `<select>` will carry the UA default radius instead.

**5. `docx_import` is the only producer of the caption step 4 protects** (docx_import.py#L286-L290
writes it, docx_report.py#L956-L957 prints it). That pair is the entire justification for the second
dialog.

### C. Does the proposed shape break any existing draft?

**No.** All three types are already in the union, all three produced shapes are byte-identical to what
`newFragment` emits, nothing migrates on load.

**But the operation, applied to drafts that exist right now, silently drops printed output.**
`Northstar_Banking/…0931592e4fdd/draft.json#L157-L162` holds
`{"frag_id": "f_9789ca8b", "type": "code_block", "caption": "Request", "text": "GET /accounts/123"}`.
`"Request"` prints into the DOCX and the tester has never seen it on screen. **Step 4's confirm is the
only thing between one click and losing a caption that appears in the finished document.** Three of the
six drafts on disk carry a code block. The one real on-disk hazard is the `load_path` repair, not the
schema.

### The ten specific claims

| # | Claim | Verdict |
|---|---|---|
| 1 | `moveUp.before(control)` lands at the end of the left cluster | **Premise right, conclusion wrong for paragraphs.** `margin-left:auto` is on move-up **and on `.toolbar`** (L3120, L3210). Paragraphs insert a toolbar; flexbox splits free space between two auto margins, so the select lands **mid-row**. Correct only for note and code_block |
| 2 | `moveUp`/`card` in scope; head holds six controls | **Scope right, count wrong** — base head holds **five**; six only when a toolbar or `.list-continue` is injected |
| 3 | `finalizeTextTransaction()` exists and is in scope | **Right**, declared L599; `onpaste` brackets itself with it inside `renderFragment` |
| 4 | `vrDialog.confirm` signature | **Right**, and it also takes `list` and `tone`; resolves to a boolean |
| 5 | `isDefaultStatusConclusion` exists | **Right** — but it is the **wrong predicate** for step 3 |
| 6 | undo can represent key deletion | **Right, and it survives scrutiny.** `diff` emits `beforePresent`/`afterPresent`; `applyChanges` does `delete parent[key]`. **No silent data-loss path on undo.** The `<select>` half is right too — `activeTextEntry()` matches only input/textarea/contenteditable, so the `focusout` microtask finalizes first. The explicit call is belt-and-braces, not load-bearing |
| 7 | The three taste.css groups; 22px | **Line numbers right, "22px" misleading** — see B4 |
| 8 | `TwinRuleTests::test_the_data_map_twin_table_names_symbols_that_still_exist` | **Right**, tests/test_app.py#L2177. Parses §12 and asserts **≥20 rows**, so a §12 edit that drops rows fails |
| 9 | `allowed` has no `paragraph` in either PoC section → one-way door | **Confirmed, and reachable** — docx_import.py#L307 emits an unclassified paragraph as the default fallback into whatever section it is reading |
| 10 | `CodeFragment.caption` has no editor UI | **Confirmed.** Read by `contentHasWork`, `fragmentHasContent` and the placeholder scan; written only by `docx_import`. Never shown, never editable |


## Round 2 - Planner: revised plan

**The premise changed.** It is **no longer purely client-side**: one condition is added to the
`load_path` repair in workspace.py#L283-L295, because that repair is type-blind and would silently
blank a converted note's runs on the next load.

### Corrected blast radius

| File | Change |
|---|---|
| **app/workspace.py#L283-L295** | **CHANGED.** `load_path`: add `fragments[0].get("type") == "paragraph"` to the `stale` predicate. One condition; provably a no-op for every draft on disk today |
| app/web/static/app.js | New `convertFragment`, new `conversionBlockedReason`; `renderFragment` gains the control **and its toolbar anchor line changes** (L3029). Reuses `allowed`, `hasDefaultStatusConclusion`, `RESOLVED_REMEDIATION`, `vrDialog.confirm`, `finalizeTextTransaction`, `rerender` |
| app/web/static/taste.css | **Four** groups, not three — radius L2510-L2513, recede L2587-L2591, reveal L2620-L2629, and a **new sizing rule placed after L3192** |
| **app/report_service.py#L245-L272** | **READ ONLY, named as the enforcing half.** `provision`'s conclusion block is `syncConclusion`'s twin. Nothing changes, but this pair is *what the block is worth*: relax either side and the block becomes unnecessary or insufficient |
| docs/DATA_MAP.md | §8 bullet, §12 **prose only**, §13 two sharp edges. **No table row added or removed**, so `TwinRuleTests` keeps its ≥20-row floor |
| tests/test_app.py, tests/test_browser.py | One new Python test, two new browser tests |

### Corrected data-risk table (changed rows only)

| Failure mode | Verdict | Reasoning |
|---|---|---|
| **Schema break** | **`RISK`** (was `clear`) | The original block keyed on `generated` being *set*, which is precisely the case the repair requires to be *absent* — so legacy unmarked boilerplate was convertible, and a note made from it would be blanked on the next server load, silently, with no undo entry. **The `code_block` arm escapes** (no `runs` left to match); only the note arm is exposed. Mitigated at source in step 1 |
| **Derived-state fight** | **`RISK`** | Two, both in `in_conclusion`. (a) the empty-paragraph re-insert. (b) the re-derivation arm selects on `hasDefaultStatusConclusion` — span **not null** — so *"We confirmed remediation. The finding "Foo" is Resolved."* passed the original block, and once converted **neither twin can re-derive the sentence again**. Predicate corrected |
| **Stale editor writes back** *(new row)* | **`RISK`** | The editor body is chosen by `if (fragment.runs)`, not by `type`. Without `rerender()` the next keystroke re-adds `runs` to a code block and **everything typed into the stale editor vanishes on the next autosave**. Mitigated in step 2 |
| Request/response asymmetry | `clear`, with a note | Deleting `generated` on **both** arms, since the server echoes `generated: null` onto every paragraph after one save |
| Offer re-opening, `pocLastStep` withdrawal | `RISK`, **accepted** | A banner asks, never writes; worst case is a re-asked question. Documented in §13, not blocked |

### How the `load_path` hazard is blocked

**Not a third arm of `conversionBlockedReason`. A one-condition narrowing of the repair itself** —
`and fragments[0].get("type") == "paragraph"`. Reasons:

- **It is a no-op for every draft on disk.** The only writer of that sentence is `provision`, which
  writes a `ParagraphFragment`. Nothing in the app can currently produce a note or code block holding
  it, so it changes the outcome for exactly zero existing drafts.
- **A client arm would create a brand-new twin** — a fifth copy of a rule whose whole problem is that
  it is invisible, and §12 would have to carry it.
- **A client arm protects one entry path only.** `import_report` and `parse_import` bypass `load_path`.
- **The refusal would be unexplainable** — "you cannot make this a note" has no honest short reason
  that is really about the tester's document.

**Ordering is the invariant.** Step 1 must merge **before** the control ships. If the control lands
first, a note converted in that window is blanked on its next load with nothing to recover it from.

### Revised plan

1. **Narrow the repair.** workspace.py `load_path`. *Test:* new `test_the_remediation_repair_only_touches_paragraphs` — a single unmarked **note** with the boilerplate text keeps its runs; the same draft with a **paragraph** still gets blanked. *The second half is what stops the fix being a blanket disable.* *Invariant: the repair may never blank a fragment type `provision` did not write.*
2. **`convertFragment`.** To code_block: join runs into `text`, `delete runs`, `caption = null` (byte-identical to `newFragment`). From code_block: `runs = text ? [{text}] : []`, `delete text`, `delete caption`. Paragraph⟷note: runs pass through. **Every arm:** set `type`, `delete generated`. Then unconditionally `rerender(); scheduleSave();`, bracketed by `finalizeTextTransaction()`. *Invariant: the card's editor and the fragment's payload key agree at all times; a fragment may never hold both `runs` and `text`.*
3. **Delete-the-source is load-bearing** — no new code, an assertion on step 2's test. *Invariant: client and server never disagree about a fragment's shape across a save boundary.*
4. **`conversionBlockedReason`**, evaluated **per candidate target** so one blocked target never disables the rest. Arms: (1) `fragment.generated` truthy; (2) `in_conclusion` paragraph that is **either** `hasDefaultStatusConclusion` **or** the last paragraph in the section. *Test:* sentence as the **tail** with prose in front, so `isDefaultStatusConclusion` is false and `hasDefaultStatusConclusion` is true. *Invariant: a conversion may never leave a conclusion sentence that neither twin can re-derive.*
5. **Render the control after `.fragment-head .tag`**, not before move-up. `margin-left: auto` sits on **both** `.fragment-move-up` and `.toolbar`, and flexbox splits free space between two auto margins, so the original insertion point lands mid-row for paragraphs. This retargets one existing line: the toolbar insert at L3029 becomes `(card.querySelector(".fragment-head .fragment-convert") || card.querySelector(".fragment-head .tag")).after(toolbar)` — a selector-list `querySelector` will not do, since it returns the tag by document order.
6. **Two confirms**, both before any mutation; on decline reset `select.value = fragment.type`. Formatting loss to code_block; caption loss from code_block, **quoting the caption verbatim**. *Invariant: nothing the tester cannot see is destroyed without them reading it first.*
7. **CSS, four groups** — radius; a **new 20px sizing rule after L3192** (the later block sizes head `button`s to 20px and wins; a `<select>` escapes it and would land on the 22px rule, two pixels taller than its neighbours); recede; reveal on **both** `:hover` and `:focus-within`.
8. **DATA_MAP prose only** — §8, §12 prose, §13. **§12 table untouched.**

### What the planner would not do (revised)

**Would not block client-side to work around the type-blind repair.** It keeps Python untouched, which
was the original premise's appeal — but it copies a four-part server predicate into JavaScript,
protects only the `load_path` entry while `import_report` and `parse_import` stay open, and refuses
the tester an action for a reason that has nothing to do with their document. The repair's own comment
says it exists for "boilerplate written before the marker existed", and boilerplate is always a
paragraph.

**Would not "fix" the two accepted risks** — excluding `type` from `normalizedSection` would make the
fingerprint blind to a real change; widening `pocLastStep` to accept code blocks would reopen a source
that was deliberately narrowed.


## Answers

**1. Which sections get the control.** User, verbatim:

> these options are only for description and recommended remediation, and previuos poc and poc

So `in_conclusion` is **out of scope entirely** — the control is never rendered there. This is a
stronger answer than any of the three options put to the user, and it dissolves two of the plan's
open problems rather than mitigating them:

- The `provision` / `syncConclusion` empty-paragraph re-insert can no longer be triggered, because
  nothing in that section is convertible.
- The `hasDefaultStatusConclusion` hole the oracle found in Round 2 **disappears**. The default status
  sentence only ever lives in `in_conclusion`, so with that section excluded there is no paragraph the
  twins re-derive that a conversion could reach. **Arm 2 of `conversionBlockedReason` is deleted, not
  corrected.**

Crossed against `allowed` (app.js#L113), the scope resolves to:

| Section | Targets offered |
|---|---|
| `description`, `recommended_remediation` | paragraph ↔ note ↔ code_block, all six directions |
| `previous_proof_of_concept`, `proof_of_concept` | **note ↔ code_block only** — `paragraph` is not in `allowed` for either |
| `in_conclusion` | none |

**2. The caption confirm — settled by evidence, not asked.** `CodeFragment.caption` has no editor UI
anywhere, and a real draft on disk carries `"Request"`, which prints into the finished DOCX. The
confirm quotes the caption verbatim; it is the only place the tester will ever read it.

**3. Reuse `allowed`; accept the one-way door in the proof-of-concept sections.** A paragraph can
reach a PoC section through `docx_import.py#L307`'s default fallback. It can convert to note or code
block and never back. **Recorded as correct rather than tolerated:** it is a one-way door *out of* a
state the section does not permit, and reusing `allowed` keeps one owner of section membership
instead of creating a second list to drift.

**4. Accept the two couplings.** A conversion re-opens an answered library offer, because
`normalizedSection` includes `type` and a type change genuinely is a content change. Converting a PoC
note to a code block withdraws it as a `pocLastStep` source, and the reverse makes one eligible.
Both are banners that ask and never write, so the worst case is a re-asked question. Pinned by test,
documented in §13, not blocked.

**5. The type-blind `load_path` repair — IN SCOPE.** Stress testing reached it through current UI:
enter the stock resolved-remediation text in a paragraph, convert that paragraph to a note, save, and
reload. The repair matched text and `generated` state without checking the fragment type, so it erased
the tester's note during load.

**Decision: narrow `app/workspace.py` to repair paragraphs only.** `provision` historically wrote this
boilerplate as a paragraph, so the fragment type is the missing migration boundary. The regression
keeps an identical note intact while still repairing the intended legacy paragraph.

## Agreed plan

**Scope.** A `<select>` in the head of a `paragraph`, `note` or `code_block` card that changes it into
one of the other two in place, keeping `frag_id` and carrying the text across. Offered in
`description`, `recommended_remediation`, `previous_proof_of_concept` and `proof_of_concept` only.
**Never in `in_conclusion`.** Targets come from `allowed[content.type] ∩ {paragraph, note, code_block}`
minus the current type, so Description and Remediation get all three types while both proof-of-concept
sections get `note ↔ code_block` only. The conversion remains client-side; the legacy load repair is
narrowed independently to the paragraph type it historically created.

**Step 1 — `convertFragment(fragment, targetType, rerender)`**, app.js, beside `deletionBlockedReason`.
One owner of the payload swap:

| To | Set | Delete |
|---|---|---|
| `code_block` | `text` = runs joined, `caption` = `null` (byte-identical to `newFragment("code_block")`) | `runs` |
| `paragraph` / `note` | `runs` = `text ? [{text}] : []` | `text`, `caption` |

Every arm sets `type` and deletes `generated`. Then **unconditionally `rerender()` then
`scheduleSave()`** — never `save()`. `frag_id` is never touched.

*Test:* `tests.test_browser` — convert a description paragraph, assert the card now shows `.code-block`
and **not** `.rich`, type one more character, await the save, reload, assert the character survived and
the stored fragment has no `runs`.

*Invariant:* **the card's editor and the fragment's payload key agree at all times.** A fragment may
never hold both `runs` and `text`. This is what stops the two day-one bugs: the editor body is chosen
by `if (fragment.runs)` rather than by `type`, so without `rerender()` the stale rich-text box keeps
writing `runs` onto a code block and everything typed into it is deleted on the next save response;
and the readiness panel branches on key presence, so a leftover `runs` makes the client call an empty
code block complete while the server refuses to generate it.

**Step 2 — render the control**, `renderFragment`. Not rendered at all when the target list is empty
(lists, tables, images, instance titles, and everything in `in_conclusion`). Inserted **immediately
after `.fragment-head .tag`**, not before move-up: `margin-left: auto` sits on **both**
`.fragment-move-up` and `.toolbar`, and flexbox splits free space between two auto margins, so
inserting before move-up lands the select mid-row on paragraphs. This retargets one existing line —
the toolbar insert becomes
`(card.querySelector(".fragment-head .fragment-convert") || card.querySelector(".fragment-head .tag")).after(toolbar)`;
a selector-list `querySelector` will not work, since it returns the tag by document order.

*Test:* assert `.fragment-convert` count is 0 on a numbered list, table, image tile and in
`in_conclusion`; 1 on paragraph, note and code block; and that the options inside a proof-of-concept
section exclude `paragraph`.

*Invariant:* lists, tables, images and instance titles are untouched by this change.

**Step 3 — two confirmations, and only two.** Both `await window.vrDialog.confirm(...)` before any
mutation; on decline reset `select.value = fragment.type` and do nothing else.

- **Caption loss**, converting a code block with a non-empty `caption`: **quote the caption verbatim**
  and say it prints in the report. `CodeFragment.caption` has no editor UI anywhere — written only by
  `docx_import`, read only by the renderer — so this dialog is the only place the tester will ever see
  it. All 3 code blocks on disk carry one.
- **Formatting loss**, converting to `code_block` when `runs.some(r => r.bold || r.italic ||
  r.underline)`: the flags have no home in a code block and none downstream either.

No dialog on any lossless conversion — that is 68 of the 69 paragraphs and all 14 notes on disk.

*Test:* assert the dialog body contains the caption text; assert Cancel leaves the fragment a
`code_block` with its caption intact on disk; assert a caption-free code block converts with **no**
dialog.

*Invariant:* nothing the tester cannot see on screen is destroyed without them reading it first — and
no dialog on a conversion that loses nothing, which is what keeps the first half meaningful.

**Step 4 — CSS, four groups** in taste.css. Add `.fragment-convert` to the radius list (L2510-L2513),
the recede list (L2587-L2591), and **both** the `:hover` and `:focus-within` reveal selectors
(L2620-L2629). Then a **new sizing rule placed after L3192**: that later block sizes head `button`s to
**20px** and wins the cascade, but a `<select>` is not a `button`, so it would escape and land on the
22px rule — two pixels taller than every neighbour.

*Test:* none. CSS, and no test asserts on the head row.

**Step 5 — `docs/DATA_MAP.md`, prose only.** §12's existing paragraph on `deletionBlockedReason` being
blind to a type change gains the conversion; §13 gains the two accepted couplings below. **The §12
table is not touched** — no row added or removed, no new Python symbol named — so
`tests/test_app.py::TwinRuleTests::test_the_data_map_twin_table_names_symbols_that_still_exist` keeps
passing on both its ≥20-row floor and its symbol check.

**Step 6 — pin the two accepted couplings**, `tests/test_browser.py`, as the deliberate mirror of
`test_ticking_continue_numbering_does_not_disturb_a_dismissed_library_offer`. A conversion **does**
re-open an answered library offer, because `normalizedSection` includes `type` and a type change is a
real content change. Converting a proof-of-concept note to a code block **does** withdraw it as a
`pocLastStep` source, and the reverse makes one eligible.

*Invariant:* both are recorded as chosen, not discovered later as bugs.

### Deliberately not doing

- **Minting a new `frag_id`** — dangles the readiness panel's jump targets, loses the Go-to arrow, and
  turns one reconciled item into a delete-plus-insert during save reconciliation.
- **Leaving the source key in place** — `extra="ignore"` makes it look harmless; what it buys is a
  window where the editor is green and Generate is blocked with no explanation.
- **Prepending a dropped caption to the converted text** — writes prose the tester never typed, from a
  field they could never see.
- **Teaching four rules that a note can be a conclusion** — moot now that `in_conclusion` is out of
  scope, and it would have cost the automatic sentence updates on rename and status change.
- **Adding a `language` field to `CodeFragment`** — nothing asks for it, no template renders it.
- **Excluding `type` from `normalizedSection`** — would make the fingerprint blind to a real change,
  far beyond this feature.
- **Broadening `app/workspace.py` repair behavior** — the only server change narrows the legacy repair
  to paragraphs; conversion still has no server-side implementation.

