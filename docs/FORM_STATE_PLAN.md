# Save State & Autosave — Research + Implementation Plan
### 3-Page Form with Cross-Page Field Dependencies

> **Status: superseded research plan. This is not documentation of the shipped
> app.** It was written before the save system was built, and the
> implementation diverged on most of its concrete technology choices. The
> *principles* in Part 1 were followed; the *stack* in Part 2 was not. Read
> `docs/PLAN.md` § Persistence and safety for what actually ships, and
> `app/web/static/app.js` for the save machine itself.
>
> | This plan says | What shipped |
> |---|---|
> | Alpine.js | no framework; plain DOM + vanilla JS |
> | Bootstrap | hand-written CSS in `app/web/static/styles.css` |
> | IndexedDB draft tier | a local tier was built, but on `localStorage` per-tab envelopes plus `sessionStorage` for the tab id - not IndexedDB, and not the "skip Tier 1" option of § 2.9 either |
> | `BroadcastChannel` multi-tab lock | no cross-tab channel; concurrent writers are resolved server-side by compare-and-swap (HTTP 409) |
> | 400-600 ms debounce | 5000 ms idle autosave (`VULNREPORT_AUTOSAVE_IDLE_MS`), with a 150 ms local-draft debounce |
> | `editing` / `saving` / `saved` / `blocked` | six states: `unsaved`, `saving`, `saved`, `failed`, `conflict`, `recovered` |
> | revision number per snapshot | kept: `saveRevision` vs `savedRevision` |
> | server-side conflict rejection | kept: monotonic `saved_at` compare-and-swap, 409 with `latest_saved_at` |
>
> Kept as-is for the reasoning, which is still the best written record of *why*
> the save system looks the way it does. Do not treat any code sample below as
> reflecting a file in this repository.

---

## Part 1 — Research Summary

### 1.1 Autosave is a state machine, not a timer

The dominant guidance is to stop treating autosave as "debounce + fetch" and model it as an explicit save-state contract. A vague spinner is not enough — the user needs to know whether an edit is local-only, in flight, durably stored, or blocked. The recommended states are `editing` → `saving` → `saved` / `blocked`, with a timestamp on success and a clear recovery action on failure. Critically, the last acknowledged snapshot must be kept **separate** from the current input values, so a slow response never marks newer edits as saved.

### 1.2 Debouncing alone is unsafe

Debounce reduces request volume but does not order writes. The fix is a monotonically increasing revision number (or idempotency key) attached to each snapshot, with either serialized writes or explicit rejection of acknowledgements from older revisions. Otherwise a slow first request can land after — and overwrite — a later edit. Typical debounce windows in production examples sit around 400–600 ms, with cleanup on unmount and abort handling for in-flight requests.

### 1.3 Local durability and server acceptance are different things

The strong recommendation is: **persist locally first, sync later, and show the difference in the UI.** A local draft should exist for every long form so a crash, refresh, or accidental navigation doesn't erase work. The four engine parts of a resilient autosave stack are debounce, a persistent write queue, retries, and offline handling.

### 1.4 Storage mechanism trade-offs

| Store | Persists until | Tab isolated | Size | Best for |
|---|---|---|---|---|
| `localStorage` | manually cleared | No | ~5–10 MB | Long-term drafts |
| `sessionStorage` | tab closes | Yes | ~5–10 MB | Single-session forms |
| IndexedDB | manually cleared | No | Browser-dependent (much larger) | Large / structured / nested data |
| History API state | navigation entry | Yes | Small | SPA back-forward nav |

`localStorage` and `sessionStorage` are synchronous and string-based — every read/write blocks the main thread and needs `JSON.stringify`/`parse`. IndexedDB is asynchronous and stores structured data natively, which matters once drafts include nested objects, evidence/file metadata, or many entries. Writes must be wrapped in `try/catch` to handle `QuotaExceededError` gracefully. IndexedDB data is origin-scoped and can be evicted by the browser unless persistent storage is requested via `navigator.storage.persist()`.

**Security note that applies directly to your use case:** the standing advice is to never write passwords, tokens, or sensitive fields to Web Storage — anything in the origin can read it via XSS. One published ADR went further and rejected client-side draft persistence entirely for a form collecting personal data, on data-residency grounds. Your app is local-only and single-user per machine, which weakens that objection, but **raw request/response evidence containing credentials or session tokens should still not be autosaved to browser storage** — push it to the Python backend on disk instead.

### 1.5 Multi-step forms: centralised state is the decision that determines everything else

Per-step state (each step component owning its own fields) fails immediately: unmounting a step destroys its data, so a user who fills step 3, goes back to step 2, and returns finds step 3 empty. Keeping all steps mounted but hidden avoids the unmount but leaves hidden inputs participating in submission and in the accessibility tree. The correct architecture is a **single store above the step components**, with steps as pure views over shared state.

That store holds:
- `values` — all field data across every step
- `meta` — `visitedSteps`, `touchedFields`, `errors`, `currentStepId`, `submitState`
- `derived` — `stepSequence` (computed from values), `isStepValid`, `canAdvance`, `progressPercent`

