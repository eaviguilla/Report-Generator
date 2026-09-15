# Retire scope mode "all"

## Request
Option 2 from the diagnosis of "why can I still go to the contents page even if I have not selected at least 1 affected location in the findings page for every vuln":

> **Retire the mode** — default `Scope.mode` to `"custom"` and convert legacy `"all"` drafts to explicit custom-plus-all-targets on load. "No ticks means blocked" becomes true everywhere. Touches the model, the legacy-repair path, and a rule that exists in both Python and JavaScript.

### Diagnosis this follows from

`scope_has_location` does not ask "did the tester tick a box", it asks "does this finding's scope *mode* resolve to any location":

- `mode: "custom"` needs actual `target_ids` or typed-in locations.
- `mode: "all"` returns true whenever the **report** has any scope target. No selection needed.
- `mode: "all_production"` / `"all_non_production"` return true if any target exists in that environment.

So a `mode: "all"` finding satisfies `finding_is_complete` the moment Setup has one target, and `/edit` lets the tester through. Meanwhile the Findings page draws ticked checkboxes only for custom-mode findings, so such a finding renders with **every box unticked** while the model says it affects everything. Display and rule disagree.

Confirmed in real data: report `c6ff01abda9e` holds 14 findings, all `mode: "all"` with all 4 target ids filled in. Every other draft on disk is `mode: "custom"`.

