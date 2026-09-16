# Editor field affordances

## Request

> - Vuln id fields to be invisible as well until clicked. Just show a text of Vuln ID placeholder. Then when they click, an empty field will replace that then the vulnerability id can be inputed.
> - The affected locations overlap when they are too long. Should expand vertically when overflowing. This is when selected or not selected.
> - The image fragments are always highlighted when they are empty. Only do so when they click go to in the right side panel.
> - Also, for the warnings for prompts when users are prompted to use library values, make them yellow instead of blue in the right side panel. You can edit the ui for the prompt accordingly.

## Round 1 - Oracle: how it works today

### Item 1 - Vuln ID, Findings page

**Render path is two passes over one `<tr>`.** `renderFindings()` builds the row as a string (app.js:1889); cell 5 is `<td><input value="…" inputmode="numeric" maxlength="5" pattern="[0-9]*" autocomplete="off"></td>`. Each finding emits **two** `<tr>`: the data row and `.finding-location-row`.

`enhanceFindingRows()` (app.js:1697-1777) upgrades it, branching on `idInput.value.trim()` (app.js:1754):

- **Has an id** - builds `<button class="finding-id-display">`; `setIdEditing()` toggles `idInput.hidden`; click unhides and focuses (app.js:1755-1774). Blur with a value returns to the button; blur when empty calls the full `renderFindings()` (app.js:1770).
- **No id** - the bare input stays visible; only a blur listener exists (app.js:1775-1777), which calls `renderFindings()` once a value is typed.

`.finding-title-display` (app.js:1730-1749) is the identical working precedent and has the same `if (value.trim())` gap.

`labelAssessmentPlaceholders()` sets `row.querySelectorAll("input")[1].placeholder = "Vuln ID"` - positional (app.js:1601).

**CSS.** `.finding-id-display` overrides.css:119; `td:nth-child(5) { position: relative }` overrides.css:120; `td:nth-child(5) input:not([hidden]) { position: absolute; inset: 7px 10px }` overrides.css:122; column pinned `width: 90px` overrides.css:107 under `table-layout: fixed` overrides.css:101; `<960px` unwind with `!important` at taste.css:1016-1024.

**Data.** `Vulnerability.display_id: Annotated[str, Field(pattern=r"^[0-9]{1,5}$")] | None` (models.py:184). `""` is **invalid**; the client writes `digits || null` (app.js:1912). Cross-finding uniqueness is enforced only server-side in `Report.validate_references` (models.py:345-347), surfacing as 422 `invalid_report` - **no JS twin**. Drafts on disk hold `"001"`, `"003"`, `"004"`, `"005"`, `null` - never `""`. Leading zeros are real, so render the string, not a parsed number.

**Invariants.** Two `<tr>` per finding (`validateFindingsPage` indexes `findingBody.children[index * 2]`; `enhanceFindingRows` takes `row.nextElementSibling` as the location row). The digit clamp is repeated in four places: markup attributes app.js:1889, the reinforcement at app.js:1751-1752, the capture listener app.js:1753, the `oninput` at app.js:1906-1913 - plus the model pattern.

### Item 2 - Affected locations overlap, Findings page

**It is the Findings page location row.** Not the Content page. `.fchip-locations` on Content is already hardened (nowrap summary plus a popover with `overflow-wrap: anywhere`, taste.css:1429-1474) and needs nothing. `.finding-locations` (plural) is **dead CSS** - styled at overrides.css:205-210 and taste.css:1313-1339 but emitted by nothing.

Markup: `.location-option { display: grid; grid-template-columns: 20px minmax(0,1fr) }` (overrides.css:143) holding either `<span class="location-preview">` when unticked or `<input class="location-value">` when ticked, the input replaced by a `<textarea>` in pass 2 (app.js:1870-1879). Parent `.location-controls` is a two-column grid (overrides.css:137). **The two states are mutually exclusive per target and never coexist** - the "overlap" is two states of one slot.