### 1.6 Steps are named states, not an integer

Modelling steps as `currentStep = 0,1,2` is described as "an incrementing integer pretending to be a state machine" — any code can set it to any value, and you lose the guarantee that state S is only reachable from state R. The recommendation is a finite state machine: a finite set of named states, an alphabet of events (`NEXT`, `PREVIOUS`, `SUBMIT`, `RETRY`), and an explicit transition function. For moderate complexity, a hand-rolled state machine is explicitly endorsed over pulling in XState — zero dependencies, fully auditable.

### 1.7 Cross-step dependencies and branching

Steps should be modelled **as data** (an array of step configs), not hardcoded markup, so reordering is a one-line change. Branching paths should be driven off *watched field values* so the path **recomputes when an earlier answer changes** — this is exactly the bidirectional-dependency case. Validation strategy: validate only the current step's fields on Next; don't surface errors for fields the user hasn't reached. Two viable models are (a) block advancement on invalid, or (b) allow free movement and flag invalid steps in the indicator — the latter is called out as better for **edit-heavy flows like settings where people revisit**, which matches your report-drafting workflow.

### 1.8 What the research does *not* settle

Nothing in the sources gives a ready-made pattern for **bidirectional** cross-page dependencies (Page 3 feeding back into Page 1). That's the genuinely hard part of your form, and Section 2.4 below is my design proposal, not established guidance.

---

## Part 2 — Implementation Plan

### 2.0 Assumptions

- Local Python backend (single tester per machine), Alpine.js + Bootstrap frontend, no PyInstaller.
- Three pages are **views over one store**, not three separate forms or three separate routes with independent state.
- "Server" below means your local Python process. Network flakiness is near-zero, but process death, browser refresh, and mid-edit navigation are all real.

---

### 2.1 Two-tier persistence

Do not pick one store. Use both, with different jobs:

**Tier 1 — Local mirror (fast, always-on)**
- IndexedDB, one object store `drafts`, keyed by `draftId`.
- Written on every debounced change (~500 ms trailing).
- Purpose: survive refresh, tab close, accidental back-navigation.
- Async and non-blocking, so it won't jank typing on large drafts.

**Tier 2 — Backend draft (durable, canonical)**
- `POST /api/draft/{draftId}` to the Python app, which writes the folder structure you already defined.
- Written on: page transition, explicit Save, idle > 5 s, and `visibilitychange` → hidden.
- Purpose: the real artifact. IndexedDB is a cache, never the source of truth.

**Rule:** Tier 1 write must never be awaited before Tier 2 is scheduled, and Tier 2 failure must never wipe Tier 1.

**Do not persist to IndexedDB:** raw captured requests/responses containing auth headers, cookies, or session tokens. Those go straight to Tier 2 (disk) with a local-only path reference held in the store.

---

### 2.2 The store shape

```js
draft = {
  draftId: "eA_20260910_001",
  schemaVersion: 3,
  revision: 47,              // monotonic, incremented on every committed change
  savedRevision: 44,         // last revision the backend acknowledged
  values: {
    meta:    { appName, ciNumber, bsnNumber, tester, scope },   // Page 1
    findings: [ { id, title, severity, ... } ],                  // Page 2
    summary: { conclusion, envStatement, ... }                   // Page 3
  },
  meta: {
    currentStepId: "findings",
    visitedSteps: ["meta", "findings"],
    touched: { "meta.appName": true },
    errors: {},
    saveState: "editing" | "saving" | "saved" | "blocked",
    lastSavedAt: "2026-09-10T02:14:00+08:00"
  }
}
```

`savedRevision` separate from `revision` is the single most important line in this document. It is what makes "Saved" honest.

---

### 2.3 Step machine (hand-rolled, ~40 lines)

```js
const STEPS = [
  { id: "meta",     label: "Engagement",  validate: validateMeta },
  { id: "findings", label: "Findings",    validate: validateFindings },
  { id: "summary",  label: "Summary",     validate: validateSummary }
];

const TRANSITIONS = {
  meta:     { NEXT: "findings" },
  findings: { NEXT: "summary", PREV: "meta" },
  summary:  { PREV: "findings", SUBMIT: "generating" },
  generating: { DONE: "complete", FAIL: "summary" }
};
```

Navigation is `send("NEXT")`, never `step++`. Because you're in an edit-heavy flow, use the **free-movement** model: the stepper lets the user jump to any visited step, and invalid steps are badged rather than locked. Hard gating only on `SUBMIT`.

---

### 2.4 Cross-page dependencies — the core design

This is the part that will rot if you improvise it. Three mechanisms, in order of preference.

#### (a) Derived fields — one-way, computed, never stored as input
If a value on Page 3 is *always* a function of Page 1/2 values, it is not a field. It's a getter.

```js
get overallSeverity() {
  return maxSeverity(this.values.findings.map(f => f.severity));
}
```
Never write it back into `values`. Never let the user edit it. This eliminates an entire class of desync bugs, and it's free in Alpine because getters re-evaluate reactively.

