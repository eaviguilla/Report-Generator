# Thick Client app type, component scope, and the MAIN_THICK_MOBILE template

## Request

> also, there is now a mobile and thick client report templates and it is called MAIN_THICK_MOBILE.docx . Mobile and Thick Client are app types. so Thick Client will be added in the options for the scope app types. BUT mobile and thick client cannot be selected together. When one is selected, deselect the other one and vise versa. But it is okay to select web and api with mobile or thick client. also, the inputs for these are different. Instead of one text box per environment, there will be 2. Label them as well. The first text box is named Component. the other one will be Description. When a mobile or thick client is selected, you do not use MAIN.docx for the main template but the MAIN_THICK_MOBILE.docx instead. its the same template but with a table for the mobile or thick client scope.
>
> there are taggings in this docx. {{mobile-thick}} this is at the 6.1 table 10. You replace that tagging based on what the app type is. if Mobile, then Mobile. If thick client, then, Thick Client.
>
> also below that is the table for the scope of the mobile or thick client
> the taggings are {{binaries}} and {{binaries-description}}
>
> this will be populated by the scope that will be put in the fields inputed in the scope. Components for the {{binaries}}, Description for the {{binaries-description}}, there will be no separation if it is prod or non prod in generating or populating this field. but just make sure to put prod scopes first before non prods.

## Round 1 - Oracle: how it works today

> Verbatim from `data-oracle`. Evidence links are repo-root-relative as written. Section 5 was left unresolved by the oracle (no shell access to read compressed DOCX XML); the coordinator settled it directly and the findings are appended as **Coordinator addendum** at the end of this section.

### 1. The `Channel` type and the app-type selector, as they stand today

**Confirmed: the `tested_channels` list has shipped. `test_type` is gone from the model and survives only as a migration input.**