- **Fault A, unticked.** `.location-preview` (overrides.css:150) declares no `overflow-wrap`/`word-break`, so an unbroken URL renders past its `minmax(0,1fr)` track and collides with the Non-Production column.
- **Fault B, ticked.** `textarea.location-value` (overrides.css:151) sets `overflow-wrap: normal; word-break: normal; overflow: hidden`, so a URL never wraps, `scrollHeight` stays one line, and the auto-grow at app.js:1882-1886 has nothing to grow. Worse, `setExpanded()` (app.js:1726) sets `locationRow.hidden = true` **before** `resize()` runs (app.js:1885), so a collapsed finding gets `height: 0px` inline and stays clipped at `min-height: 28px` until a keystroke.

No model or route change is needed. Nothing here lives in two languages **unless** the fix starts trimming stored values, which would enter `location_lines` (report_service.py:257) / `locationLines` (app.js:1023).

**On disk:** `scope` is uniformly `{mode:"custom", target_ids, location_values, custom_locations}`; `custom_locations` is `{}` in every finding of all seven drafts. The longest stored value is 28 characters, so reproducing the overlap needs a long URL typed by hand.

### Item 3 - Image fragment highlight, Content page

**Two separate mechanisms.**

`is-incomplete` is applied in bulk by `updateReadinessPanel` (app.js:2649-2650):

```js
const incomplete = new Set(issues.filter(i => i.fragmentId && (i.level||"error")==="error").map(i => i.fragmentId));
pane.querySelectorAll("[data-fragment-id]").forEach(n => n.classList.toggle("is-incomplete", incomplete.has(n.dataset.fragmentId)));
```

re-asserted on every `render()` and every `reportchange`. `is-review-target` is the separate Go-to highlight, driven by module state `reviewTargetId` (app.js:2553) via `showReviewTarget()` (app.js:2556-2562), set only on a Go-to click (app.js:2712) and cleared when the tester clicks the target.

**The current ring is amber, not red.** taste.css:3152-3162 re-declares the same selectors as taste.css:1945-1951 with `var(--warning)` and wins by order.

An empty proof-of-concept slot usually lands in `incomplete` **twice** - the per-fragment check (app.js:2605-2609) and the per-environment coverage check (app.js:2624-2632).

Empty slots are server-manufactured: `sync_evidence_image_slots` (report_service.py:340-393) runs from `provision_report` on **every PUT**. Six of seven drafts have no evidence directory at all, so every image fragment in them is empty.

**Invariants.** The issue must stay in `issues` - `generateButton.disabled` (app.js:2667), `#issue-count` and `.content-flag` all derive from that array (app.js:2645-2663). Only the class application may be narrowed. The stale-image exemption `fragmentApplies` (app.js:2592-2595, twin report_service.py:322) must be preserved. `render()` rebuilds the pane, which is why the Go-to highlight is state and not a class.

### Item 4 - Library-offer prompts blue to yellow

**Banners on Content.** `.poc-offer` (app.js:2916-2964, attributes `data-poc-offer`, `data-offer-for`) and `.content-offer` (app.js:2975-3005, attributes `data-content-offer`, `data-offer-for`). One colour declaration, **overrides.css:302 only**, no taste.css override: `border-left: 3px solid var(--accent); background: var(--accent-soft)`.

**Panel twin.** The same offers render as `<tr class="review-row" data-level="warning">` built at app.js:2673-2681 from the shared owner `pendingLibraryOffers` (app.js:1096-1111), message fixed at `"can be used or dismissed"`.

**The palette is inverted relative to the request.** Errors - real gaps that disable Generate - use `var(--warning)` amber. Suggestions use `var(--accent)` blue. Making suggestions yellow without moving errors collapses two meanings into one colour in the panel whose only job is triage.

`level: "warning"` is set in exactly two places: every library offer (app.js:2675) and the placeholder-text check (app.js:2611). Group level is `errors ? "error" : "warning"` (app.js:2689-2690).