#### (b) Dependency graph — one-way, with explicit invalidation
For values that are *seeded* from another page but then editable, declare the edges in one place:

```js
const DEPENDS_ON = {
  "summary.envStatement": ["meta.scope"],
  "findings[].remediation": ["findings[].vulnId"],
  "meta.reportTitle": ["meta.appName", "meta.ciNumber"]
};
```

When a source changes:
1. If the dependent field is **untouched** (`meta.touched[path] !== true`) → recompute silently.
2. If the dependent field **has been touched** → do NOT overwrite. Mark it `stale: true` and surface a non-blocking inline notice on that page: *"Scope changed — recompute this?"* with a one-click Recompute.

This is the rule that respects manual edits, which matters because your final report has exactly one intended human touch-up pass.

#### (c) Bidirectional pairs — resolve to a single owner
True two-way dependencies (A affects B *and* B affects A) will cause infinite update loops if implemented naively. Do not implement them as two-way. Instead:

- Identify the **owning field** — the one the user is more likely to consider authoritative.
- The non-owner becomes a derived-or-stale field per (b).
- If the user edits the non-owner, ownership **transfers** to it for the remainder of the session, and the original owner becomes the stale one.

Enforce this with a `writeGuard`: during a dependency-triggered recomputation, set a module-level `isPropagating = true` flag and refuse to enqueue further propagations. Single-pass propagation only — no cascades. If you find you need cascades, that's a signal the field model is wrong, not that you need a smarter propagator.

**Concretely, before you write code, produce this table.** It should be an artifact in the repo:

| Source field | Page | Dependent field | Page | Direction | Owner | On source change |
|---|---|---|---|---|---|---|
| `meta.scope` | 1 | `summary.envStatement` | 3 | one-way | source | recompute if untouched, else flag stale |
| `findings[].severity` | 2 | `summary.riskRating` | 3 | one-way | derived | always recompute (getter) |
| `summary.excludedFindings` | 3 | `findings[].included` | 2 | reverse | last-edited | single-pass propagation |

If a row's Direction is "both," you haven't finished designing it yet.

---

### 2.5 Validation strategy

- **On input:** cheap schema-level checks only (type, required-shape). Never announce an error on every keystroke.
- **On step exit:** full validation of that step's fields; record errors in `meta.errors` but do not block movement.
- **On SUBMIT:** full cross-page validation, including dependency consistency (any field still flagged `stale` blocks generation with a jump-to-field link).
- **Backend is authoritative.** The Python layer re-validates before DOCX generation regardless of what the client said.

---

### 2.6 Save-state UI contract

One small, persistent indicator in the page chrome — not a toast:

| State | Display |
|---|---|
| `editing` | `Unsaved changes` (muted) |
| `saving` | `Saving…` (spinner) |
| `saved` | `Saved 02:14` |
| `blocked` | `Save failed — Retry` (danger, with action) |

Plus a `beforeunload` guard when `revision > savedRevision`.

---

### 2.7 Recovery and conflict

Because a tester may have the app open in two tabs:

- On load, compare IndexedDB `revision` against the backend draft's `revision`.
- Equal → resume silently.
- Local ahead → offer *"Unsaved changes from a previous session — Restore or Discard."* Never auto-apply.
- Backend ahead → the other tab wrote more recently; load backend, keep local copy under `draftId:orphan` for one session.
- Add a `BroadcastChannel` lock so a second tab on the same `draftId` opens read-only with a clear banner. Cheap to add, prevents the ugliest bug class.

---

### 2.8 Build order

1. Store + step machine, no persistence. Prove navigation never loses data.
2. Dependency table filled in and reviewed **before** any propagation code exists.
3. Derived getters (mechanism a) only.
4. IndexedDB Tier 1 + save-state indicator.
5. Backend Tier 2 + revision/`savedRevision` acknowledgement.
6. Mechanism (b): invalidation and stale flags.
7. Mechanism (c): ownership transfer, only for rows that genuinely need it.
8. Recovery, conflict, multi-tab lock.

Steps 1–3 are where the design is proven. If step 6 feels hard, the problem is the dependency table, not the code.

---

### 2.9 Counterpoint worth considering

You may not need Tier 1 at all. Your app is a local Python process on the tester's own machine with sub-millisecond write latency — the network-flakiness argument that justifies IndexedDB drafts in the research doesn't apply. A synchronous `POST` to `localhost` on every debounce would be simpler, keeps one source of truth, and avoids the entire conflict-resolution section (2.7), the storage-security carve-out, and roughly a third of this plan.

The case *against* dropping Tier 1: the Python process can die or be killed mid-session, and a browser refresh during a request loses the in-flight edit. IndexedDB covers that gap.

My call: **build steps 1–3 and 5 first, skip Tier 1, and only add it if you actually observe data loss during testing.** Adding IndexedDB later is a contained change; the store shape above already accommodates it. Adopting it on day one costs you real complexity for a failure mode you may never hit.
