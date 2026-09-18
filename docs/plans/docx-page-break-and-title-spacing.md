# DOCX page break, title placement, and table spacing

> **Status:** shipped · 2026-09-16 · `e7b843a`

## Request

> for report generation.
> these may be done on the post processing. not sure yet
> - If a page break is next to the environment title, then move the environment title after the page break.
> - Same with if the environment title or in content title is before a page break, then remove the new line between the page break and the title.
> - basically There should be no environment title above the page break, and no empty line above content titles if there is a page break above that empty line
>
> this should be done on the generation I think
> - There should be a new line below table fragments

## Round 1 - Oracle: how it works today

> Oracle's headline: *"Three of the user's four assumptions are wrong about where the code is, and one is wrong about what the code does."*

### 1. Page break origins

Every explicit page break comes from one function, called from two places:

| # | Mechanism | Where set | Scope |
|---|---|---|---|
| 1 | `w:pageBreakBefore` on the first `w:p` of a finding component | [app/docx_report.py](../../app/docx_report.py#L530-L536) | **Per-finding** — `if index:` skips the first finding of each severity |
| 2 | `w:pageBreakBefore` on the first `w:p` of the assembled severity block | [app/docx_report.py](../../app/docx_report.py#L543-L548) | **Per-severity** |

Both go through [`_set_page_break_before`](../../app/docx_report.py#L994-L1001).

A **duplicate** `_set_page_break_before` exists at [app/docx_components.py](../../app/docx_components.py#L567-L573), called from `compose_docx_components`. **It is not on the production path** — the only shipped DOCX comes from `render_report_docx` ([app/main.py](../../app/main.py#L513)); `compose_docx_components` is referenced only by [scripts/compose_component_test.py](../../scripts/compose_component_test.py#L32) and [tests/test_docx_components.py](../../tests/test_docx_components.py#L30). It is a demo/test composer, not a page-break source in real reports.

**No `w:br w:type="page"` is ever written.** The only `w:br` writer is [app/docx_components.py](../../app/docx_components.py#L526), a soft line break from the long-value wrapper. `w:sectPr` is filtered out of every cloned component ([app/docx_components.py](../../app/docx_components.py#L52-L58)).

Oracle could not open the binary templates and flagged this as **the one open question**, noting it decides whether this is reordering work or `keepNext` work. **Settled by the coordinator below.**

### 2. Environment label emission

Function is at [app/docx_report.py](../../app/docx_report.py#L662-L678) (not L711 as assumed).

- **Text:** [`_environment_label`](../../app/docx_report.py#L658-L659) — `"PROD:"` or `f"{non_production_label.upper()}:"`.
- **Component:** `resources/fragments/title_fragment.docx` via the `"instance_title"` mapping at [app/docx_report.py](../../app/docx_report.py#L80). Forced `space_after = Pt(0)` on every returned `w:p`.
- **Insertion:** [app/docx_report.py](../../app/docx_report.py#L706-L716), immediately before the first `ImageFragment` whose `environment` differs from `labelled_environment`. Gated on `label_images`, true only for the two PoC anchors ([app/docx_report.py](../../app/docx_report.py#L652)).

**Can it be the last element before a page break? Not a generator-inserted one.** The label is always immediately followed by the image that triggered it, and explicit breaks only land on a finding's first paragraph or a severity heading. What *can* strand it is **Word's automatic page flow**, and **no code in this repo sets `w:keepNext`**.

### 3. Content / section titles — decisive

`Description:`, `Recommended Remediation:`, `Previous Proof of Concept:`, `Proof of Concept:`, `In Conclusion:`, `Severity Review Ticket (if applicable):` are **literal static paragraphs inside** `resources/finding_types/*.docx`, interleaved with the `{{...}}` anchors.

`_render_finding_component` ([app/docx_report.py](../../app/docx_report.py#L603-L657)) only substitutes tokens and swaps anchors. `_component_anchor_index` ([app/docx_report.py](../../app/docx_report.py#L980-L992)) matches an element **only** if it is a `w:p` whose entire text `fullmatch`es a `{{token}}`.

> **Blunt consequence:** "move the title after the page break" is not expressible in the current generator for section titles. The generator can move things it created; it created none of these.

**Existing test:** [tests/test_docx.py](../../tests/test_docx.py#L230-L247) walks backwards from each section title and asserts `assertLessEqual(blank_count, 1)`. Note `Description:` is **not** in that set, and the assertion is `<= 1`, **not `== 0`** — so it already permits exactly the blank line the user wants removed.

### 4. Trailing / blank paragraph handling — corrects the framing

[`_trim_trailing_empty_paragraphs`](../../app/docx_report.py#L799-L804) pops from the **end** while [`_is_empty_component_paragraph`](../../app/docx_report.py#L806-L814) holds (a `w:p` with no text, no `w:drawing`, no `w:pict`, no `w:br`). Two call sites: end of `_render_component_content` ([L726](../../app/docx_report.py#L726)), and inside `_render_image_component` ([L866](../../app/docx_report.py#L866)) so the caption stays the image's immediate sibling.

**The table answer:** [`_render_table_component`](../../app/docx_report.py#L873-L922) picks the `w:tbl` out of the cloned component ([L883-L886](../../app/docx_report.py#L883-L886)) and appends **only that element** ([L920](../../app/docx_report.py#L920)). Every paragraph in `table_fragment.docx` is discarded.

> **"New line below table fragments" is an addition, not the removal of an over-eager trim. Nothing was ever there.**

**Related defect:** two consecutive `table` fragments produce adjacent `w:tbl` siblings with nothing between them. **Word merges adjacent tables into one.**

### 5. Post-processing stage — answers "maybe post processing?"

`app/docx_captions.py` is **two unrelated stages**:

- **Stage A — pure python-docx/lxml, cross-platform.** [`add_native_image_captions`](../../app/docx_captions.py#L98-L141) converts caption paragraphs into `SEQ Figure` fields. It already runs **inside** the generator at [app/docx_report.py](../../app/docx_report.py#L174), before save.
- **Stage B — Word COM automation, Windows only.** [`update_docx_fields_with_word`](../../app/docx_captions.py#L38-L87) drives `DispatchEx("Word.Application")`. Called unconditionally by [app/main.py](../../app/main.py#L519); failure becomes HTTP 422.

> **Plain answer:** Stage B is unusable for layout surgery — Windows/Word-only, never executes on macOS. Stage A is viable and cross-platform, but it is **not a separate phase** — it already runs in-process inside `render_report_docx` on the same `Document`. **For anything cross-platform, "post-processing" and "generation" are the same stage.** The distinction the user is drawing does not exist in this codebase.

### 6. Rules that exist in both Python and JavaScript

**None of this layout logic has a JavaScript twin. DOCX layout is purely server-side.** `app/web/static/app.js` has no DOCX preview. The only shared value is the `non_production_label` `<select>` ([app.js#L1474](../../app/web/static/app.js#L1474)).

**The real twins are Python-to-Python, and they are the actual risk:**

1. **`app/docx_import.py` reads back everything this change would move.** `_build_fragments` recognises the environment label **by exact text** and requires it *before* its run of images — `labelled_environment` set at [app/docx_import.py](../../app/docx_import.py#L252-L260), consumed at [L269](../../app/docx_import.py#L269). Moving the label across a break keeps it before its images **only if the move is a property change, not a reorder.**
2. **Section titles matched by exact literal text on import** — `SECTION_HEADINGS` at [app/docx_import.py](../../app/docx_import.py#L40-L47). `Previous Proof of Concept:` is deliberately listed before `Proof of Concept:` (substring).
3. **Two `_set_page_break_before` implementations** will drift.

### 7. Existing test coverage

- [tests/test_docx_components.py](../../tests/test_docx_components.py#L29-L52) — asserts `pageBreakBefore is not None` on severity headings. Exercises the **non-production** composer only.
- [tests/test_docx.py](../../tests/test_docx.py#L230-L247) — the `blank_count <= 1` section-title guard.
- [tests/test_docx.py](../../tests/test_docx.py#L248-L251) — pins that the element after the description paragraph **is an empty `w:p`**; mid-section blanks are deliberately preserved.
- [tests/test_docx.py](../../tests/test_docx.py#L255-L259) — `image_caption._p.getprevious()` must contain the drawing. **`add_native_image_captions` itself depends on `paragraph.getnext()` being the caption** ([app/docx_captions.py](../../app/docx_captions.py#L119-L126)). Inserting anything between an image and its caption silently stops caption-field conversion.
- [tests/test_docx_import.py](../../tests/test_docx_import.py#L179-L185) — **tightest constraint**, an exact ordered fragment-type list. **Good news:** `_build_fragments` drops textless paragraphs at [L276](../../app/docx_import.py#L276), so a genuinely empty spacer after a table round-trips harmlessly — provided it contains no run text.

### 8. Risk to drafts on disk

**Zero persistence impact. Purely render-time.** `TableFragment` ([app/models.py](../../app/models.py#L87-L93)) has no spacing/layout/page-break field. `render_report_docx` takes a `Report` and returns `bytes`, never mutating it. `finalized_report` only reads under lock; the only write is `atomic_write_bytes` of the `.docx`. No `saved_at` bump.

### Invariants in play

| Invariant | Enforced at | What breaks if violated |
|---|---|---|
| A caption is the image paragraph's immediate sibling | [docx_captions.py#L119-L126](../../app/docx_captions.py#L119-L126), [test_docx.py#L257](../../tests/test_docx.py#L257) | `SEQ Figure` fields stop generating; figure numbering stops advancing |
| At most one blank paragraph precedes a section title | [test_docx.py#L247](../../tests/test_docx.py#L247) | Titles drift down the page as blanks stack |
| The environment label precedes its run of images | [docx_report.py#L706-L725](../../app/docx_report.py#L706-L725), [docx_import.py#L252-L269](../../app/docx_import.py#L252-L269) | Re-imported images lose `environment`, which drives evidence-completeness validation |
| Section titles are exact literal text | [docx_import.py#L40-L47](../../app/docx_import.py#L40-L47) | Import raises `ReportImportError` |
| No two `w:tbl` siblings without an intervening paragraph | **not enforced anywhere** | Word merges consecutive table fragments into one |

### Map drift

**None in `docs/DATA_MAP.md`** — nothing here touches the files that map governs.

**One imprecision in `docs/DOCX_TEMPLATE.md`** ([L124-L127](../../docs/DOCX_TEMPLATE.md#L124-L127)): it says each fragment is emitted "using its corresponding document under `resources/fragments/`". For `table` this is misleading — only the `w:tbl` is used, every paragraph is discarded. That sentence is what would lead a reader to the wrong conclusion about where the missing newline went.

---

### Coordinator addendum — settling the Oracle's open question

The oracle could not open the binary templates and said §1 could not be closed without it. I unzipped them. **Answer: there is no baked-in page break anywhere near a title or label.**

```
resources/MAIN_TEST.docx                 -> document.xml: pageBreakBefore=2, br@page=0, keepNext=14
resources/finding_types/new_finding.docx -> document.xml: NONE (styles.xml only)
resources/finding_types/retest_finding.docx -> document.xml: NONE (styles.xml only)
resources/fragments/table_fragment.docx  -> document.xml: NONE
resources/fragments/title_fragment.docx  -> document.xml: NONE
```

MAIN_TEST's 2 `pageBreakBefore` are on its **own static sections** — `" Findings Summary"` and `"Appendix: Common Vulnerability Scoring System"` — not on findings. Its 14 `keepNext` are **all on `Caption`-style paragraphs** (keeping a table caption with its table). The only styles defining `keepNext` are `Heading1`–`Heading9`.

Every paragraph in both finding-type templates, dumped with style and properties:

```
new_finding.docx
  0 style='Report Heading 2'  keepNext=False pbb=False  '{{finding_title}}'
  1 style='Normal'            keepNext=False pbb=False  ''
  2 style='Normal'            keepNext=False pbb=False  ''
  3 style='Normal'            keepNext=False pbb=False  'Description:'
  4 style='Normal'            keepNext=False pbb=False  '{{description-fragments-here}}'
  5 style='Normal'            keepNext=False pbb=False  ''          <- the "empty line above content title"
  6 style='Normal'            keepNext=False pbb=False  'Recommended Remediation:'
  7 style='Normal'            keepNext=False pbb=False  '{{recommended-remediation-fragments-here}}'
  8 style='Normal'            keepNext=False pbb=False  ''          <- same
  9 style='Normal'            keepNext=False pbb=False  'Proof of Concept: '
 10 style='Normal'            keepNext=False pbb=False  'The following demonstrates the vulnerability:'
 11 style='Normal'            keepNext=False pbb=False  '{{poc-fragments-here}}'
```

`retest_finding.docx` follows the same shape with the same blank-then-title pattern at indices 12/13, 16/17, 19/20.

**Three facts this establishes, which the planner must treat as settled:**

1. **Section titles use `Normal`, carry no `keepNext`, and carry no `pageBreakBefore`.** The finding title uses `Report Heading 2`, which is *not* `Heading2` and is **not** in the `keepNext` style list. So nothing in a finding is protected from being orphaned by Word's automatic pagination.
2. **The "empty line above content titles" is a literal blank paragraph authored into the template** (indices 5, 8, …), not something the generator emits. It is not a stray — it is the section spacing.
3. **Therefore every page break the user is seeing next to an environment label or a section title is Word's automatic pagination, not an element the code positioned.** No element reordering can fix it, because there is no element to reorder.

**Empirical confirmation of the table gap.** Rendering the real demo report `r_c6ff01abda9e` (VDB-035, which is `paragraph, table, paragraph, table, paragraph, table, paragraph, note`) gives the actual body element order:

```
268 <p>   'Recommended Remediation:'
269 <p>   'Without public authentication:'
270 <p>   ''                                  <- trailing blank of paragraph_fragment.docx
271 <tbl> 'Header Name | Recommended Header Value | ...'
272 <p>   'With public authentication (restricted with authentication):'   <- NO blank after the table
273 <p>   ''
274 <tbl> ...
275 <p>   'Restricted Without Authentication:'
276 <p>   ''
277 <tbl> ...
278 <p>   'More information can be found at:https://portswigger.net/web...'
```

Confirms the oracle: a table is immediately followed by the next fragment's text, with no separating paragraph. These three tables avoid Word's adjacent-table merge **only because a paragraph fragment happens to sit between each pair** — two consecutive `table` fragments would merge.

## Round 1 - Planner: proposal and open questions

### Re-framing: what each bullet actually needs

| Bullet | Verdict | The real fix |
|---|---|---|
| "If a page break is next to the environment title, move the environment title after the page break" | **Wrong mechanism.** The generator emits exactly two kinds of page break, both via [_set_page_break_before](../../app/docx_report.py#L994-L1001): one on a finding's first paragraph, one on a severity heading. Neither is ever adjacent to an environment label. The break being seen is Word's automatic pagination, decided at layout time. There is no element in the file to move. | `w:keepNext` on the label paragraph. Word then pushes the label down to join its image instead of stranding it. This is a **property** change, not a reorder — which matters, because [docx_import.py](../../app/docx_import.py#L252-L260) finds the label by text *and position*. |
| "Same with in-content titles" | **Wrong mechanism, same reason.** Also: section titles are static paragraphs authored into the finding-type templates. The generator did not create them and holds no reference to them. | `w:keepNext` on the title and on every paragraph between it and its first real content. Applied **structurally**, working backwards from each `{{...-fragments-here}}` anchor, so it needs no literal heading strings. |
| "Remove the new line between the page break and the title" | **Achievable, but not conditionally.** The blank is a real authored paragraph (indices 5 and 8 in `new_finding.docx`). "Remove it *only when* a page break lands above it" is **not computable** — python-docx has no pagination model, and the only component that does ([update_docx_fields_with_word](../../app/docx_captions.py#L38-L87)) is Windows-only and never runs on this Mac. The choice is: remove always, or never. | Largely moot once `keepNext` is in: the title and its content move down together and the blank stays behind at the bottom of the previous page, where it is invisible. Removing it unconditionally **reverses a decision a test deliberately pins** — see open question 1. |
| "There should be a new line below table fragments" | **Correct as written.** | Append one empty paragraph after the table. Also closes the latent adjacent-table merge defect. |

> Plainly: bullets 1–3 are **one** change — `keepNext` — not three. Bullet 4 is a separate, small, real change.

On "maybe post-processing": that stage does not exist as pictured. `add_native_image_captions` already runs *inside* `render_report_docx`. **Doing it at generation is the only option.**

### Blast radius

| File | Function | Change | Kind |
|---|---|---|---|
| [app/docx_report.py](../../app/docx_report.py#L994-L1001) | new `_keep_with_next` | Helper mirroring `_set_page_break_before` | Python |
| [app/docx_report.py](../../app/docx_report.py#L603-L657) | `_render_finding_component` | Walk back from each `-fragments-here` anchor, mark preceding non-empty paragraphs `keepNext`, stop at first blank | Python |
| [app/docx_report.py](../../app/docx_report.py#L662-L678) | `_render_environment_label` | Extend the existing `space_after = Pt(0)` loop to also set `keepNext` | Python |
| [app/docx_report.py](../../app/docx_report.py#L747-L753) | `InstanceTitleFragment` branch | `keepNext` on the rendered title block | Python |
| [app/docx_report.py](../../app/docx_report.py#L873-L922) | `_render_table_component` | `keepNext` on the pre-table caption; append one empty `w:p` after the table | Python |
| [app/docx_report.py](../../app/docx_report.py#L738-L747) | `CodeFragment` branch | `keepNext` on the pre-code caption | Python |
| [app/docx_report.py](../../app/docx_report.py#L820-L871) | `_render_image_component` | `keepNext` on the image paragraph so its caption cannot separate | Python |
| [tests/test_docx.py](../../tests/test_docx.py#L230-L259) | — | New assertions; existing guards re-run unchanged | Python |
| [tests/test_docx_import.py](../../tests/test_docx_import.py#L179-L185) | — | **Unchanged** — it is the proof the spacer is invisible to import | Python |
| [docs/DOCX_TEMPLATE.md](../../docs/DOCX_TEMPLATE.md#L124-L127) | — | Correct the table sentence; document the `keepNext` rule | Docs |
| [app/docx_import.py](../../app/docx_import.py) | — | **No change.** Listed because it is the consumer that constrains everything above | — |
| `resources/**/*.docx` | — | **No change under the recommended plan.** Only if open question 1 option B | Binary |
| [docs/DATA_MAP.md](../../docs/DATA_MAP.md) | — | **No change.** Nothing here touches the files that map governs | — |

### Data-risk table

| Risk | Verdict | Reasoning |
|---|---|---|
| Round trip: environment label position | `clear` | `keepNext` is a `w:pPr` child. No element added, removed, or reordered, so the label remains the immediate predecessor of its image run and `labelled_environment` still sets before it is consumed. |
| Round trip: `classify_paragraph` misreading `keepNext` | `clear` | [classify_paragraph](../../app/docx_import.py#L110-L133) reads `w:numPr`, `w:shd/@w:fill`, `w:jc`, `w:pStyle`, `w:pPr/w:rPr/w:b\|w:i`. `w:keepNext` is a direct child of `w:pPr`, not of `w:rPr`, and is on none of those paths. |
| Round trip: section title text | `clear` | Titles marked by **position relative to the `{{...}}` anchor**, not by string. Zero literal headings enter `docx_report.py`, so `SECTION_HEADINGS` stays the single owner of those strings. |
| Round trip: fragment-type ordering vs. the table spacer | `clear` | The spacer carries no runs, so [_build_fragments](../../app/docx_import.py#L276) drops it at `if not text.strip(): continue`. [tests/test_docx_import.py#L179-L185](../../tests/test_docx_import.py#L179-L185) re-runs unchanged as the proof. |
| **Spacer sourced from the wrong template** | **`RISK`** | The list branch of `_build_fragments` has **no empty-text guard** — a spacer carrying `w:numPr` would be read as an empty list item and insert a phantom `bulleted_list` after every table. A spacer carrying the `FiguresandTables` style would be read as a caption. **Mitigation:** source it from `paragraph_fragment.docx`, and assert the spacer has no `w:numPr` and no `w:pStyle`. |
| Image → caption adjacency | `clear` | `add_native_image_captions` requires `paragraph.getnext()` to be the caption. `keepNext` adds no sibling. The table spacer is appended by `_render_table_component`, whose output list is `[caption?, tbl, spacer]` — it can never land between an image paragraph and its caption. |
| `blank_count <= 1` guard | `clear` | The spacer is added **inside** `_render_table_component`, upstream of the trim at the end of `_render_component_content`. A section ending in a table contributes no spacer. **This is a sequencing constraint, not a coincidence** — adding the spacer in any later pass would break the guard. |
| **Pinned blank after the description paragraph** | **`RISK`** | Only under open question 1 option B. Removing the authored blank makes `getnext()` the `Recommended Remediation:` title and fails [test_docx.py#L248-L251](../../tests/test_docx.py#L248-L251). Steps 1–5 do not touch it. |
| **Adjacent-table merge in Word** | **`RISK` today → `clear` after step 1** | Two consecutive `TableFragment`s currently emit two `w:tbl` siblings with nothing between them; Word merges them. Masked only because a paragraph fragment usually sits between. Nothing enforces this today. |
| Duplicate `_set_page_break_before` | `clear` | Reached only by `scripts/compose_component_test.py` and [tests/test_docx_components.py](../../tests/test_docx_components.py#L29-L52). The plan adds `_keep_with_next` to `docx_report.py` **only**; mirroring it would create a second copy of a rule that has already demonstrated it drifts. |
| Binary `.docx` template edits | `clear` under the recommended plan | No template modified in steps 1–5. Under option B the diff is an opaque binary blob — unreviewable in a PR, rollback is "restore the old file". That is the reason to prefer the Python rule. |
| In-flight reports on disk | `clear` | `resources/**` is read fresh on every `render_report_docx`; nothing is cached in a draft. A report saved before the change renders with the new layout on next generate, no migration. |
| Schema break / `draft.json` shape | `clear` | `TableFragment` gains no field. `render_report_docx` returns `bytes`, mutating nothing. |
| Stale write (`saved_at`) / lost update | `clear` | No mutation path added. `finalized_report` reads under `workspace.locked_report`; the only write is `atomic_write_bytes` of the `.docx`. |
| Orphan reference (`frag_id`, `evidence_id`) | `clear` | No identifier created, copied, or deleted. The spacer is an anonymous `w:p` with no model counterpart. |
| Rule drift Python ↔ JavaScript | `clear` | `app.js` renders no DOCX preview. The real twin is `docx_report` ↔ `docx_import`, addressed by the structural-matching row above. |
| Derived-state fight with `provision` / backup exhaustion | `clear` | Nothing is written back to the report, so the `draft.bak.json` slot is never consumed. |
| **`keepNext` over-chaining pushes a large block to the next page** | **`RISK`, low** | Chains are bounded: at most two paragraphs for `Proof of Concept: `, one for a label or caption. Where a chain cannot be satisfied — a table taller than a page — Word abandons the keep and breaks anyway, so the failure mode is "no worse than today", not a corrupt document. |

### Plan

**Step 1 — Table spacer and adjacent-table fix. Python only.** In `_render_table_component`, after `rendered.append(table_element)`, append one empty `w:p` taken from `paragraph_fragment.docx`. Test: new case with **two consecutive table fragments**, asserting each `w:tbl` has a `w:p` next sibling, no two `w:tbl` are siblings, and the spacer has no `w:numPr`/`w:pStyle`. Invariant: no two `w:tbl` siblings; spacer stays textless so `_build_fragments` drops it.

**Step 2 — Confirm the spacer is invisible on the way back. Tests only.** Re-run [tests/test_docx_import.py#L179-L185](../../tests/test_docx_import.py#L179-L185) and [tests/test_docx.py#L230-L247](../../tests/test_docx.py#L230-L247) unchanged. **If either fails, step 1 is wrong — stop.**

**Step 3 — `keepNext` helper and structural title marking. Python only, no template edits.** Add `_keep_with_next` next to `_set_page_break_before`. In `_render_finding_component`, for each `-fragments-here` anchor reuse [_component_anchor_index](../../app/docx_report.py#L980-L992) and walk backwards marking every preceding non-empty `w:p`, stopping at the first blank. Test: `keepNext` present on the four titles/boilerplate lines, **absent** on the blanks above them. Invariant: no literal heading string enters `docx_report.py`.

**Step 4 — `keepNext` on generated blocks. Python only.** Environment label (extend the existing `space_after` loop to cover **every** `w:p` in the label component, including its trailing blank, or the chain stops at the blank); the `InstanceTitleFragment` branch; the pre-content captions in the `CodeFragment` branch and `_render_table_component`; the image paragraph in `_render_image_component`. Test: assert `keepNext` on `PROD:`, an instance title, a table caption, an image paragraph; assert **absent** on the caption following an image. Invariant: `keepNext` applied at the two pre-content caption call sites, **not** inside `_render_caption_component`, which also serves post-image captions.

**Step 5 — Documentation. Docs only.** Correct [docs/DOCX_TEMPLATE.md](../../docs/DOCX_TEMPLATE.md#L124-L127)'s table sentence; record that the renderer sets `keepNext` structurally.

**Step 6 — Blank-line removal. Gated on open question 1. Not started without an answer.**

### What the planner explicitly would NOT do

- **Edit the binary `.docx` templates to add `keepNext`.** Unreviewable diff; a future template re-author silently loses the behaviour. The structural Python rule survives a re-author because it keys off the `{{...}}` anchor that must exist anyway.
- **Add the table spacer in a pass after fragments are assembled.** It would run after the trim, so an end-of-section table would stack a spacer on the template blank and break `blank_count <= 1`.
- **Put `keepNext` inside `_render_caption_component`.** That function also emits the caption *after* an image, which is the end of a chain, not the start.
- **Mirror `_keep_with_next` into `docx_components.py`.** Two copies of `_set_page_break_before` already exist and have already diverged in reachability.
- **Try to remove the blank only when a page break falls above it.** python-docx has no pagination model. Promising a conditional fix would be promising something that cannot be built.
- **Add `keepNext` to the finding title.** Every finding after the first already carries `pageBreakBefore`, and the first sits under a severity heading that carries one. It cannot be stranded, so the mark would be dead weight.

### Open questions

1. **Remove the blank line above section titles outright, or leave it?** Removal cannot be conditional, so it changes spacing in every finding of every report, and reverses a pinned test. Planner recommendation: **leave it**, ship steps 1–5, look at a real rendered report first.
2. **What should "a new line below table fragments" mean when the table is last in a section?** Planner recommendation: emit unconditionally and let the existing trim remove it when last — free, since the trim already runs after table rendering.

## Round 2 - Oracle: verdict on the proposal

> Oracle's headline: *"The plan's core reframing survives: `keepNext` is the right mechanism... But the risk table is not a trustworthy inventory — two rows are right for the wrong reason, one `RISK` is mislabelled, four real hazards have no row at all, and the planner missed a third render-path test."*

### Claim-by-claim

**C1 — conclusion right, evidence list incomplete.** `classify_paragraph` is at [docx_import.py#L113](../../app/docx_import.py#L113) (planner's range drifted) and inspects **six** things, not five. The planner omitted the first and most important: `.//a:blip` descendants at [L115](../../app/docx_import.py#L115), which runs *before* `w:pPr` is fetched. Verdict holds — every lookup is a *named* child lookup, so `w:keepNext` is invisible to import — but the row is not a reliable inventory of what import reads.

**C2 — TRUE, and worse than described.** Branch order: list branch at [L273](../../app/docx_import.py#L273) has **no empty-text guard**; the general guard `if not text.strip(): continue` is at [L280](../../app/docx_import.py#L280), **strictly after** it. Two corrections to the planner:
1. **It is a phantom `numbered_list`, not `bulleted_list`.** [L120-123](../../app/docx_import.py#L120-L123) returns `bulleted_list` *only* when `formats.get(numId) == "bullet"`; every other case **including an unknown `numId`** falls to `numbered_list` — restarting at 1 after every table.
2. **The caption-style hazard is data loss, not a stray fragment.** At [L233-238](../../app/docx_import.py#L233-L238) a caption-classified paragraph whose predecessor is an image does `fragments[-1]["caption"] = _clean(caption)` — an *empty* caption-styled spacer would **silently erase the preceding image's caption**.

**C3 — TRUE, call order verified.** `_render_table_component` → `_render_component_fragment` → `_render_component_content` ends at [L726](../../app/docx_report.py#L726) with `return _trim_trailing_empty_paragraphs(rendered)`. The trim is strictly downstream and does remove an end-of-section spacer. **But step 1 is not implementable as written** — the named helper `_render_text_component(..., "paragraph", [])` returns *more than one* `w:p`; [L852-853](../../app/docx_report.py#L852-L853) picks the first and [L866](../../app/docx_report.py#L866) trims the rest. Appending the whole cloned list gives every table **two** blanks.

**C4 — mechanism verified, property claim asserted but never checked.** Reuse is viable ([L852-853](../../app/docx_report.py#L852-L853), `FRAGMENT_COMPONENT_FILES["paragraph"]` at [L75](../../app/docx_report.py#L75)). But: *"the planner named `paragraph_fragment.docx` as the safe source without ever inspecting it. That is the plan's weakest load-bearing assertion."* **Settled by the coordinator below.**

**C5 — implementable but under-specified, and it cannot reach one title.** `_component_anchor_index` ([L980-992](../../app/docx_report.py#L980-L992)) returns one index and raises unless exactly one match. The walk is implementable **only if inserted between [L643](../../app/docx_report.py#L643) and [L654](../../app/docx_report.py#L654)** — the plan never says that. Three further problems:
1. **`Severity Review Ticket (if applicable):` has no `-fragments-here` anchor** — it is filled by `replace_component_token` in the `values` loop. **Step 3's mechanism cannot reach it**, yet it is one of the four titles guarded by the existing blank-count test. Step 3's stated test "counts the wrong four and papers over the gap."
2. Later anchors are walked over a list where earlier anchors are already replaced by rendered content. "Stop at the first blank" is safe only because every template title has a blank above it — dumped for `new_finding.docx`, only *summarised* for `retest_finding.docx`.
3. Calling `_component_anchor_index` twice per anchor is wasteful but harmless.

**C6 — TRUE, exactly three call sites:** [L756](../../app/docx_report.py#L756) `CodeFragment` (pre-content), [L869](../../app/docx_report.py#L869) `_render_image_component` (post-image), [L878](../../app/docx_report.py#L878) `_render_table_component` (pre-content). Applying at call sites is correct. **Unstated consequence:** `_render_caption_component` ([L816](../../app/docx_report.py#L816)) returns `[]` when the caption is falsy, so *"keepNext on the pre-table caption is a **no-op for every uncaptioned table**"* — the majority case, as the planner's own dump shows (three uncaptioned tables in VDB-035).

**C7 — conclusion holds.** [L536](../../app/docx_report.py#L536) is inside `if index:` so the first finding of every severity is skipped; [L548](../../app/docx_report.py#L548) is unconditional on the heading. No orphan case exists, including first-finding-of-first-severity and single-finding severity blocks. Unverified dependency: [L543-547](../../app/docx_report.py#L543-L547) takes the first *top-level* `w:p` — if a `w:tbl` preceded the title in the template, the break would land wrong and strand that table. **Settled by the coordinator below.**

**C8 — the "extension" is already the loop's behaviour; the warning cancels itself.** `_render_environment_label` already loops every top-level `w:p` and sets `space_after` at [L676](../../app/docx_report.py#L676). Adding `keepNext` there covers a trailing blank automatically, whether or not one exists. One genuine narrowing the planner missed: the loop iterates `elements`, **not** `element.iter(qn("w:p"))`, so a `w:p` nested inside a table in that component is missed by both `space_after` today and any `keepNext` added there.

### Q1 — Which risk rows are wrong

**Right verdict, unreliable evidence:** `classify_paragraph` row (incomplete enumeration); image→caption adjacency row — *"The planner got there by luck, not by reading the consumer."* `add_native_image_captions` uses `body.iter(qn("w:p"))`, which is **recursive** and descends into table cells, then advances `index += 2` while pairing by `getnext()`. A body-level spacer shifts list positions but never sibling adjacency, **so the verdict survives.**

**Mislabelled:** *Adjacent-table merge* is a **pre-existing latent defect** that step 1 happens to close, not a risk introduced by the change. Inflates the table.

**Four real hazards with no row at all:**
1. A caption-styled empty paragraph **erases the preceding image's caption**.
2. `_render_text_component` returns **more than one `w:p`** — "append one empty `w:p`" is not what the named helper produces.
3. `Severity Review Ticket (if applicable):` is **unreachable** by step 3's anchor walk.
4. `_render_caption_component` returns `[]` for an uncaptioned table, making the table half of step 4 a **no-op in the common case**.

### Q2 — Files the planner missed

- **[tests/test_app.py#L1433](../../tests/test_app.py#L1433) — the big miss.** `test_generate_docx_route_uses_template_and_report_filename` renders a full report through `GET /reports/{id}/generate` and asserts **`assertEqual(caption.text, "Figure 2 Production proof")`** at [L1494](../../tests/test_app.py#L1494) — a pinned *figure number* produced by `add_native_image_captions` walking every `w:p` in the body.
- **[scripts/generate_report.py#L26](../../scripts/generate_report.py#L26)** calls `render_report_docx` directly — a second entry point.
- **[scripts/postprocess_captions.py#L17](../../scripts/postprocess_captions.py#L17)** is a standalone post-processing entry over an already-generated file, so *"the plan's 'that stage does not exist' is slightly too strong."*
- **`resources/fragments/paragraph_fragment.docx`** becomes a **read dependency with a pinned assertion** and belongs in the radius.
- **No JavaScript counterpart** confirmed absent.

### Q3 — Does this break any `draft.json` on disk?

**No.** The only route to a `draft.json` is the import path, bounded entirely by `_build_fragments`: the spacer is dropped at [L280](../../app/docx_import.py#L280) **provided** it carries no `w:numPr` and no caption `w:pStyle`.

> Blunt on the failure mode: *"if the spacer is sourced wrongly, nothing crashes. `Report.model_validate` accepts a draft carrying a phantom numbered_list after every table. The **only** detector is [tests/test_docx_import.py#L179-L185](../../tests/test_docx_import.py#L179-L185), whose pinned sequence puts an image immediately after the table — precisely where a phantom would land. It is the single gate between this change and silent draft corruption, and it should be named as such in step 2 rather than listed as a formality."*

### Asserted without evidence

1. "Source it from `paragraph_fragment.docx`" — file never opened.
2. "Phantom `bulleted_list`" — it is `numbered_list` whenever the `numId` is unknown.
3. "Append one empty `w:p`" — the named helper returns more than one.
4. "Extend the existing `space_after` loop" — the loop already covers every top-level `w:p`.
5. "Chains are bounded: at most two paragraphs" — true for `new_finding.docx`; `retest_finding.docx` was summarised, not dumped.
6. "keepNext present on the four titles" — counts the wrong four, excluding the title the mechanism cannot reach.

---

### Coordinator addendum — settling the Oracle's blocking question

The oracle could not open binaries and named `paragraph_fragment.docx` as the one thing blocking safety. I dumped it, plus `title_fragment.docx` and `caption_fragment.docx`:

```
=== paragraph_fragment | top-level children: ['p', 'p', 'sectPr']
   p0: style='Normal'            text='{{paragraph-fragment}}'  pPr=['jc']
   p1: style='Normal'            text=''                        pPr=['jc']
=== title_fragment     | top-level children: ['p', 'sectPr']
   p0: style='Normal'            text='{{instance-fragment}}'   pPr=['rPr']
=== caption_fragment   | top-level children: ['p', 'p', 'sectPr']
   p0: style='Figures and Tables' text='{{caption-fragment}}'   pPr=['pStyle']
   p1: style='Normal'             text=''                       pPr=['jc']
```

**Five findings, all decisive:**

1. **`paragraph_fragment.docx` is a SAFE spacer source. The plan's weakest assertion is now proven true.** Its paragraphs carry **only `w:jc`** — no `w:numPr`, no `w:pStyle`. `classify_paragraph` routes `w:jc val="both"` to `"paragraph"` ([docx_import.py#L127-129](../../app/docx_import.py#L127-L129)), which **is** guarded by [L280](../../app/docx_import.py#L280). The C2 phantom-`numbered_list` hazard and the caption-erasure hazard are both **unreachable from this source**. The `clear` verdict on fragment-type ordering stands.
2. **C3 confirmed exactly.** `paragraph_fragment.docx` has **two** `w:p`. So `_render_text_component(..., "paragraph", [])` returns two, and step 1 must take **one** — the same `next(... if element.tag == qn("w:p"))` pick that [L852-853](../../app/docx_report.py#L852-L853) already uses. Appending the list wholesale gives two blanks per table.
3. **C8 is moot — `title_fragment.docx` has exactly ONE paragraph and no trailing blank.** The planner's "or the chain stops at the blank" warning describes a condition that does not exist. Its `pPr=['rPr']` is the paragraph-mark bold/italic that `_paragraph_mark` reads to classify the label as `instance_title` on import — so the env label round-trips through the bold branch, not the `w:jc` branch.
4. **`caption_fragment.docx` also carries a trailing blank**, which explains the empirically observed `caption / '' / tbl` ordering in Round 1. A caption is already separated from its own table by a blank.
5. **C7's unverified dependency resolved.** Both finding templates' first top-level child is a `w:p`:
   ```
   new_finding:    first='p'  contains_tbl=True  top_level_children=13
   retest_finding: first='p'  contains_tbl=True  top_level_children=23
   ```
   The page break therefore lands on the finding title as intended. Both templates *do* contain a `w:tbl` (the finding details table), but it is not first, so no table is stranded.

**One correction to the Oracle itself.** It named `tests/test_app.py` as "a third render-path test". There are **four** files on the render path, not three:

```
tests/test_docx.py
tests/test_docx_import.py
tests/test_app.py
tests/test_browser.py     <- missed by both planner and oracle
```

`tests/test_browser.py` drives report generation end-to-end through the UI. Note it contains one of the two known Windows-only failures (`update_docx_fields_with_word` needs pywin32), so on macOS it cannot fully validate generation — which means **`tests/test_docx.py` and `tests/test_docx_import.py` are the only gates that actually execute on this machine.** That strengthens the oracle's point: `tests/test_docx_import.py#L179-L185` is the single real detector of silent draft corruption.

## Round 2 - Planner: revised plan

### What changed from Round 1

1. `paragraph_fragment.docx` proven safe by binary dump — the two import hazards are **unreachable**, not merely mitigated.
2. Step 1 now takes **exactly one** `w:p`, not the cloned list (the helper returns two).
3. Phantom fragment type corrected: `numbered_list`, not `bulleted_list`.
4. Added the caption-erasure hazard — silent data loss, worse than the one Round 1 named.
5. `classify_paragraph` inventory corrected to **six** lookups, `.//a:blip` first.
6. Step 3 pinned to the only implementable insertion window, [docx_report.py#L643–L654](../../app/docx_report.py#L643-L654).
7. `Severity Review Ticket (if applicable):` explicitly **scoped out** and pinned by an absence assertion, instead of silently miscounted.
8. Uncaptioned tables now covered by a **new step 5** walk-back, replacing a call-site mark that was a no-op for the majority case.
9. Environment label downgraded from "extension" to a one-line addition; the non-existent trailing-blank warning deleted; the real `elements`-vs-`iter` narrowing recorded.
10. Adjacent-table merge relabelled **pre-existing defect**, not an introduced risk.
11. Test radius 2 → 4 files, each labelled macOS-runnable or Windows-gated.
12. Round 1 open question 2 closed by evidence; two script consumers added; "post-processing does not exist" softened.
13. One hazard neither round caught: `keepNext` on a finding's last paragraph, whose successor carries `pageBreakBefore`.

### Corrected data-risk table

| Hazard | Verdict | Reasoning |
|---|---|---|
| Phantom `numbered_list` after every table | `clear` — **by binary inspection**, not assumption | List branch at [docx_import.py#L273](../../app/docx_import.py#L273) has no empty-text guard and precedes the general guard at [#L280](../../app/docx_import.py#L280); an unknown `numId` falls through to `numbered_list` at [#L120-L123](../../app/docx_import.py#L120-L123), restarting at 1 after every table. **Unreachable:** `paragraph_fragment.docx` paragraphs carry only `w:jc`, no `w:numPr`. |
| **Caption erasure — silent data loss** | `clear` — **by binary inspection** | [docx_import.py#L233-L238](../../app/docx_import.py#L233-L238): a caption-classified paragraph whose predecessor fragment is an image does `fragments[-1]["caption"] = _clean(caption)`. An empty caption-styled spacer would wipe the preceding image's caption. **Unreachable:** no `w:pStyle` on the source paragraphs. |
| Spacer count — helper returns two `w:p` | `RISK`, closed by step 1 | `_render_text_component(..., "paragraph", [])` returns **both** of `paragraph_fragment.docx`'s paragraphs. Appending the list gives every table two blanks. Step 1 takes one. |
| `classify_paragraph` blind to `keepNext` | `clear` — full inventory read | Inspects **six** things in order: `.//a:blip` ([#L115](../../app/docx_import.py#L115), *before* `w:pPr` is fetched), then `w:pStyle`, `w:numPr`, `w:shd/@w:fill`, `w:jc`, `w:pPr/w:rPr/w:b\|w:i`. `w:keepNext` is on none of those paths. |
| `Severity Review Ticket (if applicable):` unreachable by the anchor walk | `RISK` — **accepted and scoped out** | Filled by `replace_component_token` in the `values` loop, not by an anchor splice, so step 3's mechanism cannot see it. Step 3 pins its **absence** rather than miscounting four titles. |
| Uncaptioned table gets no `keepNext` | `RISK` — closed by step 5 | `_render_caption_component` ([#L816](../../app/docx_report.py#L816)) returns `[]` when the caption is falsy. Most tables are uncaptioned — three in the VDB-035 dump. A call-site mark is a no-op for them. |
| Adjacent `w:tbl` siblings merged by Word | **pre-existing latent defect**, not introduced here | Masked today only because a paragraph fragment usually sits between. Step 1 closes it as a side effect. |
| Image → caption sibling adjacency | `clear` — consumer read | `add_native_image_captions` uses `body.iter(qn("w:p"))` (recursive) and pairs by `getnext()` while advancing `index += 2`. A body-level spacer shifts list positions but never sibling adjacency. The spacer is appended *after* the `w:tbl`. `keepNext` adds no sibling. |
| Pinned figure number `"Figure 2 Production proof"` | `clear` by reasoning — **unverifiable on macOS** | [tests/test_app.py#L1494](../../tests/test_app.py#L1494). Numbering follows conversion order, not element index, and no conversion pair is disturbed. **Must be re-run on Windows.** |
| `blank_count <= 1` guard | `clear` — call order verified | Spacer added inside `_render_table_component`, upstream of the trim at [#L726](../../app/docx_report.py#L726). Sequencing constraint, not coincidence. |
| Environment-label round trip | `clear` | `keepNext` is a property, not a reorder. Label round-trips via `_paragraph_mark` bold to `instance_title`, not via `w:jc` — untouched either way. |
| Section-title text, Python ↔ Python | `clear` | Titles found by position relative to the `{{...}}` anchor. No literal heading string enters `docx_report.py`. |
| Pinned blank after the description paragraph | `RISK` **only under option B** of open question 1 | [tests/test_docx.py#L248-L251](../../tests/test_docx.py#L248-L251) asserts that element is an empty `w:p`. Steps 1–7 do not touch it. |
| `keepNext` over-chaining | `RISK`, low | Chains bounded: two paragraphs for `Proof of Concept:`, one for a label or caption. Step 5 adds one unbounded case — a long lead-in chained to a table. Where a keep cannot be satisfied Word abandons it, so failure is "no worse than today". |
| **`keepNext` on a finding's last paragraph** | `RISK`, low — **new in Round 2** | If an `InstanceTitleFragment` is the final fragment of a finding's last section, step 4 marks the finding's last paragraph, whose successor is the next finding's first `w:p` carrying `pageBreakBefore`. They can never share a page; Word abandons the keep. Benign, but a real consequence of step 4. |
| `paragraph_fragment.docx` as a read dependency | `clear` | Gains a pinned assertion in step 1 (no `w:numPr`, no `w:pStyle`), so a future re-author that adds either **fails loudly instead of corrupting drafts**. |
| Duplicate `_set_page_break_before` | `clear` | Reached only by `scripts/compose_component_test.py` and `tests/test_docx_components.py`. `_keep_with_next` added to `docx_report.py` only. |
| Schema break / `draft.json` shape | `clear` | `TableFragment` gains no field. `render_report_docx` returns `bytes`, mutates nothing. |
| Stale write / lost update / backup exhaustion | `clear` | No mutation path added. `draft.bak.json` never consumed. |
| Orphan reference (`frag_id`, `evidence_id`) | `clear` | Spacer is an anonymous `w:p` with no model counterpart. |
| Rule drift Python ↔ JavaScript | `clear` | `app.js` renders no DOCX preview. |
| Binary template edits | `clear` | None in steps 1–7. |

### Revised plan

**Step 1 — Table spacer.** [app/docx_report.py](../../app/docx_report.py#L873-L922), `_render_table_component`, right after `rendered.append(table_element)`. Clone via `_render_text_component(document, component_root, "paragraph", [])` and append **exactly one** `w:p` using the same `next(...)` pick as [#L852-L853](../../app/docx_report.py#L852-L853). **Do not append the returned list — it has two paragraphs.**
*Test:* two consecutive `TableFragment`s; assert every `w:tbl` has a `w:p` next sibling, no `w:tbl` has a `w:tbl` sibling, exactly **one** spacer per table, spacer has no `w:numPr`/`w:pStyle`, and a section ending in a table contributes no spacer. **Runs on macOS: yes.**
*Invariant:* no two `w:tbl` siblings; spacer stays textless and property-free so import drops it.

**Step 2 — The single gate against silent draft corruption. Tests only.** Re-run [tests/test_docx_import.py#L179-L185](../../tests/test_docx_import.py#L179-L185) and [tests/test_docx.py#L230-L234](../../tests/test_docx.py#L230-L234) **unchanged**.
> Not a formality. If the spacer is sourced wrongly nothing crashes — `Report.model_validate` accepts a draft carrying a phantom `numbered_list` after every table, and the corruption ships silently into every imported draft. That pinned sequence places an image immediately after the table, **precisely where a phantom would land.**
**Runs on macOS: yes.** *If this fails, step 1 is wrong — stop, and do not adjust the pinned list.*

**Step 3 — `_keep_with_next` and the section-title walk.** Add `_keep_with_next` beside `_set_page_break_before` ([#L994](../../app/docx_report.py#L994)). Insert the walk in `_render_finding_component` **between [#L643](../../app/docx_report.py#L643) and [#L654](../../app/docx_report.py#L654)** — the only implementable window, because the anchor must still be present and must be re-located each iteration after earlier splices shift indices. Walk backwards from `index - 1` marking each element while it is a non-empty `w:p`; stop at the first blank or first non-`w:p`.
**Scope-out, stated plainly:** `Severity Review Ticket (if applicable):` has no anchor and **this step does not cover it**.
*Test:* assert `keepNext` present on the anchored lead-ins; **absent** on every blank above them, on the finding title, and on `Severity Review Ticket (if applicable):` — that last assertion pins the scope-out so it cannot drift into an unnoticed gap. Assert each walk terminated on a blank in **both** templates, converting the one remaining template assumption into a test. **Runs on macOS: yes.**
*Invariant:* no literal heading string enters `docx_report.py`.

**Step 4 — `keepNext` on generated labels, titles and pre-content captions.** One line inside the **existing** `space_after` loop in `_render_environment_label` ([#L676](../../app/docx_report.py#L676)); the `InstanceTitleFragment` branch; the `CodeFragment` caption **call site** ([#L756](../../app/docx_report.py#L756)); the image paragraph in `_render_image_component`.
*Note:* `title_fragment.docx` has exactly one `w:p` and no trailing blank, so there is no chain-stops-at-a-blank case. The loop iterates `elements`, not `element.iter(qn("w:p"))` — vacuous now, recorded as a template coupling.
**Not covered, stated plainly:** an uncaptioned code block. A code block is a run of ordinary paragraphs Word may split at any paragraph mark — there is no all-or-nothing block to orphan.
*Test:* assert `keepNext` on `PROD:`, an instance title, a captioned code block's caption, the image paragraph; **absent** on the caption *following* an image and on the paragraph before an uncaptioned code block. **Runs on macOS: yes.**

**Step 5 — Keep every table with its lead-in, captioned or not.** `_render_component_content`, applied to the list returned by `_trim_trailing_empty_paragraphs` at [#L726](../../app/docx_report.py#L726). For each `w:tbl`, walk backwards marking `keepNext` on each preceding `w:p`, stopping **after** the first non-empty one and immediately at any non-`w:p`.
*Why this replaces Round 1's table call-site mark:* `caption_fragment.docx` carries a trailing blank, so a captioned table's list is `[caption, blank, tbl]` — marking only the caption leaves the blank unmarked and the chain broken. The walk marks both. For the uncaptioned majority it marks the real lead-in sentence, which is what was actually asked for.
*Scope note:* the finding **details** table lives inside the finding-type templates and never passes through `_render_component_content`, so the walk never touches it.
*Test:* for `[paragraph, table]` assert the paragraph carries `keepNext`; for a captioned table assert both the caption and the blank carry it; for `[table, table]` assert the walk stops at the step-1 spacer. **Runs on macOS: yes.**

**Step 6 — Record what cannot be verified here.**
- [tests/test_app.py#L1433](../../tests/test_app.py#L1433) calls `GET /reports/{id}/generate` **unpatched**; the `update_docx_bytes_with_word` patches at [#L1511](../../tests/test_app.py#L1511) and [#L1525](../../tests/test_app.py#L1525) cover only the later `POST` calls. On macOS the route returns 422 before reaching the pinned figure number. **Windows-gated.**
- [tests/test_browser.py#L1428](../../tests/test_browser.py#L1428) drives `POST .../generate` through the real UI with no patch. **Windows-gated.**
- Consequence: **only `tests/test_docx.py` and `tests/test_docx_import.py` execute the render path on this machine.** Both Windows-gated tests must be re-run before release — *reasoning is not verification.*
- Consumers in radius, no change: [scripts/generate_report.py#L26](../../scripts/generate_report.py#L26), [scripts/postprocess_captions.py#L17](../../scripts/postprocess_captions.py#L17). Round 1's "that stage does not exist" was too strong — it exists, it just is not on the app's render path.

**Step 7 — Documentation.** Correct [docs/DOCX_TEMPLATE.md#L124-L127](../../docs/DOCX_TEMPLATE.md#L124-L127)'s table claim; record the `keepNext` rule and both scope-outs. [docs/DATA_MAP.md](../../docs/DATA_MAP.md): **no change.**

**Step 8 — Blank-line removal. Gated on open question 1.**

### What the planner would NOT do (revised)

- Edit the binary templates to add `keepNext` — unreviewable diff; a future re-author silently loses it.
- **Append the whole cloned paragraph component as the spacer** — it has two `w:p`, so every table would get two blanks.
- Add the spacer in a pass after fragments are assembled — it would run after the trim and break `blank_count <= 1`.
- Put `keepNext` inside `_render_caption_component` — it also emits the post-image caption, the end of a chain.
- **Keep the table-caption call-site mark from Round 1** — a no-op for every uncaptioned table, and even for captioned ones it misses the blank `caption_fragment.docx` puts between. *Silently doing nothing in the majority case is worse than not claiming coverage.*
- **Count `Severity Review Ticket:` among the titles step 3 covers** — asserting on four titles when only three are reachable papers over the gap; asserting its absence makes the gap visible.
- Mirror `_keep_with_next` into `docx_components.py`.
- Try to remove the blank conditionally — python-docx has no pagination model.
- Add `keepNext` to the finding title — verified no orphan case exists.
- **Adjust the pinned sequence in `tests/test_docx_import.py` to make step 1 pass** — that test is the only thing standing between this change and silent draft corruption.

## Answers

**Q0 (raised by the user during review): "Python cannot see or know if there are page breaks, or where they are?"**

Confirmed, with evidence — but the answer splits in two, and the distinction is the whole basis of this plan.

| Kind of break | Can Python see it? | Evidence |
|---|---|---|
| **Explicit** — `w:pageBreakBefore` in the XML, written by our own code | **Yes, exactly.** 16 of them in the generated report | `para 80 ' Findings Summary'`, `para 89 'High Findings'`, `para 113 'Medium Findings'`, `para 138 'Exposure of Internal Rules'`, … |
| **Automatic** — Word flowing to a new page when the current one fills | **No. Never written to the file.** Computed live by the layout engine from font metrics, margins, line-breaking and widow/orphan rules | — |

**The automatic kind is what is stranding the titles and labels.**

The `w:lastRenderedPageBreak` cache looked like it might help, and it does exist (11 in `MAIN_TEST.docx`, 21 in a Word-saved report, 10 in fresh output). **It is stale template residue.** In a generated report of 417 paragraphs, with all 14 findings between paragraphs 80 and 411, the 8 markers sit at:

```
7, 25, 42, 53, 59, 65, 80    <- template front matter
411                           <- template appendix
```

**Zero markers across the ~330 paragraphs of findings.** A 14-finding report clearly breaks pages many times in that range. Reading these would yield confidently wrong data, not merely no data.

**On "is this post-processing?"** — a post-pass over the finished `.docx` is perfectly possible ([scripts/postprocess_captions.py](../../scripts/postprocess_captions.py#L17) already does exactly that). It does not help here. Post-processing does not fail because it runs too early; it fails because **the information is not in the file at any point in time.** The only component that knows is Word itself, via `update_docx_bytes_with_word`, which is Windows-only and never executes on this machine.

Even given perfect pagination there is a convergence problem: removing a blank shifts content up, which moves the break, which changes which blanks qualify. It would need to iterate to a fixed point and could oscillate.

> This is exactly why `keepNext` is the right mechanism: **you never ask where the break is.** You declare "this paragraph must stay with the next one" and Word enforces it *while* paginating.

**Q1. Remove the blank paragraph above each section title, or leave it? → DECIDE LATER.**
Ship steps 1–7. Revisit step 8 only after reviewing a real Windows-generated report. Rationale: the removal cannot be made conditional, so it would change spacing in every finding of every report; and `keepNext` may make it moot by moving the title and its content down together, leaving the blank invisible at the bottom of the previous page.

**Q2. Should `Severity Review Ticket (if applicable):` get orphan protection? → NO — scope it out, assert the gap.**
It is filled by token replacement, not an anchor splice, so step 3's walk cannot reach it. Covering it would require a second mechanism that puts a literal heading string into `docx_report.py`, breaking the rule that `SECTION_HEADINGS` in `docx_import.py` is the sole owner of those strings. **Step 3 must assert its absence**, so the gap is pinned and visible rather than silently forgotten. Low impact: the heading is short, sits at the end of a finding, and the next finding starts on a fresh page regardless.

**Q3. Should step 5 refuse to keep a table with an unusually long lead-in? → NO — no size limit.**
`keepNext` prevents a break *between* two paragraphs; it ties the **last line** of the lead-in to the start of the table. Word remains free to split the lead-in paragraph itself across pages (that is `keepLines`, which is not being set). So even a very long lead-in costs at most one line moved, never the whole paragraph. A size limit would add a tuning constant with no natural value, guarding against something the mechanism already prevents. Where a table is taller than a page, Word abandons the keep and breaks anyway — no worse than today.

## Agreed plan

**Goal.** Stop headings, environment labels and table lead-ins being stranded at the bottom of a page by Word's automatic pagination, and put a blank line below every rendered table.

**Mechanism.** `w:keepNext` as a paragraph property — not element reordering, which cannot work because there is no generator-inserted break next to any of these elements. Plus one spacer paragraph after each table.

**Scope.** Render-time only. No `draft.json` shape change, no schema change, no `saved_at` bump, no migration. No binary template edits in steps 1–7.

**Local verification reality.** Only [tests/test_docx.py](../../tests/test_docx.py) and [tests/test_docx_import.py](../../tests/test_docx_import.py) execute the render path on macOS. [tests/test_app.py](../../tests/test_app.py#L1433) and [tests/test_browser.py](../../tests/test_browser.py#L1428) are **Windows-gated** (`update_docx_bytes_with_word` needs pywin32; the route returns 422 without it) and must be re-run before release.

---

### Step 1 — Table spacer

- **Files:** [app/docx_report.py](../../app/docx_report.py#L873-L922) — `_render_table_component`, immediately after `rendered.append(table_element)`.
- **Change:** clone via `_render_text_component(document, component_root, "paragraph", [])` and append **exactly one** `w:p`, using the same `next(element for element in ... if element.tag == qn("w:p"))` pick as [#L852-L853](../../app/docx_report.py#L852-L853). **Do not append the returned list — it contains two paragraphs.**
- **Test:** new case in `tests/test_docx.py` rendering a section with two consecutive `TableFragment`s. Assert (a) every `w:tbl` has a `w:p` next sibling, (b) no `w:tbl` has a `w:tbl` sibling, (c) exactly **one** spacer per table, (d) the spacer has no `w:numPr` and no `w:pStyle`, (e) a section ending in a table contributes no spacer. **Runs on macOS.**
- **Invariant:** no two `w:tbl` siblings (Word merges them); the spacer stays textless and property-free so import drops it at [docx_import.py#L280](../../app/docx_import.py#L280).

### Step 2 — The gate against silent draft corruption (tests only)

- **Files:** [tests/test_docx_import.py#L179-L185](../../tests/test_docx_import.py#L179-L185) and [tests/test_docx.py#L230-L234](../../tests/test_docx.py#L230-L234), both re-run **unchanged**.
- **Why it is a step and not a formality:** if the spacer is sourced wrongly nothing crashes. `Report.model_validate` happily accepts a draft carrying a phantom `numbered_list` after every table, and the corruption ships silently into every imported draft. That pinned sequence places an image immediately after the table — **precisely where a phantom would land.** It is the only detector. **Runs on macOS.**
- **Invariant:** the round-tripped fragment-type sequence is unchanged by rendering.
- **Stop condition:** if this fails, step 1 is wrong. Fix step 1 — **do not adjust the pinned list.**

### Step 3 — `_keep_with_next` and the section-title walk

- **Files:** [app/docx_report.py](../../app/docx_report.py#L994) — add `_keep_with_next` beside `_set_page_break_before`. Insert the walk in `_render_finding_component` **between [#L643](../../app/docx_report.py#L643) and [#L654](../../app/docx_report.py#L654)** — the only implementable window, because the anchor must still be present in `elements` and must be re-located each iteration after earlier splices shift the indices.
- **Mechanism:** `index = _component_anchor_index(elements, anchor)`, then walk backwards from `index - 1`, marking each element while it is a non-empty `w:p`; stop at the first blank `w:p` or first non-`w:p`.
- **Scope-out (agreed Q2):** `Severity Review Ticket (if applicable):` is **not covered** — it has no `-fragments-here` anchor.
- **Test:** assert `keepNext` present on the anchored lead-ins (`Description:`, `Recommended Remediation:`, `Proof of Concept:`, `The following demonstrates the vulnerability:`, plus `Previous Proof of Concept:` and `In Conclusion:` in the retest template). Assert **absent** on every blank above them, on the finding title, and on `Severity Review Ticket (if applicable):` — pinning the agreed gap so it cannot drift into an unnoticed one. Assert each walk terminated on a blank in **both** templates, converting the one remaining template assumption into a test. **Runs on macOS.**
- **Invariant:** no literal heading string enters `docx_report.py`; `SECTION_HEADINGS` in `docx_import.py` stays the sole owner.

### Step 4 — `keepNext` on generated labels, titles and pre-content captions

- **Files:** [app/docx_report.py](../../app/docx_report.py#L676) — one line inside the **existing** `space_after` loop in `_render_environment_label`; the `InstanceTitleFragment` branch; the `CodeFragment` caption **call site** ([#L756](../../app/docx_report.py#L756)); the image paragraph in `_render_image_component`.
- **Notes:** `title_fragment.docx` has exactly one `w:p` and no trailing blank, so there is no chain-stops-at-a-blank case. The loop iterates `elements`, not `element.iter(qn("w:p"))` — vacuous today, recorded as a template coupling.
- **Not covered, deliberately:** an uncaptioned code block. A code block is a run of ordinary paragraphs Word may split at any paragraph mark; there is no all-or-nothing block to orphan.
- **Test:** assert `keepNext` on `PROD:`, an instance title, a captioned code block's caption, and the image paragraph. Assert **absent** on the caption *following* an image and on the paragraph before an uncaptioned code block. **Runs on macOS.**
- **Invariant:** `keepNext` lives at the two pre-content caption call sites, never inside `_render_caption_component`, which also serves the post-image caption at [#L869](../../app/docx_report.py#L869) — the end of a chain, not its start.

### Step 5 — Keep every table with its lead-in, captioned or not

- **Files:** [app/docx_report.py](../../app/docx_report.py#L726) — `_render_component_content`, applied to the list returned by `_trim_trailing_empty_paragraphs`.
- **Rule:** for each `w:tbl` in the section's rendered list, walk backwards marking `keepNext` on each preceding `w:p`, stopping **after** the first non-empty one and immediately at any non-`w:p`. **No size limit** (agreed Q3).
- **Why this replaces a caption call-site mark:** `caption_fragment.docx` carries a trailing blank, so a captioned table's list is `[caption, blank, tbl]` — marking only the caption leaves the blank unmarked and the chain broken. The walk marks both. For the uncaptioned majority it marks the real lead-in sentence, which is what was actually asked for.
- **Scope note:** the finding **details** table lives inside the finding-type templates and never passes through `_render_component_content`, so the walk never touches it.
- **Test:** for `[paragraph, table]` assert the paragraph carries `keepNext`; for a captioned table assert both the caption and the blank between carry it; for `[table, table]` assert the walk stops at the step-1 spacer and does not reach into the first table. **Runs on macOS.**
- **Invariant:** the walk adds no elements, so `blank_count <= 1` and image→caption sibling adjacency are both untouched.

### Step 6 — Record what cannot be verified locally

- [tests/test_app.py#L1433](../../tests/test_app.py#L1433) calls `GET /reports/{id}/generate` **unpatched**; the `update_docx_bytes_with_word` patches at [#L1511](../../tests/test_app.py#L1511) and [#L1525](../../tests/test_app.py#L1525) cover only the later `POST` calls. On macOS the route returns 422 before reaching the pinned figure number at [#L1494](../../tests/test_app.py#L1494). **Windows-gated.**
- [tests/test_browser.py#L1428](../../tests/test_browser.py#L1428) drives `POST .../generate` through the real UI with no patch. **Windows-gated.**
- Both must be re-run on Windows before release. **Reasoning is not verification.**
- Consumers in radius, no change needed: [scripts/generate_report.py#L26](../../scripts/generate_report.py#L26) calls `render_report_docx` directly; [scripts/postprocess_captions.py#L17](../../scripts/postprocess_captions.py#L17) is a standalone post-processing entry over an already-generated file.

### Step 7 — Documentation

- [docs/DOCX_TEMPLATE.md#L124-L127](../../docs/DOCX_TEMPLATE.md#L124-L127): correct the claim that each fragment is emitted "using its corresponding document" — for `table`, only the `w:tbl` is used, every paragraph is discarded, and the renderer now appends one spacer. Record the `keepNext` rule and both scope-outs (`Severity Review Ticket`, uncaptioned code blocks).
- [docs/DATA_MAP.md](../../docs/DATA_MAP.md): **no change.** None of the files that map governs are touched.

### Step 8 — Blank-line removal (DEFERRED by agreement)

Not started. Revisit only after a real Windows-generated report has been reviewed with steps 1–7 in place.

---

### Rejected, and why (kept on the record)

| Rejected | Why |
|---|---|
| Moving the environment title after the page break, as literally requested | There is no generator-inserted break adjacent to it. Nothing to move. |
| Doing any of this in post-processing | The pagination information is not in the file at any point. Post-processing does not run too early — there is nothing to read. |
| Conditional blank removal ("only if a break is above it") | Not computable. python-docx has no layout engine; the cached `lastRenderedPageBreak` markers are stale template residue (zero across 330 paragraphs of findings). |
| Editing binary templates to add `keepNext` | Unreviewable diff; a future template re-author silently loses the behaviour. The Python rule survives a re-author because it keys off the `{{...}}` anchor that must exist anyway. |
| Appending the whole cloned paragraph component as the spacer | It has two `w:p` — every table would get two blanks. |
| Adding the spacer in a pass after fragments are assembled | It would run after the trim at [#L726](../../app/docx_report.py#L726), stacking a spacer on the template blank and breaking `blank_count <= 1`. |
| `keepNext` inside `_render_caption_component` | It also emits the post-image caption — the end of a chain, not its start. |
| Round 1's table-caption call-site mark | A no-op for every uncaptioned table, and even for captioned ones it misses the blank `caption_fragment.docx` inserts. Silently doing nothing in the majority case is worse than not claiming coverage. |
| Counting `Severity Review Ticket:` among step 3's titles | The mechanism cannot reach it. Asserting on four titles when only three are reachable papers over the gap. |
| Mirroring `_keep_with_next` into `docx_components.py` | Two copies of `_set_page_break_before` already exist and have already diverged in reachability. |
| `keepNext` on the finding title | No orphan case exists — every finding after the first carries `pageBreakBefore`, and the first sits under a severity heading that carries one. |
| A size limit on step 5's lead-in walk | `keepNext` ties only the last line; a long paragraph still splits. The guarded failure cannot occur. |
| Adjusting the pinned sequence in `tests/test_docx_import.py` to make step 1 pass | That test is the only thing standing between this change and silent draft corruption. |