All current creation paths already set `"custom"` (Add finding, the editor's Add vulnerability, the server's `insert_library`, and the DOCX import's `_detail_locations`). But `Scope.mode` still defaults to `"all"` in `app/models.py`, so anything constructed without an explicit scope lands there. The Findings page has no control that can produce `"all"` any more — the checkboxes are the only scope UI and touching them switches the finding to `"custom"` — so `"all"` is a state the interface can neither create nor display, while both completeness rules still honour it.

## Round 1 - Oracle: how it works today

# Oracle: how scope mode works today

## 0. What the working tree has already overtaken

Three claims in the diagnosis need correcting against the current working tree.

**The 14 target ids in `c6ff01abda9e` were not written by a tester or by the server — the Findings page wrote them.** The previous revision on disk still holds the original shape: `draft.bak.json` has `"mode": "all"` with `"target_ids": []`. The current revision has the same `"mode": "all"` with all four ids present. What sits between the two revisions is this, which runs on every Findings-page render before the table is drawn:

```js
report.vulnerabilities.forEach(finding => {
  if (finding.scope?.mode !== "custom") finding.scope.target_ids = scopeTargetIds(finding.scope);
});
```

[app.js#L1485-L1487](../../app/web/static/app.js#L1485-L1487). It resolves the mode to ids, writes them into the live `report` object, and leaves `mode` alone. Nothing on the server objects, because `validate_references` skips `target_ids` on non-custom modes. So **half the proposed migration is already running, client-side, unversioned, and server-unvalidated** — it populates `target_ids` but never flips `mode`, producing exactly the hybrid state the plan wants to eliminate. This also means the migration's data-fidelity question is already settled favourably for this one report, and would be for any report whose Findings page has been opened and saved since that line appeared.

**The Python and JavaScript halves of "does this scope reach a location" have diverged in plumbing, not in predicate.** `scopeReaches` now takes a third `coverage` argument and filters `custom_locations` by the environments and app types the engagement still covers ([app.js#L1233-L1247](../../app/web/static/app.js#L1233-L1247)). Python has no such parameter; `reconcile_targets` gets the same effect by capturing `reached_before` at [report_service.py#L512](../../app/report_service.py#L512) **before** narrowing `scope["custom_locations"]` in place at [L515-L522](../../app/report_service.py#L515-L522), then calling `_scope_reaches_a_location` again against the narrowed scope at [L529](../../app/report_service.py#L529). Same answer, opposite mechanism: one mutates, one passes context. Any change to this rule has to be made twice, in two shapes.

**`_scope_reaches_a_location` already defaults a missing mode to `"custom"`** — `mode = scope.get("mode", "custom")` at [report_service.py#L441](../../app/report_service.py#L441). Its own caller does not: `reconcile_targets` branches on `if scope.get("mode") == "custom"` at [L524](../../app/report_service.py#L524), so a payload scope with no `mode` key is treated as custom by the helper and as non-custom by the loop around it, **inside the same function**. Flipping the Pydantic default does not fix this, because `reconcile_targets` runs on the raw dict before `Report.model_validate` ([main.py#L662](../../app/main.py#L662) vs [L676](../../app/main.py#L676)).

Confirmed unchanged from the diagnosis: all four creation paths already write `"custom"` — Add finding ([app.js#L1884](../../app/web/static/app.js#L1884)), the editor's Add vulnerability ([app.js#L2668](../../app/web/static/app.js#L2668)), `insert_library` ([main.py#L716-L719](../../app/main.py#L716-L719)), and the DOCX import's `_detail_locations` ([docx_import.py#L364](../../app/docx_import.py#L364), with the no-table fallback at [L465](../../app/docx_import.py#L465)). And the only scope control on the page rewrites the scope to custom when touched ([app.js#L1845](../../app/web/static/app.js#L1845)).

---

## 1. Every consumer of `scope.mode`

### Python — direct readers

| Function | Reads mode at | Per-mode behaviour | After the change |
|---|---|---|---|
| `Report.validate_references` | [models.py#L302](../../app/models.py#L302) | `custom`: every `target_ids` entry must exist in `scope_targets`. Any other mode: `target_ids` unchecked | The check becomes universal. This is the one consumer where "stops appearing in data" is not neutral — see §2 |
| `affected_environments` | [report_service.py#L262](../../app/report_service.py#L262), [L270](../../app/report_service.py#L270), [L273](../../app/report_service.py#L273), [L275](../../app/report_service.py#L275) | `custom`: environments of selected targets, plus any environment with a non-blank typed location. `all`: every environment present in `scope_targets`. `all_production` / `all_non_production`: that one environment if any target has it | The three non-custom branches become dead. Delete or leave as unreachable |
| `affected_channels` | [report_service.py#L290](../../app/report_service.py#L290) | `custom`: channels of selected targets plus channels of typed locations. Otherwise: every channel of every target whose environment is affected ([L299-L303](../../app/report_service.py#L299-L303)) | The `else` branch becomes dead |
| `_scope_reaches_a_location` | [report_service.py#L441](../../app/report_service.py#L441), [L443](../../app/report_service.py#L443), [L447](../../app/report_service.py#L447), [L449](../../app/report_service.py#L449) | `custom`: intersection of `target_ids` with the given target list, else any non-blank typed location. `all`: any target at all. Environment modes: any target in that environment | Collapses to the custom branch. Note it already defaults a missing key to custom |
| `reconcile_targets` | [report_service.py#L524](../../app/report_service.py#L524) | `custom`: 422 if **any** submitted `target_id` is missing from the new set, else 422 if it reached a location before and none after. Non-custom: only the before/after check | Every finding takes the strict branch. This is the largest behavioural change in the whole plan — see §7 |
| `scope_has_location` | [report_service.py#L570](../../app/report_service.py#L570), [L572](../../app/report_service.py#L572), [L574](../../app/report_service.py#L574) | `custom`: non-empty `target_ids` **or** a non-blank typed location. `all`: report has any target. Environment modes: report has a target in that environment | "No ticked box means blocked" becomes universally true. This is the objective |
| `docx_report._finding_locations` | [docx_report.py#L1006](../../app/docx_report.py#L1006), [L1012-L1016](../../app/docx_report.py#L1012-L1016) | `custom`: iterates `scope.target_ids` **in stored order**, printing `location_values[target_id]` when the tester overrode the text. Non-custom: iterates `scope_targets` sorted by `(CHANNEL_ORDER.index(channel), order)` and prints `target.value` verbatim. Typed locations append after, whatever the mode ([L1020-L1025](../../app/docx_report.py#L1020-L1025)) | **Printed output can reorder.** A converted finding prints its locations in `target_ids` order, not channel order, and becomes eligible for `location_values` overrides it never had. The `{...}[mode]` dict lookup is also a latent `KeyError` for any mode not in its three keys |

### Python — indirect consumers (no mode read, behaviour still changes)

`fragment_applies` ([report_service.py#L313-L321](../../app/report_service.py#L313-L321)) is the single owner of "is this image stale", and asks `affected_environments`. `sync_evidence_image_slots` ([L331](../../app/report_service.py#L331)) creates and prunes slots from the same list. `applicable_poc_variants` ([L308-L310](../../app/report_service.py#L308-L310)) reads `affected_channels`. `generation_issues` ([docx_report.py#L105](../../app/docx_report.py#L105)) demands one evidence image per affected environment. `finding_is_complete` ([report_service.py#L580](../../app/report_service.py#L580)) ends in `scope_has_location`.

For every finding whose `target_ids` already resolve to the same set the mode resolved to, all five are unchanged. For a `mode: "all"` finding migrated with an **incomplete** id list, all five narrow at once: fewer environments, fewer slots, fewer required screenshots, fewer proof-of-concept variants offered, and a shorter Location list in the document.

### JavaScript — direct readers

| Site | Line | Behaviour |
|---|---|---|
| `scopeTargetIds` | [app.js#L952-L958](../../app/web/static/app.js#L952-L958) | Twin of the resolution half of `_finding_locations`. Defaults a missing mode to `"custom"` |
| `scopeHasLocation` | [app.js#L960](../../app/web/static/app.js#L960) | `scopeTargetIds(...).length > 0` **or**, for custom only, a non-blank typed location |
| `scopeEnvironments` | [app.js#L961-L967](../../app/web/static/app.js#L961-L967) | Twin of `affected_environments`, via `scopeTargetIds` |
| `affectedChannels` | [app.js#L973-L984](../../app/web/static/app.js#L973-L984) | Twin of `affected_channels`, branch for branch |
| `scopeReaches` | [app.js#L1233-L1247](../../app/web/static/app.js#L1233-L1247) | Twin of `_scope_reaches_a_location`, plus the `coverage` argument |
| Findings-page backfill | [app.js#L1485-L1487](../../app/web/static/app.js#L1485-L1487) | Rewrites `target_ids` on non-custom scopes. No Python counterpart |
| `renderFindings` | [app.js#L1797](../../app/web/static/app.js#L1797) | `const selectedTargets = finding.scope.mode === "custom" ? finding.scope.target_ids : []` — **this is the display/rule disagreement**. A non-custom finding draws every box unticked even though the line above just wrote its ids into the model |
| `updateLocations` | [app.js#L1845](../../app/web/static/app.js#L1845) | Any checkbox or typed-endpoint commit replaces the whole scope with `{mode:"custom", ...}` |
| `addFinding` | [app.js#L1884](../../app/web/static/app.js#L1884) | New findings are custom |
| Editor Add vulnerability | [app.js#L2668](../../app/web/static/app.js#L2668) | New findings are custom |
| Editor finding card | [app.js#L2726](../../app/web/static/app.js#L2726) | Location chips resolve ids via `scopeTargetIds` for **all** modes, then add typed locations for custom only — so a `mode: "all"` finding already shows full location chips in the editor while showing no ticks on Findings |

After the change, only `updateLocations`, `addFinding`, and the editor's Add stay meaningful; the mode tests in `scopeTargetIds`, `scopeEnvironments`, `affectedChannels`, `scopeReaches`, and the `renderFindings` ternary all collapse to their custom branch, and the backfill at L1485-L1487 has nothing left to do.

### JavaScript — indirect consumers

`affectedEnvironments` ([L968](../../app/web/static/app.js#L968)), `syncEvidenceImageSlots` ([L997-L1021](../../app/web/static/app.js#L997-L1021)), `deletionBlockedReason` ([L1032](../../app/web/static/app.js#L1032)), `findingsStrandedBy` ([L1251](../../app/web/static/app.js#L1251)), `scopeTextStrandedFindings` ([L1324](../../app/web/static/app.js#L1324)), `updateFindingSummary` ([L1555](../../app/web/static/app.js#L1555)), `settleScopeChange` ([L1564-L1565](../../app/web/static/app.js#L1564-L1565)), `validateFindingsPage` ([L1964](../../app/web/static/app.js#L1964)), the image editor's environment dropdown ([L2133](../../app/web/static/app.js#L2133), [L2233](../../app/web/static/app.js#L2233), [L2923](../../app/web/static/app.js#L2923)), `fragmentIssues` ([L2485](../../app/web/static/app.js#L2485)), and the readiness panel ([L2527](../../app/web/static/app.js#L2527), [L2530](../../app/web/static/app.js#L2530)).

### One function named in the request does not exist

There is no `scope_targets_for` in Python. `scopeTargetIds` has no named Python twin; the same resolution is written out twice, inline, in `affected_environments` ([report_service.py#L262-L277](../../app/report_service.py#L262-L277)) and `_finding_locations` ([docx_report.py#L1006-L1019](../../app/docx_report.py#L1006-L1019)), and those two do not agree on ordering. If the plan extracts one, it should extract it from `_finding_locations`, because that is the version whose output reaches the document.

---

## 2. The `Scope` model and what `validate_references` enforces

```python
class Scope(BaseModel):
    mode: Literal["all", "all_production", "all_non_production", "custom"] = "all"
    target_ids: list[str] = Field(default_factory=list)
    location_values: dict[str, str] = Field(default_factory=dict)
    custom_locations: dict[Environment, dict[Channel, list[str]]] = Field(default_factory=dict)
```

[models.py#L130-L136](../../app/models.py#L130-L136). There are **no validators on `Scope` itself** — no `field_validator`, no `model_validator`, no cross-field rule. `target_ids` is a bare `list[str]`, not `list[StableId]`, so it accepts any string including `""`. `Vulnerability.scope` is `Field(default_factory=Scope)` ([L177](../../app/models.py#L177)), so a finding constructed with no scope lands on `mode: "all"` with everything else empty.

**The claim that `target_ids` are validated only for `mode == "custom"` is correct.** [models.py#L302](../../app/models.py#L302):

```python
if vulnerability.scope.mode == "custom" and not set(vulnerability.scope.target_ids) <= target_ids:
    raise ValueError("custom scope references a missing target")
```

`target_ids` on the right is the set of `scope_targets[].target_id` for the whole report ([L295](../../app/models.py#L295)). Nothing else in `validate_references` mentions scope: not `location_values`, not `custom_locations`, not whether `mode` and `target_ids` are consistent.

**What this means for the migration.** A rewrite to `"custom"` moves every converted finding from "unchecked" to "checked" under a rule that raises `ValidationError`, and a `ValidationError` on load does not show an error — it demotes the whole draft to the manager's legacy/invalid list via `Workspace.list_legacy_reports` ([workspace.py#L128-L146](../../app/workspace.py#L128-L146)). So a migration that writes an id that is not in `scope_targets` does not fail loudly; it makes the report look broken and unopenable.

Three concrete ways a stale id can already be sitting in a non-custom `target_ids` today, unvalidated:

1. The Findings-page backfill writes ids resolved from the mode, then Setup removes a scope target. The non-custom finding keeps the now-dangling id, and neither `reconcile_targets` (L524 sends it down the non-custom branch) nor `validate_references` (L302 skips it) objects.
2. `Workspace.import_report` validates the payload ([workspace.py#L163](../../app/workspace.py#L163)) but never runs `reconcile_targets`, so an imported bundle can carry any `target_ids` under a non-custom mode.
3. A hand-edited draft.

**Therefore a migration must filter, not just relabel.** The safe form is `target_ids = [id for id in resolved_ids if id in scope_targets]`, and it must run after `scope_targets` is known — which rules out doing it per-`Vulnerability`, since a `Vulnerability` validator cannot see the report. It has to be a `Report`-level hook.

---

## 3. Legacy repair on load, and where a mode migration belongs

`Workspace.load_path` ([workspace.py#L269-L297](../../app/workspace.py#L269-L297)) reads the raw JSON and repairs exactly two shapes:

1. A `numbered_list` or `bulleted_list` fragment with no `items` gets `[{"runs": []}]`.
2. A `recommended_remediation` holding the single unlabelled `RESOLVED_REMEDIATION` sentence: on a resolved finding it gains `generated: "resolved_remediation"`; on any other status its runs are emptied.

If either fired, it rewrites the file via `atomic_write_json(path, draft)` and then returns `Report.model_validate(draft)` ([L297](../../app/workspace.py#L297)). Nothing else. No scope repair of any kind.

**The map's claim is confirmed: `import_report` and both `parse_import` branches build a `Report` without going through the load path.** `Workspace.import_report` calls `Report.model_validate(payload)` directly at [workspace.py#L163](../../app/workspace.py#L163). `parse_import` validates the JSON branch and the ZIP branch separately ([main.py#L322-L360](../../app/main.py#L322-L360)) and returns the **raw payload dict**, which `main.import_report` then hands to `workspace.import_report` for a second validation ([main.py#L554-L559](../../app/main.py#L554-L559)).

Every entry path and the hook it shares:

| Entry path | Validation |
|---|---|
| `Workspace.load_path` | `Report.model_validate(draft)` [workspace.py#L297](../../app/workspace.py#L297) |
| `Workspace.import_report` | `Report.model_validate(payload)` [workspace.py#L163](../../app/workspace.py#L163) |
| `parse_import`, JSON branch | `Report.model_validate(payload)` [main.py#L331](../../app/main.py#L331) |
| `parse_import`, ZIP branch | `Report.model_validate(payload)` [main.py#L350](../../app/main.py#L350) |
| `parse_report_docx` import | payload → `workspace.import_report` → same validate |
| `PUT /reports/{id}` | `Report.model_validate(payload)` [main.py#L676](../../app/main.py#L676) |
| `repair_duplicate_fragment_ids` | `Report.model_validate(draft)` [workspace.py#L238](../../app/workspace.py#L238) — **then persists the raw draft** at [L239](../../app/workspace.py#L239) |
| `Workspace.duplicate` | `model_copy(deep=True)` [workspace.py#L203](../../app/workspace.py#L203) — no validation, but its source came through `load` |
| `Workspace.create_report` | `Report(...)` constructor [workspace.py#L113](../../app/workspace.py#L113) |

**The single shared hook is the `Report` model itself** — the `model_validator(mode="before")` at [models.py#L266-L281](../../app/models.py#L266-L281), exactly as app-type normalisation uses. A mode migration belongs there, not in `load_path`.

**Two traps in putting it there.**

First, that validator early-returns before it reaches most of its own body:

```python
if not isinstance(data, dict):
    return data
engagement = data.get("engagement")
if engagement is not None and not isinstance(engagement, dict):
    return data
```

[models.py#L271-L275](../../app/models.py#L271-L275). `Workspace.create_report` passes `engagement=Engagement(...)` — a model instance — so the second return fires and everything after it is skipped. That path creates no vulnerabilities so it is harmless today, but a scope migration appended after L275 would be silently skipped for any caller that constructs `Report` with a pre-built `Engagement`. If the migration goes in this function it has to sit **above** those guards, or in a second `mode="before"` validator of its own.

Second, `repair_duplicate_fragment_ids` validates the draft and then writes the **raw** dict back ([workspace.py#L238-L239](../../app/workspace.py#L238-L239)). A before-validator migration is applied in memory and thrown away by that path, so a manager repair leaves the old `mode` on disk until the next ordinary save — the same caveat the map already records for the retired `test_type`.

**The PUT path has a third hook that the model does not cover.** `reconcile_targets` runs on the raw dict *before* validation ([main.py#L662](../../app/main.py#L662) vs [L676](../../app/main.py#L676)), and it makes its own mode decision at [report_service.py#L524](../../app/report_service.py#L524). A `Report`-level default cannot reach it. That branch test has to change in the same edit or a mode-less scope keeps taking the non-custom path on every Setup save.

---

## 4. What the drafts on disk actually look like

Six `draft.json` files, not four.

| Report | Findings | Scope modes | Notes |
|---|---|---|---|
| `r_c6ff01abda9e` | 14 | `all` × 14 | 4 targets; every finding carries all 4 ids |
| `r_b0867e631235` | 5 | `custom` × 5 | 4 targets; ids `[t_prod_web, t_prod_api]`, `[t_prod_api, t_uat_api]`, `[t_prod_web]` × 3 |
| `r_0931592e4fdd` | 1 | `custom` | 2 targets, both selected; the only draft with non-empty `location_values` |
| `r_84b9ebe1bbdd` | 1 | `custom` | 1 target, selected; still carries legacy `test_type: "web"` |
| `r_404ecd327eea` | 0 | — | empty `scope_targets` and `vulnerabilities` |
| `r_d96116840c2f` | 0 | — | empty `scope_targets` and `vulnerabilities` |

**Distinct mode values present: `"all"` and `"custom"`. Neither `"all_production"` nor `"all_non_production"` appears anywhere, in any draft or backup.**

**No non-custom finding has a dangling `target_ids`.** The only non-custom findings are `c6ff01abda9e`'s 14, and every one carries exactly `["t_prod_web", "t_prod_api", "t_uat_web", "t_uat_api"]`, which is precisely that report's `scope_targets` list. Every custom finding in the other three reports also resolves cleanly.

**No draft has any `custom_locations`.** All 41 occurrences across every `draft.json` and `draft.bak.json` are the literal `{}`. The typed-endpoint feature has zero real-data coverage.

**Would `c6ff01abda9e`'s 14 findings survive a rewrite to `"custom"` with their current `target_ids`? Yes, and byte-identically in the generated document.**

- `validate_references` passes: all four ids exist in `scope_targets`.
- `scope_has_location`, `affected_environments`, `affected_channels`, `sync_evidence_image_slots`, `generation_issues` all produce the same answers, because the four ids cover both environments and both channels.
- `_finding_locations` produces the same output. Under `"all"` it sorts by `(CHANNEL_ORDER.index(channel), order)` — web before api — then buckets by environment, giving production `[prod_web, prod_api]` and non-production `[uat_web, uat_api]`. Under `"custom"` it walks `target_ids` in stored order and buckets the same way, giving the same two lists. `location_values` is `{}` on all 14, so the `.get(target_id, target.value)` fallback returns the identical strings.

That equivalence is luck, not structure: it holds because this report's stored id order happens to match channel-sorted order within each environment. A different report could reorder its printed Location rows on migration.

**The draft that actually needs care is the backup.** `draft.bak.json` still holds `"mode": "all"` with `"target_ids": []`. If that revision is ever the one a migration sees, a naive relabel to `"custom"` produces 14 findings with **no** location — which is not a validation failure, but does make all 14 incomplete, blocks `/edit`, and blocks generation. The migration must resolve the mode to ids, not just rename the mode.

---

## 5. The environment modes and their dynamic behaviour

`"all_production"` and `"all_non_production"` hold no ids and re-resolve against `report.scope_targets` on every read:

- [report_service.py#L273-L277](../../app/report_service.py#L273-L277) — `affected_environments`
- [L299-L303](../../app/report_service.py#L299-L303) — `affected_channels`, via the environments above
- [L449-L451](../../app/report_service.py#L449-L451) — `_scope_reaches_a_location`
- [L574-L575](../../app/report_service.py#L574-L575) — `scope_has_location`
- [docx_report.py#L1012-L1019](../../app/docx_report.py#L1012-L1019) — `_finding_locations`
- [app.js#L955-L957](../../app/web/static/app.js#L955-L957) — `scopeTargetIds`
- [app.js#L1244-L1246](../../app/web/static/app.js#L1244-L1246) — `scopeReaches`

So adding a Production target in Setup silently widens every `all_production` finding: new environment coverage if it was the first one, a new image slot from `sync_evidence_image_slots`, possibly a new proof-of-concept variant offer, and a new row in the document's Location cell. Freezing to `target_ids` ends all of that.

**No production code depends on the dynamic behaviour, because nothing can produce these modes.** No UI writes them — the only three scope writes in the client are `{mode:"custom"}` ([L1845](../../app/web/static/app.js#L1845), [L1884](../../app/web/static/app.js#L1884), [L2668](../../app/web/static/app.js#L2668)). `insert_library` explicitly refuses the default and passes `Scope(mode="custom")` with a comment saying why ([main.py#L716-L719](../../app/main.py#L716-L719)). The DOCX import always writes custom. They can only arrive via a hand-edited file or an imported bundle.

**Tests do depend on it, and one depends on it structurally.**

| Test | Line | Dependency | Under a custom-only world |
|---|---|---|---|
| `test_coverage_change_that_strands_a_mode_scoped_finding_is_rejected` | [test_app.py#L696-L723](../../tests/test_app.py#L696-L723) | Creates a finding with `{"mode": "all_non_production"}` and **no ids**, then unchecks Non-Production and requires a 422 `referenced_scope_removed`. Its docstring states the reason outright: *"holds no target IDs, so only a before-and-after location check can notice"* | The assertion still passes, but through the **custom** branch rather than the before/after branch. The test stops covering what it was written to cover, and [report_service.py#L532-L535](../../app/report_service.py#L532-L535) loses its only test |
| `test_non_custom_scope_modes_resolve_report_targets` | [test_app.py#L540-L566](../../tests/test_app.py#L540-L566) | Saves one finding per non-custom mode with no ids and requires `/edit` to return 200 | Becomes a test of a state that cannot exist. Delete |
| `test_affected_channels_resolve_the_proof_of_concept_variants` | [test_app.py#L402-L407](../../tests/test_app.py#L402-L407) | `Scope(mode="all")` must offer both channels. The comment says *"No draft on disk exercises the non-custom modes, so they are covered here deliberately"* | Delete that stanza |
| `test_generator_locations_use_typed_endpoints_grouped_by_channel` | [test_app.py#L959-L966](../../tests/test_app.py#L959-L966) | Switches to `{"mode": "all"}` and asserts the printed locations are the report's full target list in channel order | Rewrite against explicit ids; note the ordering difference from §1 |
| `test_typed_endpoints_reach_the_report_even_when_the_finding_covers_everything` | [test_app.py#L993-L1015](../../tests/test_app.py#L993-L1015) | Asserts `stored.vulnerabilities[0].scope.mode == "all"` round-trips | **Its premise is already false.** The docstring claims *"the Findings page ... writes them without switching the scope to custom"* — [app.js#L1845](../../app/web/static/app.js#L1845) switches to custom on every commit |
| Five more using `scope: {"mode": "all"}` as a convenient "affects everything" | L797, L831, L896, L924, L1045-L1046 | Incidental — they want two environments, not the mode | Replace with explicit ids. Each needs the target ids threaded through from the prior save's response |

Also incidental but affected: eight `Vulnerability(...)` constructions with no `scope` argument, which currently land on `mode: "all"` — test_app.py L386, L414, L433, L444, L468, L486, L518, L856. Flipping the default makes each of these a finding with **no** location, which changes `affected_environments` to `[]` and therefore changes what `sync_evidence_image_slots` and `provision` produce for them.

---

## 6. Rules that exist in both Python and JavaScript

| Rule | Python | JavaScript |
|---|---|---|
| scope resolves to a location | `scope_has_location` [L567-L575](../../app/report_service.py#L567-L575), `_scope_reaches_a_location` [L440-L451](../../app/report_service.py#L440-L451) | `scopeHasLocation` [L960](../../app/web/static/app.js#L960), `scopeTargetIds` [L952-L958](../../app/web/static/app.js#L952-L958), `scopeReaches` [L1233-L1247](../../app/web/static/app.js#L1233-L1247) |
| affected environments | `affected_environments` [L253-L277](../../app/report_service.py#L253-L277) | `affectedEnvironments` [L968](../../app/web/static/app.js#L968), `scopeEnvironments` [L961-L967](../../app/web/static/app.js#L961-L967) |
| affected app types | `affected_channels` [L281-L304](../../app/report_service.py#L281-L304) | `affectedChannels` [L973-L984](../../app/web/static/app.js#L973-L984) |
| finding completeness | `finding_is_complete` [L578-L580](../../app/report_service.py#L578-L580) | `validateFindingsPage` [L1964](../../app/web/static/app.js#L1964), `updateFindingSummary` [L1555](../../app/web/static/app.js#L1555) |
| image slots | `sync_evidence_image_slots` [L331](../../app/report_service.py#L331) | `syncEvidenceImageSlots` [L997-L1021](../../app/web/static/app.js#L997-L1021) |
| environment gating for fragments | `fragment_applies` [L313-L321](../../app/report_service.py#L313-L321) | inline in `fragmentIssues` [L2485](../../app/web/static/app.js#L2485) and `updateReadinessPanel` [L2527-L2530](../../app/web/static/app.js#L2527-L2530) |
| which targets survive an app-type or environment change | the target loop in `reconcile_targets` [L510-L536](../../app/report_service.py#L510-L536) | `findingsStrandedBy` [L1248-L1253](../../app/web/static/app.js#L1248-L1253), `dropChannelEverywhere` [L1282-L1294](../../app/web/static/app.js#L1282-L1294) |
| which targets survive a scope-text edit | the same loop, reusing ids by value [L494-L502](../../app/report_service.py#L494-L502) | `survivingAfterScopeText` [L1312-L1318](../../app/web/static/app.js#L1312-L1318), `scopeTextStrandedFindings` [L1319-L1326](../../app/web/static/app.js#L1319-L1326) |
| library proof-of-concept selection | `applicable_poc_variants` [L308-L310](../../app/report_service.py#L308-L310) | `applicablePocVariants` [L987-L991](../../app/web/static/app.js#L987-L991) |
| generation readiness | `generation_issues` [docx_report.py#L93-L130](../../app/docx_report.py#L93-L130) | `updateReadinessPanel`, `fragmentIssues` [L2483-L2545](../../app/web/static/app.js#L2483-L2545) |

Python-only, no twin: `Report.validate_references` [L302](../../app/models.py#L302), the `referenced_scope_removed` 422 [main.py#L667-L673](../../app/main.py#L667-L673), and `_finding_locations` [docx_report.py#L1003-L1026](../../app/docx_report.py#L1003-L1026) — generation is server-only.

JavaScript-only, no twin: the Findings-page `target_ids` backfill [L1485-L1487](../../app/web/static/app.js#L1485-L1487), the `renderFindings` `selectedTargets` ternary [L1797](../../app/web/static/app.js#L1797), `settleScopeChange` [L1564](../../app/web/static/app.js#L1564), `confirmScopeLoss` [L1254](../../app/web/static/app.js#L1254), `confirmScopeTextLoss` [L1328](../../app/web/static/app.js#L1328), `confirmChannelRemoval` [L1296](../../app/web/static/app.js#L1296), and `deletionBlockedReason` [L1032](../../app/web/static/app.js#L1032).

Only one contract test guards any of this: `tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues`, and it covers generation readiness alone. **Every scope row above is unguarded against drift.**

---

## 7. `reconcile_targets`, stranding, and the 422

### How a scope-text edit decides who is stranded

`reconcile_targets` only runs when the payload carries `scope_text`, which only the Setup page seeds ([report_service.py#L454-L456](../../app/report_service.py#L454-L456)). It rebuilds `scope_targets` from the submitted text, **reusing a target's id whenever the exact `(environment, channel, value)` triple is still present** ([L494-L502](../../app/report_service.py#L494-L502)). So a retyped or renamed line is a new id; an untouched line keeps its old one.

Then, per finding ([L506-L536](../../app/report_service.py#L506-L536)):

1. `reached_before = _scope_reaches_a_location(scope, prior_targets)` — captured at [L512](../../app/report_service.py#L512), **before** anything is narrowed.
2. `custom_locations` is filtered down to environments and channels the engagement still covers ([L515-L522](../../app/report_service.py#L515-L522)), mutating the payload in place.
3. **If `mode == "custom"`** ([L524](../../app/report_service.py#L524)):
   - `if set(target_ids) - new_target_ids:` → stranded. **Any** missing id, regardless of how many survive ([L525-L526](../../app/report_service.py#L525-L526)).
   - `elif reached_before and not reaches_now:` → stranded, the typed-location case ([L529-L530](../../app/report_service.py#L529-L530)).
4. **Otherwise** ([L532-L535](../../app/report_service.py#L532-L535)): only `reached_before and not reaches_now`. A `mode: "all"` finding is stranded only when the report loses **every** target.

Any name in `removed_references` becomes a hard 422 `referenced_scope_removed` for the whole save ([main.py#L666-L673](../../app/main.py#L666-L673)) — no partial apply, nothing written.

### What a universally-custom world does to it

**The 422 becomes substantially more reachable**, because the strict `set(target_ids) - new_target_ids` branch takes over from the lenient before/after branch for every finding in the app.

Worked through on real data. `c6ff01abda9e` has 4 targets and 14 findings, each holding all 4 ids. A tester deletes one line — say `https://uat-api.example.test` — from Setup:

- **Today:** all 14 are `mode: "all"`, so step 4 applies. `reached_before` is true and `reaches_now` is still true (3 targets remain), so nothing is stranded and the save succeeds.
- **After the change:** all 14 are custom holding `t_uat_api`, so step 3 applies. `{t_uat_api}` is missing from the new set for all 14, so `removed_references` names all 14 findings. **The save is refused**, and the only way out is to untick that location on all 14 findings first — one at a time, on a page whose checkboxes each trigger a re-render.

The same applies to unchecking an environment on Setup ([app.js#L1397-L1407](../../app/web/static/app.js#L1397-L1407)).

### And the client will not warn first

The pre-save gate is `strandedByScopeEdit` ([app.js#L683-L687](../../app/web/static/app.js#L683-L687)), bound to `scopeTextStrandedFindings` ([L1327](../../app/web/static/app.js#L1327)). That function reports only findings that end up with **no** location:

```js
.filter(finding => scopeReaches(finding.scope, report.scope_targets) && !scopeReaches(finding.scope, surviving, coverage))
```

[app.js#L1324](../../app/web/static/app.js#L1324). A finding that loses one of four ids still satisfies `scopeReaches(scope, surviving)` on the strength of the other three, so it is never named. `findingsStrandedBy` ([L1251](../../app/web/static/app.js#L1251)), which backs the environment and app-type dialogs, has the same shape and the same blind spot.

**So the client's model of stranding and the server's are different predicates, not two copies of one.** The result is a save that is silently blocked with a 422 and no preceding dialog. This divergence exists today — it already bites the three custom reports on disk — but `"all"` masks it entirely for `c6ff01abda9e`, and making every finding custom exposes it on every report at once.

There is one further asymmetry worth knowing before choosing a fix. Unchecking an **app type** purges the doomed ids from every finding client-side after the tester confirms (`dropChannelEverywhere`, [L1282-L1294](../../app/web/static/app.js#L1282-L1294), called at [L1367](../../app/web/static/app.js#L1367)), so the payload the server sees no longer holds them and the 422 never fires. Unchecking an **environment** has no such purge — [L1400-L1406](../../app/web/static/app.js#L1400-L1406) confirms and then just updates `tested_environments`. Editing scope text has no purge either. Whatever the plan does about the strict branch, that inconsistency is the shape of the existing workaround and the obvious template for extending it.

---

## Invariants in play

1. **`reconcile_targets` runs on the raw dict before `Report.model_validate`** ([main.py#L662](../../app/main.py#L662) vs [L676](../../app/main.py#L676)). A Pydantic default for `mode` is applied *after* [report_service.py#L524](../../app/report_service.py#L524) has already branched. Violating it: a mode-less scope keeps taking the non-custom path on every Setup save, and the model default never gets a say.
2. **`reconcile_targets` only runs when the payload carries `scope_text`**, which only Setup seeds. Violating it: any guarantee placed there is dead on the Findings and Content pages, which PUT the whole report without it.
3. **A `ValidationError` on load demotes the draft to the manager's legacy/invalid list**, it does not surface an error ([workspace.py#L128-L146](../../app/workspace.py#L128-L146)). Violating it: a migration that writes an unresolvable `target_id` makes reports vanish from the manager rather than failing loudly.
4. **`target_ids` are unchecked on non-custom modes** ([models.py#L302](../../app/models.py#L302)). Violating it: any stale id that accumulated under that exemption becomes a load-time failure the moment the mode is rewritten.
5. **`Report`'s `mode="before"` validator is the only hook every entry path shares** ([models.py#L266-L281](../../app/models.py#L266-L281)), and it early-returns at [L274-L275](../../app/models.py#L274-L275) when `engagement` is a model instance. Violating it: a migration appended after that guard is skipped for direct construction.
6. **`repair_duplicate_fragment_ids` persists the raw draft after validating** ([workspace.py#L238-L239](../../app/workspace.py#L238-L239)). Violating it: an in-memory migration is discarded by that path.
7. **`sync_evidence_image_slots` only removes an image slot that is empty, uncaptioned, and for an unaffected environment** ([report_service.py#L338-L353](../../app/report_service.py#L338-L353)). Violating it: a migration that narrows a finding's environments deletes nothing the tester filled in — but it does stop demanding evidence that the document still needs.
8. **`_finding_locations` chooses its ordering by mode** ([docx_report.py#L1006-L1019](../../app/docx_report.py#L1006-L1019)). Violating it: migrated findings silently reorder their printed Location rows.

## Both-sides warning

Every rule this change touches except three is implemented twice and must be changed in the same edit:

- `scope_has_location` ↔ `scopeHasLocation` / `scopeTargetIds`
- `_scope_reaches_a_location` ↔ `scopeReaches` — **and these two now differ in shape**: JavaScript takes a `coverage` argument, Python mutates `scope["custom_locations"]` between its two calls
- `affected_environments` ↔ `affectedEnvironments` / `scopeEnvironments`
- `affected_channels` ↔ `affectedChannels`
- `finding_is_complete` ↔ `validateFindingsPage` / `updateFindingSummary`
- `sync_evidence_image_slots` ↔ `syncEvidenceImageSlots`
- `fragment_applies` ↔ the inline checks in `fragmentIssues` and `updateReadinessPanel`
- `applicable_poc_variants` ↔ `applicablePocVariants`
- the `reconcile_targets` stranding loop ↔ `findingsStrandedBy` / `scopeTextStrandedFindings` — **already out of step**, see §7

A one-sided change here shows up as a redirect loop between `/findings` and `/edit`, or as a save refused with a 422 the browser gave no warning about. Only generation readiness has a contract test; none of these rows do.

## Map drift

Corrected in [docs/DATA_MAP.md](../DATA_MAP.md) section 12, and the "Last verified" line bumped:

1. The **"scope resolves to a location"** row listed `scopeHasLocation` and `scopeTargetIds` as the JavaScript side. The actual twin of `_scope_reaches_a_location` is `scopeReaches`, which the map never named. Added, with a note that it now carries a `coverage` argument Python achieves by mutating `scope["custom_locations"]` first.
2. **`docx_report._finding_locations` was missing entirely** as a `scope.mode` consumer. Added as a new "which locations a finding prints" row, marked server-only.
3. The **"which targets survive a scope-text edit"** row implied `reconcile_targets` and `survivingAfterScopeText` / `scopeTextStrandedFindings` are twins. They implement different predicates — the server strands on any removed `target_id`, the client only on total loss of location. Marked "not an exact twin" and documented below the table.
4. The **Findings-page `target_ids` backfill** was unrecorded. It mutates persisted data with no Python counterpart and no server validation, and it is why the drafts on disk look the way they do. Documented below the table.

## Round 1 - Planner: proposal and open questions

## Understanding

`Scope.mode` stops being a resolution instruction and becomes a historical marker. Every scope becomes `mode: "custom"` carrying the explicit `target_ids` its old mode resolved to, filtered to targets that actually exist and ordered so the generated document prints identically. After that, "this finding has no ticked location" and "this finding is blocked" are the same statement on both sides of the wire, the Findings page can draw ticks that match the rule, and roughly a dozen per-mode branches across Python and JavaScript collapse to one. The change is small in the model and large in `reconcile_targets`, because moving every finding onto the strict `set(target_ids) - new_target_ids` branch makes a currently-rare 422 routine — and fixing that is the majority of the work, not the migration.

---

## 1. Blast radius

| File | What changes | Why |
|---|---|---|
| [models.py](../../app/models.py#L131) | `Scope.mode` default flips to `"custom"`; the `Literal` narrows to `Literal["custom"]`; a new `field_validator("mode", mode="before")` on `Scope` coerces the three retired tokens instead of raising; a new module function `normalise_scope_modes(report_mapping)` is called from inside `normalise_app_types`, **above** its `engagement`-is-a-model early return | The `Report` `mode="before"` validator is the only hook every entry path shares, and only a report-level hook can see `scope_targets`, which the filter needs. The field-level coercion is the safety net that stops a missed case becoming a legacy/invalid demotion |
| [report_service.py](../../app/report_service.py#L262) | `affected_environments` loses three branches; `affected_channels` loses its `else`; `_scope_reaches_a_location` loses two branches; `scope_has_location` loses two branches; `reconcile_targets` loses its trailing non-custom block and **gains a survivor filter** on `target_ids` | The first four are pure dead-branch deletion. `reconcile_targets` is the only one whose behaviour changes, and it is the whole risk of the change |
| [main.py](../../app/main.py#L662) | `save_report` calls `normalise_scope_modes(payload)` immediately before `reconcile_targets`; the `"all"` comment above `insert_library`'s `Scope(mode="custom")` is rewritten or deleted | Invariant 1: `reconcile_targets` runs on the raw dict before `Report.model_validate`, so a Pydantic default cannot reach its mode branch. Without this call site the non-custom branch stays live on every Setup save |
| [workspace.py](../../app/workspace.py#L238) | `repair_duplicate_fragment_ids` calls `normalise_scope_modes(draft)` before `Report.model_validate(draft)`. `load_path` is deliberately **not** touched | Invariant 6: that method validates then persists the *raw* draft, so an in-memory migration is thrown away. `load_path` is left alone for the backup-exhaustion reason in §2 |
| [docx_report.py](../../app/docx_report.py#L1006) | `_finding_locations` loses its `else` branch and the `{...}[mode]` dict lookup | That dict is a latent `KeyError` for any unlisted mode, and it is the only mode branch whose output reaches the document |
| [app.js](../../app/web/static/app.js#L952) | Nine sites: `scopeTargetIds` collapses to an accessor; `scopeHasLocation` drops its `mode === "custom" &&` guard; `scopeEnvironments` and `affectedChannels` drop their mode tests; `scopeReaches` drops two branches; the Findings-page backfill is **deleted**; the `renderFindings` `selectedTargets` ternary is **deleted**; the environment-checkbox path and the scope-text commit path gain a shared `dropTargetsEverywhere` purge; `findingsStrandedBy` and `scopeTextStrandedFindings` change predicate | Both halves of every duplicated rule must move in one edit. The backfill and the ternary are the two halves of the display/rule disagreement being fixed. The purge and the predicate change are the 422 decision in §4 |
| [tests/test_app.py](../../tests/test_app.py#L540) | Two tests deleted, four rewritten, eight new (§5) | Six existing tests depend on non-custom modes |
| [tests/test_browser.py](../../tests/test_browser.py#L462) | One new contract test for the stranding predicate. Existing scope usage needs no change — all five `Scope(...)` constructions there are already `mode="custom"` | The scope-survival row is the row that already drifted and has no drift guard |
| [docs/DATA_MAP.md](../DATA_MAP.md) | Section 6 (the `validate_references` bullet), section 8 (a new legacy-repair entry), section 12 (six rows plus both client-only notes), section 13 (a new sharp edge for the on-disk lag), and the "Last verified" line | The maintenance contract at the top of that file requires it in the same change |
| [docx_import.py](../../app/docx_import.py#L465) | **No change** | Both branches already write `{"mode": "custom", ...}`. Listed so the reader knows it was checked, not overlooked |
| [tests/test_docx.py](../../tests/test_docx.py#L585), [tests/test_docx_import.py](../../tests/test_docx_import.py#L75) | **No change** | Both already build `Scope(mode="custom", target_ids=[...])` |

---

## 2. Data risks

| Failure mode | Verdict | Reasoning and what handles it |
|---|---|---|
| Stale write | **clear** | The migration adds no mutation path. It runs inside validation on paths that already carry `saved_at` (the PUT body) or that never send one (load). Because the migration is in-memory only, `saved_at` is untouched on load, so no open browser tab is spuriously 409'd |
| Lost update | **clear** | No new read-modify-write. The two persisting call sites — `repair_duplicate_fragment_ids` and the ordinary save path — both already run inside `Workspace._locked`. The deliberate refusal to write from `load_path` keeps it that way |
| Orphan reference | **RISK** | Rewriting mode to custom makes [models.py#L302](../../app/models.py#L302) enforce `target_ids ⊆ scope_targets` on data that has never been checked. Handled by filtering, not relabelling: `normalise_scope_modes` intersects the resolved ids with the report's `scope_targets` before writing them. It is a report-level function precisely because a `Vulnerability`-level validator cannot see that set |
| Silent stranding | **RISK** | A `mode: "all"` finding on a report with no resolvable targets becomes locationless and blocks `/edit`. That is the intended fix, not a defect — but it is a visible state change for any such finding. Handled by: the Findings page already counts incomplete findings in `updateFindingSummary`, `/edit` already redirects to `/findings?incomplete=findings`, and the fix is one click on a page the tester must pass through anyway |
| Schema break | **RISK** | An existing `draft.json` holding `"all"` must still load. Handled twice: the before-validator rewrites `mode` before the `Literal` is ever checked, and the `Scope.mode` field coercion catches anything that reaches `Scope` without passing the report-level hook. `validate_references` then passes because the ids were filtered |
| Request/response asymmetry | **clear**, with a note | The server now returns a `scope.mode` and `target_ids` the browser did not send. That is the mechanism by which `applyCanonicalReport` migrates the live page, and it is the same shape as every other server-owned derived value. `scope_text` remains request-only and unchanged |
| Rule drift | **RISK** | Six of the nine paired scope rules change. Handled by editing both sides in one commit, by deleting rather than orphaning the dead branches (a dead branch that encodes a second, subtly different answer *is* the drift — see `_finding_locations`' ordering and `scopeReaches`' `coverage` argument), and by adding the first contract test on a scope row |
| Navigation trap | **clear** | To reach `/findings` at all, setup must be complete, and `setup_issues` already requires at least one scope target per tested environment. So any tester who can see a newly-blocked finding can also see at least one checkbox that unblocks it. A tester deep-linked to `/edit` is bounced once to `/findings`, ticks a box, and proceeds — no loop |
| Derived-state fight | **RISK** | The Findings-page backfill is a client-side derived-state writer with no server counterpart; leaving it in place while the server owns normalisation means two writers for one field. Handled by deleting the backfill outright. `provision_report` never reads or writes scope, so there is no fight on the save path |
| Backup exhaustion | **RISK** | Persisting the migration from `load_path` would rewrite every draft the first time the manager page is opened, because `list_reports` calls `load_path` per draft — every `draft.bak.json` on disk consumed in one click, replaced by a copy differing only in `mode`. Worse, `repair_duplicate_fragment_ids` writes and then calls `load`, which would be two writes back to back. Handled by migrating in memory only and letting the next ordinary save persist it, exactly as the retired `test_type` migration already does |
| Migration fidelity (the `draft.bak.json` case) | **RISK** | That revision holds `"mode": "all"` with `"target_ids": []`. A relabel produces 14 findings with no location: not a validation failure, but every one blocked and the report ungeneratable. Handled by resolving the mode to ids **first**, filtering **second**, relabelling **last** — and by a test built from exactly that shape |
| Legacy-invalid demotion | **RISK** | Two routes in. A stale id written under a custom mode raises `ValidationError`, which makes the report vanish into `list_legacy_reports` rather than failing loudly; and a narrowed `Literal` would do the same to any mode that dodges the migration. Handled by the filter for the first and the `Scope.mode` field coercion for the second. The coercion deliberately degrades to a recoverable state (custom, possibly no ids, visibly incomplete) instead of an unopenable one |
| 422 reachability change | **RISK**, the largest | Every finding moves from the lenient before/after branch to the strict "any missing id" branch. On the real 14-finding report, deleting one Setup line goes from a clean save to a refusal naming all 14, with no dialog first. See §4 — this is decided, not deferred |
| Printed-output reordering | **RISK** | A migrated finding prints its Location rows in `target_ids` order, where it used to print them sorted by `(CHANNEL_ORDER.index(channel), order)`. Handled by making the migration emit ids in that exact sort order. That also matches the order a hand-ticked finding produces, since `updateLocations` reads checkboxes in DOM order and the DOM is built from `scope_targets`, which `reconcile_targets` writes environment-then-channel-then-line |
| Client/server stranding predicate divergence | **RISK** | The client warns only on total loss of location; the server refuses on any lost id. Today `"all"` masks the gap on the one report that would hit it; making everything custom exposes it everywhere at once. Handled in §4 by collapsing the two into one predicate rather than by making the client shout louder |
| Evidence-slot narrowing *(not in the required list, but real)* | **RISK** | Where filtering drops a stale id, `affected_environments` shrinks, and the client's `syncEvidenceImageSlots` deletes empty uncaptioned slots for the lost environment while `generation_issues` stops demanding a screenshot there. Uploaded or captioned evidence is never touched. Handled by scope: no draft on disk has a stale id under a non-custom mode, so this is latent, not live — but it is the reason the migration must be tested against a deliberately stale id |
| Undo replay reintroduces a retired mode *(not in the required list)* | **clear** | `undoHistory` lives in `sessionStorage` and survives page loads, so a stored action can carry `scope.mode: "all"` in its diff and replay it into the live `report`. That payload then hits `normalise_scope_modes` at the `save_report` call site, which resolves and filters it again. The field coercion catches it a second time at validation |
| Two findings, one `display_id` *(checked, unrelated)* | **clear** | Nothing in the migration touches `display_id`, `uid`, `frag_id`, or `evidence_id` |

---

## 3. Proposal

### 3.1 One function, three call sites

Add to [models.py](../../app/models.py):

```
normalise_scope_modes(report_mapping) -> report_mapping
```

Raw mapping in, raw mapping out. For each vulnerability that is a `dict` with a `dict` scope and a retired `mode`:

1. **Resolve.** `all` → every target; `all_production` → production targets; `all_non_production` → non-production targets. Union with any `target_ids` already present, so the client backfill's existing writes are preserved rather than recomputed away.
2. **Filter.** Keep only ids present in the mapping's own `scope_targets`.
3. **Order.** Sort by `(CHANNELS.index(channel), order)` — the sort key `_finding_locations`' non-custom branch uses, so printed output is unchanged.
4. **Relabel.** Set `mode` to `"custom"`. Leave `custom_locations` and `location_values` untouched.

It must tolerate `scope_targets` entries and `vulnerabilities` entries that are model instances rather than dicts (skip those findings; a validated `Vulnerability` already holds a custom scope), the same defensive shape `_migrate_poc_variant` already uses.

**Call site 1 — inside `normalise_app_types`, above the `engagement` guard.** Not a second `mode="before"` validator: Pydantic's ordering between multiple before-validators is not something this plan should depend on, and the existing function is already the shared hook. It must sit above the `engagement is not None and not isinstance(engagement, dict)` return at [models.py#L274](../../app/models.py#L274) but below the `isinstance(data, dict)` return at [L271](../../app/models.py#L271). Rename the function to `normalise_legacy_shapes` so its docstring stops claiming it only handles app types.

**Call site 2 — [main.py#L662](../../app/main.py#L662), on `payload`, immediately before `reconcile_targets`.** This is the answer to invariant 1. Without it, a Setup save from a page seeded before the migration keeps taking the non-custom branch at [report_service.py#L524](../../app/report_service.py#L524) forever, and the model default never gets a say.

**Call site 3 — [workspace.py#L238](../../app/workspace.py#L238), on `draft`, before `Report.model_validate`.** This is the answer to invariant 6: that method persists the raw dict, so without the call a manager repair writes the pre-migration shape back to disk.

### 3.2 The paths this hook cannot reach, and what happens to them

| Path | Reached? | Outcome |
|---|---|---|
| `Workspace.load_path` | Yes, via `Report.model_validate` | Migrated in memory. **On-disk bytes keep `mode: "all"` until the next ordinary save.** Deliberate — see the backup-exhaustion row |
| `Workspace.import_report`, both `parse_import` branches, `parse_report_docx` | Yes, same validator | Nothing extra needed |
| `PUT /reports/{id}` | Yes, twice — call site 2 on the raw payload, then the validator | Call site 2 is the one that matters, because `reconcile_targets` runs first |
| `repair_duplicate_fragment_ids` | No, by default | Fixed by call site 3 |
| `Workspace.duplicate` | No validation at all | Its source came through `load`, so the in-memory model is already migrated, and `save` dumps the migrated model. Covered by construction |
| `Workspace.create_report` | Yes — the call sits above the guard that would otherwise skip it | No vulnerabilities exist, so it is a no-op today; correct for any future caller that passes a pre-built `Engagement` |
| Direct `Scope(...)` / `Vulnerability(...)` construction | No | Covered by the new default and the field coercion. `insert_library` already passes `Scope(mode="custom")` explicitly |

### 3.3 The two environment modes

Migrated identically, through the same resolve-filter-order path, with `all_production` freezing to production targets and `all_non_production` to non-production ones. Three extra lines. Neither token appears in any draft or backup on disk, and no UI can produce one, so this is insurance against a hand-edited file or an imported bundle rather than a live migration. Their dynamic re-resolution — where adding a Production target in Setup silently widened the finding, its image slots, its proof-of-concept offer, and its printed locations — is frozen on purpose. Nothing in production depends on it.

### 3.4 The `Literal`

**Narrow it to `Literal["custom"] = "custom"`, and add a `field_validator("mode", mode="before")` on `Scope` that maps `all`, `all_production`, and `all_non_production` to `"custom"`.**

What a retired value does to an old draft on load: nothing, because the report-level normaliser has already rewritten it and resolved its ids. The field validator only fires for a scope that reached validation without passing the report-level hook — a bare `Scope.model_validate`, a nested payload, an undo replay. In that case the finding becomes custom with whatever ids it happened to carry; if that is empty, it shows as incomplete on the Findings page and the tester ticks a box. **Recoverable and visible, rather than a draft that silently disappears from the manager into the legacy/invalid list.**

Keep the `mode` field itself for now, even though it has one legal value. The migration needs to *see* `"all"` to know it should resolve; delete the field and Pydantic's default `extra="ignore"` drops that signal silently, leaving the `draft.bak.json` case with 14 empty scopes. The field can be deleted in a later change once no draft on disk carries a retired token.

Rejected alternative: leave the `Literal` as it is. That keeps the dead values legal, which means the dead branches can never honestly be deleted, which means the drift the oracle found in `_finding_locations` and `scopeReaches` stays live and unguarded.

Cost to accept: `Scope(mode="all")` in a test now coerces silently instead of raising, so a stale test fails on its assertion rather than at construction. All six such tests are rewritten or deleted in this same change, so there is nothing left to mislead.

### 3.5 The client-side backfill

**Deleted.** [app.js#L1485](../../app/web/static/app.js#L1485) exists only to paper over the disagreement this change removes. After the server normalises, the `data-report` attribute the page is seeded from already holds custom scopes, so there is nothing for it to backfill. Leaving it in would mean two writers for one field with no server validation on one of them — which is how the current data shape came to be in the first place.

### 3.6 The `renderFindings` ternary

**Deleted.** `const selectedTargets = finding.scope.target_ids || []`. This one line is the display half of the bug: the row markup drew every box unticked for a finding whose ids the line above had just written into the model.

### 3.7 The dead non-custom branches

**Deleted now, all of them, in the same commit**: `affected_environments`, `affected_channels`, `_scope_reaches_a_location`, `scope_has_location`, `reconcile_targets`' trailing block, `_finding_locations`' `else` and its mode dict, and on the client `scopeTargetIds`, `scopeEnvironments`, `affectedChannels`, `scopeReaches`, and `scopeHasLocation`'s mode guard.

The argument for deleting rather than leaving unreachable: with the `Literal` narrowed and the field coerced, none of these branches can be entered, so keeping them documents a capability that no longer exists. More to the point, **these are the branches that already drifted** — `_finding_locations`' non-custom branch sorts where its custom branch does not, and `scopeReaches`' non-custom branches ignore the `coverage` argument its custom branch respects. Unreachable code carrying a second, different answer to the same question is the drift mechanism, not a safety net.

`scopeTargetIds` keeps its name with a one-line body, because the editor's finding card at [app.js#L2726](../../app/web/static/app.js#L2726) calls it and it is the only named resolver on that side.

### 3.8 Sequence

Each step leaves the app saveable.

1. **Fix the 422 first** (§4). Client purge, server purge, one predicate. Lands before anything makes the strict branch universal. Tests: `test_removing_one_of_several_scope_lines_still_saves`, `test_removing_a_findings_only_location_is_still_refused`, and the browser contract test. Invariant: a save that the client did not warn about must not be refused.
2. **Add `normalise_scope_modes` and its three call sites**, with the `Literal` and default unchanged. Purely additive; every existing test still passes. Tests: the migration-fidelity, stale-id, ordering, environment-mode, repair-persistence, and import tests. Invariant: no draft on disk may move to the legacy/invalid list.
3. **Flip the default, narrow the `Literal`, add the field coercion.** Tests: the coercion test, plus the six rewritten tests. Invariant: `validate_references` must pass for every draft in `data/apps`.
4. **Delete the dead branches, both sides, and the client backfill and ternary.** Tests: existing suite plus the browser contract test. Invariant: a finding's ticked boxes and its completeness verdict agree.
5. **Update [docs/DATA_MAP.md](../DATA_MAP.md).** Sections 6, 8, 12, 13 and the "Last verified" line.

---

## 4. The 422 decision

### The problem in one paragraph

`reconcile_targets` strands a custom finding when **any** of its `target_ids` disappears, and a non-custom finding only when the report loses **every** location. The client warns only in the second case. Today the gap is masked on the one report that would hit it, because all 14 of its findings are `mode: "all"`. Make everything custom and the gap opens on every report: on the real 14-finding report, deleting one Setup line goes from a silent success to a 422 naming all 14 findings, with no dialog beforehand and no route out except unticking that location on 14 findings by hand, on a page that re-renders after every click.

### The options

| Option | What it does | Cost |
|---|---|---|
| **(a) Extend the `dropChannelEverywhere` purge** to the environment checkbox and the scope-text commit | After the tester confirms, strip the doomed ids from every finding's `target_ids` and `location_values` client-side, so the payload the server sees never names them | Moderate. Needs a generalised `dropTargetsEverywhere(targetIds)` and two new call sites. The confirm dialogs must also change what they count, or they will promise "no findings affected" while silently deleting ticks. Covers only payloads the browser built |
| **(b) Relax the server's strict branch** to the client's predicate | Strand only on total loss of location | Cheap in isolation, but **wrong alone**: accepting a payload whose `target_ids` name deleted targets just moves the failure to `validate_references`, which returns a raw Pydantic error blob under `invalid_report` instead of the friendly message. It only works paired with a server-side filter of `target_ids` to survivors — at which point the server is silently deleting tester selections with no prompt |
| **(c) Align the client's predicate to the server's strict one** | Warn whenever any id is lost | Cheapest of all, one changed filter in two functions. But confirming the dialog does not purge anything, so the save is still refused. It converts a silent 422 into a warned-then-still-refused 422 — honest, but still a dead end for the tester |
| **(d) Ship the migration and accept the regression** | Nothing | Free, and worse than the bug being fixed. The worked example above is the everyday case on the largest report on disk |

### Decision: (a) and (b) together, as step 1, before the migration

- **Client:** generalise `dropChannelEverywhere` into `dropTargetsEverywhere(targetIds)` and call it from the environment-checkbox path at [app.js#L1400](../../app/web/static/app.js#L1400) and from the scope-text commit, after the confirm. Change `findingsStrandedBy` and `scopeTextStrandedFindings` to count findings that lose **any** selection, and word the dialogs accordingly — they stop saying "will be left with no affected location" and start saying how many findings lose a location, distinguishing those left with none.
- **Server:** inside `reconcile_targets`, after the new target set is known, filter each finding's `target_ids` to the survivors, then strand only when `reached_before and not reaches_now`. The `else` block disappears because the two branches become one.

**Why both and not either alone.** The client purge is the tester-facing story: a prompt, then a visible change that the undo stack can reverse. The server purge is the guarantee for every payload the browser did not build — an imported bundle, a tab left open across a Setup edit, an undo replay carrying a pre-edit scope. Client-only leaves the strict branch reachable from all three. Server-only deletes the tester's selections with no prompt at all, which is the thing this plan is least willing to do.

**What this deliberately gives up.** Today, a custom finding that keeps three of four ids is refused, which functions as an accidental brake on "you just quietly removed a location from 14 findings". That brake is not lost, it moves: from a post-hoc 422 with no explanation to a pre-hoc dialog that names the findings. The dialog is the better place for it, because it is the only one of the two the tester can act on.

**This is the precedent, already set.** Unchecking an app type already purges client-side and already never 422s. The environment and scope-text paths are the two that were never given the same treatment. This step finishes a job that is half done, and it is worth doing whether or not the migration ships.

---

## 5. Test plan

### Deleted (2)

| Test | Why |
|---|---|
| `test_non_custom_scope_modes_resolve_report_targets`, [test_app.py#L540](../../tests/test_app.py#L540) | It asserts that three modes which can no longer exist let a report past `/edit`. Its replacement is `test_the_environment_modes_freeze_to_the_targets_they_resolved_to` below |
| The `Scope(mode="all")` stanza inside `test_affected_channels_resolve_the_proof_of_concept_variants`, [test_app.py#L402](../../tests/test_app.py#L402) | Two lines and their comment. The coverage it claimed — "a finding touching both app types offers both" — is already asserted four lines above with explicit ids |

### Rewritten (4)

| Test | Rewrite |
|---|---|
| `test_coverage_change_that_strands_a_mode_scoped_finding_is_rejected`, [test_app.py#L696](../../tests/test_app.py#L696) | Keep the test, change its subject. Its docstring is right about *why* it exists — it is the only test of the before/after branch. Under a custom-only world the finding that reaches that branch is one located **only** by `custom_locations` with no ids. Rewrite as `test_removing_an_environment_that_held_a_findings_only_typed_location_is_rejected` — the environment twin of the app-type test that already exists at [test_app.py#L751](../../tests/test_app.py#L751) |
| `test_generator_locations_use_typed_endpoints_grouped_by_channel`, [test_app.py#L959](../../tests/test_app.py#L959) | Replace the `{"mode": "all"}` widening stanza with explicit ids read from the prior save's `scope_targets`, and assert the printed list matches those ids in the order given. The channel-ordering guarantee moves to the migration test, because after this change the printer honours stored order and the *migration* owns the sort |
| `test_typed_endpoints_reach_the_report_even_when_the_finding_covers_everything`, [test_app.py#L993](../../tests/test_app.py#L993) | Its premise is already false — the Findings page switches to custom on every commit. Drop the `scope.mode == "all"` round-trip assertion and the misleading docstring; keep the real value as `test_typed_endpoints_print_alongside_selected_targets` |
| The five incidental `scope: {"mode": "all"}` uses at [L797](../../tests/test_app.py#L797), [L831](../../tests/test_app.py#L831), [L896](../../tests/test_app.py#L896), [L924](../../tests/test_app.py#L924), [L1045](../../tests/test_app.py#L1045) | Each wants "this finding covers both environments", not the mode. Thread the ids through from the prior save's response via one small helper, `target_ids_of(response)` |

### Not touched — checked, and clear

The eight scope-less `Vulnerability(...)` constructions **need no change**. Seven exercise `provision` and `apply_poc_variant` only, and neither reads `scope`; none builds a `Report` or calls `sync_evidence_image_slots`. The eighth assigns an explicit scope four lines later. The default flip is invisible to all eight. The oracle flagged them as a risk; on inspection the risk is not realised, and the plan records that rather than making eight cosmetic edits.

Likewise `tests/test_docx.py`, `tests/test_docx_import.py`, and all five `Scope(...)` constructions in `tests/test_browser.py` already build custom scopes.

### New (10)

| Test | Where | What it proves |
|---|---|---|
| `test_a_legacy_all_scope_loads_as_explicit_custom_targets` | test_storage.py | **The `draft.bak.json` case.** Write a draft with `mode: "all"`, `target_ids: []`, four targets; `workspace.load`; assert mode is custom and all four ids present. The one test that would have caught a naive relabel |
| `test_a_legacy_scope_drops_target_ids_that_no_longer_exist` | test_storage.py | Write `mode: "all"` carrying an id absent from `scope_targets`; assert the report **loads** and the stale id is gone. Guards invariants 3 and 4: the failure prevented is a report vanishing into the legacy list, not an exception |
| `test_migrated_locations_print_exactly_as_they_did_before` | test_app.py | Build a report whose stored id order differs from channel-sorted order; assert `_finding_locations` returns the channel-sorted list after migration |
| `test_the_environment_modes_freeze_to_the_targets_they_resolved_to` | test_app.py | `all_production` on a two-environment report yields production ids only, and stops widening when a new production target is added |
| `test_a_repaired_draft_keeps_its_migrated_scope_on_disk` | test_storage.py | Run `repair_duplicate_fragment_ids`, re-read the raw JSON, assert `mode == "custom"`. Guards invariant 6 |
| `test_an_imported_bundle_arrives_with_custom_scopes` | test_app.py | `import_report` with a legacy payload. Guards the entry path that skips both `load_path` and `reconcile_targets` |
| `test_a_scope_mode_that_escapes_the_migration_still_loads` | test_app.py | `Scope.model_validate({"mode": "all"})` coerces rather than raising. Guards the demotion safety net |
| `test_removing_one_of_several_scope_lines_still_saves` | test_app.py | The worked example, inverted. Four targets, a finding holding all four, delete one line → 200, finding keeps three ids. **Proves the change is not a regression** |
| `test_removing_a_findings_only_location_is_still_refused` | test_app.py | The strict case that must survive the relaxation: a finding holding exactly one id whose line is deleted is still a 422 `referenced_scope_removed` |
| `test_browser_scope_stranding_warning_matches_server_refusal` | test_browser.py | The contract test. **The first drift guard on any scope row**, guarding the row that had already drifted |

---

## 6. Open questions

1. **The 422 fix is roughly as much work as the migration itself.** §4 recommends both the client purge and the server purge as step 1. The cheaper alternative is server-side only — filter `target_ids` to survivors inside `reconcile_targets` and relax the strict branch, no client purge, no dialog change. That removes the regression for about a fifth of the effort, but means unticking an environment silently deletes location selections across findings with no prompt, and the client keeps warning about a case that no longer matches the server. *Absent an answer:* the full version, because "silently discards the tester's selections" is the one outcome this plan will not ship.
2. **Narrow the `Literal` in this change, or a later one?** Narrowing now with a coercion behind it is recommended. Keeping the three tokens legal is lower risk for this commit but blocks step 4 — the dead branches cannot honestly be deleted while the values they serve are legal, so the drift stays. *Absent an answer:* narrow now.
3. **Persist the migration on load, or leave it in memory?** In-memory only is recommended, so `draft.json` keeps `mode: "all"` until the next ordinary save. The cost is that anything reading the file directly sees the old shape. The alternative rewrites every draft on the first manager page load and consumes every backup at once. *Absent an answer:* in memory, recorded as a sharp edge in section 13.
4. **Prune `location_values` for filtered-out ids?** They become unreachable keys once their target is gone — never read, never validated, harmless. Pruning is two lines and makes the shape honest; leaving them means a re-added target silently restores the tester's old override text, which is arguably a feature. *Absent an answer:* leave them.
5. **Tell the tester a migration happened?** The 14-finding report will open one day with 56 boxes newly ticked that were previously all unticked. Nothing will be wrong, but nothing will announce it either. *Absent an answer:* stay silent, consistent with how the `test_type` migration shipped.

---

## What I would not do

**I would not put the migration in `load_path`.** It is the obvious home — it is where the other two legacy repairs live, and it already rewrites the file. But it is not the shared hook: `import_report` and both `parse_import` branches never go through it, so the migration would miss three entry paths and the `Literal` could never be narrowed. And because `list_reports` calls it once per draft, persisting from there rewrites every report on disk the first time the manager is opened, spending every one-of-one backup in a single click to change one string per finding.

**I would not relabel without resolving.** Setting `mode: "custom"` and keeping `target_ids` as found is one line and passes every test currently in the suite, because the one report on disk with non-custom scopes already has its ids filled in by the client-side backfill. It would also turn the backup of that same report into 14 findings with no location at all. The data that makes the shortcut look safe is data the browser wrote by accident.

**I would not ship the migration before the 422 fix.** The migration is precisely what converts that gap from theoretical to routine, and a tester who loses a save with no warning and no route forward will not care which commit introduced it.

## Round 2 - Oracle: verdict on the proposal

### Answer

The proposal is sound and the sequencing is right: relax the strict branch, add the survivor filter, migrate on the way in, keep the migration in memory. Four things must change before it is implementable — the union step should be dropped, the call-site contract (mutate vs. return) must be pinned or two of the three call sites are dead code, the sort key is named wrong, and the `draft.bak.json` evidence the plan is built around no longer exists in the tree. Three test items in §5 are mis-scoped and one new file is required. No draft on disk breaks under the proposed shape.

---

### 1. Risk rows that are wrong, in either direction

**Wrong as `RISK` — the evidence is gone.**

- **Migration fidelity (the `draft.bak.json` case).** The artefact this row rests on no longer exists. Both revisions of `2026-09_Annual_Pentest_c6ff01abda9e` now carry `"mode": "all"` with all four target IDs populated on all fourteen findings. A search for `"target_ids": []` across that report's directory returns nothing. The backup rolled over since the Round 0 pass. The row's *conclusion* — resolve before relabel — survives on other grounds (the two environment modes, hand-edited files, `parse_report_docx` output), but the plan's only real-data example is gone, the proposed `test_a_legacy_all_scope_loads_as_explicit_custom_targets` must now be built synthetically rather than harvested, and the "What I would not do → I would not relabel without resolving" argument should be rewritten to cite the environment modes instead.

**Wrong as `clear` — it is a risk, minor but real.**

- **Request/response asymmetry.** `reconcileCanonicalObject` adopts a canonical value only when `sameValue(liveValue, sentValue)`. `scope.target_ids` is a plain string array with no stable item key, so it lands in that branch. A tester who ticks a box while a save is in flight loses the canonical migration for that finding and keeps `mode: "all"` on the live page. It self-heals on the next PUT, so the disposition is right; "clear" is not.

**Correct as `RISK`, but understated.**

- **Rule drift.** The row names the right files, but the specific drift that bites here is unnamed: `scope_has_location` returns `bool(scope.target_ids)` and **never checks that those IDs resolve**, while `_scope_reaches_a_location` intersects them against the surviving target list. These are two different predicates wearing one name. Today `scope_has_location`'s honesty is guaranteed entirely by `Report.validate_references`, which only fires on `mode == "custom"`. After the migration every finding is custom, so the shape is safe — but this is the precise reason step 1's two halves cannot ship apart, and the plan attributes it only to the error blob.
- **Backup exhaustion.** Stronger than stated. `list_reports` calls `load_path` once per draft, and `list_legacy_reports` calls it *again* per draft on the same manager render. A persisting migration would rewrite every draft twice per page load in the worst case. Also worth recording in the plan's favour: `load_path` writes **before** it validates, so an in-place before-validator mutation cannot be accidentally persisted by that path.

**Correct as `clear`, for a reason the plan does not give.**

- **Undo replay.** The row is right, and stronger than stated: `restoreHistory` applies the diff, calls `save()`, then reloads the page, so a replayed `mode: "all"` reaches call site 2 within the same interaction and the page is re-seeded from the canonical response. But `sessionStorage` is not the only replay carrier — the `localStorage` local-draft envelope stores the whole `report` object and restores it on reload. Same disposition, but it belongs in the row.

**Correct as written** (verified, no change needed): navigation trap, orphan reference, stale write, lost update, two findings one display ID, silent stranding, derived-state fight, 422 reachability, schema break. On schema break, one precision note: a `mode="before"` field validator does **not** run when `mode` is absent from the payload — the field default supplies `"custom"` there, not the coercion.

**Evidence-slot narrowing** is a genuine risk and correctly marked, with one correction. `sync_evidence_image_slots` does not touch an uploaded or captioned image, as claimed. But the generalised `dropTargetsEverywhere` proposed in step 1 writes `target_ids` directly without routing through `settleScopeChange`, exactly as `dropChannelEverywhere` already does — so a finding that loses its only non-production location keeps its non-production images, which `fragment_applies` then hides from generation without any dialog. That is the existing precedent's behaviour, so it is defensible, but the plan's "reword the dialog" item needs to say that hidden-not-deleted is the intended outcome.

**A row that is missing entirely.** Because call site 2 runs *before* `reconcile_targets`, the payload still carries the pre-edit `scope_targets`. On the first Setup save after the migration, a tester who adds a scope line gets that target created **and** every `mode: "all"` finding frozen to the IDs that existed before that same save — so the newly added line is silently excluded from every legacy finding, on the one save where the old behaviour would have included it. Note that the only reason call site 2 must precede `reconcile_targets` is the `mode == "custom"` test that step 1 deletes; once step 1 lands, the call can move *after* `reconcile_targets` for strictly better fidelity.

---

### 2. Migration mechanics

**(a) The early returns — confirmed exactly as claimed.** `if not isinstance(data, dict): return data` at [models.py#L271](../../app/models.py#L271), then `engagement = data.get("engagement")` at [L273](../../app/models.py#L273), then `if engagement is not None and not isinstance(engagement, dict): return data` at [L274](../../app/models.py#L274). A call placed between them is reached by `Workspace.create_report`, which passes `engagement=Engagement(...)` at [workspace.py#L116](../../app/workspace.py#L116) — Pydantic hands the before-validator the kwargs mapping, so the first guard passes and the second fires.

One hole. Placing the call above the `engagement` guard means it also runs on constructions where `scope_targets` holds `ScopeTarget` **instances**. The plan says what to do about model *findings* (skip them) but only says "tolerate" for model targets. If tolerating means treating them as absent, the resolve step yields an empty ID set and the filter blanks the finding's locations. The safe rule is: **if `scope_targets` is not a list of dicts, return the mapping untouched.** Latent rather than live today — no call site mixes model targets with dict findings — but the plan chose this position precisely to cover model-instance construction.

**(b) The sort key — wrong as written, right in effect.** The exact expression at [docx_report.py#L1017](../../app/docx_report.py#L1017) is:

```python
sorted(targets.values(), key=lambda item: (CHANNEL_ORDER.index(item.channel), item.order))
```

`CHANNEL_ORDER = list(CHANNELS)` at [docx_report.py#L46](../../app/docx_report.py#L46) — a copy, not a re-export. So `CHANNELS.index(...)` is value-identical and is the correct thing to write in `models.py`, since importing `CHANNEL_ORDER` there would invert the dependency. The plan should say "`CHANNELS`, which `docx_report.CHANNEL_ORDER` is a `list()` copy of". Two further details that make the migration reproduce printed order exactly: the non-custom branch sorts the **whole** target collection once and then buckets by environment, and `order` is a per-(environment, channel) index assigned by the `enumerate` in `reconcile_targets`, so cross-environment ties are resolved by Python's stable sort and are invisible after bucketing. A migration that applies the same global `(channel, order)` sort per finding produces byte-identical output.

**(c) The union — no widening via the UI, and the stated justification does not hold.**

`renderFindings` computes `selectedTargets` as `mode === "custom" ? target_ids : []`, so a non-custom finding renders with **every box unticked** regardless of what the backfill wrote. There is nothing to untick. Any checkbox interaction runs `updateLocations`, which replaces the scope wholesale with `{mode: "custom", target_ids: <what is checked>, ...}`. A narrowed selection therefore cannot sit under a non-custom mode by that route.

The only client writer that narrows `target_ids` without flipping `mode` is `dropChannelEverywhere` — and it removes the same targets from `report.scope_targets` in the same call, so the resolve step resolves to the narrowed set anyway and the union is a no-op. (The typed-endpoint `oninput` handler writes `custom_locations` and never touches `mode`, but it adds nothing to `target_ids`.)

So for `mode: "all"` — the only retired mode present on disk — the union is **provably a no-op in every reachable case**, and the plan's justification ("so the client backfill's existing writes are preserved rather than recomputed away") describes a state the client cannot produce. For `all_production` and `all_non_production` the union is **not** a no-op and is a genuine widening: an existing ID pointing at the other environment — reachable via hand-edit or DOCX import, which is exactly the population those modes exist to serve — would be unioned in, adding an environment to `affected_environments`, an image slot from `sync_evidence_image_slots`, and a screenshot demand from `generation_issues`.

**Drop the union.** Resolve → filter → sort → relabel. It loses nothing reachable and removes the only widening path.

**(d) Pydantic ordering — correct.** With `pydantic==2.13.5` as pinned, a `field_validator(..., mode="before")` wraps the field's core schema and runs ahead of `Literal` enforcement, so `Scope(mode="all")` coerces rather than raising. Two caveats worth a line in the plan: it does not run when `mode` is absent, and it does not run on `model_copy`, which `Workspace.duplicate` uses — that path is covered only because its source already came through `load`.

**(e) `repair_duplicate_fragment_ids` — confirmed at the line claimed, but the call site as written cannot work.** `Report.model_validate(draft)` at [workspace.py#L238](../../app/workspace.py#L238), `atomic_write_json(path, draft)` at [L239](../../app/workspace.py#L239), `return self.load(report_id)` at [L240](../../app/workspace.py#L240). So yes — the raw draft is persisted after validation, and a migration that only lives in the model would be lost here.

But the plan specifies `normalise_scope_modes(report_mapping) -> report_mapping`, "raw mapping in, raw mapping out", modelled on `_migrate_poc_variant` — which is **pure**, returning a new dict. Call sites 2 and 3 are then written as bare statements: `normalise_scope_modes(payload)` and `normalise_scope_modes(draft)`. With a pure function those two lines are no-ops, and call site 3 would persist the un-migrated draft, defeating its own purpose. Either the function mutates in place, or all three call sites assign the result. In-place is the safer of the two, because `load_path` writes before it validates — so an in-place mutation there still cannot leak to disk.

---

### 3. The 422 decision

**`dropChannelEverywhere` does what the plan says, and slightly more.** It blanks `report.scope_text[environment][channel]`, filters `target_ids` on every finding regardless of mode, deletes matching `location_values`, deletes the channel out of `custom_locations` (pruning emptied environments), **and removes the targets from `report.scope_targets`**. That last step means a generalised `dropTargetsEverywhere(targetIds)` is not a straight extraction: for the environment path the server rebuilds `scope_targets` from `scope_text` and `tested_environments`, and for the scope-text path the textarea is the source, so neither may remove targets itself. Only the per-finding half generalises.

**The environment path is genuinely missing an equivalent.** The checkbox `onchange` confirms via `confirmScopeLoss`, sets `tested_environments`, re-renders, and schedules a save — no purge, and no target removal. The scope-text commit confirms via `confirmScopeTextLoss` and then either accepts or reverts the textarea — no purge. Both then hand a payload to `reconcile_targets`, which is where the 422 fires. The plan's reading is correct.

**Does anything else read `scope.target_ids` expecting them all to resolve?** One thing, and it is a hard error rather than a silent fault: `Report.validate_references` at [models.py#L302](../../app/models.py#L302) raises when a custom finding's IDs are not a subset of `scope_targets`. That is why option (b) — relaxing the branch alone — produces an `invalid_report` blob instead of a clean save. Every other reader is tolerant: `affected_environments` and `affected_channels` use `target_by_id.get(...)` guarded by `if target:`; `_scope_reaches_a_location` intersects; `_finding_locations` uses `targets.get(...)` guarded by `if target:`; `docx_import._empty_proof` uses `by_id.get(...)` guarded by `if target`; every JavaScript reader uses `.find(...)?.` or `.some(...)`.

**The dangerous inverse is `scope_has_location`**, which returns `bool(scope.target_ids)` and never resolves them — so a finding holding nothing but dangling IDs reads as "has a location", gates `/edit` open, and passes `finding_is_complete`. Its JavaScript twin has the same shape. The survivor filter and `validate_references` are therefore **jointly** load-bearing for that predicate's truthfulness, which is the exact reason neither (a) nor (b) can ship alone. The plan reaches the right conclusion; it should carry this reason.

**The precedent is verified.** Because `dropChannelEverywhere` removes the doomed IDs and their targets before the PUT, the app-type path already never reaches the strict branch — it is already living under the proposed regime, and has been since that purge landed.

---

### 4. Files and tests the planner missed

1. **[tests/test_storage.py](../../tests/test_storage.py) is absent from the §1 blast-radius table** although §5 adds three tests to it — and it is the wrong file. It contains exactly one test, `test_atomic_write_retries_transient_permission_error`, and imports nothing from `workspace`. Every existing legacy-migration test lives in [tests/test_app.py](../../tests/test_app.py): `test_workspace_restores_legacy_app_types_and_repairs_empty_lists`, `test_the_retired_test_type_token_migrates_on_every_entry_path`, `test_legacy_duplicate_fragment_repair`. The three proposed tests belong there.
2. **[docs/FORM_DEPENDENCIES.md](../FORM_DEPENDENCIES.md) is not listed.** Its row recording `scope_targets[].target_id/value → vulnerabilities[].scope.target_ids/location_values` as **one-way** stops being true once both purges exist. The plan lists only `docs/DATA_MAP.md`.
3. **The `scope_text` seeding block in [app.js#L1181](../../app/web/static/app.js#L1181) is unlisted.** It derives `scope_text` from `scope_targets` when absent and is the thing that makes the scope-text purge implementable. Correctly unchanged, but it should appear in the "checked, not overlooked" column.
4. **The `Scope(...)` count in [tests/test_browser.py](../../tests/test_browser.py) is wrong** — six constructions (L468, L797, L1068, L1083, L1097, L1299), not five, plus a dict scope literal in the `ready_report` fixture at L70. All are already `custom`, so the conclusion stands.
5. **Second half of a twinned rule, half-caught.** The plan's app.js row correctly drops `scopeHasLocation`'s `mode === "custom" &&` guard. What it does not say is that the Python half has no such guard — `scope_has_location`'s custom branch already ORs `target_ids` with typed locations unconditionally. The two are *currently asymmetric*, and dropping the JS guard is what brings them into line. That asymmetry is the live subject of `test_typed_endpoints_reach_the_report_even_when_the_finding_covers_everything`.
6. **Nothing under `scripts/` or `resources/` reads `scope.mode`** — verified, and worth stating rather than leaving open.

**Three §5 test items are mis-scoped.**

- Deleting the `Scope(mode="all")` stanza from `test_affected_channels_resolve_the_proof_of_concept_variants` is **not** "two lines and their comment". The next assertion, `applicable_poc_variants(finding, report, {"api": [1]}) == ["api"]` at [test_app.py#L406](../../tests/test_app.py#L406), sets no scope of its own and runs against the scope that stanza installs. Delete the stanza and it falls back to the typed-endpoint custom scope four lines earlier, resolves web-only, and returns `[]`. The rewrite has to give it its own scope.
- `test_coverage_change_that_strands_a_mode_scoped_finding_is_rejected` has a **third** stanza the plan's prose never mentions — [test_app.py#L720](../../tests/test_app.py#L720) onward, "Narrowing that leaves the finding a location is still allowed", which re-widens non-production scope text and asserts 200. The rewrite must carry it or explicitly drop it.
- `test_generator_locations_use_typed_endpoints_grouped_by_channel` **would pass unchanged** after a correctly-sorted migration, and it is currently the only assertion in the suite pinning printed `(channel, order)` ordering. Leaving it alone is cheaper than rewriting it and makes it a free before/after equivalence check.

**And the "five incidental" `{"mode": "all"}` uses split two ways.** L896, L924 and L1045-1046 pass unchanged. L797 and L831 do not — both narrow an environment via `scope_text` on a later PUT and assert 200, which is exactly the save the strict branch refuses. They are already the regression tests for step 1, not cosmetic.

One minor correction to the planner's own audit: the claim that none of the eight scope-less `Vulnerability(...)` constructions "builds a `Report`" is wrong for the one at [test_app.py#L386](../../tests/test_app.py#L386), though the planner's own note that it is assigned an explicit scope four lines later covers the case.

---

### 5. On-disk drafts

**Nothing on disk breaks.** Every `scope.mode` value in `data/apps/` is either `"all"` (fourteen findings in `2026-09_Annual_Pentest_c6ff01abda9e/draft.json` and fourteen in its backup) or `"custom"` (everything else). No `all_production` or `all_non_production` exists anywhere. All fourteen `"all"` findings already carry all four target IDs, every one of which resolves, so they migrate to `custom` with exactly the IDs they hold, `validate_references` passes, `_finding_locations` output is unchanged, and nothing is demoted to the legacy list.

**The `draft.bak.json` case the plan is built around does not exist.** That backup holds `"mode": "all"` with all four IDs, identical to the live draft; there is no `"target_ids": []` under that directory. The resolve-first design is still correct defensive practice for imports and hand-edits, but the plan's fidelity argument currently cites data that has rolled over and should be rewritten around the environment modes.

**Does the in-memory-only decision leave bytes and behaviour disagreeing in a way that matters?** Three divergences, one of which matters.

- `repair_duplicate_fragment_ids` reads the raw draft and writes it back — **this is the one that matters**, and call site 3 is exactly the fix, provided the mutation actually lands in `draft` (see 2e).
- `load_path` writes **before** it validates, so a draft that trips one of the two existing legacy repairs gets its *un-migrated* bytes written and its *migrated* model returned in the same call. That is the intended behaviour, but it deserves a line in the sharp-edges section so nobody inspects a freshly rewritten file, sees `"mode": "all"`, and concludes the migration failed.
- `export_bundle` dumps the validated model and `Workspace.duplicate` copies it, so an export or a duplicate is migrated while its source file is not. Harmless, and identical to how the retired `test_type` migration already behaves.

---

### Invariants in play

- **Every custom finding's `target_ids` must resolve against `scope_targets`.** Enforced only by `Report.validate_references`. Violate it and the save dies as an `invalid_report` 422 — which is precisely what relaxing the strict branch without the survivor filter would produce.
- **`scope_has_location` is a presence check, not a resolution check.** Its truthfulness is borrowed entirely from the invariant above plus the survivor filter. Violate either and `/edit` opens on a finding with no printable location, and `generation_issues` declares a report ready that `_finding_locations` renders empty.
- **Printed location order is `(channel, order)` over the globally sorted target list, bucketed by environment.** A migration that stores IDs in any other order silently reorders every previously non-custom finding's Location cell.
- **The before-validator must be shape-tolerant.** It runs on kwargs mappings, import payloads, and raw drafts alike. Violate it and `create_report` raises, taking the New Report button with it.
- **`load_path` writes before it validates.** Depend on the opposite order and an in-memory migration becomes an accidental disk migration.
- **`scope_text` is request-only.** The server consumes it into `scope_targets` and never echoes it; the client re-derives it from `scope_targets` when absent.

---

### Both-sides warning

Every rule this plan touches exists twice and must change in the same commit:

| Rule | Python | JavaScript |
|---|---|---|
| a finding claims a location at all | `scope_has_location` | `scopeHasLocation`, `scopeTargetIds` |
| a scope still reaches a surviving target | `_scope_reaches_a_location` | `scopeReaches` |
| affected environments | `affected_environments` | `affectedEnvironments`, `scopeEnvironments` |
| affected app types | `affected_channels` | `affectedChannels` |
| finding completeness | `finding_is_complete` | `validateFindingsPage`, `updateFindingSummary` |
| which targets survive a coverage change | the target loop in `reconcile_targets` | `findingsStrandedBy`, `dropChannelEverywhere` (and whatever step 1 generalises it into) |
| canonical app-type order | `CHANNELS` in `models.py`; `docx_report.CHANNEL_ORDER` is a `list()` copy | `CHANNELS`, module scope in `app.js` |

Only `generation_issues` has a contract test. The scope rows above have **no drift guard** — if the two sides disagree, nothing in the suite notices.

---

### Map drift

Corrected in [docs/DATA_MAP.md](../DATA_MAP.md), section 12, and the "Last verified" line bumped:

- The "scope resolves to a location" row paired `scope_has_location` with `_scope_reaches_a_location` as though they implemented one rule. They answer different questions — presence versus resolution — and the row is now split into two, with the presence row marked as not checking that IDs resolve.
- "canonical app-type order" said `CHANNELS` is "imported by `docx_report.CHANNEL_ORDER`". `CHANNEL_ORDER` is a `list()` copy, not a re-export — value-identical, not the same object, and `models.py` cannot import it back without a cycle.

## Round 2 - Planner: revised plan

## Understanding

`Scope.mode` stops being a resolution instruction and becomes a historical marker. Every scope becomes `mode: "custom"` carrying the explicit `target_ids` its old mode resolved to, filtered to targets that actually exist in the same mapping, and sorted so the generated document prints byte-identically. After that, roughly a dozen per-mode branches across Python and JavaScript collapse to one, the Findings page can draw ticks that match the rule it enforces, and `/edit` stops letting a finding through on the strength of a mode nobody can produce. The migration itself is small; the work is in `reconcile_targets`, because moving every finding onto the strict "any missing id strands you" branch would make a currently-rare 422 routine, and that has to be fixed **first**, as its own shippable step.

---

## Blast radius

| File | What changes | Why |
|---|---|---|
| [models.py](../../app/models.py#L130) | `Scope.mode` default flips to `"custom"`; `Literal` narrows to `Literal["custom"]`; new `field_validator("mode", mode="before")` on `Scope` coercing exactly the three retired tokens; new module function `normalise_scope_modes(report_mapping)` that **mutates in place**, called from inside `normalise_app_types` (renamed `normalise_legacy_shapes`), between the `isinstance(data, dict)` guard at [L271](../../app/models.py#L271) and the `engagement` guard at [L274](../../app/models.py#L274) | The `Report` `mode="before"` validator is the only hook every entry path shares, and only a report-level hook can see `scope_targets`, which the filter needs |
| [report_service.py](../../app/report_service.py#L253) | `affected_environments` loses three branches; `affected_channels` loses its `else`; `_scope_reaches_a_location` loses two branches; `scope_has_location` loses two branches; `reconcile_targets` loses its `mode == "custom"` test and its trailing non-custom block, and **gains a survivor filter** on `target_ids` | The first four are dead-branch deletion. `reconcile_targets` is the only behavioural change, and it is the whole risk |
| [main.py](../../app/main.py#L661) | `save_report` calls `normalise_scope_modes(payload)` **after** `reconcile_targets` and before `Report.model_validate`; the `"all"` comment above `insert_library`'s `Scope(mode="custom")` is rewritten | Placement is a decision, not an accident — see the "first Setup save after migration" risk row |
| [workspace.py](../../app/workspace.py#L238) | `repair_duplicate_fragment_ids` calls `normalise_scope_modes(draft)` before `Report.model_validate(draft)`. `load_path` is deliberately **not** touched | That method persists the raw dict after validating. `load_path` writes *before* it validates, so an in-place mutation there provably cannot reach disk |
| [docx_report.py](../../app/docx_report.py#L1003) | `_finding_locations` loses its `else` branch and its `{...}[mode]` dict lookup | That dict is a latent `KeyError`, and it is the only mode branch whose output reaches the document |
| [app.js](../../app/web/static/app.js#L952) | `scopeTargetIds` collapses to an accessor; `scopeHasLocation` drops its `mode === "custom" &&` guard; `scopeEnvironments` and `affectedChannels` drop their mode tests; `scopeReaches` drops two branches; the Findings-page backfill is **deleted**; the `renderFindings` ternary is **deleted**; new `dropTargetsEverywhere(targetIds)` (per-finding purge only) extracted from `dropChannelEverywhere` and called from the environment checkbox and the scope-text commit; `findingsStrandedBy` and `scopeTextStrandedFindings` change predicate; three dialogs reworded | Both halves of every duplicated rule move in one edit. Dropping the `mode === "custom" &&` guard is what brings `scopeHasLocation` **into line with Python**, whose `scope_has_location` has no such guard and already ORs ids with typed locations unconditionally |
| [tests/test_app.py](../../tests/test_app.py) | One test deleted, three rewritten, **eleven new** — including all three legacy-migration tests | Every existing legacy-migration test already lives here (`test_workspace_restores_legacy_app_types_and_repairs_empty_lists`, `test_the_retired_test_type_token_migrates_on_every_entry_path`, `test_legacy_duplicate_fragment_repair`) |
| [tests/test_browser.py](../../tests/test_browser.py) | One new contract test. The six existing `Scope(...)` constructions (L468, L797, L1068, L1083, L1097, L1299) and the dict scope literal in `ready_report` at [L70](../../tests/test_browser.py#L70) need no change — all already custom | The scope-survival row is the row that already drifted and has no drift guard |
| [docs/DATA_MAP.md](../DATA_MAP.md) | Section 6 (the `validate_references` bullet), section 7 (the `reconcile_targets` row), section 8 (new legacy-repair entry), section 12 (six rows plus both client-only notes), section 13 (new sharp edge), "Last verified" | The maintenance contract at the top of that file requires it in the same change |
| [docs/FORM_DEPENDENCIES.md](../FORM_DEPENDENCIES.md) | The `scope_targets[].target_id/value → vulnerabilities[].scope.target_ids/location_values` row stops being **One-way**; rows 8 and 9 need their "the save is refused if one is stranded anyway" wording changed to match the new predicate | Once both purges exist, a Setup change writes back into finding scopes |
| [tests/test_storage.py](../../tests/test_storage.py) | **No change.** Explicitly *not* the home for the migration tests | It holds one test, `test_atomic_write_retries_transient_permission_error`, and imports nothing from `workspace` |
| [docx_import.py](../../app/docx_import.py#L364) | **No change** | Both branches already write `{"mode": "custom", ...}` |
| The `scope_text` seeding block in [app.js#L1181](../../app/web/static/app.js#L1181) | **No change** | It derives `scope_text` from `scope_targets` when absent, and it is the thing that makes the scope-text purge implementable. Checked, not overlooked |
| [tests/test_docx.py](../../tests/test_docx.py#L585), [tests/test_docx_import.py](../../tests/test_docx_import.py#L75) | **No change** | Both already build `Scope(mode="custom", target_ids=[...])` |
| `scripts/`, `resources/` | **No change** | Verified: nothing under either reads `scope.mode` |

---

## Data risks

| Failure mode | Verdict | Reasoning and what handles it |
|---|---|---|
| Stale write | **clear** | The migration adds no mutation path. It runs inside validation on paths that already carry `saved_at` in the PUT body, or that never send one. In-memory only, so `saved_at` is untouched on load and no open tab is spuriously 409'd |
| Lost update | **clear** | No new read-modify-write. Both persisting call sites — `repair_duplicate_fragment_ids` and the ordinary save path — already run inside `Workspace._locked` |
| Orphan reference | **RISK** | Rewriting mode to custom makes [models.py#L302](../../app/models.py#L302) enforce `target_ids ⊆ scope_targets` on data never checked before. Handled by filtering inside the migration against the mapping's own `scope_targets`, which is why it must be report-level: a `Vulnerability` validator cannot see that set |
| Silent stranding | **RISK** | A legacy finding on a report with no resolvable targets becomes locationless and blocks `/edit`. That is the fix, not a defect, but it is a visible state change. `updateFindingSummary` already counts it, `/edit` already redirects to `/findings?incomplete=findings`, and one tick clears it |
| Schema break | **RISK** | An existing `draft.json` holding `"all"` must still load. Handled twice: the report-level migration rewrites `mode` before the `Literal` is checked, and the `Scope.mode` field coercion catches anything reaching `Scope` without passing that hook. **Precision note:** a `mode="before"` *field* validator does **not** run when `mode` is absent from the payload — there the field default supplies `"custom"`, not the coercion |
| Request/response asymmetry | **RISK**, minor | `reconcileCanonicalObject` adopts a canonical value only when `sameValue(liveValue, sentValue)`. `scope.target_ids` is a plain string array with no stable item key, so it lands in that branch. A tester who ticks a box while a save is in flight loses the canonical migration for that finding and keeps `mode: "all"` on the live page. Self-heals on the next PUT |
| Rule drift | **RISK** | The specific drift: `scope_has_location` returns `bool(scope.target_ids)` and **never checks the ids resolve**, while `_scope_reaches_a_location` intersects them against the surviving targets. Two different predicates wearing one name. `scope_has_location`'s honesty is borrowed entirely from `validate_references` (which fires only on custom) plus the survivor filter — which is the exact reason step 1's two halves cannot ship apart. Handled by moving both sides of all nine paired rules in one commit and adding the first contract test on a scope row |
| Navigation trap | **clear** | `setup_issues` already requires at least one scope target per tested environment before `/findings` is reachable, so any tester who can see a newly-blocked finding can also see a checkbox that unblocks it. A deep link to `/edit` bounces once, not in a loop |
| Derived-state fight | **RISK** | The Findings-page backfill is a client-side derived-state writer with no server counterpart; leaving it while the server owns normalisation means two writers for one field. Handled by deleting it. `provision_report` never reads or writes scope, so there is no fight on the save path |
| Backup exhaustion | **RISK** | Worse than a single pass: `list_reports` calls `load_path` once per draft **and** `list_legacy_reports` calls it again per draft on the same manager render, so a persisting migration would rewrite every draft twice per page load and consume every one-of-one `draft.bak.json`. Handled by migrating in memory only. Recorded in the plan's favour: `load_path` writes **before** it validates, so an in-place before-validator mutation cannot leak to disk from there |
| Migration fidelity | **RISK** | Re-evidenced. The empty-`target_ids` artefact that motivated this row has rolled over — both revisions of the fourteen-finding draft now carry `mode: "all"` with all four ids. The risk lives on in three populations the tree cannot demonstrate: the **two environment modes**, which hold no ids at all by construction, so relabelling them yields a locationless finding *every* time; hand-edited files; and `parse_report_docx` output. Handled by resolve → filter → sort → relabel, with a **synthetically built** fidelity test |
| Legacy-invalid demotion | **RISK** | A `ValidationError` on load demotes a draft to `list_legacy_reports` rather than failing loudly. Two routes in: a stale id under a rewritten mode, and a retired token that dodges the migration. Handled by the filter and by the field coercion, which degrades to a recoverable state (custom, possibly no ids, visibly incomplete) instead of an unopenable one |
| 422 reachability change | **RISK**, the largest | Every finding moves from the lenient before/after branch to the strict "any missing id" branch. On the fourteen-finding report, deleting one Setup line goes from a clean save to a refusal naming all fourteen, with no dialog first. Decided in step 1, not deferred |
| Printed-output reordering | **RISK** | A migrated finding would print Location rows in stored `target_ids` order where it used to print them sorted. Handled by making the migration emit ids in exactly the printer's sort order — see step 2 |
| Client/server stranding divergence | **RISK** | The client warns only on total loss of location; the server refuses on any lost id. `"all"` masks the gap today on the one report that would hit it. Handled in step 1 by collapsing the two into one predicate |
| Evidence-slot narrowing | **RISK** | `sync_evidence_image_slots` never touches an uploaded or captioned image — confirmed. But `dropTargetsEverywhere` writes `target_ids` directly without routing through `settleScopeChange`, exactly as `dropChannelEverywhere` already does, so a finding that loses its only non-production location **keeps** its non-production images and `fragment_applies` then hides them from generation with no dialog. Defensible as the existing precedent; **hidden-not-deleted is the intended outcome** and the reworded dialog must say so. Open question 1 |
| First Setup save after the migration | **RISK** | If the migration ran *before* `reconcile_targets`, the payload would still carry the pre-edit `scope_targets` — so a tester adding a scope line would get the target created **and** every legacy finding frozen to the ids that existed before that same save, silently excluding the new line on the one save where the old behaviour would have included it. **Eliminated by placing call site 2 *after* `reconcile_targets`**, which step 1 makes possible by deleting the `mode == "custom"` test that was the only reason to run earlier |
| Undo replay reintroduces a retired mode | **clear** | `undoHistory` lives in `sessionStorage` and `restoreHistory` applies the diff, saves, then reloads — so a replayed `mode: "all"` reaches call site 2 within the same interaction. `sessionStorage` is not the only carrier: the `localStorage` local-draft envelope stores the whole `report` and restores it on reload. Both land on the same two nets — call site 2, then the field coercion |
| Two findings, one `display_id` | **clear** | Nothing in the migration touches `display_id`, `uid`, `frag_id`, or `evidence_id` |

---

## Plan

### Step 1 — Fix the 422, both sides, before anything else

**Files:** `report_service.py` (`reconcile_targets`), `app.js` (`dropChannelEverywhere` → extracted `dropTargetsEverywhere`, the environment checkbox, the scope-text commit, `findingsStrandedBy`, `scopeTextStrandedFindings`, the three dialogs), `docs/FORM_DEPENDENCIES.md`.

**The problem.** `reconcile_targets` strands a custom finding when **any** of its `target_ids` disappears, and a non-custom finding only when the report loses **every** location. The client warns only in the second case. Universal custom exposes that gap on every report at once.

**Server.** Inside `reconcile_targets`, once the new `target_ids` set is known, filter each finding's `target_ids` down to survivors *before* the reach check, then strand only on `reached_before and not reaches_now`. The `mode == "custom"` test and the trailing non-custom block collapse into one path.

**Client.** Extract **only the per-finding half** of `dropChannelEverywhere` into `dropTargetsEverywhere(targetIds)`: filter `scope.target_ids`, delete the matching `location_values`. It is *not* a straight extraction — `dropChannelEverywhere` also blanks `scope_text[environment][channel]`, prunes `custom_locations` by channel, and **removes the targets from `report.scope_targets`**. Those three stay where they are, because on the environment path the server rebuilds `scope_targets` from `scope_text` × `tested_environments`, and on the scope-text path the textarea is the source; neither may remove targets itself. Call the new helper from the environment checkbox after `confirmScopeLoss`, and from the scope-text commit after `confirmScopeTextLoss`, passing the ids `survivingAfterScopeText` just excluded. Change `findingsStrandedBy` and `scopeTextStrandedFindings` to count findings losing **any** selection, distinguishing those left with none, and reword the three dialogs to match — including the hidden-not-deleted sentence from open question 1.

**Why both halves, and why neither ships alone.** `scope_has_location` is a presence check that never resolves its ids; its truthfulness is borrowed entirely from `validate_references` plus the survivor filter. Relax the strict branch without the filter and a payload naming deleted targets sails past `reconcile_targets` into `validate_references`, which returns a raw Pydantic blob under `invalid_report`; relax it *with* a server filter but no client purge and the server silently deletes tester selections with no prompt. The client purge is the tester-facing story with an undo behind it; the server purge is the guarantee for payloads the browser did not build — imports, stale tabs, undo replays.

**Precedent, verified.** Because `dropChannelEverywhere` removes the doomed ids *and* their targets before the PUT, the app-type path already never reaches the strict branch. It has been living under the proposed regime since that purge landed. This step finishes a half-done job and is worth doing whether or not the migration ships.

**Tests:** `test_removing_one_of_several_scope_lines_still_saves`; `test_removing_a_findings_only_location_is_still_refused`; `test_browser_scope_stranding_warning_matches_server_refusal`. The two existing tests at test_app.py L797 and L831 already are this step's regression guard — both narrow an environment via `scope_text` on a later PUT and assert 200, which is exactly the save the strict branch would refuse. Leave them unchanged and add a one-line comment saying why.

**Invariant:** a save the client did not warn about must not be refused.

### Step 2 — Add `normalise_scope_modes` and its three call sites

**Files:** `models.py`, `main.py`, `workspace.py`.

**The contract — in place, not pure.** `normalise_scope_modes(report_mapping) -> None`, mutating each finding's scope dict where it sits. This is the one decision that makes call sites 2 and 3 real: written as bare statements against a pure function they would be no-ops, and call site 3 would persist the un-migrated draft, defeating its own purpose. In-place is safe specifically because `load_path` writes **before** it validates, so a mutation there cannot leak to disk.

**The order — resolve → filter → sort → relabel.** There is no union step.

1. **Resolve.** `all` → every target id in the mapping; `all_production` → production target ids; `all_non_production` → non-production ids. The previously proposed union with any `target_ids` already present is dropped: for `mode: "all"` it is provably a no-op in every reachable case, because `renderFindings` draws every box unticked for a non-custom finding regardless of what the old backfill wrote, and any checkbox interaction runs `updateLocations`, which replaces the scope wholesale with custom. The only client writer that narrows `target_ids` without flipping mode is `dropChannelEverywhere`, and it removes the same targets from `scope_targets` in the same call, so the resolve step yields the narrowed set anyway. For the two environment modes the union is **not** a no-op and is a genuine widening — a stale id pointing at the other environment gets unioned in, adding an environment, an image slot, and a screenshot demand.
2. **Filter.** Keep only ids present in the mapping's own `scope_targets`.
3. **Sort.** By `(CHANNELS.index(channel), order)`. Write `CHANNELS.index(...)` in `models.py`: `docx_report.CHANNEL_ORDER = list(CHANNELS)` is a **copy, not a re-export**, and importing it back into `models.py` would invert the dependency. Two details make this reproduce printed order exactly: the printer's non-custom branch sorts the **whole** target collection once and only then buckets by environment, and `order` is a per-(environment, channel) index assigned by the `enumerate` in `reconcile_targets`, so cross-environment ties resolve by Python's stable sort and are invisible after bucketing. The same global sort applied per finding is byte-identical.
4. **Relabel.** Set `mode` to `"custom"`. Leave `custom_locations` and `location_values` untouched.

**Shape tolerance — a rule, not a vibe.** **If `scope_targets` is not a list of dicts, return the mapping untouched.** Call site 1 sits above the `engagement` guard, so it also runs on constructions where `scope_targets` holds `ScopeTarget` *instances*; treating those as absent would resolve to an empty id set and blank the finding's locations. Skip any vulnerability that is not a dict, any scope that is not a dict, and any `mode` outside the three retired tokens. The sort key must tolerate an unrecognised channel and a non-integer `order` rather than raising — same principle `resolve_tested_channels` already follows, letting the `Channel` literal do the rejecting so the validator never raises on its own.

**Call site 1 — inside `normalise_app_types`, renamed `normalise_legacy_shapes`.** Between the `isinstance(data, dict)` return at L271 and the `engagement is not None and not isinstance(engagement, dict)` return at L274. Not a second `mode="before"` validator: ordering between multiple before-validators is not something this plan should depend on.

**Call site 2 — `main.py`, on `payload`, immediately *after* `reconcile_targets`.** The only reason to run earlier was the `mode == "custom"` test that step 1 deletes. Running after means the migration resolves against the `scope_targets` `reconcile_targets` just wrote, so a legacy finding on a Setup save that adds a line gets that line — strictly better fidelity, and it removes the "first Setup save" risk row entirely. Consequence to accept: after step 4, a raw `mode: "all"` payload from a stale tab is evaluated by `_scope_reaches_a_location`'s custom branch inside `reconcile_targets`. With ids present it answers identically; with no ids `reached_before` is false, so the save is allowed and the migration then resolves it. Lenient in the safe direction.

**Call site 3 — `workspace.py`, on `draft`, before `Report.model_validate`.** That method validates and then persists the **raw** dict, so without the call a manager repair writes the pre-migration shape back. An in-place mutation at call site 1 may happen to reach `draft` through the validator too; the plan does not rest on that, because it depends on Pydantic handing the before-validator the same dict object rather than a copy.

**Paths and what happens to them:** `load_path` — migrated in memory, on-disk bytes keep `mode: "all"` until the next ordinary save (deliberate). `import_report`, both `parse_import` branches, `parse_report_docx` — covered by the same validator. `repair_duplicate_fragment_ids` — call site 3. `duplicate` — `model_copy` runs no validators, but its source came through `load`, so the copied model is already migrated. `create_report` — reached, because the call sits above the guard that would skip it; a no-op today.

**Tests:** `test_a_legacy_all_scope_loads_as_explicit_custom_targets` (synthetic: `mode: "all"`, `target_ids: []`, four targets → custom with four ids in channel-sorted order); `test_a_legacy_scope_drops_target_ids_that_no_longer_exist`; `test_migrated_locations_print_exactly_as_they_did_before`; `test_the_environment_modes_freeze_to_the_targets_they_resolved_to`; `test_a_repaired_draft_keeps_its_migrated_scope_on_disk`; `test_an_imported_bundle_arrives_with_custom_scopes`; `test_a_setup_save_that_adds_a_line_includes_it_in_a_migrated_finding`. **All in tests/test_app.py**, alongside the existing legacy-migration tests.

**Invariant:** purely additive — every existing test still passes, and no draft in `data/apps` moves to the legacy/invalid list.

### Step 3 — Flip the default, narrow the `Literal`, add the field coercion

**Files:** `models.py`.

`mode: Literal["custom"] = "custom"`, plus a `field_validator("mode", mode="before")` mapping exactly `all`, `all_production`, and `all_non_production` to `"custom"`. Anything else keeps today's outcome — rejected by the `Literal` — so this adds no new leniency. **Keep the `mode` field itself**: the migration needs to *see* a retired token to know it should resolve, and `extra="ignore"` would drop that signal silently. The field can go in a later change once nothing on disk carries one.

Pydantic caveats to record in the code comment: the field validator does **not** run when `mode` is absent (the default supplies `"custom"` there), and it does **not** run on `model_copy`, which `Workspace.duplicate` uses — covered only because its source came through `load`.

**Tests:** `test_a_scope_mode_that_escapes_the_migration_still_loads`, asserting both that `Scope.model_validate({"mode": "all"})` coerces and that an absent `mode` lands on the default rather than the coercion. Plus the rewritten tests below.

**Invariant:** `validate_references` passes for every draft in `data/apps`.

### Step 4 — Delete the dead branches, both sides

**Files:** `report_service.py`, `docx_report.py`, `app.js`.

Delete rather than leave unreachable, because **these are the branches that already drifted**: `_finding_locations`' non-custom branch sorts where its custom branch does not, and `scopeReaches`' non-custom branches ignore the `coverage` argument its custom branch respects. Unreachable code carrying a second, different answer to the same question is the drift mechanism, not a safety net. `scopeTargetIds` keeps its name with a one-line body, because the editor's finding card is its only remaining caller. Dropping `scopeHasLocation`'s `mode === "custom" &&` guard brings it into line with `scope_has_location`, which has no such guard — that asymmetry is the live subject of one of the tests being rewritten here.

**Tests:** existing suite plus the browser contract test.

**Invariant:** a finding's ticked boxes and its completeness verdict agree.

### Step 5 — Documentation

`docs/DATA_MAP.md` sections 6, 7, 8, 12, 13 and the "Last verified" line; `docs/FORM_DEPENDENCIES.md` rows 8, 9, and 10.

---

## Test plan, corrected

**Deleted (1).** `test_non_custom_scope_modes_resolve_report_targets` — it asserts three modes that can no longer exist let a report past `/edit`. Replaced by `test_the_environment_modes_freeze_to_the_targets_they_resolved_to`.

**Rewritten (3).**

| Test | Rewrite |
|---|---|
| The `Scope(mode="all")` stanza in `test_affected_channels_resolve_the_proof_of_concept_variants` | **Not a two-line deletion.** The next assertion sets no scope of its own and runs against the scope that stanza installs; delete it and the assertion falls back to the typed-endpoint web-only scope four lines earlier and returns `[]`. Replace the stanza with `Scope(mode="custom", target_ids=["tgt_web", "tgt_api"])` so the both-channels state survives for the "an app type the entry has no steps for is never offered" check |
| `test_coverage_change_that_strands_a_mode_scoped_finding_is_rejected` | Keep the test, change its subject to the finding located **only** by `custom_locations` — the environment twin of the app-type test — as `test_removing_an_environment_that_held_a_findings_only_typed_location_is_rejected`. It has **three** stanzas, not two: the 200 setup save, the 422 on unchecking Non-Production, and "Narrowing that leaves the finding a location is still allowed". Carry all three |
| `test_typed_endpoints_reach_the_report_even_when_the_finding_covers_everything` | Its premise is already false — the Findings page switches to custom on every commit. Drop the `scope.mode == "all"` round-trip assertion and the misleading docstring; keep the real value as `test_typed_endpoints_print_alongside_selected_targets` |

**Left alone deliberately (4).**

- `test_generator_locations_use_typed_endpoints_grouped_by_channel` — **would pass unchanged** after a correctly sorted migration, and it is the only assertion in the suite pinning printed `(channel, order)` ordering. Leaving it makes it a free before/after equivalence check.
- test_app.py L797 and L831 — both narrow an environment via `scope_text` on a later PUT and assert 200. That is exactly the save the strict branch refuses, so they are step 1's regression tests, not cosmetic. They also become legacy-payload regression tests, since the `{"mode": "all"}` literal now exercises call site 2.
- L896, L924, L1045-1046 — incidental, pass unchanged.
- The eight scope-less `Vulnerability(...)` constructions — no change. Seven exercise `provision` and `apply_poc_variant`, neither of which reads `scope`; the eighth does build a `Report` but is assigned an explicit scope four lines later.

**New (11).** Ten in tests/test_app.py: the seven listed in step 2, plus `test_a_scope_mode_that_escapes_the_migration_still_loads`, `test_removing_one_of_several_scope_lines_still_saves`, and `test_removing_a_findings_only_location_is_still_refused`. One in tests/test_browser.py: `test_browser_scope_stranding_warning_matches_server_refusal` — the first drift guard on any scope row, guarding the row that had already drifted.

---

## Open questions

Three remain. The verdict settled the other three — do both the client and server purges, narrow the `Literal` now with a coercion behind it, keep the migration in memory only — so those are folded into the plan above as decisions rather than questions.

**1. When a Setup change strips a finding's last location in one environment, should the browser prompt about that finding's screenshots for that environment, or stay silent and leave them hidden?**

Today, unchecking an app type runs `dropChannelEverywhere`, which strips the doomed target ids straight out of every finding's `scope.target_ids` without routing through `settleScopeChange` — the function that exists precisely to notice "this finding just lost its only Non-Production location and it has Non-Production screenshots", prompt, then delete those image fragments and release the orphaned evidence. Because the app-type purge bypasses it, such a finding silently keeps its screenshots and `fragment_applies` hides them from the document. Nothing is destroyed; nothing is printed either. The new `dropTargetsEverywhere` would inherit that bypass unless told otherwise.

- **Option A — follow the precedent (silent, hidden-not-deleted).** The purge strips ids only. Screenshots survive, stop appearing in the report, and reappear if the tester restores the location. Cost: a tester can produce a report missing evidence they uploaded, with only the readiness panel to hint at it.
- **Option B — route through `settleScopeChange`.** Each affected finding prompts, then its unrenderable images are deleted and unreferenced evidence released. Cost: a Setup edit touching fourteen findings can raise fourteen prompts, and confirming deletes uploaded work. It also makes the app-type path inconsistent unless changed too.
- **Option C — silent, but surfaced.** Option A plus a count in the Setup dialog: "3 findings will keep screenshots that stop appearing in the report." No deletion, no per-finding prompt.

*Recommendation: C.* It preserves the precedent's data behaviour exactly — nothing uploaded is deleted without a per-finding prompt — while ending the silence that makes it a trap.

**2. Prune `location_values` for filtered-out ids?** They become unreachable keys once their target is gone — never read, never validated, harmless. Pruning is two lines and makes the shape honest; leaving them means a re-added target silently restores the tester's old override text, which is arguably a feature. *Absent an answer:* leave them.

**3. Tell the tester a migration happened?** The fourteen-finding report will open one day with 56 boxes newly ticked that were previously all unticked. Nothing will be wrong, but nothing will announce it either. *Absent an answer:* stay silent, consistent with how the `test_type` migration shipped.

---

## What I would not do

**I would not put the migration in `load_path`.** It is the obvious home — it is where the other two legacy repairs live, and it already rewrites the file. But it is not the shared hook: `import_report` and both `parse_import` branches never go through it, so the migration would miss three entry paths and the `Literal` could never be narrowed. And because `list_reports` and `list_legacy_reports` each call it once per draft on the same manager render, persisting from there rewrites every report twice per page load, spending every one-of-one backup to change one string per finding.

**I would not relabel without resolving.** Setting `mode: "custom"` and keeping `target_ids` as found is one line and passes every test in the suite, because the only report on disk with non-custom scopes already has its ids filled in. But the two environment modes hold **no ids at all by construction** — relabelling one yields a locationless finding every time — and the same is true of any hand-edited or imported draft. The data that makes the shortcut look safe is data the browser wrote by accident.

**I would not ship the migration before the 422 fix.** The migration is precisely what converts that gap from theoretical to routine, and a tester who loses a save with no warning and no route forward will not care which commit introduced it.

## Answers

1. **Stale screenshots — option D, a fourth option the planner did not offer.** When a Setup change strips a finding's last location in an environment, **clear the `environment` field** on that finding's images for it. They then fail the existing "image requires environment" check, which blocks generation and lists them in the readiness panel, so the tester must reassign them to a surviving environment or delete them.

   Verified while answering: an image with **no** environment already blocks generation and already appears in the panel. `fragment_applies` returns `True` when `environment` is falsy (`not environment or environment in affected_environments(...)`), so such an image is not skipped — it reaches the `missing` list in `generation_issues` and its client twin, both of which report `environment` as required. The gap is only the **stale** image, whose environment is set to one the finding no longer affects; `fragment_applies` hides that one silently.

   This is better than the three options offered because it destroys nothing, hides nothing, and adds no new prompt — it routes the stale image into an error path that already exists on both sides of the wire. Accepted cost: one Setup edit can make several findings incomplete at once, which the tester then clears from the panel. Rejected: A and C (silent, hidden-not-deleted — the trap being fixed), and B (per-finding prompt that deletes uploaded work).

2. **Prune `location_values` for filtered-out ids.** Two lines. The stored shape stops carrying keys that point at nothing, and re-adding a location gives the plain target text rather than silently resurrecting an old override.

3. **Migrate silently.** No one-time notice. Consistent with how the retired `test_type` migration shipped.

Settled by the Round 2 verdict and therefore not asked: do both the client and server purges (not one alone), narrow the `Literal` now with a field coercion behind it, and keep the migration in memory only.

## Agreed plan

**What this delivers.** A finding with no ticked location is blocked everywhere — the Findings page, `/edit`, and generation all agree. `Scope.mode` stops being a resolution instruction; every scope carries explicit `target_ids`. Roughly a dozen per-mode branches across Python and JavaScript collapse to one, including two that had already drifted into giving different answers.

**Scope boundaries.** No new endpoint, no new persisted field, no schema migration on disk. Nothing in `data/apps/` breaks: all fourteen non-custom findings already carry ids that resolve, so they migrate byte-identically in the generated document. `scripts/` and `resources/` are untouched — verified, nothing there reads `scope.mode`.

### Step 1 — Fix the 422 first, both sides

Ships before anything makes the strict branch universal, and is worth doing on its own merits.

**Server** — [report_service.py](../../app/report_service.py): inside `reconcile_targets`, once the new target set is known, filter each finding's `target_ids` to survivors *before* the reach check, then strand only on `reached_before and not reaches_now`. The `mode == "custom"` test and the trailing non-custom block collapse into one path.

**Client** — [app.js](../../app/web/static/app.js): extract **only the per-finding half** of `dropChannelEverywhere` into `dropTargetsEverywhere(targetIds)` — filter `scope.target_ids`, **prune the matching `location_values`** (Answer 2), and **clear `environment` on images whose environment loses its last location** (Answer 1). It is not a straight extraction: `dropChannelEverywhere` also blanks `scope_text`, prunes `custom_locations`, and removes targets from `report.scope_targets`; those three stay where they are, because the environment path has the server rebuild `scope_targets` from `scope_text` × `tested_environments` and the scope-text path has the textarea as its source. Call it from the environment checkbox after `confirmScopeLoss` and from the scope-text commit after `confirmScopeTextLoss`. Change `findingsStrandedBy` and `scopeTextStrandedFindings` to count findings losing **any** selection, distinguishing those left with none, and reword the three dialogs to match.

- **Tests:** `test_removing_one_of_several_scope_lines_still_saves`; `test_removing_a_findings_only_location_is_still_refused`; `test_images_lose_their_environment_when_their_last_location_goes`; `test_browser_scope_stranding_warning_matches_server_refusal`. The existing tests at test_app.py L797 and L831 are already this step's regression guard — both narrow an environment via `scope_text` and assert 200, exactly the save the strict branch refuses. Leave them, add a one-line comment saying why.
- **Invariant:** a save the client did not warn about must not be refused. Nothing uploaded is deleted without a per-finding prompt.

### Step 2 — Add `normalise_scope_modes` and its three call sites

**Contract: mutates in place, returns nothing.** Written against a pure function, call sites 2 and 3 would be no-ops and call site 3 would persist the un-migrated draft. In-place is safe because `load_path` writes **before** it validates, so a mutation there cannot reach disk.

**Order: resolve → filter → sort → relabel.** No union step — for `mode: "all"` it is a no-op in every reachable case, and for the two environment modes it is a genuine widening that would add an environment, an image slot, and a screenshot demand.

1. **Resolve** — `all` → every target id; `all_production` / `all_non_production` → that environment's ids.
2. **Filter** — keep only ids present in the mapping's own `scope_targets`.
3. **Sort** — by `(CHANNELS.index(channel), order)`. Write `CHANNELS.index(...)` in [models.py](../../app/models.py); `docx_report.CHANNEL_ORDER` is a `list()` **copy**, and importing it back would invert the dependency.
4. **Relabel** — `mode = "custom"`, leaving `custom_locations` and `location_values` alone.

**Shape tolerance:** if `scope_targets` is not a list of dicts, return untouched. Skip any non-dict vulnerability or scope, and any mode outside the three retired tokens. Tolerate an unrecognised channel and a non-integer `order` rather than raising.

**Call sites:** (1) inside `normalise_app_types` — renamed `normalise_legacy_shapes` — between the `isinstance(data, dict)` return and the `engagement` guard; (2) [main.py](../../app/main.py), on `payload`, immediately **after** `reconcile_targets`, which step 1 makes possible and which removes the "first Setup save" risk entirely; (3) [workspace.py](../../app/workspace.py), on `draft`, before `Report.model_validate` in `repair_duplicate_fragment_ids`.

- **Tests, all in [tests/test_app.py](../../tests/test_app.py)** alongside the existing legacy-migration tests — **not** test_storage.py, which holds one unrelated test: `test_a_legacy_all_scope_loads_as_explicit_custom_targets` (built **synthetically**, since the empty-`target_ids` backup rolled over); `test_a_legacy_scope_drops_target_ids_that_no_longer_exist`; `test_migrated_locations_print_exactly_as_they_did_before`; `test_the_environment_modes_freeze_to_the_targets_they_resolved_to`; `test_a_repaired_draft_keeps_its_migrated_scope_on_disk`; `test_an_imported_bundle_arrives_with_custom_scopes`; `test_a_setup_save_that_adds_a_line_includes_it_in_a_migrated_finding`.
- **Invariant:** purely additive — every existing test passes, and no draft in `data/apps` moves to the legacy/invalid list.

### Step 3 — Flip the default, narrow the `Literal`, add the coercion

`mode: Literal["custom"] = "custom"` plus a `field_validator("mode", mode="before")` mapping exactly the three retired tokens to `"custom"`. Anything else is still rejected by the `Literal`, so this adds no leniency. **Keep the `mode` field** — the migration must see a retired token to know it should resolve, and `extra="ignore"` would drop that signal silently.

Record in the code comment: the field validator does **not** run when `mode` is absent (the default supplies it), and does **not** run on `model_copy`, which `Workspace.duplicate` uses — covered only because its source came through `load`.

- **Test:** `test_a_scope_mode_that_escapes_the_migration_still_loads`, asserting both the coercion and that an absent `mode` lands on the default.
- **Invariant:** `validate_references` passes for every draft in `data/apps`.

### Step 4 — Delete the dead branches, both sides

[report_service.py](../../app/report_service.py), [docx_report.py](../../app/docx_report.py), [app.js](../../app/web/static/app.js). Also delete the Findings-page `target_ids` backfill and the `renderFindings` `selectedTargets` ternary — the two halves of the display/rule disagreement being fixed.

Delete rather than leave unreachable, because **these are the branches that already drifted**: `_finding_locations`' non-custom branch sorts where its custom branch does not, and `scopeReaches`' non-custom branches ignore the `coverage` argument its custom branch respects. Unreachable code carrying a second, different answer is the drift mechanism, not a safety net. Dropping `scopeHasLocation`'s `mode === "custom" &&` guard brings it into line with Python, which has no such guard.

- **Invariant:** a finding's ticked boxes and its completeness verdict agree.

### Step 5 — Documentation

[docs/DATA_MAP.md](../DATA_MAP.md) sections 6, 7, 8, 12, 13 and the "Last verified" line. [docs/FORM_DEPENDENCIES.md](../FORM_DEPENDENCIES.md): the `scope_targets → scope.target_ids/location_values` row stops being **one-way** once both purges exist; rows 8 and 9 need their refusal wording updated.

### Test changes beyond the new ones

- **Deleted (1):** `test_non_custom_scope_modes_resolve_report_targets`.
- **Rewritten (3):** the `Scope(mode="all")` stanza in `test_affected_channels_resolve_the_proof_of_concept_variants` — **not a two-line deletion**, since the next assertion runs against the scope that stanza installs and would silently resolve web-only; `test_coverage_change_that_strands_a_mode_scoped_finding_is_rejected`, retargeted at the typed-location-only finding and carrying **all three** of its stanzas; `test_typed_endpoints_reach_the_report_even_when_the_finding_covers_everything`, whose premise is already false.
- **Left alone deliberately:** `test_generator_locations_use_typed_endpoints_grouped_by_channel` passes unchanged after a correctly sorted migration and is the only assertion pinning printed `(channel, order)` order — a free before/after equivalence check. L797 and L831 are step 1's regression tests. L896, L924, L1045-1046 are incidental. The eight scope-less `Vulnerability(...)` constructions are unaffected.

### Deliberately not done

- **No per-finding prompt and no deletion of screenshots** (Answer 1) — the environment is cleared instead, surfacing them as errors.
- **No one-time migration notice** (Answer 3).
- **The migration is not persisted from `load_path`** — `list_reports` and `list_legacy_reports` each call it once per draft on the same manager render, so persisting there would rewrite every report twice per page load and spend every one-of-one backup to change one string per finding. On-disk bytes keep `mode: "all"` until the next ordinary save; record that lag as a sharp edge.
- **`Scope.mode` is not deleted** — only narrowed. Removing the field belongs in a later change, once nothing on disk carries a retired token.