**Invariants.** Offers must never enter `issues` - the count and the Generate gate are computed before offers are appended (app.js:2645-2673); moving them would diverge from the server's `generation_issues` (docx_report.py:93). Offer rows carry no `fragmentId`, so Go-to falls through to `[data-offer-for="<type>"]` (app.js:2728) - **any markup change must keep that attribute**.

**Data.** `content_offer_resolved: dict[ContentType, StableId]` (models.py:196) - a missing key and `{}` both validate, explicit `null` does not. Three generations exist on disk: oldest with singular `poc_variant` (migrated by `_migrate_poc_variant`), middle with all three keys empty, newest with populated `content_offer_resolved` such as `{"description": "VDB-012", "recommended_remediation": "VDB-012"}`.

## Round 1 - Planner: proposal and open questions

Proposed a five-step plan: answer the palette question, wrap long locations (overrides.css:150-151), re-measure on expand (app.js:1718-1726), reveal-on-demand image highlight (app.js:2649-2650 plus new state at 2553), Vuln ID placeholder (app.js:1753-1777), apply the decided palette.

Graded as **RISK**: item 1 control indices, `display_id` pattern, digit clamp, uniqueness with no JS twin, mid-interaction rebuild, positional placeholder, double save (mild), item 2 value mutation, item 2 `height: 0px`, item 3 the `issues` array, item 3 stale-image exemption, item 3 highlight vs re-render, item 4 palette inversion (blocking), item 4 `data-offer-for`, item 4 third amber (`.content-guidance`).

Graded **clear**: item 3 server-side slots, `content_offer_resolved`, stale write, lost update, schema break, request/response asymmetry, navigation trap, orphan reference.

Put three palette options to the user: **A** swap (suggestions yellow, errors red, claiming a dead `--danger` version exists to revive), **B** two yellows, **C** yellow plus a shape change. Recommended A.

Refused to: remove the `<input>` from the row markup, keep `renderFindings()` on empty blur, filter `issues` to quiet the highlight, truncate stored location values, recolour offers without moving the error palette, or add a JS duplicate-`display_id` check.

## Round 2 - Oracle: verdict on the proposal

**Six risk verdicts overturned.**

- **item 1 control indices - clear.** `controls` is bound inside `renderFindings` (app.js:1901-1929) against an un-enhanced row. A `<button>` is neither an `input` nor a `select`, so `controls[4]`, `controls[5]`, `querySelectorAll("select")[0..3]` (app.js:1779-1786) and `labelAssessmentPlaceholders`'s input index (app.js:1601) are immune. The Delete handler `row.querySelector("button").onclick` (app.js:1961) binds before enhance, and enhance is idempotent via `row.dataset.enhanced` (app.js:1709-1710).
- **item 1 positional placeholder - clear**, same reason.
- **item 1 mid-interaction rebuild - graded backwards.** The rebuild is what the change removes, not a hazard it adds.
- **item 1 double save - clear, not mild.** One writer of `finding.display_id` (app.js:1912); the blur handler assigns nothing.
- **item 2 `height: 0px` - self-resolving inside the plan's own step.** The inline `style.height` (app.js:1883) already beats the stylesheet; `height: 28px` is what lets an inline `0px` collapse the box, and the `min-height` swap floors it. Steps 1 and 2 are coupled.
- **item 3 server-side slots - clear, conditionally.** Server-minted `frag_id`s (report_service.py:382) never reach the client because only `saved_at` is adopted back (app.js:341-345). Clear **only while the revealed set stays module-local**; persisting it flips the row to RISK.

**Missed, and material.**

