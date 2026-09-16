# Continuing a numbered list from the one before it

## Request

> having the numbered list have an option to continue numbering from last numbered list fragment. this is per content. when creating a numbered list, te default would be that the numbering will start/reset from 1. But there will be an option to contnue the count of the previous numbered list on the same content. This will be printed in the generated docx as well. if the option selected is continue numbering, then continue numbering in the docx as well. the numbered list from poc cannot continue the numbered list in previous poc. same with recommended remediation numbered list, it cannot continue the list from description as they are different contents.

## Round 1 - Oracle: how it works today

### Recap

You asked for a read-only survey of how numbered lists work today, ahead of adding a per-content "continue numbering from the previous numbered list" option. I read the working tree (not git HEAD), traced the list fragment from the Pydantic model through the DOCX renderer, the editor, and the import path, and counted the population on disk. I found one factual error in `docs/DATA_MAP.md` and corrected it; that correction is recorded in section 8 below.

**One thing I could not do: I have no terminal in this session, so I could not unzip any `.docx`.** Every claim about DOCX XML below is derived from the Python that reads and writes it, plus a pinned test that inspects the generated output. Where that leaves a gap, I say so explicitly in section 2.

---

### 1. The list fragment as it exists

#### The model

[app/models.py#L81-L84](app/models.py#L81-L84):

```python
class ListFragment(BaseModel):
    frag_id: StableId
    type: Literal["numbered_list", "bulleted_list"]
    items: list[ListItem] = Field(min_length=1)
```

Three fields. No defaults except the implicit one on `items` (there is none — `min_length=1` makes it required). **No validators of its own.** `ListItem` is `{runs: list[Run]}` ([app/models.py#L77-L78](app/models.py#L77-L78)); `Run` is `{text, bold, italic, underline}` ([app/models.py#L63-L67](app/models.py#L63-L67)).

`numbered_list` and `bulleted_list` are **not two classes**. They are one class with a two-value `Literal`, and the discriminated union keys on `type` ([app/models.py#L123](app/models.py#L123)). Every distinction between them is made by a caller reading `fragment.type` — there are four such readers, in `report_service`, `docx_report`, `docx_import`, and `app.js`.

**No model in this file sets `model_config`**, so Pydantic v2's default `extra="ignore"` applies: a key present in `draft.json` but absent from the model is dropped on load and gone from the file on the next save. This is the trap [docs/DATA_MAP.md](docs/DATA_MAP.md) §6 already records for `content_offer_resolved`.

#### Every site that creates, copies, merges or splits one

Your list was right and incomplete. The full set:

**Python**

| # | Site | What it does |
|---|---|---|
| 1 | `provision` / `required_fragments` [app/report_service.py#L202-L215](app/report_service.py#L202-L215) | seeds `["numbered_list", "image"]` into `previous_proof_of_concept` and `proof_of_concept` — **only when the section is empty** |
| 2 | `ensure_proof_steps` [app/report_service.py#L155-L159](app/report_service.py#L155-L159) | inserts one at **index 0** if the section holds none |
| 3 | `merge_step_lists` [app/report_service.py#L485-L497](app/report_service.py#L485-L497) | collapses consecutive lists — see below |
| 4 | `apply_poc_variant` [app/report_service.py#L499-L518](app/report_service.py#L499-L518) | `model_copy(deep=True)` each library fragment, fresh `frag_id`, `merge_step_lists`, `ensure_proof_steps` |
| 5 | `assign_fresh_fragment_ids` [app/report_service.py#L478-L483](app/report_service.py#L478-L483) | reassigns `frag_id` only, on library insert |
| 6 | `main.insert_library` [app/main.py#L719-L741](app/main.py#L719-L741) | `copy.deepcopy(entry["contents"])` into `Vulnerability(...)`; raw library steps parsed via `Content(type="proof_of_concept", fragments=steps).fragments` at [app/main.py#L740](app/main.py#L740) |
| 7 | `Workspace.load_path` [app/workspace.py#L276-L280](app/workspace.py#L276-L280) | a list fragment with falsy `items` gets `[{"runs": []}]` **and the file is rewritten** |
| 8 | `docx_import._build_fragments` [app/docx_import.py#L273-L279](app/docx_import.py#L273-L279) | builds list fragments back out of a DOCX |

**JavaScript**

| # | Site | What it does |
|---|---|---|
| 9 | `newFragment` [app/web/static/app.js#L2317](app/web/static/app.js#L2317) | `type.endsWith("list")` → `items:[{runs:[]}]` |
| 10 | `provision` / `required` [app/web/static/app.js#L1029-L1042](app/web/static/app.js#L1029-L1042) | twin of #1 |
| 11 | `ensureProofSteps` [app/web/static/app.js#L1199-L1201](app/web/static/app.js#L1199-L1201) | twin of #2 |
| 12 | `remintFragments` [app/web/static/app.js#L1204](app/web/static/app.js#L1204) | `JSON.parse(JSON.stringify(...))` + new `frag_id` — **copies every key**, so a new flag rides along for free |
| 13 | `mergeStepLists` [app/web/static/app.js#L1207-L1219](app/web/static/app.js#L1207-L1219) | twin of #3 |
| 14 | `applyPocVariant` [app/web/static/app.js#L1221-L1232](app/web/static/app.js#L1221-L1232) | twin of #4 |
| 15 | add-fragment menu [app/web/static/app.js#L3386-L3402](app/web/static/app.js#L3386-L3402) | `newFragment(menu.value)` then push; only `image` gets post-creation setup |
| 16 | library replace/merge arms [app/web/static/app.js#L3338](app/web/static/app.js#L3338) | `remintFragments(libraryFragments)` |
| 17 | list textarea `oninput` [app/web/static/app.js#L2641-L2646](app/web/static/app.js#L2641-L2646) | **rewrites `fragment.items` wholesale on every keystroke**; touches no other key |

**There is no split.** Nothing in either language ever divides one `ListFragment` into two. The only ways a section comes to hold two numbered lists are: the tester picks `numbered list` from the add-fragment menu, a DOCX import produces two non-adjacent runs of numbered paragraphs, or a library merge-append lands across an intervening fragment.

#### `merge_step_lists` — narrower than you feared

```python
def merge_step_lists(fragments: list) -> list:
    """Collapse consecutive step lists without moving them across intervening content."""
    merged = []
    for fragment in fragments:
        previous = merged[-1] if merged else None
        if isinstance(fragment, ListFragment) and fragment.type == "numbered_list" and isinstance(previous, ListFragment) and previous.type == "numbered_list":
            items = [*previous.items, *fragment.items]
            written = [item for item in items if any(run.text.strip() for run in item.runs)]
            previous.items = written or items[:1]
        else:
            merged.append(fragment)
    return merged
```
[app/report_service.py#L485-L497](app/report_service.py#L485-L497)

Precisely:

- **Consecutive only.** A fragment of any other type between two lists is a boundary it will not cross. `bulleted_list` is also a boundary, since both sides of the test require `numbered_list`.
- **Merges into the first**, mutating `previous.items` in place; the later fragment is dropped entirely — **and with it any flag that fragment carried.**
- **Drops blank items** when it merges, falling back to `items[:1]` if every item is blank.
- **It runs from exactly one caller: `apply_poc_variant`** ([app/report_service.py#L516](app/report_service.py#L516)). That is reached from `main.insert_library`'s auto-install when exactly one variant applies ([app/main.py#L738-L740](app/main.py#L738-L740)), and from the Content-page offer client-side ([app/web/static/app.js#L3293](app/web/static/app.js#L3293)). **It never runs from `provision`**, so lists a tester typed by hand are never collapsed by a save.

The boundary is pinned by [tests/test_browser.py#L1706-L1727](tests/test_browser.py#L1706-L1727), which asserts a merge-append across a note yields `["numbered_list", "note", "numbered_list", "image"]`.

So the hazard you named is real but bounded: a flag on a second list is destroyed **only when that list is immediately adjacent to the one before it, and only during a library step install.** In that situation the two lists become one fragment and there is nothing left to continue from — which is arguably the right outcome, but it must be a decided one.

---

### 2. How numbered lists reach the DOCX

#### The clone path

`FRAGMENT_COMPONENT_FILES["numbered_list"] = ("numbered_fragment.docx", "numbered-list-fragment")` — [app/docx_report.py#L74-L82](app/docx_report.py#L74-L82).

`_render_component_fragment`, [app/docx_report.py#L753-L765](app/docx_report.py#L753-L765):

```python
if isinstance(fragment, ListFragment):
    component_type = "numbered_list" if fragment.type == "numbered_list" else "bulleted_list"
    filename, token = FRAGMENT_COMPONENT_FILES[component_type]
    numbering_ids: dict[tuple[Path, int], int] = {}      # <- fresh, per fragment
    rendered = []
    for item in fragment.items:
        elements = clone_component_elements(
            document,
            component_root / "fragments" / filename,
            numbering_ids=numbering_ids,
        )
        replace_component_token_runs(elements, token, item.runs)
        rendered.extend(elements)
    return rendered
```

**One clone of `numbered_fragment.docx` per `ListItem`.** The `numbering_ids` cache is created **inside the branch**, so it is shared across the items of one fragment and never across two fragments. That single line is the whole reason lists restart.

#### What `_remap_numbering` actually does

[app/docx_components.py#L225-L284](app/docx_components.py#L225-L284):

1. Reads `component_document.part.numbering_part.element` and `document.part.numbering_part.element` (L232-233). **Both the component and the main template must carry a `word/numbering.xml`.**
2. Walks every `w:numId` element inside the cloned body (L234-239) — i.e. the cloned paragraph's `w:pPr/w:numPr/w:numId`.
3. Keys the cache on `(component path, source numId)` (L241). **A repeat within the same cache reuses the already-allocated target id** — that is what makes all items of one list share a number.
4. On a miss: finds the source `w:num` and its `w:abstractNum` (raising `ComponentCompositionError` if either is absent, L249-252 and L262-265), allocates `abstractNumId = max(existing)+1` and `numId = max(existing)+1` via `_next_numbering_id` (L269-270), deep-copies both, rewrites their ids, assigns the abstract a unique `w:nsid` (`_assign_unique_numbering_identity`, [app/docx_components.py#L288-L303](app/docx_components.py#L288-L303)), calls `_restart_numbering_levels`, inserts the abstract before the first `w:num` and appends the `w:num` (L277-282).
5. Rewrites the cloned paragraph's `w:numId/@w:val` to the new id (L284).

#### What makes a list restart at 1 — the answer

**An explicit `w:startOverride`. Not a python-docx side effect, not Word's implicit behaviour.**

`_restart_numbering_levels`, [app/docx_components.py#L306-L355](app/docx_components.py#L306-L355):

- collects the `w:ilvl` values the cloned paragraphs actually use for that `numId`, **defaulting to `0` when `w:ilvl` is absent** (L307-313);
- skips any level whose `w:numFmt` is `bullet` or `none` (L323-325) — **this is why bulleted lists get no override**;
- reads the abstract level's `w:start`, defaulting to `"1"` (L326-327);
- builds `<w:lvlOverride w:ilvl="N"><w:startOverride w:val="START"/></w:lvlOverride>` on the new `w:num` (L328-355).

So every `ListFragment` gets its **own `numId`, own `abstractNumId`, own `nsid`, and an explicit `startOverride`**. Two list fragments render `1..n` then `1..m`. **Nothing continues by accident.**

This is pinned by [tests/test_docx_components.py#L129-L148](tests/test_docx_components.py#L129-L148), reading via `_numbering_details` ([tests/test_docx_components.py#L267-L289](tests/test_docx_components.py#L267-L289)). For each of two five-item lists it asserts: one distinct `numId` shared by all five items, one shared `nsid`, `startOverride == 1` on every one — and that the two lists differ in **both** `numId` and `nsid`.

#### Coordinator note: the DOCX XML the oracle could not read

The oracle had no terminal and flagged its section 2 XML claims as unverified. I unzipped the files.
**Every inference it drew from the Python was correct.**

`resources/fragments/numbered_fragment.docx` holds exactly one paragraph, carrying:

```xml
<w:numPr><w:ilvl w:val="0"/><w:numId w:val="29"/></w:numPr>
```

`numId 29` resolves to `abstractNumId 11`, whose level 0 is `<w:start w:val="1"/>`,
`<w:numFmt w:val="decimal"/>`, `<w:lvlText w:val="%1."/>`, and carries **no `w:startOverride` of its
own** — the override is written at render time by `_restart_numbering_levels`. The component's
numbering part defines 20 `abstractNum` and 29 `num`; `resources/MAIN_TEST.docx` has a numbering part
with 18 and 27. So `_remap_numbering`'s preconditions hold, `decimal` is neither `bullet` nor `none`
so the `startOverride` branch is live, and the restart is explicit rather than implicit.

#### The mechanism for continuation already exists elsewhere

Two places already share a cache across components, which is exactly what continuation would need:

- `compose_docx_template` creates **one `numbering_ids` per anchor** and threads it through every component at that anchor ([app/docx_components.py#L145-L162](app/docx_components.py#L145-L162)). That path is used by [scripts/compose_component_test.py](scripts/compose_component_test.py) and the component tests — **not** by `render_report_docx`.
- `_replace_token_with_bullets` creates one cache per affected-locations cell so all its bullets share a `numId` ([app/docx_report.py#L577-L582](app/docx_report.py#L577-L582)).

#### Other numbering helpers: none

- [app/docx_captions.py](app/docx_captions.py) contains **no** `numPr`, `numId`, `abstractNum` or `startOverride`. It is figure `SEQ` fields, caption styles and Word field updates only.
- `scripts/postprocess_captions.py` is a wrapper over that; no numbering.
- The only other `w:numPr` touch in the whole app is `_center_plain` ([app/docx_report.py#L374-L384](app/docx_report.py#L374-L384)), which *strips* `w:numPr` from a scope-table placeholder cell.
- `scripts/compose_component_test.py` names `numbered_fragment.docx` as a component ([scripts/compose_component_test.py#L64-L76](scripts/compose_component_test.py#L64-L76)) but does no numbering work itself.

#### ⚠️ What I could not determine

**I could not unzip any DOCX.** No terminal tool is available in this session, and reading [resources/fragments/numbered_fragment.docx](resources/fragments/numbered_fragment.docx) returns raw deflate-compressed ZIP bytes.

So I have **not** read the literal XML of `numbered_fragment.docx` or [resources/MAIN_TEST.docx](resources/MAIN_TEST.docx), and I cannot tell you:

- MAIN_TEST.docx's count of `w:num` / `w:abstractNum` definitions;
- `numbered_fragment.docx`'s `w:start` value, `w:numFmt` value, `w:ilvl` value, or its source `w:numId`;
- the anchor ordering inside `resources/finding_types/*.docx` (relevant to §4).

What the code **requires** of those files, and which generation working proves is satisfied:

- the numbered fragment's paragraph carries `w:pPr/w:numPr/w:numId` — otherwise `_remap_numbering` finds nothing to rewrite and the list renders unnumbered;
- its numbering part defines a matching `w:num` → `w:abstractNum` — otherwise `_remap_numbering` raises (L249-252, L262-265);
- the level's `w:numFmt` is neither `bullet` nor `none` — otherwise no `startOverride` would be written (L323-325), and the pinned test above reads a real `startOverride` of `1`;
- MAIN_TEST.docx has a real numbering part — python-docx's `NumberingPart.new()` raises `NotImplementedError`, which `docx_import.numbering_formats` catches ([app/docx_import.py#L81-L84](app/docx_import.py#L81-L84)) but `_remap_numbering` does **not**.

**Verify the exact values by unzipping before relying on them.**

---

### 3. The editor side

#### How a numbered list renders

The `else if (fragment.items)` branch of `renderFragment`, [app/web/static/app.js#L2616-L2674](app/web/static/app.js#L2616-L2674).

- **One `<textarea class="list-textarea">` for the entire fragment**, not one field per item. Seeded at [app/web/static/app.js#L2628](app/web/static/app.js#L2628) by joining each item's run texts, flattening embedded newlines to spaces, and joining items with `\n`.
- `numbered` is decided once, at [app/web/static/app.js#L2621](app/web/static/app.js#L2621), from `fragment.type`.
- **The numbers are drawn in a separate gutter and never exist in the textarea.** `renderGutter` ([app/web/static/app.js#L2632-L2635](app/web/static/app.js#L2632-L2635)) resets `itemNumber = 0` and passes `line => line.trim() ? numbered ? \`${++itemNumber}.\` : "•" : ""` into `renderLineMarkers`.
- `renderLineMarkers` ([app/web/static/app.js#L203-L225](app/web/static/app.js#L203-L225)) copies the textarea's computed typography onto a hidden measure div, clears the gutter, and appends one height-matched `<span class="list-marker">` per textarea line. Blank lines get an empty marker and do not advance the counter.

**Would it need to change to show continued numbering? Yes, in two ways.**

1. `renderLineMarkers` has no concept of a starting offset — the counter lives in the caller's closure. Either it gains a seed parameter, or `itemNumber` is initialised from the preceding list. Note `renderLineMarkers` is **shared** with the scope page's bullet gutter ([app/web/static/app.js#L2049](app/web/static/app.js#L2049)), so a new required parameter touches that caller too.
2. `renderGutter` is re-run only by `resize()` and a per-textarea `ResizeObserver` ([app/web/static/app.js#L2666-L2673](app/web/static/app.js#L2666-L2673)). It is **not** re-run when a *different* fragment changes. Editing the first list would leave the second list's continued numbers stale until the pane re-renders.

#### The add-fragment menu and `allowed`

[app/web/static/app.js#L111](app/web/static/app.js#L111):

```js
const allowed = {
  description:               ["paragraph","numbered_list","bulleted_list","image","table","note","code_block"],
  recommended_remediation:   ["paragraph","numbered_list","bulleted_list","image","table","note","code_block"],
  previous_proof_of_concept: ["numbered_list","image","bulleted_list","instance_title","note","code_block"],
  proof_of_concept:          ["numbered_list","image","bulleted_list","instance_title","note","code_block"],
  in_conclusion:             ["paragraph","note"],
};
```

`numbered_list` is permitted in **all four** fragment-bearing sections. Only `in_conclusion` excludes it. This is **client-only**: `Content.fragments: list[Fragment]` ([app/models.py#L126-L128](app/models.py#L126-L128)) accepts any fragment type in any section, and `Report.validate_references` ([app/models.py#L317-L352](app/models.py#L317-L352)) does not constrain membership.

The menu itself ([app/web/static/app.js#L3386-L3402](app/web/static/app.js#L3386-L3402)) is a `<select>` rebuilt from `allowed[content.type]`; `onchange` calls `newFragment` and pushes. Only `image` gets post-creation initialisation (L3394-3398) — **that is the precedent for choosing a sensible default at add time.**

#### Per-fragment options UI — one precedent, and one of your two examples does not exist

**The image fragment's environment select is the only live precedent.** [app/web/static/app.js#L2450-L2468](app/web/static/app.js#L2450-L2468), inside `renderEvidenceTile`. It:

- collapses to a read-only `<span class="evidence-environment-value">` when exactly one environment applies and the fragment is not historical (L2452-2458);
- otherwise renders a `<select class="evidence-environment">`, with an `is-unset` modifier class and an extra placeholder option for historical images (L2461-2466);
- on change writes `fragment.environment` and calls **`rerender(); scheduleSave();`** (L2467).

The caption beside it is a plain `<input>` writing `fragment.caption` with `scheduleSave()` **only**, no rerender ([app/web/static/app.js#L2441-L2446](app/web/static/app.js#L2441-L2446)).

**The code block's caption is not a precedent — it has no UI at all.** `CodeFragment.caption` exists in the model ([app/models.py#L110-L114](app/models.py#L110-L114)), `newFragment` initialises it to `null` ([app/web/static/app.js#L2317](app/web/static/app.js#L2317)), the renderer prints it via `_render_caption_component` ([app/docx_report.py#L853](app/docx_report.py#L853)) and DOCX import restores it ([app/docx_import.py#L287-L294](app/docx_import.py#L287-L294)) — but `renderFragment`'s code-block branch renders **only the text area** ([app/web/static/app.js#L2768-L2786](app/web/static/app.js#L2768-L2786)). `TableFragment.caption` is in the same position: model and renderer, no editor.

The distinction that matters for your feature: **`environment` calls `rerender()`, `caption` does not.** A continue-numbering toggle changes a *sibling* fragment's visible numbers, so it belongs in the `rerender()` category.

---

### 4. Section boundaries

#### Order in the model

`provision` ([app/report_service.py#L192-L200](app/report_service.py#L192-L200)) rebuilds `contents` as `content_types_for_status(status)` order first, then carried unprinted sections appended. `content_types_for_status` ([app/report_service.py#L162-L166](app/report_service.py#L162-L166)):

- `open_new` → `["description", "recommended_remediation", "proof_of_concept"]`
- everything else → `["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"]`

#### Order in the document is **not** that list

`_render_finding_component` ([app/docx_report.py#L609-L665](app/docx_report.py#L609-L665)) builds an `anchors` dict at [#L639-L649](app/docx_report.py#L639-L649) mapping five anchor tokens to sections, then for each anchor calls `_render_component_content` and splices the result **in place of that anchor** via `_replace_component_anchor` ([app/docx_report.py#L1020-L1023](app/docx_report.py#L1020-L1023)).

So the printed order is whatever order the anchors sit in inside `resources/finding_types/new_finding.docx` / `retest_finding.docx` — **which I could not read** (§2). The headings `docx_import` expects back, in its own stated order, are `Description:`, `Recommended Remediation:`, `Previous Proof of Concept:`, `Proof of Concept:`, `In Conclusion:` ([app/docx_import.py#L37-L44](app/docx_import.py#L37-L44)).

#### Fragment iteration order

`_render_component_content` ([app/docx_report.py#L690-L739](app/docx_report.py#L690-L739)):

1. filter the section's fragments through `fragment_applies` (L695-699);
2. if nothing survives, render `N/A` from the paragraph component (L700-706);
3. otherwise walk `content.fragments` **in stored order** (L709-728), inserting an environment label before each new run of images when `label_images` is set;
4. trim trailing empty paragraphs (L730), tie tables to their lead-in (L731).

#### Can two sections' fragments end up adjacent?

**In the XML, yes.** Once the anchors are replaced, the last paragraph of one section's block and the first of the next are siblings in the body, separated only by whatever static heading paragraphs the finding template carries between the anchors.

**But a continuation still cannot happen by accident**, because continuation is `numId` identity, not adjacency — and every `ListFragment` gets its own `numId` (§2). The section boundary you want is enforced structurally today, for free.

The same holds across findings: `_populate_component_findings` ([app/docx_report.py#L504-L556](app/docx_report.py#L504-L556)) groups by `SEVERITY_ORDER` ([app/docx_report.py#L44](app/docx_report.py#L44)), sorts within a severity by case-folded title (L516-519), and forces a page break before every finding after the first (L531-538). Each finding is one `_render_finding_component` call, so no cache is shared across findings either.

**Conclusion for your rule:** "a PoC list may not continue the previous PoC's, and remediation may not continue description's" is **already the behaviour**. The feature is the opt-in exception *within* one section, and the natural definition of "the previous numbered list" is "the nearest preceding `numbered_list` in the same `content.fragments` array".

---

### 5. Invariants and twins

#### Confirmed twin pairs touching list fragments

| Rule | Python | JavaScript |
|---|---|---|
| seed a numbered list first in both PoC sections | `ensure_proof_steps` [#L155-L159](app/report_service.py#L155-L159) | `ensureProofSteps` [#L1199-L1201](app/web/static/app.js#L1199-L1201) |
| collapse **consecutive** numbered lists, never across another fragment | `merge_step_lists` [#L485-L497](app/report_service.py#L485-L497) | `mergeStepLists` [#L1207-L1219](app/web/static/app.js#L1207-L1219) |
| install library steps, replace or merge-append | `apply_poc_variant` [#L499-L518](app/report_service.py#L499-L518) | `applyPocVariant` [#L1221-L1232](app/web/static/app.js#L1221-L1232) |
| required seed fragments per section | `provision` / `required_fragments` [#L192-L215](app/report_service.py#L192-L215) | `provision` / `required` [#L1029-L1042](app/web/static/app.js#L1029-L1042) |
| which sections a status prints | `content_types_for_status` [#L162-L166](app/report_service.py#L162-L166) | `contentTypesForStatus`, used at [#L1030](app/web/static/app.js#L1030) |
| whether a section holds work (reads `items`) | `content_has_work` [#L169-L189](app/report_service.py#L169-L189) | `contentHasWork` [#L1022-L1028](app/web/static/app.js#L1022-L1028) |
| fresh ids on every copy | `apply_poc_variant`'s `model_copy(deep=True)` + reassignment; `assign_fresh_fragment_ids` [#L478-L483](app/report_service.py#L478-L483) | `remintFragments` [#L1204](app/web/static/app.js#L1204) |
| list-item readiness | `generation_issues` [app/docx_report.py#L126](app/docx_report.py#L126) | `fragmentIssues` [app/web/static/app.js#L2869-L2875](app/web/static/app.js#L2869-L2875) |
| a PoC always keeps one numbered list (delete guard) | **none** — the server just re-adds it on the next save | `deletionBlockedReason` [#L1189](app/web/static/app.js#L1189) |

#### ⚠️ Both-sides warning

The first four rows are genuine synchronous twins and **must move in pairs**.

`merge_step_lists`/`mergeStepLists` is the load-bearing one: merging two lists **deletes the second fragment**, and with it any flag it carried. If only one side learns about a `continue_numbering` flag, a library step install will behave differently depending on whether it ran in the browser (`applyPocVariant` at [app/web/static/app.js#L3293](app/web/static/app.js#L3293)) or on the server's auto-install path ([app/main.py#L738-L740](app/main.py#L738-L740)).

**None of these has a drift guard.** The only Python/JavaScript contract test is `tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues`, which compares generation readiness alone and reads no JavaScript constant.

#### What `generation_issues` says about list fragments

Exactly one thing, [app/docx_report.py#L126-L127](app/docx_report.py#L126-L127):

```python
elif isinstance(fragment, ListFragment) and any(not _runs_have_text(item.runs) for item in fragment.items):
    issues.append(f"{label}: {content.type} list item text is required")
```

No rule about count, order, position, or numbering. The JS twin ([app/web/static/app.js#L2869-L2875](app/web/static/app.js#L2869-L2875)) says the same but collapses PoC numbered lists into one message, `"Steps to reproduce requires text"`, because all items share one textarea.

**Neither side would notice a continue-numbering flag, and neither objects to two numbered lists in one section.**

#### What validates or normalises `items`

**Server:**
- `min_length=1` ([app/models.py#L84](app/models.py#L84)) is the only schema constraint.
- `load_path` repairs missing/empty `items` to `[{"runs": []}]` **and rewrites the file** ([app/workspace.py#L274-L280](app/workspace.py#L274-L280)).
- `merge_step_lists` drops blank items when merging ([app/report_service.py#L491-L493](app/report_service.py#L491-L493)).
- Nothing else on the server rewrites item text.

**Client (your understanding is correct):**
- `input.oninput` ([app/web/static/app.js#L2641-L2646](app/web/static/app.js#L2641-L2646)) rebuilds `fragment.items` from scratch on every keystroke — split on newlines, trim, drop blanks, fall back to `[{runs:[]}]`. This is why a list item cannot hold formatting, and why `conclusion_offer_resolved` stores step *text* rather than an id ([docs/DATA_MAP.md](docs/DATA_MAP.md) §6).
- `onpaste` ([app/web/static/app.js#L2650-L2664](app/web/static/app.js#L2650-L2664)) strips `LIST_MARKER_PREFIX` ([app/web/static/app.js#L163](app/web/static/app.js#L163)) per pasted line, is bracketed by `finalizeTextTransaction()` so it is one undo step, and defers the actual write to `oninput` — **`oninput` remains the only writer of `fragment.items`.** Client-only by decision, not omission ([docs/DATA_MAP.md](docs/DATA_MAP.md) §12).

---

### 6. Drafts on disk and the library

#### Drafts

Nine drafts under `data/apps/*/*/draft.json`. **32 `numbered_list` fragments across six of them**; the three in `data/apps/unnamed/` hold none.

| Draft | numbered lists | sections holding **more than one** |
|---|---|---|
| Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235 | 10 | **1** |
| Vuln_Library_QA_-_Merged_References/…c6ff01abda9e | 15 | 0 |
| Northstar_Banking/…0931592e4fdd | 2 | 0 |
| Northstar_Banking/2026-09_Report_84b9ebe1bbdd | 2 | 0 |
| Prompt_Reference/…5395baea9d23 | 2 | 0 |
| Image_Error_Probe/…8224ed05ecee | 1 | 0 |

**Exactly one section in the entire corpus holds two numbered lists**: the `proof_of_concept` beginning at line 851 of `data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json`. Its shape is `instance_title → numbered_list → image → instance_title → numbered_list → …`, i.e. "Instance 1: Production" steps, then "Instance 2: Non-Production" steps.

Two observations on that:

1. **It is exactly the shape the feature is for** — and exactly the shape `merge_step_lists` will not collapse, because an image and a title sit between the lists.
2. **One occurrence in nine drafts, in a file whose name says it is a coverage demo.** The reachable population today is a fixture, not tester data. That is a finding about demand, not feasibility: `allowed` offers `numbered_list` in four sections ([app/web/static/app.js#L111](app/web/static/app.js#L111)) and nothing stops a tester adding a second.

#### Library

[resources/vuln_library.json](resources/vuln_library.json) holds **24** `numbered_list` fragments, **all** inside `proof_of_concept`: 12 entries, each with exactly `web` and `api` (no `mobile`), each channel list holding **exactly one** list fragment — e.g. [#L74-L131](resources/vuln_library.json#L74-L131). **Zero** `numbered_list` inside any entry's `contents`.

So **no library channel list can ever supply two numbered lists.** A merge-append produces two only when the tester's existing section already had one, separated from the append point by another fragment.

#### Would a new field break an existing draft?

**No — and the reason cuts both ways.**

- **Adding `continue_numbering: bool = False` is backward-compatible on read.** Pydantic fills the default for all 32 fragments on disk that lack the key. `Report.validate_references` ([app/models.py#L317-L352](app/models.py#L317-L352)) says nothing about list fragments beyond `frag_id` uniqueness.
- **`load_path` needs no repair entry, and should not get one.** It reads the raw JSON, applies two named repairs, conditionally rewrites, then calls `Report.model_validate(draft)` ([app/workspace.py#L271-L299](app/workspace.py#L271-L299)). A model default is enough; a back-filling repair would only spend the single `draft.bak.json` to write a value the model already supplies.
- **The danger is the other direction.** Because no model sets `model_config`, Pydantic v2's `extra="ignore"` means a key present on disk but absent from the model is **silently dropped and gone on the next save**. If the flag ever ships and is later removed from `ListFragment`, it is deleted from every draft with no warning — the same trap [docs/DATA_MAP.md](docs/DATA_MAP.md) §6 records for `content_offer_resolved`.
- **Two client-side consequences, neither a break, both decisions:**
  - `normalizedSection` ([app/web/static/app.js#L1258-L1264](app/web/static/app.js#L1258-L1264)) enumerates fragment keys **explicitly**. A new field is not in that list, so toggling it would neither re-arm nor dismiss a library offer, and `sameFragments` would call a toggled section identical to the library's. Defensible, but not a default — it is a decision.
  - `diff` ([app/web/static/app.js#L532-L543](app/web/static/app.js#L532-L543)) and `reconcileCanonicalObject` ([app/web/static/app.js#L422-L471](app/web/static/app.js#L422-L471)) are **key-generic**, so undo/redo and canonical merge-back carry a new field with no change. `stableItemKey` ([app/web/static/app.js#L418-L421](app/web/static/app.js#L418-L421)) already keys fragments by `frag_id`.

---

### 7. DOCX import

**`app/docx_import.py` reads numbering, but only to tell bulleted from numbered. It reads nothing about starting values or continuation.**

- `numbering_formats` ([app/docx_import.py#L77-L97](app/docx_import.py#L77-L97)) builds `{numId: numFmt}` by resolving each `w:num` through its `w:abstractNumId` to the abstract's **first** `w:lvl`'s `w:numFmt`. Its docstring states why the id itself is untrustworthy: `_remap_numbering` reassigns ids on the way out, so a bulleted list written as `numId 30` can come back as `29`. Guarded against a missing numbering part by catching `AttributeError, KeyError, NotImplementedError` (L81-84).
- `classify_paragraph` ([app/docx_import.py#L110-L133](app/docx_import.py#L110-L133)) uses it once, at L120-L124: a paragraph with a `w:numPr` is `bulleted_list` if `formats.get(numId) == "bullet"`, otherwise `numbered_list`. **An unknown `numId` falls through to `numbered_list`.**
- **`w:startOverride`, `w:lvlOverride` and `w:ilvl` are read nowhere in the import path.** There is no notion of a list's starting number, and none of continuation.
- `_build_fragments` ([app/docx_import.py#L273-L279](app/docx_import.py#L273-L279)) groups **by adjacency and kind alone**: a list paragraph is appended to `fragments[-1]["items"]` if `fragments[-1]["type"] == kind`, otherwise it starts a new fragment. **`numId` is never compared.**

#### What happens if a tester imports a DOCX with a continued list

- **Two adjacent numbered lists** — whatever their `numId`s, and however Word numbered them on screen — come back as **one** `ListFragment`. The continuation is lost as a distinction because it was never a distinction in the draft model.
- **Two numbered lists separated by an image, note, title, code block or table** come back as **two** fragments, each with no flag. Re-generating restarts the second at `1.`, so the numbers in the regenerated document differ from the imported one.

That is a **pre-existing lossy round trip**, not something a new field creates. But it is the sharp edge for this feature: a `continue_numbering` flag would need import support to survive, and today's `classify_paragraph` discards the only available signal — `numId` identity across a fragment boundary — before `_build_fragments` ever sees it.

---

### 8. Map drift — corrected

**One error found, in [docs/DATA_MAP.md](docs/DATA_MAP.md) §7.** It read:

> **`merge_step_lists` then collapses every `numbered_list` into one**, because two list fragments each restart at `1.` in the generated document (`_remap_numbering` allocates a fresh `numId` per fragment and writes a `w:startOverride`).

The source contradicts it. `merge_step_lists` ([app/report_service.py#L485-L497](app/report_service.py#L485-L497)) collapses only **consecutive** numbered lists — a fragment of any other type between two lists is a boundary it will not cross. The map contradicted itself: its own §12 row already said "without crossing an intervening fragment", and `tests/test_browser.py::test_poc_add_below_does_not_cross_an_intervening_note` ([tests/test_browser.py#L1706-L1727](tests/test_browser.py#L1706-L1727)) pins that boundary.

**This matters directly to your plan.** The wrong version says a PoC can never hold two numbered lists after a library install, which would make the feature unreachable in the section it is most wanted. The right version says a second list survives whenever something separates it — which is precisely the one real occurrence on disk (§6).

I corrected that sentence, added the mechanism detail (`_render_component_fragment` opens the fresh `numbering_ids` cache; `_restart_numbering_levels` writes the `startOverride` back to the abstract level's `w:start`), noted that merging drops blank items, and recorded this verification pass in the "Last verified against source" line. No other drift found: §8's `load_path` list repair, §12's `required_fragments`/`required` parity, and §12's `merge_step_lists`/`mergeStepLists` row all match source.

Everything else in this report was read from source and is unchanged in the map.

---

## Round 1 - Planner: proposal and open questions

### Understanding

Add one opt-in flag to a numbered list fragment meaning "don't start at 1; carry on from the numbers of the nearest numbered list before me in this same section". Default off. The document must honour it. It must never reach across a content section, a finding, or the report — a Proof of Concept list can't continue the Previous Proof of Concept's, and Recommended Remediation can't continue Description's. That last rule already holds for free: continuation in Word is `numId` identity, and today every list fragment gets its own `numId` because [app/docx_report.py#L753-L765](app/docx_report.py#L753-L765) opens a fresh `numbering_ids` cache inside the `ListFragment` branch. So this change is not "stop lists continuing across sections" — it is "let two lists inside *one* section share a `numId` when, and only when, the tester asks".

---

### A. Blast radius

| File | What changes | Why |
|---|---|---|
| [app/models.py](app/models.py#L81-L84) | `ListFragment` gains `continue_numbering: bool = False` | the one place the field is declared; the default is what makes all 32 list fragments on disk load unchanged |
| [app/docx_report.py](app/docx_report.py#L690-L739) | `_render_component_content` holds a `numbering_carry` cache across the section's fragments; `_render_component_fragment` takes it as a keyword and uses it instead of its own `{}` | the renderer is the only thing that turns the flag into numbers |
| [app/docx_report.py](app/docx_report.py#L741-L765) | `_render_component_fragment` signature gains `numbering_ids: dict | None = None`; the `ListFragment` branch uses it when given | exactly one caller ([app/docx_report.py#L727](app/docx_report.py#L727)), so the signature change is contained |
| [app/web/static/app.js](app/web/static/app.js#L2317) | `newFragment` sets `continue_numbering: false` on both list types | so a freshly added list has the same shape before and after its first save |
| [app/web/static/app.js](app/web/static/app.js#L2616-L2674) | new `numberingOffset(fragment, content)` helper; `renderGutter` seeds its counter from it; `oninput` refreshes the gutters of downstream lists in the same chain | the JavaScript twin of the "which list is the previous one" rule, plus the staleness fix |
| [app/web/static/app.js](app/web/static/app.js#L2563) | the fragment head gains a `continue numbering` checkbox for numbered lists that have a preceding numbered list in the section | the control itself |
| [app/web/static/app.js](app/web/static/app.js#L1258-L1264) | `normalizedSection` includes the flag, conditionally | so a ticked section is not reported as identical to its library entry |
| [app/web/static/taste.css](app/web/static/taste.css#L2549) | one rule for the new head control | `taste.css` loads last, after `app.css` and `overrides.css`; head-item styling already lives there |
| [docs/DATA_MAP.md](docs/DATA_MAP.md) | §6 (new field + the `extra="ignore"` warning), §7 (the renderer sentence currently says two list fragments each restart at 1), §12 (new twin row), import note | required by the file's own maintenance contract |
| [tests/test_docx.py](tests/test_docx.py) | new numbering test | proves the DOCX half |
| [tests/test_app.py](tests/test_app.py) | new round-trip test | proves the schema half |
| [tests/test_browser.py](tests/test_browser.py) | three new tests | proves the editor half and the fingerprint |

**Not touched, deliberately:** `merge_step_lists` / `mergeStepLists`, `provision` / `ensure_proof_steps` and their twins, `docx_import.py`, `docx_components.py`, `library_editor.py`, `Report.validate_references`, `Workspace.load_path`. Each is justified below.

---

### C. Design decisions

#### 1. The field is a boolean, `continue_numbering: bool = False`, on `ListFragment`

Rejected: `continues_from: frag_id`. A pointer would need uniqueness and existence rules in `Report.validate_references` ([app/models.py#L317-L352](app/models.py#L317-L352)), a repair in `load_path` for when the target is deleted, and an answer for what happens when the target is dragged *below* it. A positional boolean has no target to orphan.

Rejected: `start_at: int`. The user asked to continue from the list above, not to start at a number. An explicit number goes wrong the instant the list above gains a line, and would need a resync rule on every keystroke.

Rejected: splitting `ListFragment` into two classes so the field can only exist on the numbered one. That rewrites the discriminated union and every `isinstance(fragment, ListFragment)` site, to prevent a key that is inert.

#### 2. "The previous numbered list" = the nearest preceding `numbered_list` in the same `content.fragments`, scanning past any number of other fragments

Not "immediately preceding". The oracle found the only real two-list section on disk is shaped `instance_title → numbered_list → image → instance_title → numbered_list`. Adjacency-only would make the feature unreachable in the exact shape it exists for. It would also be perverse, since `merge_step_lists` ([app/report_service.py#L485-L497](app/report_service.py#L485-L497)) is the app's own rule that two *adjacent* numbered lists should be one list.

- A `bulleted_list` in between is skipped like anything else. It has no numbers to consume.
- The scan stops at index 0 of `content.fragments`. That is the section rule the user asked for — it is a consequence of where the scan lives, not a separate check.
- Chains work: A (restart) → B (continue) → C (continue) numbers straight through. That falls out of the mechanism below without an accumulator.

#### 3. The DOCX shares one `numbering_ids` cache along a chain. No computed `startOverride`.

`_render_component_content` holds `numbering_carry`. For each fragment:

- numbered list, `continue_numbering` true, `numbering_carry` is not `None` → pass the existing cache
- numbered list, otherwise → `numbering_carry = {}`, pass that
- anything else → pass `None`, so `_render_component_fragment` makes its own fresh dict exactly as today, and **`numbering_carry` is left alone** — that is what lets a chain cross an image or an instance title

On a cache hit, `_remap_numbering` ([app/docx_components.py#L225-L284](app/docx_components.py#L225-L284)) reuses the allocated `numId` and never reaches `_restart_numbering_levels`, so no second `w:num`, no `w:lvlOverride`, no `w:startOverride`. Word continues the count across intervening paragraphs. **[app/docx_components.py](app/docx_components.py) is not edited at all** — fact 3's "decide which" is answered by not entering the branch rather than by changing it.

Why not a computed `w:startOverride` equal to the running count:

1. This pattern is already live and tested in two places — one cache per anchor in `compose_docx_template` ([app/docx_components.py#L145-L162](app/docx_components.py#L145-L162)), one per table cell in `_replace_token_with_bullets` ([app/docx_report.py#L577-L582](app/docx_report.py#L577-L582)). A computed override is new XML logic with no precedent.
2. An override would have to re-derive the renderer's "one clone per `ListItem`" rule in a second place, and go wrong the day that rule changes.
3. The filtering worry is moot either way: **a list fragment is never filtered out by `fragment_applies`.** That function reads `getattr(fragment, "environment", None)` ([app/report_service.py#L329-L340](app/report_service.py#L329-L340)) and `ListFragment` has no `environment` field ([app/models.py#L81-L84](app/models.py#L81-L84)), so it always returns `True`. The shared cache would nevertheless survive a future gate; a hard-coded start would not.
4. If the tester edits the finished DOCX and adds a step to the first list, Word renumbers the second automatically. A frozen `startOverride` would leave it wrong.

The cost is a new failure mode — `numId` leakage — handled in the risk table and pinned by a test.

#### 4. The editor shows the continued numbers

A toggle whose only effect is invisible until generation invites the tester to flip it twice to check. So the gutter shows `3. 4. 5.`

**`renderLineMarkers` is not changed.** It already takes `markerText` as a callback ([app/web/static/app.js#L203-L225](app/web/static/app.js#L203-L225)), so the counter stays in the caller's closure and only the seed changes — `let itemNumber = numberingOffset(fragment, content)` instead of `0`. The scope page's bullet gutter ([app/web/static/app.js#L2049](app/web/static/app.js#L2049)) is untouched. Fact 6's "new required parameter touches that caller too" does not apply.

**Staleness, without re-rendering the pane.** `input.oninput` already rewrites `fragment.items` on every keystroke. After it calls `changed()`, it also redraws the gutters of any *later* numbered list in the same content block that is in this chain. Each list's textarea carries its own `renderGutter` as a property, and `oninput` finds the following ones through the content block's DOM. That is a gutter repaint only — no DOM rebuild, no `render()`, no extra save, no focus loss. In every realistic case it is one extra list.

Deleting, moving, or dragging a fragment already goes through `rerender()`, which recomputes every offset from scratch.

**Known, accepted divergence:** the gutter does not number a blank line, but the renderer emits one numbered paragraph per `ListItem` including an empty one. A draft whose first list ends with an empty item would show the second list one lower in the editor than in Word. It cannot reach a generated document: `generation_issues` ([app/docx_report.py#L126-L127](app/docx_report.py#L126-L127)) blocks on any empty list item, and `allow_incomplete=True` is reachable only from [scripts/generate_report.py](scripts/generate_report.py#L30) and tests — [app/main.py#L518](app/main.py#L518) never passes it. Counted as non-blank in the editor, documented, no code.

#### 5. The toggle is a checkbox in the fragment head, shown only when it can act

The only live per-fragment control precedent is the image environment select ([app/web/static/app.js#L2450-L2468](app/web/static/app.js#L2450-L2468)), which sits in the tile body and calls `rerender(); scheduleSave();`. A list fragment's body *is* the gutter and textarea, so there is nowhere to put it there. It goes in the head, after `<span class="tag">numbered list</span>` ([app/web/static/app.js#L2563](app/web/static/app.js#L2563)), which already holds the move and delete buttons.

Label "Continue numbering", with a `title` that names what happens: *"Continues the list above — this list starts at 4."*

It calls `rerender(); scheduleSave();` — the environment-select category, not the caption category, because flipping it changes this list's visible numbers and, through chaining, every later list's.

**On the first list in a section: hidden, not disabled.** `ensure_proof_steps` guarantees every Proof of Concept opens with a numbered list, so a disabled control would sit greyed out on the single most common fragment in the app, explaining nothing. Hidden means it appears exactly when it has something to do.

**A flag that is true on a list that has moved to the top is kept, not cleared.** Both the renderer and the gutter fall back to starting at 1 when there is no preceding list, so nothing is corrupt; and if the tester drags it back down, their intent is still there. Clearing it would be a silent edit of their choice.

#### 6. Bulleted lists: the field exists on them and is ignored

**A list's type cannot be changed in the editor today** — there is no type switcher; `fragment.type` is written only by `newFragment`. The only routes from `numbered_list` to `bulleted_list` are hand-editing `draft.json` or a DOCX import classifying differently.

So: no validator forbids the key on a bulleted list, and nothing raises. The renderer only consults it inside the `numbered_list` arm, the editor only draws the control inside the `numbered` arm, and `numberingOffset` only counts `numbered_list` fragments. A stray `true` on a bulleted list is inert. Raising instead would demote a whole draft to the manager's legacy list over a cosmetic key.

#### 7. DOCX import does not learn this. The lossy round trip is accepted and documented.

`classify_paragraph` ([app/docx_import.py#L110-L133](app/docx_import.py#L110-L133)) already throws away `numId` before `_build_fragments` ([app/docx_import.py#L273-L279](app/docx_import.py#L273-L279)) can compare it, and `_build_fragments` groups by adjacency and kind alone. Teaching it continuation means changing how *every* imported list is grouped — a larger blast radius than this whole feature.

It is also the low-stakes half: `parse_report_docx` builds a **retest draft**, so the imported Proof of Concept lands in `previous_proof_of_concept` and a fresh empty one is created. The flag is lost in history the tester is about to supersede.

Concrete consequence to write down: import a report whose Proof of Concept had a continued list, regenerate it, and the second list restarts at 1. That is already true today for any pair of lists separated by another fragment. This is open question 3.

---

### B. Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| New field, existing drafts | **clear** | `continue_numbering: bool = False` — Pydantic fills the default for all 32 list fragments on disk. `validate_references` says nothing about lists beyond `frag_id` uniqueness. No `load_path` repair, and the oracle already established a back-filling one would burn the single `draft.bak.json` to write a value the model supplies. |
| Field removed later | **RISK, accepted, documented** | No model sets `model_config`, so `extra="ignore"` deletes an undeclared key from every draft on its next save — the trap [docs/DATA_MAP.md](docs/DATA_MAP.md) §6 already records for `content_offer_resolved`. Once shipped, the field is never deleted without a migration. Goes in §6 next to its sibling. |
| `merge_step_lists` destroying the flag | **RISK, narrow, accepted** | Three of four cases are already correct: survivor false + absorbed true produces one list numbered `1..n+m`, which is exactly what the two would have printed; survivor true is preserved and still continues from its own predecessor. The one real loss is **survivor true + absorbed false** — the tester's explicit "restart at 1" on the second list is silently replaced by continuation. Reachable only when a tester hand-builds two *adjacent* numbered lists, ticks continue on the first, and then accepts a library merge-append; the library can never supply the flag (`_steps_to_fragments` writes `frag_id`/`type`/`items` only, [app/library_editor.py#L27-L30](app/library_editor.py#L27-L30)), and `merge_step_lists` never runs from `provision`. **Decision: no guard.** A three-way condition reproduced by hand in two languages with no drift test costs more than the case. Say the word and I will add it to both sides with a test. |
| The list above is **deleted** | **RISK, low, silent by decision** | The continuing list falls back to 1 in both the document and the gutter — `numbering_carry` is `None`, `numberingOffset` returns 0. Numbers change without a prompt; no text is lost. `deletionBlockedReason` ([app/web/static/app.js#L1189](app/web/static/app.js#L1189)) already forbids deleting the only numbered list in a Proof of Concept. A confirmation dialog on every list delete would be worse than a number moving. |
| The list above is **moved** below it | **clear** | Same fallback, and the gutter updates on the `rerender()` that every move already triggers. |
| The list above is **emptied** | **clear** | `oninput` leaves `items` as `[{runs:[]}]`; the offset counts non-blank items, so the continuing list shows 1. In the document the report cannot generate at all while an item is blank. |
| The list above **becomes bulleted** | **clear** | Unreachable through the UI (no type switcher). If it happens via a hand edit, `numberingOffset` and the renderer both skip it and scan further back, or fall back to 1. |
| Python/JavaScript twins | **RISK, new twin, no drift guard** | "Which list is the previous one" now exists in `_render_component_content` and in `numberingOffset`. They are not the same code — Python shares a `numId`, JavaScript counts items — but they must agree on *which* list. Needs a row in [docs/DATA_MAP.md](docs/DATA_MAP.md) §12 and the paired tests in steps 2 and 3. |
| `numId` leaking across sections or findings | **RISK, the headline one** | If `numbering_carry` is ever hoisted out of `_render_component_content` into `_render_finding_component` ([app/docx_report.py#L650](app/docx_report.py#L650)) or `_populate_component_findings`, numbering runs on across sections and findings — silently, in the document only, where no test currently looks. Mitigated by keeping the variable local (one caller each, verified) plus an explicit assertion in step 2 that two sections' lists hold different `numId`s. |
| DOCX import round trip | **RISK, pre-existing, accepted** | Covered in decision 7. Nothing this change adds makes it worse; it makes an existing loss more visible. Open question 3. |
| `normalizedSection` | **RISK, mitigated** | The tuple at [app/web/static/app.js#L1258-L1264](app/web/static/app.js#L1258-L1264) enumerates keys explicitly, so a naive append changes the fingerprint of **every** section — invalidating every `content_offer_dismissed` on disk and re-showing dismissed banners once. Mitigated by a **conditional spread**: contribute the flag only when truthy, leaving the normalised string byte-identical for every draft written before this change. Pinned by the step 5 test. |
| Request/response asymmetry | **RISK, mitigated** | A list created client-side without the key is `undefined` locally and `false` after the round trip, which `diff` ([app/web/static/app.js#L532-L543](app/web/static/app.js#L532-L543)) and `reconcileCanonicalObject` would read as a change. `newFragment` sets it explicitly, for the same reason `code_block` sets `caption: null`. |
| Stale write / `saved_at` | **clear** | No new mutation endpoint. The toggle writes in memory and calls `scheduleSave()`, which uses the existing full PUT with `saved_at` in the body. No header path involved. |
| Lost update | **clear** | No new server read-then-write. Nothing outside `Workspace._locked`. |
| Orphan reference | **clear by design** | The flag names no id. This is the reason it is a boolean and not a `frag_id` pointer. |
| Silent stranding | **clear** | The flag gates no location, environment, or scope. No finding can be left with nothing. |
| Navigation trap | **clear** | `generation_issues` gains no rule, `finding_is_complete` is untouched, no page gate reads the field. |
| Derived-state fight | **clear** | Nothing server-side writes `continue_numbering`. `provision` only creates fragments into an empty section and reads `type`; `ensure_proof_steps` only inserts when no numbered list exists; `sync_evidence_image_slots` touches images. `apply_poc_variant` in `replace` mode discards non-image fragments including their flags — that is the documented meaning of replace, not a regression. |
| Backup exhaustion | **clear** | `scheduleSave()` is debounced through `queueBackendSave` ([app/web/static/app.js#L711](app/web/static/app.js#L711)); one toggle is one eventual write, and the gutter refresh writes nothing. |
| Undo / recovery | **clear** | `diff` and `reconcileCanonicalObject` are key-generic and `stableItemKey` keys fragments by `frag_id`, so the toggle is one undo step for free. `remintFragments` uses `JSON.parse(JSON.stringify(...))` and copies the flag on every library copy. |

---

### D. Open questions

Three decisions are waiting. Here is the first; I will bring the other two — **how the editor shows it** and **whether re-importing a document should keep it** — once this one is settled.

#### 1. How much of this should the editor show you?

**Background.** The flag itself and the document half are small and certain. The expensive half is making the editor's left-hand number column show the continued numbers live — so a second list under a screenshot reads `3. 4. 5.` while you type in it, and jumps to `4. 5. 6.` the moment you add a line to the list above. That needs a small amount of extra plumbing: each list has to know how many items the list above it currently holds, and typing in one list has to quietly repaint the number column of the one below without disturbing what you are doing.

One more thing to weigh: right now the shape this feature is for exists exactly **once** across your nine saved reports — a Proof of Concept in `Fragment_Coverage_Demo` with two sets of steps separated by a screenshot and a title. The saved vulnerability library can never produce two numbered lists in one section, so today this is something you would reach for deliberately, not something that happens to you.

**The options.**

- **Full version.** A "Continue numbering" tickbox on the second and later lists in a section, and the number column shows the real continued numbers as you type. You see the finished numbering before you generate. Four code steps.
- **Minimal version.** The same tickbox, but the number column of a continuing list still counts from 1 and the card shows a small line of text instead — "Continues the list above; prints as 4, 5, 6." The correct numbers appear only in the generated document. Two code steps, and no risk of the editor and Word disagreeing, because the editor never claims a number.

**Tradeoffs.** The full version is what you would expect from a word processor and needs no trust. The minimal version is faster to build and cannot ever show a number that the document then contradicts — but it asks you to believe a sentence instead of seeing the result, and the one place the two can legitimately disagree (a list whose last line is blank) is already blocked from generating.

**My recommendation: the full version.** A tickbox whose effect you cannot see until you generate is a tickbox people flip twice to check, and the plumbing is genuinely modest — the number column already draws its markers through a callback, so the only new thing is a seed value and a repaint of the list below.

---

### E. Plan

Each step leaves the app saveable and generating.

**Step 1 — the field.**
Files: [app/models.py](app/models.py#L81-L84) (`ListFragment.continue_numbering: bool = False`), [app/web/static/app.js](app/web/static/app.js#L2317) (`newFragment` sets it explicitly on both list types).
Test: `tests/test_app.py` — a `draft.json` whose list fragments have no `continue_numbering` key loads, and re-serialises with `false`; a draft that has it `true` keeps it across a save.
Invariant: every draft currently on disk still validates, and a client-made list has the same shape before and after its first round trip.

**Step 2 — the document.**
Files: [app/docx_report.py](app/docx_report.py#L690-L765) only. `_render_component_content` owns `numbering_carry`; `_render_component_fragment` takes `numbering_ids: dict | None = None`. [app/docx_components.py](app/docx_components.py) unchanged.
Test: `tests/test_docx.py`, alongside the existing fragment-render tests. One finding whose Proof of Concept is `numbered_list(2) → image → numbered_list(2, continue)`. Assert, via the same `w:num` / `w:abstractNum` reading the component tests use: all four list paragraphs share one `numId`, exactly one `w:startOverride` of 1 exists for it, and the Description section's own list carries a **different** `numId`. A control case with `continue_numbering=False` asserts two `numId`s and two overrides — the behaviour [tests/test_docx_components.py#L129-L148](tests/test_docx_components.py#L129-L148) already pins.
Invariant: **no `numId` is shared by two content sections or two findings.**

**Step 3 — the gutter.**
Files: [app/web/static/app.js](app/web/static/app.js#L2616-L2674) — `numberingOffset`, the seed in `renderGutter`, the downstream repaint in `oninput`. `renderLineMarkers` untouched.
Test: `tests/test_browser.py`, near [tests/test_browser.py#L2359](tests/test_browser.py#L2359). Build the two-list shape with the flag set in the seeded draft; assert the second gutter's first `.list-marker` reads `3.`; type a line into the first list; assert the second gutter reads `4.` and that focus and caret position in the **first** textarea are unchanged.
Invariant: a keystroke in one list never rebuilds the pane or moves the caret.

**Step 4 — the toggle.**
Files: [app/web/static/app.js](app/web/static/app.js#L2563) (the head control), [app/web/static/taste.css](app/web/static/taste.css#L2549) (one rule).
Test: `tests/test_browser.py` — the control is absent on the first numbered list of a section and present on the second; ticking it changes the gutter and survives a reload.
Invariant: the control never appears where there is no preceding numbered list to continue.

**Step 5 — the fingerprint.**
Files: [app/web/static/app.js](app/web/static/app.js#L1258-L1264) — conditional contribution in `normalizedSection`.
Test: `tests/test_browser.py` — a seeded draft carrying a `content_offer_dismissed` value **computed by today's code** still shows no `.content-offer` banner for that section. A one-time pin with a literal hash, commented as such.
Invariant: shipping this does not resurrect a single dismissed library banner.

**Step 6 — the map.**
Files: [docs/DATA_MAP.md](docs/DATA_MAP.md) §6, §7, §12.
Test: none. Required by the file's own maintenance contract, which names `app/models.py` and `app/report_service.py` explicitly.
Invariant: §7's claim that "two list fragments each restart at 1" is corrected to "unless the second asks to continue", so the next reader is not misled the way the `merge_step_lists` sentence misled this round.

Order rationale: the model before the renderer, because the renderer reads the field. The renderer before the editor, so the editor is never showing a number the document would not print. The toggle after the gutter, so the first tick has a visible effect. The fingerprint last among the code steps — it is independent, and its test is the most brittle thing here.

---

### What I would not do

**Compute and write a `w:startOverride` equal to the running item count.** It looks more explicit and it is the obvious reading of "make it start at 4". It is the wrong choice: it duplicates the renderer's own item-counting rule in a second place where nothing will keep them in step, it freezes the number so that editing the finished DOCX by hand produces a document Word will not renumber, and it adds new XML-writing code when a cache-sharing pattern that already ships in two places does the same job by *not* entering a branch.

**Make `merge_step_lists` flag-aware to protect the one lossy case.** Tempting, because it is a silent overwrite of an explicit tester choice. Rejected because the guard is a three-way condition that must be reproduced byte-for-byte in `mergeStepLists` with no drift test — and the twin table in §12 records that none of these pairs has one — to protect a shape that needs a tester to hand-build two adjacent numbered lists, tick continue on the first, and then accept a library merge-append. It is listed as a RISK rather than buried, and it is one clause away if you want it.

**Add a `load_path` repair back-filling `continue_numbering: false`.** A model default already does it, and a repair would rewrite the file and spend the single `draft.bak.json` to write a value nothing was missing — the same reasoning §6 already gives for `content_offer_dismissed`.

**Teach `docx_import` to read `numId` identity now.** It is the honest fix for the round trip, but it changes how every imported list is grouped, which is a bigger and riskier change than the feature that exposed it. It belongs in its own plan, on its own tests.

Next action: answer open question 1 — full version or minimal version.

## Round 2 - Oracle: verdict on the proposal

> **Coordinator correction.** The oracle opens by saying my DOCX note was missing from this file.
> It was right: my splice had silently no-op'd because I rewrote the heading levels before
> anchoring on them. The note is now in Round 1 above, and it confirms rather than contradicts
> anything below.

### 1. Risk rows, graded

| Planner's row | Verdict | Evidence |
|---|---|---|
| New field, existing drafts — *clear* | **CONFIRMED** | [app/models.py](app/models.py#L81-L84) declares three fields, no `model_config` anywhere in the file (one grep hit, a comment at [L133](app/models.py#L133)). Pydantic v2 default applies. |
| Field removed later — *RISK accepted* | **CONFIRMED** | Same absence of `model_config` ⇒ `extra="ignore"`. The trap is real and identical to `content_offer_resolved`. |
| `merge_step_lists` four cases — *RISK narrow* | **CONFIRMED, with two refinements** | see below |
| The list above is **deleted** — *RISK low* | **WRONG as reasoned** | see below |
| The list above is **moved** — *clear* | **CONFIRMED** | `moveFragment` and `ondrop` both call `rerender(); scheduleSave();` — [app/web/static/app.js](app/web/static/app.js#L2573-L2586), [app.js](app/web/static/app.js#L2600-L2611). |
| The list above is **emptied** — *clear* | **CONFIRMED** | `oninput` writes `(lines.length ? lines : [""]).map(...)` — [app.js](app/web/static/app.js#L2641-L2646). |
| The list above **becomes bulleted** — *clear* | **CONFIRMED** | No `fragment.type =` assignment exists in app.js; all 17 `.type =` hits are DOM (`input.type`, `button.type`). |
| Python/JS twins — *RISK* | **CONFIRMED** | New rule genuinely lives in two languages with no drift guard. |
| `numId` leaking — *RISK headline* | **CONFIRMED as a risk, WRONG as mitigated** | see below |
| DOCX import round trip — *accepted* | **CONFIRMED** | `classify_paragraph` discards `numId`; `_build_fragments` groups by adjacency+kind. Sharing a `numId` does not change either, since both lists still resolve to a decimal format and are still separated by an image. |
| `normalizedSection` — *mitigated* | **CONFIRMED mechanically, UNDERSTATED in consequence** | see below |
| Request/response asymmetry — *mitigated* | **CONFIRMED** | `newFragment` sets `caption:null` for `code_block` — [app.js](app/web/static/app.js#L2317). Precedent is real. |
| Stale write / lost update / orphan / stranding / nav trap / backup | **CONFIRMED** | No new endpoint, no id, no gate. |
| Derived-state fight — *`apply_poc_variant` replace discards flags* | **CONFIRMED** | `kept = [...] if mode == "merge" else []`, then `proof.fragments = merge_step_lists(kept + copied) + images` — [app/report_service.py](app/report_service.py#L505-L510). |
| Undo / recovery — *clear* | **CONFIRMED, and stronger than claimed** | `restoreHistory` ends in `window.location.reload()` — [app.js](app/web/static/app.js#L588-L592). Undo cannot leave a stale gutter, because the page is rebuilt. |

#### The central mechanism — CONFIRMED

`_remap_numbering` puts *everything* behind `if target_numbering_id is None:` — the `w:num`/`w:abstractNum` lookup, `_next_numbering_id`, the deep copies, `_assign_unique_numbering_identity`, **`_restart_numbering_levels`**, and both insertions. On a hit, the only statement that runs is the last line, `numbering_id_element.set(qn("w:val"), str(target_numbering_id))` — [app/docx_components.py](app/docx_components.py#L225-L284). No second `w:num`, no `w:lvlOverride`, no `w:startOverride`. Exactly as claimed.

**Nothing later resets it.** The only other `w:numPr` touch in the app is `_center_plain` ([app/docx_report.py](app/docx_report.py#L374-L383)), which strips `w:numPr` from a *scope table cell* and runs in `_populate_scope_tables`, before `_populate_component_findings` ([app/docx_report.py](app/docx_report.py#L166-L176)). `add_native_image_captions` contains no numbering code (grep for `numPr|numId|startOverride|abstractNum` hits only docx_components.py, docx_import.py, and docx_report.py:380).

**And I closed two of my round-1 DOCX gaps without a terminal.** [tests/test_docx_components.py](tests/test_docx_components.py#L266-L286) reads `w:startOverride` at `w:ilvl="0"` and [L143-L147](tests/test_docx_components.py#L143-L147) asserts it equals `1` for every paragraph. That is only reachable if `numbered_fragment.docx`'s cloned paragraph resolves to level 0 and its abstract level 0 carries `w:start="1"`. Both inferences are now evidenced. What remains unverified is only Word's on-screen rendering, which no test in this repo observes.

#### Threading claim — CONFIRMED, but the planner's *reason* is the wrong test

`_render_component_fragment` has exactly one caller ([app/docx_report.py](app/docx_report.py#L727-L734)). `_render_component_content` also has exactly one ([app/docx_report.py](app/docx_report.py#L650-L659)), inside the five-anchor loop of `_render_finding_component`.

But **caller count is irrelevant to leakage.** A `numbering_carry` declared inside the function body is re-initialised on every call no matter how many callers exist. The failure mode that would actually leak across sections and findings is a mutable default argument — `def _render_component_fragment(..., numbering_ids: dict = {})` — which in Python is created once at definition time and would silently join every list in the entire report. The planner's proposed signature, `numbering_ids: dict | None = None` with `clone_component_elements` already doing `numbering_ids if numbering_ids is not None else {}` ([app/docx_components.py](app/docx_components.py#L60-L67)), avoids exactly that. Right answer, wrong justification — and the justification is what a future reader will copy.

#### `merge_step_lists` — CONFIRMED, two refinements

The survivor is `merged[-1]`, always an element already appended, so **always the earlier fragment** ([app/report_service.py](app/report_service.py#L485-L496)). Stronger than the planner says: in a run of three adjacent lists A→B→C, B merges into A and then C also sees `merged[-1] == A`, so the survivor is the **earliest of the whole run**, not the immediately preceding one. The four-case analysis holds; only survivor-true + absorbed-false loses intent.

**The sub-claim "the library can never supply the flag" is too strong.** `_steps_to_fragments` writing only `frag_id`/`type`/`items` is **CONFIRMED** ([app/library_editor.py](app/library_editor.py#L27-L30)) — but that is the library *editor*'s writer, and the editor is untracked and opt-in. `main.insert_library` parses raw library dicts through the model: `Content(type="proof_of_concept", fragments=steps).fragments` ([app/main.py](app/main.py#L740)). A hand-edited `resources/vuln_library.json` carrying `continue_numbering: true` would be accepted and installed. The correct claim is "the library editor never writes it", not "the library can never supply it".

#### "The list above is deleted" — WRONG as reasoned

`deletionBlockedReason` does forbid deleting the only numbered list in a Proof of Concept — **CONFIRMED** ([app/web/static/app.js](app/web/static/app.js#L1182-L1196)) — and in fact covers both PoC sections, because the gate is `content.type.endsWith("proof_of_concept")`.

But it gives **no protection at all** in `description` or `recommended_remediation`. There the only guard is `requiresFragment`, which blocks deletion solely when the section is down to its **last fragment of any kind**. Since `allowed` offers `numbered_list` in all four sections ([app.js](app/web/static/app.js#L111)), the feature is fully reachable in two sections where the cited guard does nothing. The row's "low" rating rests on a guard that covers half the surface.

#### `normalizedSection` — CONFIRMED mechanically, understated in consequence

The current function maps each fragment to a **fixed-length 10-element array** ([app.js](app/web/static/app.js#L1258-L1267)). Because it is an array and not an object, a conditional contribution genuinely leaves `JSON.stringify` **byte-identical** when the flag is falsy — for both `undefined` (client-made, pre-save) and `false` (server round-tripped). Confirmed.

What the planner does not say out loud: `sameFragments` compares the tester's section against the **library entry's** fragments, and library fragments will never carry the flag. So ticking the box in a section that currently matches its library entry makes it stop matching — which **re-shows that section's library banner**. The planner presents that as the goal ("so a ticked section is not reported as identical"), but it is also a visible side-effect of the tick, and it is not in the risk table.

---

### 2. What the planner missed

**a. `app/docx_components.py` untouched is sufficient — but the cited proof is the wrong test.** The planner's step 2 says a `continue_numbering=False` control case asserts "two `numId`s and two overrides — the behaviour tests/test_docx_components.py#L129-L148 already pins." **It does not.** That test calls `compose_docx_template` ([tests/test_docx_components.py](tests/test_docx_components.py#L56-L108)), which `render_report_docx` never calls, and its two numbered groups differ only because they sit at **two different anchors** (`prev-poc-fragments-here` and `poc-fragments-here`), each with its own per-anchor cache. **There is currently no test anywhere pinning that two list fragments inside one section restart independently.** Step 2's control case is new coverage, not a re-assertion.

The same test is, however, **direct evidence for the proposal**: five separately-cloned `numbered_fragment.docx` groups behind one anchor share one cache and are asserted to share one `numId`, one `nsid`, and exactly one `startOverride` of `1` ([tests/test_docx_components.py](tests/test_docx_components.py#L133-L149)). The "same `numId` across separately-cloned element groups" case is already shipping and already pinned. Nothing in the clone path breaks.

**b. One latent assumption in the clone path, harmless today.** `_restart_numbering_levels(number, source_abstract, elements, source_numbering_id)` is called with `elements` = only the **first** clone group ([app/docx_components.py](app/docx_components.py#L277)), so the `w:ilvl` set it writes overrides for is derived from that group alone. If a later fragment in a chain ever used a different level, it would get no override. Every clone comes from the same file today, so this cannot bite — but it is a real "one clone group per `numId`" assumption, and the proposal widens the distance between the group that defines the levels and the groups that use them.

**c. A continued chain also shares its `nsid`.** `_assign_unique_numbering_identity` runs once per cache miss ([app/docx_components.py](app/docx_components.py#L288-L303)), so the two lists in a chain share `numId` *and* `nsid`. Any future assertion of the `tests/test_docx_components.py` shape — "two lists differ in both" — is false for a continued chain by design.

**d. No memoisation anywhere that matters.** The only `lru_cache` in the render path is `_cached_image_fragment_format` ([app/docx_report.py](app/docx_report.py#L1137)), images only. `clone_component_elements` re-opens `Document(component_path)` on **every single call** ([app/docx_components.py](app/docx_components.py#L44-L67)), so the component document is fresh per list item and `numbering_ids` is genuinely the only carrier. The planner's account is right.

**e. Existing tests: none break, but two come close.**
- [tests/test_browser.py](tests/test_browser.py#L1426-L1430) asserts the **exact** child list of `.fragment-head`: `["fragment-drag-handle", "tag", "toolbar", "fragment-move-up", "fragment-move-down", "danger fragment-delete"]`. It targets `.fragment` filtered by `has=.toolbar`, i.e. a paragraph/note card, so a list-only control does not break it. Add the control to *all* fragment heads and this test fails.
- [tests/test_browser.py](tests/test_browser.py#L1671-L1682) adds a **second** numbered list to a PoC and counts cards — that is precisely where the new control appears. It passes, because it only queries `button.danger`.
- [tests/test_browser.py](tests/test_browser.py#L2359-L2397) asserts `["1.", "", "2.", "3."]` on a Description list. Only one numbered list is present, so the offset is 0 and the assertion is unchanged — and it also **confirms the gutter skips blank lines and does not advance the counter**.
- No test anywhere counts `w:num` elements or asserts `numId` uniqueness outside test_docx_components.py.

**f. "One CSS rule" is optimistic.** Three groups in [app/web/static/taste.css](app/web/static/taste.css#L2549-L2601) govern that row and none would include a new child: the height normaliser at [L2558-L2566](app/web/static/taste.css#L2558-L2566) (whose own comment is "so Delete stops setting the row's height on its own" — an unsized label will do exactly that); the 20px square rule at [L3149-L3157](app/web/static/taste.css#L3149-L3157), which would crush any `<button>` form of the control; and the fade-until-engaged group at [L2585-L2601](app/web/static/taste.css#L2585-L2601), leaving the checkbox the only permanently-opaque item in a row designed to recede. The good news: `.fragment-head .fragment-move-up { margin-left: auto; }` ([L2553](app/web/static/taste.css#L2553)) is what pins everything rightward, so an insert after `.tag` does land on the left as intended.

**g. Tab order gains a stop.** Drag and both move buttons are `tabIndex = -1`; the delete button is not, so the head already contributes one tab stop before the field ([app.js](app/web/static/app.js#L2589-L2591)). A checkbox adds a second, ahead of the textarea. No test asserts tab order — the sole `activeElement` assertion ([tests/test_browser.py](tests/test_browser.py#L1038)) is about the findings-page ID field.

**h. `renderGutter` is a closure, not a property.** [app.js](app/web/static/app.js#L2632-L2635) declares it inside the `fragment.items` branch and never attaches it to the textarea. The planner writes "each list's textarea carries its own `renderGutter` as a property" as though it already does. It is a new assignment, not an existing affordance. Paste is covered for free (`onpaste` defers to `input.oninput()`, [app.js](app/web/static/app.js#L2650-L2664)), and undo needs nothing (item **d** above).

**i. Step 5's literal hash — brittle in three specific ways.** `sectionFingerprint` is `${text.length}-${FNV1a32(text).toString(16)}` over `normalizedSection` ([app.js](app/web/static/app.js#L1270-L1279)). It *is* deterministic — arrays not objects, so no key-order dependence, and `charCodeAt` is stable. The brittleness is elsewhere: (1) the literal is only meaningful if computed with **pre-change** code, and nothing in the test can enforce that — computed after, it is a tautology that passes no matter what; (2) the tuple has grown before (`generated` is in it), so the next legitimate addition invalidates the literal and the failure will read as though this feature regressed; (3) the assertion is a UI **absence** (`.content-offer` count 0), which passes for unrelated reasons — a finding with no `library_ref` shows no banner either — so it can rot into a test that proves nothing while still being green.

---

### 3. Does the shape break any existing `draft.json`?

**No — CONFIRMED, no migration needed.** `continue_numbering: bool = False` is filled by Pydantic for every list fragment on disk. `Report.validate_references` constrains nothing about lists beyond `frag_id` uniqueness. `Workspace.load_path` needs no repair entry.

**The one real two-list section behaves sensibly.** [data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json](data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json#L851-L945) is `proof_of_concept` → `instance_title, numbered_list, image, instance_title, numbered_list, image, note`. Both lists load with the flag false, so `numbering_carry` is reset at each one and each gets its own `numId` + `startOverride` of 1 — **byte-identical output to today**, and the gutters read `1.` in both. That is also the correct default for this draft: the two lists are "Instance 1" and "Instance 2", two independent procedures that *should* restart. The feature stays opt-in, and this is the shape it is opt-in *for*.

I also confirmed the cross-section rule is structural, not a new check: `anchors` maps five tokens to five distinct `Content` objects and calls `_render_component_content` once per anchor ([app/docx_report.py](app/docx_report.py#L639-L659)), so a function-local carry can never span Description→Remediation or PreviousPoC→PoC.

---

### The three "Also" items

- **`renderLineMarkers` needs no change — CONFIRMED.** Its fourth parameter is `markerText`, invoked as `markerText(line)` per line ([app.js](app/web/static/app.js#L203-L225)); the counter lives in the caller's closure at [L2632-L2635](app/web/static/app.js#L2632-L2635). Seeding `let itemNumber = numberingOffset(...)` instead of `0` is sufficient, and the scope-page caller at [L2049](app/web/static/app.js#L2049) is untouched. This is not a contradiction of my round-1 report so much as the planner taking the second of the two options I listed.
- **No type switcher — CONFIRMED.** No assignment to `fragment.type` exists anywhere in app.js.
- **`remintFragments` uses `JSON.parse(JSON.stringify(...))` — CONFIRMED** ([app.js](app/web/static/app.js#L1204)). A new key rides along for free.

---

### Invariants in play

- **One `numId` per list fragment** (today, via the fresh cache at [app/docx_report.py](app/docx_report.py#L753-L765)). Violating it *deliberately and locally* is the feature; violating it by hoisting the carry, or by a `dict = {}` default argument, silently renumbers a whole report with no test watching.
- **`numbering_carry` must be created inside `_render_component_content`'s body.** Not a module global, not a default argument. This is what enforces the section boundary the user asked for.
- **`generation_issues` blocks any blank list item** ([app/docx_report.py](app/docx_report.py#L126-L127)), and `render_report_docx` is called from [app/main.py](app/main.py#L518) with no `allow_incomplete` — the only `True` callers are [scripts/generate_report.py](scripts/generate_report.py#L26) and tests. **CONFIRMED**: the editor/renderer blank-item divergence cannot reach a shipped document. One caveat the planner did not note — `generation_issues` skips sections this status does not print (`if content.type not in printed: continue`), which is safe only because `anchors` renders exactly that same set.

### Both-sides warning

Every rule this feature touches is already a twin and would gain a new one:

- `merge_step_lists` ([app/report_service.py](app/report_service.py#L485-L496)) ↔ `mergeStepLists` ([app.js](app/web/static/app.js#L1207-L1219))
- `apply_poc_variant` ([app/report_service.py](app/report_service.py#L499-L518)) ↔ `applyPocVariant` ([app.js](app/web/static/app.js#L1221-L1232))
- **New:** "which list is the previous one" would exist in `_render_component_content` and in `numberingOffset`. Python shares a `numId`; JavaScript counts items. They must agree on *which* list or the editor shows a number the document contradicts, and there is no drift guard for any pair in this table.

### Map drift

**None.** [docs/DATA_MAP.md](docs/DATA_MAP.md#L191) §7 now reads correctly against source — the *consecutive*-only wording, the `_render_component_fragment` fresh-cache mechanism, `_restart_numbering_levels` writing `w:startOverride` from the abstract's `w:start`, and the blank-item drop on merge all match. §12's twin rows and §8's `load_path` list repair also match. No edit made.

## Round 2 - Planner: revised plan

### Understanding

Add one opt-in flag to a numbered list fragment meaning "don't start at 1; carry on from the numbers of the nearest numbered list before me in this same section". Default off. The document honours it by letting the two lists share one `numId`, which is what Word treats as one continuing list. It can never reach across a content section, a finding, or the report, because the cache that carries the shared `numId` is a variable local to one call of `_render_component_content`, and that function is called once per anchor per finding. So this change is not "stop lists continuing across sections" — that already holds structurally. It is "let two lists inside *one* section share a `numId` when, and only when, the tester asks".

### What changed since Round 1

Eight corrections, one of which reverses a decision:

| Round 1 said | Round 2 says |
|---|---|
| Step 2's control case re-asserts pinned behaviour | It is **new coverage**. Nothing anywhere pins that two lists in one section restart independently |
| Threading is safe because there is one caller | Caller count is irrelevant. It is safe because the parameter is `dict \| None = None`, not `dict = {}` |
| "Delete the list above" is low risk, guarded | **Re-rated.** The cited guard covers only the two proof-of-concept sections; Description and Remediation have none |
| The library can never supply the flag | The library **editor** never writes it. A hand-edited library file can, through `main.insert_library` |
| `normalizedSection` gains a conditional contribution | **Reversed.** It is not touched at all — see decision 8 |
| Step 5 pins the fingerprint with a literal hash | Replaced with a behavioural test that needs no constant |
| One CSS rule | Three existing groups plus the control's own rule |
| The textarea carries `renderGutter` as a property | It does not. That is a new assignment this plan must specify |

### Demand, stated plainly

The oracle counted the shape this feature serves: **exactly one section across all nine saved reports holds two numbered lists**, and it is in a file named `Fragment_Coverage_Demo`. The library editor can never produce two lists in one section. So nobody is hitting this by accident — it is something a tester would reach for deliberately, or never.

That cuts two ways, and both change this plan:

- **It lowers the priority and caps the budget.** This should not become a large change, and it must not alter a single byte of output for the drafts that exist. That makes step 2's control case the most valuable test in the plan, not the least.
- **It does not argue for dropping the feature, because there is no workaround today.** A tester who wants `4. 5. 6.` on their second list has no route to it: typing `4.` into an item renders as `1. 4.` in Word, and pasting a pre-numbered list has its numbers stripped by `onpaste`. The option either exists or the outcome is unreachable.

If the answer to open question 1 is the minimal version, this is a two-step change. If it is the full version, it is four. Either is proportionate. What would not be proportionate is teaching DOCX import to preserve it (decision 7).

---

### A. Blast radius

| File | What changes | Why |
|---|---|---|
| [app/models.py#L81-L84](app/models.py#L81-L84) | `ListFragment` gains `continue_numbering: bool = False` | the one place the field is declared; the default is what makes all 32 list fragments on disk load unchanged |
| [app/docx_report.py#L690-L739](app/docx_report.py#L690-L739) | `_render_component_content` declares `numbering_carry` **in its body** and threads it per fragment | the section boundary is enforced by where this variable lives |
| [app/docx_report.py#L741-L765](app/docx_report.py#L741-L765) | `_render_component_fragment` gains `numbering_ids: dict \| None = None`; the `ListFragment` branch uses it when given | `clone_component_elements` already does `numbering_ids if numbering_ids is not None else {}` ([app/docx_components.py#L60-L67](app/docx_components.py#L60-L67)) |
| [app/web/static/app.js#L2317](app/web/static/app.js#L2317) | `newFragment` sets `continue_numbering: false` in the `type.endsWith("list")` branch | both list types, so a client-made fragment has the same shape before and after its first round trip |
| [app/web/static/app.js#L2616-L2674](app/web/static/app.js#L2616-L2674) | new `numberingOffset(fragment, content)`; `renderGutter` seeds from it; **new** `input.renderGutter = renderGutter`; `oninput` repaints the chain below | the JavaScript twin of "which list is the previous one", plus the staleness fix |
| [app/web/static/app.js#L2563](app/web/static/app.js#L2563) | the control, inserted after `.tag` **from inside the `fragment.items` branch** | same insertion point and same pattern as the rich-text toolbar; keeps every other fragment head untouched |
| [app/web/static/taste.css](app/web/static/taste.css#L2549-L2601) | the height normaliser, the fade group, an opacity exception for the ticked state, and the control's own rule | four rules, not one — see decision 5 |
| [docs/DATA_MAP.md](docs/DATA_MAP.md) | §6 new field, §7 the renderer sentence, §12 new twin row | required by the file's own maintenance contract |
| [tests/test_docx.py](tests/test_docx.py) | two numbering tests plus a small numbering reader | the DOCX half, and the regression guard that has never existed |
| [tests/test_app.py](tests/test_app.py) | one round-trip test | the schema half |
| [tests/test_browser.py](tests/test_browser.py) | three tests | the gutter, the control, and the library banner |

**Removed from the Round 1 radius:** [app/web/static/app.js#L1258-L1264](app/web/static/app.js#L1258-L1264). `normalizedSection` is now deliberately unchanged (decision 8), which also deletes Round 1's step 5.

**Not touched, deliberately:** `merge_step_lists` / `mergeStepLists`, `provision` / `ensure_proof_steps` and their twins, [app/docx_components.py](app/docx_components.py), [app/docx_import.py](app/docx_import.py), [app/library_editor.py](app/library_editor.py), `Report.validate_references`, `Workspace.load_path`. Each is justified below.

---

### B. Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Schema break — new field, existing drafts | **clear** | `bool = False` is filled by Pydantic for all 32 list fragments on disk; `validate_references` constrains nothing about lists beyond `frag_id` uniqueness. |
| Field removed later | **RISK, accepted, documented** | No model sets `model_config`, so `extra="ignore"` would delete the key from every draft on its next save — the trap §6 already records for `content_offer_resolved`. Once shipped, never removed without a migration. |
| `merge_step_lists` destroying the flag | **RISK, narrow, accepted** | The survivor is `merged[-1]`, so in a run of three it is the **earliest**, not the immediately preceding one. Only survivor-true + absorbed-false loses intent. Reachable only by hand-building two *adjacent* numbered lists and then accepting a library merge-append. No guard — a three-way condition duplicated in two languages with no drift test costs more than the case. One clause away if you want it. |
| **The list above is deleted** | **RISK, medium — re-rated** | Round 1 rated this low on `deletionBlockedReason`. That guard fires only for `content.type.endsWith("proof_of_concept")`; in `description` and `recommended_remediation` the only guard is `requiresFragment`, which blocks deletion solely at the section's last fragment of any kind. Since `allowed` offers `numbered_list` in all four sections, half the surface is unguarded. **No text is lost** — the continuing list falls back to 1 in both the gutter and the document. The real mitigation is that `removeButton.onclick` calls `rerender()`, so the numbers change on screen the instant the list above goes, in the same frame as the deletion. Silent in the file, immediate on screen. |
| **A `true` flag with nothing above it** | **RISK, new row, mitigated by design** | Follows from the row above and from dragging to the top: the flag stays `true` but inert. Round 1 hid the control whenever there was no preceding list, which would have made that `true` invisible and able to re-activate later. **Revised rule: render the control whenever it can act *or* whenever the flag is already `true`.** A set flag is never hidden. |
| The list above is moved below it | **clear** | `moveFragment` and `ondrop` both call `rerender(); scheduleSave();`, which recomputes every offset. |
| The list above is emptied | **clear** | `oninput` leaves `items` as `[{runs:[]}]`; the offset counts non-blank items, so the continuing list shows 1, and `generation_issues` blocks generation while any item is blank. |
| The list above becomes bulleted | **clear** | Unreachable: no assignment to `fragment.type` exists in app.js. A hand edit leaves both the offset and the renderer scanning further back. |
| Rule drift — Python/JavaScript twins | **RISK, new twin, no drift guard** | "Which list is the previous one" will live in `_render_component_content` and in `numberingOffset`. They are not the same code — Python shares a `numId`, JavaScript counts items — but they must agree on *which* list, or the editor shows a number the document contradicts. Needs the §12 row and the paired tests in steps 2 and 3. |
| `numId` leaking across sections or findings | **RISK, the headline one** | Two ways it happens: hoisting `numbering_carry` up into `_render_finding_component`, or writing `numbering_ids: dict = {}` as a default argument — which Python creates **once at definition time** and would silently join every list in the report. **The invariant is about where the dict is created, not how many callers exist.** Pinned by step 2's cross-section assertion, which covers the cross-finding case too because it is the same variable. |
| `_restart_numbering_levels` derives levels from the first clone group only | **clear, latent, recorded** | It is called with `elements` = the first group ([app/docx_components.py#L277](app/docx_components.py#L277)), so a chain's `w:ilvl` overrides come from its first member. Harmless while every clone comes from `numbered_fragment.docx`, but this proposal widens the distance between the group that defines the levels and the groups that use them. Gets a one-line comment at the carry site. |
| A continued chain shares its `nsid` too | **clear, latent, recorded** | `_assign_unique_numbering_identity` runs once per cache miss, so a chain shares `numId` **and** `nsid`. Any future "two lists differ in both" assertion is false for a chain by design. Step 2's test wording must say so explicitly. |
| DOCX import round trip | **RISK, pre-existing, accepted** | `classify_paragraph` discards `numId` before `_build_fragments` can compare it. Sharing a `numId` changes neither. Open question 3. |
| Request/response asymmetry | **RISK, mitigated** | A client-made list would be `undefined` locally and `false` after the round trip, which `diff` and `reconcileCanonicalObject` read as a change. `newFragment` sets it explicitly on **both** list types, for the same reason `code_block` sets `caption: null`. |
| Library banner resurrection | **clear — by not changing the normaliser** | Round 1 wanted the flag in `normalizedSection`. The oracle found the consequence I had not stated: `sameFragments` compares the tester's section against the **library entry's** fragments, which never carry the flag, so ticking the box in a matching section makes it stop matching and **re-shows that section's library banner**. Since the only offered actions are install (which would wipe the flag) or dismiss, that is noise, not signal. Decision 8: leave the normaliser alone. |
| A hand-edited library supplying the flag | **RISK, low, accepted** | `_steps_to_fragments` never writes it, but `main.insert_library` parses raw dicts through `Content(type="proof_of_concept", fragments=steps).fragments`, so a hand-edited `resources/vuln_library.json` carrying `continue_numbering: true` is accepted and installed. Consequence is bounded: on a first list it is inert; on an appended list it continues the tester's existing steps. The "show the control whenever the flag is true" rule makes an installed flag visible and untickable rather than hidden. |
| Stale write / `saved_at` | **clear** | No new mutation endpoint. The tick writes in memory and calls `scheduleSave()` — the existing full PUT with `saved_at` in the body. No header path. |
| Lost update | **clear** | No new server read-then-write; nothing outside `Workspace._locked`. |
| Orphan reference | **clear by design** | The flag names no id. That is why it is a boolean and not a `frag_id` pointer. |
| Silent stranding | **clear** | Gates no location, environment, or scope. |
| Navigation trap | **clear** | `generation_issues` gains no rule, `finding_is_complete` is untouched, no page gate reads the field. |
| Derived-state fight | **clear** | Nothing server-side writes `continue_numbering`. `apply_poc_variant` in replace mode discards non-image fragments including their flags — the documented meaning of replace, not a regression. |
| Backup exhaustion | **clear** | `scheduleSave()` is debounced through `queueBackendSave`; one tick is one eventual write, and a gutter repaint writes nothing. |
| Undo / recovery | **clear, stronger than claimed** | `diff` and `reconcileCanonicalObject` are key-generic and `stableItemKey` keys by `frag_id`. `restoreHistory` ends in `window.location.reload()`, so undo cannot leave a stale gutter. `remintFragments` deep-clones through JSON and carries the flag for free. |
| Tab order | **clear, noted** | The head already contributes one tab stop — drag and both move buttons are `tabIndex = -1`, delete is not. A checkbox adds a second, ahead of the textarea. Keeping it in the chain is deliberate: it is an input, and `tabIndex = -1` would make it mouse-only. No test asserts tab order. |
| Existing head-children test | **clear, with an invariant** | [tests/test_browser.py#L1426-L1430](tests/test_browser.py#L1426-L1430) asserts the exact child list of `.fragment-head`, but targets a card filtered by `has=.toolbar` — a paragraph or note. Inserting the control from inside the `fragment.items` branch keeps that card untouched. **Invariant: the control is never added to the shared head construction.** |

---

### C. Design decisions

#### 1. The field is a boolean, `continue_numbering: bool = False`, on `ListFragment`

Rejected `continues_from: frag_id` — a pointer needs existence rules in `validate_references`, a repair in `load_path` when the target is deleted, and an answer for the target being dragged below it. A positional boolean has no target to orphan. Rejected `start_at: int` — the request was "continue from the list above", and an explicit number goes wrong the moment the list above gains a line. Rejected splitting `ListFragment` into two classes — that rewrites the discriminated union and every `isinstance` site to prevent a key that is inert.

#### 2. "The previous numbered list" = the nearest preceding `numbered_list` in the same `content.fragments`

Scanning past any number of other fragments, not adjacency-only. The single real two-list section on disk is `instance_title → numbered_list → image → instance_title → numbered_list`; adjacency-only would make the feature unreachable in the exact shape it exists for. It would also be perverse, since `merge_step_lists` is the app's own rule that two *adjacent* numbered lists should be one list. A `bulleted_list` in between is skipped like anything else. The scan stops at index 0 of `content.fragments` — that is the section rule, and it is a consequence of where the scan lives rather than a separate check. Chains work without an accumulator: A restart → B continue → C continue numbers straight through.

#### 3. The DOCX shares one `numbering_ids` cache along a chain. No computed `startOverride`.

`_render_component_content` declares `numbering_carry`. Per fragment:

- numbered list, flag true, `numbering_carry` is not `None` → pass the existing cache
- numbered list, otherwise → `numbering_carry = {}`, pass that
- anything else → pass `None`, so `_render_component_fragment` makes its own fresh dict exactly as today, and **`numbering_carry` is left alone** — that is what lets a chain cross an image or an instance title

On a cache hit, `_remap_numbering` runs only its final `set(qn("w:val"), ...)`. No second `w:num`, no `w:lvlOverride`, no `w:startOverride`, and nothing later resets it. [app/docx_components.py](app/docx_components.py) is not edited.

**The safety argument, corrected.** Round 1 justified the signature change by counting callers. That is the wrong test — a variable declared in a function body is re-initialised on every call regardless of how many callers there are. The failure that would actually leak across sections and findings is a **mutable default argument**, `numbering_ids: dict = {}`, created once when the module is imported and then shared by every list in the report. `dict | None = None` avoids exactly that. Two invariants follow, and they are about *where the dict is created*:

- `numbering_carry` is declared inside `_render_component_content`'s body — not a module global, not a class attribute, not a default argument.
- `_render_component_fragment`'s parameter defaults to `None` and never to `{}`.

Why not a computed `w:startOverride` equal to the running count: the cache-sharing pattern already ships in two places ([app/docx_components.py#L145-L162](app/docx_components.py#L145-L162), [app/docx_report.py#L577-L582](app/docx_report.py#L577-L582)); an override would re-derive the renderer's "one clone per `ListItem`" rule in a second place; and a frozen number means editing the finished DOCX by hand produces a document Word will not renumber. Filtering is moot either way — `fragment_applies` reads `getattr(fragment, "environment", None)` and `ListFragment` has no such field, so a list is never filtered out.

**Evidence the chain works, cited correctly this time.** [tests/test_docx_components.py#L133-L149](tests/test_docx_components.py#L133-L149) asserts that five **separately cloned** `numbered_fragment.docx` groups behind one anchor, sharing one cache, come out with one `numId`, one `nsid`, and exactly one `startOverride` of 1. "Same `numId` across separately cloned element groups" is already shipping and already pinned. Nothing in the clone path breaks.

#### 4. The editor shows the continued numbers (subject to open question 1)

`renderLineMarkers` is **not** changed — it takes `markerText` as a callback, so the counter stays in the caller's closure and only the seed changes: `let itemNumber = numberingOffset(fragment, content)` instead of `0`. The scope page's bullet gutter is untouched.

**Two things Round 1 stated as existing that do not exist:**

- `renderGutter` is a closure declared inside the `fragment.items` branch and attached to nothing. **`input.renderGutter = renderGutter;` is a new assignment this plan adds**, alongside the existing `ResizeObserver`. Rejected alternative: a custom DOM event, which needs a listener per textarea and a teardown story for no gain.
- `renderGutter` must call `numberingOffset` **at paint time**, not capture the offset when the fragment renders, or the repaint below reads a stale value.

**The repaint, driven from the model rather than the DOM.** After `oninput` calls `changed()`, it walks `content.fragments` forward from this fragment, collecting each following `numbered_list` while the flag is true and stopping at the first that is not — that is the chain. For each, it finds `card.parentElement.querySelector('[data-fragment-id="…"] .list-textarea')` and calls its `renderGutter`. A gutter repaint only: no DOM rebuild, no `render()`, no extra save, no focus loss. In every realistic case it is one extra list.

**Known, accepted divergence.** The gutter does not number a blank line; the renderer emits one numbered paragraph per `ListItem` including an empty one. So a first list ending in an empty item would show the second list one lower in the editor than in Word. It cannot reach a generated document: `generation_issues` blocks any blank list item and [app/main.py#L518](app/main.py#L518) never passes `allow_incomplete`. Documented, no code.

#### 5. The control is a checkbox in the fragment head, and the CSS is four rules

Placement: inserted after `<span class="tag">numbered list</span>` from inside the `fragment.items` branch, the same way the rich-text toolbar is inserted from inside the `fragment.runs` branch. `.fragment-head .fragment-move-up { margin-left: auto; }` ([app/web/static/taste.css#L2553](app/web/static/taste.css#L2553)) is what pins the move and delete buttons rightward, so an insert after `.tag` lands on the left as intended.

**Element: a `<label>` wrapping a native `<input type="checkbox">`, never a `<button>.`** [app/web/static/taste.css#L3149-L3157](app/web/static/taste.css#L3149-L3157) makes every `button` in a fragment head a 20px square, which would crush a button form of this control. Choosing a label sidesteps that rule entirely rather than fighting it.

**The CSS, honestly scoped — four rules, not one:**

1. Add the label to the height normaliser at [app/web/static/taste.css#L2558-L2566](app/web/static/taste.css#L2558-L2566). Its own comment says it exists "so Delete stops setting the row's height on its own", and an unsized label will do exactly that.
2. Add it to the fade-until-engaged group at [app/web/static/taste.css#L2585-L2601](app/web/static/taste.css#L2585-L2601) — both the resting `opacity: 0.34` and the `:hover` / `:focus-within` reveal — or it is the only permanently opaque item in a row designed to recede.
3. An exception to (2) for the ticked state, so a set flag stays fully legible at rest. A state indicator that fades is a state indicator nobody reads. This is the rule Round 1 did not know it needed.
4. The label's own layout: gap, font size to match `.tag`, and the checkbox's own dimensions.

Behaviour: `rerender(); scheduleSave();` — the image-environment-select category, not the caption category, because ticking changes this list's visible numbers and, through chaining, every later list's.

**Visibility, revised.** Round 1 said "hidden on the first list in a section". That is right for a list that never had a predecessor — `ensure_proof_steps` guarantees every proof of concept opens with a numbered list, so a permanently disabled control would sit greyed out on the most common fragment in the app, explaining nothing. But it is wrong for a list that *had* a predecessor and lost it, which the re-rated delete row makes reachable in two unguarded sections. **Revised rule: render the control when there is a preceding numbered list, or when `continue_numbering` is already true.** A set flag is always visible and always untickable.

#### 6. Bulleted lists: the field exists on them and is ignored

There is no type switcher — `fragment.type` is written only by `newFragment`, so the only routes from numbered to bulleted are a hand edit or a DOCX import classifying differently. The renderer consults the flag only in the `numbered_list` arm, the editor draws the control only in the `numbered` arm, and `numberingOffset` counts only `numbered_list` fragments. A stray `true` on a bulleted list is inert. Raising instead would demote a whole draft to the manager's legacy list over a cosmetic key.

#### 7. DOCX import does not learn this

`classify_paragraph` throws away `numId` before `_build_fragments` can compare it, and `_build_fragments` groups by adjacency and kind alone. Teaching it continuation means changing how *every* imported list is grouped — a larger blast radius than this whole feature, and against the budget the demand finding sets. It is also the low-stakes half: `parse_report_docx` builds a **retest draft**, so an imported proof of concept lands in `previous_proof_of_concept` and a fresh empty one is created. The flag is lost in history the tester is about to supersede. Consequence to write down: import a report whose proof of concept had a continued list, regenerate, and the second list restarts at 1. Open question 3.

#### 8. `normalizedSection` is not touched — reversing Round 1

Round 1 planned a conditional contribution so a ticked section would not be reported as identical to its library entry. I asserted that as a goal without justifying it. The oracle's finding makes the consequence explicit: `sameFragments` compares against the **library entry's** fragments, which never carry the flag, so contributing it means ticking the box in a matching section **re-shows that section's library banner** — offering the tester a choice between installing content that would wipe the flag they just set, and dismissing a banner they did not summon.

Leaving the flag out is correct on its own terms, not merely cheaper:

- The library offer asks "does this section still match the library's content". Numbering presentation is not content.
- The dismissal fingerprint asks "has this section changed since you dismissed". Ticking a numbering box should not re-open an offer about content.
- The normaliser enumerates keys explicitly, so the flag is excluded by construction. Nothing is added; a one-line comment records why.
- It also deletes the entire class of risk Round 1 invented: no legacy dismissal can be invalidated, because no fingerprint changes. (Supporting fact: **zero** drafts on disk carry a `content_offer_dismissed` value today, so even the risk it was guarding was empty.)
- Do **not** split the two uses to get a different answer for each. [docs/DATA_MAP.md](docs/DATA_MAP.md) records that the comparison and the fingerprint must share one coercing normaliser, "without which a dismissal is undone by its own save". That bug has already been fixed once.

---

### D. Open questions

Three decisions are waiting. **Only the first needs an answer now** — steps 1 and 2 can be built whatever you decide. The other two are written out below so you can read them when you get to them; they do not block anything.

#### 1. How much of this should the editor show you? (carried from Round 1, unanswered)

**Background.** The option itself and the generated-document half are small and certain. The expensive half is making the editor's left-hand number column show the continued numbers live — so a second set of steps under a screenshot reads `3. 4. 5.` while you type in it, and shifts to `4. 5. 6.` the moment you add a line to the set above. That needs a little extra plumbing: each list has to know how many lines the list above currently holds, and typing in one list has to quietly repaint the number column of the one below without disturbing where your cursor is.

**Worth weighing before you answer.** The shape this feature serves exists exactly **once** across your nine saved reports — a proof of concept in `Fragment_Coverage_Demo` with two sets of steps separated by a screenshot and a title — and it is a file whose own name says it is a coverage demo. The saved library can never produce two numbered lists in one section. So this is something you would reach for on purpose, rarely. Against that: there is no workaround today. Typing `4.` at the start of a step prints as `1. 4.` in Word, and pasting a list that already has numbers has them stripped automatically.

**The options.**

- **Full version.** A "Continue numbering" tickbox on the second and later sets of steps in a section, and the number column shows the real continued numbers as you type. You see the finished numbering before you generate. Four build steps.
- **Minimal version.** The same tickbox, but the number column of a continuing list still counts from 1, and the card shows a short line of text instead — *"Continues the list above."* The real numbers appear only in the generated document. Two build steps, and the editor can never show a number the document then contradicts, because it never claims one.

**Tradeoffs.** The full version is what you would expect from a word processor and asks you to trust nothing. The minimal version is faster and carries no risk of the screen and Word disagreeing — but it asks you to believe a sentence, on a rarely used option, where believing it wrongly means regenerating the document to find out.

**My recommendation: the full version.** Precisely *because* this is rare and deliberate, you will have no habit telling you it works. A tickbox whose effect you cannot see is one people flip twice to check. The plumbing is genuinely modest — the number column already draws its markers through a callback, so the only new things are a starting value and a repaint of the list below.

#### 2. What should the tickbox look like, and where should it sit? (deferred — answer after 1)

**Background.** Every set of steps sits in a card with a small grey strip along the top: a drag handle, the words "numbered list", then Move up, Move down and Delete pushed to the right. That strip deliberately fades to near-invisible until you hover over the card, so a page of steps does not look like a control panel.

**The question.** The tickbox and its label go in that strip, immediately after the words "numbered list", on the left. Two things need deciding: **when it appears**, and **whether it fades**.

- **When it appears.** My plan: it appears on a set of steps only when there is another set above it in the same section for it to continue from — and also whenever it is already ticked, even if the list above has since been deleted, so a ticked box is never hidden from you. The alternative is showing it greyed-out on every set of steps, which means the most common card in the app permanently carries a control that does nothing.
- **Whether it fades.** Everything else in that strip fades until you hover. An unticked box should fade with them. A **ticked** box should not — it is telling you something about this list, and a state you cannot read at a glance is not a state.

**My recommendation: appears when it can act or when it is already ticked; fades when unticked, stays solid when ticked.** Label "Continue numbering", with a hover tooltip naming the outcome — *"Continues the list above; this list starts at 4."*

#### 3. If you re-import a finished document, should the continued numbering survive? (deferred — answer after 1)

**Background.** You can import a finished Word report to start a retest. When you do, the app reads the document back into steps, screenshots and paragraphs. It does that by looking at each paragraph and deciding "this is a numbered item" or "this is a bullet" — it does not record *which* numbered list each item belonged to.

**The consequence.** Import a report whose proof of concept had two sets of steps running `1, 2, 3` then `4, 5, 6`, and the second set comes back as an ordinary set starting from 1. Regenerate, and it prints `1, 2, 3` then `1, 2, 3`. You would have to re-tick the box.

**Worth knowing:** this is not new. Today, any two sets of steps separated by a screenshot already come back as two independent sets. And on import, the old proof of concept is filed as *Previous* proof of concept — history you are about to supersede — while a fresh empty one is created for the retest.

**The options.**

- **Accept it.** The option is lost on import; you re-tick it if you want it. Nothing to build.
- **Teach the importer.** It would have to start tracking which numbered list each paragraph belonged to, which changes how *every* imported list is grouped, not just continued ones. That is a bigger and riskier change than this whole feature, and it deserves its own plan and its own tests.

**My recommendation: accept it, and write the consequence down** so the next person to hit it finds the answer rather than a mystery.

---

### E. Plan

Each step leaves the app saveable and generating. Test scope is named per step so nothing runs that the change cannot affect.

**Step 1 — the field.**
Files: [app/models.py#L81-L84](app/models.py#L81-L84) (`continue_numbering: bool = False`); [app/web/static/app.js#L2317](app/web/static/app.js#L2317) (`newFragment` sets it explicitly on both list types).
Test: `tests/test_app.py` — a draft whose list fragments have no `continue_numbering` key loads and re-serialises with `false`; a draft carrying `true` keeps it across a save. Scope: the named tests in `tests/test_app.py`, plus `tests.test_browser` because `newFragment` changed.
Invariant: every draft on disk still validates, and a client-made list has the same shape before and after its first round trip.

**Step 2 — the document.**
Files: [app/docx_report.py#L690-L765](app/docx_report.py#L690-L765) only. [app/docx_components.py](app/docx_components.py) unchanged. Includes a one-line comment at the carry site recording that `_restart_numbering_levels` takes its levels from the chain's **first** clone group.
Tests: `tests/test_docx.py`, plus a small local numbering reader — `_numbering_details` currently exists only as a static method on the component test class, and a local reader is cheaper than coupling two test modules. **Two tests, one fixture shape** (`numbered_list(2) → image → numbered_list(2)` in a proof of concept, with a separate list in Description):

- *Chain case*, flag `true`: all four list paragraphs share **one `numId` and one `nsid`** — say `nsid` explicitly, because a chain sharing it is by design and contradicts the shape the component test asserts for two unrelated lists — and exactly one `w:startOverride` of 1 exists for that `numId`; the Description list carries a **different** `numId`.
- *Control case*, flag `false`: two distinct `numId`s, two distinct `nsid`s, each with its own `startOverride` of 1.

**Say this out loud in the commit and in the test's own comment: the control case is new coverage, not a re-assertion.** Round 1 claimed [tests/test_docx_components.py#L129-L148](tests/test_docx_components.py#L129-L148) already pinned it. It does not — that test calls `compose_docx_template`, which `render_report_docx` never calls, and its two groups differ only because they sit at two different anchors with a cache each. **Nothing anywhere currently pins that two list fragments inside one section restart independently.** That makes this the most valuable test in the plan: it is the only thing standing between a future edit and silently renumbering every existing report, including the one real two-list section on disk.
Scope: `tests.test_docx`, `tests.test_docx_components`, `tests.test_docx_captions`, `tests.test_docx_import`.
Invariant: **no `numId` is shared by two content sections.** Because the carry is one function-local variable in `_render_component_content`, which is called once per anchor per finding, that single assertion covers the cross-finding case too.

**Step 3 — the gutter.** *(Full version only — skipped if open question 1 chooses minimal.)*
Files: [app/web/static/app.js#L2616-L2674](app/web/static/app.js#L2616-L2674) — `numberingOffset`, the seed in `renderGutter`, the **new** `input.renderGutter = renderGutter` assignment, and the chain repaint in `oninput`. `renderLineMarkers` untouched.
Test: `tests/test_browser.py`, beside `test_list_textareas_show_markers_and_store_non_empty_lines`. Seed the two-list shape with the flag already set; assert the second gutter's first `.list-marker` reads `3.`; type a line into the first list; assert the second gutter reads `4.` **and** that focus and caret position in the *first* textarea are unchanged. Scope: `tests.test_browser`.
Invariant: a keystroke in one list never rebuilds the pane or moves the caret.

**Step 4 — the control.**
Files: [app/web/static/app.js#L2563](app/web/static/app.js#L2563) (inserted from inside the `fragment.items` branch), [app/web/static/taste.css](app/web/static/taste.css#L2549-L2601) (the four rules in decision 5).
Test: `tests/test_browser.py` — the control is absent on the first numbered list of a section and present on the second; ticking it changes the gutter and survives a reload; the control is still present on a list whose flag is true after the list above it is deleted. Scope: `tests.test_browser`.
Invariants: the control is never added to the shared head construction, so [tests/test_browser.py#L1426-L1430](tests/test_browser.py#L1426-L1430) still sees exactly six children on a paragraph card; and a `true` flag is never invisible.

**Step 5 — the library banner must not notice the tick.**
Files: none. This step is a test and a comment, guarding decision 8.
Test: `tests/test_browser.py` — on a finding whose Description matches its library entry and holds a numbered list: assert the banner is **present** before dismissal, dismiss it, tick Continue numbering, reload, assert the banner is still gone. Fold into step 4's test if the fixture allows; it is one finding either way.
Why this shape, replacing Round 1's literal hash: there is no constant, so it cannot be a tautology computed after the change; it does not depend on the fingerprint tuple's length, so a future legitimate field does not make it read as though this feature regressed; and the absence assertion is validated by a presence assertion **in the same run**, so it cannot rot into a green test that proves nothing.
Invariant: ticking the box changes no fingerprint and resurrects no dismissed banner.

**Step 6 — the map.**
Files: [docs/DATA_MAP.md](docs/DATA_MAP.md) §6, §7, §12. Scope: nothing runs.
Invariant: §7's claim that two list fragments each restart at 1 is corrected to "unless the second asks to continue", and §12 gains the new twin row, so the next reader is not misled the way the `merge_step_lists` sentence misled this round.

Order rationale: the model before the renderer, because the renderer reads the field. The renderer before the editor, so the editor never shows a number the document would not print. The control after the gutter, so the first tick has a visible effect. Step 5 last among the code steps because it is the only one that guards a decision rather than a behaviour.

---

### What I would not do

**Compute and write a `w:startOverride` equal to the running item count.** It duplicates the renderer's own item-counting rule where nothing will keep the two in step, it freezes the number so hand-editing the finished DOCX produces a document Word will not renumber, and it adds new XML-writing code when a cache-sharing pattern that already ships in two places does the job by *not* entering a branch.

**Contribute the flag to `normalizedSection`, conditionally or otherwise.** This is the shortcut I took in Round 1. It makes ticking a presentation option re-open a content offer, on a section the tester did not change, whose only remedy would wipe the flag. And it puts every `content_offer_dismissed` string on disk at the mercy of a conditional that a future reader can make unconditional in one keystroke.

**Pin the fingerprint with a literal hash.** It is only meaningful if computed with pre-change code, which nothing in the test can enforce; the tuple has grown before, so the next legitimate field makes the failure read as though this feature regressed; and it guards an absence that passes for unrelated reasons. Step 5 asserts the outcome instead.

**Write `numbering_ids: dict = {}` as a default argument.** It looks tidier than `None` and it is the bug that would silently join every list in the report into one. The parameter defaults to `None`; `clone_component_elements` already substitutes a fresh dict.

**Make `merge_step_lists` flag-aware.** Tempting, because survivor-true + absorbed-false is a silent overwrite of an explicit choice. Rejected because the guard is a three-way condition that must be reproduced byte-for-byte in `mergeStepLists` with no drift test — §12 records that none of these pairs has one — to protect a shape that needs a tester to hand-build two adjacent numbered lists, tick continue on the first, and then accept a library merge-append. Listed as a risk rather than buried, and one clause away if you want it.

**Add a `load_path` repair back-filling `continue_numbering: false`.** A model default already does it, and a repair would rewrite the file and spend the single `draft.bak.json` to write a value nothing was missing.

**Teach `docx_import` to read `numId` identity now.** It is the honest fix for the round trip, but it changes how every imported list is grouped — a bigger change than the feature that exposed it, and out of proportion to a shape that occurs once on disk. Its own plan, its own tests.

## Answers

### 1. Should the editor show the continued numbers live, or just say the list continues?

**Answered: the full version.** The tickbox *and* a number column that shows the real continued
numbers as you type, updating when the list above gains a line. All four build steps.

The planner's reasoning, accepted: precisely because this option is rare and deliberate, there is no
habit telling the tester it worked, and a tickbox whose effect is invisible until generation is one
people flip twice to check.

### 2. When should the tickbox appear, and should it fade?

**Answered: as planned.** It appears on a set of steps when there is another set above it in the same
section to continue from, **and also whenever it is already ticked** — so a ticked box is never hidden,
even if the list it continued has since been deleted. It fades with the rest of the card's controls
when unticked, and stays solid when ticked, because a state nobody can read at a glance is not a state.

Label "Continue numbering", hover tooltip naming the outcome: *"Continues the list above; this list
starts at 4."*

### 3. If you re-import a finished document, should the continued numbering survive?

**Answered: accept the loss and document it.** The importer is not taught to track which numbered list
each paragraph belonged to. That would change how *every* imported list is grouped, not just continued
ones — a bigger and riskier change than the feature itself, spent on preserving an option into a
section that import files as superseded history.

Consequence to write down: import a report whose proof of concept ran `1, 2, 3` then `4, 5, 6`,
regenerate, and the second set restarts at 1.

### Not asked

Every answer matched the planner's recommendation, so no third planner round was needed. The two
judgement calls the planner made without asking — no guard on `merge_step_lists`, and leaving
`normalizedSection` alone — are recorded in Round 2 with their reasoning, and both are one clause away
if they turn out wrong.

## Agreed plan

Six ordered steps. Each names its files, its test, and the invariant it must not break.

### What is being built

A numbered list gains an opt-in **Continue numbering** option, off by default. When set, that list does
not restart at 1 — it carries on from the nearest numbered list before it **in the same content
section**, and the generated document numbers it the same way.

### Why the section rule needs no code

Continuation in Word is `numId` identity, not adjacency. Today every list fragment gets a fresh
`numId`, `abstractNumId`, `nsid` and an explicit `w:startOverride`, because `_render_component_fragment`
opens a new `numbering_ids` cache inside its `ListFragment` branch. So a proof-of-concept list already
cannot continue a previous-proof-of-concept list, and remediation cannot continue description. **The
user's boundary rule is already the behaviour.** This change is the opt-in exception *within* one
section, and the boundary survives because the cache lives in one function-local variable in
`_render_component_content`, which is called once per anchor per finding.

### The three decisions that shape it

- **A boolean, not a pointer.** `continue_numbering: bool = False` on `ListFragment`. A `continues_from: frag_id` would need existence rules in `validate_references`, a repair when the target is deleted, and an answer for the target being dragged below it. A positional boolean has no target to orphan.
- **"The previous numbered list" means the nearest preceding one in the same section, scanning past anything in between** — not adjacency. The only real two-list section on disk is `instance_title → numbered_list → image → instance_title → numbered_list`; adjacency-only would make the feature unreachable in the exact shape it exists for.
- **The document shares a `numbering_ids` cache along the chain; it does not compute a `w:startOverride`.** On a cache hit `_remap_numbering` runs only its final `set(qn("w:val"), ...)`, so no second `w:num` and no override is written, and Word continues the count. A computed override would duplicate the renderer's own item-counting rule where nothing keeps the two in step, and would freeze the number so hand-editing the finished document leaves it wrong.

### Ordered steps

**Step 0 — read this first: the two ways this silently renumbers every report.**
The carry variable must be declared **inside `_render_component_content`'s body**, and
`_render_component_fragment`'s parameter must default to `None`, never `{}`. A mutable default argument
is created once at import and would join every list in the report into one chain. Caller count is
irrelevant — a function-local is re-initialised per call however many callers exist. This is the
invariant step 2's test exists to protect.

**Step 1 — the field.**
*Files:* [app/models.py](../../app/models.py) — `continue_numbering: bool = False` on `ListFragment`; [app/web/static/app.js](../../app/web/static/app.js) — `newFragment` sets it explicitly on both list types.
*Test:* a draft whose list fragments lack the key loads and re-serialises with `false`; a draft carrying `true` keeps it across a save.
*Invariant:* every draft on disk still validates with no `load_path` repair, and a client-made list has the same shape before and after its first round trip. Setting it explicitly in `newFragment` is what stops `undefined` locally versus `false` after the round trip reading as a change to `diff`.

**Step 2 — the document.**
*Files:* [app/docx_report.py](../../app/docx_report.py) only. [app/docx_components.py](../../app/docx_components.py) is not edited.
*Test:* one fixture shape — `numbered_list(2) → image → numbered_list(2)` in a proof of concept, plus a separate list in Description. **Chain case** (flag true): all four list paragraphs share one `numId` **and one `nsid`**, exactly one `w:startOverride` of 1 exists for it, and the Description list carries a different `numId`. **Control case** (flag false): two distinct `numId`s, two distinct `nsid`s, each with its own override.
*Invariant:* **no `numId` is shared by two content sections.** Because the carry is one function-local in a function called once per anchor per finding, that assertion covers the cross-finding case too.
*Say this in the test's comment:* the control case is **new coverage, not a re-assertion**. Nothing anywhere currently pins that two list fragments inside one section restart independently — the existing component test calls `compose_docx_template`, which `render_report_docx` never calls, and its two groups differ only because they sit at two different anchors. This is the only thing standing between a future edit and silently renumbering every existing report.

**Step 3 — the number column.**
*Files:* [app/web/static/app.js](../../app/web/static/app.js) — `numberingOffset(fragment, content)`, the seed in `renderGutter`, a **new** `input.renderGutter = renderGutter` assignment, and the chain repaint in `oninput`. `renderLineMarkers` is untouched: it already takes the marker text as a callback, so only the counter's starting value changes, and the scope page's bullet gutter is unaffected.
*Test:* seed the two-list shape with the flag set; the second column's first marker reads `3.`; type a line into the first list; the second column reads `4.` **and** focus and caret position in the first textarea are unchanged.
*Invariants:* a keystroke in one list never rebuilds the pane or moves the caret. `renderGutter` must call `numberingOffset` **at paint time**, not capture it when the fragment renders, or the repaint reads a stale value.
*Known divergence, documented not coded:* the column skips a blank line but the renderer emits a paragraph per item including an empty one, so a first list ending in an empty item would show the second one lower than Word. It cannot reach a document — `generation_issues` blocks any blank list item and the app never passes `allow_incomplete`.

**Step 4 — the control.**
*Files:* [app/web/static/app.js](../../app/web/static/app.js) — a `<label>` wrapping a native checkbox, inserted after the `numbered list` tag **from inside the `fragment.items` branch**; [app/web/static/taste.css](../../app/web/static/taste.css) — **four rules, not one**: add it to the head's height normaliser, add it to the fade-until-hovered group, an exception so the *ticked* state stays solid, and the label's own layout.
*Test:* absent on the first numbered list of a section, present on the second; ticking changes the number column and survives a reload; still present on a list whose flag is true after the list above it is deleted.
*Invariants:* the control is **never added to the shared head construction** — an existing test asserts the exact six children of a paragraph card's head. A `true` flag is never invisible. It must be a `<label>`, not a `<button>`: a stylesheet rule makes every button in a fragment head a 20px square.

**Step 5 — the library banner must not notice the tick.**
*Files:* none. A test and a comment, guarding the decision to leave `normalizedSection` alone.
*Test:* on a finding whose Description matches its library entry and holds a numbered list — assert the banner is **present**, dismiss it, tick Continue numbering, reload, assert it is still gone.
*Invariant:* ticking changes no fingerprint and resurrects no dismissed banner. The presence assertion in the same run is what stops this rotting into a green test that proves nothing.

**Step 6 — the map.** [docs/DATA_MAP.md](../DATA_MAP.md) §6 (the new field and the `extra="ignore"` warning it shares with its siblings), §7 (correct "two list fragments each restart at 1" to "unless the second asks to continue"), §12 (the new twin row).

### Accepted costs, to be stated in the release note

- **A `merge_step_lists` corner loses intent silently.** If a tester hand-builds two *adjacent* numbered lists, ticks continue on the first, and then accepts a library merge-append, the survivor's flag wins and the second list's explicit "restart at 1" is lost. No guard: a three-way condition duplicated in two languages with no drift test costs more than the case. One clause away if it proves real.
- **Deleting the list above is silent in the file.** The continuing list falls back to 1 in both the column and the document; no text is lost, and the numbers change on screen in the same frame as the deletion. The delete guard that covers the proof-of-concept sections does **not** cover Description or Recommended Remediation, where numbered lists are equally allowed.
- **Re-importing a document loses the option**, per answer 3.
- **A hand-edited `resources/vuln_library.json` can carry the flag** through `insert_library`, even though the library editor never writes it. Bounded: inert on a first list, continues the tester's steps on an appended one, and always visible because a set flag is never hidden.
- **Two latent facts about the chain:** it shares its `nsid` as well as its `numId`, so any future "two lists differ in both" assertion is false for a chain by design; and `_restart_numbering_levels` derives its level set from the chain's **first** clone group, harmless while every clone comes from one component file.