| Thing | Where | Current value |
|---|---|---|
| `Channel` | [app/models.py](app/models.py#L12) | `Literal["web", "api", "mobile"]` |
| `CHANNELS` | [app/models.py](app/models.py#L13-L15) | `("web", "api", "mobile")` — the one canonical order, deliberately in `models.py` so `docx_report` and `report_service` can both import it |
| `LEGACY_TEST_TYPE_CHANNELS` | [app/models.py](app/models.py#L17-L18) | `{"web": ["web"], "api": ["api"], "mobile": ["mobile"], "web_api": ["web", "api"]}` |
| `Engagement.tested_channels` | [app/models.py](app/models.py#L228) | `list[Channel]`, default `["web"]`, **`min_length=1`** |
| `ScopeTarget.channel` | [app/models.py](app/models.py#L159-L164) | one `Channel` per target, alongside `environment`, `value`, `order` |
| `Engagement.validate_coverage` | [app/models.py](app/models.py#L238-L244) | uniqueness only — no combination rule of any kind |

**`resolve_tested_channels` is the single owner**, [app/models.py](app/models.py#L44-L65). Precedence tests key *presence*, never truthiness:

1. both keys present → **union** ([L57-L61](app/models.py#L57-L61))
2. `tested_channels` present → used as given, reordered by `CHANNELS`, unknown tokens appended so the `Channel` literal rejects them ([L64-L65](app/models.py#L64-L65)); the only branch that can return `[]`
3. `test_type` present → expanded through `LEGACY_TEST_TYPE_CHANNELS` via `expand_legacy_test_type` ([L39-L41](app/models.py#L39-L41))
4. neither → channels present on the mapping's own `scope_targets` ([L53-L56](app/models.py#L53-L56))
5. neither, no targets → `["web"]`

**Yes, something still migrates old values, and it still fires on real files.** The hook is the `Report` `mode="before"` validator [app/models.py](app/models.py#L339-L357): it strips `test_type` at [L352](app/models.py#L352) and writes the resolved list at [L353](app/models.py#L353). `Workspace.load_path` [app/workspace.py](app/workspace.py#L271-L298) no longer has a channel branch at all. Two drafts on disk still carry `test_type` (§7).

**The Setup checkbox UI** is `renderCoverage` in [app/web/static/app.js](app/web/static/app.js#L1709-L1747). It iterates the static `CHANNELS` constant, not `tested_channels` ([L1719](app/web/static/app.js#L1719)) — deliberately, so an imported empty selection still shows boxes. The `onchange` arm confirms, purges, then rewrites `tested_channels` in `CHANNELS` order ([L1735-L1741](app/web/static/app.js#L1735-L1741)). The last remaining box is **disabled**, not guarded by a dialog ([L1731-L1734](app/web/static/app.js#L1731-L1734)). Markup host: [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L11).

### 2. Every place a channel value is enumerated or branched on

| # | Site | Location | If NOT updated for a fourth channel |
|---|---|---|---|
| 1 | `Channel` literal | [models.py#L12](app/models.py#L12) | `thick_client` **422s every save**. Nothing else matters until this changes. |
| 2 | `CHANNELS` tuple | [models.py#L15](app/models.py#L15) | `resolve_tested_channels` pushes the unknown token to the tail instead of ordering it; `normalise_scope_modes`' sort key files it last ([L299-L302](app/models.py#L299-L302)). Silent misordering, no error. |
| 3 | `affected_channels` | [report_service.py#L307-L326](app/report_service.py#L307-L326) | Nothing — data-driven off targets. **Free.** |
| 4 | `applicable_poc_variants` | [report_service.py#L329-L332](app/report_service.py#L329-L332) | Iterates `CHANNELS`; fix #2 and this is free. **Free.** |
| 5 | `reconcile_targets` per-channel loop | [report_service.py#L563-L583](app/report_service.py#L563-L583) | **Free** for the channel axis — but see #6 and §3. |
| 6 | mobile character allowlist | [report_service.py#L578-L582](app/report_service.py#L578-L582) — `if channel == "mobile"` | **A hard-coded string equality.** Thick-client scope gets *no* character validation while mobile gets a restrictive one. Asymmetric by accident. |
| 7 | JS `mobileScopeRule` | [app.js#L1351-L1359](app/web/static/app.js#L1351-L1359), wired at [L1868](app/web/static/app.js#L1868) | Same asymmetry on the client. Declared twin of #6. |
| 8 | JS `CHANNELS` | [app.js#L1130](app/web/static/app.js#L1130) | No checkbox, no textarea; the seed at [L1432](app/web/static/app.js#L1432) never creates the key, so `reconcile_targets` reads `""` and **deletes every thick-client target on the next save**. |
| 9 | JS `channelLabels` | [app.js#L1131](app/web/static/app.js#L1131) | `undefined` in the checkbox label, aria-label, removal dialog ([L1664-L1667](app/web/static/app.js#L1664-L1667)), PoC offer text. Cosmetic but visible everywhere. |
| 10 | scope-grid render | [app.js#L1842-L1880](app/web/static/app.js#L1842-L1880) | Free once #8 lands. The hard-coded `if (channel === "mobile")` note at [L1872-L1878](app/web/static/app.js#L1872-L1878) says *"Mobile scope does not appear in the generated report yet"* — **that sentence becomes a lie the moment this change ships, and its own comment tells you to delete it.** |
| 11 | Findings-page endpoint boxes | [app.js#L2143-L2190](app/web/static/app.js#L2143-L2190) | Free once #8 lands — but see §3 for the two-field problem, which lands here too. |
| 12 | `docx_report.CHANNEL_ORDER` | [docx_report.py#L46-L47](app/docx_report.py#L46-L47) | `list(CHANNELS)` — updates itself. **Free.** |
| 13 | `_metadata` scope tokens | [docx_report.py#L247-L250](app/docx_report.py#L247-L250) | Only `prod-web`/`non-prod-web`/`prod-api`/`non-prod-api`. An unreplaced `{{binaries}}` is caught by `_unresolved_placeholders` ([L1326-L1331](app/docx_report.py#L1326-L1331)) and **fails generation loudly** — the good failure mode. |
| 14 | `_populate_scope_tables` | [docx_report.py#L387-L415](app/docx_report.py#L387-L415) | Two hard-coded tables, positional cells. No binaries table → token survives → generation fails. |
| 15 | `docx_import` channel parsing | [docx_import.py#L539](app/docx_import.py#L539), [L544-L556](app/docx_import.py#L544-L556) | `_scope_rows(... "URL(s) in Scope", "web") + _scope_rows(... "API Routes", "api")` is the **only** source of targets and `tested_channels` on import. **Mobile scope is already unrecoverable on import today.** Re-importing a generated MAIN_THICK_MOBILE report silently drops the whole binaries table. |
| 16 | library `proof_of_concept` keys | [library.py#L22-L23](app/library.py#L22-L23) | Widening `Channel` widens the key set for free. **Free.** |
| 17 | **library editor channel list** | [library_editor.html#L64-L66](app/web/templates/library_editor.html#L64-L66), [#L79](app/web/templates/library_editor.html#L79) | `variants = ["web", "api", "mobile"]` plus three hard-coded textareas. **This page does not load `app.js`**, so it cannot share the constant. Not updated → the library editor silently drops any thick-client PoC list on save. This is the copy that gets forgotten. |
| 18 | `scripts/generate_showcase_reports.py` | [#L63](scripts/generate_showcase_reports.py#L63), [#L443](scripts/generate_showcase_reports.py#L443) | Fixture-only; asserts `len(channels) == 1`. Breaks only if you add a thick-client showcase. |

**Blunt read:** ten of eighteen are free or self-updating. The expensive ones are #6/#7, #15, and #17.

### 3. The scope-text shape — the hardest part

`report.scope_text[environment][channel]` is **one newline-separated string**. Seeded client-only from `scope_targets` at [app.js#L1429-L1438](app/web/static/app.js#L1429-L1438); one textarea per environment×channel at [app.js#L1845](app/web/static/app.js#L1845); **excluded from canonical reconciliation** at [app.js#L426-L427](app/web/static/app.js#L426-L427); consumed by `reconcile_targets` [report_service.py#L538-L583](app/report_service.py#L538-L583), which pops it at [L542](app/report_service.py#L542) and early-returns when absent at [L540-L541](app/report_service.py#L540-L541).

**Confirmed: it never reaches disk.** Zero occurrences of `"scope_text"` under `data/apps/`.

**Per line:** `splitlines()` → strip → drop blank → drop `#` → drop duplicates → `enumerate` for `order` → one target dict. **The reuse key is the triple `(environment, channel, value)`** — built at [L557](app/report_service.py#L557), consumed at [L583](app/report_service.py#L583). `order` restarts per (environment, channel).

**`ScopeTarget` can structurally carry a second string** ([models.py#L159-L165](app/models.py#L159-L165)); a `str = ""` default is the entire migration. What is *not* trivial is everything reading `value` as *the* location: `_target_values` [docx_report.py#L217-L222](app/docx_report.py#L217-L222), `_finding_locations` [#L1246-L1259](app/docx_report.py#L1246-L1259), `setup_issues` [report_service.py#L653](app/report_service.py#L653) (a component with only a Description would **not** count as a scope target), and `Scope.location_values` [models.py#L146](app/models.py#L146).

**The mirror problem you did not ask about:** the Findings page's "additional affected endpoints" box for a mobile/thick channel has the same one-string shape and nowhere to put a Description ([app.js#L2143-L2190](app/web/static/app.js#L2143-L2190)).

**What breaks if a channel needs two values per line:**

1. **`reconcile_targets` raises immediately.** [L565-L566](app/report_service.py#L565-L566): `if not isinstance(raw_values, str): raise ValueError("scope target values must be text")` → 422 `invalid_scope`. It runs on the **raw payload before Pydantic** ([main.py#L667](app/main.py#L667) vs [#L684](app/main.py#L684)), so no model change can reach it.
2. **The ID reuse key becomes a choice.** Include the description in the triple and editing a description remints the ID, drops it from findings' `target_ids` ([L613-L618](app/report_service.py#L613-L618)), and can strand a finding into the 422 at [L621-L622](app/report_service.py#L621-L622). Exclude it and a description edit is invisible to identity — almost certainly what you want, but it must be stated.
3. **Five client-side counters read the DOM, not the model** ([app.js#L619-L620](app/web/static/app.js#L619-L620), [#L648-L651](app/web/static/app.js#L648-L651), [#L1852](app/web/static/app.js#L1852), [#L2373](app/web/static/app.js#L2373)) and count *every* textarea in a scope panel. A second textarea means **a Description alone would satisfy "define at least one scope target"**, then 422 server-side via `setup_issues`.
4. **`survivingAfterScopeText`** [app.js#L1674-L1679](app/web/static/app.js#L1674-L1679) splits on `\n` and is the live save-blocker's predicate. **`dropChannelEverywhere`** [app.js#L1645](app/web/static/app.js#L1645) assigns `""`. Both assume string.

**Options the data model permits (no recommendation):**

- **A — second column on `ScopeTarget`** (`description: str = ""`). Costs item 1, the reuse-key decision, a new accessor beside `_target_values`, and a `_finding_locations` decision. One target per component, which is what the binaries table wants.
- **B — second channel key.** **The model forbids this.** `reconcile_targets` iterates `for channel in channels` ([L563](app/report_service.py#L563)) filtered against the `Channel` literal; a non-channel key is never read. Making it a channel makes it a real app type everywhere. Enumerable, and bad.
- **C — `scope_text[env][channel]` becomes `{component, description}`.** Same Python change as A, natural client pairing. `ScopeTarget` still needs the second column, because `scope_text` never reaches disk.
- **D — one line, delimited.** Zero schema change, but the mobile allowlist permits only `:'"/.,-_&`, so the delimiter must come from that set or the allowlist widens. The whole line becomes the reuse key, so **editing a description remints the ID**. Cheapest to build, worst to live with.
- **E — separate top-level list** (`report.scope_components`). Avoids the reuse key, `_target_values`, `setup_issues`, `custom_locations`. But a component is then **not** a scope target: it cannot be ticked as a finding's affected location, and `affected_channels` never returns the channel.

### 4. Mutual exclusion

**Precedent: none for auto-deselect.** Two adjacent patterns, neither is it: **disable the last one** ([app.js#L1731-L1734](app/web/static/app.js#L1731-L1734)), and **confirm-then-revert-on-cancel** ([#L1735-L1741](app/web/static/app.js#L1735-L1741) via `confirmChannelRemoval` [#L1658-L1671](app/web/static/app.js#L1658-L1671)).

**Blunt:** ticking Thick Client must *silently destroy every mobile scope target, every mobile `custom_locations` entry, and possibly strand findings*. `dropChannelEverywhere` [app.js#L1643-L1656](app/web/static/app.js#L1643-L1656) already does that purge and `confirmChannelRemoval` already counts the cost. "Deselect the other one" without routing through that dialog would delete a tester's typed scope with no prompt — the one behaviour this codebase has consistently refused to ship.

**Three gates, in order:** `reconcile_targets` [report_service.py#L549](app/report_service.py#L549) (raw payload); `normalise_scope_modes` [main.py#L682](app/main.py#L682); `Report.normalise_legacy_shapes` → `Engagement.validate_coverage` [models.py#L238-L244](app/models.py#L238-L244).

`resolve_tested_channels` is the **only function both gate 1 and gate 3 call**. A rule there covers the PUT path, `load_path`, `import_report`, both `parse_import` branches, and `docx_import` at once. A rule only on `validate_coverage` runs *after* `reconcile_targets` rebuilt targets for both channels, and the save dies with a raw Pydantic blob.

Also: `reconcile_targets` **only runs when the payload carries `scope_text`**, which only Setup seeds. Findings and Content PUT the whole report *including* `engagement`, so they can carry an illegal combination past gate 1 entirely.

**Today:** `{mobile, thick_client}` would pass `validate_coverage` (uniqueness only) and **save cleanly**. There is no combination rule anywhere to extend.

### 5. The DOCX template path and token substitution

`render_report_docx` takes `template_path: Path` [docx_report.py#L152-L159](app/docx_report.py#L152-L159). It doubles as the **component root** — `template_path.parent` goes to `_populate_component_findings` at [L178](app/docx_report.py#L178). **The path is never stored on the report.**

**Two independent substitution mechanisms:**

1. **Positional table cells.** `_find_table(document, header)` [#L304-L308](app/docx_report.py#L304-L308) matches on the **casefolded text of row 0, cell 0**. `_populate_scope_tables` [#L387-L415](app/docx_report.py#L387-L415) overwrites `cell(2,0)` / `cell(4,0)` by index, via `_set_cell_lines` [#L352-L372](app/docx_report.py#L352-L372) — **one paragraph per line**.
2. **Flat token replacement.** `_metadata` [#L225-L257](app/docx_report.py#L225-L257) + `_replace_metadata` [#L267-L275](app/docx_report.py#L267-L275), rewriting `{{token}}` across split runs via `replace_pattern_across_text_nodes` [docx_components.py#L402-L437](app/docx_components.py#L402-L437).

**Critical constraint for `{{binaries}}`:** `replace_pattern_across_text_nodes` writes into a **single `w:t` node** ([#L428](app/docx_components.py#L428)). A `\n` in `w:t` does not render as a line break in Word. **So the token mechanism can only ever produce one line.** Multi-row binaries content needs the `_set_cell_lines` table mechanism.

**Could not read the template.** No shell/unzip in that session. *(Coordinator resolved this — see addendum.)*

### 6. Template selection

**`Engagement.template_set` is dead.** Declared at [models.py#L236](app/models.py#L236), mirrored at [tester_identity.py#L164-L166](app/tester_identity.py#L164-L166). **Nothing reads either.**

`resources/` holds `MAIN.docx`, `MAIN_ASIA.docx`, `MAIN_THICK_MOBILE.docx`, `MAIN_THICK_MOBILE_ASIA.docx`. **`MAIN_TEST.docx` no longer exists.** Every reference points at `MAIN.docx`: [main.py#L520](app/main.py#L520) (the only production path), [generate_report.py#L17](scripts/generate_report.py#L17), [generate_showcase_reports.py#L45](scripts/generate_showcase_reports.py#L45), [compose_component_test.py#L32](scripts/compose_component_test.py#L32), and nine test sites.

**Blunt:** switching is a one-line change. The cost is that there are now **four** templates and the selection axis is two-dimensional (mobile/thick × Asia segment), with `template_set` sitting there unused as an obvious but currently meaningless hook.

### 7. What the drafts on disk contain

Nine `draft.json` files, all `schema_version: "1.4"`.

- **Every channel value on disk is `web` or `api`. Zero mobile.** The mobile path has never been exercised by a real draft.
- **`scope_text` does not exist on disk.** Zero matches across all nine.
- **`custom_locations` is `{}` on every one of the ~30 findings.**
- **Two drafts still carry the retired `test_type`** ([Northstar_Banking/…84b9ebe1bbdd](data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json#L23), [unnamed/…404ecd327eea](data/apps/unnamed/2026-09_Report_404ecd327eea/draft.json#L24)), so branch 3 of `resolve_tested_channels` is live code.

**What breaks if `Channel` gains a fourth literal and `ScopeTarget` gains a field: nothing on disk.** Widening a `Literal` is strictly permissive; a new field with a default validates against every existing file. **No `load_path` repair should be added** — a repair rewrites every draft and burns the single `draft.bak.json` level for a no-op.

The one-way door: once any report stores `"thick_client"`, reverting the literal makes that draft unloadable.

### 8. Rules that exist in BOTH Python and JavaScript

| Rule | Python | JavaScript | One-sided consequence |
|---|---|---|---|
| canonical app-type order | `CHANNELS` [models.py#L15](app/models.py#L15); `CHANNEL_ORDER` [docx_report.py#L47](app/docx_report.py#L47) | `CHANNELS` [app.js#L1130](app/web/static/app.js#L1130) **and `variants`** [library_editor.html#L79](app/web/templates/library_editor.html#L79) | Python only → no checkbox, server deletes targets. JS only → 422 every save. Forget the library editor → thick-client PoC silently dropped. |
| which app types a report covers | `resolve_tested_channels` [models.py#L44-L65](app/models.py#L44-L65) | the seed at [app.js#L1412-L1417](app/web/static/app.js#L1412-L1417) | JS falls back to `["web"]` and drops every thick-client location. |
| **mobile character allowlist** | [report_service.py#L578-L582](app/report_service.py#L578-L582) | `mobileScopeRule` [app.js#L1351-L1359](app/web/static/app.js#L1351-L1359) | **Directly in scope: does thick-client share mobile's allowlist, and does Description get the same rule as Component?** |
| which targets survive an app-type change | the loop in `reconcile_targets` [#L557-L583](app/report_service.py#L557-L583) | `findingsStrandedBy` [app.js#L1552-L1558](app/web/static/app.js#L1552-L1558); `dropChannelEverywhere` [#L1643-L1656](app/web/static/app.js#L1643-L1656) | **The mutual-exclusion auto-deselect goes through here.** |
| which targets survive a scope-text edit | same loop, reusing IDs by value | `survivingAfterScopeText` [app.js#L1674-L1679](app/web/static/app.js#L1674-L1679) — **already not an exact twin** | A two-field shape changes what "the same line" means. |
| affected app types | `affected_channels` [#L307-L326](app/report_service.py#L307-L326) | `affectedChannels` [app.js#L1133-L1145](app/web/static/app.js#L1133-L1145) | |
| a finding claims a location | `scope_has_location` [#L654-L671](app/report_service.py#L654-L671) | `scopeHasLocation` [app.js#L1115](app/web/static/app.js#L1115) | |
| which typed lines count | `location_lines` [#L270-L283](app/report_service.py#L270-L283) | `locationLines` [app.js#L1100-L1106](app/web/static/app.js#L1100-L1106) | If a Description is ever a `custom_locations` line, both must skip it. |
| setup completeness | `setup_issues` [#L626-L647](app/report_service.py#L626-L647) | `validateSetupPage` [app.js#L2373](app/web/static/app.js#L2373) | **The two-field input lands squarely here.** Client counts DOM textareas; server counts `target.value.strip()`. |

**No drift guard exists for any of these.**

### Invariants in play

1. **`reconcile_targets` runs on the raw dict, before Pydantic, and only when `scope_text` is present.** Put a guarantee in the model and it is dead on Findings/Content; put it in `reconcile_targets` and it is dead on every non-Setup save.
2. **`resolve_tested_channels` is the single owner of "which app types"** and the only function both gates call.
3. **Target identity is the `(environment, channel, value)` triple.** Violate it and IDs churn, findings strand.
4. **`tested_channels` has `min_length=1`.** Mutual exclusion must never reach zero.
5. **`scope_text` is client-only.** Any second field living only there is lost on reload; the durable home is `ScopeTarget`.
6. **No model sets `model_config`**, so Pydantic's default `extra="ignore"` **silently deletes any undeclared key on the next save.**
7. **Every unresolved `{{token}}` fails generation loudly.** Use this rather than guessing.
8. **Widening is safe; narrowing is a one-way door.**

### The blunt summary

**Cheap:** the fourth literal, `CHANNELS`, `channelLabels`, `CHANNEL_ORDER`, `affected_channels`, `applicable_poc_variants`, the library key type, the renders, the template switch, and the migration (there is none).

**Expensive:** the two-field scope input. It changes the shape of the one buffer feeding the only function that can delete scope targets, and it desynchronises a Python/JavaScript completeness pair that reads the DOM on one side and the model on the other.

**Already broken and about to get worse:** `docx_import` reconstructs scope from exactly two tables.

---

### Coordinator addendum — template facts, read directly

The oracle could not open the DOCX. Resolved with `unzip` + `python-docx`. **These are measured, not inferred.**

**Tokens actually present:**

| Template | Thick/mobile token | Binaries tokens | Extra tokens not in MAIN |
|---|---|---|---|
| `MAIN.docx` | — | — | — |
| `MAIN_THICK_MOBILE.docx` | **`{{mobile-thick}}`** | `{{binaries}}`, `{{binaries-description}}` | — |
| `MAIN_THICK_MOBILE_ASIA.docx` | **`{{thick-mobile}}`** ← reversed | `{{binaries}}`, `{{binaries-description}}` | `{{cvss-score}}`, `{{cvss-vector}}`, `{{section-number}}` |
| `MAIN_ASIA.docx` | — | — | `{{cvss-score}}`, `{{cvss-vector}}` |

**The two thick/mobile templates disagree on the token name.** `MAIN_THICK_MOBILE.docx` says `{{mobile-thick}}`; `MAIN_THICK_MOBILE_ASIA.docx` says `{{thick-mobile}}`. Whichever is unhandled fails generation loudly via `_unresolved_placeholders`. This is a defect in the template files, not in the code.

**The binaries table is real and locatable:**

```
MAIN.docx              12 tables, headers: Version, Environment, Resource, Risk Category,
                       Risk Category, Finding Severity Rating, URL(s) in Scope, User Roles,
                       API Routes, Limitations, Findings, Severity
MAIN_THICK_MOBILE.docx 13 tables — identical plus "Component" inserted at index 9,
                       between "API Routes" (8) and "Limitations" (10)
```

- `tables[9]`: **2 rows × 2 columns**
- row 0 (header): `["Component", "Description"]`
- row 1 (data): `["{{binaries}}", "{{binaries-description}}"]`
- `cell(0,0).text == "Component"`, and **"Component" is unique** across all 13 tables — so `_find_table(document, "Component")` locates it exactly, the same mechanism `URL(s) in Scope` and `API Routes` already use.

**`{{mobile-thick}}` is not in a table.** It sits in a `Caption`-styled paragraph reading `Table  {{mobile-thick}} Application Binary` — the double space is the Word `SEQ` auto-number field. So it renders as *"Table 10 Mobile Application Binary"* / *"Table 10 Thick Client Application Binary"*. That matches the request exactly and confirms the token is a plain inline substitution, suitable for `_metadata`.

**Consequence for the oracle's §5 warning:** `{{binaries}}` sits in a table cell, so it can be filled either by `_set_cell_lines` (multi-line, one paragraph per line — what `URL(s) in Scope` does) **or** by the single-line token mechanism. The oracle's constraint stands for the token path only. Because the data row is a single row with two cells, a multi-component scope must either write multiple paragraphs into each of the two cells (risking visual drift between the Component and Description columns if a description wraps) or append real table rows. **That is an open design decision for the planner.**

## Round 1 - Planner: proposal and open questions

> Verbatim from `change-planner`, given the oracle's findings and the coordinator's template facts as established.

### Understanding

Adding a fourth app type, `thick_client`, alongside `mobile`; making those two mutually exclusive with each other but freely combinable with `web` and `api`; giving those two a **two-field** scope input (Component + Description) instead of the single textarea every other app type uses; and switching the main DOCX template to `MAIN_THICK_MOBILE.docx` whenever either is covered, filling `{{mobile-thick}}` with "Mobile" or "Thick Client" and the Component/Description table with every component, production first, non-production second, with no environment separation in the table itself. **The hard part is not the fourth literal** — it is that `scope_text` is a newline-separated string that `reconcile_targets` parses on the raw payload before Pydantic ever runs, and that target identity is the `(environment, channel, value)` triple that string produces.

### Blast radius

**Model — [app/models.py](app/models.py)**

| Change | Mandatory? | Reason |
|---|---|---|
| `Channel` gains `"thick_client"` ([#L12](app/models.py#L12)) | mandatory | until this lands every thick-client save 422s |
| `CHANNELS` gains it ([#L15](app/models.py#L15)) | mandatory | canonical order; feeds `CHANNEL_ORDER`, `applicable_poc_variants`, the `normalise_scope_modes` sort key |
| new `COMPONENT_CHANNELS = ("mobile", "thick_client")` | mandatory | one constant, three uses: mutual exclusion, two-field input, component character rule. Replaces the hard-coded `== "mobile"` |
| `ScopeTarget.description: str = ""` ([#L159-L165](app/models.py#L159-L165)) | mandatory | the durable home; `scope_text` never reaches disk |
| `Engagement.validate_coverage` raises on >1 component channel ([#L238-L244](app/models.py#L238-L244)) | mandatory | the only gate covering Findings/Content PUTs, `load_path`, `import_report`, undo replay |
| `resolve_tested_channels` ([#L44-L65](app/models.py#L44-L65)) | **no change** | it must keep returning what it was given; silently dropping a channel on load would orphan its targets |
| `template_set` ([#L236](app/models.py#L236)) | **no change** | stays dead — see the template decision |

**Server — [app/report_service.py](app/report_service.py), [app/main.py](app/main.py)**

| Change | Mandatory? | Reason |
|---|---|---|
| `reconcile_targets` accepts the paired shape ([#L538-L583](app/report_service.py#L538-L583)) | mandatory | it runs on the raw dict; no model change can reach it |
| `reconcile_targets` early-raises on the illegal pair | mandatory | turns a raw Pydantic blob into a named `invalid_scope` message |
| `if channel == "mobile"` → `in COMPONENT_CHANNELS`, plus a prose rule for `description` ([#L578-L582](app/report_service.py#L578-L582)) | mandatory | otherwise thick-client scope gets no validation while mobile gets a restrictive one |
| `setup_issues` ([#L653](app/report_service.py#L653)) | **no change** | `value` stays the Component, so a Description-only row correctly does not count |
| `affected_channels`, `applicable_poc_variants`, `scope_has_location`, `location_lines` | **no change** | data-driven off targets |
| `finalized_report` template argument ([main.py#L520](app/main.py#L520)) | mandatory | the only production generation path |

**DOCX — [app/docx_report.py](app/docx_report.py)**

| Change | Mandatory? | Reason |
|---|---|---|
| new `main_template_path(report)` | mandatory | one testable owner; `template_path.parent` is also the component root |
| new `_component_rows(report)` beside `_target_values` ([#L217-L222](app/docx_report.py#L217-L222)) | mandatory | returns `(component, description)` pairs, production first |
| `_populate_scope_tables` fills the `Component` table ([#L387-L415](app/docx_report.py#L387-L415)) | mandatory | 13th table, `_find_table(document, "Component")` locates it |
| `_metadata` gains `mobile-thick` **and** `thick-mobile` ([#L225-L257](app/docx_report.py#L225-L257)) | mandatory | the two templates disagree; both spellings cost two dict entries |
| `_target_values`, `_finding_locations` | **no change** | `value` is still the printed location |
| `CHANNEL_ORDER` ([#L47](app/docx_report.py#L47)) | free | it is `list(CHANNELS)` |

**Client — [app/web/static/app.js](app/web/static/app.js)**

| Change | Mandatory? | Reason |
|---|---|---|
| `CHANNELS` ([#L1130](app/web/static/app.js#L1130)), `channelLabels` ([#L1131](app/web/static/app.js#L1131)) | mandatory | missing → no checkbox, no seed, server deletes every thick-client target |
| new `COMPONENT_CHANNELS` twin + `componentText()` / `emptyScopeText()` helpers | mandatory | five call sites read `scope_text` as a string |
| seed ([#L1429-L1438](app/web/static/app.js#L1429-L1438)) | mandatory | must create the object shape for component channels |
| checkbox `onchange` ([#L1735-L1741](app/web/static/app.js#L1735-L1741)) | mandatory | the mutual-exclusion swap |
| scope-grid render ([#L1845-L1878](app/web/static/app.js#L1845-L1878)) | mandatory | two labelled textareas, `data-scope-field`, and **delete the stale "does not appear in the generated report yet" note** |
| `mobileScopeRule` ([#L1351-L1359](app/web/static/app.js#L1351-L1359)) | mandatory | declared twin of the Python allowlist |
| `survivingAfterScopeText` ([#L1674-L1679](app/web/static/app.js#L1674-L1679)), `dropChannelEverywhere` ([#L1645](app/web/static/app.js#L1645)) | mandatory | both assume string |
| three DOM counters ([#L619-L620](app/web/static/app.js#L619-L620), [#L648-L651](app/web/static/app.js#L648-L651), [#L1852](app/web/static/app.js#L1852)) | mandatory | narrow to `[data-scope-field="component"]` |
| Findings endpoint boxes ([#L2143-L2190](app/web/static/app.js#L2143-L2190)) | **no change** | decided one-field; see risks |

**Library editor** — `variants` at [library_editor.html#L79](app/web/templates/library_editor.html#L79) and the PoC textareas at [#L64-L66](app/web/templates/library_editor.html#L64-L66) — **mandatory**. Third hard-coded channel list; the page does not load `app.js`. Missed → thick-client PoC lists silently dropped on save.

**Import** — `_scope_rows` call site at [docx_import.py#L539](app/docx_import.py#L539) — **optional**, sequenced last.

**Tests, docs** — `tests/test_app.py`, `tests/test_docx.py`, `tests/test_browser.py`, optionally `tests/test_docx_import.py`. [docs/DATA_MAP.md](docs/DATA_MAP.md) mandatory, [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md) mandatory.

### Decisions, argued

**1. The scope shape: A + C together, not either alone.**

`ScopeTarget.description: str = ""` (A) **and** `scope_text[env][channel]` accepting `{"component", "description"}` (C). They are not alternatives — C is the transport, A is the durable home, and C without A loses every description on reload.

*The pairing rule.* Both boxes split on `\n`. Pair by **raw index, before cleaning** — `zip_longest(component_lines, description_lines, fillvalue="")` — then apply today's clean rules to the component half, carrying its description along. A blank or `#` component line still consumes its index, so a comment in the Component box cannot shift every description below it onto the wrong row. A description with no component at that index is discarded.

*Web and API stay a plain string.* The object shape is produced only for component channels, and `reconcile_targets` accepts both forms for any channel. This keeps ~40 existing test payloads green unchanged, and means a browser tab cached before the deploy degrades to "components with no descriptions" rather than 422ing every save.

*Does a Description-only row count as a scope target?* **No.** The Component is the identity. `setup_issues` needs no change — it already requires `target.value.strip()`, and `value` is still the Component. The client must be narrowed to match, or a Description-only entry looks complete and then 422s.

*Does editing a Description remint the target ID?* **No.** The reuse key stays `(environment, channel, value)`. Any other answer means a tester fixing a typo silently drops the target from every finding's `target_ids` and can strand one into the refusal at [report_service.py#L621-L622](app/report_service.py#L621-L622).

*Rejected:* **B** (model forbids it — a non-channel key is never read, and making it a channel makes it a real app type everywhere). **D** (delimiter must come from `:'"/.,-_&`, and the whole line becomes the reuse key). **E** (a component would not be a scope target, so it could not be ticked as a finding's affected location — guts the Findings page for the one app type this exists to serve). **A alone** (there is no other transport; a sibling key is eaten by `extra="ignore"`).

**2. Mutual exclusion: route the outgoing channel through the existing confirm-and-purge.**

`confirmChannelRemoval` ([#L1658-L1671](app/web/static/app.js#L1658-L1671)) already counts the damage; `dropChannelEverywhere` ([#L1643-L1656](app/web/static/app.js#L1643-L1656)) already performs the purge. Critically, `confirmChannelRemoval` returns `true` **with no dialog** when there is nothing to lose ([#L1660](app/web/static/app.js#L1660)) — so on an empty panel the behaviour is exactly the silent instant swap requested. The two diverge only when the tester has typed something.

Server-side the rule goes in **two places**: `Engagement.validate_coverage` raises (the floor; the only gate Findings/Content PUTs pass, and those carry `engagement` without `scope_text`), and `reconcile_targets` checks the **resolved** channel list before building targets (without it, the Setup save rebuilds targets for both channels then dies with a raw Pydantic blob).

**3. Binaries table: cloned rows, not multi-paragraph cells.**

Append one real table row per component, cloning the data row as a prototype — the `User Roles` pattern already fifteen lines above in the same function. Multi-paragraph cells would put N components in cell (1,0) and N descriptions in (1,1); **the moment one description wraps to two lines, every description below sits against the wrong component — silently, in the delivered report**. Cloned rows also give real borders and correct page-break behaviour. **The empty case must still emit one `N/A` row**, or the untouched prototype survives with raw tokens and `_unresolved_placeholders` raises.

**4. Template selection: a one-axis function, and leave Asia alone.**

A small pure function returning `MAIN_THICK_MOBILE.docx` when `tested_channels` intersects `COMPONENT_CHANNELS`, else `MAIN.docx`. A function, not an inline ternary, because `template_path.parent` doubles as the component root and that coupling deserves one visible owner.

*Do not add the Asia axis.* Both Asia templates carry `{{cvss-score}}` and `{{cvss-vector}}` (and `MAIN_THICK_MOBILE_ASIA.docx` also `{{section-number}}`) for which **no field exists anywhere on the model**. Selecting either fails generation — correctly, but on a path nobody asked for.

*Do not wire `template_set`.* The determinant is `tested_channels`, not a stored string. Leave it as the hook for the Asia dimension later.

*The token mismatch is handled in code, not by editing the DOCX.* Both `mobile-thick` and `thick-mobile` in `_metadata` with the same value. `_replace_metadata` no-ops on an absent token, so `MAIN.docx` is unaffected.

### Data risks

| Area | What could go wrong | Verdict | Mitigation |
|---|---|---|---|
| Raw payload before Pydantic | `reconcile_targets` runs on the raw dict at [main.py#L667](app/main.py#L667) before validation at [#L684](app/main.py#L684) and raises on a non-string at [report_service.py#L565-L566](app/report_service.py#L565-L566). A model-only change is invisible to it → 422 on every Setup save | **RISK** | Python accepts the paired shape in a commit strictly preceding the JS that sends it; `str` stays valid so a cached tab degrades instead of 422ing |
| ID reuse key | `description` in the identity triple means a typo remints the ID, drops it from `target_ids`, can strand a finding | **RISK** | Key stays `(environment, channel, value)`. Named test: edit only a description, assert `target_id` unchanged |
| `setup_issues` vs the DOM counter | Server counts `target.value.strip()`; client counts *every* `#scope-grid textarea`. A Description-only entry looks complete, then 422s | **RISK** | `data-scope-field="component" \| "description"`; narrow the three counters |
| Mutual exclusion destroying typed scope | A literal auto-deselect purges targets, endpoints, strands findings, no prompt, no undo | **RISK** | Route through `confirmChannelRemoval` + `dropChannelEverywhere`; silent when the count is zero (Question 1) |
| `min_length=1` floor | Untick-then-tick momentarily empties `tested_channels`; a save in that window 422s. Cancelling must restore *both* boxes | **RISK** | Single assignment for the next list; revert the incoming checkbox on cancel; no `scheduleSave` between states |
| `extra="ignore"` | Any second value outside a declared field is silently deleted on the next save | **RISK** | Declare `ScopeTarget.description`. Also why E would still need a declared field |
| Findings-page mirror | "Additional affected endpoints" for a component channel has one box, nowhere for a Description | **clear** | Deliberate. A typed endpoint is a *location*, not a component; `_populate_scope_tables` reads `scope_targets` and never `custom_locations`. Write it down or someone will "fix" it |
| `docx_import` losing the binaries table | A generated report re-imported drops every component | **RISK** | Already true for mobile. Optional step 7; the **environment is unrecoverable by design** because the table has no prod/non-prod split |
| Token spelling mismatch | Handling one leaves the other unresolved → `ReportGenerationError` on the Asia template | **RISK (contained)** | Both keys in `_metadata`. Fails loudly, never silently |
| Two-dimensional template selection | The Asia pair carries three tokens with no model data → generation raises the moment either is selected | **RISK** | Select on the component axis only; Asia stays on `MAIN.docx` |
| Prototype row on empty scope | Empty component list → the `{{binaries}}` row survives → generation raises | **RISK** | Mirror the `User Roles` empty state: one `N/A` row. Named test |
| `dropChannelEverywhere` empty shape | Assigns `""`; next render reads `.component` of a string → `undefined` in the textarea | **RISK** | One `emptyScopeText(channel)` helper for seed and drop; one `componentText(value)` reader |
| Rule drift — library editor | Third hard-coded list, in a page that cannot import `app.js` | **RISK** | Update `variants` + fourth textarea in the same commit as the literal |
| Rule drift — character allowlist | `== "mobile"` gives thick client *no* validation | **RISK** | `in COMPONENT_CHANNELS` both sides; Description reuses the existing **Limitations** prose set rather than a fourth rule |
| Schema break / legacy repair | Would an existing draft fail? | **clear** | Widening a `Literal` is permissive; a defaulted field validates against all nine. **No `load_path` repair** — it would rewrite nine files and burn the backup level for a no-op |
| One-way door | Once a draft stores `"thick_client"`, reverting makes it unloadable | **RISK (accepted)** | Inherent. Named because the exclusion rule must be right first time |
| Stale write | New mutation path needing `saved_at`? | **clear** | Setup already PUTs the whole report with `saved_at` |
| Lost update | Read-then-write outside `Workspace._locked`? | **clear** | Generation runs inside `workspace.locked_report`; selection is a pure read |
| Backup exhaustion | Second textarea = second `scheduleSave` source | **clear** | Same debounced save; a tester types one box at a time |
| Navigation trap | New required field blocking a page? | **clear** | Description is never required; the Setup gate still keys on the Component |
| Derived-state fight | Anything overwriting what the browser set? | **clear, with a note** | `provision_report` touches neither. But `reconcile_targets` *does* write resolved `tested_channels` back at [#L555-L556](app/report_service.py#L555-L556) — the exclusion check must run against that resolved list |
| Orphan reference | Can a `target_id` outlive its target? | **clear** | Creation and survivor filter unchanged; only a second field rides along |

### Ordered steps

Python precedes JavaScript throughout. Reversing any of the first five leaves the tree in a state where every Setup save 422s.

1. **Widen the model** — `Channel`, `CHANNELS`, `COMPONENT_CHANNELS`, `ScopeTarget.description`. *Test:* `thick_client` orders last; an existing `test_type` draft still loads unchanged. *Invariant:* widening is permissive; no `load_path` repair.
2. **The exclusion rule, both gates** — `validate_coverage` + `reconcile_targets` early check. *Test:* a Setup PUT with both → 422 `invalid_scope` with a readable message; **a Findings PUT with both** (no `scope_text`) is also refused — the test that earns the model-level rule its place. *Invariant:* `tested_channels` never empties; no path stores the illegal pair.
3. **The paired shape in Python** — accepts `str` or `{component, description}`; `zip_longest` before cleaning; `COMPONENT_CHANNELS` allowlist. *Tests:* paired input carries descriptions; **editing only a description keeps the `target_id`**; a description with no component creates no target; the plain-string form still works. *Invariant:* identity is the triple; a Description never creates or renames a target.
4. **Generation** — `_component_rows`, cloned-row fill, both caption tokens, `main_template_path`, the `main.py` call. *Tests:* thick-client renders against `MAIN_THICK_MOBILE.docx` with **no unresolved placeholders**; production rows first; empty list → one `N/A` row; caption reads "Thick Client"/"Mobile"; web-only still selects `MAIN.docx`. *Invariant:* every unresolved token fails loudly.
5. **The client** — constants, helpers, seed, swap, two labelled textareas, narrowed counters, `survivingAfterScopeText`, `dropChannelEverywhere`, character rules, and **deletion of the stale scope note**. *Tests:* ticking Thick Client unticks Mobile; with scope typed, the swap prompts and cancelling restores both; a Description-only entry fails the gate; paired values survive save-and-reload. *Invariant:* no typed scope deleted without a prompt; `tested_channels` never momentarily empty.
6. **The library editor** — `variants` + a fourth textarea. *Invariant:* no third copy drifts.
7. **(Optional, last) Import recovery** — parse the `Component` table. *Invariant:* import never silently discards a whole table.
8. **Docs** — `DATA_MAP.md`, `DOCX_TEMPLATE.md`, this file.

### What the planner would not do

- **Would not put the exclusion rule in `resolve_tested_channels`.** Tempting — one edit covers every entry path. But it returns a list and runs during load. Dropping a channel there means opening a draft silently deletes an app type while its `scope_targets` stay behind. Raising there demotes the draft to the legacy list instead of being fixable. The cost is duplicating one `if`.
- **Would not put the description into `scope_text` only.** It would vanish on the first reload — silent, delayed, and indistinguishable from the tester's own mistake.
- **Would not fill the binaries table with multi-paragraph cells.** Guarantees the first wrapping description misaligns every row beneath it, with no error anywhere.
- **Would not select either Asia template.** The "complete" two-axis version breaks generation for Asia engagements that work today.
- **Would not add a `load_path` repair.** A defaulted field already validates against all nine drafts.

## Round 2 - Oracle: verdict on the proposal

> Verbatim from `data-oracle`, checking the planner's claims against source.

### A. Risk rows that are wrong, in either direction

**A1. `setup_issues` needs no change — planner is right. I doubted it; it is correct.** [report_service.py#L644](app/report_service.py#L644) reads `if not any(target.environment == environment and target.value.strip() ...)`. It tests `value`, nothing else. If `value` stays the Component, `setup_issues` is genuinely untouched.

One thing the planner did not say and should: **`description` gets no character validation on any non-Setup path.** The allowlist lives at [#L578](app/report_service.py#L578) inside `reconcile_targets`, which early-returns when `scope_text` is absent. A Findings or Content PUT carries `scope_targets` with descriptions and nothing validates them. That hole already exists for `value`, so it is not new — but the plan adds a second free-text field to the same unvalidated surface and should name it.

**A2. Findings-page boxes need no change — marked `clear`, and the justification is wrong.** The planner's reason: *"a typed endpoint is a location not a component; `_populate_scope_tables` reads `scope_targets` and never `custom_locations`."* The second half is true. The implied conclusion is false:

- `affected_channels` **does** consume them ([#L307-L326](app/report_service.py#L307-L326)) — a typed `thick_client` endpoint makes the finding a thick-client finding.
- `scope_has_location` **does** consume them ([#L654-L671](app/report_service.py#L654-L671)) — a finding with no scope target and one typed thick-client line passes the Content gate.
- **They reach the DOCX.** [`_finding_locations`](app/docx_report.py#L1246-L1259) walks `custom_locations` over `CHANNEL_ORDER` and appends every value into the printed location list.

The delivered report will contain thick-client "locations" typed on the Findings page, printed with no Description, beside a binaries table built only from `scope_targets`. That may still be right, but **rewrite the row as**: *typed component lines print as affected locations and never as binaries rows; that asymmetry is deliberate.*

**A3. `_replace_metadata` no-ops on an absent token — planner is right.** [#L267-L275](app/docx_report.py#L267-L275) compiles `\{\{\s*token\s*\}\}` and runs across every root. No match, no write, no error. The plain-word second pattern only fires for `PLAIN_METADATA_TOKENS` ([#L53](app/docx_report.py#L53)), which these are not. Safe.

**A4. `provision_report` touches neither — planner is right.** [main.py#L261-L265](app/main.py#L261-L265) calls `provision` (writes only `contents`) and `sync_evidence_image_slots` (reads `scope_targets`, writes only `contents` and `fragment.environment`).

**A5. "~40 existing test payloads" — 37, and one breaks.** 37 `scope_text` assignments, all in `tests/test_app.py`. They stay green *if* `str` remains valid. But [tests/test_app.py#L713](tests/test_app.py#L713) asserts the exact string `'Production Mobile scope contains invalid character: "!" (exclamation mark)'`, built inline at [report_service.py#L579-L580](app/report_service.py#L579-L580) from a hard-coded `"Mobile"`. Replacing `== "mobile"` with `in COMPONENT_CHANNELS` forces a channel→label lookup, and **Python has no channel label table** (see B5).

**A6. `normalise_scope_modes` — free, planner's silence is correct.** Its sort key ([models.py#L272-L302](app/models.py#L272-L302)) handles a fourth entry, and it never sees `scope_text` because `reconcile_targets` pops it first.

**A7. `min_length=1` untick-then-tick — marked RISK, structurally unreachable.** The current handler is already a single assignment ([app.js#L1737-L1739](app/web/static/app.js#L1737-L1739)); the swap is one extra predicate in the same filter, `scheduleSave()` fires once after, and the incoming channel is always in the result. **Demote to a coding-style note.**

**A8. The row the planner is missing entirely: the exclusion rule in `validate_coverage` demotes drafts on load — the exact objection it used to reject `resolve_tested_channels`.** `load_path` ends in `Report.model_validate` ([workspace.py#L298](app/workspace.py#L298)) → `normalise_legacy_shapes` → `validate_coverage`. A raise there is a `ValidationError` on load, demoting the draft to the legacy list. The planner wrote *"Raising there demotes the draft to the legacy list instead of being fixable"* as its reason for keeping the rule **out** of `resolve_tested_channels`. **That argument applies verbatim to `validate_coverage`. The plan is internally inconsistent.**

One live path: the **union branch** ([models.py#L57-L61](app/models.py#L57-L61)). A file carrying both `tested_channels: ["thick_client"]` and legacy `test_type: "mobile"` unions to the illegal pair and becomes permanently unopenable. Either accept it and say so, or make `validate_coverage` raise only when both were *submitted*, not when the union produced them.

### B. What the planner missed

**B1. The `User Roles` cloned-row pattern — real, not invented.** [docx_report.py#L401-L415](app/docx_report.py#L401-L415): `deepcopy(accounts.rows[1]._tr)` as prototype, remove all data rows, append one `_Row` per account, and an `N/A` row when none. Two corrections: it starts at **line 401, not 404**, and it is the **last** block in `_populate_scope_tables`, not "fifteen lines above" anything. `_populate_summary_table` uses the same idiom at [#L423](app/docx_report.py#L423).

**B2. No `deepcopy` row-append helper exists, in either module.** `_set_cell_lines` writes *into* one cell. `docx_components.py` has no row helper at all. So the binaries table means a **third** hand-rolled copy of the clone-prototype idiom. Worth extracting one helper; the planner treated it as free reuse.

**B3. The DOM counters: four sites, not three. This is the significant miss.**

| Site | Selector |
|---|---|
| [app.js#L619](app/web/static/app.js#L619) `updateSetupValidationNotice` | `.scope-panel.${environment}` → `querySelectorAll("textarea")` |
| [app.js#L649](app/web/static/app.js#L649) `setupSectionSummary` | `#scope-grid textarea` |
| [app.js#L1852](app/web/static/app.js#L1852) `textarea.oninput` | `#scope-grid textarea` **and** `#scope-grid textarea.validation-error` |
| [app.js#L2373](app/web/static/app.js#L2373) **`validateSetupPage`** | `.scope-panel` → `querySelectorAll("textarea")`, plus the reveal branch |

`validateSetupPage` is the **save-blocking gate** and the declared JS twin of `setup_issues`. The planner dropped it. Without narrowing it, a Description-only entry passes the client gate and 422s server-side — **precisely the failure the planner's own risk row claims to mitigate.** The reveal branch also needs a decision: today it marks and focuses every textarea in the panel; with two boxes it should target the Component.

**B4. `dropChannelEverywhere` is listed, but the `localStorage` recovery path is not — and it fails silently.** `persistLocalDraft` serialises the whole `report` including `scope_text` ([app.js#L305-L312](app/web/static/app.js#L305-L312)); a cached draft is restored wholesale at [#L86](app/web/static/app.js#L86). The seed only fills when the value is `=== undefined` ([#L1433](app/web/static/app.js#L1433)), so a **string** written by a pre-deploy tab survives into the new code. Then `report.scope_text[env][channel].component = textarea.value` assigns a property to a **string primitive** — and `app.js` is a classic-script IIFE with **no `"use strict"`** ([#L1](app/web/static/app.js#L1)), so that assignment **silently no-ops**. The tester types, nothing is stored, the stale string is PUT, and the server rebuilds the old targets. Silent loss, no error.

The planner's "a cached tab degrades rather than 422ing" is true of the *server* contract and false of the *browser* recovery contract. **Fix:** the seed must upgrade a string, not just fill an `undefined`.

**B5. Python has no channel label table.** `f"{environment_label} Mobile scope"` at [#L579](app/report_service.py#L579) is the only place a channel is named in Python prose. Generalising requires a `CHANNEL_LABELS` constant in `models.py` — a **fourth** channel-keyed table with a JS twin. The plan lists neither the constant nor the test it breaks (A5).

**B6. Mutual-exclusion dialog copy is wrong for a swap.** `confirmChannelRemoval` hard-codes *"Remove Mobile from the scope?"* / *"Keep this app type"*. During a swap the tester ticked **Thick Client** and gets a dialog about removing Mobile. Title, message and cancel label all need a swap variant. The impact counts themselves are correct. Confirmed: it returns `true` with no dialog when nothing is at stake ([#L1660](app/web/static/app.js#L1660)) — the silent-swap claim is right.

**B7. Duplicate components collapse, and the pairing spec does not cover it.** The loop has `if not value or value.startswith("#") or value in seen: continue` ([#L573](app/report_service.py#L573)). The planner specified that blank and `#` lines consume their index but said nothing about **duplicates**. Two binaries with the same name and different descriptions — plausible for two builds — silently lose the second row *and* its description. Correct for URLs; a behaviour change in meaning for a Component/Description pair. Decide and write it down.

**B8. `export_bundle` / `import_report` round-trip — safe, with one one-way door.** A `description: str = ""` validates against a payload omitting it. Old export → new build: `""`. **New export → old build: `extra="ignore"` deletes it silently.** Deserves its own line.

**B9. Tests asserting on `ScopeTarget`'s field set or `CHANNELS` length — none.** No browser test targets `#scope-grid`, `.scope-panel`, or `.coverage-option`, so narrowing breaks nothing — but **no browser test currently covers the Setup scope gate**, so step 5's tests are net-new coverage, not a regression suite.

**B10. `docx_import` is safer than the plan implies.** It resolves tables **by header**, not index ([docx_import.py#L311-L316](app/docx_import.py#L311-L316)), so inserting "Component" at index 9 breaks nothing on import. A re-imported thick-client report lands visibly incomplete rather than corrupt. "Optional, last" is right, for a stronger reason than given.

**B11. Scripts were not mentioned at all.** `generate_showcase_reports.py` asserts a single channel; `generate_report.py` and `compose_component_test.py` hard-code `MAIN.docx`. Fixture-only, but they belong in the blast radius as "no change, and here is why".

### C. Does the proposed shape break any `draft.json` on disk?

Nine drafts re-checked. **`scope_text` on disk: zero occurrences**, across all nine and all `draft.bak.json`. Every channel value is `web` or `api` — zero `mobile`, obviously zero `thick_client`. **`ScopeTarget.description` defaulting is genuinely free** — no entry carries a `description` key. **The exclusion rule cannot make any existing draft unloadable**: no draft carries `mobile`, none can carry `thick_client`, and the two with `test_type` have no `tested_channels`, so the union branch cannot fire. **No `load_path` repair is needed.**

**C verdict: nothing on disk breaks. The disk-level risk is zero. The risk is entirely in `localStorage` (B4), which is not disk but is cached state the plan treats as safe.**

### Both-sides warning

| Rule | Python | JavaScript |
|---|---|---|
| canonical app-type order | `CHANNELS` [models.py#L15](app/models.py#L15), `CHANNEL_ORDER` [docx_report.py#L47](app/docx_report.py#L47) | `CHANNELS` [app.js#L1130](app/web/static/app.js#L1130) **+ `variants`** [library_editor.html#L79](app/web/templates/library_editor.html#L79) |
| component character allowlist | `invalid_character_issue` in `reconcile_targets` [#L578](app/report_service.py#L578) | `mobileScopeRule` [app.js#L1351-L1359](app/web/static/app.js#L1351-L1359) |
| **channel display labels (new)** | **does not exist — must be created** | `channelLabels` [app.js#L1131](app/web/static/app.js#L1131) |
| setup completeness | `setup_issues` [#L626-L647](app/report_service.py#L626-L647) | `validateSetupPage` [#L2373](app/web/static/app.js#L2373) **+ three counters** |
| `COMPONENT_CHANNELS` (new) | `models.py` | `app.js` |

### Verdict

**Safe with the corrections listed — but two of them are load-bearing, not cosmetic.**

The shape decision (A+C), the reuse-key decision, the cloned-row table, the Asia exclusion, and the no-repair call are all correct and correctly argued. `setup_issues`, `_replace_metadata`, `provision_report`, and the disk analysis are all right, **including two I doubted**.

Two things must change before it ships:

1. **`validateSetupPage` is missing from the counter list.** It is the gate, not a display. Miss it and the plan's own headline mitigation does not work.
2. **The `scope_text` seed must upgrade a cached string, not just fill an `undefined`.** Without it, a restored local draft silently swallows every keystroke in the scope boxes, in sloppy mode, with no error.

And one argument must be reconciled rather than patched: the plan rejects `resolve_tested_channels` because raising there demotes a draft, then puts a raise in `validate_coverage`, reached from the same load path. **Pick a position.**

## Round 2 - Planner: revised plan

_pending_

## Answers

_pending_

## Agreed plan

_pending_