- **A. `hidden` is inert on both display buttons.** No stylesheet declares `[hidden] { display: none }`; the only matches are three `:not([hidden])` guards. Author origin beats the UA rule, so `.finding-id-display { display: flex }` (overrides.css:119) makes `idDisplay.hidden = editing` (app.js:1763) do nothing. It only looks right because the input is lifted out of flow and painted on top (overrides.css:122). The `<960px` unwind (taste.css:1016-1024) sets `position: static !important`, removing the mask - so at narrow widths the button and the input stack. Same defect for `.finding-title-display` (overrides.css:115, 118). **This is the plan's real item-1 hazard.**
- **B. Duplicate label below 960px.** taste.css:1012 already injects `content: "Vuln ID"` into cell 5.
- **C. Two amber surfaces outside the palette list:** `.content-flag` (taste.css:3143-3150) and `#issue-count` (taste.css:2002-2013).
- **D. Error-side base rules for two of the five pairs:** `.review-group` border-left at taste.css:2063-2070 and `.review-group-count` at taste.css:3394-3403.
- **E. Five dead `[data-level]` rules** at taste.css:1569, 1586, 2045, 2118, 2122, targeting `.review-item` / `.review-icon` / a `<b>` inside `.review-group-count`, none of which `renderGroup` emits (app.js:2694-2696).

**The test claim was half right.** tests/test_browser.py:821-823 does fill `#findings input[inputmode='numeric']`, but the test **will not break - it will go vacuous**: `.finding-id-display` resolves immediately and `expanded.count() == 0` still holds, because the rebuild it exists to catch no longer happens. Its docstring (line 811) becomes false.

Every other test touching the four surfaces: Vuln ID - browser only 810-825, server test_app.py:1246-1257, test_docx_import.py:73/174/214/221, test_docx.py:570/579. Location preview or value - **none**; the nearest (test_browser.py:1511-1512) targets `.location-lines-textarea`, a different control already floored by `Math.max(28, scrollHeight)` (app.js:1845). `is-incomplete` - **none in any suite**. Offer banners - test_browser.py:1106-1108, 1117, 1148, 1274-1275, all asserting counts and attributes, none asserting colour. Also `#issue-count` at test_browser.py:929 and 1358-1359, and the title button's accessible name at 869, 941, 959 - the `aria-label` at app.js:1733 must survive verbatim.

**Item 2 mechanics corrected.** `.location-preview` has **no wrapping declaration to remove** - `overflow-wrap: anywhere` must be **added**. For the textarea, deleting `overflow-wrap: normal; word-break: normal` works only by falling back to the UA sheet; declare `overflow-wrap: anywhere` explicitly. Nothing later re-imposes them - the only other matching rule is taste.css:554-555, font only.

**Option A is cheaper than claimed but collides with a stated decision.** taste.css:1942-1951 is not dead code to revive - it is a **shadowed duplicate** of taste.css:3153-3162; deleting the later block makes the earlier live with no new declarations. But taste.css:3185-3193 states *"Delete is neutral until reached for; red on a resting control reads as an error"*, and A puts a resting red ring on a card whose own Delete stays grey until hover. `--danger` already means failure at overrides.css:13, taste.css:148-164, taste.css:485-494, overrides.css:315. Inside `#editor-notifications` itself there is no collision.

**No `draft.json` breaks.** Nothing in the plan reaches the schema.

## Round 2 - Planner: revised plan

Accepted every correction. Six rows flipped to clear, one regraded as backwards, hazard A added, steps 1 and 2 folded together because they are causally coupled - today's rebuild is what re-runs the textarea resize and hides the collapsed-box bug, so removing the rebuild exposes it. One correction back to the oracle: taste.css loads **after** overrides.css in all four templates, which strengthens rather than changes the conclusion that the heading badge is amber today.

**Revised risk table.** RISK: orphan reference (the revealed set must be keyed on `(finding.uid, content.type, environment)`, never `frag_id`, because reminting happens at app.js:1062, report_service.py:411 and 439, and workspace.py:229-235); **A. inert `hidden`, stacked controls**; **B. duplicate label below 960px** (dissolves if the placeholder is a glyph); **C. test goes vacuous**. Clear: stale write, lost update, silent stranding, schema break, request/response asymmetry, rule drift, navigation trap, backup exhaustion, control-index drift, and derived-state fight **conditionally** - clear only while the revealed set stays module-local.

