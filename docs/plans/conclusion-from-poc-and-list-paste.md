# Conclusion seeded from the proof of concept, and list paste cleanup

## Request

> - Add the last line of the generated POC to the beginning of the Conclusion field
> - Prompt the users to replace or retain the in conclusion value when a vulnerability/finding and the status is changed. Since the value here is dependent on the name and status of the finding.
> - Require the users to replace the default in conclusion value.
> - After the testers finished typing the POC, prompt the user to add the last item or line in the POC to be added before the default value of the In Conclusion.
> - When pasting a numbered list in the numbered list fragment, I want that field to auto clean the inputs. So no 1. 2. 3. Would be there but just the lines. same with the bulleted list.

## Round 1 - Oracle: how it works today

### 1. The "In Conclusion" field — what it actually is

**Answer.** It is a full `Content` section named `in_conclusion`, not a field and not a fragment inside another section. Its default text is **not** a named constant — it is an inline three-`Run` literal built inside `provision`. The `status_conclusion` marker exists in the schema but **nothing in the app ever writes it**; `provision` explicitly sets it to `None`.

#### Schema names

| Thing | Real name | Evidence |
|---|---|---|
| The section | `"in_conclusion"`, 5th member of `ContentType` | [app/models.py](app/models.py#L23) |
| The section container | `Content{type, fragments}` | [app/models.py](app/models.py#L126-L128) |
| Where it sits | `Vulnerability.contents: list[Content]` | [app/models.py](app/models.py#L198) |
| The marker | `ParagraphFragment.generated: Literal["status_conclusion", "resolved_remediation"] \| None = None` | [app/models.py](app/models.py#L70-L74) |

#### Position in `Vulnerability.contents`

`provision` **rebuilds `contents` from scratch** on every run, in `content_types_for_status` order, then appends carried sections. So `in_conclusion` is always the **last printed section** for a non-`open_new` finding, and **absent entirely** for `open_new` unless it holds tester work and gets carried.

- [app/report_service.py](app/report_service.py#L162-L167) — `content_types_for_status`
- [app/report_service.py](app/report_service.py#L193-L197) — the rebuild
- Twin: [app/web/static/app.js](app/web/static/app.js#L920-L922), [app/web/static/app.js](app/web/static/app.js#L933-L938)

#### The literal default text

There is **no constant**. The sentence is assembled inline as three `Run`s:

```python
default.generated = None
default.runs = [
Run(text=f'The finding "{vulnerability.title}" is still ' if status == "Open" else f'The finding "{vulnerability.title}" is '),
Run(text=status, bold=True),
Run(text="."),
]
```

[app/report_service.py](app/report_service.py#L244-L249). `status` is `"Resolved"` if `vulnerability.status == "resolved"` else `"Open"` ([app/report_service.py](app/report_service.py#L235)).

Rendered, the two possible strings are exactly:

- `The finding "<title>" is still Open.`
- `The finding "<title>" is Resolved.`

The recogniser is a separate regex: `r'The finding ".*" is(?: still)? (?:Open|Resolved)\.'` under `re.fullmatch` ([app/report_service.py](app/report_service.py#L401-L405)).

The JavaScript twin builds the same runs ([app/web/static/app.js](app/web/static/app.js#L915)) and carries the same regex anchored with `^...$` ([app/web/static/app.js](app/web/static/app.js#L901)).

**This sentence therefore has four spellings** (Python builder, Python regex, JS builder, JS regex). Compare `RESOLVED_REMEDIATION`, which *is* a constant ([app/report_service.py](app/report_service.py#L20)) with a declared JS twin ([app/web/static/app.js](app/web/static/app.js#L113)).

#### What regenerates it, and when

The rewrite fires on exactly one condition, identical on both sides: the paragraph carries `generated == "status_conclusion"`, **or** it has no text, **or** it still matches the default regex. Anything else is tester prose and is left alone.

- Python: [app/report_service.py](app/report_service.py#L233-L255)
- JavaScript: [app/web/static/app.js](app/web/static/app.js#L902-L918)

| Trigger | Side | Evidence |
|---|---|---|
| Every `PUT /reports/{id}` | server | [app/main.py](app/main.py#L692) → [app/main.py](app/main.py#L256-L260) → `provision` |
| Library insert | server | [app/main.py](app/main.py#L727) |
| Status change on Findings page | client | [app/web/static/app.js](app/web/static/app.js#L1928) calls `provision`, which calls `syncConclusion` at [app/web/static/app.js](app/web/static/app.js#L952) |
| Title typing on Findings page | client | [app/web/static/app.js](app/web/static/app.js#L1892) |
| Title commit in the editor | client | [app/web/static/app.js](app/web/static/app.js#L2856) |
| Library title pick in the editor | client | [app/web/static/app.js](app/web/static/app.js#L2870) |
| Editor boot, every finding | client | [app/web/static/app.js](app/web/static/app.js#L2549) |

So: **both**, and the client runs first with the server re-deriving the same answer on save.

Seeding, as distinct from rewriting: `required_fragments["in_conclusion"]` is `[]` ([app/report_service.py](app/report_service.py#L205)), so the generic seed loop adds nothing. The paragraph is created only by the conclusion block itself, and only when the section holds **no paragraphs at all** ([app/report_service.py](app/report_service.py#L240-L242)).

#### `test_in_conclusion_seed_is_editable_and_accepts_more_fragments`

[tests/test_browser.py](tests/test_browser.py#L1006-L1030). It pins:

1. The guidance line `Include a brief justification or explanation.` is visible for this section. That string is client-only and rendered for `in_conclusion` alone ([app/web/static/app.js](app/web/static/app.js#L2902-L2907)).
2. The section opens with **exactly one** fragment.
3. Its text is exactly `The finding "Browser finding" is still Open.`
4. `.generated-conclusion` count is `0`. **That class does not exist anywhere** — not in [app/web/static/app.js](app/web/static/app.js) and not in [app/web/static/app.css](app/web/static/app.css). The assertion is a permanent zero and pins nothing today.
5. The sentence can be overwritten with free prose.
6. A `note` fragment can be added via the "Add fragment to In Conclusion" combobox.
7. Both survive save + reload — i.e. the server does **not** restore the default over tester prose.

Server-side equivalent, including the title-rename-preserves-prose case: [tests/test_app.py](tests/test_app.py#L1599-L1624).

---

### 2. The status/title dependency

**Answer.** Confirmed, on both. The generated sentence reads `vulnerability.status` and `vulnerability.title` directly. A status change today does **not** overwrite tester prose, and the existing confirmation prompt never mentions the conclusion.

#### The reads

- `status` → `Open`/`Resolved` word: [app/report_service.py](app/report_service.py#L235), [app/models.py](app/models.py#L189)
- `title` → interpolated into the sentence: [app/report_service.py](app/report_service.py#L246-L247), [app/models.py](app/models.py#L185)
- JS twin reads both: [app/web/static/app.js](app/web/static/app.js#L905), [app/web/static/app.js](app/web/static/app.js#L915)

#### What happens on a status change after the conclusion was edited

Nothing overwrites it. The rewrite guard at [app/report_service.py](app/report_service.py#L243) and [app/web/static/app.js](app/web/static/app.js#L913) fails for edited prose, so the paragraph is preserved verbatim — including the now-stale `Open`/`Resolved` word, if the tester wrote one into their own sentence. This is pinned by [tests/test_app.py](tests/test_app.py#L1618-L1624) (for a rename) and [tests/test_app.py](tests/test_app.py#L976-L1000) (for a status round-trip).

Changing to `open_new` **hides** the section rather than deleting it, but only if it holds work — and the default sentence does not count as work (next section).

#### The two `generated` markers, precisely

**`generated="resolved_remediation"`**

| Where | What it causes |
|---|---|
| [app/report_service.py](app/report_service.py#L222-L228) | On `status == "resolved"`, `recommended_remediation.fragments` is **replaced wholesale** with one marked paragraph holding `RESOLVED_REMEDIATION` |
| [app/report_service.py](app/report_service.py#L229-L232) | On any other status, every fragment carrying the marker is **deleted**; an empty paragraph replaces them if nothing survives |
| [app/workspace.py](app/workspace.py#L284-L296) | `load_path` backfills the marker onto a lone unmarked `RESOLVED_REMEDIATION` sentence when resolved, and **blanks its runs** when not — then rewrites the file |
| [app/report_service.py](app/report_service.py#L175), [app/web/static/app.js](app/web/static/app.js#L926) | Marked fragments are invisible to `content_has_work` / `contentHasWork` |
| JS twin | [app/web/static/app.js](app/web/static/app.js#L947-L951) |

**`generated="status_conclusion"`**

It is **read-only legacy**. No code path writes it:

- `provision` sets `default.generated = None` on the very line before writing the sentence ([app/report_service.py](app/report_service.py#L244)).
- `syncConclusion` does `delete defaultParagraph.generated` ([app/web/static/app.js](app/web/static/app.js#L914)).
- `insert_library` copies library `contents` verbatim ([app/main.py](app/main.py#L722)) and no library entry defines an `in_conclusion` section.
- On disk: a grep for `status_conclusion` across every `data/apps/**/draft.json` returns **zero matches**.

When one *is* present, it causes two things:

1. It is selected as `default` unconditionally ([app/report_service.py](app/report_service.py#L237-L238)), and its presence makes the rewrite guard true regardless of what the tester wrote ([app/report_service.py](app/report_service.py#L243)) — so it **forces an overwrite of tester prose**.
2. It triggers a purge: every other `ParagraphFragment` in the section with no text is **deleted** ([app/report_service.py](app/report_service.py#L250-L255), [app/web/static/app.js](app/web/static/app.js#L917)).

It is also skipped by `content_has_work` via the `fragment.generated` test ([app/report_service.py](app/report_service.py#L175)) — but so is the unmarked default sentence, via the `_is_default_status_conclusion(fragment)` arm of the same condition.

#### The existing status-change prompt

Yes, one exists. It is `window.vrDialog.confirm` — **not** `window.confirm` — inside the status `<select>`'s `onchange`:

[app/web/static/app.js](app/web/static/app.js#L1915-L1929), the dialog itself at [app/web/static/app.js](app/web/static/app.js#L1922).

It guards exactly two things, and **neither is the conclusion**:

1. Sections that the new status will stop printing **and** that hold work (`contentHasWork`). Title: *"Change the status of this finding?"*, message names the sections, tone `default`.
2. Moving to `resolved`, which replaces the recommended remediation. Message: *"This will replace the recommended remediation."*, tone `danger`.

If neither applies, **no dialog is shown at all** and the status changes silently. Because `contentHasWork` skips the default conclusion ([app/web/static/app.js](app/web/static/app.js#L926)), an `in_conclusion` section still holding the default is invisible to this guard — it is never listed in `hidden`, and it never causes the prompt to appear.

There is no prompt of any kind on **title** change.

---

### 3. The proof-of-concept sections

**Answer.** Two section types, both holding the same fragment set. "The last line of the generated PoC" is **not a well-defined concept in the data today** — the last *fragment* of a provisioned PoC is normally an image, not text. There is **no marker** distinguishing library-sourced from tester-typed PoC fragments.

#### Section types and fragment types

Both `proof_of_concept` and `previous_proof_of_concept` are `ContentType` members ([app/models.py](app/models.py#L23)).

The editor's Add menu allows, for **both**: `numbered_list`, `image`, `bulleted_list`, `instance_title`, `note`, `code_block` ([app/web/static/app.js](app/web/static/app.js#L109)). No `paragraph`, no `table`.

**That allowlist is UI-only.** `Content.fragments` accepts any member of the `Fragment` union ([app/models.py](app/models.py#L123), [app/models.py](app/models.py#L127)), and the DATA_MAP states section membership is not validated ([docs/DATA_MAP.md](docs/DATA_MAP.md#L131-L133)). Confirmed on disk: a `table` fragment sits inside a `previous_proof_of_concept` in [data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json](data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L165-L189).

#### "The last line of the generated POC" — what it resolves to

There is no such concept in the code. Reconstructing it from the data:

1. `apply_poc_variant` sets `proof.fragments = merge_step_lists(kept + copied) + images` — **images are appended last, unconditionally** ([app/report_service.py](app/report_service.py#L437)). Twin: [app/web/static/app.js](app/web/static/app.js#L1080).
2. `provision` seeds `["numbered_list", "image"]` in that order ([app/report_service.py](app/report_service.py#L202-L203)), and `sync_evidence_image_slots` **appends** further image slots ([app/report_service.py](app/report_service.py#L379-L387)).
3. `ensure_proof_steps` guarantees a `numbered_list` exists and inserts it at **index 0** if missing ([app/report_service.py](app/report_service.py#L155-L159)).
4. `merge_step_lists` collapses every `numbered_list` in the section into the **first** one ([app/report_service.py](app/report_service.py#L414-L425)).
5. Every `proof_of_concept` block in [resources/vuln_library.json](resources/vuln_library.json) is exactly **one `numbered_list` per channel** — e.g. [resources/vuln_library.json](resources/vuln_library.json#L74-L131).

So for a library-generated PoC, the only reading that is well-defined is: **the last `ListItem` of the single `numbered_list` in the `proof_of_concept` section**, whose text is `"".join(run.text for run in item.runs)`. A `ListItem` is `{runs: list[Run]}` ([app/models.py](app/models.py#L77-L78)); a `Run` is `{text, bold, italic, underline}` ([app/models.py](app/models.py#L63-L67)).

It is **not** well-defined as "the last fragment", because:

- The last fragment is almost always an `ImageFragment`, which has no `runs` and no `items` ([app/models.py](app/models.py#L101-L108)).
- A `table` can be present on disk and its "last line" would be a row of cells, not a line.
- A `note` or `code_block` last fragment gives `runs` / `text` respectively — a different extraction shape each time ([app/models.py](app/models.py#L95-L99), [app/models.py](app/models.py#L110-L115)).
- A tester-typed PoC may hold **several** `numbered_list` fragments: `merge_step_lists` only runs from `apply_poc_variant`, never from `provision`, so nothing collapses lists a tester added by hand.
- A `numbered_list` may legally end with a blank item — `min_length=1` permits `items: [{runs: []}]` ([app/models.py](app/models.py#L81-L84)), and that is exactly what `provision` seeds ([app/report_service.py](app/report_service.py#L203)).

The client's existing text-extraction helper for a whole fragment is `fragmentText` ([app/web/static/app.js](app/web/static/app.js#L2571-L2576)); it joins list items with a **space**, so it is not a "last line" source.

#### Library-generated vs tester-typed PoC

**No fragment-level marker exists.**

- `generated` is a field on `ParagraphFragment` only ([app/models.py](app/models.py#L74)), and PoC sections do not use paragraphs.
- Every copied fragment gets a **fresh `frag_id`**, server-side via `model_copy(deep=True)` + reassignment ([app/report_service.py](app/report_service.py#L434-L436)) and client-side via `remintFragments` ([app/web/static/app.js](app/web/static/app.js#L1062)). So the library's original ids (e.g. `VDB-015-web-poc`) never survive into a draft.

The only signal is **finding-level**: `Vulnerability.poc_variants` and `poc_variant_declined` ([app/models.py](app/models.py#L194-L195)), which record *which app types were installed or refused*, not which fragments came from where. Once a tester edits a copied step, nothing can tell it apart from one they typed.

`apply_poc_variant` has two modes ([app/report_service.py](app/report_service.py#L427-L447)): `"replace"` overwrites all non-image fragments; `"merge"` keeps them and appends. Twin: [app/web/static/app.js](app/web/static/app.js#L1075-L1089).

#### "The tester finished typing" — what a prompt could hang off

There is **no blur, change, or commit event on the list textarea**. It has only `oninput` ([app/web/static/app.js](app/web/static/app.js#L2416-L2421)). Available boundaries, in order of coarseness:

| Mechanism | Delay | Evidence |
|---|---|---|
| `reportchange` event → readiness panel recompute | 100 ms debounce | [docs/DATA_MAP.md](docs/DATA_MAP.md#L249-L255) |
| `persistLocalDraft` to `localStorage` | 150 ms | same |
| `queueBackendSave` → the PUT | **5000 ms idle**, restarted by every edit | [app/web/static/app.js](app/web/static/app.js#L115), [app/web/static/app.js](app/web/static/app.js#L274) |
| `focusout` on `root` → `finalizeTextTransaction` | next microtask, only when focus leaves **all** text entry | [app/web/static/app.js](app/web/static/app.js#L636-L642), `activeTextEntry` at [app/web/static/app.js](app/web/static/app.js#L633-L635) |
| Explicit save / Next / Back / `pagehide` / `visibilitychange` | immediate | [docs/DATA_MAP.md](docs/DATA_MAP.md#L261-L268) |

`scheduleSave` ([app/web/static/app.js](app/web/static/app.js#L644-L671)) is the funnel every edit goes through. Note its behaviour while a text field is focused: it takes an early-return branch that bumps `saveRevision` and re-arms the timers but **does not push an undo action** ([app/web/static/app.js](app/web/static/app.js#L646-L654)). One focused field is one undo step, closed by `finalizeTextTransaction`.

The nearest thing to a "finished typing" signal that already exists is therefore `focusout` on the containing `root`, which the transaction system already uses. There is no per-fragment equivalent.

---

### 4. List fragments and paste

**Answer.** A list is a flat `items: list[ListItem]`, each `ListItem` a bag of runs, with no per-item id. The whole fragment is edited in **one `<textarea>`, one item per line**. There is paste handling in the app, but **none on the list textarea**. Per-line `trim` and blank-line dropping already exist client-side; prefix stripping does not exist anywhere.

#### The exact model

```python
class ListItem(BaseModel):
    runs: list[Run] = Field(default_factory=list)


class ListFragment(BaseModel):
    frag_id: StableId
    type: Literal["numbered_list", "bulleted_list"]
    items: list[ListItem] = Field(min_length=1)
```

[app/models.py](app/models.py#L77-L84). `Run` at [app/models.py](app/models.py#L63-L67).

Flat. No nesting, no per-item `frag_id`, no ordinal stored — numbering is purely presentational. `min_length=1` means a list can never be empty, but an item **can** be `{runs: []}`. `load_path` backfills a missing `items` key with one empty item ([app/workspace.py](app/workspace.py#L278-L280)).

#### How list items are edited in the UI

One `<textarea>` per fragment, at [app/web/static/app.js](app/web/static/app.js#L2391-L2430):

- Value in: items joined with `\n`, each item's runs concatenated and any embedded newline collapsed to a space — [app/web/static/app.js](app/web/static/app.js#L2404)
- Placeholder: `"One item per line"` — [app/web/static/app.js](app/web/static/app.js#L2402)
- `aria-label`: `"Numbered list items"` / `"Bulleted list items"` — [app/web/static/app.js](app/web/static/app.js#L2401)
- Markers (`1.`, `2.`… or `•`) are drawn in a **decorative, `aria-hidden` gutter** beside the textarea, never in the value — [app/web/static/app.js](app/web/static/app.js#L2407-L2410), `renderLineMarkers` at [app/web/static/app.js](app/web/static/app.js#L153-L177)

Consequence for your change: the tester never sees `1. ` in the field, so a pasted `1. ` would render as a doubled number (`1. 1. Browse to…`) beside the gutter's own marker.

#### Existing normalisation on list items

**Client, on every keystroke and every paste** — [app/web/static/app.js](app/web/static/app.js#L2417-L2418):

```js
const lines = input.value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
fragment.items = (lines.length ? lines : [""]).map(text => ({runs:text ? [{text}] : []}));
```

So already: split on newline, **trim each line**, **drop blank lines**, and fall back to one empty item. What does **not** exist is stripping a `1.` / `2)` / `-` / `•` prefix.

Note this also **destroys per-run formatting** — every item becomes a single unformatted run.

**Server: none.** `ListFragment` has no validator ([app/models.py](app/models.py#L81-L84)). `provision` only creates lists, never cleans them. `generation_issues` *reports* blank items but does not fix them ([app/docx_report.py](app/docx_report.py#L120-L121)).

#### Is there a `location_lines` equivalent for list fragments?

**No.** `location_lines` ([app/report_service.py](app/report_service.py#L257-L270)) and its twin `locationLines` ([app/web/static/app.js](app/web/static/app.js#L959-L967)) are scope-only — they clean the "additional affected locations" box and nothing else. Their consumers are `scope_has_location`, `affected_environments`, `affected_channels`, `_scope_reaches_a_location`, and `docx_report._finding_locations` ([docs/DATA_MAP.md](docs/DATA_MAP.md#L167-L169)). There is no list-fragment counterpart on either side.

#### All existing paste handling in app.js

Four sites, exhaustively:

| Site | What it does | Evidence |
|---|---|---|
| `rich()` contenteditable | `preventDefault()`, then `execCommand("insertText", …, clipboardData.getData("text/plain"))` — **strips formatting, plain text only** | [app/web/static/app.js](app/web/static/app.js#L886) |
| Evidence tile | Takes the first `clipboardData.files` entry whose type starts `image/` and uploads it | [app/web/static/app.js](app/web/static/app.js#L2144-L2149) |
| Document-level fallback | If no card claimed the paste, forwards it to the first empty evidence tile that is not in `previous_proof_of_concept` | [app/web/static/app.js](app/web/static/app.js#L2545-L2548) |
| Formatting toolbar | `document.execCommand` for bold/italic/underline (not paste, but the same API) | [app/web/static/app.js](app/web/static/app.js#L885) |

The `rich()` handler applies to `paragraph` and `note` fragments and other `.rich` fields — **not** to list fragments, which are a plain `<textarea>` and receive no paste handler at all. `runsFrom` additionally strips leading and trailing whitespace-only runs for rich fields ([app/web/static/app.js](app/web/static/app.js#L866-L867)), which is a separate code path.

There is no `onpaste` on the scope textarea or the additional-locations textarea either; those clean on `oninput` like the list does.

---

### 5. Invariants and twins

#### Provisioning guarantees (server)

`provision` at [app/report_service.py](app/report_service.py#L192-L220), driven by `required_fragments` at [app/report_service.py](app/report_service.py#L198-L206):

| Section | Guaranteed |
|---|---|
| `description` | one `paragraph` |
| `recommended_remediation` | one `paragraph` |
| `previous_proof_of_concept` | `numbered_list`, then `image` |
| `proof_of_concept` | `numbered_list`, then `image` |
| `in_conclusion` | `[]` — **nothing from this map**; the conclusion block seeds a paragraph separately, and only when there are no paragraphs at all ([app/report_service.py](app/report_service.py#L240-L242)) |

Two further guarantees:

- `ensure_proof_steps`: a `numbered_list` always exists in both PoC sections, inserted at index 0 — [app/report_service.py](app/report_service.py#L155-L159), twin [app/web/static/app.js](app/web/static/app.js#L1057-L1059)
- `sync_evidence_image_slots`: one `proof_of_concept` image slot per affected environment — [app/report_service.py](app/report_service.py#L340-L394), twin [app/web/static/app.js](app/web/static/app.js#L1020-L1033)

**Sharp edge that matters here:** seeding only reaches an **empty** section (`if content.fragments or content.type not in required_fragments: continue`, [app/report_service.py](app/report_service.py#L208)). A section that already holds anything is never backfilled ([docs/DATA_MAP.md](docs/DATA_MAP.md#L338-L340)).

#### `deletionBlockedReason` (client-only)

[app/web/static/app.js](app/web/static/app.js#L1041-L1054). Blocks Delete on:

- the last fragment **of any type** in `description` or `recommended_remediation` ([app/web/static/app.js](app/web/static/app.js#L1042-L1044), driven by `requiresFragment` at [app/web/static/app.js](app/web/static/app.js#L111))
- the last `numbered_list` in either PoC section
- the last `image` in `previous_proof_of_concept`
- the last `proof_of_concept` image for an affected environment

**There is no rule for `in_conclusion`.** A tester can delete the conclusion paragraph outright; the next `provision` re-seeds the default sentence.

#### Rules that must change in pairs

I verified each against source rather than the doc. These are the ones this change touches:

| Rule | Python | JavaScript |
|---|---|---|
| The default conclusion sentence + its recogniser | [app/report_service.py](app/report_service.py#L233-L255), [app/report_service.py](app/report_service.py#L401-L405) | [app/web/static/app.js](app/web/static/app.js#L902-L918), [app/web/static/app.js](app/web/static/app.js#L901) |
| Which sections a status prints | [app/report_service.py](app/report_service.py#L162-L167) | [app/web/static/app.js](app/web/static/app.js#L920-L922) |
| Whether a section holds tester work | [app/report_service.py](app/report_service.py#L169-L190) | [app/web/static/app.js](app/web/static/app.js#L925-L931) |
| Required seed fragments | [app/report_service.py](app/report_service.py#L198-L206) | [app/web/static/app.js](app/web/static/app.js#L939) |
| A PoC always keeps one numbered list | [app/report_service.py](app/report_service.py#L155-L159) | [app/web/static/app.js](app/web/static/app.js#L1057-L1059) |
| Installing PoC steps, replace or merge | [app/report_service.py](app/report_service.py#L427-L447) | [app/web/static/app.js](app/web/static/app.js#L1075-L1089) |
| Collapsing appended steps into one list | [app/report_service.py](app/report_service.py#L414-L425) | [app/web/static/app.js](app/web/static/app.js#L1064-L1073) |
| Generation readiness | [app/docx_report.py](app/docx_report.py#L93-L142) | [app/web/static/app.js](app/web/static/app.js#L2565-L2620) |
| Description/remediation never empty | [app/docx_report.py](app/docx_report.py#L115-L116) | [app/web/static/app.js](app/web/static/app.js#L111), [app/web/static/app.js](app/web/static/app.js#L2584-L2586) |

**List-item normalisation has no Python twin today.** The `trim`-and-drop-blanks rule exists only at [app/web/static/app.js](app/web/static/app.js#L2417). Any paste-cleaning rule either stays client-only — and will be silently undone by a draft that reaches the server another way (`import_report`, `parse_report_docx`, a hand-edited file) — or a Python owner has to be created for it.

The only contract test guarding any of this is `test_browser_readiness_verdict_matches_server_generation_issues`, and it covers **generation readiness alone** ([docs/DATA_MAP.md](docs/DATA_MAP.md#L272)).

#### What `generation_issues` says about the conclusion and empty items

**About the conclusion: nothing beyond "must not be empty."**

`in_conclusion` is in `printed` for every non-`open_new` status, so its fragments are checked. A `ParagraphFragment` or `NoteFragment` with no text yields `"{label}: in_conclusion text is required"` ([app/docx_report.py](app/docx_report.py#L118-L119)). Client twin at [app/web/static/app.js](app/web/static/app.js#L2594).

**The default sentence has text, so it passes readiness clean.** Nothing today asks the tester to replace it. The `PLACEHOLDER_TEXT` regex ([app/docx_report.py](app/docx_report.py#L62-L65)) matches `(insert …)` and `insert technology/version/eol date/cves/latest … here` — it does **not** match the conclusion sentence. Same for the JS `placeholderPattern` ([app/web/static/app.js](app/web/static/app.js#L2570)).

**About empty list items: yes, both sides flag them.**

- Server: `"{label}: {content.type} list item text is required"` if **any** item has no text ([app/docx_report.py](app/docx_report.py#L120-L121))
- Client: for a `numbered_list` inside a PoC section, one aggregate message `"Steps to reproduce requires text"`; for any other list, a per-item `"item N text is required"` ([app/web/static/app.js](app/web/static/app.js#L2596-L2600))

In practice a blank item survives only as the single seeded empty item, because the textarea drops blank lines on input.

---

### 6. Drafts on disk

Six report folders under `data/apps/`. Four hold findings; **21 findings total**.

| Draft | Findings | Statuses |
|---|---|---|
| [data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json](data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json#L89) | 5 | `open_new` ×3, `open_previously_discovered` ×1, `resolved` ×1 |
| [data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json](data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json#L70) | 1 | `open_previously_discovered` |
| [data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json](data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L49) | 1 | `open_previously_discovered` |
| [data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json#L78) | 14 | all `open_new` |
| [data/apps/unnamed/2026-09_Report_404ecd327eea/draft.json](data/apps/unnamed/2026-09_Report_404ecd327eea/draft.json#L40) | 0 | — |
| [data/apps/unnamed/2026-09_Report_d96116840c2f/draft.json](data/apps/unnamed/2026-09_Report_d96116840c2f/draft.json#L42) | 0 | — |

#### Conclusion fragments

Exactly **4** `in_conclusion` sections exist, matching the 4 non-`open_new` findings. The 17 `open_new` findings have no such section at all.

| Finding | State | Evidence |
|---|---|---|
| `v_high` — "Broken Access Control on Account API" | default, unedited, `"generated": null` — `The finding "Broken Access Control on Account API" is still Open.` | [data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json](data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json#L476-L503) |
| `v_medium` — "Missing Rate Limiting on Password Reset" | default, unedited, `"generated": null` — `The finding "Missing Rate Limiting on Password Reset" is Resolved.` | [data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json](data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json#L716-L743) |
| `v_852106ea` — "Session Token Remains Valid after Session Expiry Message" | default, unedited, `"generated": null` | [data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json](data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json#L235-L262) |
| `v_10536a47` — "Authorization bypass" | **`"fragments": []`** — an empty conclusion section | [data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json](data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L225-L228) |

**Zero findings carry `generated: "status_conclusion"`.** A grep for that string across every `draft.json` under `data/apps/` returns no matches. All three populated conclusions carry `"generated": null`.

**No conclusion on disk has been edited by a tester** — all three match `_is_default_status_conclusion` exactly, so all three are still rewritable.

The empty one is explained: that draft still carries the retired `"poc_variant": null` key ([data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json](data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L65)), which `_migrate_poc_variant` strips on any modern save ([app/models.py](app/models.py#L236-L247)). It predates the migration and has not been through a `PUT` since. Its next save will seed the default sentence, taking the count of defaulted conclusions from 3 to 4.

#### Numbered/bulleted list contents

A regex search for run text beginning with `1.` / `2)` / `-` / `•` across all `data/apps/**/draft.json` returns **zero matches**. The same search across [resources/vuln_library.json](resources/vuln_library.json) also returns **zero matches** — library PoC steps are clean sentences, e.g. `"Browse to the assistant page as a standard user."` ([resources/vuln_library.json](resources/vuln_library.json#L74-L102)).

**No existing content would be stripped or double-stripped by a new cleanup rule.** That is unsurprising given the textarea already trims each line and the gutter supplies the visible numbering.

Blank list items do exist, as the seeded empty item — e.g. a `proof_of_concept` `numbered_list` with `"items": [{"runs": []}]` at [data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json](data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L203-L211).

#### What a "require the tester to replace the default" rule would retroactively mark incomplete

**3 findings today, 4 after one more save:**

1. `v_high`, Fragment_Coverage_Demo
2. `v_medium`, Fragment_Coverage_Demo
3. `v_852106ea`, Northstar_Banking `0931592e4fdd`
4. `v_10536a47`, Northstar_Banking `84b9ebe1bbdd` — currently empty, so it is *already* incomplete under the existing "text is required" rule ([app/docx_report.py](app/docx_report.py#L118-L119)); it joins the list above the moment it is saved

The 17 `open_new` findings are unaffected — they have no `in_conclusion` section, and `generation_issues` skips unprinted sections ([app/docx_report.py](app/docx_report.py#L111-L113)).

Two caveats I cannot resolve from the source, and will not guess about:

- The Fragment_Coverage_Demo and Vuln_Library_QA drafts **look like seeded fixtures**, not tester work — their `uid`s are `v_critical` / `v_high` / `v_medium` and their `frag_id`s are `v_high_conclusion` rather than the `f_<8 hex>` shape `provision` mints ([app/report_service.py](app/report_service.py#L211)). Whether they count as "real drafts" for migration purposes is a judgment call, not something the source establishes.
- `draft.bak.json` files exist beside three of these drafts and I did not inspect them; they hold one prior revision each ([docs/DATA_MAP.md](docs/DATA_MAP.md#L84-L86)) and are not loaded by any code path.

---

### Both-sides warning

Every rule this change touches is implemented twice and **must move in lockstep**:

- **The default conclusion sentence** — [app/report_service.py](app/report_service.py#L244-L249) and [app/report_service.py](app/report_service.py#L401-L405) on one side, [app/web/static/app.js](app/web/static/app.js#L915) and [app/web/static/app.js](app/web/static/app.js#L901) on the other. Four spellings of one sentence, with the regex as the only link. Change the sentence without changing the regex and every existing default on disk becomes permanently tester-authored, frozen at its old title and status.
- **Whether a section holds work** — `content_has_work` ([app/report_service.py](app/report_service.py#L169-L190)) / `contentHasWork` ([app/web/static/app.js](app/web/static/app.js#L925-L931)). Both currently skip the default conclusion. If a "replaced" conclusion must start counting as work, both arms change, and the status-change prompt's behaviour changes with them.
- **Readiness** — `generation_issues` ([app/docx_report.py](app/docx_report.py#L93-L142)) / `updateReadinessPanel` + `fragmentIssues` ([app/web/static/app.js](app/web/static/app.js#L2565-L2620)). This pair **is** guarded by a contract test, so a one-sided change will fail CI rather than ship silently.
- **PoC step installation** — `apply_poc_variant`/`merge_step_lists`/`ensure_proof_steps` and their three JS twins. Anything that reads "the last step" has to agree on both sides about what the step list even is after a merge.
- **List-item cleaning has no Python owner at all.** A paste-normalisation rule added only to [app/web/static/app.js](app/web/static/app.js#L2417) is not a twin — it is a new client-only rule with no server enforcement, and drafts arriving via `import_report` or `parse_report_docx` will bypass it entirely.

---

### Map drift

**One correction made.** [docs/DATA_MAP.md](docs/DATA_MAP.md) section 12 — the "rules that exist twice" table, whose whole purpose is to be exhaustive for pair-changes — was **missing the conclusion-sentence twin**. It listed `resolved remediation boilerplate` but not the `status_conclusion` sentence, despite `provision`/`_is_default_status_conclusion` and `syncConclusion`/`isDefaultStatusConclusion` being a genuine, undefended pair.

I added the row and a note recording three things the source establishes and the doc did not: that the sentence is an inline literal rather than a constant (unlike `RESOLVED_REMEDIATION`), that both sides share one three-part rewrite condition, and that `generated = "status_conclusion"` is read-only legacy that nothing writes but any consumer must still honour. I bumped the "Last verified" line to record the pass.

No other claim in the map was contradicted by source. Section 6's note that section membership is unvalidated, section 7's `provision` guarantees, section 8's `load_path` repairs, and section 13's "seeds only into an empty section" edge all check out.

## Round 1 - Planner: proposal and open questions

### Understanding

Five requests, which I read as **three independent pieces of work**. The first piece changes what the In Conclusion section starts life as: the last written step of the finding's proof of concept becomes available as an opening line, placed **above** the existing status sentence. The second changes what the tester owes before the report can be generated: the app-written status sentence must no longer be the whole conclusion. The third is unrelated to the conclusion entirely — pasting a numbered or bulleted list into a list fragment should strip the `1.` / `-` markers the tester can already see drawn in the gutter. The two prompts asked for (on status/title change, and after typing the proof of concept) are the user-facing surface of pieces one and two, not separate features.

Everything below is designed around one hard constraint the oracle established: the default sentence is recognised by `re.fullmatch` on the **whole paragraph text** ([app/report_service.py](app/report_service.py#L401-L405)) with a JavaScript twin anchored `^…$` ([app/web/static/app.js](app/web/static/app.js#L901)). Concatenating the proof-of-concept line into that paragraph destroys the recogniser for every draft on disk. So the line goes in **its own paragraph**, and that decision drives the rest.

---

### A. Blast radius

| File | What changes | Why |
|---|---|---|
| [app/report_service.py](app/report_service.py) | Extract the inline three-`Run` sentence in `provision`'s conclusion block into `status_conclusion_runs(title, status_word)`; extract the recogniser regex into a module-level `STATUS_CONCLUSION_PATTERN` that `_is_default_status_conclusion` uses. Add `has_default_status_conclusion(content) -> bool`. **No behaviour change in this file.** | The sentence has four spellings with the regex as the only link. Two of the four live here. Every later step in this plan reads "is this still the default?", and it must read it from one place. |
| [app/docx_report.py](app/docx_report.py) | One new issue inside the existing `printed`-section loop in `generation_issues`: `f"{label}: in_conclusion still holds the default sentence"` when `has_default_status_conclusion(content)`. | This is the enforcement half of "require the users to replace the default". It rides the existing readiness contract rather than inventing a new gate. |
| [app/web/static/app.js](app/web/static/app.js) | Six edits: (1) name the sentence builder and the regex beside the existing `RESOLVED_REMEDIATION` twin comment at [app/web/static/app.js](app/web/static/app.js#L113); (2) new `pocLastStep(finding)`; (3) new offer banner in the `in_conclusion` branch of `buildContentBlock`, beside the existing `proof_of_concept` offer; (4) new `hasDefaultStatusConclusion` + the readiness issue inside `fragmentIssues`; (5) the replace-or-keep prompt at the three title/status commit points; (6) `onpaste` on the list textarea. | All four twinned rules and every confirmation guard live in this one file. Items 1–5 are the conclusion work; item 6 is the list work and touches nothing else. |
| [app/web/static/app.css](app/web/static/app.css) | Reuse of the existing `.poc-offer` rules for the new banner; a selector addition only if the existing class cannot be reused verbatim. | Cosmetic. Listed so it is not a surprise. |
| [tests/test_app.py](tests/test_app.py) | New: the recogniser matches the builder's own output for both statuses and for a title containing a quote. New: the readiness issue appears for a defaulted conclusion and clears when overwritten. | The four-spellings problem has never had a drift guard. This is it. |
| [tests/test_browser.py](tests/test_browser.py) | New: the banner appears, inserts the step above the sentence, and disappears. New: the replace-or-keep prompt on a status change. New: a paste of `1. a\n2. b` lands as `a` / `b`. Extend `test_browser_readiness_verdict_matches_server_generation_issues` with a defaulted-conclusion case. | The readiness rule is a twin; the contract test is the only thing that catches a one-sided change. |
| [tests/test_docx.py](tests/test_docx.py) | **Two existing tests must have their fixtures updated** — see the data-risk table. | Both assert a fully ready report over a finding that is not `open_new`. |
| [docs/DATA_MAP.md](docs/DATA_MAP.md) | §12: the conclusion-sentence row gains the constant names; two new client-only entries (`pocLastStep` + the banner, and list paste cleaning); the readiness row is unchanged in shape. §13: the "clearing the conclusion restores the default" edge. Plus one **unrelated drift correction**, below. | The maintenance contract in the file's header requires it for any change to `report_service.py` or the save paths in `app.js`. |

**Map drift found while planning, unrelated to this change.** [docs/DATA_MAP.md](docs/DATA_MAP.md#L245) states that on the Content page "`validateCurrentPage` is never reassigned off its `() => true` default there, because that assignment lives in `setup()`". It is reassigned, inside `continuousEditor`, at [app/web/static/app.js](app/web/static/app.js#L2738), where it becomes the readiness check. The *conclusion* the doc draws is still correct — Back off the Content page is ungated — but for the other reason it gives: `.back-link` short-circuits on `document.querySelector("#editor")` at [app/web/static/app.js](app/web/static/app.js#L796) before `validateCurrentPage` is consulted. I am flagging it rather than fixing it inside this change.

---

### B. Open questions

Four decisions are waiting. They are ordered — **only question 1 needs an answer before work starts**; 2 and 3 can be answered while step 1 of the plan is in flight, and 4 only matters at the last step.

#### 1. Does "add the last line of the PoC to the Conclusion" happen automatically, or as a banner the tester clicks?

**Background.** The request says "add" for the library-generated case and "prompt the user to add" for the tester-typed case. The app has no way to tell those apart after the fact — the oracle established there is no fragment-level marker for library-sourced proof-of-concept steps, only the finding-level `poc_variants` list. So "automatic for library, prompt for typed" is implementable only at the exact instant `apply_poc_variant` runs, and never afterwards.

**Option A — one banner for both cases.** Inside the In Conclusion section, a message reading *Start the conclusion with your last step: "Observe the balance of another user"* with a **Use it** button. It appears whenever the proof of concept has a last written step, the conclusion still holds the default sentence, and that step is not already in the conclusion. It therefore appears within a second of a library install, and equally after the tester types their own last step. It is derived entirely from current state, so it survives a reload, cannot double-fire, and needs no "finished typing" event and no stored dismissal flag.

**Option B — automatic on library install, banner for typed.** `apply_poc_variant` and `applyPocVariant` both gain a write into `in_conclusion`. Two more lines in an already-twinned pair, plus the banner anyway for the typed case.

**Tradeoffs.** B is closer to the literal request. It also breaks the rule [docs/DATA_MAP.md](docs/DATA_MAP.md#L7) states for the proof-of-concept offer — *"Nothing is written without a click"* — and writes into a section that, under the other half of this request, the tester is then required to rewrite. It doubles the twin surface for no behaviour the tester cannot get by clicking once.

**Recommendation: A.** One mechanism, one code path, no new twin, and the tester sees the same affordance whichever way the steps got there.

#### 2. Is the copied line a snapshot, or does it track the PoC step for ever?

**Background.** Once the line is in the conclusion, the tester can edit the underlying step — or delete it. Nothing links the two.

**Option A — snapshot.** The text is copied once. If step 5 later changes, the conclusion keeps the old wording until the tester fixes it. Because the same change requires the tester to replace the default sentence sitting directly beneath it, they are guaranteed to look at this section before the report can be generated.

**Option B — derived live.** `provision` and `syncConclusion` rewrite the line on every save from the current last step. The tester can then never edit that line — their edit is overwritten on the next autosave, five seconds later. That is the `resolved_remediation` pattern, and the only reason it is tolerable there is that the section is boilerplate the tester is not meant to touch. A conclusion is the opposite.

**Tradeoffs.** A can go stale. B fights the tester and turns a sentence they are being *required* to author into a field they cannot edit.

**Recommendation: A, snapshot.** Staleness is visible and one edit away; a field that undoes your typing is neither.

#### 3. Does "require replacing the default" block generation, or block navigation?

**Background.** There are two enforcement shapes in the app already. Readiness (`generation_issues` ↔ `updateReadinessPanel`) lists the gap, marks the field, and disables the Generate button — this is how `PLACEHOLDER_TEXT` is handled. Navigation gates (`finding_is_complete` → `/edit` redirects) refuse to open a page at all.

**Option A — readiness issue.** The finding still opens, the row appears in the review panel with a working "go to" arrow, Generate is disabled until it is fixed.

**Option B — navigation gate.** `/edit` or Back refuses. This is the shape used by the affected-location rule.

**Tradeoffs.** B is unreachable by construction: the only place a tester can write a conclusion is the Content page, and the Content page is what `/edit` opens. A gate on it is a loop. Option A also inherits the only contract test in the codebase, `test_browser_readiness_verdict_matches_server_generation_issues`, which will fail loudly if the Python and JavaScript halves drift apart.

**Cost of either.** The oracle counted 3 findings on disk that become incomplete immediately and a 4th on its next save. On top of that, **every finding in a DOCX-imported retest** becomes incomplete, because `parse_report_docx` sets every retained finding to `open_previously_discovered`, which provisions a defaulted conclusion for each.

**Recommendation: A, readiness issue.** It is the only shape that leaves the fix reachable.

#### 4. Should the "replace or keep" prompt fire on title changes as well as status changes, and what exactly does "replace" replace?

**Background.** Today, when the title or status changes, a conclusion still holding the default sentence is silently re-derived, and one holding tester prose is silently left alone — including a prose conclusion that now says "Open" about a finding that has just become Resolved. The prompt is only meaningful in that second case.

**Option A — both triggers, replaces the first paragraph.** Fires on a committed title change and on a confirmed status change, only when the conclusion holds tester prose. **Replace** rewrites the *first* `ParagraphFragment` of the section with the freshly derived sentence; every other fragment is untouched. The dialog quotes the text being replaced in its list, and the whole thing is one undo step.

**Option B — status only.** A rename is usually a wording fix, and prompting on it is noise.

**Tradeoffs.** A is what was asked and catches the stale-`Resolved` case a rename can also cause (the title is interpolated into the sentence). Its cost is that a tester whose conclusion runs to three paragraphs loses the first one if they choose Replace — there is no automatic answer that is better, and undo covers it. B is quieter but leaves the title half of the request unimplemented.

**Recommendation: A**, with the dialog quoting the exact text at risk.

---

### C. Design decisions

These are decisions, not options. The alternatives are recorded so the oracle can attack the reasoning.

**1. The proof-of-concept line goes in its own paragraph, inserted at index 0 of the section — never concatenated into the default sentence's paragraph.** This is the load-bearing decision. `_is_default_status_conclusion` is a `re.fullmatch` over the joined run text of one paragraph; `isDefaultStatusConclusion` is the `^…$` twin. Prepending text into that paragraph makes it stop matching on both sides, which (a) freezes it at its current title and status for ever, (b) makes it count as tester work in `content_has_work`, changing what the status-change dialog says, and (c) does this retroactively to every default on disk if the recogniser is relaxed to compensate. A relaxed recogniser is worse still: an end-anchored `re.search` would match a paragraph in which the tester typed their conclusion *above* the sentence, and `provision` would then overwrite the whole paragraph, prose included. Two paragraphs cost nothing and keep `fullmatch` honest. `provision` finds the default by regex, not by position ([app/report_service.py](app/report_service.py#L237-L238)), so inserting above it is safe.

**2. Copied, not derived.** Per open question 2. The snapshot is written client-side on a click and is thereafter an ordinary `ParagraphFragment` that no server code recognises or rewrites. Consequence, stated plainly: **if the tester later edits or deletes that PoC step, the conclusion line does not follow.** It is stale until they fix it. The mitigation is that the default sentence directly beneath it still blocks generation, so they cannot ship without reading the section.

**3. "The last line" means: the last list item with non-blank text in the `proof_of_concept` section, scanning fragments in document order and items within them in order, across both `numbered_list` and `bulleted_list` fragments.** This is one total function, `pocLastStep(finding)`, and it answers all three awkward cases the oracle raised:
- *Ends with a blank item* (the seeded `items: [{runs: []}]`): blank items are skipped, so the answer is the last item that has text. If none do, there is no last line and no banner.
- *Several numbered lists* (a tester-typed PoC, since `merge_step_lists` only runs from `apply_poc_variant`): document order across all of them, so the answer is the last line the tester can see at the bottom of the section.
- *The last fragment is an image / a table / a note*: irrelevant. Only list items are considered. The last fragment is never consulted.

`previous_proof_of_concept` is **excluded**. It records the engagement before this one; a conclusion about this retest must not quote last year's steps.

The text is `"".join(run.text for run in item.runs).strip()`, copied as a single unformatted `Run`. Bold and italic within a list item are dropped — which costs nothing, because the list textarea already collapses every item to one plain run on any edit ([app/web/static/app.js](app/web/static/app.js#L2417-L2418)). Nothing is appended: no full stop, no space, no joining punctuation. That is only a question when two texts share a paragraph, and they do not.

**4. "Require replacing the default" is a readiness issue, and its predicate is "a paragraph matching the default sentence, or carrying `generated == "status_conclusion"`, is still present in a printed `in_conclusion`".** Per open question 3. Three consequences worth naming:
- **`open_new` findings are entirely unaffected.** They have no `in_conclusion` section, and `generation_issues` skips sections the status does not print ([app/docx_report.py](app/docx_report.py#L111-L113)). 17 of the 21 findings on disk are `open_new`.
- The rule is satisfied by **overwriting** the sentence, or by deleting the paragraph while another paragraph with text remains. It is *not* satisfied by emptying the paragraph: `provision` re-seeds the sentence into a text-less paragraph on the next save ([app/report_service.py](app/report_service.py#L239)), and the issue comes back. That is a genuine confusion and belongs in [docs/DATA_MAP.md](docs/DATA_MAP.md) §13.
- Accepting the banner does **not** satisfy the rule. The copied step is a second paragraph; the default sentence is still there. This is deliberate — otherwise "require the tester to replace the default" would be dischargeable by one click on a line the app wrote.

**5. The sentence becomes a named builder plus a named pattern on each side, in a step of its own with no behaviour change.** Four spellings with a regex as the only link is exactly the shape that breaks silently. After this step there are two owners per side — `status_conclusion_runs` / `STATUS_CONCLUSION_PATTERN` in Python, and their declared twins in `app.js` beside the existing `// Twin of report_service.RESOLVED_REMEDIATION` comment at [app/web/static/app.js](app/web/static/app.js#L113) — and a unit test that feeds the builder's own output to the recogniser for both statuses. `RESOLVED_REMEDIATION` is the precedent and it is the right one.

**6. No new field, and no new `generated` marker value.** I considered marking the copied line `generated: "poc_conclusion"` so it could be excluded from `content_has_work` and treated as boilerplate. Rejected: it widens a `Literal` in [app/models.py](app/models.py#L70-L74), which makes any draft written afterwards fail validation on an older build (demoting it to the manager's legacy list), it needs a clear-on-edit mechanism that does not exist for `resolved_remediation`, and it buys nothing — the readiness rule keys off the *default sentence*, which is still present, so the copied line does not need to be recognisable at all. Similarly, the banner needs no stored "declined" flag, because its visibility predicate includes "the default sentence is still present": writing your conclusion, which the tester must do anyway, is what dismisses it.

**7. List paste: `paste` only, not `input`.** The existing `oninput` handler already trims each line and drops blanks, and paste fires `input`, so cleaning could be done there in one line. It is the wrong place. A tester typing `1.` at the start of a line would watch the characters vanish under the cursor, and a step that legitimately begins `3. of the form` becomes untypeable. Paste is a distinct, unambiguous intent.

**Prefix shapes stripped, exactly:** `^\s*(\d{1,3}[.)]|\(\d{1,3}\)|[-*+•–—])\s+` per line, applied once (not repeatedly). Notes on each boundary:
- The trailing `\s+` is required. `1.2.3.4 is the target` keeps its `1.` because the `.` is followed by a digit.
- At most three digits, so a pasted timestamp or ID is not mistaken for an ordinal.
- **Roman numerals and lettered markers (`a.`, `i.`, `iv)`) are not stripped.** `i.` and `a.` are ambiguous with prose and with abbreviations; the cost of a missed strip is one manual edit, the cost of a wrong strip is silently deleted text.
- `•`, `–`, `—`, `-`, `*`, `+` are stripped. A line reading `- 192.168.0.1` loses its dash, which is the correct reading of a pasted bullet.

**8. List paste cleaning stays client-only, with no Python owner.** The oracle is right that this makes it bypassable by `import_report`, `parse_report_docx`, and a hand-edited file. That is the correct outcome. This is an *input affordance* — a rule about what happens to the clipboard on the way into a field — not a data invariant. A server-side stripper in `provision` would run on every save and would permanently delete a `1.` the tester typed on purpose, with no way back. The oracle also established that zero list items on disk and zero in [resources/vuln_library.json](resources/vuln_library.json) currently begin with such a marker, so there is nothing for a server-side rule to repair. It will be recorded in [docs/DATA_MAP.md](docs/DATA_MAP.md) §12's client-only list so the next audit reads it as a decision, not drift.

**9. Insertion mechanism: `setRangeText`, then invoke the existing `oninput` handler.** Not `document.execCommand("insertText")`, which is what `rich()` uses at [app/web/static/app.js](app/web/static/app.js#L886). `execCommand` is retained there because it preserves the native undo stack inside a contenteditable; for this textarea that argument does not apply, since Ctrl+Z is intercepted at document level and `preventDefault()`ed regardless of focus ([docs/DATA_MAP.md](docs/DATA_MAP.md#L221)) — native textarea undo is already gone. `setRangeText` does not fire `input`, so the handler is called explicitly, which keeps the fragment-writing logic in exactly one place.

**10. Shipping order: three units, not one change.** (a) List paste — client-only, no schema, no twin, no interaction with anything else in this list; ship it first and independently. (b) The constant extraction — no behaviour change, and a prerequisite for (c). (c) The banner, the prompt, and the readiness rule together. Within (c) the banner must land **before or with** the readiness rule: shipping the requirement first would block generation on 3–4 drafts while offering no new way to satisfy it.

---

### D. Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write / `saved_at` | **clear** | No new mutation path and no new endpoint. Every mutation here — the banner's Use it, the prompt's Replace, the paste — mutates the client `report` object and calls `scheduleSave()`, which rides the ordinary `PUT /reports/{id}` carrying `saved_at` in the body. Nothing uses the `X-Report-Saved-At` header path, which is reserved for library insert and evidence upload. |
| Lost update | **clear** | No read-modify-write is added on the server. The one server-side change, the new `generation_issues` branch, is read-only. `provision_report` continues to run inside the existing `save_report` handler, which persists through `save_if_current` under `Workspace._locked`. |
| Orphan reference | **clear** | The inserted paragraph is minted by `newFragment("paragraph")` ([app/web/static/app.js](app/web/static/app.js#L2096)), which produces `f_<8 hex>` exactly as `provision` does. It holds no `evidence_id` and no `scope.target_ids`, so there is nothing for `Report.validate_references` to be left pointing at. |
| Silent stranding | **clear** | Nothing in this change touches scope, environments, or image slots. `sync_evidence_image_slots` is not read or modified. |
| **Schema break / migration of existing drafts** | **clear on schema, RISK on meaning** | No field is added, no `Literal` widened, no validator changed — every `draft.json` on disk loads byte-identically and `validate_references` is unaffected. `load_path` needs no new repair. **But** the 3 findings holding an unedited default conclusion (`v_high` and `v_medium` in Fragment_Coverage_Demo, `v_852106ea` in Northstar_Banking) become generation-blocked the moment this ships, and `v_10536a47` joins them on its next save when its empty section is seeded. No migration can fix this, because the missing thing is tester prose. Mitigation: none, by design — the requirement is the feature. It must be stated in the release note. |
| **Existing tests that assert a fully ready report** | **RISK — two known breakages** | [tests/test_docx.py](tests/test_docx.py#L85) sets `report.vulnerabilities[1].status = "resolved"` and calls `provision`, then renders at [tests/test_docx.py](tests/test_docx.py#L104) with no `allow_incomplete`, so `render_report_docx` will raise `ReportGenerationError`. [tests/test_docx.py](tests/test_docx.py#L403), inside `test_previous_proof_of_concept_image_survives_a_narrower_retest`, asserts `generation_issues(report) == []` over a finding that `_carry_history` has just made `open_previously_discovered`. Both need one line of fixture: write a real conclusion into the affected finding. Everything else surveyed is safe — `ready_report` seeds `status="open_new"` ([tests/test_browser.py](tests/test_browser.py#L52)) and `test_docx.py`'s `_finding` helper defaults to `open_new` ([tests/test_docx.py](tests/test_docx.py#L584)), and the assertions in [tests/test_docx_import.py](tests/test_docx_import.py#L260), [tests/test_app.py](tests/test_app.py#L1033) and [tests/test_app.py](tests/test_app.py#L1058) are `assertIn`/`assertNotIn` on specific strings, which a new message cannot disturb. |
| **Readiness / the `generation_issues` contract test** | **RISK, and deliberately so** | The new rule is a twin pair. A one-sided implementation is exactly what `test_browser_readiness_verdict_matches_server_generation_issues` exists to catch, and it will catch it — **but only if a case with a non-`open_new` finding is added**, because every case in that test today runs on the `open_new` finding from `ready_report`, which has no `in_conclusion` section at all. As written, the test cannot see this rule in either direction. Adding the case is part of the work, not optional. |
| Python/JavaScript twin rules | **RISK, three of them** | (1) The default sentence and its recogniser — four spellings today, reduced to two named owners per side by step 2, with a new unit test feeding the builder's output to the recogniser. (2) Readiness — `generation_issues` ↔ `fragmentIssues`, guarded by the contract test above. (3) `content_has_work` ↔ `contentHasWork` — **not modified**, and that is a deliberate decision, not an omission: its existing skip of the default sentence is what keeps this change from altering the status-change dialog's behaviour for untouched findings. |
| Request/response asymmetry | **clear** | No client-only field is introduced, so nothing repeats the `scope_text` trap. The inserted paragraph is an ordinary `ParagraphFragment` that round-trips through `applyCanonicalReport` like any other. |
| **Derived-state fight** | **clear, and this is the point of decision 1** | Verified against [app/report_service.py](app/report_service.py#L233-L255) line by line for the state the banner creates. `provision` finds the default by regex (arm 2), which is position-independent, so the inserted paragraph does not displace it. The inserted paragraph always has text — the banner only appears when `pocLastStep` is non-blank — so it can never be captured by arm 3 ("first paragraph with no text") and overwritten with the status sentence. It is also therefore safe from the legacy `status_conclusion` purge at [app/report_service.py](app/report_service.py#L250-L255), which deletes only text-less sibling paragraphs. Under decision 2 (snapshot, not derived) there is nothing for the server to rewrite. |
| Navigation trap | **clear** | `/edit`'s gate is `setup_is_complete` plus `finding_is_complete` ([app/main.py](app/main.py#L638-L640)), and `finding_is_complete` reads title, ratings, status and scope — never `contents`. A conclusion-blocked finding still opens in the editor, which is the only page where a conclusion can be written. The readiness rule reaches only the Generate button and the review panel. |
| Backup exhaustion | **clear** | No path writes twice in quick succession. The banner click, the prompt's Replace, and a paste each call `scheduleSave()` once, which restarts the shared 5000 ms idle timer rather than issuing a save. |
| Dialog stacking | **RISK, low, mitigated by sequencing** | `vrDialog.ask` cancels any dialog already open — *"A second prompt would trap focus behind the first, so settle the open one first"* ([app/web/static/dialog.js](app/web/static/dialog.js#L11)). The status `onchange` handler already opens one dialog ([app/web/static/app.js](app/web/static/app.js#L1922)); the new conclusion prompt must be `await`ed strictly after it resolves and only when the status change was confirmed, never opened alongside it. |
| Existing status dialog starts naming In Conclusion | **clear, but a visible behaviour change** | `contentHasWork` skips the default sentence, which is why In Conclusion never appears in the "this will take … out of the report" list today. Once a tester writes a real conclusion — which this change requires — that section starts appearing in that list on a switch to `open_new`. No code changes; a previously unreachable output becomes reachable. Correct, and worth expecting. |
| DOCX import produces a wall of new issues | **RISK, accepted** | `parse_report_docx` makes every retained finding `open_previously_discovered`, so every finding in an imported retest is provisioned with a defaulted conclusion and is immediately generation-blocked. For a 14-finding import that is 14 new rows in the review panel on first open. This is arguably correct — a retest does owe a conclusion per finding — but it is a large first impression and belongs in the release note. |
| Paste cleaning damages existing content | **clear** | The rule runs on the clipboard payload only; it never rewrites `fragment.items` that are already in the draft. The oracle's regex sweep of `data/apps/**/draft.json` and of [resources/vuln_library.json](resources/vuln_library.json) found zero list items beginning with `1.` / `2)` / `-` / `•`, so there is nothing on disk for it to touch even if it did. |
| Paste cleaning strips a legitimate line | **RISK, bounded** | `- 192.168.0.1` loses its leading dash, and a step genuinely beginning `2) ` loses the marker. Both are the intended behaviour of the feature and both are one keystroke to restore, because the cleaning happens at paste time in a visible field. The `\s+` requirement and the 3-digit cap keep `1.2.3.4`, version strings, and IDs intact. |

---

### E. Plan

Each step names its files, its test, and the invariant it must not break. Steps 1, 2–3, and 4–6 are independently shippable in that order.

**Step 1 — List paste cleaning.**
*Files:* [app/web/static/app.js](app/web/static/app.js) (an `onpaste` beside the existing `oninput` at [app/web/static/app.js](app/web/static/app.js#L2416-L2421)), [docs/DATA_MAP.md](docs/DATA_MAP.md) §12 client-only list.
*Test:* [tests/test_browser.py](tests/test_browser.py) — dispatch a real `paste` event carrying `text/plain` into `.list-textarea`, following the `DataTransfer` pattern of the existing `paste_png` helper at [tests/test_browser.py](tests/test_browser.py#L529); assert `1. Alpha\n2) Beta\n- Gamma` persists as three items reading `Alpha`, `Beta`, `Gamma`, and that `1.2.3.4 is the host` survives whole.
*Invariant:* the field's value is still one item per line, trimmed, blanks dropped, and a paste into a selection replaces only that selection. The fragment is written by exactly one code path, the existing `oninput`.

**Step 2 — Name the sentence and its recogniser, Python side.**
*Files:* [app/report_service.py](app/report_service.py).
*Test:* [tests/test_app.py](tests/test_app.py) — `STATUS_CONCLUSION_PATTERN` fullmatches the joined text of `status_conclusion_runs(title, word)` for `Open` and `Resolved`, and for a title containing `"` and a regex metacharacter.
*Invariant:* no behaviour change. [tests/test_app.py](tests/test_app.py#L1599-L1624) must pass untouched, including its byte-exact run assertions.

**Step 3 — Name the same two things in JavaScript, and declare the twin.**
*Files:* [app/web/static/app.js](app/web/static/app.js) (beside `RESOLVED_REMEDIATION` at [app/web/static/app.js](app/web/static/app.js#L113)), [docs/DATA_MAP.md](docs/DATA_MAP.md) §12.
*Test:* [tests/test_browser.py](tests/test_browser.py#L1006-L1030) unchanged and passing — it already pins the client-rendered sentence to the exact string `The finding "Browser finding" is still Open.`
*Invariant:* `syncConclusion`'s three-part rewrite condition is unchanged — marker, or no text, or still matches. Only the spelling moves.

**Step 4 — `pocLastStep` and the In Conclusion offer banner.**
*Files:* [app/web/static/app.js](app/web/static/app.js), [app/web/static/app.css](app/web/static/app.css), [docs/DATA_MAP.md](docs/DATA_MAP.md) §12 client-only list.
*Test:* [tests/test_browser.py](tests/test_browser.py) — on an `open_previously_discovered` finding whose proof of concept has three steps plus a trailing blank item, the banner quotes step three; **Use it** inserts it as the first fragment of In Conclusion with the default sentence still second; the banner then disappears; both survive save and reload. A second case with two `numbered_list` fragments asserts the last line of the *second* one is offered.
*Invariant:* the section still holds exactly one fragment until the button is clicked — [tests/test_browser.py](tests/test_browser.py#L1006-L1030) asserts `.fragment` count is 1, and the banner is not a `.fragment`. Nothing is written without a click. The guidance string `Include a brief justification or explanation.` is not altered, because that test matches it with `exact=True`.

**Step 5 — The readiness rule, both sides, plus the contract-test case.**
*Files:* [app/docx_report.py](app/docx_report.py), [app/web/static/app.js](app/web/static/app.js), [tests/test_docx.py](tests/test_docx.py) (two fixture updates), [docs/DATA_MAP.md](docs/DATA_MAP.md) §13.
*Test:* a new `default_conclusion` case in `test_browser_readiness_verdict_matches_server_generation_issues` ([tests/test_browser.py](tests/test_browser.py#L1311)) that flips the finding to `open_previously_discovered` and provisions — the first case in that test to exercise a non-`open_new` finding. Plus a server-side test in [tests/test_app.py](tests/test_app.py) asserting the issue appears for the default and clears when the paragraph is overwritten, and does **not** appear for an `open_new` finding.
*Invariant:* an `open_new` finding never gains an issue from this rule. Both sides agree on the predicate for every case in the contract test, or CI fails.

**Step 6 — The replace-or-keep prompt.**
*Files:* [app/web/static/app.js](app/web/static/app.js) — the status `<select>` `onchange` at [app/web/static/app.js](app/web/static/app.js#L1915-L1929), the Findings-page title commit at [app/web/static/app.js](app/web/static/app.js#L1892-L1898), and `finishTitle` in the editor at [app/web/static/app.js](app/web/static/app.js#L2856). Also the library title path through `replaceFromLibrary` at [app/web/static/app.js](app/web/static/app.js#L1690), which changes the title without going through either commit handler.
*Test:* [tests/test_browser.py](tests/test_browser.py) — a finding whose conclusion has been overwritten with prose, changed from `open_previously_discovered` to `resolved`: the status dialog resolves first, then the conclusion prompt appears quoting the prose; **Keep** leaves the text byte-identical, **Replace** writes the freshly derived `is Resolved.` sentence. A second case asserts **no** prompt appears while the conclusion still holds the default.
*Invariant:* the prompt never fires while the conclusion is still boilerplate — that case stays silent, exactly as today. Only one dialog is open at a time, because `vrDialog.ask` cancels its predecessor. The status is not applied if the *status* dialog is cancelled, and the conclusion prompt is not reached in that case.

---

### What I would not do

**I would not concatenate the proof-of-concept line into the default sentence's paragraph**, even though "add to the beginning of the Conclusion field" reads most naturally that way. It breaks `re.fullmatch` on both sides, and the obvious repair — relaxing the recogniser to an end-anchored search — creates a worse bug than the one it fixes: a tester who types their conclusion above the sentence in the same paragraph would have the whole paragraph, prose included, silently overwritten by `provision` on the next save.

**I would not add a `generated: "poc_conclusion"` marker.** It widens a `Literal` in the schema for a distinction the readiness rule does not need, it makes new drafts unreadable to an older build, and it would require a clear-on-edit mechanism that does not exist for the one marker the app already has.

**I would not add a Python owner for list-marker stripping.** Twinning it would mean running the stripper inside `provision`, on every save, over text the tester may have typed deliberately — permanently deleting a `1.` with no way to get it back. A rule about the clipboard is not a rule about the document.

**I would not hang the "finished typing" prompt off a blur or `change` handler on the list textarea.** It would fire every time the tester tabbed out of their steps, it would steal focus from wherever they were heading, and it would need a stored "don't ask again" flag to stop nagging. The state-derived banner has none of those problems and is the pattern this codebase already uses for the proof-of-concept library offer.

**I would not enforce "replace the default" as a navigation gate.** The only place a conclusion can be written is the page the gate would close.

---

**Four decisions are open.** Question 1 — automatic insertion versus a click-to-use banner — is the only one that blocks starting, because it determines whether `apply_poc_variant` and `applyPocVariant` are in the blast radius at all. My recommendation there is the banner.

## Round 2 - Oracle: verdict on the proposal

### 1. The risk rows

#### `Derived-state fight — clear` → **WRONG**

This is the one that matters. The planner's stated reason is: *"The inserted paragraph always has text — the banner only appears when `pocLastStep` is non-blank — so it can never be captured by arm 3."* The predicate holds at insertion time and nowhere after it. By the planner's own decision 2, the copied line is "thereafter an ordinary `ParagraphFragment`" — which means the tester can clear its text, and then arm 3 does capture it.

**The selection walk you asked for.** Two paragraphs, PoC line at index 0, status sentence at index 1:

```python
generated = next((f for f in paragraphs if f.generated == "status_conclusion"), None)
default = generated or next((f for f in paragraphs if _is_default_status_conclusion(f)), None)
default = default or next((f for f in paragraphs if not _fragment_has_text(f)), None)
```

[app/report_service.py](app/report_service.py#L237-L239). `generated` is `None` (nothing writes that marker). Arm 2 scans in document order and the first match is the **status sentence at index 1** — it is the only paragraph matching the regex. `default` is now a truthy Pydantic model, so `default or ...` short-circuits and **arm 3 never runs**. The sentence at index 1 is rewritten; the PoC line at index 0 is untouched. For that state the planner is right.

**But that state is the state the plan forbids.** The whole point of the readiness rule is to make the tester overwrite index 1. Once they have, arm 2 returns `None`, and arm 3 becomes live over both paragraphs. Now clear the PoC line at index 0 — the obvious gesture when you change your mind about a quoted step, since deleting the fragment is a separate button:

- arm 2 → `None` (prose does not match the regex)
- arm 3 → `next((f for f in paragraphs if not _fragment_has_text(f)))` → **index 0**
- rewrite guard `not _fragment_has_text(default)` → `True` → [app/report_service.py](app/report_service.py#L244-L249) writes `The finding "<title>" is still Open.` into index 0

The app inserts boilerplate **above** the conclusion the tester just wrote, and under the plan's own new readiness rule that finding is generation-blocked again. Clearing it a second time reproduces it. The only escape is deleting the fragment — and `deletionBlockedReason` has no `in_conclusion` rule, so that does work, but nothing tells the tester it is the required move.

The planner did identify a version of this loop in decision 4 ("It is *not* satisfied by emptying the paragraph"), which makes the `clear` verdict on this row an internal contradiction: the same mechanism it documents as a known confusion, it declares impossible one section later.

**JS twin: identical, and it fires sooner.** `syncConclusion` uses the same three-arm chain — `generated || paragraphs.find(isDefaultStatusConclusion) || paragraphs.find(fragment => !fragmentHasText(fragment))` at [app/web/static/app.js](app/web/static/app.js#L909) with the same guard at [app/web/static/app.js](app/web/static/app.js#L912). And it runs on **editor boot for every finding** at [app/web/static/app.js](app/web/static/app.js#L2549), so the sentence reappears on the next page load, not just after a save.

**Corrected verdict for that row: RISK, unmitigated by decision 1.** Two paragraphs do not keep `fullmatch` honest; they widen arm 3's reach from one candidate to two.

#### `Navigation trap — clear` → **CONFIRMED**

```python
return bool(vulnerability.title.strip() and vulnerability.likelihood and vulnerability.impact and vulnerability.severity and vulnerability.status and scope_has_location(vulnerability, report))
```

[app/report_service.py](app/report_service.py#L598). No read of `contents`. The `/edit` gate is `setup_is_complete` plus that, at [app/main.py](app/main.py#L638-L640). A conclusion-blocked finding still opens.

#### `Orphan reference — clear` → **CONFIRMED**

`newFragment` mints `{frag_id: id("f"), type}` at [app/web/static/app.js](app/web/static/app.js#L2096), and `id` is `` `${prefix}_${crypto.randomUUID().replaceAll("-","").slice(0,8)}` `` at [app/web/static/app.js](app/web/static/app.js#L145) — `f_` + 8 hex, matching `f"f_{uuid.uuid4().hex[:8]}"` at [app/report_service.py](app/report_service.py#L211).

#### `Backup exhaustion — clear` → **CONFIRMED**

`queueBackendSave` does `clearTimeout(autoSaveTimer)` before arming a new one at [app/web/static/app.js](app/web/static/app.js#L274-L280). Restarts, does not issue.

#### `Paste cleaning damages existing content — clear` → **CONFIRMED**

Re-ran the sweep — it was cheap. `"text": "\s*(\d{1,3}[.)]|\(\d{1,3}\)|[-*+•–—])\s` across every `data/apps/**/draft.json` returns zero matches.

#### The two **RISK** rows carrying factual claims

**Both `test_docx.py` breakages — CONFIRMED**, with one line-number correction.

[tests/test_docx.py](tests/test_docx.py#L85) is `report.vulnerabilities[1].status = "resolved"` followed immediately by `provision(...)`, and the render is at [tests/test_docx.py](tests/test_docx.py#L100), **not** L104 as the plan says. `render_report_docx` raises when `issues and not allow_incomplete` at [app/docx_report.py](app/docx_report.py#L157), so the failure is `ReportGenerationError` out of line 100. [tests/test_docx.py](tests/test_docx.py#L403) is `assertEqual(generation_issues(report), [])` after `_carry_history` sets `open_previously_discovered` and provisions at [tests/test_docx.py](tests/test_docx.py#L377-L379) — the assertion fails with the new message in the list.

I swept the rest independently and the plan's "everything else is safe" holds. [tests/test_docx.py](tests/test_docx.py#L333), [tests/test_docx.py](tests/test_docx.py#L447) and [tests/test_docx.py](tests/test_docx.py#L531) all build findings through `_finding`, whose `status="open_new"` is at [tests/test_docx.py](tests/test_docx.py#L584), and never call `provision` — no `in_conclusion` section exists in any of them. [tests/test_docx_import.py](tests/test_docx_import.py#L260) is `assertIn`.

**Every contract-test case runs on `open_new` — CONFIRMED.** `cases` is the six closures at [tests/test_browser.py](tests/test_browser.py#L1340), each invoked over `self.ready_report(include_finding=True)`, which hardcodes `status="open_new"` at [tests/test_browser.py](tests/test_browser.py#L60). None of the six writes `finding.status`. The rule is invisible to the test in both directions until a case is added.

#### The remaining rows

`Stale write`, `Lost update`, `Silent stranding`, `Request/response asymmetry`, `Paste strips a legitimate line`, `Twin rules`, `Status dialog starts naming In Conclusion` — all **CONFIRMED**. `Dialog stacking` is **CONFIRMED** and correctly quoted: `if (openDialog) openDialog.settle("cancel")` at [app/web/static/dialog.js](app/web/static/dialog.js#L11).

`DOCX import produces a wall of new issues` — **half wrong**, see question 3.

`Schema break / migration` — **CONFIRMED on schema**; the count needs one correction, see question 3.

---

### 2. Files and owners the plan missed

**Readiness owners: the plan is right that there are two.** I checked for a third and there is none. `generation_issues` is imported once, at [app/main.py](app/main.py#L26), and called once, inside `finalized_report` at [app/main.py](app/main.py#L510). The manager page does not compute readiness. `allow_incomplete` appears only inside [app/docx_report.py](app/docx_report.py) and is never passed `True` by any route — only by [tests/test_docx.py](tests/test_docx.py#L286). So that path does not need to know about a new issue shape.

The review panel's "go to" arrow **is** a third consumer of the issue *shape*, though not of the rule. It keys off `issue.fragmentId` and derives the section from `issue.contentLabel` through `typeByLabel` at [app/web/static/app.js](app/web/static/app.js#L2657-L2663), and the `is-incomplete` marking uses `fragmentId` at [app/web/static/app.js](app/web/static/app.js#L2650). An issue emitted without a `fragmentId` gets no arrow and marks no field. The plan says "a twin in `fragmentIssues`" without naming that requirement.

**Title and status commit points — the plan's four are not exhaustive, but it caught the fifth.** The complete client-side set:

| Write | Site | Calls `syncConclusion`? |
|---|---|---|
| `finding.title = event.target.value` | [app/web/static/app.js](app/web/static/app.js#L1892) | yes |
| `finding.status = nextStatus` | [app/web/static/app.js](app/web/static/app.js#L1926) | via `provision` |
| `finding.title = titleInput.value.trim()` | [app/web/static/app.js](app/web/static/app.js#L2855) | — |
| `finding.title = entry.title` | [app/web/static/app.js](app/web/static/app.js#L2870) | yes, inline |
| `Object.assign(finding, {title: entry.title, …})` | [app/web/static/app.js](app/web/static/app.js#L1694) | **no** |

The last one is `applyLibraryEntry`, reached from `replaceFromLibrary` at [app/web/static/app.js](app/web/static/app.js#L1691), itself called from the row autocomplete at [app/web/static/app.js](app/web/static/app.js#L1891) and the committed-title path at [app/web/static/app.js](app/web/static/app.js#L1898). The plan names it, but as "`replaceFromLibrary` at L1690" — the actual writer is `applyLibraryEntry`, and the plan does not note what makes it different from the other four: **it is the only title write that does not re-derive the conclusion client-side.** Today that is masked, because the sentence still matches the regex and the server's `provision` fixes it on the next PUT. Under the plan the tester is being prompted at this exact moment, so the prompt and the sentence would disagree about what the title is until the save lands.

**Server side.** `insert_library` writes a title at [app/main.py](app/main.py#L722), but `Vulnerability.status` defaults to `open_new` at [app/models.py](app/models.py#L189) and `provision` therefore builds no `in_conclusion` — so it needs no prompt and cannot mint a defaulted conclusion. The only server-side status write is [app/docx_import.py](app/docx_import.py#L470). Everything else arrives wholesale through `save_report`.

**`pocLastStep` client-only — CORRECT, but for a reason the plan does not give.** The snapshot needs no Python twin because no server code reads it: `provision`'s conclusion block only ever touches the paragraph arm 2 or arm 3 selects, and `content_has_work` treats any paragraph with text as work at [app/report_service.py](app/report_service.py#L174-L177). The risk is not a missing twin, it is arm 3 — see above.

**Nothing in `docx_report` assumes one conclusion paragraph.** The section is rendered through a single anchor, `"conclusion-fragments-here": contents.get("in_conclusion")` at [app/docx_report.py](app/docx_report.py#L641), gated on `finding.status != "open_new"` at [app/docx_report.py](app/docx_report.py#L639). `_render_component_content` loops every fragment and appends at [app/docx_report.py](app/docx_report.py#L704-L726), and a `ParagraphFragment` clones `paragraph_fragment.docx` once at [app/docx_report.py](app/docx_report.py#L733-L734). No caption, no numbering, no per-section spacing rule. Two paragraphs render as two. The one thing to know is that an **empty** section renders the literal text `N/A` at [app/docx_report.py](app/docx_report.py#L695-L701).

---

### 3. Existing drafts on disk

**The count of 3 + 1 — CONFIRMED.** Exactly four `in_conclusion` sections exist across `data/apps/`: two in [data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json](data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json#L476) and [line 716](data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json#L716), one at [data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json](data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json#L235), all three holding the default sentence. The fourth is `"fragments": []` at [data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json](data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L225-L228). Zero `status_conclusion` markers anywhere.

**No existing draft is disturbed by a second paragraph.** Nothing constrains `Content.fragments` length, `load_path` has no conclusion repair, and the `"poc_variant": null` key at [data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json](data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L65) is stripped by `_migrate_poc_variant` at [app/models.py](app/models.py#L236-L247) independently of the conclusion. The `"fragments": []` draft gains its default sentence on first save via the `default is None and not paragraphs` branch at [app/report_service.py](app/report_service.py#L240-L242), exactly as the plan says.

**The DOCX-import claim — half wrong.** `"status": "open_previously_discovered"` for every retained finding is real, at [app/docx_import.py](app/docx_import.py#L470). But the plan says those findings are "provisioned with a defaulted conclusion and immediately generation-blocked," and that is false in two steps. `parse_report_docx` writes the section **empty** — `{"type": "in_conclusion", "fragments": []}` at [app/docx_import.py](app/docx_import.py#L472) — and `Workspace.import_report` at [app/workspace.py](app/workspace.py#L161) never calls `provision`. `finalized_report` does not provision either; it reads the stored report as-is at [app/main.py](app/main.py#L508-L510).

So on a freshly imported retest:

- **Server** sees `fragments: []`, finds no paragraph, reports no issue. `in_conclusion` is not in the `{"description", "recommended_remediation"}` empty-section check at [app/docx_report.py](app/docx_report.py#L115), so an empty conclusion is silent — the report generates and prints `N/A`. That is true today and the plan's rule does not close it, because its predicate is "a paragraph matching the default sentence is present."
- **Client** seeds the sentence on editor boot via `syncConclusion` at [app/web/static/app.js](app/web/static/app.js#L2549) — which does **not** call `scheduleSave()` — and then reports the new issue.

Result: a divergence window where the browser says "not ready" and the server says "ready," lasting until any edit triggers a PUT. It is the safe direction, and the contract test cannot see it because that test mirrors the save route with `main.provision_report(report)` before comparing, at [tests/test_browser.py](tests/test_browser.py#L1348). The plan's "14 new rows on first open" is right about the panel and wrong about the server.

---

### Other false assertions

**Decision 9's Ctrl+Z claim — TRUE.** I checked this one hardest because `setRangeText` rides on it:

```js
document.addEventListener("keydown", event => {
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== "z") return;
  event.preventDefault();
```

[app/web/static/app.js](app/web/static/app.js#L825-L827). Document-level, no `event.target` test, unconditional `preventDefault()`. Native textarea undo is genuinely already gone, so `setRangeText` forfeits nothing. The plan is right.

What it does not say is what replaces it. A paste happens while the textarea is focused, so `scheduleSave` takes the early-return branch at [app/web/static/app.js](app/web/static/app.js#L646-L654) and pushes **no undo action** — the paste folds into the open text transaction, closed only by `focusout` at [app/web/static/app.js](app/web/static/app.js#L636-L642). A tester cannot undo just the paste; one Ctrl+Z reverts the entire time they were in that field. That is the actual cost of stripping markers silently, and the plan presents decision 9 as cost-free.

**Decision 7's regex — verified correct on its stated boundary.** `^\s*(\d{1,3}[.)]|\(\d{1,3}\)|[-*+•–—])\s+` against `1.2.3.4 is the target`: `\d{1,3}` cannot extend past `1` because the next character is `.`, `[.)]` consumes the `.`, then `\s+` must match `2` and fails; no alternation branch recovers. The `1.` survives. One gap the plan does not mention: Word pastes bullets as `•\t`, which `\s+` does catch, but `•Text` with no separator is not stripped.

**Decision 3's "last line" — sound as a function, incomplete against the request.** It is a real total function and it does answer the three cases the round-1 report raised. But the PoC Add menu also offers `note`, `code_block`, and `instance_title` at [app/web/static/app.js](app/web/static/app.js#L109), and a `table` exists in a PoC section on disk at [data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json](data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L165-L189). A tester whose steps end with a `note` will be offered a line that is not the last thing in the section. The request said "the last item or line in the POC." That is a design gap to declare, not a bug.

**The plan's "map drift found while planning" — STALE, the correction is already in.** It says [docs/DATA_MAP.md](docs/DATA_MAP.md) claims `validateCurrentPage` is never reassigned outside `setup()`. The current text says the opposite, in the plan's own words: *"`validateCurrentPage` has **three** module-scope states… and a **second** assignment inside `continuousEditor()`… That third one is write-only — the `#editor` clause short-circuits before it is ever called."* That is [docs/DATA_MAP.md](docs/DATA_MAP.md#L246), and the header records the pass that added it. The planner is reading a version of the file that no longer exists. Its proposed correction would be a no-op.

---

### Invariants in play

- **`_is_default_status_conclusion` is `re.fullmatch` over one paragraph's joined runs** ([app/report_service.py](app/report_service.py#L401-L405)). Violate it and every default on disk freezes at its stored title and status. Decision 1 protects this correctly.
- **`provision`'s arm 3 will claim any text-less paragraph in the section, at any index** ([app/report_service.py](app/report_service.py#L239)). Violated by the plan's assumption that position 0 is safe once the sentence at position 1 is tester prose.
- **Seeding only reaches an empty section** ([app/report_service.py](app/report_service.py#L208)). This is why an imported `in_conclusion: []` still gets a sentence — the conclusion block bypasses `required_fragments` entirely.
- **`content_has_work` skips the default sentence but not an emptied paragraph's siblings** ([app/report_service.py](app/report_service.py#L174)). Once a real conclusion exists, In Conclusion starts appearing in the status dialog's hidden-sections list. Correct, and the plan expects it.

### Both-sides warning

Three pairs, all of which must move together:

- `_is_default_status_conclusion` ([app/report_service.py](app/report_service.py#L401-L405)) ↔ `isDefaultStatusConclusion` ([app/web/static/app.js](app/web/static/app.js#L901)), and the two builders at [app/report_service.py](app/report_service.py#L244-L249) ↔ [app/web/static/app.js](app/web/static/app.js#L915).
- The three-arm selection in `provision` ([app/report_service.py](app/report_service.py#L237-L239)) ↔ `syncConclusion` ([app/web/static/app.js](app/web/static/app.js#L909)). **Any fix for the arm-3 capture lands here, on both sides, and the client's copy runs on editor boot without a save — so the two will visibly disagree if only one moves.**
- `generation_issues` ([app/docx_report.py](app/docx_report.py#L111-L141)) ↔ `fragmentIssues` ([app/web/static/app.js](app/web/static/app.js#L2577-L2617)). Guarded, but only over `open_new` findings today.

List-marker stripping remains client-only with no Python owner, and I agree with decision 8 that it should stay that way.

### Map drift

**None.** Every claim I checked in [docs/DATA_MAP.md](docs/DATA_MAP.md) — §9's timers and the Ctrl+Z note, §10's three states of `validateCurrentPage`, §12's readiness and twin rows, §7's provisioning guarantees — matches source. No edit made.

---

### Verdict

The plan's architecture is sound and its shipping order is right. Decision 1 correctly identifies that the recogniser must not be relaxed. Four of the five `clear` rows you flagged are genuinely clear.

One thing blocks it: **`provision`'s arm 3 can capture the inserted paragraph, and it does so precisely in the state the readiness rule forces the tester into.** That needs an answer before step 4 is written, and the answer belongs on both sides. Two shapes exist — restrict arm 3 to the last paragraph rather than the first, or give it an explicit "not the first paragraph when a later one holds prose" condition — but choosing between them is the planner's job, not mine.

## Round 2 - Planner: revised plan

### Understanding

Three independent pieces of work. **One:** the last written step of a finding's proof of concept becomes available as an opening line of that finding's In Conclusion, in its own paragraph above the app-written status sentence. **Two:** that status sentence stops counting as a finished conclusion — a finding whose conclusion is still boilerplate cannot be generated, and a title or status change on a finding whose conclusion is tester prose asks whether to replace it. **Three:** unrelated to the conclusion, pasting a numbered or bulleted list into a list fragment strips the markers the tester can already see drawn in the gutter.

Two hard constraints shape everything. The first: `_is_default_status_conclusion` is a `re.fullmatch` over one paragraph's joined runs ([app/report_service.py](app/report_service.py#L401-L405)) with a `^…$` twin ([app/web/static/app.js](app/web/static/app.js#L901)), so the PoC line must go in its **own** paragraph — concatenating it destroys the recogniser for every draft on disk. The second, which Round 1 got wrong: once the section holds two paragraphs, `provision`'s third selection arm claims **any** text-less paragraph at any index ([app/report_service.py](app/report_service.py#L239)), so the two-paragraph shape is not free. It has to be paid for with a change to the selection chain, on both sides, before the banner ships.

---

### A. Blast radius

| File | What changes | Why |
|---|---|---|
| [app/report_service.py](app/report_service.py) | (a) Extract the inline three-`Run` sentence into `status_conclusion_runs(title, status_word)` and the regex into a module-level `STATUS_CONCLUSION_PATTERN`; rename `_is_default_status_conclusion` to a public `is_default_status_conclusion` so `docx_report` can import it. No behaviour change. (b) **Change the conclusion selection chain** at [app/report_service.py](app/report_service.py#L237-L239) per open question 1. | The sentence has four spellings with the regex as the only link, and every later step asks "is this still the default?". The selection chain is the blocking fix. |
| [app/docx_report.py](app/docx_report.py) | Two new issues inside the existing `printed` loop of `generation_issues`: the default sentence is still present; and `in_conclusion` joins `{"description", "recommended_remediation"}` in the empty-section check at [app/docx_report.py](app/docx_report.py#L115). Extends the existing `report_service` import at [app/docx_report.py](app/docx_report.py#L42). | The first is the enforcement half of "require the tester to replace the default". The second closes the escape hatch that would otherwise make the first dischargeable by deleting the paragraph, and closes the pre-existing hole where an empty conclusion generates silently and prints `N/A` ([app/docx_report.py](app/docx_report.py#L695-L701)). |
| [app/web/static/app.js](app/web/static/app.js) | Nine edits: (1) name the sentence builder and the regex beside the `RESOLVED_REMEDIATION` twin comment at [app/web/static/app.js](app/web/static/app.js#L113); (2) the matching change to `syncConclusion`'s selection chain at [app/web/static/app.js](app/web/static/app.js#L909); (3) `pocLastStep(finding)`; (4) the offer banner in the `in_conclusion` branch of `buildContentBlock` at [app/web/static/app.js](app/web/static/app.js#L2900-L2907); (5) `in_conclusion` added to `requiresFragment` at [app/web/static/app.js](app/web/static/app.js#L111); (6) the two new readiness issues in `fragmentIssues`; (7) `syncConclusion(finding)` inside `applyLibraryEntry` at [app/web/static/app.js](app/web/static/app.js#L1694); (8) the replace-or-keep prompt at the five title/status commit points; (9) `onpaste` on the list textarea at [app/web/static/app.js](app/web/static/app.js#L2416-L2421), bracketed by `finalizeTextTransaction()`. | Every twinned rule, every confirmation guard, and the undo transaction system live in this one file. |
| [app/web/static/app.css](app/web/static/app.css) | Reuse of the existing `.poc-offer` rules; a selector addition only if the class cannot be reused verbatim. | Cosmetic. Listed so it is not a surprise. |
| [tests/test_app.py](tests/test_app.py) | New: the recogniser matches the builder's own output for both statuses and for a title containing a quote and a regex metacharacter. New: a two-paragraph conclusion whose later paragraph holds prose is not overwritten when an earlier one is emptied. New: the readiness issue appears for a defaulted conclusion, clears when overwritten, and never appears for an `open_new` finding. | The four-spellings problem and the selection chain have never had a drift guard. |
| [tests/test_browser.py](tests/test_browser.py) | New: the banner appears, inserts above the sentence, and disappears. New: the replace-or-keep prompt on a status change. New: a list paste. New: one Ctrl+Z after a paste reverts only the paste. Extend `test_browser_readiness_verdict_matches_server_generation_issues` ([tests/test_browser.py](tests/test_browser.py#L1311)) with a non-`open_new` case. | Readiness is a twin and the contract test is the only thing that catches a one-sided change. |
| [tests/test_docx.py](tests/test_docx.py) | **Two existing tests need a fixture line each** — the render at [tests/test_docx.py](tests/test_docx.py#L100) over the finding made `resolved` at [tests/test_docx.py](tests/test_docx.py#L85), and the `assertEqual(generation_issues(report), [])` at [tests/test_docx.py](tests/test_docx.py#L403). | Both assert a fully ready report over a finding that is not `open_new`. |
| [docs/DATA_MAP.md](docs/DATA_MAP.md) | §12: the conclusion-sentence row gains the constant names and a fourth twin pair (the selection chain); `requiresFragment` grows a third member; two client-only entries (`pocLastStep` + banner, list paste cleaning). §13: the new one-sentence rule for where the app will and will not write the sentence. | The maintenance contract in that file's header requires it for any change to `report_service.py` or the save paths in `app.js`. |

Round 1 claimed a drift correction in [docs/DATA_MAP.md](docs/DATA_MAP.md) about `validateCurrentPage`. **That claim was stale — the map already says what I proposed adding.** It is dropped.

---

### B. Open questions

**Five decisions are waiting, and none has been put to you yet.** Only question 1 blocks starting — it is the fix for the fault the oracle found, and it decides the semantics every later step builds on. Questions 2 and 3 are needed by step 5, question 4 by step 6, question 5 by step 7.

#### 1. When the tester empties a paragraph in the In Conclusion section, should the app write its default sentence back into it?

**Background — this is the fault, stated in full.** Today the app picks which paragraph to write its status sentence into by walking three arms in order: a paragraph carrying the legacy `status_conclusion` marker (nothing ever writes it), then the first paragraph still matching the default sentence, then **the first paragraph with no text at all** ([app/report_service.py](app/report_service.py#L237-L239), twin at [app/web/static/app.js](app/web/static/app.js#L909)). With only one paragraph in the section, which is every finding today, the third arm just means "the tester cleared the sentence, so put it back".

This change puts a second paragraph in that section — the copied PoC line above the sentence — and the readiness half of this change then requires the tester to overwrite the sentence. Once they have, arm two finds nothing, arm three goes live across both paragraphs, and clearing the PoC line (the natural gesture when you change your mind about a quoted step, since deleting the fragment is a separate button) makes the app write `The finding "…" is still Open.` **above the conclusion they just wrote** — which re-blocks generation under the new rule. Clearing it again reproduces it. The client copy of this runs on editor boot for every finding ([app/web/static/app.js](app/web/static/app.js#L2549)), so it reappears on page load, not only after a save.

**Option A — the sentence owns the last paragraph slot.** Arm three stops scanning and looks only at the **last** paragraph in the section, taking it only if it is text-less. Clearing the last paragraph brings the sentence back, exactly as today. Clearing any earlier paragraph leaves it empty, and the existing `in_conclusion text is required` issue names it with a working "go to" arrow.

**Option B — the app never refills an emptied paragraph.** Arm three is deleted. The sentence is written once, when the section has no paragraphs at all, and afterwards only into a paragraph that still matches it. Emptying any paragraph, including the sentence's own, leaves it empty and produces `text is required`.

**Tradeoffs.** Both are a one-line change on each side, both fix the fault, and — importantly — **neither changes a single byte of any draft on disk, nor requires a `load_path` repair**: all four In Conclusion sections that exist hold either zero paragraphs or exactly one, and both options behave identically on zero and one. Neither disturbs any existing test; I checked the four that pin this behaviour ([tests/test_app.py](tests/test_app.py#L1599), [tests/test_app.py](tests/test_app.py#L976), [tests/test_app.py](tests/test_app.py#L1032), [tests/test_browser.py](tests/test_browser.py#L1006)) and every one stays on the single-paragraph or prose path.

They differ only in future behaviour. A keeps a way to get the default sentence back — clear the last paragraph — at the cost of keeping the loop where clearing it restores boilerplate that still blocks generation. B removes that loop entirely and replaces it with an accurate message, at the cost that once the sentence is replaced there is no way to ask for it back. B is also a deletion: it is the only option under which the app never writes over a paragraph a tester deliberately emptied.

**Recommendation: B.** The sentence is the thing this change exists to make them replace, so "get it back" is not a capability the app owes; and an empty paragraph saying "text is required" is a better instruction than boilerplate reappearing. **Absent an answer I would build A**, because it is the smaller behavioural change and can be narrowed to B later, whereas B cannot be widened back without re-opening the loop.

#### 2. Does "add the last line of the PoC to the Conclusion" happen automatically, or as a banner the tester clicks?

**Background.** The request says "add" for the library-generated case and "prompt the user to add" for the tester-typed case. Nothing in the data distinguishes them: there is no fragment-level marker for library-sourced PoC steps, only the finding-level `poc_variants` list ([app/models.py](app/models.py#L194-L195)), and every copied fragment gets a fresh `frag_id`. So "automatic for library, prompt for typed" is implementable only at the instant `apply_poc_variant` runs and never afterwards.

**Option A — one banner for both.** Inside the In Conclusion section: *Start the conclusion with your last step: "Observe the balance of another user"* with a **Use it** button. It appears whenever the proof of concept has a last written line and the conclusion holds nothing but the app's own sentence. Derived from current state, so it survives a reload, cannot double-fire, and needs no "finished typing" event and no stored dismissal flag.

**Option B — automatic on library install, banner for typed.** `apply_poc_variant` and `applyPocVariant` each gain a write into `in_conclusion` — two more lines in an already-twinned pair — plus the banner anyway for the typed case.

**Tradeoffs.** B is closer to the literal request. It also breaks the rule the proof-of-concept offer already follows — nothing is written without a click — and writes into a section the tester is then required to rewrite. It doubles the twin surface for no behaviour a single click does not give.

**Recommendation: A.** **Absent an answer I would build A**, and it is what the rest of this plan assumes.

#### 3. Is the copied line a snapshot, or does it track the PoC step for ever?

**Background.** Once the line is in the conclusion the tester can edit the underlying step, or delete it. Nothing links the two.

**Option A — snapshot.** Copied once. If the step later changes, the conclusion keeps the old wording until the tester fixes it.

**Option B — derived live.** `provision` and `syncConclusion` rewrite the line on every save from the current last step, so the tester can never edit that line — their edit is gone on the next autosave. That is the `resolved_remediation` pattern, tolerable there only because that section is boilerplate nobody is meant to touch.

**Tradeoffs.** A goes stale visibly and is one edit from correct; B turns a sentence the tester is being *required* to author into a field that undoes their typing.

**Recommendation: A, snapshot.** **Absent an answer I would build A.**

#### 4. Does "require replacing the default" block generation, or block navigation?

**Background.** Two enforcement shapes exist. Readiness (`generation_issues` ↔ `updateReadinessPanel`) lists the gap, marks the field, disables Generate. A navigation gate (`finding_is_complete` → `/edit` redirect) refuses to open the page.

**Option A — readiness issue.** The finding still opens, the row appears in the review panel with a working arrow, Generate is disabled until it is fixed.

**Option B — navigation gate.** `/edit` or Back refuses.

**Tradeoffs.** B is unreachable by construction: the only place a conclusion can be written is the Content page, which is what `/edit` opens, so the gate is a loop. A also inherits the codebase's only contract test, which fails loudly if the two sides drift.

**Cost of either, corrected.** Three findings on disk become generation-blocked immediately, and a fourth — the one whose section is `"fragments": []` — becomes blocked immediately too under step 6's empty-section rule, rather than on its next save. (Round 1 said that fourth one was "already incomplete". It is not: an empty `in_conclusion` is silent on the server today and generates a document printing `N/A`.) On top of that, every finding in a DOCX-imported retest is affected — see the risk table.

**Recommendation: A, readiness issue.** **Absent an answer I would build A.**

#### 5. Should the "replace or keep" prompt fire on title changes as well as status changes, and what does "replace" replace?

**Background.** Today a conclusion still holding the default is silently re-derived on a title or status change, and one holding tester prose is silently left alone — including prose that now says "Open" about a finding that just became Resolved. The prompt is only meaningful in that second case.

**Option A — both triggers.** Fires on a committed title change and on a confirmed status change, only when the conclusion holds tester prose. **Replace** rewrites the *first* `ParagraphFragment` of the section with the freshly derived sentence and leaves every other fragment alone. The dialog quotes the text at risk, and the whole thing is one undo step.

**Option B — status only.** A rename is usually a wording fix and prompting on it is noise.

**Tradeoffs.** A is what was asked and catches the stale-`Resolved` case a rename can also cause, since the title is interpolated into the sentence. Its cost is that a tester with a three-paragraph conclusion loses the first one if they choose Replace; there is no better automatic answer, and undo covers it. B leaves the title half of the request unimplemented.

**Recommendation: A**, with the dialog quoting the exact text at risk. **Absent an answer I would build A.**

---

### C. Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| **Derived-state fight** | **RISK — the blocking one, resolved by step 4** | `provision`'s arm three claims any text-less paragraph at any index ([app/report_service.py](app/report_service.py#L239)), and the twin runs on editor boot without a save ([app/web/static/app.js](app/web/static/app.js#L909), [app/web/static/app.js](app/web/static/app.js#L2549)). Once the readiness rule forces the sentence to be overwritten, arm two returns nothing and arm three reaches the copied PoC line; clearing that line makes the app write boilerplate above the tester's conclusion and re-block generation. Round 1 called this clear and was wrong. Step 4 changes the chain on both sides before step 5 creates the two-paragraph state. |
| Stale write / `saved_at` | clear | No new mutation path, no new endpoint. Banner click, prompt Replace, and paste all mutate the client `report` and call `scheduleSave()`, riding the ordinary `PUT` with `saved_at` in the body. Nothing touches the `X-Report-Saved-At` header path. |
| Lost update | clear | No read-modify-write added on the server. The `generation_issues` changes are read-only; `provision_report` still runs inside `save_report` under `Workspace._locked`. |
| Orphan reference | clear | The inserted paragraph comes from `newFragment("paragraph")` ([app/web/static/app.js](app/web/static/app.js#L2096)), which mints `f_` + 8 hex exactly as `provision` does. No `evidence_id`, no `scope.target_ids`. |
| Silent stranding | clear | Nothing here touches scope, environments, or `sync_evidence_image_slots`. |
| Schema break / migration | clear on schema, **RISK on meaning** | No field added, no `Literal` widened, no validator changed; every `draft.json` loads byte-identically and `load_path` needs no repair. Both options in question 1 behave identically on the zero- and one-paragraph sections that are the only ones on disk. **But** three findings holding an unedited default become generation-blocked the moment step 6 ships, and the fourth — `"fragments": []` at [data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json](data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L225-L228) — joins them immediately rather than on next save. No migration can fix this; the missing thing is tester prose. Release note. |
| **Client/server divergence on an imported retest** | **RISK, closed by step 6** | `parse_report_docx` sets every retained finding to `open_previously_discovered` ([app/docx_import.py](app/docx_import.py#L470)) but writes `in_conclusion` **empty** ([app/docx_import.py](app/docx_import.py#L472)), and neither `Workspace.import_report` ([app/workspace.py](app/workspace.py#L161)) nor `finalized_report` ([app/main.py](app/main.py#L508-L510)) provisions. So the server sees no paragraph, reports nothing, and generates a document printing `N/A`; the client seeds the sentence on editor boot without calling `scheduleSave()` and reports the new issue. The panel says "not ready", the server says "ready", until any edit triggers a PUT — and the contract test cannot see it, because it calls `main.provision_report(report)` before comparing ([tests/test_browser.py](tests/test_browser.py#L1348)). Step 6 adds `in_conclusion` to the empty-section check on both sides, so both verdicts become "not ready" and the `N/A` document stops being generable. Round 1's "14 new rows on first open" was right about the panel and wrong about the server. |
| Rule drift / twins | **RISK, four pairs** | (1) The sentence builder and its recogniser — four spellings, reduced to two named owners per side in steps 2–3 with a unit test feeding the builder's output to the recogniser. (2) **The selection chain** — `provision` ([app/report_service.py](app/report_service.py#L237-L239)) ↔ `syncConclusion` ([app/web/static/app.js](app/web/static/app.js#L909)); the client's copy runs without a save, so the two will visibly disagree if only one moves. (3) Readiness — `generation_issues` ↔ `fragmentIssues`, guarded by the contract test once a non-`open_new` case exists. (4) `requiresFragment` ↔ the server's empty-section set. `content_has_work` ↔ `contentHasWork` is deliberately **not** modified. |
| Contract test is blind to the new rule | **RISK, part of the work** | All six cases run over `ready_report(include_finding=True)`, which hardcodes `status="open_new"` ([tests/test_browser.py](tests/test_browser.py#L60)), and no case writes `finding.status`. An `open_new` finding has no `in_conclusion` section, so the rule is invisible in both directions. Adding a non-`open_new` case is not optional. The test compares the **verdict** (`data-state` and the Generate button), not message strings, so the two sides' wording may differ. |
| Review-panel issue shape | clear, by construction | The "go to" arrow keys off `issue.fragmentId` and derives the section from `issue.contentLabel` through `typeByLabel` ([app/web/static/app.js](app/web/static/app.js#L2657-L2663)); `is-incomplete` marking also uses `fragmentId` and ignores `level:"warning"` ([app/web/static/app.js](app/web/static/app.js#L2650)). **The new issue is emitted inside the per-fragment loop on the offending paragraph and carries `contentLabel: contentNames.in_conclusion`, `fragmentLabel: optionLabel("paragraph")`, `fragmentId: fragment.frag_id`, and error level** — so it gets an arrow, marks the field, and counts into the section flag. The empty-section issue reuses the existing `missingFragment` shape, which carries no `fragmentId` by design because there is no fragment to point at. |
| **`applyLibraryEntry` disagrees with the prompt** | **RISK, fixed in step 7** | `applyLibraryEntry` ([app/web/static/app.js](app/web/static/app.js#L1694)) is the only one of the five client-side title writes that does **not** re-derive the conclusion; the other four are [app/web/static/app.js](app/web/static/app.js#L1892), [app/web/static/app.js](app/web/static/app.js#L1926), [app/web/static/app.js](app/web/static/app.js#L2855) and [app/web/static/app.js](app/web/static/app.js#L2870). Today that is masked because the sentence still matches the regex and the server fixes it on the next PUT. Under this plan the tester is prompted at that exact moment, so the prompt and the on-screen sentence would disagree about the title until the save lands. Step 7 adds `syncConclusion(finding)` to `applyLibraryEntry` and makes both call sites `await` the prompt. |
| Navigation trap | clear | `/edit`'s gate is `setup_is_complete` plus `finding_is_complete` ([app/main.py](app/main.py#L638-L640)), and `finding_is_complete` never reads `contents` ([app/report_service.py](app/report_service.py#L598)). A conclusion-blocked finding still opens in the only page where a conclusion can be written. |
| Backup exhaustion | clear | `queueBackendSave` clears the pending timer before arming a new one ([app/web/static/app.js](app/web/static/app.js#L274-L280)). Banner click, prompt Replace, and paste each restart the shared idle timer rather than issuing a save. |
| Existing tests asserting a ready report | **RISK, two known breakages** | [tests/test_docx.py](tests/test_docx.py#L85) makes a finding `resolved` and provisions, then renders with no `allow_incomplete` at [tests/test_docx.py](tests/test_docx.py#L100) — `render_report_docx` raises when `issues and not allow_incomplete` ([app/docx_report.py](app/docx_report.py#L157)). [tests/test_docx.py](tests/test_docx.py#L403) asserts `generation_issues(report) == []` over a finding `_carry_history` has just made `open_previously_discovered`. One fixture line each. Everything else is safe: `ready_report` and `test_docx.py`'s `_finding` helper both default to `open_new`, and the other assertions are `assertIn`/`assertNotIn` on specific strings. |
| **Paste undo granularity** | **RISK, low, fixed in step 1** | Ctrl+Z is intercepted at document level and `preventDefault()`ed regardless of focus ([app/web/static/app.js](app/web/static/app.js#L825-L827)), so native textarea undo is already gone and `setRangeText` forfeits nothing — that part of Round 1 was right. What Round 1 did not say: a paste into a field with an open text transaction takes `scheduleSave`'s early-return branch ([app/web/static/app.js](app/web/static/app.js#L646-L654)) and pushes **no** undo action, folding into a transaction closed only by `focusout` ([app/web/static/app.js](app/web/static/app.js#L636-L642)). One Ctrl+Z would then revert the tester's whole time in that field, not just the paste — an unacceptable remedy for a silent strip. Step 1 brackets the paste with `finalizeTextTransaction()` before and after, making it exactly one undo step. |
| Paste cleaning damages existing content | clear | The rule runs on the clipboard payload only and never rewrites `fragment.items` already in the draft. A sweep of every `data/apps/**/draft.json` and of [resources/vuln_library.json](resources/vuln_library.json) finds zero list items beginning with such a marker. |
| Paste strips a legitimate line | **RISK, bounded and declared** | `- 192.168.0.1` loses its dash and a step genuinely beginning `2) ` loses the marker; both are the feature working, both are one keystroke to restore in a visible field, and step 1 makes that keystroke Ctrl+Z. The required trailing whitespace and the three-digit cap keep `1.2.3.4`, version strings and IDs intact. **Known gap:** Word pastes bullets as `•\t`, which is caught, but `•Text` with no separator is **not** stripped. Accepted — requiring a separator is what protects `1.2.3.4`. |
| Dialog stacking | **RISK, low, mitigated by sequencing** | `vrDialog` cancels any open dialog ([app/web/static/dialog.js](app/web/static/dialog.js#L11)). The status `onchange` already opens one ([app/web/static/app.js](app/web/static/app.js#L1922)); the conclusion prompt must be awaited strictly after it resolves, and only when the status change was confirmed. |
| Status dialog starts naming In Conclusion | clear, but a visible behaviour change | `contentHasWork` skips the default sentence, which is why In Conclusion never appears in the "this will take … out of the report" list today. Once a real conclusion exists — which this change requires — that section starts appearing on a switch to `open_new`. No code changes; a previously unreachable output becomes reachable. |
| "Last line" when the PoC ends with a non-prose fragment | **declared design gap, decision 3** | The PoC Add menu also offers `note`, `code_block` and `instance_title` ([app/web/static/app.js](app/web/static/app.js#L109)), and a `table` exists in a PoC section on disk. `pocLastStep` deliberately considers only prose-bearing fragment types, so a PoC ending with a code block is offered the line above it. The banner quotes the text, so the offer is never blind. |

---

### D. Design decisions

**1. The PoC line goes in its own paragraph at index 0, and the selection chain is fixed in the same change.** Concatenating into the sentence's paragraph breaks `re.fullmatch` on both sides, which freezes every default on disk at its stored title and status and makes it count as tester work. Relaxing the recogniser to an end-anchored search is worse: it would match a paragraph in which the tester typed *above* the sentence, and `provision` would overwrite the whole paragraph, prose included. So: two paragraphs. Round 1 stopped there and called it safe. It is not — two paragraphs widen arm three's reach from one candidate to two, which is the fault the oracle found. **The two-paragraph shape is only safe once the selection chain is narrowed (question 1), and that narrowing ships as its own step before the banner exists.**

**2. Copied, not derived.** Per question 3. The snapshot is written client-side on a click and is thereafter an ordinary `ParagraphFragment` that no server code recognises. Stated plainly: if the tester later edits or deletes that PoC step, the conclusion line does not follow. The mitigation is that the sentence beneath it still blocks generation, so they cannot ship without reading the section.

**3. "The last line" means the last non-blank line of the last prose-bearing fragment in `proof_of_concept`.** One total function, `pocLastStep(finding)`: scan fragments in reverse; take the first that is a `numbered_list`, `bulleted_list` or `note`; from it take the last item or line with text. Skip `image`, `table`, `code_block` and `instance_title`. This answers every awkward case — a trailing blank item (the seeded `items: [{runs: []}]`) is skipped; several numbered lists are handled because the scan is in document order; a trailing image is never consulted. `previous_proof_of_concept` is excluded entirely: a conclusion about this retest must not quote last year's steps.

Round 1 said "list items only". This widens it to `note`, because a note is prose and is exactly the kind of closing observation a conclusion wants, and narrows it away from `code_block` and `instance_title`, because a command line or a section heading quoted into a conclusion would make the tester distrust the banner. The gap remains that a PoC ending with a code block is offered the line above it — declared, not fixed. The text is `"".join(run.text for run in item.runs).strip()`, copied as one unformatted `Run`; no full stop or joining punctuation is appended, because that is only a question when two texts share a paragraph and they do not.

**4. The banner's visibility predicate is `!contentHasWork(conclusion) && pocLastStep(finding)`.** It shows when the section holds nothing but the app's own sentence — `contentHasWork` already skips the default sentence ([app/web/static/app.js](app/web/static/app.js#L925-L931)) — and a PoC line exists. Derived entirely from current state: it survives a reload, cannot double-fire, needs no stored dismissal flag, and disappears the moment any tester text exists in the section. This is stricter than Round 1's "the copied line is not already present", which would have made the banner reappear as soon as the tester edited the line they had just accepted.

**5. "Require replacing the default" is a readiness issue whose predicate is "a paragraph matching the default sentence, or carrying `generated == "status_conclusion"`, is present in a printed `in_conclusion`" — and the empty-section hole is closed alongside it.** Per question 4. Four consequences:
- **`open_new` findings are entirely unaffected.** They have no `in_conclusion`, and `generation_issues` skips unprinted sections ([app/docx_report.py](app/docx_report.py#L111-L113)). A carried conclusion on an `open_new` finding is also skipped, which [tests/test_app.py](tests/test_app.py#L1032) already pins.
- The rule is satisfied by overwriting the sentence, or by deleting the paragraph while another paragraph with text remains.
- **It is not satisfied by emptying the section**, and that is why `in_conclusion` joins the empty-section check on both sides. Without it, "write a conclusion" would be dischargeable by deleting the paragraph — and the resulting document prints `N/A` ([app/docx_report.py](app/docx_report.py#L695-L701)) with no issue raised. Adding `in_conclusion` to `requiresFragment` also blocks deleting the section's last fragment, which is the matching UI-side guarantee.
- Accepting the banner does **not** satisfy the rule. The copied step is a second paragraph and the sentence is still there. Deliberate: otherwise the requirement would be dischargeable by one click on a line the app wrote.

**6. The sentence becomes a named builder plus a named pattern on each side, in a step of its own with no behaviour change.** Four spellings linked only by a regex is the shape that breaks silently. Afterwards there are two owners per side — `status_conclusion_runs` / `STATUS_CONCLUSION_PATTERN` and their declared JS twins beside the existing `// Twin of report_service.RESOLVED_REMEDIATION` comment ([app/web/static/app.js](app/web/static/app.js#L113)) — plus a unit test feeding the builder's own output to the recogniser. `_is_default_status_conclusion` becomes public so `docx_report` can import it on the line that already imports from `report_service` ([app/docx_report.py](app/docx_report.py#L42)).

**7. No new field and no new `generated` marker value.** A `generated: "poc_conclusion"` marker would widen a `Literal` in [app/models.py](app/models.py#L70-L74), making new drafts fail validation on an older build, and it buys nothing: the readiness rule keys off the default sentence, so the copied line never needs to be recognisable.

**8. List paste cleans on `paste`, not on `input`.** The existing `oninput` already trims lines and drops blanks ([app/web/static/app.js](app/web/static/app.js#L2417-L2418)) and paste fires `input`, so cleaning there would be one line — and the wrong line. A tester typing `1.` would watch it vanish under the cursor, and a step legitimately beginning `3. of the form` would be untypeable. Paste is a distinct, unambiguous intent.

Prefixes stripped, per line, once: `^\s*(\d{1,3}[.)]|\(\d{1,3}\)|[-*+•–—])\s+`. The trailing whitespace requirement is load-bearing — it is what keeps `1.2.3.4 is the target` intact. Three digits maximum, so a pasted timestamp or ID is not read as an ordinal. Roman and lettered markers (`a.`, `i.`, `iv)`) are **not** stripped: they are ambiguous with prose, and a missed strip costs one edit while a wrong strip silently deletes text. A bullet with no separator (`•Text`) is not stripped either, for the same reason.

**9. The paste is one undo step, bought with two lines.** `finalizeTextTransaction()` before the mutation closes whatever transaction the tester's earlier typing opened; `setRangeText` applies the cleaned text; the existing `oninput` handler runs so the fragment is written by exactly one code path; `scheduleSave()` then pushes an undo action for the paste alone; a second `finalizeTextTransaction()` closes it so the next keystroke starts fresh. `document.execCommand("insertText")` is not used — it is retained in `rich()` ([app/web/static/app.js](app/web/static/app.js#L886)) because it preserves the native undo stack inside a contenteditable, and that stack does not exist here.

**10. List paste cleaning stays client-only, with no Python owner.** It is an input affordance — a rule about the clipboard on its way into a field — not a data invariant. A server-side stripper in `provision` would run on every save and permanently delete a `1.` a tester typed on purpose, with no way back. Nothing on disk or in the library would benefit from a repair. Recorded in [docs/DATA_MAP.md](docs/DATA_MAP.md) §12's client-only list so the next audit reads it as a decision rather than drift.

**11. Shipping order: four units.** (a) List paste — client-only, no schema, no twin, no interaction with anything else. (b) The naming extraction — no behaviour change, prerequisite for everything after. (c) The selection-chain fix — a behaviour change that stands alone and is worth shipping alone, because it makes the section safe for a second paragraph. (d) The banner, the readiness rules, and the prompt. Within (d), the banner must land before or with the readiness rules: shipping the requirement first would block generation on four drafts while offering no new way to satisfy it.

---

### E. Plan

**Step 1 — List paste cleaning, as one undo step.**
*Files:* [app/web/static/app.js](app/web/static/app.js) — an `onpaste` beside the `oninput` at [app/web/static/app.js](app/web/static/app.js#L2416-L2421); [docs/DATA_MAP.md](docs/DATA_MAP.md) §12 client-only list.
*Test:* [tests/test_browser.py](tests/test_browser.py) — dispatch a real `paste` carrying `text/plain` into `.list-textarea` following the `DataTransfer` pattern of `paste_png` at [tests/test_browser.py](tests/test_browser.py#L529); assert `1. Alpha\n2) Beta\n- Gamma` persists as `Alpha` / `Beta` / `Gamma`, that `1.2.3.4 is the host` survives whole, and that one Ctrl+Z after typing-then-pasting reverts the paste and leaves the typing.
*Invariant:* the field is still one item per line, trimmed, blanks dropped; a paste into a selection replaces only that selection; `fragment.items` is written by exactly one code path, the existing `oninput`. Verify `finalizeTextTransaction` is in lexical scope from the fragment editor — it is declared beside `scheduleSave` ([app/web/static/app.js](app/web/static/app.js#L536)), which the editor already reaches through `changed()`.

**Step 2 — Name the sentence and its recogniser, Python side.**
*Files:* [app/report_service.py](app/report_service.py).
*Test:* [tests/test_app.py](tests/test_app.py) — `STATUS_CONCLUSION_PATTERN` fullmatches the joined text of `status_conclusion_runs(title, word)` for `Open` and `Resolved`, and for a title containing `"` and a regex metacharacter.
*Invariant:* no behaviour change. [tests/test_app.py](tests/test_app.py#L1599-L1624) passes untouched, including its byte-exact run assertions.

**Step 3 — Name the same two things in JavaScript and declare the twin.**
*Files:* [app/web/static/app.js](app/web/static/app.js) beside [app/web/static/app.js](app/web/static/app.js#L113); [docs/DATA_MAP.md](docs/DATA_MAP.md) §12.
*Test:* [tests/test_browser.py](tests/test_browser.py#L1006-L1030) unchanged and passing — it already pins the client-rendered sentence to an exact string.
*Invariant:* `syncConclusion`'s rewrite condition is unchanged — marker, or no text, or still matches. Only the spelling moves.

**Step 4 — The conclusion selection chain, both sides. Blocked on question 1.**
*Files:* [app/report_service.py](app/report_service.py#L237-L239), [app/web/static/app.js](app/web/static/app.js#L909), [docs/DATA_MAP.md](docs/DATA_MAP.md) §12 (fourth twin pair) and §13 (the one-sentence rule for where the app will and will not write).
*Test:* [tests/test_app.py](tests/test_app.py) — a conclusion holding a prose paragraph followed by a second paragraph, where the **first** is emptied: `provision` must leave it empty and must not write the sentence into it. Plus the option-specific case (under A: emptying the **last** paragraph restores the sentence; under B: it does not, and `in_conclusion text is required` is reported instead). Plus a browser case asserting the client agrees on editor boot without a save.
*Invariant:* the creation branch still seeds the sentence into a section with no paragraphs at all ([app/report_service.py](app/report_service.py#L240-L242)) — that path does not go through the arm being changed, and the imported `"fragments": []` case depends on it. Arm one (the legacy `status_conclusion` marker) and its purge are untouched. All four existing conclusion tests pass unmodified.

**Step 5 — `pocLastStep` and the In Conclusion offer banner. Blocked on questions 2 and 3.**
*Files:* [app/web/static/app.js](app/web/static/app.js), [app/web/static/app.css](app/web/static/app.css), [docs/DATA_MAP.md](docs/DATA_MAP.md) §12 client-only list.
*Test:* [tests/test_browser.py](tests/test_browser.py) — on an `open_previously_discovered` finding whose PoC has three steps plus a trailing blank item, the banner quotes step three; **Use it** inserts it as the first fragment with the sentence still second; the banner disappears; both survive save and reload. A second case with two `numbered_list` fragments asserts the last line of the second is offered. A third case with a trailing `note` asserts the note's text is offered, and with a trailing `code_block` asserts the list line above it is.
*Invariant:* nothing is written without a click — [tests/test_browser.py](tests/test_browser.py#L1006-L1030) asserts the section opens with exactly one `.fragment`, and the banner is not a `.fragment`. The guidance string `Include a brief justification or explanation.` is untouched, because that test matches it with `exact=True`.

**Step 6 — The readiness rules, both sides, plus the contract-test case. Blocked on question 4.**
*Files:* [app/docx_report.py](app/docx_report.py) (the new default-sentence issue, `in_conclusion` added to the empty-section check at [app/docx_report.py](app/docx_report.py#L115), and the import line at [app/docx_report.py](app/docx_report.py#L42)); [app/web/static/app.js](app/web/static/app.js) (`fragmentIssues`, and `in_conclusion` added to `requiresFragment` at [app/web/static/app.js](app/web/static/app.js#L111) with its comment corrected from "these two" to three); [tests/test_docx.py](tests/test_docx.py) (two fixture lines); [docs/DATA_MAP.md](docs/DATA_MAP.md) §12 and §13.
*Test:* two new cases in `test_browser_readiness_verdict_matches_server_generation_issues` ([tests/test_browser.py](tests/test_browser.py#L1311)) — one flipping the finding to `open_previously_discovered` with the default conclusion left in place, one emptying the section — the first non-`open_new` cases that test has ever run. Plus server tests in [tests/test_app.py](tests/test_app.py): the issue appears for the default, clears when overwritten, appears for an empty printed section, and never appears for an `open_new` finding or a carried section.
*Invariant:* an `open_new` finding, and any carried unprinted section, never gains an issue from either rule — [tests/test_app.py](tests/test_app.py#L1032) pins this and must pass untouched. The new default-sentence issue carries `fragmentId` and `contentLabel` so the review panel's arrow and the `is-incomplete` marking both work. Both sides agree on the verdict for every case in the contract test, or CI fails.

**Step 7 — The replace-or-keep prompt, and the fifth title writer. Blocked on question 5.**
*Files:* [app/web/static/app.js](app/web/static/app.js) — the status `onchange` at [app/web/static/app.js](app/web/static/app.js#L1915-L1929); the Findings-page title commit at [app/web/static/app.js](app/web/static/app.js#L1892-L1898); `finishTitle` and the editor's library pick at [app/web/static/app.js](app/web/static/app.js#L2855-L2870); and **`applyLibraryEntry` at [app/web/static/app.js](app/web/static/app.js#L1694), which gains `syncConclusion(finding)`** so the on-screen sentence agrees with the title before the prompt quotes it. One shared `offerConclusionRewrite(finding)` helper, awaited at each site.
*Test:* [tests/test_browser.py](tests/test_browser.py) — a finding whose conclusion is prose, changed from `open_previously_discovered` to `resolved`: the status dialog resolves first, then the conclusion prompt appears quoting the prose; **Keep** leaves the text byte-identical, **Replace** writes the freshly derived `is Resolved.` sentence, and either way it is one undo step. A second case asserts no prompt while the conclusion still holds the default. A third picks a library entry from the Findings-page row on a finding with a defaulted conclusion and asserts the rendered sentence names the new title immediately, before any save.
*Invariant:* the prompt never fires while the conclusion is still boilerplate — that case stays silent, exactly as today. Only one dialog is open at a time. The status is not applied if the status dialog is cancelled, and the conclusion prompt is not reached in that case. Making `titleInput.onchange` async must not change its behaviour: it currently branches on `replaceFromLibrary`'s synchronous return, so the call sites are converted to `await` rather than left to test a Promise for truthiness.

---

### F. What I would not do

**I would not keep the two-paragraph shape without changing the selection chain.** That was Round 1's mistake. The plan's own readiness rule drives the section into the exact state where arm three reaches a paragraph it must not touch, and the client copy of that code runs on editor boot, so the boilerplate reappears on a page load with no save involved.

**I would not solve the arm-three capture by making "Use it" overwrite the default sentence instead of sitting above it.** It is tempting — one paragraph, nothing to fix — but it makes a single click discharge a requirement whose entire purpose is that the tester writes the conclusion themselves, and the request is explicit that the line goes *before* the default value, not instead of it.

**I would not solve it by writing `generated: "status_conclusion"` onto the app's own paragraph.** The value already exists in the `Literal`, so it costs no schema widening, and it would make the app's paragraph unambiguous. But a paragraph carrying that marker makes the rewrite guard true **unconditionally** ([app/report_service.py](app/report_service.py#L243)) — the app would overwrite tester prose on every save — and it purges every text-less sibling paragraph. Making it safe needs a clear-on-edit mechanism that does not exist, plus a backfill over the three defaults on disk that all carry `generated: null`, producing drafts that an older build would overwrite on every save. That is a migration with a one-way trapdoor in it.

**I would not concatenate the PoC line into the sentence's paragraph.** It breaks `re.fullmatch` on both sides, and the obvious repair — an end-anchored search — creates a worse bug: a tester who types their conclusion above the sentence in the same paragraph has the whole paragraph, prose included, silently overwritten on the next save.

**I would not leave the empty-conclusion hole open.** Without it, "you must write a conclusion" is dischargeable by deleting the paragraph, and the resulting document prints `N/A` in every conclusion with the server reporting nothing wrong. It is also the exact hole a DOCX-imported retest lands in, which is where the client and server currently disagree.

**I would not add a Python owner for list-marker stripping.** Twinning it means running the stripper inside `provision` on every save, over text the tester may have typed deliberately, deleting it with no way back. A rule about the clipboard is not a rule about the document.

**I would not hang the "finished typing" prompt off a blur or `change` handler on the list textarea.** It would fire every time the tester tabbed out of their steps, steal focus, and need a stored "don't ask again" flag. The state-derived banner has none of those problems and matches the pattern the proof-of-concept library offer already uses.

**I would not enforce "replace the default" as a navigation gate.** The only place a conclusion can be written is the page the gate would close.

---

**Five decisions are waiting, and here is the first — it is the one that unblocks everything else.**

Question 1: when the tester empties a paragraph in the In Conclusion section, should the app write its default sentence back into it? Option A keeps that behaviour but confines it to the section's **last** paragraph, so the sentence can be recovered by clearing the closing line, while an emptied earlier paragraph is left alone. Option B removes the refill entirely — the app writes the sentence once into a section that has no paragraphs at all, maintains it only while it is untouched, and never writes into a paragraph the tester emptied; an emptied paragraph then reports `text is required` with a working arrow instead. Both are one line per side, neither alters any draft on disk, and neither disturbs any existing test. A preserves a way to get the sentence back; B removes the loop where clearing it restores boilerplate that still blocks generation. I recommend B.

Next action: choose option A or option B for question 1.

## Answers

### 1. When a tester empties a paragraph in In Conclusion, does the app write the default sentence back?

**Answered: neither option as put.** Do not refill. But when the paragraph is empty, show an offer — the same shape as the existing library-value banners — asking whether to put the default sentence back.

> "do not refil but, if it is empty, add a prompt like the ones used when there is a library value available, add a prompt like that if they would like to add the default value."

This resolves the planner's one hesitation about Option B. Its objection was that B removes any way to get the sentence back; the banner *is* that way, and it keeps the codebase's existing rule that nothing is written without a click.

### 2. Is the proof-of-concept line added automatically, or offered as a banner?

**Answered: Option A** — always a banner with a **Use it** button, for both library-installed and tester-typed steps.

### 3. Is the copied line a snapshot, or does it track the step it came from?

**Answered: Option A, with an addition.** Copied once — but when the proof of concept gains a *new* last line, offer it again.

> "copied once. but when there is another new line in the POC, then, can ask the users again"

This is a real extension, not a clarification: the app must now remember which proof-of-concept text it has already offered, otherwise the banner reappears the moment the tester edits the line they just accepted. Round 2's predicate (`!contentHasWork(conclusion)`) cannot express it.

### 4. Does an unreplaced default block generation, or block navigation?

**Answered: Option A** — a readiness issue. The finding still opens; the review panel lists it with a working "go to" arrow; Generate is disabled until it is fixed.

### 5. Does the replace-or-keep prompt fire on name changes as well as status changes?

**Answered: Option A** — both triggers, only when the conclusion holds tester prose, with the dialog quoting the exact text at risk.

### 6. Should the banner re-offer on a reworded last step, or only on an added one? *(raised by the planner's addendum)*

**Answered: Option A** — re-offer whenever the last line's text differs, rewording included. The steps field rewrites every line on any keystroke, so the app cannot distinguish an edit from an append; re-offering on both keeps a stale quoted line one click from correct, via an **Update the quoted step** button. Accepted cost: the banner no longer disappears when the tester types, so a tester who always writes conclusions by hand clicks **Dismiss** once per finding.

## Round 3 - Planner: design addendum after the answers

### 1. Change 1 specified — the restore-default banner

#### 1.1 The selection-chain change (Option B semantics)

Arm three is deleted from both sides. In [app/report_service.py](app/report_service.py#L239) the line `default = default or next((fragment for fragment in paragraphs if not _fragment_has_text(fragment)), None)` goes; in [app/web/static/app.js](app/web/static/app.js#L909) the clause `|| paragraphs.find(fragment => !fragmentHasText(fragment))` goes.

**The creation branch stays, and it is load-bearing.** With arm three gone, `default` can be non-`None` only via arm one (the legacy marker, which nothing writes) or arm two (a paragraph still matching the sentence). The branch at [app/report_service.py](app/report_service.py#L240-L242) is therefore the *only* remaining path that mints a paragraph, and its freshly minted `runs=[]` paragraph is the only fragment that can still satisfy the `not _fragment_has_text(default)` clause of the rewrite guard at [app/report_service.py](app/report_service.py#L243). Both must stay: remove the branch and an imported `"fragments": []` conclusion is permanently blank; remove that clause of the guard and the newly created paragraph is created empty and never written.

Net effect: after this step the app writes the sentence in exactly two circumstances — into a section holding zero paragraphs, and into a paragraph that still matches the sentence. It never writes into a paragraph a tester emptied.

#### 1.2 Visibility predicate

Client-only, in the `in_conclusion` branch of `buildContentBlock` at [app/web/static/app.js](app/web/static/app.js#L2912-L2917):

```
contentTypesForStatus(finding.status).includes("in_conclusion")
&& content.fragments.some(f => f.type === "paragraph" && !fragmentHasText(f))
&& !content.fragments.some(isDefaultStatusConclusion)
```

Each clause is load-bearing:

1. **Printed sections only.** A carried `in_conclusion` on an `open_new` finding never reaches the document and readiness already skips it ([app/docx_report.py](app/docx_report.py#L111-L113)), so offering to write a status sentence into it is noise.
2. **An empty paragraph exists.** This is your "if it is empty". Without it the banner would appear the instant the tester overwrote the sentence with their own prose — a nag fired by the exact action this change exists to encourage.
3. **No default sentence present.** Nothing to restore, and it makes the banner self-dismissing: accepting removes its own trigger.

**Deleting the paragraph is not the empty case.** A tester who deletes the fragment outright leaves no empty paragraph, so no banner. That is correct and symmetrical with Change 2: deleting is an answer, emptying is an ambiguous state.

**A zero-fragment section is not a banner case either.** The creation branch writes the sentence automatically, `syncConclusion` runs on editor boot for every finding ([app/web/static/app.js](app/web/static/app.js#L2549)), and step 8 adds `in_conclusion` to `requiresFragment` so the last fragment cannot be deleted. The section is never observed empty in the editor.

**No new field, no dismissal record.** The predicate is pure current state. The tester quiets it by typing into the empty paragraph or deleting that fragment. This asymmetry with Change 2 — which does need a field — is deliberate and worth stating: Change 1 asks a question the current state can answer, Change 2 asks one it cannot.

#### 1.3 Both banners at once

**Yes, both can be visible simultaneously.** Concretely: the tester empties the sentence's paragraph *and* the proof of concept holds a last line that has never been resolved. Both predicates hold independently; neither suppresses the other.

**Order: proof-of-concept-step banner first, restore-default banner second.** This mirrors the paragraph order the two produce — Round 2's decision that the PoC line sits above and the sentence below. The stacked pair therefore reads as a preview of the resulting section rather than as two competing asks.

**Does it read badly?** Honestly: it is a new maximum for this app — today every section renders at most one banner ([app/web/static/app.js](app/web/static/app.js#L2919) and [app/web/static/app.js](app/web/static/app.js#L2977)). Two stacked `.content-offer` cards is heavy. It is coherent because of the ordering, and because the primary verbs differ ("Use it" / "Put it back") rather than being two spellings of "Fill from library". I rejected suppressing the restore banner while the PoC banner shows: that hides a recovery affordance behind an unrelated offer, and a tester may want only the sentence.

DOM hooks for tests: `div.content-offer[data-conclusion-step]` and `div.content-offer[data-conclusion-restore]`, both reusing `offerTag()` from [app/web/static/app.js](app/web/static/app.js#L2559) and the existing `.content-offer` CSS.

#### 1.4 What accepting writes, and where

It writes the runs from the named builder step 3 introduces — the same source as `syncConclusion` — **into the last text-less `paragraph` fragment in the section, in place**. No insert, no move, no delete, no change to the fragment count. Then `render(); scheduleSave();`, one undo step, like every other banner.

- **Why in place, not appended.** Appending would leave the emptied paragraph behind, and an empty paragraph is a readiness error (`In Conclusion — paragraph text is required`, [app/web/static/app.js](app/web/static/app.js#L2604)). A banner whose accept action creates a *new* error is worse than the state it left.
- **Why the last text-less paragraph.** It honours the meaningful order: the sentence belongs below the quoted step. In the common case — the tester emptied the sentence's own paragraph, which is the bottom one — there is exactly one candidate and the question is moot.
- **Declared consequence.** With paragraphs `[empty, prose]`, the sentence lands *above* the prose. I take that rather than silently relocating a fragment; writing where the tester is looking is more predictable than reordering their section.

#### 1.5 Does accepting re-trigger the Q4 readiness issue?

**Yes.** It writes exactly the sentence `is_default_status_conclusion` recognises, so step 8's "still holds the default sentence" issue fires on the next readiness recompute.

**It is not a trap, and here is the falsifiable reason.** Compare the two states:

| | Readiness | Generate |
|---|---|---|
| Before the click | `In Conclusion — paragraph text is required` | blocked |
| After the click | `In Conclusion — still holds the default sentence` | blocked |

The click never moves the finding from clean to blocked. It swaps one error row for another and puts real text into a section that will print. That is a poor affordance if the tester expected it to resolve something, so **it is resolved by copy, not by mechanism**:

> *Suggested* — The standard closing sentence is missing. Put it back as a starting point; you will still need to replace it with your own wording before generating. **[Put it back]**

Two alternatives rejected:

- **Exempt a restored sentence from the readiness rule.** Needs a marker distinguishing restored from seeded, which means widening the `generated` `Literal` at [app/models.py](app/models.py#L74) — Round 2 decision 7, rejected for the same reason (new drafts become unreadable to an older build). It is also semantically wrong: a restored default is a default.
- **Suppress the banner while the readiness rule is live.** The rule is live for every printed section, so this deletes the banner.

**Corollary to pin in a test:** the restored paragraph matches the recogniser, so arm two owns it again — a later title or status change re-derives it exactly as a seeded sentence would. Restoring the sentence restores its liveness. It does *not* arm the Q5 replace-or-keep prompt, which fires only on tester prose.

---

### 2. Change 2 specified — the re-offer mechanism

#### 2.1 Does this need a persisted field? Yes

Distinguishing "the tester edited the line they accepted" from "the proof of concept gained a new last line" requires remembering what was already put to them. Nothing in current state can supply it: the accepted paragraph is an ordinary `ParagraphFragment` the tester may have since edited, and the proof-of-concept side has no stable identity — `ListItem` is `{runs}` with no id ([app/models.py](app/models.py#L77-L78)), the list textarea rewrites every item to a single plain run on any keystroke ([app/web/static/app.js](app/web/static/app.js#L2417-L2418)), and `remintFragments` assigns fresh `frag_id`s on every copy ([app/web/static/app.js](app/web/static/app.js#L1063)).

#### 2.2 The field

On `Vulnerability`, declared beside `content_offer_resolved` at [app/models.py](app/models.py#L196):

```python
# Which proof-of-concept last lines the In Conclusion offer has already put to the tester,
# accepted or dismissed, so a line they have answered stops coming back.
conclusion_offer_resolved: list[str] = Field(default_factory=list)
```

- **Type** `list[str]`. **Default** `[]` via `default_factory`.
- **Shape precedent:** `poc_variant_declined: list[Channel]`. **Name precedent:** `content_offer_resolved`.
- **No `Literal` widened, no validator changed.**

**`load_path` legacy repair: not needed.** `default_factory` fills the missing key, the same answer as for `content_offer_resolved`. All 21 findings on disk load unchanged. Add nothing to [app/workspace.py](app/workspace.py#L271-L298).

**`reconcileCanonicalObject`: merged generically, and must NOT join the exclusion list.** That list is `["saved_at", "app_id", "_folder_name_hint", "scope_text"]` ([app/web/static/app.js](app/web/static/app.js#L366)) — fields the server owns or never echoes. This one is client-written and server-echoed, so it belongs in the generic path. As an array of primitives, `stableItemKey` returns `null` for every element, `keyed` is false, and it falls to the `sameValue(liveValue, sentValue)` branch at [app/web/static/app.js](app/web/static/app.js#L398): untouched-since-PUT adopts the canonical value, touched-since-PUT keeps the live one. Correct in both directions.

**It must never be written as `null`.** Same rule the map already records for `content_offer_resolved`: a plain `list`, not `Optional`, so a missing key and `[]` both validate but an explicit JSON `null` fails and demotes the draft to the manager's legacy list. Every writer assigns a list; the JS uses `(finding.conclusion_offer_resolved ||= [])`, mirroring `(finding.content_offer_resolved ||= {})` at [app/web/static/app.js](app/web/static/app.js#L2991).

**No server-side pre-answer is needed** — and this is where it differs from `content_offer_resolved`. `insert_library` builds a `Vulnerability` with the default `status = "open_new"` ([app/main.py](app/main.py#L722)), and `content_types_for_status("open_new")` excludes `in_conclusion`, so an inserted finding has no conclusion section and the banner is unreachable until the tester changes the status. [app/main.py](app/main.py#L727) is untouched.

#### 2.3 What is remembered: the text itself

Not a hash, not an identity.

- **Identity is impossible** — see 2.1.
- **A hash is worse than useless here.** It would need a synchronous hash computed identically in Python and JavaScript; `crypto.subtle.digest` is async, so it would have to be hand-rolled — a brand-new twin pair bought for nothing, when the only consumer is the client.
- **Text is auditable in the draft and compares with `===`.** Stored exactly as `pocLastStep` returns it, `"".join(run.text for run in item.runs).strip()`, and compared with exact equality. No case folding, no extra whitespace normalisation: the textarea already trims every line, so the value is stable under a no-op edit.

Growth is bounded because **the list only ever grows on a click** — one entry per tester decision, accepted or dismissed. No cap needed.

#### 2.4 Predicate and buttons

```
const offered = pocLastStep(finding);
show = contentTypesForStatus(finding.status).includes("in_conclusion")
    && offered
    && !(finding.conclusion_offer_resolved || []).includes(offered);
```

**Round 2's `!contentHasWork(conclusion)` clause is deleted.** It cannot survive the requirement: the accepted paragraph is ordinary text, so `contentHasWork` is true forever after the first accept and the banner could never return. Its job — quieting the banner — passes to `conclusion_offer_resolved`, which is why Dismiss is now mandatory rather than optional.

**Accept.** Two branches, chosen by whether the section's **first** paragraph's exact joined text is a member of `conclusion_offer_resolved`:

| Condition | Button | Effect |
|---|---|---|
| First paragraph's text is a previously resolved offer | **Update the quoted step** | Replace that paragraph's runs |
| Otherwise | **Use it** | Insert `newFragment("paragraph")` at index 0 holding one plain `Run` |

Either branch then appends `offered` to `conclusion_offer_resolved` (deduped) and calls `render(); scheduleSave();`. The replace branch exists to stop a corrected step stacking a second near-identical opening line; it only ever overwrites a paragraph byte-identical to something this banner previously wrote, and an edited paragraph no longer matches and takes the insert branch instead. This mirrors the existing content-offer banner, whose primary label already switches on `written` at [app/web/static/app.js](app/web/static/app.js#L3005).

**Dismiss.** Appends `offered` to `conclusion_offer_resolved`, writes nothing, `render(); scheduleSave();`. This is the `poc_variant_declined` refuse-button precedent at [app/web/static/app.js](app/web/static/app.js#L2953). **Yes, the dismissed case needs recording** — without it the banner would sit forever on a finished finding, because `!contentHasWork` is gone.

#### 2.5 What counts as "a new last line"

| Tester action | `pocLastStep` | Behaviour | Justification |
|---|---|---|---|
| Appends a step | new text | **Re-offers** | Exactly the request. |
| Edits the existing last step | new text | **Re-offers** | The app cannot distinguish an edit from a replacement — the textarea rewrites every item on any keystroke. And re-offering is the right answer: under the snapshot decision the quoted line is now stale, and the replace branch is the one-click fix. Deliberate, not a side effect. |
| Deletes the last step, revealing an earlier one | the earlier line | **Re-offers only if that line has never been resolved** | This is what a list buys over a single remembered string. If the revealed line is the one already sitting in the conclusion, it is in the list and the banner stays quiet. |
| Installs a second library variant (merge) | last step of the merged list | **Re-offers** | `applyPocVariant` merge-appends ([app/web/static/app.js](app/web/static/app.js#L1080)), so the last line genuinely changed, and the finding gained steps the tester has not read. A `replace`-mode install that shortens the list back to a previously resolved line correctly stays quiet. |

#### 2.6 Rendering cadence — there is no flicker, and this is load-bearing

Typing in the list textarea calls `changed()`, which is `() => scheduleSave()` ([app/web/static/app.js](app/web/static/app.js#L2384)). `scheduleSave` queues `reportchange` on a 100 ms debounce, whose only listeners are `updateSetupSectionSummaries` ([app/web/static/app.js](app/web/static/app.js#L614)) and `updateReadinessPanel` ([app/web/static/app.js](app/web/static/app.js#L2758)); neither re-renders the editor pane. **The banner's quoted text is a snapshot taken at the last `render()`**, and `render()` runs on editor boot, finding switch, section expand/collapse, fragment add/delete, any banner click, and undo/redo. It never redraws character by character while the tester types a step.

The flip side, stated plainly: after typing a new last step, the banner does not appear until something else triggers a render — possibly not in that session. For a suggestion that is acceptable, and it is incidentally the "finished typing" boundary Round 1 went looking for and could not find, obtained without a new event.

Note `expandedContentTypes` defaults to *every* section expanded ([app/web/static/app.js](app/web/static/app.js#L2889)), so the banner is on screen when the tester opens a finding — it is not hidden behind a collapsed section.

#### 2.7 Not a review-panel row, and not a nag

The review panel's `offers` array is built from `pendingLibraryOffers` alone ([app/web/static/app.js](app/web/static/app.js#L2688)). **I would not add the conclusion offer to it**: the panel is a completion checklist, and this row's label would quote live proof-of-concept text. Reversible either way — a `level:"warning", suggestion:true` row is tolerated by the contract test, which compares the verdict and ignores warnings.

**Q4 interaction.** On a finished finding — real conclusion written, banner never touched — the banner still shows, because the offer was never resolved. It is a "Suggested" card, not a readiness row; it steals no focus; one Dismiss removes it permanently for that text; and `conclusion_offer_resolved` is read by no readiness rule on either side, so it can never block generation. This is the same standing behaviour the description and remediation library offers already have.

---

### 3. Revised data-risk rows

Only rows that change from Round 2, plus new ones.

| Failure mode | Round 2 | Now | Reasoning |
|---|---|---|---|
| **Derived-state fight** | RISK, resolved by step 4 | **clear after step 4** | Arm three is deleted on both sides, so no path writes the sentence into an existing paragraph that was emptied. The only writers left are the creation branch (zero paragraphs) and arm two (still matches). Both banners write only on a click. Nothing derived fights anything typed. |
| **Schema break / migration** | clear on schema, RISK on meaning | **RISK on schema, RISK on meaning** | A field is now added. No `Literal` widened, no validator changed, no `load_path` repair — `default_factory` fills the missing key for all 21 findings on disk. Two new obligations: never write JSON `null` (plain `list`, not `Optional`; `null` fails validation and demotes the draft); and a **downgrade** to a build without the field silently drops it, because no model in [app/models.py](app/models.py) sets `model_config`, so Pydantic v2's default `extra="ignore"` applies. Consequence of a downgrade: the offer reappears once. Benign, and identical to `content_offer_resolved`'s existing property. The meaning half is unchanged — 3 findings blocked on ship, the 4th immediately under step 8. |
| **Request/response asymmetry** | clear | **clear, but now load-bearing** | Round 2 added no field, so this was trivially clear. Not any more. `conclusion_offer_resolved` is client-written, sent in the `PUT` body, and echoed by the server because it rides `Vulnerability.model_dump()` like every other field. It must **not** join `reconcileCanonicalObject`'s exclusion list; excluding it would recreate the `scope_text` trap in reverse — the client would keep a value the server never confirmed. Prove the round trip directly; this is the row most likely to be wrong. |
| **Lost update** | clear | **clear, with one named ordering** | Still no server read-modify-write. New: two clients on the same finding can each append a different text; last writer wins the whole list, so one tester's dismissal can be lost and the banner returns once. Bounded, non-destructive, no tester prose involved. Not worth a merge strategy. |
| **Navigation trap** | clear | **clear, re-verified** | The restore banner re-arms the Q4 readiness issue, but readiness reaches only the Generate button and the review panel. `finding_is_complete` never reads `contents` ([app/report_service.py](app/report_service.py#L598)), so the Content page — the only place a conclusion can be written — stays open. No loop. |
| **Rule drift / twins** | RISK, four pairs | **RISK, three pairs** | Pair 2 shrinks rather than growing: the selection chain still moves in lockstep, but arm three is *deleted* from both sides, so the surface is smaller than Round 2 planned. Unchanged: sentence builder + recogniser; readiness; `requiresFragment` ↔ the server's empty-section set. **Neither change creates a new twin** — `pocLastStep`, both banners, and every writer of `conclusion_offer_resolved` are client-side; the server round-trips the field and reads it nowhere. Confirm in review that no Python code reads it. |
| **NEW — the restore banner hands the tester a generation blocker** | — | **RISK, declared, resolved by copy not code** | Accepting writes a paragraph the Q4 rule immediately flags. Not a trap — the pre-click state is already an error — but the button must say so. Both mechanism alternatives (a new `generated` marker; suppressing the banner) were rejected in 1.5. |
| **NEW — two suggestion banners in one section** | — | **RISK, low, resolved by ordering** | Both predicates can hold at once; no section renders more than one banner today. Fixed order — PoC-step first, restore-default second — mirrors the paragraph order they produce. Distinct primary verbs. Pin the order in a browser test. |
| **NEW — re-offer stacks duplicate opening paragraphs** | — | **RISK, bounded by the replace branch** | The replace branch covers accept → correct the step → accept. It does **not** cover accept → edit the quoted paragraph → correct the step → accept, which yields two paragraphs. Accepted: the app must not overwrite a paragraph the tester has edited, and it cannot tell that paragraph from prose. The extra fragment is one click to delete, since `requiresFragment` blocks only the section's last fragment. |
| **NEW — offer memory diverges from the conclusion's contents** | — | **clear, by design** | `conclusion_offer_resolved` records what was *offered*, never what the conclusion *contains*. Deleting the quoted paragraph does not re-offer that text. Correct: deleting a quote is an answer, not a question. |
| Stale write; orphan reference; silent stranding; backup exhaustion; contract-test blindness; review-panel issue shape; `applyLibraryEntry`; dialog stacking; existing tests asserting a ready report; client/server divergence on import; all four paste rows | — | **unchanged** | Neither change touches them. Both banners mint paragraphs through `newFragment("paragraph")` and call `scheduleSave()` exactly once, so the orphan, stale-write and backup rows hold verbatim. |

---

### 4. Revised step list

**Step 1 — List paste cleaning, as one undo step.** *(unchanged)*
*Files:* [app/web/static/app.js](app/web/static/app.js) — an `onpaste` beside the `oninput` at [app/web/static/app.js](app/web/static/app.js#L2417); [docs/DATA_MAP.md](docs/DATA_MAP.md) §12 client-only list.
*Test:* [tests/test_browser.py](tests/test_browser.py) — dispatch a real `paste` carrying `text/plain` into `.list-textarea`; assert `1. Alpha\n2) Beta\n- Gamma` persists as three clean items, `1.2.3.4 is the host` survives whole, and one Ctrl+Z after typing-then-pasting reverts only the paste.
*Invariant:* one item per line, trimmed, blanks dropped; a paste into a selection replaces only that selection; `fragment.items` is written by exactly one code path.

**Step 2 — Name the sentence and its recogniser, Python side.** *(unchanged)*
*Files:* [app/report_service.py](app/report_service.py).
*Test:* [tests/test_app.py](tests/test_app.py) — the pattern fullmatches the builder's own output for `Open` and `Resolved`, and for a title containing `"` and a regex metacharacter.
*Invariant:* no behaviour change; [tests/test_app.py](tests/test_app.py#L1599-L1624) passes untouched.

**Step 3 — Name the same two things in JavaScript and declare the twin.** *(unchanged)*
*Files:* [app/web/static/app.js](app/web/static/app.js#L113); [docs/DATA_MAP.md](docs/DATA_MAP.md) §12.
*Test:* [tests/test_browser.py](tests/test_browser.py#L1006-L1030) unchanged and passing.
*Invariant:* the rewrite condition is unchanged — marker, or no text, or still matches. Only the spelling moves.

**Step 4 — Delete arm three, both sides. CHANGED.** Option B is now the only shape; the Option A variant is dropped. Ships in the same release as step 5.
*Files:* [app/report_service.py](app/report_service.py#L239), [app/web/static/app.js](app/web/static/app.js#L909), [docs/DATA_MAP.md](docs/DATA_MAP.md) §12 (the chain is a twin pair) and §13 (the two-circumstance rule for where the app writes the sentence).
*Test:* [tests/test_app.py](tests/test_app.py) — emptying the sole conclusion paragraph leaves it empty across `provision`, and `generation_issues` reports `text is required`; a two-paragraph conclusion with the first emptied and the second prose leaves both alone; **an imported `in_conclusion` with `"fragments": []` still gains the sentence on first provision.** Plus a browser case asserting the client agrees on editor boot with no save.
*Invariant:* the creation branch at [app/report_service.py](app/report_service.py#L240-L242) and the `not _fragment_has_text(default)` clause of the guard both remain — together they are the only remaining way a paragraph is created and filled. Arm one and its purge are untouched. All four existing conclusion tests pass unmodified.

**Step 5 — The restore-default banner. NEW.** Must ship with step 4: step 4 alone removes the only way to get the sentence back.
*Files:* [app/web/static/app.js](app/web/static/app.js#L2912-L2917), [app/web/static/app.css](app/web/static/app.css), [docs/DATA_MAP.md](docs/DATA_MAP.md) §12 client-only list.
*Test:* [tests/test_browser.py](tests/test_browser.py) — on an `open_previously_discovered` finding, clearing the sentence shows `[data-conclusion-restore]`; **Put it back** writes the sentence into that same paragraph with the fragment count unchanged; the banner then disappears; a subsequent status change to `resolved` re-derives the restored sentence (proving arm two owns it again); the banner does **not** appear when the tester's own prose is present, nor on a carried section of an `open_new` finding, nor when the paragraph was deleted rather than emptied.
*Invariant:* the banner is not a `.fragment`, so [tests/test_browser.py](tests/test_browser.py#L1006-L1030)'s count of exactly one fragment holds. Nothing is written without a click. The guidance string `Include a brief justification or explanation.` is untouched — that test matches it with `exact=True`.

**Step 6 — Add `conclusion_offer_resolved` and prove the round trip. NEW.** No behaviour change; a prerequisite for step 7, in the style of steps 2 and 3.
*Files:* [app/models.py](app/models.py#L196), [docs/DATA_MAP.md](docs/DATA_MAP.md) §6.
*Test:* [tests/test_app.py](tests/test_app.py) — a draft without the key loads with `[]` and needs no `load_path` repair; a `PUT` carrying `["Observe the balance"]` returns it verbatim; an explicit `null` is rejected by validation. Plus a browser case proving `reconcileCanonicalObject` neither drops nor clobbers it across a save, in both the untouched-since-PUT and edited-since-PUT directions.
*Invariant:* no `Literal` widened, no validator added, no existing draft altered on disk. No Python code reads the field.

**Step 7 — `pocLastStep` and the proof-of-concept-step banner. CHANGED** (was Round 2's step 5): the `!contentHasWork` clause is replaced by the resolved-offer check, a **Dismiss** button is added, and accept gains the replace branch.
*Files:* [app/web/static/app.js](app/web/static/app.js), [app/web/static/app.css](app/web/static/app.css), [docs/DATA_MAP.md](docs/DATA_MAP.md) §12 client-only list.
*Test:* [tests/test_browser.py](tests/test_browser.py) — the banner quotes the last written step, skipping a trailing blank item; **Use it** inserts it as the first fragment with the sentence still second and appends the text to `conclusion_offer_resolved`; the banner disappears; both survive save and reload. Then: appending a new step re-offers it; **Dismiss** records it and the banner stays gone; editing the last step re-offers and **Update the quoted step** replaces the first paragraph rather than adding one; deleting the last step to reveal a previously resolved line does **not** re-offer. Plus the two-`numbered_list` case, the trailing-`note` case, the trailing-`code_block` case, and a case asserting both banners render in the fixed order.
*Invariant:* nothing is written without a click. Typing in the list textarea does not re-render the pane, so the banner text cannot churn mid-keystroke. `conclusion_offer_resolved` is only ever assigned a list.

**Step 8 — The readiness rules, both sides, plus the contract-test cases.** *(unchanged; was step 6)*
*Files:* [app/docx_report.py](app/docx_report.py#L42), [app/docx_report.py](app/docx_report.py#L115), [app/web/static/app.js](app/web/static/app.js#L111), `fragmentIssues`, [tests/test_docx.py](tests/test_docx.py) (two fixture lines), [docs/DATA_MAP.md](docs/DATA_MAP.md) §12 and §13.
*Test:* two new cases in `test_browser_readiness_verdict_matches_server_generation_issues` ([tests/test_browser.py](tests/test_browser.py#L1311)) — one non-`open_new` finding with the default left in place, one with the section emptied. Plus server tests: the issue appears for the default, clears when overwritten, appears for an empty printed section, and never appears for an `open_new` finding or a carried section. **Add one more:** accepting the restore banner produces exactly the default-sentence issue and no other, which is what proves 1.5's claim that the swap is one row for one row.
*Invariant:* an `open_new` finding and any carried unprinted section never gain an issue — [tests/test_app.py](tests/test_app.py#L1032) must pass untouched. The new issue carries `fragmentId` and `contentLabel` so the arrow and `is-incomplete` marking work. Both sides agree on every verdict, or CI fails.

**Step 9 — The replace-or-keep prompt, and the fifth title writer.** *(unchanged; was step 7)*
*Files:* [app/web/static/app.js](app/web/static/app.js#L1915-L1929), [app/web/static/app.js](app/web/static/app.js#L1892-L1898), [app/web/static/app.js](app/web/static/app.js#L2855-L2870), and `applyLibraryEntry` at [app/web/static/app.js](app/web/static/app.js#L1694), which gains `syncConclusion(finding)`. One shared helper, awaited at each site.
*Test:* as Round 2, plus one new case: the prompt does not fire immediately after the restore banner is accepted, because the restored paragraph is boilerplate, not prose.
*Invariant:* the prompt never fires while the conclusion is still boilerplate. One dialog at a time. The status is not applied, and the prompt not reached, if the status dialog is cancelled.

---

### 5. Anything I would push back on

**1. The proof-of-concept banner now outlives a finished conclusion, and that is forced by your answer.** Round 2's banner vanished the moment the tester wrote anything in the section. It cannot any more: "come back when the proof of concept changes" and "disappear as soon as I write my conclusion" are contradictory, because writing the conclusion is permanent and the change comes later. So the quieting mechanism moves from "you wrote something" to "you clicked Dismiss". Net effect: a tester who writes their conclusion by hand and never wants a quoted step must click Dismiss once per finding. That is one extra click per finding, on every finding, forever. It is the price of re-offering and I think it is worth paying, but it is a real cost and you should know you are buying it.

**2. Re-offering on an *edited* last step is broader than "another new line," and I am building it deliberately.** The app cannot distinguish an edit from an append — the textarea rewrites every item on any keystroke. I have justified it as a staleness fix, and I believe that justification, but the practical consequence is that the banner returns when the tester merely rewords the last step, which happens far more often than adding a step. This is the part most likely to feel wrong in use. The only narrowing available is "re-offer only when the step count rises", which costs a second remembered value and misses delete-then-add. Say the word if you would rather have that.

**3. The restore-default banner cannot resolve anything, and that is inherent to the pair of requests.** "Require them to replace the default" and "let them put the default back" point in opposite directions; the banner's accept action necessarily produces a state the readiness rule flags. I am building it with copy that says so. But it is worth asking what the underlying need is: if the real case is "I emptied that paragraph by accident", **Ctrl+Z already restores it** — the undo system covers a cleared paragraph like any other edit. The banner then is a second, slower, more confusing undo. If the real case is "I want the sentence as a template to edit", the banner earns its place. I cannot tell which from the answer, and the design changes depending on it.

**4. `conclusion_offer_resolved` is the first field in this schema that stores a copy of content for bookkeeping rather than for printing.** It duplicates a line that already exists in the proof of concept. It is small, auditable, and grows only on a click, so I am comfortable with it — but if storing tester-visible text for state-tracking is objectionable on principle, the only alternative is a hand-rolled hash implemented identically in Python and JavaScript, which is a new twin pair for zero functional gain. I would take the duplicated text every time.

Next action: consider the output above, then tell me whether push-back item 3 is the accidental-empty case or the template case — it decides whether the restore-default banner ships at all.

## Agreed plan

The change is three independent pieces of work, shipped in four units. Steps are ordered; each names its files, its test, and the invariant it must not break.

### What is being built

1. **List paste cleaning.** Pasting `1. Alpha` / `2) Beta` / `- Gamma` into a numbered or bulleted list fragment strips the markers, because the visible numbering is drawn in a separate gutter and a pasted marker would double it.
2. **The In Conclusion section stops being self-repairing.** The app writes its status sentence in only two circumstances — into a section with no paragraphs at all, and into a paragraph that still matches the sentence. It never rewrites a paragraph the tester emptied. A banner offers the sentence back on a click.
3. **The last proof-of-concept step is offered as the conclusion's opening line**, in its own paragraph above the sentence, on a click, and re-offered whenever that step's text changes.
4. **The default sentence stops counting as a finished conclusion.** It blocks document generation until replaced, as does an empty conclusion section. A name or status change on a finding whose conclusion is tester prose asks whether to replace it.

### Decisions that shape it

- The proof-of-concept line goes in **its own paragraph**, never concatenated into the sentence's paragraph. The sentence is recognised by `re.fullmatch` over one paragraph's joined text, with a `^…$` twin in JavaScript; concatenating destroys the recogniser for every draft on disk and freezes each one at its stored title and status.
- **Arm three of the conclusion selection chain is deleted** on both sides — the rule that claims the first text-less paragraph. Keeping it while the section holds two paragraphs lets the app write boilerplate above a conclusion the tester just wrote, and the client copy runs on editor boot, so it reappears on a page load with no save involved.
- The copied line is a **snapshot**, not derived. It can go stale; the banner's **Update the quoted step** button is the fix.
- Enforcement is a **readiness issue**, not a navigation gate. The only page where a conclusion can be written is the page a gate would close.
- The sentence becomes a **named builder plus a named pattern on each side**. It currently has four spellings linked only by a regex.
- List paste cleaning stays **client-only with no Python owner**. It is a rule about the clipboard, not about the document; a server-side stripper would run on every save and permanently delete a `1.` a tester typed on purpose.

### Ordered steps

**Step 1 — List paste cleaning, as one undo step.**
*Files:* [app/web/static/app.js](../../app/web/static/app.js) — an `onpaste` beside the list textarea's existing `oninput`; [docs/DATA_MAP.md](../DATA_MAP.md) §12 client-only list.
*Rule:* strip `^\s*(\d{1,3}[.)]|\(\d{1,3}\)|[-*+•–—])\s+` per line, once. The trailing whitespace requirement is load-bearing — it keeps `1.2.3.4 is the target` intact. Roman and lettered markers are not stripped; they are ambiguous with prose, and a wrong strip silently deletes text. Bracket the mutation with `finalizeTextTransaction()` so the paste is exactly one undo step.
*Test:* dispatch a real `paste` carrying `text/plain` into `.list-textarea`; assert `1. Alpha\n2) Beta\n- Gamma` lands as three clean items, `1.2.3.4 is the host` survives whole, and one Ctrl+Z after typing-then-pasting reverts only the paste.
*Invariant:* one item per line, trimmed, blanks dropped; a paste into a selection replaces only that selection; `fragment.items` is written by exactly one code path — the existing `oninput`.

**Step 2 — Name the sentence and its recogniser, Python side.**
*Files:* [app/report_service.py](../../app/report_service.py).
*Test:* the pattern fullmatches the builder's own output for `Open` and `Resolved`, and for a title containing `"` and a regex metacharacter.
*Invariant:* no behaviour change. The existing conclusion tests pass untouched, including their byte-exact run assertions.

**Step 3 — Name the same two things in JavaScript and declare the twin.**
*Files:* [app/web/static/app.js](../../app/web/static/app.js) beside the existing `RESOLVED_REMEDIATION` twin comment; [docs/DATA_MAP.md](../DATA_MAP.md) §12.
*Test:* the existing browser test pinning the rendered sentence to an exact string passes unchanged.
*Invariant:* `syncConclusion`'s rewrite condition is unchanged — marker, or no text, or still matches. Only the spelling moves.

**Step 4 — Delete arm three, both sides.** Ships with step 5.
*Files:* [app/report_service.py](../../app/report_service.py), [app/web/static/app.js](../../app/web/static/app.js), [docs/DATA_MAP.md](../DATA_MAP.md) §12 and §13.
*Test:* emptying the sole conclusion paragraph leaves it empty across `provision`, and readiness reports `text is required`; a two-paragraph conclusion with the first emptied and the second prose leaves both alone; an imported conclusion with `"fragments": []` still gains the sentence on first provision; the client agrees on editor boot with no save.
*Invariant:* the creation branch and the `not _fragment_has_text(default)` clause of the rewrite guard both remain — together they are the only remaining way a paragraph is created and filled. Arm one and its purge are untouched. All four existing conclusion tests pass unmodified.

**Step 5 — The restore-default banner.** Must ship with step 4, which otherwise removes the only way to get the sentence back.
*Files:* [app/web/static/app.js](../../app/web/static/app.js), [app/web/static/app.css](../../app/web/static/app.css), [docs/DATA_MAP.md](../DATA_MAP.md) §12 client-only list.
*Shows when:* the section is printed for this status, **and** it holds a text-less paragraph, **and** no paragraph matching the default sentence is present. Accepting writes the sentence into the last text-less paragraph **in place** — no insert, no move, no change to the fragment count.
*Copy matters:* accepting swaps one readiness error for another (`text is required` becomes `still holds the default sentence`), so the button must say so — *"Put it back as a starting point; you will still need to replace it before generating."* It is not a trap: the pre-click state is already blocked.
*Test:* clearing the sentence shows the banner; **Put it back** writes into the same paragraph with the fragment count unchanged; the banner disappears; a later status change re-derives the restored sentence, proving arm two owns it again; the banner does not appear for tester prose, nor on a carried section of an `open_new` finding, nor when the paragraph was deleted rather than emptied.
*Invariant:* the banner is not a `.fragment`, so the existing "exactly one fragment" assertion holds. Nothing is written without a click.

**Step 6 — Add `conclusion_offer_resolved` and prove the round trip.** No behaviour change; prerequisite for step 7.
*Files:* [app/models.py](../../app/models.py), [docs/DATA_MAP.md](../DATA_MAP.md) §6.
*Shape:* `conclusion_offer_resolved: list[str] = Field(default_factory=list)` on `Vulnerability`, beside `content_offer_resolved`. Stores the offered step text verbatim — identity is impossible (list items have no id and the textarea rewrites every item on any keystroke), and a hash would need a new synchronous Python/JavaScript twin for no benefit.
*Test:* a draft without the key loads with `[]` and needs no `load_path` repair; a `PUT` carrying a value returns it verbatim; an explicit `null` is rejected; `reconcileCanonicalObject` neither drops nor clobbers it across a save, in both the untouched-since-PUT and edited-since-PUT directions.
*Invariant:* no `Literal` widened, no validator added, no existing draft altered. It must **not** join `reconcileCanonicalObject`'s exclusion list — it is client-written and server-echoed, so it belongs in the generic merge path. Never written as `null`. No Python code reads it.

**Step 7 — `pocLastStep` and the proof-of-concept-step banner.**
*Files:* [app/web/static/app.js](../../app/web/static/app.js), [app/web/static/app.css](../../app/web/static/app.css), [docs/DATA_MAP.md](../DATA_MAP.md) §12 client-only list.
*`pocLastStep`:* scan `proof_of_concept` fragments in reverse; take the first that is a `numbered_list`, `bulleted_list` or `note`; from it take the last item or line with text. Skip `image`, `table`, `code_block`, `instance_title`. `previous_proof_of_concept` is excluded — a conclusion about this retest must not quote last year's steps. **Declared gap:** a proof of concept ending with a code block is offered the line above it; the banner quotes the text, so the offer is never blind.
*Shows when:* the section is printed for this status, **and** `pocLastStep` is non-empty, **and** that text is not already in `conclusion_offer_resolved`. Three buttons: **Use it** (insert at index 0), **Update the quoted step** (replace the first paragraph, when its text is a previously resolved offer), **Dismiss**. All three record the text.
*Order:* when both banners show, proof-of-concept first, restore-default second — mirroring the paragraph order they produce.
*Test:* the banner quotes the last written step, skipping a trailing blank item; **Use it** inserts it first with the sentence still second and records the text; appending a new step re-offers; **Dismiss** records it and the banner stays gone; rewording the last step re-offers and **Update the quoted step** replaces rather than adds; deleting the last step to reveal a previously resolved line does not re-offer. Plus the two-`numbered_list`, trailing-`note` and trailing-`code_block` cases, and a case pinning the two-banner order.
*Invariant:* nothing is written without a click. Typing in the list textarea does not re-render the editor pane, so the quoted text cannot churn mid-keystroke. `conclusion_offer_resolved` is only ever assigned a list.

**Step 8 — The readiness rules, both sides, plus the contract-test cases.**
*Files:* [app/docx_report.py](../../app/docx_report.py), [app/web/static/app.js](../../app/web/static/app.js) (`fragmentIssues`, and `in_conclusion` added to `requiresFragment`), [tests/test_docx.py](../../tests/test_docx.py) (two fixture lines), [docs/DATA_MAP.md](../DATA_MAP.md) §12 and §13.
*Two rules:* the default sentence is still present; and `in_conclusion` joins the empty-section check. The second closes a pre-existing hole where an empty conclusion generates silently and prints `N/A`, and stops "write a conclusion" being dischargeable by deleting the paragraph.
*Test:* two new cases in `test_browser_readiness_verdict_matches_server_generation_issues` — one non-`open_new` finding with the default left in place, one with the section emptied. These are the first non-`open_new` cases that test has ever run; without them the rule is invisible to it in both directions. Plus server tests: the issue appears for the default, clears when overwritten, appears for an empty printed section, never appears for an `open_new` finding or a carried section, and accepting the restore banner produces exactly one issue and no other.
*Invariant:* an `open_new` finding and any carried unprinted section never gain an issue from either rule. The new issue carries `fragmentId` and `contentLabel` so the review panel's arrow and the `is-incomplete` marking both work. Both sides agree on every verdict, or CI fails.

**Step 9 — The replace-or-keep prompt, and the fifth title writer.**
*Files:* [app/web/static/app.js](../../app/web/static/app.js) — the status `onchange`, the Findings-page title commit, `finishTitle`, the editor's library pick, and **`applyLibraryEntry`**, which gains `syncConclusion(finding)`. One shared helper, awaited at each site.
*Why `applyLibraryEntry`:* it is the only one of the five client-side title writes that does not re-derive the conclusion. Today that is masked because the sentence still matches the regex and the server fixes it on the next save — but under this change the tester is prompted at that exact moment, so the prompt and the on-screen sentence would disagree about the title until the save lands.
*Test:* a finding whose conclusion is prose, changed from `open_previously_discovered` to `resolved` — the status dialog resolves first, then the conclusion prompt appears quoting the prose; **Keep** leaves the text byte-identical, **Replace** writes the freshly derived sentence, either way one undo step. No prompt while the conclusion still holds the default, including immediately after the restore banner is accepted. Picking a library entry from the Findings-page row renders the sentence with the new title immediately, before any save.
*Invariant:* the prompt never fires while the conclusion is boilerplate. One dialog at a time — the status dialog must resolve first, and the prompt is not reached if it is cancelled. Converting the title handlers to `async` must not change their branching on `replaceFromLibrary`'s return; the call sites are converted to `await` rather than left testing a Promise for truthiness.

### Costs accepted, to be stated in the release note

- **Three findings on disk become generation-blocked the moment step 8 ships**, and a fourth — whose conclusion section is empty — joins them immediately. No migration can fix these; the missing thing is prose only a tester can write.
- **Every finding in a DOCX-imported retest** is affected, because the import marks every retained finding as previously-discovered. For a 14-finding import that is 14 rows in the review panel on first open.
- **The proof-of-concept banner no longer disappears when the tester writes their conclusion.** It goes when they click **Use it** or **Dismiss**. A tester who always writes conclusions by hand clicks Dismiss once per finding. This is the price of re-offering on a changed step.
- **Two suggestion banners can render in one section.** No section renders more than one today. Fixed order and distinct primary verbs are the mitigation.
- **Re-offering fires on a reworded step, not only an added one.** The app cannot tell them apart. Chosen deliberately; narrowing to "only when the step count rises" is a small later change.

