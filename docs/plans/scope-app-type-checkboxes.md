# Scope app-type checkboxes (replace the Test Surface dropdown)

> **Status: implemented on 2026-09-15.** Steps 0 through 8 of the agreed plan are done, except step 0's two parity tests, which were replaced by three behavioural browser tests (`test_unchecking_an_app_type_confirms_then_clears_it_from_every_finding`, `test_a_finding_is_offered_only_the_app_types_it_has_not_installed`, `test_unchecking_a_location_in_the_page_withdraws_that_app_types_offer`). One requirement was added during execution and is not described below: **unchecking an app type now purges it from memory** — its scope targets, the per-finding affected locations selected against them, and the typed additional endpoints — behind a confirm dialog that counts exactly what goes. That replaces the plan's "warn, then let the server 422" behaviour for the channel axis. The deferred mobile scope table is still outstanding; the step 7 warning ships in its place.

## Request

> I think for the scope selection, instead of a drop down, let's do a checkbox instead on what app types will be tested as there may be mixed app types or even all app types in a single report.

## Round 1 - Oracle: how it works today

> Verbatim report from `data-oracle`. Evidence links are repo-root-relative as the oracle wrote them.

**Round 1 factual report.** No application code changed. Everything below was read from source; where `docs/DATA_MAP.md` or `docs/plans/` disagrees with source, the source wins and I say so.

### 1. The field itself

**Definition**

`TestType` is a four-token string literal, and `Engagement.test_type` is a required-with-default scalar:

- [app/models.py](app/models.py#L13) — `TestType = Literal["web", "api", "mobile", "web_api"]`
- [app/models.py](app/models.py#L12) — `Channel = Literal["api", "web", "mobile"]` (note the order differs from `CHANNEL_ORDER`)
- [app/models.py](app/models.py#L156) — `test_type: TestType = "web"`

`TestType` is **not** only used on `Engagement`. It is also the type of two fields on `Vulnerability` and the key type of the library's PoC dict:

- [app/models.py](app/models.py#L141-L142) — `poc_variant: TestType | None`, `poc_variant_declined: list[TestType]`
- [app/library.py](app/library.py#L23) — `proof_of_concept: dict[TestType, list[Fragment]]`

**Blunt:** these three are stored on disk today. Changing the `TestType` token set (e.g. adding `web_mobile`, or switching to a channel list) changes the validation surface of every existing draft that carries a `poc_variant`, and of `resources/vuln_library.json`.

**Every read/write of `engagement.test_type`**

Python — reads:

| Location | What it does |
|---|---|
| [app/report_service.py](app/report_service.py#L400-L403) | `engagement.get("test_type", "web")` from the **raw payload dict**, before Pydantic runs; raises `ValueError("test_type is invalid")` on an unknown token |
| [app/docx_import.py](app/docx_import.py#L537) | **writes** it, derived from imported scope-table channels |

That is the complete list. Grepped across `app/` — no other Python module reads `engagement.test_type`. Notably **`app/docx_report.py` never reads it** (see §7).

JavaScript — reads and writes:

| Location | What it does |
|---|---|
| [app/web/static/app.js](app/web/static/app.js#L1027) | seed: `report.engagement.test_type \|\|= "web"` |
| [app/web/static/app.js](app/web/static/app.js#L1153) | renders the `<select>` and marks the selected `<option>` |
| [app/web/static/app.js](app/web/static/app.js#L1156) | revert-on-cancel: `event.target.value = report.engagement.test_type` |
| [app/web/static/app.js](app/web/static/app.js#L1159) | the only client **write** |
| [app/web/static/app.js](app/web/static/app.js#L1185) | passes it to `confirmScopeLoss` when an environment checkbox toggles |
| [app/web/static/app.js](app/web/static/app.js#L1227) | drives which scope textareas the Setup grid renders |
| [app/web/static/app.js](app/web/static/app.js#L1519) | drives which "Additional affected endpoints" boxes the Findings page renders, with a `?? ["web"]` fallback |

[app/web/static/app.js](app/web/static/app.js#L21) is a false positive — that local is named `testType` but reads `engagement.report_type`.

**The legacy `tested_channels` migration — exact shape**

[app/workspace.py](app/workspace.py#L269-L286), inside `load_path`:

```python
engagement = draft.setdefault("engagement", {})
if "test_type" not in engagement:
    legacy_channels = set(engagement.pop("tested_channels", []))
    engagement["test_type"] = "web_api" if {"web", "api"} <= legacy_channels else "api" if "api" in legacy_channels else "mobile" if "mobile" in legacy_channels else "web"
    repaired = True
```

Three things matter for your change:

1. **It is gated on key absence, not on a schema version.** Once `test_type` exists it never runs again.
2. **It is lossy in exactly the direction you now want to reverse.** `{"web","mobile"}` collapsed to `"mobile"`; `{"web","api","mobile"}` collapsed to `"web_api"`. The dropped channels are **gone** — nothing on disk preserves them. Reversing the migration cannot recover them.
3. It rewrites the file in place via `atomic_write_json` ([app/workspace.py](app/workspace.py#L284-L285)) and is covered by [tests/test_app.py](tests/test_app.py#L275-L290).

### 2. The type→channel expansion

| Language | Location | Shape |
|---|---|---|
| Python | [app/report_service.py](app/report_service.py#L399) | `channels_by_type = {"web": ["web"], "api": ["api"], "mobile": ["mobile"], "web_api": ["web", "api"]}` — a **function-local** inside `reconcile_targets` |
| JavaScript | [app/web/static/app.js](app/web/static/app.js#L879) | `testTypes = {web:{label,channels:["web"]}, api:…, mobile:…, web_api:{label:"Web App + API", channels:["web","api"]}}` — module-scope, also carries UI labels |

There is a **third, inverse copy** in [app/docx_import.py](app/docx_import.py#L530-L537): `"web_api" if channels == {"web","api"} else (channels.pop() if len(channels) == 1 else "web")`.

**Consumers**

- Python `channels_by_type` has exactly one consumer: the target-building loop in [app/report_service.py](app/report_service.py#L403-L437) plus the `custom_locations` filter at [app/report_service.py](app/report_service.py#L445-L452).
- JS `testTypes` has five: [app.js#L1104](app/web/static/app.js#L1104), [app.js#L1153](app/web/static/app.js#L1153), [app.js#L1227](app/web/static/app.js#L1227), [app.js#L1519](app/web/static/app.js#L1519), [app.js#L2351](app/web/static/app.js#L2351) (the PoC banner label — `testTypes[variant].label`).

**Is `web_api` the only multi-channel value?** Yes. Every other value maps to a single-element list.

**Does anything assume `len(channels) <= 2`?** Yes, one place, and it is load-bearing:

- [app/web/static/app.js](app/web/static/app.js#L894-L900) — `applicablePocVariant` hard-codes `channels.length === 1` / `channels.length === 2`.
- The Python twin ([app/report_service.py](app/report_service.py#L273-L285)) uses exact set comparison, so it has no arithmetic assumption, but it has no 3-channel token either.
- [app/web/static/app.js](app/web/static/app.js#L1533) and [app.js#L1543](app/web/static/app.js#L1543) branch on `channels.length > 1` for labelling only — that already generalises to three.
- CSS: `.scope-grid` is 2 columns of **environment** panels ([app/web/static/app.css](app/web/static/app.css#L2)), and channels stack as labels inside a panel, so three channels lays out without a CSS change.

### 3. Invariants that constrain the change

**`reconcile_targets` — [app/report_service.py](app/report_service.py#L388-L463)**

The critical ordering fact: **`reconcile_targets` runs on the raw dict *before* `Report.model_validate`** — [app/main.py](app/main.py#L662) vs [app/main.py](app/main.py#L677). A payload carrying a new-shaped field reaches `reconcile_targets` first, and [app/report_service.py](app/report_service.py#L401-L402) will 422 with `invalid_scope` before Pydantic ever sees it.

How it decides survival:

1. Expands `test_type` to `channels` ([app/report_service.py](app/report_service.py#L399-L403)).
2. Builds `old = {(environment, channel, value): target_id}` from `prior.scope_targets` ([app/report_service.py](app/report_service.py#L404)).
3. Emits one target per `environment × channel × cleaned line`, reusing the prior ID when the triple matches, otherwise minting `tgt_<8 hex>` ([app/report_service.py](app/report_service.py#L437)). **A dropped channel is simply never iterated, so its targets do not appear in the new list.**
4. Filters `custom_locations` down to surviving `environment`/`channel` keys ([app/report_service.py](app/report_service.py#L445-L452)).
5. For `mode == "custom"` findings: appends the title if any `target_id` is missing from the new set ([app/report_service.py](app/report_service.py#L454-L457)).
6. For non-custom modes: appends the title if `_scope_reaches_a_location` was true against the prior targets and false against the new ones ([app/report_service.py](app/report_service.py#L461-L462)).

A non-empty return → [app/main.py](app/main.py#L666-L672) returns **422 `referenced_scope_removed`** with `f"Restore the removed scope target or give another affected location to: {names}."`. **Whole save rejected, no partial apply.** Test: [tests/test_app.py](tests/test_app.py#L607-L610).

**Good news for your change:** widening is the safe direction. Adding a channel only adds keys to the iteration; no target can be dropped, so `removed_references` stays empty. The 422 only bites when a tester *unchecks* a box.

**`ScopeTarget` identity — the doc claim**

[docs/plans/vuln-db-editor-poc-autofill.md](docs/plans/vuln-db-editor-poc-autofill.md#L107) claims:

> **`ScopeTarget` identity is the `(environment, channel, value)` triple.** Changing `test_type` destroys targets on dropped channels and remints IDs if they return, so **`scope.target_ids` do not survive a test-type round trip**.

**Confirmed, with one correction.** The triple is the *reuse key*, not the identity — the stored identity is `target_id` ([app/models.py](app/models.py#L96-L101)), and `Report.validate_references` enforces uniqueness on `target_id` alone ([app/models.py](app/models.py#L210-L212)). But the practical consequence the doc states is correct: `old.get((environment, channel, value), f"tgt_{uuid4}")` at [app/report_service.py](app/report_service.py#L437) keys reuse off the triple, and `old` is rebuilt from `prior.scope_targets` each call. So a channel dropped and re-added across two saves gets fresh IDs.

**The round trip is worse than the doc implies — it cannot complete.** Dropping a channel that any finding references is refused with 422 at step 5 above, so the tester never reaches the "add it back" step unless they first re-scope every affected finding. And the drop *also* strips `custom_locations` for that channel ([app/report_service.py](app/report_service.py#L445-L452), test at [tests/test_app.py](tests/test_app.py#L617-L641)) — those typed endpoints are deleted, not restored on re-add.

**`Report.validate_references` — [app/models.py](app/models.py#L208-L241)**

**It never mentions `test_type` or `channel`.** The only clause in the blast radius:

```python
if vulnerability.scope.mode == "custom" and not set(vulnerability.scope.target_ids) <= target_ids:
    raise ValueError("custom scope references a missing target")
```
— [app/models.py](app/models.py#L218-L219)

This fires only for `mode == "custom"`. It is a *second* gate behind `reconcile_targets`: if a caller writes `scope_targets` directly (bypassing `scope_text`), this is what catches a stranded custom finding — and it raises `ValidationError` on **load**, which demotes the draft to the manager's legacy/invalid list.

`setup_issues` and `setup_input_issues` ([app/report_service.py](app/report_service.py#L466-L490), [app/report_service.py](app/report_service.py#L103-L136)) do **not** read `test_type`. `setup_issues` requires at least one scope target per selected environment, regardless of channel.

### 4. Proof-of-concept variant resolution — **this is where the change breaks**

**The functions**

| | Python | JavaScript |
|---|---|---|
| channel set | [app/report_service.py](app/report_service.py#L247-L271) `affected_channels` | [app/web/static/app.js](app/web/static/app.js#L880-L892) `affectedChannels` |
| set → token | [app/report_service.py](app/report_service.py#L273-L285) `applicable_poc_variant` | [app/web/static/app.js](app/web/static/app.js#L894-L900) `applicablePocVariant` |
| install | [app/report_service.py](app/report_service.py#L359-L373) `apply_poc_variant` | [app/web/static/app.js](app/web/static/app.js#L935-L946) `applyPocVariant` |

Your prompt says "the `pocVariantFor`-style function around [app/web/static/app.js](app/web/static/app.js#L879-L900)". The actual names are `applicablePocVariant` at [app.js#L894](app/web/static/app.js#L894) and a separate `pocStepsFor` at [app.js#L947-L951](app/web/static/app.js#L947-L951). There is no `pocVariantFor`.

**What happens today for a set with no token**

Python — [app/report_service.py](app/report_service.py#L275-L285):

```python
channels = set(affected_channels(vulnerability, report))
if channels == {"web"}:   return "web"
if channels == {"api"}:   return "api"
if channels == {"mobile"}: return "mobile"
if channels == {"web", "api"}: return "web_api"
return None
```

`{web, mobile}` → `None`. `{web, api, mobile}` → `None`. `{api, mobile}` → `None`. Empty set → `None`.

Consequences of `None`, both sides:

- Server: [app/main.py](app/main.py#L722-L726) — `steps` becomes `None`, `apply_poc_variant` is never called. The library insert produces a finding with an **empty PoC** (just the provisioned `numbered_list` + image slots). No error, no warning.
- Browser: [app/web/static/app.js](app/web/static/app.js#L2340-L2345) — `pocStepsFor` returns `null`, so the banner at [app.js#L2351](app/web/static/app.js#L2351) never renders. The tester is never told steps exist.

**Silent degradation, not a crash.** That is arguably worse — the feature just stops appearing.

**What the library actually contains**

[app/library.py](app/library.py#L23) keys `proof_of_concept` by `TestType`, and [app/library.py](app/library.py#L32-L41) rejects an empty list per key.

In [resources/vuln_library.json](resources/vuln_library.json), 12 entries carry `proof_of_concept`. The keys present, counted:

- `api` — 12
- `web` — 12
- `web_api` — 11
- `mobile` — **0**

**There is not a single `mobile` PoC variant in the shipped library.** So `applicable_poc_variant` returning `"mobile"` already dead-ends today for every entry.

**The crux, stated bluntly**

Today the selector can only produce channel sets `{web}`, `{api}`, `{web,api}`, `{mobile}` — which is exactly the token set, by construction. Checkboxes break that correspondence. The new reachable sets are:

| New set | Token today | PoC outcome |
|---|---|---|
| `{web, mobile}` | none | **stranded — no steps, no banner** |
| `{api, mobile}` | none | **stranded** |
| `{web, api, mobile}` | none | **stranded** |
| `{mobile}` | `mobile` | reachable, but **zero library entries define it** |

So of the four newly-reachable combinations, **three have no PoC representation at all**, and the one that already existed has no data. Note this fires per *finding*, not per report: a finding scoped only to web endpoints inside a web+mobile engagement still resolves to `{web}` and works fine. The stranding hits findings whose locations genuinely span channels.

One prior decision is on record and was reversed: [docs/plans/vuln-db-editor-poc-autofill.md](docs/plans/vuln-db-editor-poc-autofill.md#L182) records "Re-keyed variants from `TestType` to `Channel`, and ruled that a finding resolving to more than one channel gets **no variant at all**" — the shipped code went back to `TestType` keys with a `web_api` special case.

### 5. Rules that exist in BOTH Python and JavaScript

Verified against source, not copied from the map. Every row must be changed in the same commit.

| Rule | Python | JavaScript |
|---|---|---|
| type → channel expansion | [report_service.py#L399](app/report_service.py#L399) `channels_by_type` | [app.js#L879](app/web/static/app.js#L879) `testTypes` |
| affected channels from a finding | [report_service.py#L247-L271](app/report_service.py#L247-L271) | [app.js#L880-L892](app/web/static/app.js#L880-L892) |
| channel set → PoC token | [report_service.py#L273-L285](app/report_service.py#L273-L285) | [app.js#L894-L900](app/web/static/app.js#L894-L900) |
| installing PoC steps | [report_service.py#L359-L373](app/report_service.py#L359-L373) | [app.js#L935-L946](app/web/static/app.js#L935-L946) |
| "would this scope change strand a finding" | [report_service.py#L370-L386](app/report_service.py#L370-L386) `_scope_reaches_a_location` | [app.js#L1092-L1101](app/web/static/app.js#L1092-L1101) `scopeReaches` |
| which targets survive a surface/environment change | [report_service.py#L404-L437](app/report_service.py#L404-L437) | [app.js#L1103-L1108](app/web/static/app.js#L1103-L1108) `findingsStrandedBy` |
| which targets survive a scope-text edit | same loop, by-value reuse | [app.js#L1123-L1128](app/web/static/app.js#L1123-L1128) `survivingAfterScopeText` |
| `custom_locations` filtered to live channels | [report_service.py#L445-L452](app/report_service.py#L445-L452) | *(no client twin — server-only; client renders boxes per channel at [app.js#L1519](app/web/static/app.js#L1519))* |
| mobile scope character allowlist | [report_service.py#L430-L435](app/report_service.py#L430-L435) | [app.js#L973](app/web/static/app.js#L973) `mobileScopeRule`, wired at [app.js#L1249](app/web/static/app.js#L1249) |
| default when absent | [models.py#L156](app/models.py#L156) `= "web"` | [app.js#L1027](app/web/static/app.js#L1027) `\|\|= "web"` |
| fallback when unknown | [report_service.py#L400](app/report_service.py#L400) `.get("test_type", "web")` | [app.js#L1519](app/web/static/app.js#L1519) `?? ["web"]` |

**Three default-to-`"web"` seeds**, not two — [models.py#L156](app/models.py#L156), [app.js#L1027](app/web/static/app.js#L1027), [app.js#L1519](app/web/static/app.js#L1519) — plus the payload fallback at [report_service.py#L400](app/report_service.py#L400) and the import fallback at [docx_import.py#L537](app/docx_import.py#L537). Five places encode "when in doubt, web".

**Map drift found here:** [docs/DATA_MAP.md](docs/DATA_MAP.md#L229-L243) §12 omits the `channels_by_type` ↔ `testTypes` pair entirely. [docs/plans/vuln-db-editor-poc-autofill.md](docs/plans/vuln-db-editor-poc-autofill.md#L118) has it; the maintained map does not.

### 6. What the drafts on disk actually contain

Two reports, three JSON files (one has a `.bak`):

| File | `schema_version` | `test_type` | legacy `tested_channels` |
|---|---|---|---|
| `data/apps/Northstar_Banking/2026-09_Report_0931592e4fdd/draft.json` | `"1.4"` | `"web"` (L24) | no |
| `…/2026-09_Report_0931592e4fdd/draft.bak.json` | `"1.4"` | `"web"` | no |
| `data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json` | `"1.4"` | `"web"` (L23) | no |

**Distribution: 100% `"web"`, 100% `schema_version "1.4"`, zero legacy keys.** No draft exercises `web_api` or `mobile`; the only coverage for those is in tests.

**Does `load_path` migration run on every load?**

**No — only on a missing key.** [app/workspace.py](app/workspace.py#L274) is `if "test_type" not in engagement:`. There is no schema-version check anywhere in the load path. `repaired` also gates the rewrite ([app/workspace.py](app/workspace.py#L284-L285)), so an already-migrated draft is read and returned without touching disk.

`import_report` does **not** go through `load_path` — it calls `Report.model_validate(payload)` directly at [app/workspace.py](app/workspace.py#L163). **A bundle or DOCX import gets no legacy repair at all.**

**What breaks if `test_type` becomes a list**

In order of when you would hit it:

1. **Nothing on disk breaks on read** *if* you add a `load_path` branch mirroring the existing one (`if "test_channels" not in engagement: derive from engagement.pop("test_type")`). All three files are `"web"` → `["web"]`, unambiguous.
2. **Every save 422s** until [app/report_service.py](app/report_service.py#L400-L403) is updated, because it reads the raw payload before validation and raises `ValueError("test_type is invalid")` on anything not in its four keys. This is the first thing that fails.
3. **`Vulnerability.poc_variant` still typed `TestType`** ([app/models.py](app/models.py#L141)). If you retire the tokens, stored values fail validation on load → draft demoted to legacy/invalid. If you keep the tokens for PoC keys only, this is fine — but then `TestType` means two different things.
4. **`LibraryEntry.proof_of_concept` keys** ([app/library.py](app/library.py#L23)) — same fork. Re-keying means rewriting all 12 entries in [resources/vuln_library.json](resources/vuln_library.json).
5. **Tests that set `test_type` as a string:** [tests/test_app.py](tests/test_app.py#L279-L289), [L331](tests/test_app.py#L331), [L472](tests/test_app.py#L472), [L491](tests/test_app.py#L491), [L621](tests/test_app.py#L621), [L634](tests/test_app.py#L634), [L647](tests/test_app.py#L647), [L702](tests/test_app.py#L702); [tests/test_browser.py](tests/test_browser.py#L446) drives `page.get_by_label("Test Surface").select_option("mobile")` — that Playwright call breaks the moment the `<select>` becomes checkboxes; [tests/test_browser.py](tests/test_browser.py#L925), [L954](tests/test_browser.py#L954); [tests/test_docx.py](tests/test_docx.py#L52), [L311](tests/test_docx.py#L311), [L364](tests/test_docx.py#L364), [L435](tests/test_docx.py#L435), [L520](tests/test_docx.py#L520); [tests/test_docx_import.py](tests/test_docx_import.py#L66).
6. **`draft.bak.json` is not migrated.** Only `draft.json` is read by `load_path`. A rollback by hand-renaming the backup would reintroduce the old shape.

### 7. The DOCX render path

**Does `docx_report.py` read `test_type`?**

**No. Not once.** Grepped the whole file. It reads `scope_targets` and `custom_locations` exclusively:

- [app/docx_report.py](app/docx_report.py#L202-L207) — `_target_values(report, environment, channel)` filters `report.scope_targets`
- [app/docx_report.py](app/docx_report.py#L372-L379) — `_populate_scope_tables` fills the two scope tables from `_target_values`
- [app/docx_report.py](app/docx_report.py#L232-L235) — the `prod-web` / `non-prod-web` / `prod-api` / `non-prod-api` metadata tokens
- [app/docx_report.py](app/docx_report.py#L1009) — per-finding locations, sorted by `(CHANNEL_ORDER.index(channel), order)`
- [app/docx_report.py](app/docx_report.py#L1013-L1015) — typed `custom_locations`, iterated in `CHANNEL_ORDER`

**The `test-type` token is a different field**

[app/docx_report.py](app/docx_report.py#L222):

```python
"test-type": REPORT_TYPE_LABELS.get(engagement.report_type or "", "N/A"),
```

**The DOCX token named `test-type` renders `engagement.report_type`, not `engagement.test_type`.** This confirms the claim at [docs/plans/import-docx-as-retest-draft.md](docs/plans/import-docx-as-retest-draft.md#L216). Nothing in the generated document changes shape if `test_type` becomes a list.

**`CHANNEL_ORDER`**

[app/docx_report.py](app/docx_report.py#L44-L45):

```python
# Targets number from zero within each channel, so channel rank has to come first when ordering them.
CHANNEL_ORDER = ["web", "api", "mobile"]
```

Already covers all three channels and is independent of `test_type`. It is a sort key over channels that are **already present** in the data — a mixed-channel report sorts correctly today with no change.

**The real DOCX gap**

**The template has only two scope tables: "URL(s) in Scope" (web) and "API Routes" (api)** — [app/docx_report.py](app/docx_report.py#L374-L379). There is **no mobile scope table**. Mobile targets are stored, validated, and rendered in per-finding "Affected locations" ([app/docx_report.py](app/docx_report.py#L1009)), but they **never appear in the report's scope section**.

That is a pre-existing hole, reachable today by selecting `mobile`. Your change makes it far more likely to be hit, because "web + mobile" will look like a fully supported combination in the UI while the generated document silently omits the mobile scope.

`docx_import.py` writes but never reads `test_type` ([app/docx_import.py](app/docx_import.py#L537)), and can only ever produce `web`/`api`/`web_api` because it only parses two tables ([app/docx_import.py](app/docx_import.py#L522)).

### 8. Schema version

**Current value: `"1.4"`.** It is a `Literal`, so any other value is a hard validation failure, not a migration path:

- [app/models.py](app/models.py#L197) — `schema_version: Literal["1.4"] = "1.4"`
- [app/tester_identity.py](app/tester_identity.py#L152) — `PREFS_SCHEMA = "1.4"`
- [app/tester_identity.py](app/tester_identity.py#L170) — prefs pin the same literal
- [app/library.py](app/library.py#L45) — `LibraryDocument.schema_version: str`, **unconstrained**; [resources/vuln_library.json](resources/vuln_library.json#L2) carries `"1.4"`

**Precedent for bumping**

**There is none, and I want to be precise about what I can and cannot establish.**

- I searched the entire workspace for `1.3`, `1.2`, and "bump". The only hits are unrelated: a heading in [docs/FORM_STATE_PLAN.md](docs/FORM_STATE_PLAN.md#L34), TLS version prose in the library, and CSS line-heights.
- **No code anywhere branches on `schema_version`.** Not in `load_path`, not in `import_report`, not in `Library.load_or_empty`. The value is validated and then ignored.
- The one migration the project has ever performed — `tested_channels` → `test_type` — was done **without a version bump**, keyed on key presence ([app/workspace.py](app/workspace.py#L274)). That is the only observable precedent, and it argues for *not* bumping.
- Git history: **not established in the source** — I have no terminal access in this mode, so I cannot confirm whether `"1.3"` ever existed in a prior commit. The current tree contains no trace of one.

**Practical consequence:** bumping to `"1.5"` would make every draft on disk fail `Report.model_validate` and land on the manager's legacy/invalid list, because `load_path` has no code that rewrites the version. A bump requires a companion line in `load_path` — which is the same mechanism you would need for the field migration anyway, making the bump redundant unless you want it as documentation.

### Invariants in play

1. **`reconcile_targets` runs on the raw dict before Pydantic.** Violating: every save 422s with `invalid_scope` regardless of what the model says.
2. **Save rejection is all-or-nothing.** Violating: a partially-applied scope change leaves `scope_targets` and `vulnerabilities[].scope` inconsistent, which `validate_references` then catches on the *next* load — demoting the draft.
3. **`target_id` reuse is keyed on `(environment, channel, value)`.** Violating: stable IDs churn, `scope.target_ids` go stale, findings strand.
4. **`custom_locations` is filtered to live channels on every save.** Violating: the document prints endpoints outside the tested surface.
5. **`applicable_poc_variant` returns `None` rather than guessing.** Violating (e.g. synthesising a variant for `{web,mobile}`): the tester gets steps that describe a channel the finding does not touch.
6. **`schema_version` is a `Literal` with no migration hook.** Violating: every existing draft becomes unloadable.

### Both-sides warning

Eleven rules in the table in §5 are implemented twice. The three that will bite hardest, because a one-sided fix produces *silently wrong UI* rather than an error:

- `channels_by_type` ([report_service.py#L399](app/report_service.py#L399)) / `testTypes` ([app.js#L879](app/web/static/app.js#L879)) — fix Python only and Setup renders the wrong textareas; fix JS only and the server deletes targets the tester just typed.
- `applicable_poc_variant` ([report_service.py#L273](app/report_service.py#L273)) / `applicablePocVariant` ([app.js#L894](app/web/static/app.js#L894)) — divergence means the banner offers steps the server would not install, or the server installs steps the banner never offered.
- `_scope_reaches_a_location` ([report_service.py#L370](app/report_service.py#L370)) / `scopeReaches` ([app.js#L1092](app/web/static/app.js#L1092)) — divergence means the client's confirm dialog stops predicting the server's 422, so testers hit a save rejection with no warning.

The drift guard is `tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues` ([docs/DATA_MAP.md](docs/DATA_MAP.md#L228)) — note it covers readiness, **not** channel expansion or PoC variant selection. There is no contract test for the rows you are about to change.

### Map drift

`docs/DATA_MAP.md` not yet updated — this is a read-only Round 1 report and I have not changed the shipped behaviour it describes. Two inaccuracies found, both worth correcting when the change lands:

1. **[docs/DATA_MAP.md](docs/DATA_MAP.md#L229-L243) §12 omits the `channels_by_type` ↔ `testTypes` pair**, which is one of the most consequential duplicated rules for this change. [docs/plans/vuln-db-editor-poc-autofill.md](docs/plans/vuln-db-editor-poc-autofill.md#L118) lists it; the maintained map does not.
2. **[docs/DATA_MAP.md](docs/DATA_MAP.md#L153)** says a `LibraryEntry` "may carry `proof_of_concept`, keyed by `TestType` (`web`, `api`, `web_api`, `mobile`)". Accurate as a type statement, but it reads as though all four are populated. **`resources/vuln_library.json` contains zero `mobile` variants** across all 12 entries that define `proof_of_concept`. Worth stating, since it means the `mobile` branch of `applicable_poc_variant` is already dead in practice.

One doc claim I checked and **confirmed correct**: [docs/plans/vuln-db-editor-poc-autofill.md](docs/plans/vuln-db-editor-poc-autofill.md#L107) on `ScopeTarget` identity — with the refinement in §3 that the triple is the *reuse key* while `target_id` is the stored identity, and that the round trip it describes cannot actually be completed because the drop half is refused with 422.

## Round 1 - Planner: proposal and open questions

> Verbatim from `change-planner`, given the oracle's Round 1 findings as established fact. Section headings demoted one level.

### Understanding

`engagement.test_type` is not really a "type" — it is a compressed representation of a channel set, and `web_api` is the only compound token, which is why `web+mobile` is unrepresentable. The change is to stop compressing: store the set. Everything downstream already works in channels (`ScopeTarget.channel`, `Scope.custom_locations`, `CHANNEL_ORDER`, `affected_channels`), so the expansion maps in three places exist *only* to undo the compression. Storing the set deletes them rather than growing them. The cost is a migration on two entry paths, and it makes two half-built things — mobile in the document, and PoC steps for mixed channel sets — reachable in normal use for the first time.

### 1. Blast radius

**Model**

| File / symbol | Change | Why | |
|---|---|---|---|
| [app/models.py](app/models.py#L156) `Engagement.test_type` | → `tested_channels: list[Channel]`, default `["web"]` | the field that changes shape | **mandatory** |
| [app/models.py](app/models.py#L13) `TestType` | rename symbol to `PocVariant` | the token set survives, but only as a library key; two meanings in one name is how they re-merge | **mandatory** |
| [app/models.py](app/models.py#L141-L142) `poc_variant`, `poc_variant_declined` | type renamed, **values unchanged** | keeps every stored `poc_variant` valid; no draft re-validation | mandatory (rename only) |
| [app/models.py](app/models.py#L162-L166) `Engagement` validators | add `mode="before"` normaliser: `tested_channels` → map `test_type` → map legacy `tested_channels` → default; dedupe; order by `CHANNEL_ORDER` | **the single migration hook that covers `load_path`, `import_report`, PUT, and library insert at once** | **mandatory** |
| [app/models.py](app/models.py#L197) `schema_version` | **no change** | see risk table row 14 | — |
| [app/library.py](app/library.py#L23) `proof_of_concept: dict[TestType, ...]` | type symbol rename only | `resources/vuln_library.json` is untouched — no re-keying, no rewrite of 12 entries | mandatory (rename only) |

**Server**

| File / symbol | Change | Why | |
|---|---|---|---|
| new helper in [app/models.py](app/models.py#L12) | `engagement_channels(mapping) -> list[Channel] \| None` | one function called by both the validator and the raw-payload reader, so the rule cannot drift | **mandatory** |
| [app/report_service.py](app/report_service.py#L399-L403) `reconcile_targets` | delete `channels_by_type`; read via the helper; **write the resolved list back into `payload["engagement"]["tested_channels"]`**; raise on empty; fall back to prior targets' channels, never to `"web"` | reads the raw dict before Pydantic — first thing that breaks, and the only place that can silently delete targets | **mandatory** |
| [app/report_service.py](app/report_service.py#L273-L285) `applicable_poc_variant` | none for correctness; changes only under PoC policy | exact-set match already returns `None` for the new sets | conditional |
| [app/report_service.py](app/report_service.py#L466-L490) `setup_issues` | add `"app type"` when `tested_channels` is empty | friendly gate instead of a Pydantic blob | recommended |
| [app/workspace.py](app/workspace.py#L269-L286) `load_path` | **delete** the `tested_channels` → `test_type` branch | superseded by the before-validator, which also covers the import path it misses | **mandatory** |
| [app/workspace.py](app/workspace.py#L163) `import_report` | no code change — inherits the validator | this is the gap the oracle found, closed for free | — |
| [app/docx_import.py](app/docx_import.py#L530-L537) | write the parsed channel set directly; delete the inverse collapse | stops a two-table import from lying | **mandatory** |
| [app/main.py](app/main.py#L644-L699) `save_report` | none | ordering and 409 handling unchanged | — |

**Client — [app/web/static/app.js](app/web/static/app.js)**

| Line | Change | |
|---|---|---|
| [#L879](app/web/static/app.js#L879) `testTypes` | **split, do not delete.** A `channelLabels` map (3 entries, module scope, replacing the setup-local duplicate at [#L880](app/web/static/app.js#L880)) **plus** a `pocVariantLabels` map that still contains `web_api` | **mandatory** |
| [#L2351](app/web/static/app.js#L2351) `testTypes[variant].label` | point at `pocVariantLabels` | **mandatory — deleting `web_api` from the map is a `TypeError` in the PoC banner** |
| [#L1027](app/web/static/app.js#L1027) seed | `tested_channels ||= ` channels present in `scope_targets`, else `["web"]` | **mandatory** |
| [#L1153-L1159](app/web/static/app.js#L1153-L1159) `renderCoverage` | `<select>` → three checkboxes; confirm-then-commit per box; refuse to uncheck the last | **mandatory** |
| [#L1103-L1108](app/web/static/app.js#L1103-L1108) `findingsStrandedBy` | second argument becomes a channel list | **mandatory** |
| [#L1185](app/web/static/app.js#L1185) environment toggle | pass `tested_channels` | **mandatory** |
| [#L1227](app/web/static/app.js#L1227) scope grid | iterate `tested_channels` | **mandatory** |
| [#L1519](app/web/static/app.js#L1519) findings endpoint boxes | `report.engagement.tested_channels ?? ["web"]` | **mandatory** |
| [#L1112-L1122](app/web/static/app.js#L1112-L1122) `confirmScopeLoss` | also count targets and `custom_locations` lines about to be deleted, not only stranded findings | **mandatory** (see risks 6 and 7) |
| [#L894-L900](app/web/static/app.js#L894-L900) `applicablePocVariant` | none for correctness | — |
| [#L973](app/web/static/app.js#L973) `mobileScopeRule` | none — already per-channel | — |

**DOCX**

| File | Change | |
|---|---|---|
| [app/docx_report.py](app/docx_report.py#L374-L379) `_populate_scope_tables` | mobile scope table — **blocked on question 1** | conditional |
| [app/docx_report.py](app/docx_report.py#L234-L237) `_metadata` | `prod-mobile` / `non-prod-mobile` tokens — same gate | conditional |
| the `.docx` template itself | a new table captioned for mobile; `_find_table` locates by caption, so **this is a document edit, not a code edit** | conditional |

**Tests**

| File | Change | |
|---|---|---|
| **new** `tests/test_app.py::test_channel_rules_match_between_python_and_javascript` | parity test for the three twinned rules being edited | **strongly recommended — there is none today** |
| [tests/test_app.py](tests/test_app.py#L275-L290) | rewrite migration test; add `{web,mobile}` and 3-channel cases; **add an `import_report` case** | **mandatory** |
| tests/test_app.py L331, L472, L491, L621, L634, L647, L702 | string → list | **mandatory** |
| [tests/test_browser.py](tests/test_browser.py#L446) | `select_option("mobile")` → checkbox clicks; also L925, L954 | **mandatory** |
| tests/test_docx.py L52, L311, L364, L435, L520; [tests/test_docx_import.py](tests/test_docx_import.py#L66) | string → list | **mandatory** |

**Docs**

| File | Change | |
|---|---|---|
| [docs/DATA_MAP.md](docs/DATA_MAP.md) §6, §7, §8 | field shape; "keyed by `PocVariant`"; **§8 must say channel normalisation moved to the model validator *because* `import_report` bypasses `load_path`** | **mandatory — maintenance contract** |
| [docs/plans/scope-app-type-checkboxes.md](docs/plans/scope-app-type-checkboxes.md) | append decisions | mandatory |
| [docs/FORM_DEPENDENCIES.md](docs/FORM_DEPENDENCIES.md) | check for `test_type` | optional |

### 2. Data risks

| # | Area | What could go wrong | Verdict | Mitigation |
|---|---|---|---|---|
| 1 | `saved_at` / stale write | New mutation path bypassing the concurrency token | **clear** | Checkbox toggle goes through the existing `scheduleSave` → PUT with `saved_at` in the body. No new header path, no new endpoint. |
| 2 | Lost update | Read-modify-write outside `Workspace._locked` | **clear** | No new `Workspace` method. `save_if_current` unchanged. |
| 3 | **Raw payload before Pydantic** | Client sends `tested_channels`; `reconcile_targets` still reads `test_type`; `.get("test_type","web")` silently narrows to web and **deletes every API and mobile target** | **RISK — the worst one** | Read through the shared helper; fall back to `sorted({t.channel for t in prior.scope_targets})`, never to `"web"`. A default that cannot drop a target turns silent deletion into a no-op. |
| 4 | Derived-state fight | `reconcile_targets` builds targets for web+api, then Pydantic applies the `["web"]` model default, and the *next* save drops the api targets | **RISK** | `reconcile_targets` writes the resolved list back into the payload before validation, same as it already does for `scope_targets`. |
| 5 | Import bypasses repair | `import_report` calls `model_validate` directly — no legacy repair today | **RISK, closed by design** | The migration lives in `Engagement`'s before-validator, not `load_path`, so import, load, PUT, and library insert all get it. Needs its own test. |
| 6 | **Unchecking deletes scope text** | Uncheck "API" on a report with 40 API targets and no findings: no 422, no warning, targets gone. On reload `scope_text` is rebuilt from `scope_targets`, so the typed lines are **unrecoverable** | **RISK — pre-existing, but this change makes it one click** | Extend `confirmScopeLoss` to count targets, not just stranded findings. |
| 7 | `custom_locations` stripped | [report_service.py#L445-L452](app/report_service.py#L445-L452) deletes typed endpoints for a dropped channel with no warning and no 422 | **RISK — pre-existing, amplified** | Count them in the same dialog. |
| 8 | 422 `referenced_scope_removed` | Unchecking an app type a finding references rejects the **whole save** | **RISK, by design** | Correct behaviour — keep it. The client dialog must fire first so the tester is never surprised by a rejected autosave. |
| 9 | Empty checkbox set | Zero channels wipes all targets, then Setup renders no textareas | **RISK** | `reconcile_targets` raises `ValueError("select at least one app type")` → 422 `invalid_scope` **before any target is dropped**; client refuses to uncheck the last box. |
| 10 | **Stranded PoC combinations** | `{web,mobile}`, `{api,mobile}`, `{web,api,mobile}` → `applicable_poc_variant` returns `None` → library insert produces an empty PoC, no error, no banner | **RISK** | Question 2. Today this is rare by construction; after the change it is the normal case for mixed engagements. |
| 11 | `mobile` is hollow | `resources/vuln_library.json` has **zero** mobile PoC variants | **RISK, pre-existing** | Out of scope to author them, but do not let the UI imply they exist. Folds into question 2. |
| 12 | PoC banner crash | Deleting `web_api` from the `testTypes` map breaks `testTypes[variant].label` at [app.js#L2351](app/web/static/app.js#L2351) | **RISK** | Keep a separate `pocVariantLabels` map containing `web_api`. |
| 13 | **Mobile never reaches the document** | `_populate_scope_tables` has tables only for web and api; `_metadata` has no mobile token. After this change, "web + mobile" looks fully supported in the UI and the document silently omits mobile scope | **RISK, pre-existing, badly amplified** | Question 1. |
| 14 | `schema_version` | Bumping to `"1.5"` makes every draft on disk fail validation and land in the manager's legacy list | **clear, because we do not bump** | No code branches on it; the project's only prior migration was key-presence based. A bump would need a companion rewrite line and buy nothing. |
| 15 | `draft.bak.json` | The migration rewrite consumes the single backup slot on first load; a bad save immediately after loses the pre-migration copy | **RISK (low)** | Deleting the `load_path` branch means no migration rewrite at all — normalisation happens in memory and reaches disk on the next ordinary save. This risk disappears with the recommended design. |
| 16 | Rule drift | Three twinned rules edited in two languages with **zero contract-test coverage** | **RISK** | Parity test first, in step 0. |
| 17 | Orphan references | A `target_id` outliving its target | **clear** | `target_id` reuse keys on `(environment, channel, value)`; adding a channel only adds keys. `validate_references` never mentions channels. |
| 18 | Navigation trap | A new required field blocking a page needed to fill it in | **clear** | Both gates redirect *to* Setup, which is where channels are set — no loop is constructible. A finding stranded by a channel change can never be persisted (the 422 blocks it), so `/edit` cannot be gated by one. |
| 19 | Request/response asymmetry | Client sends a field the server drops | **clear after step 1** | `tested_channels` round-trips. `scope_text` remains client-only, unchanged. |
| 20 | One-way migration | A draft saved by the new code loses `test_type`; reverting the code silently reads it as `"web"` | **RISK (low)** | Accept and record it. Any rollback plan is "restore from `draft.bak.json`". |

### 3. The shape decision

**Recommendation: (a), with two refinements — name the field `tested_channels`, and rename the `TestType` symbol to `PocVariant`.**

**Why (a).** The expansion maps at [report_service.py#L399](app/report_service.py#L399), [app.js#L879](app/web/static/app.js#L879), and [docx_import.py#L530-L537](app/docx_import.py#L530-L537) exist only to undo a compression that this change abandons. Storing the set **deletes a twinned rule** instead of growing one — the diff is larger but the standing complexity is smaller. Three channels give seven non-empty sets for free, and a fourth channel would cost nothing. Critically, the PoC key type stays exactly as it is: `resources/vuln_library.json` is not re-keyed, the 12 entries are not rewritten, and every stored `poc_variant` remains valid. The whole "changing `TestType` invalidates drafts and the library" hazard evaporates once the two meanings are separated.

**Why `tested_channels` and not `test_channels`.** My first instinct was to avoid the dead legacy key name. That instinct is wrong: the old `tested_channels` meant *exactly* a list of channels, which is precisely what we are restoring. Reusing the name makes it symmetric with `tested_environments`, and it turns the old lossy migration into a **lossless restoration** — an ancient never-opened draft or an old exported bundle carrying `tested_channels: ["web","mobile"]` now loads correctly instead of collapsing to `"mobile"`. The collision fear is handled by precedence in the validator: `tested_channels` wins, then `test_type`, then default. Both keys can never coexist, because the old `load_path` branch popped `tested_channels` when it wrote `test_type`.

**Rejecting (b) — widen the literal.** Smallest diff, worst outcome. Seven tokens for three channels, fifteen for four. The token set becomes a set encoded as an enum, which means the checkbox UI needs a set→token serialiser **in both languages** — a brand-new twinned rule, on top of keeping all three expansion maps. Worse, `poc_variant: TestType` would then accept `web_mobile`, and `LibraryEntry.proof_of_concept` would accept a `web_mobile` key that `applicable_poc_variant` can never return — a validation surface that admits values the code cannot produce. It is worse on every axis except diff size.

**Rejecting (c′) — delete the field, derive channels from `scope_targets`.** This is the tempting minimal answer and it nearly works. It fails on two counts. A brand-new report has zero targets, so the Setup page would have no textareas to type into — you would reintroduce the field as unsaved client state, lost on reload. And `reconcile_targets` needs the channel list to decide which `custom_locations` survive; deriving it from the submitted targets makes "I cleared the API box for now" indistinguishable from "we never tested API", silently deleting typed endpoints. The field earns its place: it is tester intent, not a summary of data.

### 4. PoC-variant policy

Today the selector can only produce the four token sets, so `None` is nearly unreachable. Checkboxes make `{web,mobile}`, `{api,mobile}` and `{web,api,mobile}` ordinary, and every one resolves to `None` = empty PoC, no message, no error. `{mobile}` is reachable today and already dead-ends, because the shipped library has **zero** mobile variants.

| Option | Verdict |
|---|---|
| **Leave silent** | Rejected. Zero work, but it converts a rare quiet failure into the common case for exactly the reports this feature exists to support. |
| **Explicit "no steps for this combination" note** | **Recommended minimum.** When `applicablePocVariant` returns `null` *and* the entry has any PoC variants, the Content page says so and names which variants exist. Nothing is written, no guessing, the tester can narrow the finding's scope if they want steps. Small, and it is the only thing standing between this change and a silent regression. |
| **Offer a picker** | Good, more work. When the resolved set has no exact match, list the variants the entry does have and let the tester install one. `poc_variant` stays a single `PocVariant`, so it records the choice with **no schema change**. |
| **Synthesise or fall back to a subset** | **Rejected.** Violates invariant 5 and re-reverses a decision already made and reversed once at [docs/plans/vuln-db-editor-poc-autofill.md](docs/plans/vuln-db-editor-poc-autofill.md#L182). Steps for a channel the finding does not touch are worse than no steps. |

The choice between the note and the picker is a product call → question 2.

### 5. Ordered implementation steps

Sequenced so each step is independently reviewable and green. **Ship steps 1–4 as one commit**: a half-applied state means an open browser tab silently narrows scope on its next autosave (risk 3), and this app is local with no rolling deploy to justify the skew.

**Step 0 — Parity test first.**
*Files:* `tests/test_app.py` (new test).
*Does:* Asserts the Python and JavaScript twins agree for channel expansion, `affected_channels`, and PoC-variant resolution, extracting the JS constants by parse or exposing them the way `test_browser.py` already does for readiness.
*Proves:* Nothing yet — it must pass before and after.
*Invariant:* Rule drift is caught by a test, not by a user. **This is the step that makes the rest safe; do not skip it because the feature is not written yet.**

**Step 1 — Model, validator, shared helper.**
*Files:* [app/models.py](app/models.py), [app/library.py](app/library.py#L23).
*Does:* `engagement_channels()` helper; `Engagement.tested_channels: list[Channel]`; `mode="before"` validator (precedence, dedupe, `CHANNEL_ORDER`); `TestType` → `PocVariant`.
*Test:* Load a `test_type` draft, a legacy `tested_channels` draft, and a bare draft; assert all three produce the right list. Assert a stored `poc_variant: "web_api"` still validates.
*Invariant:* Every entry path — load, import, PUT, library insert — normalises identically.

**Step 2 — Raw-payload boundary.**
*Files:* [app/report_service.py](app/report_service.py#L388-L463).
*Does:* `reconcile_targets` reads via the helper, writes the resolved list back into the payload, raises on empty, falls back to prior targets' channels.
*Test:* PUT with `tested_channels`, PUT with legacy `test_type`, PUT with neither on a report holding api targets (assert **no target is dropped**), PUT with `[]` (assert 422 `invalid_scope` and **no partial write**).
*Invariant:* Ordering (raw dict before Pydantic) and all-or-nothing rejection both hold. **After this step the server accepts both shapes, so no save can 422 for the rest of the work.**

**Step 3 — Remove the old migration; fix the importer.**
*Files:* [app/workspace.py](app/workspace.py#L269-L286), [app/docx_import.py](app/docx_import.py#L530-L537).
*Does:* Delete the `load_path` branch; make the DOCX importer write the parsed channel set.
*Test:* Rewrite [tests/test_app.py#L275-L290](tests/test_app.py#L275-L290); add a bundle-import case with `test_type`; assert a two-table DOCX import yields `["web","api"]`.
*Invariant:* Legacy repair reaches `import_report`, which `load_path` never did. Nothing rewrites a draft on load, so the single backup slot is untouched.

**Step 4 — Client.**
*Files:* [app/web/static/app.js](app/web/static/app.js) — the ten rows in the blast radius; `app/web/static/app.css` if the checkbox row needs it.
*Does:* Checkboxes; split the label maps; channel-list plumbing; extend `confirmScopeLoss` to count targets and custom locations; floor of one channel.
*Test:* [tests/test_browser.py#L446](tests/test_browser.py#L446) rewritten to click checkboxes; a new test that checking "mobile" on a web report adds a Mobile textarea **without** a confirm dialog; a new test that unchecking "api" with existing api targets **does** raise one and that cancelling leaves `scope_targets` untouched.
*Invariant:* Widening never warns; narrowing always warns before the server can reject it. The PoC banner still renders for a `web_api` finding.

**Step 5 — PoC policy.** Files depend on question 2.

**Step 6 — Mobile in the document.** Blocked on question 1.

**Step 7 — Docs.** [docs/DATA_MAP.md](docs/DATA_MAP.md) §6, §7, §8 per the maintenance contract, plus [docs/plans/scope-app-type-checkboxes.md](docs/plans/scope-app-type-checkboxes.md).

### 6. Open questions

**Question 1 — Should mobile scope appear in the generated report?**

*Background.* The generated document builds its scope section from two tables located by their captions in the `.docx` template: "URL(s) in Scope" and "API Routes" ([app/docx_report.py](app/docx_report.py#L374-L379)). There is no mobile table, and `_metadata` has `prod-web` and `prod-api` tokens but no mobile equivalent ([app/docx_report.py](app/docx_report.py#L234-L237)). Mobile scope targets are stored correctly and do show up in each finding's "Affected locations", but they never appear in the report's scope section. This hole exists today — you can select "Mobile" in the dropdown and hit it. It is rare only because "Mobile" means *mobile and nothing else*. After this change, "Web + Mobile" becomes an obvious thing to tick, the Setup page will show a Mobile box that accepts targets, and the document will silently omit them. Separately, the shipped library has zero mobile PoC variants, so mobile findings also get no steps.

*Options.*

- **(i) Add a mobile scope table.** Edit the `.docx` template to add a table captioned for mobile applications, then add the `_populate_scope_tables` call and the two metadata tokens. Mobile becomes a real channel. Cost: a template document edit outside the codebase, plus a new DOCX test. This is the only option where a web+mobile report generates a correct document.
- **(ii) Ship the checkboxes, warn loudly.** Add a readiness-panel warning when mobile targets exist: "Mobile scope will not appear in the generated report." Cheap, honest, but you are shipping a UI that offers something the output cannot carry.
- **(iii) Ship web and API checkboxes only, defer mobile.** Two boxes now, third when the template is ready. No new hole. But `{web,api}` is already expressible today, so this version of the feature delivers nothing new — it is refactoring dressed as a feature.

*Tradeoff.* (i) is the only one that makes the feature true, and the code side is small — the real cost is the template edit and whoever owns that document. (ii) ships today and moves a known gap from hidden to visible, which is a genuine improvement but leaves a tester able to produce a report missing scope they typed in. (iii) is safe and pointless.

*Recommendation: (i)*, and if the template edit cannot happen in this change, then **(ii) with the warning as a hard requirement of step 4, not a follow-up**. What I would not accept is shipping the third checkbox with no warning — that is the change turning a rare hole into a routine one.

**Question 2** — held until question 1 is answered (PoC policy: explicit note vs. variant picker).

### What the planner would not do

- **Would not keep `test_type` on the model "just in case".** Two fields meaning the same thing, with the client writing one and the server deriving the other, is the derived-state fight in its purest form. The before-validator maps the old key on the way in; nothing needs to store it.
- **Would not put the migration in `load_path`.** It is the documented home ([docs/DATA_MAP.md](docs/DATA_MAP.md) §8), and it is the wrong home: `import_report` does not go through it, which is why bundle and DOCX imports get no repair today. The model validator covers all four entry paths for less code. Update §8 to say so rather than preserve a convention that has a known hole in it.
- **Would not default to `"web"` at the raw-payload boundary.** It is the existing behaviour and it reads as harmless, but once the field shape changes it becomes "silently delete every API and mobile target". Defaulting to the channels already present in `prior.scope_targets` makes the ambiguous case a no-op instead of a deletion.
- **Would not bump `schema_version`.** It would need a companion rewrite line in `load_path` — the exact mechanism the validator already replaces — and without one, every draft on disk lands in the manager's legacy list. It would be documentation that breaks the thing it documents.
- **Would not let the checkboxes reach `0` selected.** `tested_environments` already permits this and gets away with it because `setup_issues` catches it downstream. Channels cannot get away with it: `reconcile_targets` runs first and deletes every target before any gate sees the report.

## Round 2 - Oracle: verdict on the proposal

> Verbatim from `data-oracle`, checking the planner's claims against source. Headings demoted one level.

### A. Risk rows that are wrong

**Rows where the planner is right and I doubted it**

**Row 4 — the planner is correct, and my doubt was misplaced.** `reconcile_targets` already mutates the payload dict in three places: it pops at [app/report_service.py](app/report_service.py#L392), writes at [app/report_service.py](app/report_service.py#L431):

```python
payload["scope_targets"] = targets
```

and rewrites each finding's `custom_locations` at [app/report_service.py](app/report_service.py#L448) and [app/report_service.py](app/report_service.py#L453). "Same as it already does for `scope_targets`" is an accurate description of an existing mechanism. State it from the existing precedent, not from scratch.

**But the mitigation as placed does not work.** [app/report_service.py](app/report_service.py#L390-L391) is the first thing in the function:

```python
if "scope_text" not in payload:
    return None
```

`scope_text` is seeded only inside `setup()` at [app/web/static/app.js](app/web/static/app.js#L1044-L1051). The findings and editor pages never call it, so their PUTs carry no `scope_text` and `reconcile_targets` returns before reaching any write-back, any empty-set raise, or any prior-channel fallback. Every mitigation the planner assigned to step 2 is dead on two of the three pages. The `save()` body is the whole report from any page ([app/web/static/app.js](app/web/static/app.js#L634)), so those PUTs do carry `engagement` and can still overwrite `tested_channels`.

**Rows that are wrong**

**Row 20 — wrong, and wrong pessimistically.** The claim is that rolling back "silently reads it as `web`". It does not. Rolling back restores [app/workspace.py](app/workspace.py#L274-L276), which fires on `"test_type" not in engagement` and reads `tested_channels` — the exact key the new code writes. `["web","mobile"]` collapses to `"mobile"`, `["web","api"]` to `"web_api"`, `["web"]` to `"web"`. That is a lossy collapse, not a reset. This is a genuine argument in favour of reusing the `tested_channels` name that the planner did not make: rollback degrades instead of resetting.

**Row 9 vs row 3 — they conflict, and the planner did not notice.** The two mitigations are "raise on empty" and "fall back to prior channels when the key is absent". Distinguishing them requires the helper to return `[]` for a present-but-empty key and `None` for an absent one. `engagement.get("tested_channels")` returns `[]`, which is falsy, so any `or`-chained precedence collapses the two cases and the raise becomes unreachable. The planner's signature `-> list[Channel] | None` permits the distinction but the precedence rule as written ("`tested_channels` → `test_type` → default") does not specify it.

There are two further holes on the same row:

- `Engagement.tested_channels: list[Channel]` with a default accepts `[]` at the model layer. Nothing in `Report.validate_references` ([app/models.py](app/models.py#L208-L241)) mentions channels. So `[]` enters through `Workspace.import_report` ([app/workspace.py](app/workspace.py#L163)) without ever passing `reconcile_targets`.
- The client floor ("refuse to uncheck the last") means the server raise is only ever hit by a non-browser caller. Fine as defence, but do not count it as the row-9 mitigation.

**Row 3 — right verdict, wrong owner.** The mitigation belongs to step 1, not step 2. The before-validator is what closes it, because it maps `test_type` on every path including the no-`scope_text` PUT. The residual case the validator cannot close is a payload carrying *neither* key: the model default is `["web"]` and the validator has no access to `prior.scope_targets`. So the planner's own rule — "would not default to `web` at the raw-payload boundary" — is violated by the model default it also proposes. Two places decide the same thing and they disagree. That is the derived-state fight of row 4, reintroduced by the fix for row 3.

**Row 6 — "unrecoverable" is too strong, and the amplification is understated.** Confirmed correct: `confirmScopeLoss` returns `true` immediately when nothing is stranded ([app/web/static/app.js](app/web/static/app.js#L1115-L1117)), so unchecking a channel with targets but no referencing findings produces no dialog. There is already a test that does exactly this and expects 200 — [tests/test_app.py](tests/test_app.py#L490-L492) flips `test_type` from `mobile` to `web` with a live mobile target.

The correction: `report.scope_text` stays in browser memory after the channel is dropped, because the grid loop at [app/web/static/app.js](app/web/static/app.js#L1232) merely stops rendering it. Re-ticking the box inside the same page session restores the text and the next save re-mints targets with **fresh `target_id`s** ([app/report_service.py](app/report_service.py#L437)). Loss is total only after a reload, when the seed at [app/web/static/app.js](app/web/static/app.js#L1048-L1049) rebuilds `scope_text` from `scope_targets` and `clearLocalDraft()` ([app/web/static/app.js](app/web/static/app.js#L636)) has already discarded the local copy. Say "unrecoverable after reload", and note the ID churn, which is the part that silently strands `scope.target_ids`.

**Row 5 — right verdict, inflated framing.** "Four entry paths" is not accurate. Library insert ([app/main.py](app/main.py#L711-L727)) and evidence upload ([app/main.py](app/main.py#L735-L753)) accept no engagement input at all; they load an already-validated `Report` through `report_or_404` and save the model. They are not entry paths, and counting them as coverage the validator buys is double-counting. See §B1 for the real list.

**Row 18 — clear, but not for the stated reason.** The sub-claim "a finding stranded by a channel change can never be persisted because the 422 blocks it" is false as written: the 422 comes from `reconcile_targets`, which early-returns without `scope_text`. What actually catches a stranded finding on a non-Setup save is [app/models.py](app/models.py#L218-L219), and only for `scope.mode == "custom"`. The other three modes are not checked. The verdict still stands — no non-Setup page mutates `scope_targets` — but the reasoning needs replacing, and it carries a requirement: **the checkbox row must render from a static three-channel list, not from `tested_channels`.** If it iterated `tested_channels`, an imported `[]` would render zero checkboxes on a page that also renders zero scope textareas, and Setup would be unfixable. Note that a zero-channel state is already double-blocked client-side by `missingScopePanels` at [app/web/static/app.js](app/web/static/app.js#L1738), which counts a panel with no textareas as missing.

**Rows confirmed as stated**

**Row 1 — clear, confirmed, with one omission.** The `<select>` handler calls `scheduleSave()` ([app/web/static/app.js](app/web/static/app.js#L1165)) and `save()` PUTs the whole report with `saved_at` in the body ([app/web/static/app.js](app/web/static/app.js#L634)). Neither header path can carry an engagement change: `insert_library` takes no body, `upload_evidence` takes only a file. The planner missed a **third** header-based path — `PATCH /reports/{id}/name` at [app/main.py](app/main.py#L601-L613) writes `report.engagement.app_name` and calls `save_if_current` with `expected_revision`. It cannot touch channels, but it re-dumps the whole engagement, so it silently persists the normalisation. Not a risk; the enumeration was just incomplete.

Rows 2, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17, 19: verified correct as stated. Row 12 in particular is real — [app/web/static/app.js](app/web/static/app.js#L2374) does `testTypes[variant].label` and is reached whenever `steps` is truthy at [app/web/static/app.js](app/web/static/app.js#L2368), which 11 of the 12 library entries make reachable for `web_api`. Row 15 is correct: deleting the `load_path` branch leaves `repaired` false for all three drafts on disk, so nothing rewrites and no backup slot is consumed on load.

### B. What the planner missed

**B1. Does a `mode="before"` validator cover every path?**

Yes — but the path list is wrong. The real set of places engagement data is constructed:

| Path | Location | Validated? |
|---|---|---|
| `load_path` | [app/workspace.py](app/workspace.py#L286) | yes |
| `import_report` | [app/workspace.py](app/workspace.py#L163) | yes |
| `repair_duplicate_fragment_ids` | [app/workspace.py](app/workspace.py#L238) | yes, then writes the **raw** draft at [app/workspace.py](app/workspace.py#L239) |
| `parse_import`, JSON branch | [app/main.py](app/main.py#L330) | yes, then returns the **raw** payload |
| `parse_import`, ZIP branch | [app/main.py](app/main.py#L352) | yes, then returns the **raw** payload |
| PUT `save_report` | [app/main.py](app/main.py#L676) | yes |
| `create_report` | [app/workspace.py](app/workspace.py#L116) — `Engagement(tester=…, report_date=…)` | yes, `before` runs on `__init__` |
| `duplicate` | [app/workspace.py](app/workspace.py#L203) — `model_copy(deep=True)` | **no**, but the source is already normalised |

No `model_construct` anywhere. `export_bundle` ([app/workspace.py](app/workspace.py#L182-L196)) returns the loaded model, so the bundle round-trip is clean. Library insert and evidence upload are not on this list because they never accept engagement input.

Two behaviours worth writing into the plan: `parse_import` validates and then discards the validated model, returning the raw dict for `import_report` to revalidate — normalisation reaches disk via the model, not the dict. And `repair_duplicate_fragment_ids` persists the raw draft, so a manager-triggered repair leaves `test_type` on disk untouched.

**B2. The existing `Engagement` validators**

**Wrong line range.** [app/models.py](app/models.py#L162-L164) are `report_date`, `classification`, `template_set`. The only `Engagement` validator is `validate_environments`, `mode="after"`, at [app/models.py](app/models.py#L166-L170). No interaction problem — `before` runs first on the raw mapping, `after` runs on the built model and touches only `tested_environments`.

One behavioural change nobody flagged: the old branch used `set(engagement.pop("tested_channels", []))`, which never raises — `set("web")` yields `{"w","e","b"}`, silently wrong but non-fatal. A before-validator that rejects a malformed value raises `ValidationError` on load, which demotes the draft to the manager's legacy/invalid list ([app/workspace.py](app/workspace.py#L140-L148)). Moving the migration into the model converts a silent mis-repair into a hard load failure.

Also: the planner's claim that `test_type` and `tested_channels` "can never coexist" holds only for drafts this app wrote. The pop at [app/workspace.py](app/workspace.py#L275) is inside the `if "test_type" not in engagement` branch, so a hand-edited or third-party import can carry both — and the proposed precedence makes a stale `tested_channels` beat a current `test_type`.

**B3. Templates, other JS, CSS**

- [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L11) holds `<div id="test-configuration" class="test-configuration">`, empty and JS-filled. No template edit needed.
- `page2_findings.html`, `page2_editor.html`, `manager.js`, `diagnostics.js`: zero references. Grepped across `app/web/**`.
- **Three stylesheets, not one.** The planner wrote "app.css if the checkbox row needs it". `.test-type-select` is styled in [app/web/static/overrides.css](app/web/static/overrides.css#L38), [app/web/static/overrides.css](app/web/static/overrides.css#L50-L51), [app/web/static/overrides.css](app/web/static/overrides.css#L347) and [app/web/static/taste.css](app/web/static/taste.css#L665), [app/web/static/taste.css](app/web/static/taste.css#L699), [app/web/static/taste.css](app/web/static/taste.css#L704) — including `flex-direction: column` and two fixed `select { width: … }` rules. `app.css` carries `.scope-grid` but not `.test-type-select`.
- **Accessible name.** [tests/test_browser.py](tests/test_browser.py#L446) uses `page.get_by_label("Test Surface")`, which resolves through the wrapping `<label class="test-type-select"><span>Test Surface</span><select>` at [app/web/static/app.js](app/web/static/app.js#L1157-L1158). Three checkboxes inside one `<label>` break that association; each needs its own `aria-label`. Not in the plan.

**B4. `library_editor.py`**

It does **not** import `TestType`. It iterates variants generically at [app/library_editor.py](app/library_editor.py#L57-L59) and [app/library_editor.py](app/library_editor.py#L88-L94). No change needed — the planner is right by omission.

But there is a **fifth copy of the token set** neither of us named: [app/web/templates/library_editor.html](app/web/templates/library_editor.html#L80) hard-codes `const variants = ["web", "api", "web_api", "mobile"]`, with matching textareas at [app/web/templates/library_editor.html](app/web/templates/library_editor.html#L66-L67). Harmless under rename-only. It would have been fatal under the rejected option (b).

**B5. `channelLabels` — the planner is wrong, and my Round 1 line number drifted**

There is no "setup-local duplicate at #L880". [app/web/static/app.js](app/web/static/app.js#L881) **is** `testTypes` itself, and #L880 is its comment. `channelLabels` is at [app/web/static/app.js](app/web/static/app.js#L961), inside `setup()`, consumed once at [app/web/static/app.js](app/web/static/app.js#L1234). My Round 1 said L956; L961 is correct.

Other copies of the channel list, which is more interesting: **three orderings that disagree.**

| Source | Order |
|---|---|
| [app/models.py](app/models.py#L12) `Channel` | `api, web, mobile` |
| [app/web/static/app.js](app/web/static/app.js#L961) `channelLabels`, and the seed loop at [app/web/static/app.js](app/web/static/app.js#L1047) | `api, web, mobile` |
| [app/docx_report.py](app/docx_report.py#L45) `CHANNEL_ORDER` | `web, api, mobile` |

"Order by `CHANNEL_ORDER`" needs to say which one. `CHANNEL_ORDER` lives in `docx_report.py`, which imports from `report_service.py`, which imports from `models.py`. Putting the canonical order in `models.py` inverts that direction; importing it into `models.py` from `docx_report.py` is a cycle.

**B6. Twinned rules with no client or server edit listed**

Walking Round 1 §5 against the planner's ten client rows:

**Missing: `survivingAfterScopeText` / `scopeTextStrandedFindings`** ([app/web/static/app.js](app/web/static/app.js#L1128-L1136), assigned to `strandedByScopeEdit` at [app/web/static/app.js](app/web/static/app.js#L1137)). This is the live save blocker at [app/web/static/app.js](app/web/static/app.js#L624-L628). It decides survival by looking up `report.scope_text[env][channel]` and treats `undefined` as "survives". After a channel is unchecked, `scope_text` for that channel is still defined and still populated — so the client judges its targets as surviving while the server drops them. `strandedByScopeEdit` under-reports after any channel change. This row has no entry in the planner's table and needs one.

**Missing: `mobileScopeRule` wiring.** The planner says "no change, already per-channel", which is right about the rule. But the wiring at [app/web/static/app.js](app/web/static/app.js#L1259) is `if (channel === "mobile")` inside the grid loop — it follows the channel list automatically, so this is correct, just worth recording as verified rather than assumed.

**Not missing, verified: `setup_issues` has no JS twin.** The editor's readiness panel twins only `requiresFragment` ([app/web/static/app.js](app/web/static/app.js#L95-L96) ↔ [app/docx_report.py](app/docx_report.py#L110-L111)). `setup_issues` is server-only because `/findings` and `/edit` both gate on it at [app/main.py](app/main.py#L629) and [app/main.py](app/main.py#L638). The new `"app type"` issue needs no JavaScript counterpart.

**B7. The parity-test mechanism is invented**

[tests/test_browser.py](tests/test_browser.py#L1077-L1133) does not extract, expose, or parse any JavaScript constant. It mutates a report in Python, saves it, calls `generation_issues(...)` in Python, navigates Playwright to `/edit`, and compares `#issue-count`'s `data-state` attribute plus the Generate button's enabled state. It is a behavioural comparison through the DOM.

[tests/test_app.py](tests/test_app.py#L16) imports `TestClient` and nothing else — no browser, no JS engine, no JS parser. A parity test "in `tests/test_app.py`" as described cannot be written without a new dependency.

A DOM-observable version is possible, but it is a different test in a different file: the scope-grid labels at [app/web/static/app.js](app/web/static/app.js#L1234) expose the channel list, the "Additional affected {CHANNEL} endpoints" labels at [app/web/static/app.js](app/web/static/app.js#L1533) expose it again per finding, and the PoC banner at [app/web/static/app.js](app/web/static/app.js#L2374) exposes `applicablePocVariant`. `affectedChannels` has no observable except through that banner. Step 0 must be rewritten to say this, and it belongs in `test_browser.py`.

**B8. The `_metadata` line numbers**

**Both of us were wrong.** The scope tokens are at [app/docx_report.py](app/docx_report.py#L235-L238) — `prod-web`, `non-prod-web`, `prod-api`, `non-prod-api`. Round 1 said #L232-L235; the planner said #L234-L237. `_metadata` itself begins at [app/docx_report.py](app/docx_report.py#L213). The two scope tables are located by caption at [app/docx_report.py](app/docx_report.py#L377) and [app/docx_report.py](app/docx_report.py#L380), inside `_populate_scope_tables` ([app/docx_report.py](app/docx_report.py#L375-L383)), called once from [app/docx_report.py](app/docx_report.py#L157).

### C. What happens to the drafts on disk

Three files, all `schema_version: "1.4"`, all `test_type: "web"`, zero legacy `tested_channels`, zero non-`null` `poc_variant`.

**`data/apps/Northstar_Banking/2026-09_Report_0931592e4fdd/draft.json`**

`test_type: "web"` at L24. Two `web` scope targets, `tgt_635d8485` (production) and `tgt_f5c03d52` (non_production). One finding, `v_852106ea`, with **`scope.mode == "custom"` and `target_ids: ["tgt_635d8485", "tgt_f5c03d52"]`** (L74-L81). `poc_variant: null`, `poc_variant_declined: []`.

- **First load:** before-validator sees no `tested_channels`, falls to `test_type: "web"` → `["web"]`. Loads clean. No disk write — the `load_path` branch is gone and no list fragment is empty, so `repaired` stays false.
- **First save:** [app/storage.py](app/storage.py) copies the current bytes to `draft.bak.json`, **overwriting the existing backup**, then writes the model dump with `tested_channels: ["web"]` and no `test_type`.
- **`draft.bak.json`:** currently a `test_type` copy. After the first save it becomes a *different* `test_type` copy (the pre-migration `draft.json`). After the **second** save it holds a `tested_channels` copy and the last pre-change bytes are gone. One save of headroom.
- **Stranding exposure:** this is the one draft where a channel change bites. Unchecking "Web" drops both targets, `removed_references` becomes `["Authorization bypass"]`, and the save is refused with 422 `referenced_scope_removed` ([app/main.py](app/main.py#L666-L672)). The client's `findingsStrandedBy` predicts it correctly. If the targets were ever removed by a path that skips `reconcile_targets`, [app/models.py](app/models.py#L218-L219) would reject the draft on load.

**`data/apps/Northstar_Banking/2026-09_Report_0931592e4fdd/draft.bak.json`**

`schema_version "1.4"`, `test_type: "web"`. **Never read by `load_path`.** `find_path` globs `*/*/draft.json` only ([app/workspace.py](app/workspace.py#L249)). It is not migrated, not validated, and not touched. A hand-rename to `draft.json` reintroduces `test_type` — which the before-validator then maps correctly, so hand-rollback works.

**`data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json`**

`test_type: "web"` at L23, `app_id: "unnamed"`, one production `web` target, one finding with `scope.mode == "custom"` and `target_ids: ["tgt_1acb9708"]`. `poc_variant: null`. No `draft.bak.json` yet — the first save creates it, so nothing is lost here.

Note the `app_id: "unnamed"` interaction: this draft's first save also triggers the folder migration (`X_unnamed` gate) if the engagement name resolves. That is orthogonal to channels but it means the first save after this change moves the directory as well as rewriting the field.

**Direct answers to the two sub-questions**

- **`poc_variant` values affected by the `TestType` → `PocVariant` rename:** none. All three files carry `poc_variant: null` and `poc_variant_declined: []`. The rename is symbol-only and the token values are unchanged, so nothing on disk revalidates differently.
- **`scope.mode == "custom"` with strandable `target_ids`:** both live drafts, on every finding. All targets are `channel: "web"`, so any future removal of the Web checkbox strands every finding in both reports. Widening is free; narrowing is 422 on both.

### Invariants in play

1. **`reconcile_targets` runs on the raw dict before Pydantic, and only when `scope_text` is present** ([app/report_service.py](app/report_service.py#L390-L391), [app/main.py](app/main.py#L662) vs [app/main.py](app/main.py#L676)). Violate by assuming it always runs and two of three pages skip every guard you put there.
2. **Save rejection is all-or-nothing.** Violate and `scope_targets` and `vulnerabilities[].scope` diverge, which [app/models.py](app/models.py#L218-L219) then catches on the *next* load, demoting the draft.
3. **`target_id` reuse is keyed on `(environment, channel, value)`** ([app/report_service.py](app/report_service.py#L437)). Violate by dropping and re-adding a channel and every ID churns.
4. **One rule, one owner.** The model default and the raw-payload fallback must agree on what "no channel information" means, or you have rebuilt the compression bug in a new place.
5. **`applicable_poc_variant` returns `None` rather than guessing** ([app/report_service.py](app/report_service.py#L273-L285)).

### Both-sides warning

Beyond the planner's list, two rules are implemented twice and have **no** edit listed on one side:

- `survivingAfterScopeText` / `scopeTextStrandedFindings` ([app/web/static/app.js](app/web/static/app.js#L1128-L1136)) ↔ the by-value reuse loop in `reconcile_targets` ([app/report_service.py](app/report_service.py#L404-L437)). Client-only edit needed; a one-sided fix means the save blocker stops predicting the server's 422.
- The channel ordering, which exists three times ([app/models.py](app/models.py#L12), [app/web/static/app.js](app/web/static/app.js#L961) and [app/web/static/app.js](app/web/static/app.js#L1047), [app/docx_report.py](app/docx_report.py#L45)) and disagrees across them.

There is **no** drift guard for any of these. [tests/test_browser.py](tests/test_browser.py#L1077) covers generation readiness only.

### Map drift corrected

The oracle edited [docs/DATA_MAP.md](docs/DATA_MAP.md) in this round:

1. **§12 overstated its own contract test.** It said `test_browser_readiness_verdict_matches_server_generation_issues` "is the contract test that catches drift", full stop. It covers generation readiness alone, and that sentence is what led the planner to propose a mechanism that does not exist. Rewritten to say what the test actually does and that the app-type rows have no guard.
2. **§12 was missing four twinned rules:** `channels_by_type` ↔ `testTypes`, `reconcile_targets` ↔ `findingsStrandedBy`, the by-value reuse loop ↔ `survivingAfterScopeText`, and the mobile character allowlist ↔ `mobileScopeRule`. Added.
3. **§7 read as though all four PoC variant keys are populated.** Added the real counts (12 web, 12 api, 11 web_api, 0 mobile) and the fact that the token set is hard-coded a third time in the library-editor template.
4. Bumped the "Last verified" line.

### Verdict

**Safe with the corrections listed — but steps 0 and 2 need rewriting before anyone starts, not adjusting during.** The shape decision is sound and I am not re-opening it; row 4's mechanism claim is correct and I was wrong to doubt it. The plan's two structural defects are that **every step-2 mitigation sits behind an early return that fires on two of three pages**, and that **step 0 describes a test mechanism that does not exist in this repo**. Fix those, make `[]` distinguishable from absent, reconcile the model default against the prior-channel fallback, add `survivingAfterScopeText` to the client table, and add the two extra stylesheets and the checkbox accessible names. Then it ships.

## Round 2 - Planner: revised plan

> Verbatim from `change-planner` after the oracle's verdict. Headings demoted one level. This section supersedes Round 1 - Planner where they disagree.

### What the planner got wrong in Round 1

1. **Put every safety guarantee in a function that does not run.** `reconcile_targets` opens with `if "scope_text" not in payload: return None` ([app/report_service.py](app/report_service.py#L390-L391)). Only `setup()` seeds `scope_text` ([app/web/static/app.js](app/web/static/app.js#L1044-L1051)). Findings and Editor PUT the whole report without it, so "raise on empty", "fall back to prior channels" and "write the resolved list back" were dead on two of three pages. This forced the redesign in §3, not a patch.
2. **Invented a test mechanism.** [tests/test_browser.py](tests/test_browser.py#L1097-L1133) does not extract or parse JavaScript; it mutates a report in Python, saves, navigates Playwright, and compares DOM attributes. [tests/test_app.py](tests/test_app.py#L16) has no browser and no JS engine. Step 0 was unbuildable.
3. **Rows 3 and 9 contradicted each other.** "Raise on `[]`" and "fall back when absent" need `[]` and absent to be different; `engagement.get("tested_channels")` returns a falsy `[]`, so any `or`-chain collapses them.
4. **The planner's own rule contradicted its own design.** "Would not default to `web` at the raw-payload boundary", then `tested_channels: list[Channel] = ["web"]` on the model — a `web` default at a different boundary, with no access to `prior.scope_targets`. Two owners, disagreeing.
5. **Row 20 was wrong pessimistically.** Rolling back the code restores [app/workspace.py](app/workspace.py#L274-L276), which reads `tested_channels` — the very key the new code writes. `["web","mobile"]` → `"mobile"`. Lossy collapse, not reset. That is an argument *for* reusing the name.
6. **Row 18's reasoning was false.** The 422 comes from the function that early-returns. What actually catches a stranded finding is [app/models.py](app/models.py#L218-L219), and only for `scope.mode == "custom"`.
7. **Row 5 was inflated.** Library insert and evidence upload accept no engagement input; counting them was double-counting.
8. **Line numbers.** `Engagement`'s only validator is at [app/models.py](app/models.py#L166-L170), not #L162-L164. `channelLabels` is at [app.js](app/web/static/app.js#L961); there is no duplicate at #L880 — #L881 *is* `testTypes`. `_metadata` scope tokens are at [app/docx_report.py](app/docx_report.py#L235-L238). The PoC banner label is [app.js](app/web/static/app.js#L2383).
9. **Named one stylesheet when there are three**, and omitted accessible names for the checkboxes entirely.
10. **Missed `survivingAfterScopeText`** — the live save blocker — which under-reports after any channel change.

Row 4 was the one the oracle doubted and the planner was right: `reconcile_targets` already mutates the payload at [app/report_service.py](app/report_service.py#L392), #L431, #L448 and #L453.

### Understanding

`engagement.test_type` is a compressed channel *set*, not a type, and `web_api` is the only compound token — which is why `web + mobile` is unrepresentable. The change stops compressing and stores the set as `engagement.tested_channels: list[Channel]`. Everything downstream already works in channels, so the three expansion maps exist only to undo the compression and get deleted rather than grown. The `TestType` token set survives under the name `PocVariant` as a library proof-of-concept key, so `resources/vuln_library.json` is not re-keyed and no stored value revalidates differently. The real work is not the field: it is deciding, once, which component answers "what channels does this report have" — because the function that held that answer runs on one page out of three.

### 1. Revised blast radius

**app/models.py**

| Symbol | Change | |
|---|---|---|
| [`Channel`](app/models.py#L12) | reorder to `Literal["web", "api", "mobile"]` | **mandatory** — §4 |
| new `CHANNELS` beside it | `("web", "api", "mobile")`, the one canonical order | **mandatory** — §4 |
| new `resolve_tested_channels(mapping) -> list[Channel]` | the single owner of the question | **mandatory** — §3 |
| [`TestType`](app/models.py#L13) | rename symbol to `PocVariant`; token values unchanged | **mandatory** |
| [`poc_variant`, `poc_variant_declined`](app/models.py#L141-L142) | type symbol renamed only | mandatory (rename only) |
| [`Engagement.test_type`](app/models.py#L156) | → `tested_channels: list[Channel] = Field(default_factory=lambda: ["web"], min_length=1)` | **mandatory** |
| [`Engagement.validate_environments`](app/models.py#L166-L170) | **no change** — `mode="after"`, touches only `tested_environments`; runs after the new `before` and cannot interact | — |
| new `Report` `model_validator(mode="before")` | calls the helper, writes `engagement["tested_channels"]`, pops `test_type` | **mandatory** — and note this is the **first `mode="before"` validator in the codebase** |
| [`Report.validate_references`](app/models.py#L208-L241) | **no change** | — |
| [`schema_version`](app/models.py#L197) | **no change** | — |

**app/report_service.py**

| Location | Change | |
|---|---|---|
| [import line](app/report_service.py#L9) | `TestType` → `PocVariant`; add `resolve_tested_channels` | **mandatory** |
| [`reconcile_targets` early return](app/report_service.py#L390-L391) | **unchanged — and nothing in this plan may depend on the function running** | invariant |
| [`reconcile_targets` channel block](app/report_service.py#L399-L403) | delete `channels_by_type`; call the helper on `payload`; **write the result into `payload["engagement"]["tested_channels"]`**; raise `ValueError("select at least one app type")` on `[]` | **mandatory** |
| [`applicable_poc_variant`](app/report_service.py#L273-L285) | return annotation rename only | mandatory (rename only) |
| [`apply_poc_variant`](app/report_service.py#L359) | parameter annotation rename only | mandatory (rename only) |
| [`setup_issues`](app/report_service.py#L466-L490) | **no change — reversed from Round 1.** `min_length=1` makes an empty list unrepresentable on a validated `Report`, so an `"app type"` issue would be unreachable code | — |

**app/workspace.py**

| Location | Change | |
|---|---|---|
| [`load_path` legacy branch](app/workspace.py#L274-L276) | **delete** | **mandatory** |
| [`import_report`](app/workspace.py#L163) | no code change; inherits the validator — the hole `load_path` never covered | — |
| [`repair_duplicate_fragment_ids`](app/workspace.py#L238-L239) | no change. **Note:** it validates, then persists the **raw** draft, so a manager repair leaves `test_type` on disk; the next real save migrates it | note only |
| [`create_report`](app/workspace.py#L116) | no change — `Engagement(tester=…, report_date=…)` picks up the field default | — |
| [`duplicate`](app/workspace.py#L203) | no change — `model_copy(deep=True)` skips validation, but the source is already normalised | — |
| [`find_path`](app/workspace.py#L249) | no change. `draft.bak.json` is never read; hand-rollback by rename works, because the before-validator maps `test_type` | note only |

**app/main.py**

| Location | Change | |
|---|---|---|
| [`save_report`](app/main.py#L662-L676) | no change — ordering (raw dict → `reconcile_targets` → `model_validate`) preserved | — |
| [`rename_report`](app/main.py#L601-L613) | no change. **Note:** it re-dumps the whole engagement under `save_if_current`, so a rename silently persists the channel normalisation | note only |
| [`parse_import` JSON](app/main.py#L330) / [ZIP](app/main.py#L352) | no change. **Note:** both validate then discard the model and return the **raw** payload for `import_report` to revalidate | note only |
| [library insert](app/main.py#L711-L727), [evidence upload](app/main.py#L735-L753) | no change — neither accepts engagement input | — |

**app/docx_import.py** — [#L523, #L537](app/docx_import.py#L523): write the parsed channel set ordered by `CHANNELS`; delete the inverse collapse; fall back to `["web"]` only when no targets parsed, mirroring the existing `environments or ["production"]`. **mandatory**

**app/docx_report.py**

| Location | Change | |
|---|---|---|
| [`CHANNEL_ORDER`](app/docx_report.py#L45) | delete; import `CHANNELS` from `app.models` (this file already imports from there, so no cycle) | **mandatory** — §4 |
| [#L1012, #L1017](app/docx_report.py#L1012) | use `CHANNELS` | **mandatory** |
| [`_metadata` scope tokens](app/docx_report.py#L235-L238) | `prod-mobile` / `non-prod-mobile` | **conditional — question 1** |
| [`_populate_scope_tables`](app/docx_report.py#L375-L383), called from [#L157](app/docx_report.py#L157) | third caption lookup | **conditional — question 1** |
| the `.docx` template | a mobile-captioned table; `_find_table` locates by caption, so this is a **document** edit | **conditional — question 1** |

**app/library.py** — [`proof_of_concept: dict[TestType, ...]`](app/library.py#L23) symbol rename only. `resources/vuln_library.json` untouched, 12 entries not rewritten.

**app/web/static/app.js**

| Line | Change | |
|---|---|---|
| [#L881](app/web/static/app.js#L881) `testTypes` | **split, do not delete.** New module-scope `CHANNELS` + `channelLabels`; keep a `pocVariantLabels` that still contains `web_api` | **mandatory** |
| [#L961](app/web/static/app.js#L961) setup-local `channelLabels` | delete; use the module-scope one. There is **no** duplicate at #L880 | **mandatory** |
| [#L2383](app/web/static/app.js#L2383) `testTypes[variant].label` | → `pocVariantLabels[variant].label` | **mandatory — removing `web_api` here is a `TypeError`** |
| [#L1032](app/web/static/app.js#L1032) seed | `tested_channels ||=` channels present in `scope_targets`, else `["web"]` — twin of the server helper's last two branches | **mandatory** |
| [#L1047](app/web/static/app.js#L1047) `scope_text` seed loop | iterate `CHANNELS` instead of the inline `["api","web","mobile"]` | **mandatory** — §4 |
| [#L1108-L1113](app/web/static/app.js#L1108-L1113) `findingsStrandedBy` | second argument becomes a channel list; drop `testTypes[testType].channels` | **mandatory** |
| [#L1128-L1133](app/web/static/app.js#L1128-L1133) `survivingAfterScopeText` | **also filter on `tested_channels.includes(target.channel)`.** Missed entirely in Round 1 — see risk 21 | **mandatory** |
| [#L1154-L1168](app/web/static/app.js#L1154-L1168) `renderCoverage` type group | `<select>` → three checkboxes rendered from the **static `CHANNELS` list, never from `tested_channels`**; confirm-then-commit per box; refuse to uncheck the last | **mandatory** |
| same | each checkbox gets its own `aria-label` (`"Test Web App"` / `"Test API"` / `"Test Mobile"`), because three inputs in one `<label>` have no association | **mandatory** |
| [#L1190](app/web/static/app.js#L1190) environment toggle | pass `report.engagement.tested_channels` | **mandatory** |
| [#L1232](app/web/static/app.js#L1232) scope grid | iterate `tested_channels` ordered by `CHANNELS` | **mandatory** |
| [#L1234](app/web/static/app.js#L1234) panel label | unchanged mechanism; this is the DOM observable step 0 asserts against | note |
| [#L1254](app/web/static/app.js#L1254) `mobileScopeRule` wiring | **verified no change** — `if (channel === "mobile")` follows the channel list automatically | — |
| [#L1524](app/web/static/app.js#L1524) findings endpoint boxes | `report.engagement.tested_channels`; **delete the `?? ["web"]`** — if a fallback must exist it derives from `scope_targets`, never `web` | **mandatory** |
| [#L883-L892](app/web/static/app.js#L883-L892) `affectedChannels` | no change | — |
| [#L897-L900](app/web/static/app.js#L897-L900) `applicablePocVariant` | no change for correctness | — |
| [#L1115-L1126](app/web/static/app.js#L1115-L1126) `confirmScopeLoss` | count targets and `custom_locations` lines about to be deleted, not only stranded findings — it returns `true` immediately when nothing is stranded ([#L1117](app/web/static/app.js#L1117)) | **mandatory** — risks 6 and 7 |
| [#L120](app/web/static/app.js#L120), [#L623](app/web/static/app.js#L623) | no change; note `strandedByScopeEdit` is only wired inside `setup()` and only consulted when `data-step === "setup"` | — |

**Accessible-name collision check.** [tests/test_browser.py](tests/test_browser.py#L432-L433) locates scope textareas with `get_by_role("textbox", name="Web", exact=True)`, whose name comes from the wrapping `<label>` at [#L1234](app/web/static/app.js#L1234). Checkbox `aria-label`s must not be bare `"Web"`/`"API"`/`"Mobile"`, or `get_by_label` becomes ambiguous. Prefixing with `Test ` keeps both locators unique.

**Stylesheets — three, not one**

| File | Selectors that assume a `<select>` |
|---|---|
| [app/web/static/overrides.css](app/web/static/overrides.css#L38) | `label, .test-type-select { … }` |
| [app/web/static/overrides.css](app/web/static/overrides.css#L49-L51) | `.test-configuration { display:flex; justify-content:flex-end }`, `.test-configuration .test-type-select { display:flex; align-items:center }`, **`.test-configuration .test-type-select select { width:155px }`** |
| [app/web/static/overrides.css](app/web/static/overrides.css#L347) | mobile breakpoint, **`select { width:128px }`** |
| [app/web/static/taste.css](app/web/static/taste.css#L665) | `label, .test-type-select { gap:6px; … }` |
| [app/web/static/taste.css](app/web/static/taste.css#L672), [#L676](app/web/static/taste.css#L676) | `.test-configuration { justify-content:flex-start }`, `.scope-heading .test-configuration { margin:0 }` |
| [app/web/static/taste.css](app/web/static/taste.css#L699-L705) | **`flex-direction: column`** plus **`select { width:170px }`** |
| [app/web/static/app.css](app/web/static/app.css#L2) | carries `.scope-grid` only — **no `.test-type-select` rule** |

Existing checkbox styling to reuse rather than reinvent: `.coverage-option` at [overrides.css#L54-L56](app/web/static/overrides.css#L54) and [taste.css#L722](app/web/static/taste.css#L722), already sized for `input[type="checkbox"]` inside `#setup`.

**Templates**

| File | Change |
|---|---|
| [app/web/templates/page1_setup.html](app/web/templates/page1_setup.html#L11) | **none** — `<div id="test-configuration" class="test-configuration">` is empty and JS-filled |
| `page2_findings.html`, `page2_editor.html`, `manager.js`, `diagnostics.js` | **none** — zero references |
| [app/web/templates/library_editor.html](app/web/templates/library_editor.html#L80) | **none.** It hard-codes `const variants = ["web","api","web_api","mobile"]` — a fifth copy of the token set. Harmless under rename-only; it would have been fatal under the rejected option (b), and that is now a recorded reason the rename-only choice was right |

**Tests**

| File | Change | |
|---|---|---|
| **new** `tests/test_browser.py::test_scope_grid_channels_match_server_tested_channels` | step 0, DOM-observable | **mandatory** |
| **new** `tests/test_browser.py::test_poc_offer_matches_server_applicable_poc_variant` | step 0, via `data-poc-offer` at [#L2381](app/web/static/app.js#L2381) | **mandatory** |
| [tests/test_app.py#L275-L290](tests/test_app.py#L275-L290) | rewrite: legacy `tested_channels` now restores losslessly; add `{web,mobile}`, three-channel, both-keys, and an **`import_report`** case | **mandatory** |
| [tests/test_app.py#L490-L493](tests/test_app.py#L490-L493) | see §6 step 2 — it currently asserts un-warned narrowing is a 200, incidentally | **mandatory** |
| tests/test_app.py L331, L472, L621, L634, L647, L702 | string → list | **mandatory** |
| [tests/test_browser.py#L446](tests/test_browser.py#L446) | `get_by_label("Test Surface").select_option("mobile")` → checkbox clicks | **mandatory** |
| tests/test_browser.py L925, L954 | string → list | **mandatory** |
| tests/test_docx.py L52, L311, L364, L435, L520; [tests/test_docx_import.py#L66](tests/test_docx_import.py#L66) | string → list | **mandatory** |

**Docs** — [docs/DATA_MAP.md](docs/DATA_MAP.md) §6 (field shape), §7 (`PocVariant`), §8 (normalisation moved from `load_path` to a `Report` before-validator, **because `import_report` bypasses `load_path`**), §12 (the twinned-rule table gains the `survivingAfterScopeText` channel filter and loses `channels_by_type` ↔ `testTypes`). Maintenance contract — same change, not a follow-up.

### 2. Revised data-risk table

| # | Area | What could go wrong | Verdict | Reasoning / mitigation |
|---|---|---|---|---|
| 1 | Stale write | A mutation path that skips `saved_at` | **clear** | Checkbox toggle → `scheduleSave()` ([#L1165](app/web/static/app.js#L1165) today) → `save()` PUTs the whole report with `saved_at` in the **body** ([#L634](app/web/static/app.js#L634)). Three header paths exist and none can carry a channel change: library insert (no body), evidence upload (file only), and **`PATCH /reports/{id}/name`** ([app/main.py](app/main.py#L601-L613)) which writes only `app_name` — though it re-dumps the whole engagement, silently persisting normalisation |
| 2 | Lost update | Read-modify-write outside `Workspace._locked` | **clear** | No new `Workspace` method; `save_if_current` unchanged |
| 3 | Raw payload before Pydantic | Client sends `tested_channels`; the raw reader still reads `test_type` and `.get("test_type","web")` narrows to web | **RISK — owned by step 1, not step 2** | The `Report` before-validator maps `test_type` on **every** path, including the no-`scope_text` PUT. `reconcile_targets` calls the same helper. The residual — a payload with **neither** key — is resolved by deriving from the mapping's own `scope_targets`, not by a `web` default. See §3 |
| 4 | Derived-state fight | `reconcile_targets` builds web+api targets, then the model default applies `["web"]`, and the next save drops api | **RISK — closed by write-back** | `reconcile_targets` already mutates the payload: pops at [#L392](app/report_service.py#L392), writes `payload["scope_targets"]` at [#L431](app/report_service.py#L431), rewrites `custom_locations` at [#L448](app/report_service.py#L448) and [#L453](app/report_service.py#L453). **It is load-bearing, not belt-and-braces:** `reconcile_targets` replaces `scope_targets`, so a later derive-from-targets would see the *new* list and could resolve differently |
| 5 | Import bypasses repair | `import_report` calls `model_validate` directly and gets no legacy repair today | **RISK, closed by design** | The real construction sites are `load_path` ([#L286](app/workspace.py#L286)), `import_report` ([#L163](app/workspace.py#L163)), `repair_duplicate_fragment_ids` ([#L238](app/workspace.py#L238)), `parse_import` ×2 ([#L330](app/main.py#L330), [#L352](app/main.py#L352)), PUT ([#L676](app/main.py#L676)), `create_report` ([#L116](app/workspace.py#L116)), `duplicate` ([#L203](app/workspace.py#L203)). No `model_construct`. Library insert and evidence upload are **not** entry paths |
| 6 | Unchecking deletes scope text | Uncheck "API" with 40 API targets and no referencing findings: no dialog, no 422, targets gone | **RISK — pre-existing, now one click** | `confirmScopeLoss` returns `true` immediately when nothing is stranded ([#L1117](app/web/static/app.js#L1117)). `report.scope_text` **survives in browser memory** — [#L347](app/web/static/app.js#L347) excludes it from canonical reconciliation and the grid loop merely stops rendering it. Re-ticking in the same session restores the text; the next save **re-mints fresh `target_id`s** ([#L437](app/report_service.py#L437)). Loss is total only **after a reload**, when the seed at [#L1048-L1049](app/web/static/app.js#L1048-L1049) rebuilds from `scope_targets` and `clearLocalDraft()` ([#L636](app/web/static/app.js#L636)) has discarded the local copy. **The ID churn is the quiet half.** Mitigation: `confirmScopeLoss` counts targets and custom locations |
| 7 | `custom_locations` stripped | [#L445-L452](app/report_service.py#L445-L452) deletes typed endpoints for a dropped channel, no warning, no 422 | **RISK — pre-existing, amplified** | Counted in the same dialog |
| 8 | 422 `referenced_scope_removed` | Unchecking a channel a finding references rejects the **whole** save | **RISK, by design** | Correct. The client dialog must fire first so an autosave is never surprised |
| 9 | Empty channel set | Zero channels wipes targets and renders no textareas | **RISK — now three gates, in the right order** | `min_length=1` on the field is the **floor** and covers `import_report`, `duplicate`, `load_path` and non-Setup PUTs. `reconcile_targets` keeps a friendly `ValueError` → 422 `invalid_scope` on the one path it runs. The client floor is UX, **not** the mitigation. `[]` vs absent is distinguished by testing `"tested_channels" in engagement`, never truthiness — §3 |
| 10 | Stranded PoC combinations | `{web,mobile}`, `{api,mobile}`, `{web,api,mobile}` → `None` → empty PoC, no error, no banner | **RISK** | Question 2 |
| 11 | `mobile` is hollow | `resources/vuln_library.json` has **zero** mobile variants (12 web, 12 api, 11 web_api, 0 mobile) | **RISK, pre-existing** | Folds into question 2 |
| 12 | PoC banner crash | Deleting `web_api` breaks `testTypes[variant].label` at [#L2383](app/web/static/app.js#L2383), reachable whenever `steps` is truthy at [#L2377](app/web/static/app.js#L2377) — 11 of 12 entries | **RISK** | Keep `pocVariantLabels` with `web_api` |
| 13 | Mobile never reaches the document | Two scope tables only ([#L377](app/docx_report.py#L377), [#L380](app/docx_report.py#L380)); no mobile `_metadata` token ([#L235-L238](app/docx_report.py#L235-L238)) | **RISK, pre-existing, badly amplified** | Question 1 |
| 14 | `schema_version` | Bumping to `"1.5"` makes every draft on disk fail validation | **clear — we do not bump** | Nothing branches on it; the only prior migration was key-presence based |
| 15 | Backup exhaustion | Migration rewrite consumes the single `draft.bak.json` on load | **clear, and improved** | Deleting the `load_path` branch leaves `repaired` false for all three drafts, so **load writes nothing**. Normalisation reaches disk on the next ordinary save |
| 16 | Rule drift | Twinned rules edited in two languages with zero contract coverage | **RISK** | Step 0 — rebuilt as a DOM comparison, §6 |
| 17 | Orphan references | A `target_id` outliving its target | **clear** | Reuse keys on `(environment, channel, value)`; widening only adds keys. `validate_references` never mentions channels |
| 18 | Navigation trap | A new required field blocking the page that sets it | **clear — reasoning replaced** | The correct reason: no non-Setup page mutates `scope_targets`, and the only cross-object guard that runs on a non-Setup save is [app/models.py](app/models.py#L218-L219), which covers `mode == "custom"` **only**. Hard requirement this carries: **the checkbox row renders from the static `CHANNELS` list.** If it iterated `tested_channels`, an imported `[]` would render zero checkboxes on a page already rendering zero scope textareas, and Setup would be unfixable. `missingScopePanels` ([#L1738](app/web/static/app.js#L1738)) already blocks zero-channel client-side |
| 19 | Request/response asymmetry | Client sends a field the server drops | **clear** | `tested_channels` round-trips. `scope_text` stays client-only and is explicitly excluded from reconciliation at [#L347](app/web/static/app.js#L347). A list of plain strings has no `stableItemKey`, so [#L379-L381](app/web/static/app.js#L379-L381) adopts the server's normalised order wholesale — the same mechanism `tested_environments` already relies on |
| 20 | One-way migration | A draft saved by new code loses `test_type`; rollback misreads it | **RISK (low) — better than Round 1 said** | Rollback restores [app/workspace.py](app/workspace.py#L274-L276), which fires on `"test_type" not in engagement` and reads `tested_channels` — the exact key we write. `["web","mobile"]` → `"mobile"`, `["web","api"]` → `"web_api"`, `["web"]` → `"web"`. **Lossy collapse, not reset.** The strongest argument for reusing the name |
| **21** | **`strandedByScopeEdit` under-reports** | `survivingAfterScopeText` ([#L1128-L1133](app/web/static/app.js#L1128-L1133)) decides survival from `report.scope_text[env][channel]` and treats `undefined` as "survives". After a channel is unchecked, that text is **still defined and still populated**, so the client judges dropped targets as surviving while the server deletes them. This is the **live save blocker** at [#L623-L627](app/web/static/app.js#L623-L627) | **RISK — missed entirely in Round 1** | Add a `tested_channels.includes(target.channel)` filter. Consequence to accept: after unchecking a channel that strands a finding, `save()` blocks with "Give X another affected location" until the finding is re-scoped — identical to today's environment-uncheck behaviour |
| **22** | **`reconcile_targets` early return** | Guarantees placed there fire on Setup only; Findings and Editor PUTs carry `engagement` and can overwrite `tested_channels` | **RISK — the structural defect** | §3. Nothing may depend on `reconcile_targets` running. Every guarantee it gives is also enforced in the model |
| **23** | **`[]` via `import_report`** | `list[Channel]` with a default accepts `[]`; `validate_references` never mentions channels; `import_report` skips `reconcile_targets` | **RISK — closed by `min_length=1`** | The field-level floor is the only gate on this path. Consequence: an imported bundle with `[]` is refused with 422 rather than persisted |
| **24** | **Before-validator turns a silent mis-repair into a load failure** | The old branch used `set(engagement.pop("tested_channels", []))` — `set("web")` yields `{"w","e","b"}`, silently wrong but **never raises**. A validated field raises `ValidationError`, which demotes the draft to the manager's legacy/invalid list ([app/workspace.py](app/workspace.py#L140-L148)) where the only offered repair is for duplicate fragment IDs | **RISK — new rejection surface, accepted and bounded** | Bounded by fact: **zero drafts on disk carry the key**, so exposure is hand-edited files and third-party bundles only. Design rule: **the before-validator must not raise on its own.** It coerces a bare string to a one-element list (the one malformed shape the old code actually produced) and otherwise passes values through to the `Channel` `Literal`, which would have rejected them anyway |
| **25** | **`test_type` and `tested_channels` coexisting** | The Round 1 claim that they "can never coexist" holds only for drafts *this app wrote* — the pop at [app/workspace.py](app/workspace.py#L275) sits inside the `if "test_type" not in engagement` branch, so a hand-edited or third-party file can carry both, and simple precedence makes a **stale `tested_channels` beat a current `test_type`** | **RISK — resolved by union** | When **both** keys are present, take the **union**. The only resolution that cannot drop a scope target, and it is visible: an extra ticked checkbox and an extra empty scope panel, which the tester can untick. Widening is provably free — `reconcile_targets` produces no targets for a channel with no `scope_text`, the `custom_locations` filter keeps *more*, and `setup_issues` gates per environment, not per channel |
| **26** | **Three disagreeing channel orderings** | [`Channel`](app/models.py#L12) is `api, web, mobile`; [`channelLabels`](app/web/static/app.js#L961) and the seed loop at [#L1047](app/web/static/app.js#L1047) are `api, web, mobile`; [`CHANNEL_ORDER`](app/docx_report.py#L45) is `web, api, mobile`. "Order by `CHANNEL_ORDER`" was ambiguous | **RISK — resolved in §4** | One tuple in `models.py`, imported by `docx_report.py`, mirrored once in `app.js` |

### 3. Where the channel decision lives — resolved

**The owner: one function, `resolve_tested_channels(report_mapping) -> list[Channel]` in [app/models.py](app/models.py).** It takes the **whole raw report mapping**, not just the engagement, because branch 4 needs `scope_targets` and `Engagement` cannot see them. Precedence, testing key **presence**, never truthiness:

1. **Both `tested_channels` and `test_type` present** → union, ordered by `CHANNELS`. Only reachable in a hand-edited or third-party file; chosen because it is the only rule that cannot drop a target (risk 25).
2. **`tested_channels` present** → use it verbatim, after deduping and ordering. A bare string is coerced to a one-element list. **This is the only branch that can return `[]`.**
3. **`test_type` present** → map through the four-token table (`web_api` → `["web","api"]`). An unrecognised token is passed through unchanged so the `Channel` `Literal` rejects it — the validator never raises on its own (risk 24).
4. **Neither** → the channels present on the mapping's own `scope_targets`, ordered by `CHANNELS`.
5. **Neither, and no targets** → `["web"]`.

**Stated invariant: `resolve_tested_channels` returns `[]` if and only if the caller explicitly sent an empty list.** That is the `[]`-vs-absent distinction, and it is what makes "raise on empty" and "fall back when absent" stop contradicting each other.

**What every other component does**

| Component | Role |
|---|---|
| **`Report` `model_validator(mode="before")`** | The **only** caller that runs on every path. Calls the helper, writes `engagement["tested_channels"]`, pops `test_type`. Runs on `load_path`, `import_report`, `repair_duplicate_fragment_ids`, both `parse_import` branches, and the PUT. Guards `isinstance(data, dict)` and returns unchanged otherwise |
| **`Engagement.tested_channels` field default `["web"]`** | Answers a **different question**: "what does a brand-new engagement test?" Reachable only from direct construction — `Workspace.create_report` at [#L116](app/workspace.py#L116) — because a mapping-based path always has the key written by the `Report` validator first. The two never both fire, so this is not a second owner |
| **`Engagement.tested_channels` `min_length=1`** | The **floor**. The only gate that catches `[]` on `import_report`, `duplicate`, `load_path` and non-Setup PUTs. This is what makes the Round 1 `setup_issues` addition unreachable and therefore deleted |
| **`reconcile_targets`** | Calls the **same helper** on its raw payload, raises the friendly `ValueError` on `[]`, and **writes the result back** into `payload["engagement"]["tested_channels"]`. The write-back is load-bearing because the function replaces `scope_targets` — without it, branch 4 would later see the *new* target list and could resolve differently. It provides **no unique guarantee** |
| **`Engagement.validate_environments` (`mode="after"`)** | Untouched. `before` runs on the raw mapping, `after` on the built model, and it reads only `tested_environments` |
| **The client seed at [#L1032](app/web/static/app.js#L1032)** | Twin of branches 4 and 5 only. It never maps `test_type` — the server guarantees the key is present on anything it returns |
| **The checkbox row** | Renders from the static `CHANNELS` list and reads `tested_channels` only for checked state (risk 18) |

**Why this fixes the early return.** The fix is not to move code out of `reconcile_targets`. It is to **stop the correctness of the feature depending on it at all**. Findings and Editor PUTs skip it entirely, so the model must give the same answer unaided — and it does, because both callers invoke one function on one mapping. `reconcile_targets` keeps its own raise purely so a Setup PUT gets `invalid_scope` with a readable message *before* a single target is touched.

**"Default to web" sites after the change.** Five before ([models.py#L156](app/models.py#L156), [app.js#L1032](app/web/static/app.js#L1032), [app.js#L1524](app/web/static/app.js#L1524), [report_service.py#L400](app/report_service.py#L400), [docx_import.py#L537](app/docx_import.py#L537)); three after, all saying the same thing — *a report with no channel information anywhere starts as web*: the field default, helper branch 5, and its JS twin. The `?? ["web"]` and the `.get("test_type","web")` are deleted rather than translated.

### 4. Where the canonical channel order lives

The import direction is `models.py` ← `report_service.py` ← `docx_report.py` ([app/docx_report.py](app/docx_report.py#L40) imports from `.report_service`, which imports from `app.models`). Importing `CHANNEL_ORDER` into `models.py` would be a cycle, so the canonical order must live **at or below `models.py`**.

**Decision: `app/models.py`, next to `Channel`.**

- Add `CHANNELS: tuple[Channel, ...] = ("web", "api", "mobile")`.
- **Reorder the `Channel` `Literal` itself** to `"web", "api", "mobile"` so the two cannot silently disagree. Verified safe: `get_args` appears nowhere in `app/`, `Literal` member order has no validation semantics, and nothing in the repo consumes the generated JSON Schema.
- [app/docx_report.py](app/docx_report.py#L45): delete `CHANNEL_ORDER`, import `CHANNELS`, use it at [#L1012](app/docx_report.py#L1012) and [#L1017](app/docx_report.py#L1017).
- [app/web/static/app.js](app/web/static/app.js): one module-scope `const CHANNELS = ["web", "api", "mobile"]`, with `channelLabels` re-keyed in that order and the inline `["api","web","mobile"]` at [#L1047](app/web/static/app.js#L1047) replaced by it.

**Why `web, api, mobile`:** it is the ordering with a stated reason in a comment ([app/docx_report.py](app/docx_report.py#L44)), it drives the generated document, it matches the template's table order (URL(s) in Scope, then API Routes), and it matches the rendered scope-grid order today since `testTypes.web_api.channels` is already `["web","api"]`. The `Channel` `Literal` order has no consumer at all, so it is the one that yields.

### 5. Open questions

See the **Answers** section below for what was decided.

**Question 1 — Should mobile scope appear in the generated report?**

*Background.* The document's scope section is built from two tables located by caption in the `.docx` template: "URL(s) in Scope" and "API Routes", at [app/docx_report.py](app/docx_report.py#L377) and [#L380](app/docx_report.py#L380), inside `_populate_scope_tables` ([#L375-L383](app/docx_report.py#L375-L383)) called once from [#L157](app/docx_report.py#L157). There is no mobile table, and `_metadata` has `prod-web`, `non-prod-web`, `prod-api`, `non-prod-api` but no mobile equivalent ([#L235-L238](app/docx_report.py#L235-L238)). Mobile targets *are* stored, validated, and printed in each finding's "Affected locations" ([#L1012](app/docx_report.py#L1012)) — they simply never appear in the report's scope section. The hole exists today and is reachable by picking "Mobile"; it is rare only because "Mobile" currently means *mobile and nothing else*. After this change, "Web + Mobile" becomes an obvious thing to tick and the document will silently omit those targets. Separately, the shipped library has **zero** mobile PoC variants.

*Options.* **(i)** Add a mobile scope table — template document edit plus the `_populate_scope_tables` lookup and two `_metadata` tokens; the only option where a web+mobile report generates a correct document. **(ii)** Ship all three checkboxes with a loud readiness warning when mobile targets exist. **(iii)** Ship web and API checkboxes only; defer mobile — no new hole, but `{web, api}` is already expressible as `web_api` today, so it delivers nothing new.

*Recommendation: (i).* If the template edit cannot happen in this change, then **(ii) with the warning as a hard requirement of step 4, not a follow-up**. Shipping the third checkbox with no warning turns a rare hole into a routine one.

**Question 2 — What should happen when a finding's channels match no proof-of-concept variant?**

*Background.* `applicable_poc_variant` ([app/report_service.py](app/report_service.py#L273-L285)) and its twin `applicablePocVariant` ([app.js#L897-L900](app/web/static/app.js#L897-L900)) match the finding's channel set **exactly** against four tokens, returning `None` for anything else. Today the dropdown can only produce `{web}`, `{api}`, `{web,api}`, `{mobile}` — exactly the token set — so `None` is nearly unreachable. Checkboxes make `{web,mobile}`, `{api,mobile}` and `{web,api,mobile}` ordinary. `None` means: the server's library insert produces a finding with an **empty** proof of concept and no error ([app/main.py](app/main.py#L722-L726)), and the browser's offer banner never renders ([app.js#L2377](app/web/static/app.js#L2377)). This fires **per finding**, not per report. The shipped library has 12 `web`, 12 `api`, 11 `web_api` and **0 `mobile`** variants.

*Options.* **(a)** Leave it silent — zero work, converts a rare quiet failure into the common case. **(b)** Explicit note: when the variant resolves to `null` *and* the entry has any variants, the Content page says so and names which exist; needs both sides. **(c)** Offer a picker among the variants the entry does have; `poc_variant` stays a single `PocVariant`, so **no schema change**; must choose only among **existing** tokens because the set is hard-coded a fifth time in [app/web/templates/library_editor.html](app/web/templates/library_editor.html#L80). **(d)** Synthesise or fall back to a subset — **rejected**, violates the "return `None` rather than guess" invariant and re-reverses a decision already reversed once at [docs/plans/vuln-db-editor-poc-autofill.md](docs/plans/vuln-db-editor-poc-autofill.md#L182).

*Recommendation: (b) as the minimum, shipped with the checkboxes*, with (c) as a follow-up if testers ask for it.

### 6. Revised ordered steps

**Ship steps 1–5 as one commit.** A half-applied state means an open browser tab narrows scope on its next autosave. Local app, no rolling deploy to justify the skew.

**Step 0 — Parity tests, first, in `tests/test_browser.py`**

*Files:* `tests/test_browser.py` (two new tests).

*Mechanism.* Copy the pattern of [tests/test_browser.py#L1097-L1133](tests/test_browser.py#L1097-L1133): mutate a report **in Python**, save it, navigate Playwright, assert on the DOM. **No JavaScript is extracted or parsed.**

*Test 1 — `test_scope_grid_channels_match_server_tested_channels`.* Parametrised over `["web"]`, `["web","api"]`, `["web","mobile"]`, `["web","api","mobile"]`. Saves the report server-side, loads `/setup`, and asserts the `#scope-grid label` texts in each panel equal `report.engagement.tested_channels` mapped through the labels ([app.js#L1234](app/web/static/app.js#L1234)). Must pass before and after the change (before, only `["web"]` and `["web","api"]` are constructible).

*Test 2 — `test_poc_offer_matches_server_applicable_poc_variant`.* Builds findings whose scopes Python resolves to `web`, `api`, `web_api`, and asserts `[data-poc-offer]` ([app.js#L2381](app/web/static/app.js#L2381)) carries the same value. Plus **one negative case**: a finding resolving to `{web, mobile}` on a library entry that *does* have `web` steps — Python says `None`, so the assertion is "no banner".

*What this explicitly cannot cover, and must say so in a comment:*
- **`affectedChannels` has no observable of its own.** It is visible only composed with `applicablePocVariant` through the banner. A bug that cancels out between the two is invisible.
- **`mobile` is untestable.** The library has zero mobile variants, so `steps` is never truthy.
- The banner is also suppressed when `finding.poc_variant === variant` or the variant is in `poc_variant_declined`, so fixtures must leave both clear.

*Invariant:* rule drift is caught by a test, not a user.

**Step 1 — The owner: model, helper, canonical order**

*Files:* [app/models.py](app/models.py), [app/library.py](app/library.py#L23).

*Does:* `CHANNELS`; reorder the `Channel` `Literal`; `resolve_tested_channels`; the `Report` `mode="before"` validator; `Engagement.tested_channels: list[Channel] = Field(default_factory=lambda: ["web"], min_length=1)`; `TestType` → `PocVariant`.

*Test:* Load a `test_type` draft, a legacy `tested_channels` draft, a **both-keys** draft (assert union), a bare draft **with** `scope_targets` on api (assert `["api"]`, not `["web"]`), and an empty draft (assert `["web"]`). Assert `tested_channels: []` is rejected on `import_report`. Assert a stored `poc_variant: "web_api"` still validates. Assert a malformed `tested_channels: "web"` coerces rather than raises.

*Invariants:* one function answers the question on every entry path; `[]` is returned only when explicitly sent; the validator adds no rejection surface beyond the `Channel` type.

**Step 2 — Raw-payload boundary, with no unique guarantees**

*Files:* [app/report_service.py](app/report_service.py#L388-L463).

*Does:* `reconcile_targets` deletes `channels_by_type`, calls `resolve_tested_channels`, raises on `[]`, and writes the resolved list back into `payload["engagement"]["tested_channels"]`. `setup_issues` is **not** touched.

*Test:* PUT with `tested_channels`; PUT with legacy `test_type`; **PUT with neither, from a Findings-page-shaped payload that carries no `scope_text`, on a report holding api targets** — assert `tested_channels` is still `["web","api"]` after the round trip, proving the model closed it without this function; PUT with `[]` → 422 `invalid_scope` with **no partial write**; PUT with `[]` and **no `scope_text`** → 422 from the model, proving the floor.

*Rewrite of [tests/test_app.py#L490-L493](tests/test_app.py#L490-L493).* It currently flips `test_type` from `mobile` to `web` with a live mobile target and asserts 200 — an **incidental** assertion inside a test about the mobile character allowlist. It becomes `tested_channels: ["mobile"]` → `["web"]` **and gains an explicit assertion that the mobile target is gone**, turning an accident into a deliberate pin: *server-side narrowing with no stranded findings is allowed and silent; warning the tester is the client's job.*

*Invariant:* **nothing here is the sole guarantee of anything.**

**Step 3 — Remove the old migration; fix the importer**

*Files:* [app/workspace.py#L274-L276](app/workspace.py#L274-L276), [app/docx_import.py#L523](app/docx_import.py#L523).

*Test:* Rewrite [tests/test_app.py#L275-L290](tests/test_app.py#L275-L290) — a legacy `["web","mobile"]` draft now **restores losslessly**. Add a bundle-import case carrying `test_type`. Assert a two-table DOCX import yields `["web","api"]`. Assert loading an unmigrated draft **writes nothing** to disk.

*Invariant:* legacy repair reaches `import_report`; load consumes no backup slot.

**Step 4 — Client**

*Files:* [app/web/static/app.js](app/web/static/app.js) — the fourteen rows above.

*Does:* checkboxes from the static `CHANNELS` list with per-box `aria-label`s; split `channelLabels` / `pocVariantLabels`; channel-list plumbing through `findingsStrandedBy` and the environment toggle; **the `survivingAfterScopeText` channel filter (risk 21)**; `confirmScopeLoss` counts targets and custom locations; floor of one checked box.

*Test:* [tests/test_browser.py#L446](tests/test_browser.py#L446) rewritten to click checkboxes. New: ticking "Mobile" on a web report adds a Mobile textarea with **no** dialog. New: unticking "API" with api targets but **no referencing findings** raises the target-count dialog, and cancelling leaves `scope_targets` untouched. New: unticking a channel that strands a finding blocks the save through `strandedByScopeEdit`, proving risk 21 is closed. Existing [#L432-L433](tests/test_browser.py#L432-L433) must still pass.

*Invariant:* widening never warns; narrowing always warns before the server can reject it.

**Step 5 — Stylesheets and accessibility**

*Files:* [app/web/static/overrides.css](app/web/static/overrides.css#L38), [app/web/static/taste.css](app/web/static/taste.css#L665). Same commit as step 4 — a `select { width: … }` rule with no `<select>` leaves a silently broken layout.

*Does:* replace the two `select` width rules ([overrides.css#L51](app/web/static/overrides.css#L51), [taste.css#L704](app/web/static/taste.css#L704)) and the breakpoint rule ([overrides.css#L347](app/web/static/overrides.css#L347)); revisit `flex-direction: column` ([taste.css#L699-L702](app/web/static/taste.css#L699)) for a three-box row; reuse `.coverage-option` sizing ([overrides.css#L54-L56](app/web/static/overrides.css#L54)). [app/web/static/app.css](app/web/static/app.css#L2) is untouched.

**Step 6 — PoC policy.** Per question 2.

**Step 7 — Mobile in the document.** Per question 1.

**Step 8 — Docs.** [docs/DATA_MAP.md](docs/DATA_MAP.md) §6, §7, §8, §12 per the maintenance contract, plus this plan file.

### 7. What the planner would not do

- **Would not put the empty-set guarantee in `reconcile_targets`.** That was Round 1's defect: it runs on one page in three. The floor is `min_length=1` on the field.
- **Would not add `"app type"` to `setup_issues`.** With `min_length=1`, an empty list cannot exist on a validated `Report`, so the branch is unreachable code that reads like a guarantee.
- **Would not keep `test_type` on the model "just in case".**
- **Would not put the migration in `load_path`.** `import_report` does not go through it, which is exactly why bundle and DOCX imports get no repair today.
- **Would not default to `web` at any boundary where the report's own `scope_targets` can answer.**
- **Would not let a `test_type` present alongside a stale `tested_channels` be overruled by simple precedence.** Union is three words and it cannot destroy a target.
- **Would not bump `schema_version`.**
- **Would not render the checkbox row from `tested_channels`.**
- **Would not write a parity test that parses JavaScript.**

## Answers

> Reading order note: Questions 1 and 2 were put to the user after Round 2. The Question 2 answer invalidated the plan's central premise, which commissioned **Round 3 - Oracle** (below this section), and Questions 3 and 4 came out of those findings. Round 3 therefore sits after these answers even though it precedes the last two of them.

### Question 1 — Should mobile scope appear in the generated report?

**Answer: option (i), deferred.** The user will supply an updated `.docx` template containing the mobile scope table:

> "I will add the report template where the mobile scope will be put in the future."

**Consequence recorded.** The template is not arriving inside this change, which triggers the planner's own fallback clause verbatim: *"if the template edit cannot happen in this change, then (ii) with the warning as a hard requirement of step 4, not a follow-up."* So:

- **Now (step 4):** all three checkboxes ship, **plus** a readiness warning whenever mobile scope targets exist — "Mobile scope will not appear in the generated report." Not optional, not a follow-up. Without it the change turns a rare silent data-loss hole into a routine one.
- **Later (step 7), when the template lands:** add the third caption lookup in `_populate_scope_tables` ([app/docx_report.py](app/docx_report.py#L375-L383)) and the `prod-mobile` / `non-prod-mobile` tokens in `_metadata` ([app/docx_report.py](app/docx_report.py#L235-L238)), then **delete the warning in the same change**. The warning is scaffolding with a defined removal trigger, not a permanent feature.

Rejected: **(iii) web + API only**, because `{web, api}` is already expressible today as the `web_api` token, so that version delivers nothing new. Rejected: shipping the third checkbox with no warning.

### Question 2 — What happens when a finding's channels match no proof-of-concept variant?

**Answer: none of the offered options. The user redefined the mechanism**, verbatim:

> "I think, we just remove the web + api. And make the user choose which poc they want to apply on the apptype that they have. if they have apptype api web mobile selected in the affected location (in the findings tab not the scope in setup page), then they can choose one or more then those will just append each other they the testers can just remove parts and revise it as they like."

Decoded into three requirements:

1. **Retire the `web_api` composite token.** Proof-of-concept variants are keyed by plain `Channel` — `web`, `api`, `mobile` — with no compound tokens. This makes `PocVariant` and `Channel` the same type, so the `TestType` → `PocVariant` rename in the Round 2 plan collapses into "delete `TestType`, use `Channel`".
2. **Selection is driven by the finding's own affected locations**, from the Findings tab — not by the report-level `tested_channels` set on Setup. A finding touching web + api + mobile offers three variants.
3. **Multi-select and append.** The tester ticks one or more; their step lists are concatenated into the proof-of-concept section as ordinary editable content, which the tester then trims and rewrites.

**This invalidates the Round 2 plan's cheapest premise.** That plan kept `resources/vuln_library.json` untouched and every stored value valid, precisely *because* the token set survived unchanged. Under this answer the library must be re-keyed and `Vulnerability.poc_variant` becomes plural. It also re-reverses a decision already made and reversed once — [docs/plans/vuln-db-editor-poc-autofill.md](docs/plans/vuln-db-editor-poc-autofill.md#L182) records "Re-keyed variants from `TestType` to `Channel`, and ruled that a finding resolving to more than one channel gets no variant at all", after which the shipped code went back to `TestType` keys with a `web_api` special case. Going to per-channel keys is therefore a *third* position, and it differs from that reverted one in the part that matters: multi-channel findings get **several** variants rather than none.

Round 3 below establishes what re-keying actually costs before any of this is committed to.

### Question 3 — Where does the proof-of-concept multi-select live?

Raised because Round 3 §4 found that the phrase "in the findings tab" is ambiguous: the affected-location editing is on the Findings tab, but the proof-of-concept section and its offer banner are on the Content page, one navigation step later.

**Answer: A — the multi-select lives on the Content page.** The app types offered are derived from *that finding's own* affected locations (edited on the Findings tab), not from the report-level `tested_channels` on Setup — which is what `affected_channels` already does. The control itself replaces the existing single-variant banner where the proof-of-concept section actually is.

Rejected: **B, a new picker inside the findings rows.** Round 3 §4 lists four defects — the Findings page never renders `contents` so the tester would see no result until navigating away; a newly added finding has `contents: []` until its first save, so the install silently no-ops; it needs an entirely new render surface in `enhanceFindingRows()`; and it still cannot fire for a finding with no `library_ref`. It also would not remove the need to change the Content page.

### Question 4 — Numbering when two variants' steps are appended

Raised because Round 3 §2 found that two concatenated `numbered_list` fragments render as two lists each restarting at `1.`, because `_remap_numbering` allocates a fresh `numId` per fragment and writes a `w:startOverride`.

**Answer: (1) merge into one continuous list.** Selected variants' `items` arrays are combined into a **single** `ListFragment`, so the generated document reads `1.` through `6.` rather than `1,2,3` twice.

**Consequences accepted.** The tester cannot tell at a glance which steps came from which app type, and unticking a variant afterwards cannot cleanly remove just its steps — that becomes a manual edit. Both are consistent with the user's own framing that testers "just remove parts and revise it as they like". Note also that in all 11 header entries the final step is byte-identical between `web` and `api`, so any append leaves one duplicated line for the tester to delete; that is true under every option and is not a reason to prefer one.

Rejected: **(2) separate blocks**, which prints two `1.` items in the delivered report and reads as a defect. Rejected: **(3) separate blocks with `Web:` / `API:` headings**, which makes the restart deliberate but injects content into the section and changes its shape.

## Round 3 - Oracle: what the user's answer actually costs

> Verbatim findings from `data-oracle`, commissioned after the Question 2 answer invalidated the Round 2 premise. Headings demoted.

### 1. What is inside the 11 `web_api` variants

**`web_api` is dead weight. All 11 are verbatim copies of that entry's `web` list.** Deleting it loses **zero** unique content. This is a pure deletion, not a merge and not a content-authoring job.

`resources/vuln_library.json` has 51 entries; 12 define `proof_of_concept`; 11 of those define `web_api`. Only VDB-015 ("AI Response Misinformation", [L83](resources/vuln_library.json#L83)) has no `web_api`. The other 11 — VDB-050, VDB-051, VDB-036 through VDB-044 — are all "identical": same single `numbered_list` fragment, same three items, same run text, same order. The **only** difference is the `frag_id` (`VDB-050-web-poc` vs `VDB-050-web_api-poc`), a naming convention from the library editor's id template ([app/library_editor.py](app/library_editor.py#L29)), and it is reminted on install anyway.

Representative — VDB-050, `web` ([L1155-L1183](resources/vuln_library.json#L1155-L1183)) and `web_api` ([L1184-L1212](resources/vuln_library.json#L1184-L1212)) both read:

```
1. Run the application in a browser configured to proxy with Burp Suite.
2. Open the captured traffic in the HTTP History's Proxy tab.
3. It is observed in the response that the "Pragma" is Present/not set.
```

while `api` ([L1126-L1154](resources/vuln_library.json#L1126-L1154)) reads:

```
1. Run the endpoint in Burp Suite.
2. Send the request to Repeater.
3. It is observed in the response that the "Pragma" is Present/not set.
```

Note **step 3 is byte-identical between `web` and `api` in all 11 header entries.** Only the first two steps differ.

The most-distinct entry, VDB-015, has genuinely different `web` and `api` prose with parallel structure; concatenating those two gives six coherent steps with no duplication — the best case.

**Would concatenating `web` + `api` be coherent?** Mostly yes, with two cosmetic warts: (1) a duplicated final line in all 11 header entries, which the tester deletes; (2) numbering restarts — see §2. No contradictory setup steps, no cross-references between variants, nothing describing "a combined attack". The premise that motivated `web_api` never materialised in the data.

### 2. Fragment identity and append mechanics

**`frag_id` uniqueness is report-wide**, not per-finding and not per-section — [app/models.py](app/models.py#L231-L234), inside `Report.validate_references`. A repeat raises `ValueError("duplicate fragment id: …")` on **load**, demoting the whole draft to the manager's legacy/invalid list. `repair_duplicate_fragment_ids` ([app/workspace.py](app/workspace.py#L217-L240)) is the opt-in manual escape hatch, not a load-path hook.

Within a `LibraryEntry`, uniqueness is checked **per variant only** — [app/library.py](app/library.py#L31-L41), whose comment reads *"Checked per app type, not across them: only one set is ever copied into a finding."* **That comment becomes false under this requirement.** Nothing today rejects a library entry whose `web` and `api` lists share a `frag_id`.

**Appending two variants will not mint duplicates, because every install path remints:** Python [app/report_service.py](app/report_service.py#L369-L372) (`model_copy(deep=True)` then a fresh `f_<8 hex>`), JavaScript [app/web/static/app.js](app/web/static/app.js#L942) `remintFragments`. **The only way to trip the duplicate-id validator is to write new code that concatenates raw library fragments without routing through one of those two paths.**

**`mode="merge"` already does exactly the append the user asked for.** `apply_poc_variant` ([app/report_service.py](app/report_service.py#L360-L377)) keeps images at the end, keeps existing non-image fragments when merging, and inserts the copied steps between. Its JS twin is [app/web/static/app.js](app/web/static/app.js#L945-L956). **But `poc_variant` is singular and overwritten on every call** ([#L375](app/report_service.py#L375)), so two merges leave only the second token recorded and the banner re-offers the first forever.

**Two concatenated numbered lists produce two "1." items.** [app/docx_report.py](app/docx_report.py#L736-L749) creates a **fresh** `numbering_ids` cache per `ListFragment`; `_remap_numbering` ([app/docx_components.py](app/docx_components.py#L225-L284)) then allocates a new `numId` and `_restart_numbering_levels` ([#L336-L355](app/docx_components.py#L336-L355)) writes a `w:startOverride` back to 1. So a naive append renders `1. 2. 3.` then `1. 2. 3.` **To get `1..6` the two variants' `items` arrays must be merged into one `ListFragment`, which is not what merge mode does.**

### 3. `poc_variant` becoming plural

[app/models.py](app/models.py#L139-L142): `poc_variant: TestType | None = None`, `poc_variant_declined: list[TestType] = Field(default_factory=list)`.

**Complete list of reads and writes** — six hits beyond definitions and twin-marker comments:

| Side | Location | Field | R/W | What it does |
|---|---|---|---|---|
| Python | [report_service.py#L375](app/report_service.py#L375) | `poc_variant` | write | records the installed variant |
| Python | [report_service.py#L377](app/report_service.py#L377) | `poc_variant_declined` | write | resets to `[]` |
| JS | [app.js#L953](app/web/static/app.js#L953) | `poc_variant` | write | same |
| JS | [app.js#L955](app/web/static/app.js#L955) | `poc_variant_declined` | write | same |
| JS | [app.js#L2364](app/web/static/app.js#L2364) | **both** | **read** | the only read of either field anywhere |
| JS | [app.js#L2385](app/web/static/app.js#L2385) | `poc_variant_declined` | write | pushes the refused variant |

**`poc_variant` is purely an idempotence guard.** Never displayed, never exported, never read by Python at all. Its one consumer is the banner condition at [app.js#L2364](app/web/static/app.js#L2364):

```javascript
if (steps && finding.poc_variant !== variant && !(finding.poc_variant_declined || []).includes(variant)) {
```

The label the tester sees comes from `testTypes[variant].label` at [#L2370](app/web/static/app.js#L2370) where `variant` is the freshly-derived value, **not** `finding.poc_variant`.

**What breaks if it becomes `list[Channel]`:** the stored `null` is not a valid list unless the field stays optional or the loader repairs it, and `import_report` bypasses `load_path` entirely; the suppression check becomes set logic rather than equality, so the banner must offer the *remainder*; `apply_poc_variant` overwrites rather than accumulates; and the wholesale clear of `poc_variant_declined` ([#L377](app/report_service.py#L377)) is **plainly wrong for a multi-select**, where declining `api` and accepting `web` are independent decisions.

**On disk, reconfirmed:** all three files carry `poc_variant: null`, `poc_variant_declined: []`, **and `library_ref: null` on every finding** — which means the PoC offer cannot fire for any finding currently on disk. `LibraryRef` is `{library_id, source_id, inserted_at}` ([app/models.py](app/models.py#L116-L119)) and **does not record which variant was applied**; that memory lives on `Vulnerability` deliberately, because both insert paths rebuild `library_ref` from scratch.

### 4. The offer surface: Findings tab vs Content page — **they are different pages**

Page dispatch is [app.js#L2468](app/web/static/app.js#L2468): `root.id === "setup" ? setup() : continuousEditor();`

| Template | `<main>` | Entry function |
|---|---|---|
| [page1_setup.html](app/web/templates/page1_setup.html) | `id="setup" data-step="setup"` | `setup()` |
| [page2_findings.html](app/web/templates/page2_findings.html#L4) | `id="setup" data-step="findings"` | `setup()` |
| [page2_editor.html](app/web/templates/page2_editor.html#L3) | `id="editor"` | `continuousEditor()` |

**The PoC banner renders on the Content/Editor page only** — built at [app.js#L2360-L2388](app/web/static/app.js#L2360-L2388) inside `continuousEditor()`, DOM node `div.poc-offer` with `data-poc-offer` at [#L2366-L2368](app/web/static/app.js#L2366-L2368).

**The affected-location editing is on the Findings page only** — the "Additional affected endpoints" textareas that write `scope.custom_locations` are built at [app.js#L1505-L1553](app/web/static/app.js#L1505-L1553) inside `enhanceFindingRows()`, and the target checkboxes that write `scope.target_ids` are in the same rows. `affectedChannels` ([#L883-L895](app/web/static/app.js#L883-L895)) reads exactly those two sources.

**What a multi-select offer would need to appear on the Findings tab:**

1. A new render surface inside `enhanceFindingRows()`; the per-finding expandable location row at [#L1392-L1404](app/web/static/app.js#L1392-L1404) is the natural host.
2. `library` is already available there — [page2_findings.html](app/web/templates/page2_findings.html#L4) seeds `data-library`, parsed at [#L90](app/web/static/app.js#L90). `pocStepsFor` works unchanged.
3. `applyPocVariant` mutates `finding.contents`, which exists on the Findings page's `report` object — **but the Findings page never renders `contents`**, so the tester ticks boxes and sees no result until they reach the Content page. UX consequence, not a data one.
4. **The findings half of `setup()` provisions nothing.** `provision()` runs inside `continuousEditor()` at [#L2101](app/web/static/app.js#L2101). A finding whose `proof_of_concept` section does not yet exist makes `applyPocVariant` return silently at [#L947](app/web/static/app.js#L947). Server-side `provision` runs on every PUT, so the section exists after the first save — but a newly added finding, before any save, has `contents: []` ([#L1662](app/web/static/app.js#L1662)).
5. **The offer cannot fire without `library_ref`**, set by `applyLibraryEntry` ([#L1381-L1383](app/web/static/app.js#L1381-L1383)) on a title match. A tester-authored finding still gets nothing.

### 5. Every hard-coded copy of the four-token set — **eight, not five**

| # | Location | Form | What breaks if not updated |
|---|---|---|---|
| 1 | [models.py#L13](app/models.py#L13) | `TestType = Literal[...]` | One symbol, **four meanings**: `Engagement.test_type` ([#L156](app/models.py#L156)), `poc_variant` / `poc_variant_declined` ([#L141-L142](app/models.py#L141-L142)), and `LibraryEntry.proof_of_concept` keys ([library.py#L23](app/library.py#L23)) |
| 2 | [report_service.py#L404](app/report_service.py#L404) | `channels_by_type` local | Raw-payload read raises `ValueError("test_type is invalid")` → **422 `invalid_scope`, whole save rejected**, before Pydantic runs. *Cited as #L399 in Rounds 1-2; it has drifted* |
| 3 | [report_service.py#L274-L285](app/report_service.py#L274-L285) | `applicable_poc_variant`'s four branches | Server asks the library for a `web_api` key that no longer exists → **silent empty PoC, no error** |
| 4 | [workspace.py#L275-L276](app/workspace.py#L275-L276) | the legacy migration's `"web_api" if …` | Writes a token the new `Literal` rejects → `ValidationError` on the next load → **draft demoted**. Fires only on drafts missing `test_type`; none on disk today |
| 5 | [docx_import.py#L536](app/docx_import.py#L536) | the inverse collapse | A two-table DOCX import writes `web_api` and `model_validate` rejects it → **import fails outright**, no legacy repair to catch it |
| 6 | [app.js#L881](app/web/static/app.js#L881) | `testTypes` | (a) the Setup dropdown and scope grid render from it; (b) **`testTypes[variant].label` at [#L2370](app/web/static/app.js#L2370) is an unguarded property access — delete the key while anything still resolves to `web_api` and the Content page throws a `TypeError` mid-render** |
| 7 | [app.js#L897-L903](app/web/static/app.js#L897-L903) | `applicablePocVariant` | Drifts from its Python twin. **No contract test covers this pair** |
| 8 | [library_editor.html#L80](app/web/templates/library_editor.html#L80) | `const variants = ["web","api","web_api","mobile"]` plus textareas at [#L64-L67](app/web/templates/library_editor.html#L64-L67) | The editor keeps offering a "Web + API" box and POSTs `proof_of_concept.web_api` on save. **Untracked file, so it will not appear in a diff** |

Plus the data: 11 `web_api` blocks in [resources/vuln_library.json](resources/vuln_library.json).

### 6. The library editor

The Python side is **variant-agnostic** — [app/library_editor.py](app/library_editor.py#L56-L59) and [#L85-L96](app/library_editor.py#L85-L96) iterate whatever keys they receive and never import `TestType`. So it **round-trips `web_api` faithfully**, and combined with the template still rendering the box, **the editor is a live re-injection path for the retired token**: a user editing any unrelated field on VDB-050 re-submits `web_api` and it is written back.

**Validation would reject it, hard.** `proof_of_concept: dict[TestType, list[Fragment]]` ([app/library.py](app/library.py#L23)) — Pydantic validates dict **keys** against the `Literal`. An invalid dict key is a validation failure, not `extra="ignore"` territory. Three consequences:

1. The editor's `_write_validated` ([app/library_editor.py](app/library_editor.py#L126-L152)) catches it and returns 422, so the good file is never replaced — **but the editor becomes unusable for all 12 PoC entries** until the `web_api` blocks are deleted by hand.
2. **At app boot the failure is soft and easy to miss.** `ValidationError` subclasses `ValueError`, so `Library.load_or_empty` ([app/library.py](app/library.py#L58-L67)) catches it and the app boots with a **completely empty library** — no search results, no PoC offers, no content offers. The only signal is one line printed at startup ([app/main.py](app/main.py#L41-L43)). **The symptom is "the library silently disappeared", not an error.**
3. `LibraryDocument` also enforces `entry_count == len(entries)` and unique `library_id`s ([app/library.py](app/library.py#L50-L56)).

`resources/vuln_library.json` is the only library read ([app/main.py](app/main.py#L39-L41), `LIBRARY_PATH` at [app/tester_identity.py](app/tester_identity.py#L153-L154), [data/prefs.json](data/prefs.json#L13)). The untracked root `vuln_library.json` **contains zero `proof_of_concept` keys** — it is the converter's raw output, no code references it, and it is immune to this change.

### 7. Migration reality for the library

**There is no migration path at all.** `Library.__init__` ([app/library.py](app/library.py#L61-L66)) is `LibraryDocument.model_validate(json.loads(...))` and nothing else — no key-presence repair, no version branch, no rewrite. The only write path is the untracked editor's `_write_validated`, which validates but never transforms. **So retiring `web_api` from the type requires editing `resources/vuln_library.json` in the same change. There is no "the loader will fix it on first read" option.**

`LibraryDocument.schema_version` is an unconstrained `str` ([app/library.py](app/library.py#L45)), never compared to anything. The file carries `"1.4"`. Bumping it is free and worthless.

**Risk to the 39 entries with no `proof_of_concept`:** low for the field itself (`Field(default_factory=dict)`), but **real and document-wide from hand-editing a 5,000-line JSON file**. Every failure mode is all-or-nothing:

| Failure | Caught at | Symptom |
|---|---|---|
| Stray comma / broken JSON | `json.loads` ([library.py#L61](app/library.py#L61)) | **Whole library empty**, all 51 entries gone |
| Entry accidentally deleted | `entry_count` mismatch ([#L52-L53](app/library.py#L52-L53)) | Same |
| `library_id` duplicated by a bad paste | [#L54-L55](app/library.py#L54-L55) | Same |
| `frag_id` duplicated inside one entry | [#L25-L29](app/library.py#L25-L29) | Same |
| `_README` block damaged | nowhere — undeclared key, ignored | Survives |

Existing drafts carry `library_ref.library_id` values pointing into that file, so with an empty library all library-linked offers silently stop appearing across every report. **One tracked guard exists:** [tests/test_app.py](tests/test_app.py#L1005-L1006) constructs `Library(ROOT / "resources" / "vuln_library.json")` and asserts `shipped.entries` is truthy, so a broken library fails the suite rather than only failing at runtime.

### Additional invariants this requirement touches

| Invariant | Where | If violated |
|---|---|---|
| Every fragment copied from the library is reminted | [report_service.py#L369-L372](app/report_service.py#L369-L372), [app.js#L942](app/web/static/app.js#L942) | Violates report-wide `frag_id` uniqueness. Any new append path must route through one of these two |
| `proof_of_concept` always holds a `numbered_list`, first | `ensure_proof_steps` [#L155-L159](app/report_service.py#L155-L159) / `ensureProofSteps` [#L938-L940](app/web/static/app.js#L938-L940) | The section loses its steps; the server puts one back on the next save and the editor looks like it discarded the change |
| `apply_poc_variant` never touches images | [report_service.py#L368](app/report_service.py#L368) | Uploaded evidence destroyed by a library install |
| One `Content` per `type` per finding | [models.py#L227-L229](app/models.py#L227-L229) | An append pushing a *second* `proof_of_concept` block fails validation. Both install paths correctly target the single existing block |
| `applicable_poc_variant` returns `None` rather than guessing | [report_service.py#L274-L285](app/report_service.py#L274-L285) | **This requirement deliberately relaxes it — the tester picks, so the guess is theirs** |

### The server has no multi-select path

`insert_library` ([app/main.py](app/main.py#L722-L726)) picks exactly one variant and calls `apply_poc_variant` once, in `"replace"` mode. A per-finding multi-select is a client mutation riding the ordinary autosave PUT — **unless `insert_library` also changes, the server's first-insert behaviour and the client's offer diverge by construction.**

### Line-number drift in this plan document

`channels_by_type` is now [app/report_service.py](app/report_service.py#L404) (cited as #L399 above); `data-poc-offer` is now [app.js#L2368](app/web/static/app.js#L2368) (cited as #L2381); `testTypes[variant].label` is now [app.js#L2370](app/web/static/app.js#L2370) (cited as #L2374/#L2383). Function and field names are the durable identifiers.

_pending_

## Agreed plan

This section is self-contained. Nothing above is required to follow it.

### What is being built

Two linked changes to how app types work.

**1. Report scope becomes a set.** `engagement.test_type` — a single token from `web` / `api` / `mobile` / `web_api`, rendered as a dropdown on Setup — is replaced by `engagement.tested_channels: list[Channel]`, rendered as three checkboxes. Any combination becomes expressible, including web + mobile and all three, which are unrepresentable today.

**2. Proof-of-concept variants become per-channel and multi-select.** The `web_api` composite is retired. Library steps are keyed by plain channel (`web`, `api`, `mobile`). On the Content page, a finding whose affected locations span several app types offers all the variants its library entry actually has; the tester ticks one or more and their steps merge into one continuous numbered list, which the tester then edits freely.

### The decisions that shaped it

| Decision | Chosen | Why |
|---|---|---|
| Field shape | `tested_channels: list[Channel]`, reusing the **old legacy key name** | Symmetric with `tested_environments`; deletes three type→channel expansion maps instead of growing them; and a code rollback degrades losslessly, because the old `load_path` branch reads that exact key |
| Migration home | A `Report` `model_validator(mode="before")`, **not** `load_path` | `import_report` and both `parse_import` branches bypass `load_path` entirely, so the documented home has a known hole |
| `schema_version` | **Not bumped** | Nothing branches on it; it is a `Literal`, so a bump makes every draft on disk unloadable unless `load_path` rewrites it — the same mechanism the validator already replaces |
| `web_api` | **Deleted from the library and the type** | All 11 entries that define it hold a verbatim copy of that entry's `web` steps. Zero unique content is lost |
| PoC key type | `Channel` — `TestType` is deleted outright | With `web_api` gone, `PocVariant` and `Channel` are the same three tokens. One symbol, one meaning |
| Multi-select location | Content page, driven by the finding's own affected locations | The proof-of-concept section and its offer already live there; the Findings page never renders `contents` |
| Merged numbering | One `ListFragment`, steps run continuously | Two fragments render as two lists each restarting at `1.` |
| Mobile in the DOCX | Deferred; **a warning ships in the meantime** | The template has no mobile scope table. The user will supply one later |

### The load-bearing invariants

Every step below protects at least one of these. They are the reason the ordering is what it is.

1. **`reconcile_targets` only runs when the payload carries `scope_text`** — [app/report_service.py](app/report_service.py#L390-L391). Only the Setup page seeds it. **Nothing in this change may depend on that function running.**
2. **`reconcile_targets` runs on the raw dict *before* `Report.model_validate`** — [app/main.py](app/main.py#L662) vs [#L676](app/main.py#L676).
3. **Save rejection is all-or-nothing.** A partial apply leaves `scope_targets` and `vulnerabilities[].scope` inconsistent, which [app/models.py](app/models.py#L218-L219) catches on the *next* load and demotes the draft.
4. **`target_id` reuse is keyed on the `(environment, channel, value)` triple** — [app/report_service.py](app/report_service.py#L437). Dropping and re-adding a channel remints every ID and strands `scope.target_ids`.
5. **`frag_id` is unique report-wide** — [app/models.py](app/models.py#L231-L234). Every fragment copied from the library must be reminted, as both install paths already do.
6. **One `Content` per `type` per finding** — [app/models.py](app/models.py#L227-L229). An append must extend the existing `proof_of_concept` block, never push a second one.
7. **`apply_poc_variant` never touches images** — [app/report_service.py](app/report_service.py#L368). Uploaded evidence survives every install.
8. **`LibraryDocument` is all-or-nothing** — [app/library.py](app/library.py#L58-L67). One malformed byte empties all 51 entries **silently**, behind a single printed startup line.
9. **One rule, one owner.** The model default and any raw-payload fallback must agree on what "no channel information" means.

### Where the channel decision lives

One function owns it: **`resolve_tested_channels(report_mapping) -> list[Channel]`** in [app/models.py](app/models.py). It takes the whole raw report mapping, because branch 4 needs `scope_targets`. Precedence tests key **presence**, never truthiness:

1. Both `tested_channels` and `test_type` present → **union**, ordered by `CHANNELS`. Only reachable in a hand-edited or third-party file; chosen because it is the only rule that cannot drop a target.
2. `tested_channels` present → use it, deduped and ordered. A bare string coerces to a one-element list. **The only branch that can return `[]`.**
3. `test_type` present → map the four tokens (`web_api` → `["web","api"]`). An unrecognised token passes through so the `Channel` `Literal` rejects it — **the validator never raises on its own**.
4. Neither → the channels present on the mapping's own `scope_targets`.
5. Neither, and no targets → `["web"]`.

**Invariant: it returns `[]` if and only if the caller explicitly sent an empty list.** That is what keeps "raise on empty" and "fall back when absent" from contradicting each other.

The `Report` before-validator is the only caller that runs on every path. `Engagement.tested_channels` carries `min_length=1` as the floor — the only gate that catches `[]` arriving through `import_report`, which skips `reconcile_targets`. `reconcile_targets` calls the same helper and writes the result back into the payload, but **provides no unique guarantee**, because it does not run on two of the three pages.

Canonical channel order lives in `app/models.py` as `CHANNELS = ("web", "api", "mobile")`, with the `Channel` `Literal` reordered to match. `app/docx_report.py` imports it (that direction already exists, so no cycle); `app.js` mirrors it once.

---

### Step 0 — Parity tests, before any feature code

**Files:** `tests/test_browser.py` (two new tests).

Follow the existing pattern at [tests/test_browser.py](tests/test_browser.py#L1097-L1133): mutate a report in Python, save, navigate Playwright, assert on the DOM. **No JavaScript is extracted or parsed** — there is no JS engine in the test suite and adding one is not in scope.

- `test_scope_grid_channels_match_server_tested_channels` — parametrised over `["web"]`, `["web","api"]`, `["web","mobile"]`, `["web","api","mobile"]`; asserts the `#scope-grid` panel labels match the server's list. Must pass before and after (before, only the first two are constructible).
- `test_poc_offer_matches_server_applicable_variants` — asserts the Content page's `data-poc-offer` node matches what Python resolves, including a negative case.

**Must carry a comment stating what it cannot cover:** `affectedChannels` has no DOM observable of its own — it is visible only composed with variant resolution through the banner, so a bug that cancels out between the two is invisible. Fixtures must leave `poc_variants` and `poc_variant_declined` clear, since both suppress the offer.

**Invariant protected:** 9 — rule drift is caught by a test, not a user. There is no contract test for any of the rules this change touches.

### Step 1 — The model: one owner, one channel order, no `TestType`

**Files:** [app/models.py](app/models.py), [app/library.py](app/library.py#L23).

- Add `CHANNELS = ("web", "api", "mobile")`; reorder the `Channel` `Literal` to match. Verified safe: `get_args` appears nowhere in `app/`, `Literal` member order has no validation semantics, and nothing consumes the generated JSON Schema.
- Add `resolve_tested_channels`.
- `Engagement.test_type` → `tested_channels: list[Channel] = Field(default_factory=lambda: ["web"], min_length=1)`. Leave `validate_environments` ([#L166-L170](app/models.py#L166-L170)) alone — it is `mode="after"` and reads only `tested_environments`.
- Add the `Report` `model_validator(mode="before")`. Guard `isinstance(data, dict)`. **This is the first `mode="before"` validator in the codebase.**
- **Delete `TestType`.** `LibraryEntry.proof_of_concept` becomes `dict[Channel, list[Fragment]]`. `Vulnerability.poc_variant: TestType | None` becomes `poc_variants: list[Channel] = Field(default_factory=list)`; `poc_variant_declined: list[Channel]`. The same before-validator migrates the old scalar: `"web_api"` → `["web","api"]`, `"web"` → `["web"]`, `null` → `[]`.

**Test:** load a `test_type` draft, a legacy `tested_channels` draft, a both-keys draft (assert union), a bare draft *with* api `scope_targets` (assert `["api"]`, not `["web"]`), and an empty draft (assert `["web"]`). Assert `tested_channels: []` is rejected through `import_report`. Assert a stored `poc_variant: "web_api"` migrates to `["web","api"]`. Assert a malformed `tested_channels: "web"` coerces rather than raises.

**Invariants protected:** 9, and the `[]`-vs-absent distinction. Note the risk this step introduces: the old migration used `set(engagement.pop("tested_channels", []))`, which never raised — `set("web")` silently yields `{"w","e","b"}`. A validated field raises `ValidationError`, which **demotes a draft to the manager's legacy/invalid list**. Bounded by fact: zero drafts on disk carry the key. The coercion rule above is what keeps the rejection surface no wider than the `Channel` type itself.

### Step 2 — The library data and its editor

**Files:** [resources/vuln_library.json](resources/vuln_library.json), [app/web/templates/library_editor.html](app/web/templates/library_editor.html#L64-L80).

- Delete the 11 `web_api` blocks. Nothing else in the file changes; `entry_count` is unaffected because entries are not removed.
- Remove the "Web + API" textarea and drop `web_api` from the hard-coded `variants` array. **This file is untracked, so it will not appear in a diff — it is the easiest thing in this change to forget, and leaving it re-injects the retired token on the next library edit.**

**Why this step comes before the client:** there is **no migration path for the library at all**. `Library.__init__` validates and nothing else. If the type drops `web_api` while the JSON still has it, `Library.load_or_empty` catches the `ValidationError` and the app boots with a **completely empty library** — no search, no offers anywhere — signalled only by one printed startup line.

**Test:** the existing guard at [tests/test_app.py](tests/test_app.py#L1005-L1006) constructs `Library(ROOT / "resources" / "vuln_library.json")` and asserts `entries` is truthy; it turns a silently-empty library into a test failure. Add an assertion that no entry carries a `web_api` key. Re-run it immediately after the JSON edit and before anything else.

**Invariant protected:** 8.

### Step 3 — Server: raw-payload boundary and PoC resolution

**Files:** [app/report_service.py](app/report_service.py), [app/main.py](app/main.py#L722-L726).

- `reconcile_targets`: delete the local `channels_by_type` ([#L404](app/report_service.py#L404)); call `resolve_tested_channels`; **write the result back into `payload["engagement"]["tested_channels"]`** — the function already mutates the payload at [#L392](app/report_service.py#L392), [#L431](app/report_service.py#L431), [#L448](app/report_service.py#L448) and [#L453](app/report_service.py#L453), so this follows existing precedent. The write-back is load-bearing, not belt-and-braces: the function replaces `scope_targets`, so a later derive-from-targets would otherwise see the new list. Raise `ValueError("select at least one app type")` on `[]`.
- `applicable_poc_variant` → **`applicable_poc_variants(vulnerability, report, entry) -> list[Channel]`**: the finding's `affected_channels`, filtered to channels the library entry actually has steps for. The four exact-set branches and the `None` return are deleted.
- `apply_poc_variant` → accepts several channels; **merges the selected variants' list items into the existing `numbered_list` fragment** rather than appending a second `ListFragment`, so numbering runs continuously. Still copies and remints every fragment, still preserves images, still extends the single `proof_of_concept` block. Appends to `poc_variants` rather than overwriting, and **stops clearing `poc_variant_declined` wholesale** — declining `api` and accepting `web` are now independent decisions.
- `insert_library` ([app/main.py](app/main.py#L722-L726)): today it picks one variant and installs in `replace` mode. New rule — **auto-install only when exactly one variant applies; when two or more apply, install nothing and let the tester's multi-select decide.** This preserves today's behaviour for single-channel findings and honours "make the user choose" for the mixed case. Without this the server's first-insert and the client's offer diverge by construction.
- **Do not** add an `"app type"` issue to `setup_issues`. `min_length=1` makes an empty list unrepresentable on a validated `Report`, so the branch would be unreachable code that reads like a guarantee.

**Test:** PUT with `tested_channels`; PUT with legacy `test_type`; **PUT with neither from a Findings-page-shaped payload carrying no `scope_text`, on a report holding api targets — assert the api targets survive**, proving the model closed it without `reconcile_targets`; PUT with `[]` → 422 `invalid_scope`, no partial write; PUT with `[]` and no `scope_text` → 422 from the model floor. Assert two merged variants produce **one** `numbered_list` with all items and fresh `frag_id`s.

**Rewrite [tests/test_app.py](tests/test_app.py#L490-L493):** it currently flips `test_type` from `mobile` to `web` with a live mobile target and asserts 200 — an *incidental* assertion inside a test about the mobile character allowlist. It becomes `tested_channels: ["mobile"]` → `["web"]` **plus an explicit assertion that the mobile target is gone**, turning an accident into a deliberate pin: server-side narrowing with no stranded findings is allowed and silent; warning the tester is the client's job.

**Invariants protected:** 1, 2, 3, 5, 6, 7.

### Step 4 — Remove the old migration; fix the DOCX importer

**Files:** [app/workspace.py](app/workspace.py#L274-L276), [app/docx_import.py](app/docx_import.py#L523-L537).

- Delete the `tested_channels` → `test_type` branch in `load_path`; the before-validator supersedes it and also covers `import_report`, which `load_path` never did.
- The importer writes the parsed channel set directly, ordered by `CHANNELS`, falling back to `["web"]` only when no targets parsed — mirroring the existing `environments or ["production"]`.

**Test:** rewrite [tests/test_app.py](tests/test_app.py#L275-L290) — a legacy `["web","mobile"]` draft now **restores losslessly** instead of collapsing to `"mobile"`. Add a bundle-import case carrying `test_type`. Assert a two-table DOCX import yields `["web","api"]`. Assert loading an unmigrated draft **writes nothing to disk**, so no backup slot is consumed.

**Invariant protected:** 3. Note `repair_duplicate_fragment_ids` validates and then persists the **raw** draft, so a manager-triggered repair leaves `test_type` on disk; the next ordinary save migrates it. That is acceptable, not a bug to fix here.

### Step 5 — Client: Setup checkboxes

**Files:** [app/web/static/app.js](app/web/static/app.js).

- Split `testTypes` ([#L881](app/web/static/app.js#L881)) into a module-scope `CHANNELS` and `channelLabels`; delete the setup-local `channelLabels` at [#L961](app/web/static/app.js#L961); replace the inline `["api","web","mobile"]` in the `scope_text` seed loop at [#L1047](app/web/static/app.js#L1047).
- `renderCoverage` ([#L1154-L1168](app/web/static/app.js#L1154-L1168)): `<select>` → three checkboxes rendered from the **static `CHANNELS` list, never from `tested_channels`**. If it iterated `tested_channels`, an imported empty list would render zero checkboxes on a page already rendering zero scope textareas, and Setup would be unfixable. Confirm-then-commit per box; refuse to uncheck the last.
- Each checkbox needs its own `aria-label` — three inputs inside one `<label>` have no association. **Prefix them (`"Test Web App"`, `"Test API"`, `"Test Mobile"`)**, because [tests/test_browser.py](tests/test_browser.py#L432-L433) already locates scope textareas by the bare names `Web` / `API` / `Mobile`.
- Seed at [#L1032](app/web/static/app.js#L1032): derive from `scope_targets`, else `["web"]` — twin of helper branches 4 and 5. Delete the `?? ["web"]` at [#L1524](app/web/static/app.js#L1524).
- Plumb the channel list through `findingsStrandedBy` ([#L1108-L1113](app/web/static/app.js#L1108-L1113)), the environment toggle ([#L1190](app/web/static/app.js#L1190)), and the scope grid ([#L1232](app/web/static/app.js#L1232)).
- **`survivingAfterScopeText` ([#L1128-L1133](app/web/static/app.js#L1128-L1133)) must also filter on `tested_channels.includes(target.channel)`.** It decides survival from `report.scope_text[env][channel]` and treats `undefined` as "survives" — but after a channel is unchecked that text is still defined and still populated, so the client judges dropped targets as surviving while the server deletes them. This feeds the **live save blocker** at [#L623-L627](app/web/static/app.js#L623-L627).
- `confirmScopeLoss` ([#L1115-L1126](app/web/static/app.js#L1115-L1126)) must count **scope targets and `custom_locations` lines** about to be deleted, not only stranded findings — it returns `true` immediately when nothing is stranded, which is why unchecking a channel with 40 targets and no referencing findings is silent today.
- `mobileScopeRule` wiring at [#L1254](app/web/static/app.js#L1254) needs no change — `if (channel === "mobile")` follows the channel list automatically.

**Test:** rewrite [tests/test_browser.py](tests/test_browser.py#L446) to click checkboxes. New: ticking Mobile on a web report adds a Mobile textarea with **no** dialog. New: unticking API with api targets but no referencing findings **does** raise the target-count dialog, and cancelling leaves `scope_targets` untouched. New: unticking a channel that strands a finding blocks the save through `strandedByScopeEdit`. The existing textbox locators at [#L432-L433](tests/test_browser.py#L432-L433) must still pass.

**Invariants protected:** 3, 4. Rule: **widening never warns; narrowing always warns before the server can reject it.**

### Step 6 — Client: the proof-of-concept multi-select

**Files:** [app/web/static/app.js](app/web/static/app.js#L2360-L2388).

- Replace the single-variant banner with a multi-select over the channels `applicablePocVariants` returns — the finding's own affected channels, filtered to those its library entry has steps for.
- **Keep a `pocVariantLabels` map.** `testTypes[variant].label` at [#L2370](app/web/static/app.js#L2370) is an unguarded property access; removing the key while anything still resolves to the old token throws a `TypeError` mid-render.
- The suppression check at [#L2364](app/web/static/app.js#L2364) becomes set logic: offer the **remainder** — channels not already in `poc_variants` and not in `poc_variant_declined` — instead of an all-or-nothing equality test.
- `applyPocVariant` ([#L945-L956](app/web/static/app.js#L945-L956)) merges items into the single existing `numbered_list`, appends to `poc_variants`, and no longer clears `poc_variant_declined` wholesale. **It must keep routing through `remintFragments` ([#L942](app/web/static/app.js#L942))** — that is the only thing preventing duplicate `frag_id`s.
- Stays byte-parallel with its Python twin. **A one-sided change here produces no error at all:** fix Python only and the server installs steps the banner never offered; fix JS only and the banner offers steps the server would not install.

**Test:** extend step 0's `data-poc-offer` test to the multi-select. Assert ticking web + api on one finding yields **one** `numbered_list` containing both step sets, that images survive, and that the resulting draft reloads without a duplicate-`frag_id` error.

**Invariants protected:** 5, 6, 7.

### Step 7 — Stylesheets and the mobile warning

**Files:** [app/web/static/overrides.css](app/web/static/overrides.css), [app/web/static/taste.css](app/web/static/taste.css), [app/web/static/app.js](app/web/static/app.js).

Same commit as steps 5–6 — a `select { width: … }` rule with no `<select>` leaves a silently broken layout.

- **Three stylesheets carry `.test-type-select` rules, not one.** [overrides.css#L38](app/web/static/overrides.css#L38), [#L49-L51](app/web/static/overrides.css#L49-L51) (fixed `select { width:155px }`), [#L347](app/web/static/overrides.css#L347) (mobile breakpoint, `select { width:128px }`); [taste.css#L665](app/web/static/taste.css#L665), [#L672](app/web/static/taste.css#L672), [#L676](app/web/static/taste.css#L676), [#L699-L705](app/web/static/taste.css#L699-L705) (`flex-direction: column` plus `select { width:170px }`). [app.css](app/web/static/app.css#L2) carries `.scope-grid` only and is **not** touched.
- Reuse the existing `.coverage-option` sizing ([overrides.css#L54-L56](app/web/static/overrides.css#L54), [taste.css#L722](app/web/static/taste.css#L722)) rather than inventing new checkbox rules.
- **Ship the mobile warning.** Whenever mobile scope targets exist, surface "Mobile scope will not appear in the generated report." This is a hard requirement of this step, not a follow-up: the template has no mobile scope table ([app/docx_report.py](app/docx_report.py#L375-L383) holds two caption lookups, and `_metadata` at [#L235-L238](app/docx_report.py#L235-L238) has no mobile token), so a tester can otherwise type mobile targets that silently never reach the document.

**Test:** covered by step 5's browser tests plus a visual check. There is no CSS test harness and none is proposed.

### Step 8 — Docs

**Files:** [docs/DATA_MAP.md](docs/DATA_MAP.md), this plan file.

Required by the maintenance contract in the same change, not after it. §6 (field shape), §7 (PoC keyed by `Channel`, `web_api` retired, `poc_variants` plural), §8 (**normalisation moved from `load_path` to a `Report` before-validator *because* `import_report` bypasses `load_path`**), §12 (the twinned-rule table loses `channels_by_type` ↔ `testTypes` and gains the `survivingAfterScopeText` channel filter).

### Deferred, with a defined trigger

**Mobile scope in the generated document.** When the user supplies the updated `.docx` template containing a mobile-captioned scope table: add the third caption lookup in `_populate_scope_tables` ([app/docx_report.py](app/docx_report.py#L375-L383)) and the `prod-mobile` / `non-prod-mobile` tokens in `_metadata` ([#L235-L238](app/docx_report.py#L235-L238)), add a DOCX test, **and delete the step 7 warning in the same change.** The warning is scaffolding with a removal trigger, not a permanent feature.

### Known gaps this change does not close

- **The library ships zero `mobile` proof-of-concept variants** (12 web, 12 api, 0 mobile). A mobile-only finding gets no steps regardless of this work. Authoring them is a content task, not a code one.
- **`affectedChannels` has no test observable of its own.** It is only visible composed with variant resolution through the Content page banner.
- **`repair_duplicate_fragment_ids` persists the raw draft**, so a manager repair leaves `test_type` on disk until the next ordinary save.

### Rollback

Reverting the code restores the `load_path` branch at [app/workspace.py](app/workspace.py#L274-L276), which fires on `"test_type" not in engagement` and reads `tested_channels` — the exact key the new code writes. `["web","mobile"]` collapses to `"mobile"`, `["web","api"]` to `"web_api"`, `["web"]` to `"web"`. **A lossy collapse, not a reset** — which is the strongest argument for having reused the old key name. `draft.bak.json` is never read by `find_path` ([app/workspace.py](app/workspace.py#L249)); a hand-rename back to `draft.json` reintroduces `test_type`, which the before-validator maps correctly, so manual rollback works. Note there is **one save of headroom**: the first save overwrites the backup with pre-migration bytes, the second loses them.

The library JSON has **no** rollback mechanism. Take a copy of [resources/vuln_library.json](resources/vuln_library.json) before step 2.