**Revised plan.**

1. **Make `hidden` real** (prerequisite, cannot be reordered). Add `.finding-id-display[hidden], .finding-title-display[hidden] { display: none; }` to overrides.css after lines 115 and 119. Specificity (0,2,0) beats the base (0,1,0); the narrow-width block sets only `position`, `width`, `min-width`, `max-width`, `text-align`, never `display`, so the guard survives its `!important`s. Both inputs are already safe via their `:not([hidden])` guards. *Test:* at an 800px viewport, click a populated `.finding-id-display` and assert exactly one of button and input is visible; same for the title. *Invariant:* the two displays and their inputs are never simultaneously visible at any width.
2. **Vuln ID always-on display, coupled with the location box floor.** JS: build `.finding-id-display` unconditionally, delete the `else` branch (app.js:1777) and the empty-blur `renderFindings()` (app.js:1773); blur becomes `setIdEditing(false); scheduleSave();`. If the builder is generalised across both displays, `"Edit vulnerability ID"` and `"Edit finding name"` must survive verbatim. CSS: at overrides.css:151 drop `height: 28px`, keep `min-height: 28px`, replace `overflow-wrap: normal; word-break: normal` with explicit `overflow-wrap: anywhere`; at overrides.css:150 **add** `overflow-wrap: anywhere`. *Tests:* **rewrite** test_browser.py:810-825 rather than delete it - hold a JS handle to the `<tr>`, type, blur, assert the handle is still connected, the fold state is unchanged and the button reads the value; add a case for the empty state; add a long-endpoint wrap case in both states. *Invariant:* the table is never rebuilt while a cell holds focus; `expandedFindingIds` survives every ID edit; `display_id` keeps exactly one writer.
3. **Evidence slot reveal.** Key the revealed set on `(finding.uid, content.type, fragment.environment)`, never `frag_id`. Keep it module-local and do not persist it, with a comment saying why. *Test:* reveal a slot, force a save, assert it stays revealed with no duplicate; reload and assert it returns to unrevealed. *Invariant:* `provision_report` owns which slots exist; the client owns only which are shown.
4. **Palette consolidation.** Delete the shadowed `--danger` block at taste.css:1942-1951. Delete `background: var(--danger)` from `.review-heading b` (overrides.css:272), doubly shadowed and a trap for any future badge. Verify only, no change, on `.content-flag`, `#issue-count`, the `.review-group` border-left and `.review-group-count`. *Tests:* none new; do not add colour assertions, which would freeze a design decision into the suite.
5. **Dead rule removal** (independent, droppable). Delete the `.review-item` family (overrides.css:273-279, taste.css:1562-1588, taste.css:2015-2058), the two `.review-group-count b[data-level]` rules (taste.css:2118, 2122), and `.finding-nav-heading .nav-count[data-state="issues"]` (taste.css:2962-2966). Keep the base `.nav-count` rule - that class is emitted at app.js:1628-1631 and 2774.

**Palette recommendation reversed: keep amber, option A withdrawn.** Learning A was cheap made the planner less inclined to it, not more. A is not two lines: amber is load-bearing on at least four more live surfaces on the same page, so either the editor shows two colours for one verdict or the deletion becomes a six-surface repaint. It would overrule a decision stated twice in the file by the same hand. And it spends `--danger`, which already means failure elsewhere, on "not written yet" - the normal state of a report being written. If more urgency is wanted, change weight rather than hue.

**Note:** the revised step 4 consolidates the error palette but **does not make the library offers yellow**, so as written it does not yet satisfy the fourth request. That is the first open question below.

