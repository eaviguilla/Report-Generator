# Back to Setup without blockers

## Request

> Allow users to go back to setup page without any blockers as users do not need to have a finding to edit the app or testing details

## Round 1 - Oracle: how it works today

### 1. Which parts of the data layer this touches

**The one handler that owns every Back control.** All Back controls on all three pages share a single listener registered at module scope in [app/web/static/app.js](../../app/web/static/app.js#L793):

```js
document.querySelectorAll(".back-link").forEach(link => link.addEventListener("click", async event => {
  event.preventDefault();
  // Going back is never gated: the tester is on their way to fix the gaps.
  if (!document.querySelector("#editor") && !validateCurrentPage(true)) {
    return;
  }
  if (pendingMutation) await pendingMutation;
  if (await save()) window.location.assign(link.dataset.href);
}));
```

The comment on L795 says "never gated"; the line under it gates. That comment is only true for the Content page.

**Which elements carry `.back-link`:**

| Page | Template | `.back-link` elements |
|---|---|---|
| Setup | page1_setup.html | **none** — stepper steps 2 and 3 are inert `<span aria-disabled="true">`; footer has only `#next` |
| Findings | page2_findings.html | stepper step 1 → `data-href="setup"`, plus footer `Previous: Setup` |
| Content | page2_editor.html | stepper steps 1 and 2, plus footer `Previous: Findings` |

**The difference between Findings and Content.** The discriminator is `document.querySelector("#editor")`:

- Content page root is `<main id="editor">` → truthy → the `&&` short-circuits → **no validation, straight to `save()`**.
- Findings page root is `<main id="setup" data-step="findings">` → `#editor` is null → `validateCurrentPage(true)` runs → **blocked on any incomplete finding**.

There is a **second, independent** reason Content is ungated. `validateCurrentPage` is initialised to `() => true` at L138 and reassigned only at L2083:

```js
validateCurrentPage = root.dataset.step === "setup" ? validateSetupPage : validateFindingsPage;
```

That line lives inside `setup()`, and the entry point at L3075 is `root.id === "setup" ? setup() : continuousEditor();`. The Content page calls `continuousEditor()`, so `validateCurrentPage` there is still the `() => true` default. **Deleting the `#editor` check alone would not change Content's behaviour**, and would not change Setup's either (Setup has no `.back-link`). It would only ungate Findings — which is exactly the requested change.

**What Back does on each page:**

| Page | Validates? | Awaits `pendingMutation`? | Awaits `save()`? | On `save()` false |
|---|---|---|---|---|
| Setup | n/a — no Back control | n/a | n/a | n/a |
| Findings | **yes**, `validateFindingsPage(true)` | yes | yes | stays put, no navigation |
| Content | no (both reasons above) | yes | yes | stays put, no navigation |

**`validateFindingsPage`** ([app/web/static/app.js](../../app/web/static/app.js#L2053)) fails when `!report.vulnerabilities.length` **or** any finding is missing title, likelihood, impact, severity, status, or location. On `reveal` it paints `.validation-error`, force-expands the fold of the first locationless finding, scrolls to it, and sets the save state to "Enter a finding name, complete the highlighted fields, and select or add a location for every finding".

Note the `!report.vulnerabilities.length` clause: **a report with zero findings cannot go Back to Setup either.** That is the exact scenario the user describes.

**Server-side route gates:**

| Route | Gate | Redirect |
|---|---|---|
| `GET /reports/{id}/setup` | **none** ([app/main.py](../../app/main.py#L616)) | — |
| `GET /reports/{id}/findings` | `setup_is_complete` ([app/main.py](../../app/main.py#L627)) | `303 → /setup?incomplete=setup` |
| `GET /reports/{id}/edit` | `setup_is_complete`, then every finding `finding_is_complete` and at least one finding ([app/main.py](../../app/main.py#L636)) | `303 → /setup?incomplete=setup` / `303 → /findings?incomplete=findings` |

### 2. The invariants that constrain it

| Mechanism | Purpose | Load-bearing for not losing edits? |
|---|---|---|
| `if (pendingMutation) await pendingMutation` (L798) | waits for an in-flight evidence upload or library insert, which reach the server outside `save()` | **Yes.** Removing it strands uploads. |
| `if (await save())` (L799) | refuses to navigate on a failed save | **Yes.** The only thing stopping a failed PUT from being navigated away from. |
| `save()` clearing `autoSaveTimer` (L698) | stops a queued debounce firing mid-navigation | **Yes.** |
| `!validateCurrentPage(true)` (L796) | refuses to navigate on an incomplete finding | **No.** Pure workflow policy. |

The gate is in fact **counterproductive** for data safety: returning at L796 skips the `save()` on L799, so a tester who clicks Previous with unsaved edits and an incomplete finding gets no flush at all. Their edits survive only via the autosave timer and `persistLocalDraft`.

**Can an incomplete finding be saved? Yes.** `PUT /reports/{id}` never calls `finding_is_complete`. The only completeness-adjacent refusal is `reconcile_targets`, whose 422 fires only when a *scope-target removal* strands a finding that still points at it. A finding with no title, no severity, and no affected location saves with `200` today. `finding_is_complete` ([app/report_service.py](../../app/report_service.py#L596)) is purely a navigation predicate.

**Not in the map, found by reading source:** `report.scope_text` is seeded inside `setup()` with **no step guard** (L1202), and `setup()` runs on the Findings page too. So a Findings-page PUT **does** carry `scope_text` and **does** run `reconcile_targets`. In practice the text round-trips from `scope_targets`, IDs are reused by value, and nothing is removed — so this does not currently block anything.

**`beforeunload`, `pagehide`, `allowUnsavedUnload`, autosave timer:** none are on the Back path. Back navigates with `window.location.assign` **after** a successful `save()`, at which point `savedRevision >= saveRevision`, so `beforeunload` returns early and `pagehide` is a no-op. They become relevant only if Back is made to navigate **without** awaiting `save()` — then `beforeunload` would start prompting.

### 3. What existing drafts on disk look like

Six `draft.json` files exist under `data/apps`.

| Draft | Findings | Any failing `finding_is_complete`? |
|---|---|---|
| Fragment_Coverage_Demo/…b0867e631235 | 5 | no |
| Northstar_Banking/…0931592e4fdd | 1 | no |
| Northstar_Banking/…84b9ebe1bbdd | 1 | no |
| Vuln_Library_QA…c6ff01abda9e | 14 | no |
| unnamed/…404ecd327eea | **0** | — |
| unnamed/…d96116840c2f | **0** | — |

**0 drafts contain a finding that fails `finding_is_complete`. 2 drafts contain zero findings.** All 21 findings have a non-empty title, all four assessment fields set, and non-empty `target_ids`.

Caveats: `scope_has_location` is a **presence** check on `target_ids`, not a resolution check — a dangling ID would still pass, so this cannot produce a false "incomplete". `draft.bak.json` was not scanned; `docs/plans/retire-scope-mode-all.md` records a backup holding `"target_ids": []`.

**The 2 zero-finding drafts are the real-world instances of the complaint.** On either, opening Findings and clicking Previous: Setup is refused by the `!report.vulnerabilities.length` clause — with nothing to fix and no highlighted field to act on.

### 4. Which rules exist in both Python and JavaScript

| Gate | Python half | JavaScript half | Twinned? |
|---|---|---|---|
| **Back-from-Findings gate** | **none** | `.back-link` handler L793 + `validateFindingsPage` L2053 | **No twin. Client-only.** |
| Back-from-Content gate | none | none (ungated by design) | n/a |
| `#next` forward gate | none directly | L2084 | No — but leads into a twinned server gate |
| Findings-page entry | `setup_is_complete` | `validateSetupPage` | **Yes** |
| Content-page entry | `finding_is_complete` | `validateFindingsPage`, `updateFindingSummary` | **Yes** |
| finding claims a location | `scope_has_location` | `scopeHasLocation` | **Yes** |
| Setup-page entry | none | none | n/a |

**Would client and server disagree after a naive change? No.** The `/setup` route has **no gate at all**. Navigating to `/setup` with an incomplete finding already works today — a tester can type the URL, or hit browser Back, and land on Setup with no resistance. The client-side gate is the *only* thing enforcing this rule anywhere. Both server gates point **forward**, never backward.

Removing the Back call site does not disturb the twinned predicate — `#next` and `updateFindingSummary` still call `validateFindingsPage`, and `/edit` still enforces the Python half.

### 5. Existing tests that encode the current behaviour

**`tests/test_browser.py::test_invalid_findings_block_navigation_but_content_allows_back`** (L906):

| Line | Assertion |
|---|---|
| L907 | `ready_report()` — setup complete, **no findings** |
| L910 | clicks "Add finding" → one **blank** finding exists |
| L913 | `previous.get_attribute("href")` **is None** — asserts the control is a `<button>`, not an `<a>` |
| L914-916 | **middle-click** does not open Setup in a new tab; URL still `/findings` |
| L918-920 | ordinary click on `Previous: Setup` leaves the URL on `/findings` — **the core assertion the request would invert** |
| L921 | `#finding-validation-note` is visible |
| L923-925 | `Next: Content` is also refused — **forward** gate, unaffected |
| L927-932 | Content page: `Previous: Findings` **does** navigate |

Lines L913-L920 would need to change. L923-L932 should survive untouched.

**Other tests that touch Back, but assert something else — all must keep passing:**

- `test_previous_saves_before_library_replacement_and_next_navigation` (L827) — aborts the PUT, clicks `Previous: Findings`, asserts the URL is still `/edit`. **This is the `if (await save())` half.**
- `test_leaving_a_page_mid_upload_keeps_the_screenshot` (L570) — delays the evidence POST, clicks Previous mid-flight, asserts the upload survives. **This is the `await pendingMutation` half.**
- `test_evidence_upload_preserves_pending_content` (L512) — uses Previous as a flush mechanism, not as a subject.

**Server-side gate tests (forward only — none assert Back):** `test_workflow_routes_enforce_setup_and_finding_gates` (tests/test_app.py L402) asserts the PUTs all return **200** with findings in varying states, corroborating that incomplete findings save fine. `test_a_library_finding_still_needs_an_affected_location` (L1411) asserts `/edit` returns 303.

## Round 1 - Planner: proposal and open questions

### Correction to the oracle brief — settled by the coordinator

The planner challenged oracle finding #2. **The planner is right.** Coordinator verified directly at [app/web/static/app.js](../../app/web/static/app.js#L2738):

```js
validateCurrentPage = reveal => {
  const issues = updateReadinessPanel();
  if (!issues.length) return true;
  if (reveal) {
    const firstIssue = document.querySelector("#editor-notifications [data-review-finding]");
    firstIssue?.click();
    firstIssue?.focus({preventScroll:true});
  }
  return false;
};
```

`validateCurrentPage` is reassigned a **second** time at L2738, inside `continuousEditor()` — the Content page path — to a readiness validator that returns `false` whenever the Content page has generation issues. The oracle's claim that it "is reassigned ONLY at L2083" is false.

Consequences:

- On Content, `validateCurrentPage` is **not** `() => true`. It is a real validator with **zero readers**, because the `#editor` clause short-circuits before it is called. A write-only dead assignment.
- Deleting *only* the `!document.querySelector("#editor") &&` clause **does not fix Findings** (`validateFindingsPage` still refuses) **and newly gates Content** on readiness issues, breaking [tests/test_browser.py](../../tests/test_browser.py#L927).
- [docs/DATA_MAP.md](../../docs/DATA_MAP.md) repeats the same wrong claim and needs correcting whether or not this ships.
- The file is a non-strict IIFE, so localising `validateCurrentPage` into `setup()` without also deleting L2738 would silently create a global rather than throw. The two edits are coupled.

### Decisions on A–F

**A — Delete the whole guard, not the `#editor` check.** Remove L796-798 entirely. The `#editor` probe is the *only* thing suppressing the L2738 validator; it is not a redundant spelling of "am I on Content".

**B — Yes, Back must still flush; the oracle is right.** Keep `await pendingMutation` and `if (await save())`. Verified that `save()`'s two refusal guards are fenced behind `root.dataset.step === "setup"` (L679, L683) and the Findings page carries `data-step="findings"`. **No data is at risk; one class of data loss is removed.**

**C — Rewrite the comment, don't delete it.** Replace with one true of all three pages: `// Back is never gated; completeness is a forward requirement, and the flush below is what protects the edits.`

**D — Silent, and it already is, for free.** `#finding-validation-note` renders only when `findingBody.dataset.validationAttempted === "true"`, set only by `validateFindingsPage(true)` (L2062) and the `?incomplete=findings` bounce (L625). With the Back call site gone, Back neither reveals nor hides it. No replacement signal needed.

**E — One assertion inverts; four survive.** See Plan step 3.

**F — Forward path untouched.** `#next` keeps calling `validateCurrentPage(true)`, `validateFindingsPage` is not edited, no Python changes. The change is to one call site, not a predicate.

### Blast radius

| File | Change | Twin? |
|---|---|---|
| [app/web/static/app.js](../../app/web/static/app.js#L795) | Delete guard L796-798; rewrite comment L795 | None — client-only rule, no Python half |
| [app/web/static/app.js](../../app/web/static/app.js#L138) | *(optional, q1)* Delete `let validateCurrentPage = () => true;` | — |
| [app/web/static/app.js](../../app/web/static/app.js#L2083) | *(optional, q1)* Make assignment a `const` local to `setup()` | — |
| [app/web/static/app.js](../../app/web/static/app.js#L2738) | *(optional, q1)* Delete the dead write-only assignment; keep `updateReadinessPanel` and its `reportchange` listener | — |
| [tests/test_browser.py](../../tests/test_browser.py#L906) | Reorder and invert one assertion; rename the test | — |
| [tests/test_browser.py](../../tests/test_browser.py) | New test: zero-finding report reaches Setup | — |
| [docs/DATA_MAP.md](../../docs/DATA_MAP.md) | Rewrite the **Back** bullet; wrong today, wronger after | Required by the maintenance contract |
| `app/main.py`, `app/report_service.py`, `app/models.py` | **No change** | — |
| [app/web/templates/page2_findings.html](../../app/web/templates/page2_findings.html) | **No change** — stays a `<button>`, which keeps middle-click inert | — |

### Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write | **clear** | No new mutation path, no new field. Back already reached `save()` on its success path; the change widens *when* it is reached. A 409 still lands in `markSaveConflict`, still returns `false`, still refuses navigation. |
| Lost update | **clear** | Zero server-side change. Every write still goes through `PUT /reports/{id}` under `Workspace._locked`. |
| Orphan reference | **clear** | Nothing deleted; no `frag_id`, `evidence_id` or `target_ids` created, moved or dropped. Empty `target_ids` is an absence, not a dangling reference, and already saves 200. |
| Silent stranding | **RISK** | This is the requested behaviour stated plainly: a tester may leave Findings with a zero-location finding and see no warning at that moment. Mitigations all pre-existing: `updateFindingSummary` still counts it, `#next` still refuses, `/edit` still bounces, `strandedByScopeEdit` is Setup-only and unaffected. Accept knowingly. |
| Schema break | **clear** | No field added, removed or retyped. Every `draft.json` loads unchanged; no migration needed. |
| Request/response asymmetry | **clear**, reasoned | Findings *does* send `scope_text` and *does* run `reconcile_targets`, so its 422 is reachable. But that 422 fires only on scope-target **removal**, and Findings has no scope inputs — the value round-trips unchanged. Same PUT already fires on every Findings autosave. New *moment*, not new *shape*. |
| Rule drift | **clear**, drift *decreases* | The removed rule is client-only with no Python twin. Today the client blocks Back to `/setup` while the route serves it happily to a typed URL — the client is stricter than the server. Removing the call site closes that gap. |
| Navigation trap | **RISK** (residual, deliberate) | The change *fixes* the main trap. It introduces none — `save()`'s refusals are fenced to `data-step="setup"`, and a tester can only be on `/findings` if setup was already complete. **Residual:** `await save()` still pins the tester when the save genuinely fails (409/422/5xx). "Without any blockers" is not literally achieved, deliberately. |
| Derived-state fight | **clear** | No ownership changes. The PUT goes through the same `applyCanonicalReport` reconciliation, so `provision_report` wins the same arguments. |
| Backup exhaustion | **clear** | `save()` early-returns without a PUT when nothing is pending. With edits pending it writes **once** — and today's blocked path never calls `save()`, so `clearTimeout(autoSaveTimer)` never runs and the debounce fires anyway. Net writes same or lower. |

### Plan (Round 1 draft)

1. **Delete the guard.** Remove L796-798, rewrite the L795 comment. *Test:* `test_previous_saves_before_library_replacement_and_next_navigation` and `test_leaving_a_page_mid_upload_keeps_the_screenshot` must pass unmodified. *Invariant:* Back never navigates without a successful flush, never abandons an in-flight upload.
2. **Correct the data map** in the same change, per the maintenance contract.
3. **Rewrite the browser test.** Reorder so the forward-gate block runs *before* the Back click, proving Back navigates in the exact state the old gate cared about. One assertion inverts (L918-920 → `wait_for_url(".../setup")`); L913, L914-916, L921, L923-925, L927-932 survive. Add an on-disk assertion that the blank finding was flushed.
4. **Add the zero-findings test** — a report with no findings at all, straight to Previous: Setup. This is the actual complaint.
5. **Optional collapse** (only if Option A chosen), as a separate commit after 1-4 are green.

### Open questions

1. **Collapse the dead `validateCurrentPage` machinery in the same change, or leave it?** Option A collapses (delete L138, `const` at L2083, delete L2738-2746) — one validator, one owner, no shared mutable global; cost is touching `continuousEditor` and discarding unreachable reveal behaviour. Option B ships the three-line deletion alone — smaller diff, but a write-only global that *looks* like it gates Content survives, which is how this area got mis-documented. **Planner recommends A; default B.**
2. Whether the new zero-findings test belongs in `test_browser.py` or as a cheaper non-browser test.

### What the planner would not do

- **Would not make Back navigate without awaiting `save()`.** It drops the only thing stopping a failed PUT being navigated away from; `beforeunload` would start prompting on every Back; and it breaks the two tests that exist to pin this.
- **Would not delete only the `#editor` clause.** Leaves Findings gated and newly gates Content.
- **Would not add a "you have incomplete findings" confirm dialog.** A blocker wearing a politer hat.
- **Would not add a server-side gate to `/setup` for symmetry.** Gates point forward; a backward gate creates the redirect loop the data map warns about.

## Round 2 - Oracle: verdict on the proposal

**Verdict: approve, with three corrections to the document, none to the design.**

### 1. Risk rows

**All six named mechanisms verified CONFIRMED:**

- `markSaveConflict` exists at [app/web/static/app.js](../../app/web/static/app.js#L424); the 409 branch at L718-721 returns `false`, which reaches L800 and refuses navigation. There is also a front-door short-circuit at L676: `if (saveConflict) return false;`.
- The two refusal guards are fenced exactly as claimed, L679-687: `if (root.dataset.step === "setup" && !validateSetupInputs(false))` and `const stranded = root.dataset.step === "setup" ? strandedByScopeEdit() : [];`. On Findings `root.dataset.step` is `"findings"`, so neither fires.
- `strandedByScopeEdit` is **safer than the planner realised**: it defaults to `() => []` at L137 and its only assignment at L1407 sits inside `if (configuration && windows && scopeGrid) {` (L1254). `#scope-grid` exists only in the Setup template, so on Findings the binding stays `() => []`. Doubly closed — never assigned *and* never called.
- Early return confirmed at L678: `if (!pendingSave || savedRevision >= saveRevision) return true;`
- `applyCanonicalReport` at L698 is inside the only `PUT /reports/{id}` site in the file, so every save path reconciles identically.
- **Setup cannot go stale after arrival** — the oracle checked the case the planner did not. `setup_issues` reads only engagement fields and `scope_targets`; the Findings template carries no `[data-path]` inputs and no `#scope-grid`; the single client write to `report.scope_targets` (L1374) is inside the Setup-only block. No Findings edit can invalidate Setup.

**Three rows have wrong reasoning (verdicts all stand):**

**A. Silent stranding — mitigation list WRONG.** `updateFindingSummary` early-returns at L1639: `if (findingBody.dataset.validationAttempted !== "true") return;`. That flag is written in exactly **one** place, L2062, inside `validateFindingsPage(reveal=true)`. Today, clicking Back *is* what sets it for a tester who has not pressed Next. After the change nothing on the Back path sets it, so the "N findings are incomplete" line never appears for that tester. The planner's claim that the `?incomplete=findings` bounce also sets it is **false** — L627-632 only unhides the note and sets its text; the *setup* branch at L620-624 sets `validationAttempted` but on `#setup-validation-note`, a different element. **Surviving mitigations are only `#next` refusing and `/edit` bouncing.** The accepted risk is larger than the row describes.

**B. Backup exhaustion — reasoning WRONG twice.** `clearTimeout(autoSaveTimer)` is at **L688, not L698**. More substantively the argument is fragile; the real fact is `queueBackendSave` (L274-279) has **no page gate and no completeness gate**, plus `visibilitychange` → hidden calls `save()` at L843. The incomplete finding is already being written today. Conclusion `clear` is correct; premise should be replaced.

**C. Request/response asymmetry — one premise WRONG.** `reconcile_targets` has a **second** 422 at [app/report_service.py](../../app/report_service.py#L472): `"select at least one app type"`, surfaced as `invalid_scope`. It cannot fire from a Findings edit because channels are not editable there, so the verdict holds but the reason was incomplete. Also unnamed: L524-529 *prunes* `custom_locations` outside coverage on any save carrying `scope_text` — already happening on every Findings autosave, unchanged by this proposal.

**D. Navigation trap — one clause wrong, the oracle's own.** Setup was never back-gated: [app/web/templates/page1_setup.html](../../app/web/templates/page1_setup.html#L12) has no `.back-link`. The earlier report and the data map both implied otherwise. Verdict unaffected.

**Rows correctly `clear`, no disagreement:** lost update, schema break, derived-state fight, stale write. **Orphan reference** confirmed at source — `Scope.target_ids` defaults to `[]` and the check at [app/models.py](../../app/models.py#L355) is vacuously true for an empty set. **Rule drift decreases** confirmed — what is deleted is a client-only *application* of the twin predicate to a transition the server has never gated.

**One residual the planner did not name:** `beforeunload` (L837-842) prompts when `saveRevision > savedRevision`. If Back fires while a save is already in flight, L677 returns the older in-flight promise, which can resolve `true` while a newer revision is pending — then `location.assign` runs and the native "Leave site?" prompt can appear. **Not new** — reachable today from Content and from a complete Findings page. The change only widens which report states can reach it.

### 2. Files missed

| Check | Verdict |
|---|---|
| Other callers of `validateCurrentPage` | **CONFIRMED — none.** Five occurrences total: L138 declaration, L796 read, L2083 `setup()` assignment, L2086 `#next` read, L2738 `continuousEditor()` assignment. After deleting L796-798 the sole reader is L2086, inside `setup()` alongside both validators — so Option A's `const` localisation is sound. |
| Other readers of `#finding-validation-note` / `validationAttempted` | **CONFIRMED — none left inconsistent** (the page unloads on the new success path), though see row A above |
| Stepper `aria-disabled` / class state | **CONFIRMED — no template change needed.** Findings step 1 is `class="step complete back-link"` with no `aria-disabled`; the only `aria-disabled="true"` is step 3, the *forward* gate. Note Findings has **two** `.back-link` elements (stepper step 1 and the footer); both ungate together. |
| Other breaking tests | **CONFIRMED — none.** `"Previous: Setup"` occurs exactly once in `tests/`, at L912. Every other Previous click is `"Previous: Findings"` on `/edit` where `#editor` exists. No test references `validateCurrentPage`. |
| ROUTES.md / FORM_STATE_PLAN.md / FORM_DEPENDENCIES.md | **CONFIRMED — none need updating.** ROUTES.md already says "Server-side gates control workflow entry; disabled buttons are only a UI affordance", which this change makes *more* accurate. |
| Sibling plan docs | **MISSED — cosmetic.** `keyboard-save-and-undo.md`, `retire-scope-mode-all.md`, `scope-app-type-checkboxes.md` cite `app.js` line numbers that shift by three after the deletion, more under Option A. Historical records, not a maintenance contract. |

**The test claim is WRONG as stated.** The planner said "exactly one assertion inverts (L918-920) … L921 survives". [tests/test_browser.py](../../tests/test_browser.py#L921) is `assertFalse(page.locator("#finding-validation-note").is_hidden())`. In the **current order** it runs *after* the Back click; once Back navigates to `/setup` that element does not exist, `is_hidden()` returns `True`, and the assertion fails. **L921 survives only under the reorder the planner also proposes.** Ship them as one coupled edit, not two independent claims.

### 3. Effect on existing `draft.json`

**CONFIRMED — no draft on disk is affected, and nothing new is persisted.**

Disk state re-verified: six drafts, two with `"vulnerabilities": []`, no `"target_ids": []` and no null/empty assessment fields across the other four.

**Nothing moves from memory to disk that was not already going there** — this is the load-bearing answer. `queueBackendSave` calls `save()` whenever `pendingSave` is set, with no page gate and no completeness gate, on the 5000 ms `autoSaveDelay`. `visibilitychange` → hidden calls `save()` directly. Neither consults `validateCurrentPage`. **The Back gate refused navigation, never persistence** — an incomplete finding typed on Findings is PUT to disk today within one debounce interval whether or not the tester clicks anything.

The PUT body is byte-identical: `clone(report)`, the same object regardless of call site. The only delta is **timing** — the write moves earlier by at most one debounce interval. Zero-finding drafts survive Back: `reconcile_targets` accepts an empty list, produces no `removed_references`, `Report.model_validate` passes, 200.

### Oracle's three required corrections

1. **Silent-stranding mitigation column** — remove `updateFindingSummary`, or qualify it as "only after a prior Next attempt", and drop the false claim that the `?incomplete=findings` bounce sets `validationAttempted`.
2. **Backup-exhaustion reasoning** — replace with `queueBackendSave` having no page gate; fix `clearTimeout(autoSaveTimer)` to L688.
3. **Test plan** — state plainly that the reorder is **required**, not optional, because L921 fails without it.

## Round 2 - Planner: revised plan

All three oracle corrections folded in. **No design change** — only the write-up moved.

### What remains on the data map

The oracle already corrected section 10 and the "Last verified" line **on disk** as a side effect of its review. That correction describes *today's* behaviour. Still outstanding and belonging to this change:

1. Rewrite the Back bullet for **post-change** behaviour: Back awaits `pendingMutation` and navigates only if `await save()` returned true, on all three pages, with no completeness check anywhere.
2. Rewrite the `validateCurrentPage` paragraph. Under Option B: two live states, sole reader is `#next` inside `setup()`, and the `continuousEditor()` readiness assignment now has *zero* readers rather than being suppressed by a DOM check. Under Option A it collapses to one sentence.
3. Prepend a new "Last verified" sentence — this time code changed, so it must say what shipped.

### Corrected data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write | **clear** | No new mutation path, no new field. PUT body is `clone(report)` regardless of call site. A 409 still lands in `markSaveConflict`, returns `false`, refuses navigation at L800; `if (saveConflict) return false;` at L676 keeps it refused thereafter. |
| Lost update | **clear** | Zero server-side change. Every write goes through `PUT /reports/{id}` under `Workspace._locked`. |
| Orphan reference | **clear** | Nothing deleted, nothing created. Empty `target_ids` is an absence — the check at [app/models.py](../../app/models.py#L355) is vacuously true for an empty set, and such a report already saves 200. |
| Silent stranding | **RISK — larger than first described** | `updateFindingSummary` does **not** survive as a mitigation. It early-returns at L1639 unless `findingBody.dataset.validationAttempted === "true"`, and that flag has exactly one writer: L2062 inside `validateFindingsPage(reveal=true)`. Today the refused Back click is what sets it for a tester who has not pressed Next; after this change nothing on the Back path does. The `?incomplete=findings` bounce does not set it either — L627-632 only unhides the note and writes a fixed sentence, while the branch that *does* set a flag (L620-624) writes it on `#setup-validation-note`, a different element. **Surviving mitigations are exactly two:** `#next` refusing and revealing (L2086 → L2062), and `GET /edit` bouncing. The incomplete reveal becomes tied exclusively to forward intent. See Question 2. |
| Schema break | **clear** | No field added, removed or retyped. Every `draft.json` loads unchanged. No migration. |
| Request/response asymmetry | **clear** | Findings *does* send `scope_text` (seeded L1202, no step guard), so `reconcile_targets` runs and **both** its 422s are nominally reachable — the stranded-finding refusal and `"select at least one app type"` at [app/report_service.py](../../app/report_service.py#L472). Neither can fire from a Findings edit: no scope inputs, so `scope_text` round-trips with IDs reused by value; no channel controls, so the app-type list is never emptied. The `custom_locations` pruning at L524-529 already runs on every Findings autosave. New *moment*, not new *shape*. |
| Rule drift | **clear — drift decreases** | The deleted rule is client-only with no Python twin. Today the browser refuses Back to `/setup` while the route serves that URL to anyone who types it. Removing the call site closes the gap; the twinned predicate is untouched. |
| Navigation trap | **RISK (residual, deliberate)** | Removes the main trap. Introduces none — `save()`'s refusal guards at L679-687 are fenced behind `root.dataset.step === "setup"` and Findings carries `data-step="findings"`. **Residual:** `await save()` still pins the tester when the save genuinely fails (409/422/5xx). |
| Derived-state fight | **clear** | No ownership changes. Same `applyCanonicalReport` reconciliation at L698, the only PUT site in the file. |
| Backup exhaustion | **clear** | Corrected premise: `queueBackendSave` (L274-279) has **no page gate and no completeness gate**, and `visibilitychange` → hidden calls `save()` at L843. The incomplete finding is **already written to disk today** on the 5000 ms cadence; only the timing shifts earlier by at most one debounce. `clearTimeout(autoSaveTimer)` is at **L688** (L698 is `applyCanonicalReport`), so one Back click produces one PUT and cancels the pending debounce. Net writes same or fewer. |
| **Residual (named, pre-existing): `beforeunload` on a concurrent save** | **not new, not introduced** | `beforeunload` (L837-842) prompts when `saveRevision > savedRevision`. If Back fires while a save is in flight, L677 returns the *older* promise, which can resolve `true` while a newer revision is pending — `location.assign` runs and the native "Leave site?" prompt can appear. Reachable today from Content and from a complete Findings page. Named so it is not mistaken for a regression during testing. |

### The test reorder is mandatory, not stylistic

L921 is `assertFalse(page.locator("#finding-validation-note").is_hidden())`. In the current order it runs *after* the Back click. Once Back navigates to `/setup` the element does not exist, `is_hidden()` returns `True`, and it **fails**. It survives only if moved to sit after the `#next` refusal — which is where it now belongs, since `#next` → `validateFindingsPage(true)` is the sole path that sets `validationAttempted`. **Inversion and reorder are one coupled edit.**

New order:

1. `ready_report()`, `/findings`, **Add finding** → one blank finding.
2. `previous` — assert `get_attribute("href") is None`; middle-click; URL still `/findings`. *(unchanged)*
3. Click **Next: Content**; URL still `/findings`; **then** assert `#finding-validation-note` visible. *(L921 relocated)*
4. Click `previous`; `wait_for_url(".../setup")`. *(the inverted assertion)*
5. Read the draft off disk, assert the blank finding is present. **Corroborating only** — the 5000 ms autosave could satisfy it for the wrong reason on a slow run; the durable proof of the flush invariant is the Content-page test in step 1.
6. Content block unchanged, against its own `ready_report(include_finding=True)`.

Rename to `test_findings_gate_blocks_next_but_back_is_never_refused`.

**On the second `.back-link`:** Findings has two — stepper step 1 and the footer button, both `data-href="setup"`. `get_by_role("button", name="Previous: Setup")` selects the footer. Both are wired by the same `querySelectorAll(".back-link").forEach(...)` with an identical handler, so clicking one exercises both. Only the template attachment can regress independently — assert `nav.stepper .back-link` resolves to one element rather than doing a second navigation round-trip.

### Revised steps

Steps 1 and 2 are **one commit** — the code change inverts an assertion, so the suite is red between them if split.

1. **Delete the guard.** [app/web/static/app.js](../../app/web/static/app.js#L795): remove L796-798 in full, rewrite the L795 comment. *Test:* `test_previous_saves_before_library_replacement_and_next_navigation` and `test_leaving_a_page_mid_upload_keeps_the_screenshot` pass **unmodified**. *Invariant:* Back never navigates without a successful flush and never abandons an in-flight upload.
2. **Rewrite the browser test** with the reorder as part of the step. *Invariant:* the forward gate still refuses and still reveals.
3. **Add the zero-findings test.** Must be a browser test — the rule exists only in JavaScript and `/setup` has no server gate to assert against. *Invariant:* a report with no findings can always reach Setup.
4. **Finish the data map** — the three outstanding edits above.
5. **Optional collapse** (only if Q1 = Option A), separate commit after 1-4 are green.

### Decision on the sibling plan docs

**Do not touch them.** `keyboard-save-and-undo.md`, `retire-scope-mode-all.md` and `scope-app-type-checkboxes.md` cite `app.js` line numbers that shift by three, but they are dated records of past reasoning, not a maintenance contract. DATA_MAP itself says line numbers are hints and function names are the durable identifier.

## Answers

**Q1 — collapse the dead `validateCurrentPage` machinery?**
> **Clean it up, in the same commit as the fix.**

Chosen over the planner's recommendation of a separate follow-up commit. The collapse ships together with the Back fix rather than behind it.

**Q2 — accept a quieter Findings page, or keep the incomplete count visible?**
> **Also fix the bounce message, in this change.**

So the `?incomplete=findings` branch gains the `validationAttempted` flag, turning the static sentence *"Add at least one complete finding before continuing to Content."* into the live count that names the missing fields and hides itself as they are filled. This fixes a pre-existing defect adjacent to the change rather than a consequence of it.

**Implementation detail verified by the coordinator:** `findingBody` is declared at [app/web/static/app.js](../../app/web/static/app.js#L1578) as `const findingBody = document.querySelector("#findings")`, inside `setup()`. The `?incomplete=` branch at L625-631 runs at module scope, long before that. So the bounce fix must issue its own `document.querySelector("#findings")` — it cannot reuse `findingBody`. Ordering is safe: the module-scope branch runs first and sets the attribute, then `setup()` runs and `updateFindingSummary` reads it.

## Agreed plan

Deleting the completeness check from the shared `.back-link` click handler in `app/web/static/app.js`, so Previous: Setup from the Findings page always navigates — including from a report with zero findings, which is the actual complaint. Two of the six drafts on disk are in exactly that state.

**Scope:** JavaScript, tests and docs only. No Python, no templates, no schema, no migration. `app/main.py`, `app/report_service.py` and `app/models.py` are untouched. `GET /reports/{id}/setup` already has no gate, so the client is merely being brought into line with a route that already serves this.

**The two guarantees that must survive:** `await pendingMutation` (waits for in-flight evidence uploads and library inserts, which reach the server outside `save()`) and `if (await save())` (refuses to navigate on a failed PUT). Both stay. The gate being deleted is not load-bearing for data — worse, it currently `return`s *above* the `save()` call, so a tester clicking Previous with unsaved edits and an incomplete finding gets no flush at all. Removing it makes the flush strictly more reliable.

### Step 1 — Delete the Back guard and collapse the dead validator

**Files:** [app/web/static/app.js](../../app/web/static/app.js#L795) — delete L796-798 in full and rewrite the L795 comment, which currently claims "never gated" while the line below it gates. Then delete `let validateCurrentPage = () => true;` at L137, make the L2083 assignment a `const` local to `setup()`, and delete the write-only readiness assignment at L2738-2746 — keeping `updateReadinessPanel` and its `reportchange` listener at L2747, which have other callers.

Delete the **whole** guard, not just the `!document.querySelector("#editor") &&` clause. That clause is the only thing suppressing the readiness validator at L2738; removing it alone would leave Findings gated *and* newly gate Content.

**Test:** `test_previous_saves_before_library_replacement_and_next_navigation` and `test_leaving_a_page_mid_upload_keeps_the_screenshot` must pass **unmodified** — they are the regression guards for the two kept lines.

**Invariant:** Back never navigates without a successful flush and never abandons an in-flight upload. `#next` keeps validating on both Setup and Findings through the new local binding.

### Step 2 — Make the Content bounce show a live count

**Files:** [app/web/static/app.js](../../app/web/static/app.js#L625) — in the `routeGate === "findings"` branch, set `data-validation-attempted` on the `#findings` element via its own `document.querySelector("#findings")`.

**Test:** a browser test that reaches `/edit` with an incomplete finding, follows the bounce to `/findings`, and asserts the summary names the missing field rather than the fixed sentence.

**Invariant:** the reveal is triggered by forward intent only — pressing Next, or being bounced by the Content route. Back never triggers it and never suppresses it.

### Step 3 — Rewrite the existing browser test

**Files:** [tests/test_browser.py](../../tests/test_browser.py#L906). Rename to `test_findings_gate_blocks_next_but_back_is_never_refused`.

**The reorder is mandatory, not stylistic.** L921 asserts `#finding-validation-note` is visible and currently runs *after* the Back click. Once Back navigates to `/setup` that element does not exist, `is_hidden()` returns `True`, and it fails. Inversion and reorder are one coupled edit.

New order: add a blank finding → assert Previous has no `href` and middle-click is inert → click **Next**, assert it is refused, **then** assert the validation note is visible → click Previous, `wait_for_url(".../setup")` → read the draft off disk and assert the blank finding is present → Content block unchanged.

The on-disk assertion is **corroborating only**; the 5000 ms autosave could satisfy it for the wrong reason on a slow run. The durable proof of the flush invariant is the Content-page test named in step 1.

Findings has **two** `.back-link` elements — stepper step 1 and the footer button, both `data-href="setup"`. They share one handler, so clicking one exercises both; only the template attachment can regress independently. Assert `nav.stepper .back-link` resolves to one element rather than doing a second navigation round-trip.

**Invariant:** the forward gate still refuses and still reveals; Back navigates in exactly the state the old gate cared about.

### Step 4 — Add the zero-findings test

**Files:** [tests/test_browser.py](../../tests/test_browser.py). `ready_report()` with no findings, go to `/findings`, click Previous: Setup, `wait_for_url` on `/setup`.

Must be a browser test — the rule being removed exists only in JavaScript, and `/setup` has no server gate to assert against.

**Invariant:** a report with no findings can always reach Setup.

### Step 5 — Finish the data map

**Files:** [docs/DATA_MAP.md](../../docs/DATA_MAP.md). Section 10 and its "Last verified" line were already corrected on disk during the review, describing *today's* behaviour. Outstanding: rewrite the Back bullet for post-change behaviour, collapse the `validateCurrentPage` paragraph to one sentence naming a single validator local to `setup()`, and prepend a new "Last verified" entry saying what shipped.

Required by the maintenance contract, since this touches the navigation path in `app.js`.

**Invariant:** the map describes the shipped behaviour, not the reviewed behaviour.

### Accepted risks

- **Silent stranding.** A tester may leave Findings with a zero-location finding and get no warning at that moment. Step 2 restores the signal for testers bounced back from Content; for a tester who simply clicks Back, the reveal is deferred until they press Next. Nothing is permanently hidden. `#next` still refuses and `/edit` still bounces.
- **Back can still be refused by a genuinely failing save** (409, 422, 5xx). "Without any blockers" is therefore not literally achieved, deliberately — that refusal is the only thing preventing a failed PUT from being navigated away from.
- **Pre-existing, named so it is not mistaken for a regression:** `beforeunload` prompts when `saveRevision > savedRevision`. If Back fires while a save is in flight, L677 returns the older in-flight promise, which can resolve `true` while a newer revision is pending, and the native "Leave site?" prompt can appear. Reachable today from Content and from a complete Findings page; this change only widens which report states can reach it.

### Explicitly rejected

- **Navigating without awaiting `save()`** — the literal reading of "no blockers". Drops the only protection against navigating away from a failed PUT, makes `beforeunload` prompt on every Back, and breaks two tests that exist to pin this.
- **Deleting only the `#editor` clause** — reads like the minimal fix, is neither minimal nor a fix.
- **A "you have incomplete findings, continue?" confirm** — a blocker wearing a politer hat.
- **A server-side gate on `/setup` for symmetry** — every gate in this app points forward; a backward gate builds the redirect loop the data map warns about.
- **Chasing line numbers through the sibling plan docs** (`keyboard-save-and-undo.md`, `retire-scope-mode-all.md`, `scope-app-type-checkboxes.md`) — their `app.js` citations shift, but they are dated records, not a maintenance contract, and the map itself says line numbers are hints while function names are durable.