**Open questions raised.** (1) The palette, restated below. (2) What the empty Vuln ID cell should say before a number is typed - a dash `—` (no duplication at any width, nothing else to change, the whole cell is the click target; recommended) or a word such as "Add" or "Set" (more explicit about being clickable, but the narrow-width label at taste.css:1012 must then be suppressed so it does not read "Vuln ID  Add").

## Answers

**Palette - option C: library suggestions go yellow, and gain a shape change to stay distinguishable from errors.**

Both kinds of row now use `var(--warning)`. They are told apart by form, not hue: errors keep a **solid** rail, suggestions get a **dashed** rail plus a small **"Suggested"** tag. This satisfies the request literally while keeping the panel triage-able, and it introduces no new colour token.

Retires option A (suggestions yellow, errors red) - the planner withdrew it and the user did not take it. The stated design decision at taste.css:3185-3193 stands: red is reserved for failure, not for "not written yet". Also retires option B (two yellows, indistinguishable at 3px) and option D (do nothing).

**Empty Vuln ID cell - a dash (`—`).**

The user chose the dash over the literal words "Vuln ID" from the request. This **dissolves hazard B entirely**: taste.css:1012 already injects `content: "Vuln ID"` below 960px, and a glyph placeholder cannot duplicate it, so no narrow-width label suppression is needed and taste.css:1012 is not touched.

## Agreed plan

Five steps. Steps 1 and 2 must ship in that order and cannot be separated. Steps 3, 4 and 5 are independent of each other and of 1-2.

### Step 1 - Make `[hidden]` actually hide the two display buttons

**Why first:** step 2 puts a display button on every row, and today `hidden` does nothing to those buttons. No stylesheet declares `[hidden] { display: none }`, so the author-origin `.finding-id-display { display: flex }` at overrides.css:119 beats the browser default. The button only appears to vanish because the input is lifted out of flow and painted over it (overrides.css:122). Below 960px, taste.css:1016-1024 sets `position: static !important` and removes that cover - so the button and the input stack on top of each other. This is already broken today for rows that have an ID; step 2 would spread it to every row.

**Files:** app/web/static/overrides.css - one new rule after the existing display-button declarations at lines 115 and 119.

**Change:** add `.finding-id-display[hidden], .finding-title-display[hidden] { display: none; }`. Specificity (0,2,0) beats the base (0,1,0), so source order does not matter, and the narrow-width block declares only `position`, `width`, `min-width`, `max-width` and `text-align` - never `display` - so the guard survives its `!important`s. The two inputs need nothing; their positioning rules are already guarded by `:not([hidden])` at overrides.css:118 and 122, and neither base rule declares `display`.

**Test:** new case in tests/test_browser.py - at an 800px viewport, click a populated `.finding-id-display` and assert exactly one of the button and the input is visible. Same assertion for `.finding-title-display`.

**Invariant protected:** a display button and its input are never both visible, at any viewport width.

### Step 2 - Vuln ID dash placeholder, coupled with the location box floor

**Why coupled:** the empty-blur `renderFindings()` at app.js:1773 is what currently re-runs the location textarea's auto-grow while the row is visible. `setExpanded()` at app.js:1726 hides the location row *before* `resize()` measures it at app.js:1885, so a collapsed finding gets an inline `height: 0px`. Today the rebuild washes that away. Remove the rebuild without flooring the box and the clipping becomes permanent.

**Files:** app/web/static/app.js, app/web/static/overrides.css, tests/test_browser.py.

**Changes:**

- **Vuln ID, app.js:1697-1777.** Build `.finding-id-display` unconditionally in `enhanceFindingRows`, empty or not; an empty `display_id` renders `—`. Delete the `else` branch at app.js:1777 and the `else renderFindings()` at app.js:1773; blur becomes an unconditional `setIdEditing(false); scheduleSave();`. Render `display_id` as a string - leading zeros such as `"001"` are real. If the builder is generalised across both displays, the `aria-label` strings `"Edit vulnerability ID"` and `"Edit finding name"` must survive **verbatim**; test_browser.py:869, 941 and 959 assert the title button's accessible name.
- **Location value, overrides.css:151.** Drop `height: 28px`, keep `min-height: 28px`, and replace `overflow-wrap: normal; word-break: normal` with an explicit `overflow-wrap: anywhere`. A bare deletion would work only by falling through to the browser default - declare it.
- **Location preview, overrides.css:150.** **Add** `overflow-wrap: anywhere`. There is no wrapping declaration to remove here. The preview span and the value textarea are two states of one slot and never coexist, so both need the same rule for ticked and unticked to behave identically.
- **Not touched:** taste.css:1012. The dash cannot duplicate the injected narrow-width label.

**Tests:**

- **Rewrite, do not delete, test_browser.py:810-825.** As written it will not fail after this change - it will go **vacuous**: `.finding-id-display` resolves immediately and `expanded.count() == 0` still holds, because the rebuild it exists to catch no longer happens, and its docstring at line 811 becomes false. Rename it to assert the absence of the rebuild directly: hold a JS handle to the `<tr>` before typing, then after blur assert the handle is still connected, the fold state is unchanged, and the button reads the typed value. Deleting it would lose the only coverage of fold survival.
- New case: a finding with no `display_id` shows `.finding-id-display` reading `—`; clicking it focuses the numeric input.
- New case: a long unbroken endpoint wraps rather than clips, asserted on rendered height, in **both** the ticked and unticked states.

**Invariants protected:** the table is never rebuilt while one of its cells holds focus; `expandedFindingIds` survives every ID edit; `finding.display_id` keeps exactly one writer (app.js:1912), writing `digits || null` and never `""`, which the model at models.py:184 rejects; two `<tr>` per finding, since `validateFindingsPage` indexes `children[index * 2]`.

### Step 3 - Reveal empty evidence slots on demand instead of always

**Files:** app/web/static/app.js - `updateReadinessPanel` at app.js:2649-2650, alongside the existing `reviewTargetId` state at app.js:2553.

**Change:** narrow the application of `is-incomplete` to image fragments that the tester has reached via Go-to, rather than every empty slot on load. Key the revealed set on `(finding.uid, content.type, fragment.environment)` - **never on `frag_id`**, which is reminted in three places (app.js:1062, report_service.py:411 and 439) plus legacy duplicate-id repair at workspace.py:229-235, and would silently lose its entries. Keep the set module-local and do **not** write it to `draft.json`; leave a comment saying why, because the reason is invisible from the code: `sync_evidence_image_slots` mints server-side `frag_id`s at report_service.py:382 on every PUT, and only `saved_at` is adopted back at app.js:341-345, so a persisted set would be fighting a value it never sees.

**Test:** reveal a slot, force a save, assert it stays revealed and no duplicate slot appears; then reload and assert the UI returns to the unrevealed state with no orphaned tile.

**Invariants protected:** the issue stays in the `issues` array - `#issue-count`, `.content-flag` and `generateButton.disabled` all derive from it (app.js:2645-2667) and must not change; only the class application narrows. The stale-image exemption `fragmentApplies` (app.js:2592-2595, twinned at report_service.py:322) is preserved. `provision_report` remains the sole owner of which slots exist; the client owns only which ones are shown.

### Step 4 - Library suggestions in yellow, distinguished by shape

**Files:** app/web/static/overrides.css, app/web/static/taste.css, app/web/static/app.js.

**Changes:**

- **Banners, overrides.css:302.** `.poc-offer, .content-offer` move from `border-left: 3px solid var(--accent); background: var(--accent-soft)` to the `--warning` pair, with the rail **dashed** rather than solid.
- **Panel rows.** `.review-group[data-level="warning"]` at taste.css:2072-2074 moves off blue to a dashed `--warning` rail; the error-side base it overrides is at taste.css:2063-2070, and `.review-group-count`'s error colour is at taste.css:3394-3403 - both stay amber and solid.
- **"Suggested" tag, app.js.** Add the tag to the two banner builders (`.poc-offer` at app.js:2916-2964, `.content-offer` at app.js:2975-3005) and to the offer rows built at app.js:2673-2681. **The `data-offer-for` attribute must survive** - offer rows carry no `fragmentId`, so Go-to falls back to `[data-offer-for="<type>"]` at app.js:2728 and silently does nothing if the attribute moves. `data-poc-offer` and `data-content-offer` are asserted by tests and must also survive.
- **Delete the shadowed `--danger` block at taste.css:1942-1951.** Its selectors are identical to the amber pair at taste.css:3153-3162 in the same file at the same specificity, so the later block already wins - it is a shadowed duplicate, not a live alternative, and it makes the file look like it holds two opinions about the same thing.
- **Delete `background: var(--danger)` from `.review-heading b` at overrides.css:272.** Doubly shadowed - by `background: var(--muted)` at taste.css:1996-2000 on load order, and by `#issue-count` on specificity. It is a trap: any future non-`#issue-count` badge in that heading would come out red.
- **Verify only, no change:** `.content-flag` (taste.css:3143-3150) and `#issue-count` (taste.css:2002-2013) stay amber. They report errors, not suggestions.

**Tests:** none new, and **do not add colour assertions** - they would freeze a design decision into the suite. Run the existing offer cases to confirm they stay green: test_browser.py:1106-1108, 1117, 1148, 1274-1275 (counts and attributes), plus test_browser.py:929 and 1358-1359 (`#issue-count` text and state).

**Invariants protected:** library offers never enter the `issues` array - the count and the Generate gate are computed at app.js:2645-2667 *before* offers are appended at app.js:2673, and moving them would diverge from the server's `generation_issues` at docx_report.py:93. Errors and suggestions remain distinguishable at a glance. `--danger` continues to mean failure only.

### Step 5 - Remove dead review-panel rules

**Independent and droppable.** Sequenced last so it can be cut without disturbing anything above.

**Files:** app/web/static/overrides.css, app/web/static/taste.css.

**Change:** delete the orphaned `.review-item` family (overrides.css:273-279, taste.css:1562-1588, taste.css:2015-2058), the two `.review-group-count b[data-level]` rules (taste.css:2118 and 2122), and `.finding-nav-heading .nav-count[data-state="issues"]` (taste.css:2962-2966). `renderGroup` at app.js:2694-2696 emits `.review-row` and puts `data-level` on the count span itself, with no `<b>` child; `data-state` is set on `#issue-count` alone. **Keep** the base `.finding-nav-heading .nav-count` rule at taste.css:2954-2960 - that class *is* emitted, at app.js:1628-1631 and app.js:2774. Only the `data-state` variant is dead.

**Test:** full browser suite as a regression net. No new test - dead CSS has no observable behaviour to assert.

**Invariant protected:** every selector in the stylesheets corresponds to markup something actually emits.

### Not in scope, deliberately

- **`docs/DATA_MAP.md` needs no update.** Nothing in these five steps reaches the schema. `display_id` stays `str | None` with the dash living in a button's text content and never in the input's value; the revealed-slot set is never persisted; the palette work has no server counterpart.
- **A JS twin for the cross-finding `display_id` uniqueness check** (models.py:345-347, surfacing as a 422) is not added. It is a pre-existing gap, unrelated to this change, and adding it would create a second place for that rule to drift.
- **Stored location values are not trimmed or truncated.** The overlap is a presentation fault; touching the values would enter `location_lines` (report_service.py:257) and its twin `locationLines` (app.js:1023).
- **`.finding-locations` (plural) dead CSS** at overrides.css:205-210 and taste.css:1313-1339 is left alone. It is genuinely dead but outside the review-panel cleanup, and folding it in would widen step 5's blast radius for no benefit.
