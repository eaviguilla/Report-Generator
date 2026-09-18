# Keyboard save and undo

> **Status:** shipped · 2026-09-15 · `f49d503`

## Request
ctrl + s and ctrl + z functions for this app

## Round 1 - Oracle: how it works today

# Keyboard save and undo: what exists today

## 0. The headline

**Ctrl/Cmd+Z and Ctrl/Cmd+Shift+Z already work.** A document-level `keydown` listener at [app.js#L770-L774](../../app/web/static/app.js#L770-L774) binds undo and redo globally on all three report pages:

```js
document.addEventListener("keydown", event => {
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== "z") return;
  event.preventDefault();
  if (event.shiftKey) redo(); else undo();
});
```

There is **no** Ctrl/Cmd+S binding, and **no** Ctrl+Y alias for redo. A search for modifier-key handling across the static scripts returns only this listener and the Shift-Tab focus trap in the dialog helper. So the work is: add save, optionally add the Ctrl+Y alias, and decide what to do about the problems the existing undo binding already has (section 4).

---

## 1. The save path in the browser

### `save(successStatus)`

Declared `async` at [app.js#L620](../../app/web/static/app.js#L620). It resolves to a **boolean**, except on the coalescing branch where it returns the in-flight promise, which itself resolves to a boolean. Callers always `await` it.

Five guard clauses run before anything is sent, in this order:

| Line | Guard | Returns |
|---|---|---|
| [L621](../../app/web/static/app.js#L621) | `saveConflict` is set | `false`, silently, nothing sent |
| [L622](../../app/web/static/app.js#L622) | `saveInFlight` is non-null | the existing promise — a second call never issues a second PUT |
| [L623](../../app/web/static/app.js#L623) | `!pendingSave \|\| savedRevision >= saveRevision` | `true` — "nothing to save" is success |
| [L624-L627](../../app/web/static/app.js#L624-L627) | Setup page only: `validateSetupInputs(false)` fails | `false`, button relabelled "Correct invalid Setup fields" |
| [L628-L632](../../app/web/static/app.js#L628-L632) | Setup page only: `strandedByScopeEdit()` non-empty | `false`, button relabelled "Give X another affected location" |

Only after all five does it `clearTimeout(autoSaveTimer)` at [L633](../../app/web/static/app.js#L633). **A save refused by a guard leaves the autosave debounce armed** — the timer is cancelled on the sending path, not at function entry.

The send itself is an IIFE assigned to `saveInFlight` at [L634-L671](../../app/web/static/app.js#L634-L671). It sets `SAVING`, then runs a `while (savedRevision < saveRevision)` loop: capture `revision`, clone the report, `PUT /reports/{reportId}` with the whole document as the body, throw on a non-OK response, `applyCanonicalReport(sentReport, saved.report)`, re-baseline `previousReport` **only when no text transaction is open** ([L644](../../app/web/static/app.js#L644)), then `savedRevision = revision`. If edits landed during the request the loop runs again and the button stays `SAVING`; otherwise it clears `pendingSave`, calls `clearLocalDraft()`, clears a stale `save_report` diagnostic, resets `saveRetryCount`, and settles the button. `finally` nulls `saveInFlight` at [L670](../../app/web/static/app.js#L670).

Failure handling at [L662-L669](../../app/web/static/app.js#L662-L669): a 409 routes to `markSaveConflict` and returns `false`; anything else forces `pendingSave`, persists the local draft, shows `FAILED`, and — for a network error or 5xx — schedules an exponential-backoff retry via `queueBackendSave(autoSaveDelay * 2 ** (saveRetryCount - 1))`, capped at `maxSaveRetries = 3` ([L106-L107](../../app/web/static/app.js#L106-L107)).

The `successStatus` parameter keeps the button in `SAVING` with a caller-supplied label instead of settling to `SAVED` — used by the library insert ("Adding...", [L1801-L1802](../../app/web/static/app.js#L1801-L1802)) and the evidence upload ("Uploading...", [L1934](../../app/web/static/app.js#L1934)).

### `scheduleSave()` and the debounce

`scheduleSave` at [app.js#L589-L618](../../app/web/static/app.js#L589-L618) has two branches. When the focused element is the same one that owns the open text transaction ([L592](../../app/web/static/app.js#L592)), it bumps `saveRevision`, marks pending, requeues both timers, and returns — **no undo entry is created**. Otherwise it finalizes any open transaction, diffs `previousReport` against `report`, and on a non-empty diff pushes a new undo action, trims to `maxHistoryEntries`, clears the redo stack, opens a fresh transaction if a text field is focused, and re-baselines.

`queueBackendSave(delay = autoSaveDelay)` at [L259-L265](../../app/web/static/app.js#L259-L265) is a plain restartable `setTimeout` that fires `if (pendingSave) void save()`. `autoSaveDelay` is `Math.max(100, ... || 5000)` at [L99](../../app/web/static/app.js#L99) — 5000 ms idle by default, overridable by `window.VULNREPORT_AUTOSAVE_IDLE_MS` for tests.

### `setSaveState` and `SAVE_STATES`

`SAVE_STATES` is frozen at [L112-L119](../../app/web/static/app.js#L112-L119): `unsaved`, `saving`, `saved`, `failed`, `conflict`, `recovered`. `setSaveState(state, label)` at [L205-L224](../../app/web/static/app.js#L205-L224) is the only writer of `#save-button`. It returns early when the button is absent, writes `dataset.saveState`, the visible text, `disabled = state === SAVED`, `aria-live="polite"`, `aria-busy`, and a `title` carrying the full save timestamp. The initial call is [L225](../../app/web/static/app.js#L225).

**`#save-button` is disabled whenever the state is `saved`** — a keyboard handler that simply dispatches `.click()` on it is a no-op in exactly the case where a no-op is correct, but the behaviour is incidental, not designed.

### Dirty tracking

Three module-level values, [L103-L105](../../app/web/static/app.js#L103-L105):

- `pendingSave` — a boolean "there is something to send"
- `saveRevision` — incremented on **every** edit, on conflict resolution ([L431](../../app/web/static/app.js#L431)), in `restoreHistory` ([L498](../../app/web/static/app.js#L498)), and on draft recovery ([L792](../../app/web/static/app.js#L792))
- `savedRevision` — the highest revision the server has acknowledged

"Dirty" is expressed two ways: `pendingSave && savedRevision < saveRevision` in the generate handler ([L709-L710](../../app/web/static/app.js#L709-L710)) and error recovery ([L454](../../app/web/static/app.js#L454)), and `saveRevision > savedRevision` alone in the unload prompt ([L783](../../app/web/static/app.js#L783)).

### The existing button handler is not just `save()`

[L691-L702](../../app/web/static/app.js#L691-L702) does three things `save()` does not:

1. If `dataset.action === "resolve"` it focuses `#app-diagnostics` and returns — it does not attempt a save during a conflict.
2. On Setup it runs `validateSetupInputs(**true**)` — reveal mode, which paints `.validation-error`, scrolls to and focuses the first offender.
3. It resets `saveRetryCount` so a manual save restarts the backoff budget.

A Ctrl+S binding that calls `save()` directly would skip all three.

---

## 2. Undo and redo

### The stacks

`undoHistory` and `redoHistory` are declared at [L80-L87](../../app/web/static/app.js#L80-L87) and **rehydrated from `sessionStorage`** on load, keyed `vulnreport-history:{reportId}` ([L37](../../app/web/static/app.js#L37)). A parse failure clears the key. `maxHistoryEntries = 20` ([L79](../../app/web/static/app.js#L79)). There is a real redo stack, not a single level.

An action is `{changes}`, where `changes` comes from `diff` at [L457-L468](../../app/web/static/app.js#L457-L468) — a recursive key-wise diff producing `{path, beforePresent, before, afterPresent, after}` entries. Arrays are deliberately excluded from the "both objects" test at [L459](../../app/web/static/app.js#L459), so any array change is recorded as one whole-array replacement. `applyChanges(target, changes, direction)` at [L469-L479](../../app/web/static/app.js#L469-L479) replays in reverse, reading the `before` side for `"undo"` and the `after` side for `"redo"`, deleting the key when the chosen side is absent.

### The baseline and the transaction

`previousReport = clone(report)` at [L88](../../app/web/static/app.js#L88) is the undo baseline. It is re-cloned after an action is captured ([L610](../../app/web/static/app.js#L610)), after a transaction finalizes ([L529](../../app/web/static/app.js#L529)), after each settled PUT when no transaction is open ([L644](../../app/web/static/app.js#L644)), and twice inside `restoreHistory` ([L495](../../app/web/static/app.js#L495), [L501](../../app/web/static/app.js#L501)).

`activeTextTransaction` at [L89](../../app/web/static/app.js#L89) is `{input, before, action}`. `before` is a clone of `previousReport` taken when the transaction opened; `action` is the object **already pushed onto `undoHistory`**, so finalizing mutates a stack entry in place rather than pushing a new one.

`finalizeTextTransaction()` at [L521-L531](../../app/web/static/app.js#L521-L531) recomputes `action.changes = diff(activeTextTransaction.before, report)`, splices the action out of `undoHistory` when the net diff is empty, nulls the transaction, re-baselines, and persists. It is called from four places: the `focusout` microtask ([L582-L586](../../app/web/static/app.js#L582-L586)), `scheduleSave` when nothing text-like is focused ([L601](../../app/web/static/app.js#L601)), the top of `undo` ([L748](../../app/web/static/app.js#L748)), and `pagehide` ([L779](../../app/web/static/app.js#L779)). `redo` does **not** call it.

`activeTextEntry()` at [L577-L580](../../app/web/static/app.js#L577-L580) is what decides "is a text field focused": any `input` that is not checkbox/radio/file, any `textarea`, or any `[contenteditable="true"]`.

**One focused field is one undo step.** Every keystroke in a field takes the early branch of `scheduleSave` and never pushes an action; the whole editing session collapses into the single action opened at the first keystroke.

### The restore and the reload

`restoreHistory(action, direction)` at [L492-L520](../../app/web/static/app.js#L492-L520) is the shared engine. It applies the change, re-baselines, drops any open transaction, forces `pendingSave` and bumps `saveRevision`, then attempts three persistence steps — `persistLocalDraft()`, `storeHistory()`, and `sessionStorage[recoverySelectionKey] = localDraftKey`. **Any one of them failing triggers `rollback()`** ([L500-L506](../../app/web/static/app.js#L500-L506)), which reverses the change, restores the prior `pendingSave`, and returns `false`.

On success it sets `allowUnsavedUnload = true` and returns `save().then(() => { window.location.reload(); return true; })` at [L513-L519](../../app/web/static/app.js#L513-L519). **Every undo and every redo ends in a full page reload.** The resolved value of that save is not inspected — a refused save reloads anyway, and the undone state is recovered from `localStorage` on boot because `recoverySelectionKey` was pointed at it ([L65-L73](../../app/web/static/app.js#L65-L73), landing in the `recoveredDraft` branch at [L791-L795](../../app/web/static/app.js#L791-L795)).

### The handlers

- `undo` — [L747-L757](../../app/web/static/app.js#L747-L757): finalize, `undoHistory.pop()`, push onto `redoHistory`, await `restoreHistory(action, "undo")`, and reverse the stack move if it returned falsy.
- `redo` — [L758-L767](../../app/web/static/app.js#L758-L767): the mirror image, minus the finalize.
- `updateHistoryControls()` — [L480-L485](../../app/web/static/app.js#L480-L485): disables `#undo-button`/`#redo-button` by stack length. Called from `storeHistory` ([L488](../../app/web/static/app.js#L488)) and once at [L775](../../app/web/static/app.js#L775).
- `storeHistory()` — [L486-L491](../../app/web/static/app.js#L486-L491): writes both stacks to `sessionStorage` and returns `false` on quota failure, which is what feeds the rollback.
- Click bindings — [L768-L769](../../app/web/static/app.js#L768-L769). Keyboard binding — [L770-L774](../../app/web/static/app.js#L770-L774).

---

## 3. Every existing keyboard listener

| Location | Bound to | Keys claimed | Notes |
|---|---|---|---|
| [app.js#L186-L199](../../app/web/static/app.js#L186-L199) | the library search `input`, via `wireLibraryCombobox` | ArrowDown, ArrowUp, Enter, Escape | Enter calls `stopImmediatePropagation()` when an option is active |
| [app.js#L770-L774](../../app/web/static/app.js#L770-L774) | `document`, bubble phase | **Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z** | ignores Alt; `preventDefault()` fires regardless of focus |
| [app.js#L1703](../../app/web/static/app.js#L1703) | Findings row title `input` | Escape | clears the per-row library results |
| [app.js#L1826-L1831](../../app/web/static/app.js#L1826-L1831) | `#search` on Findings | Escape | clears the library results list |
| [app.js#L2687](../../app/web/static/app.js#L2687) | editor finding-title `input` | Enter, Escape | Enter commits the rename |
| [dialog.js#L70-L85](../../app/web/static/dialog.js#L70-L85) | `document`, **capture** phase, only while a dialog is open | Escape, Tab, Shift+Tab | registered at [L88](../../app/web/static/dialog.js#L88), removed on settle at [L52](../../app/web/static/dialog.js#L52) |
| [manager.js#L83-L86](../../app/web/static/manager.js#L83-L86) | the rename `input` on the home page | Enter, Escape | `manager.js` never loads alongside `app.js` |

`theme.js`, `diagnostics.js`, and the library editor script have no key handling at all.

**The collision that matters today:** the dialog's capture-phase handler does not call `stopPropagation()` for anything except its own Escape and Tab cases. So while a confirmation dialog is open, Ctrl+Z still reaches the app.js listener, undoes a report-level action, and reloads the page out from under the dialog. A Ctrl+S binding added at the same level would behave the same way. Both should either register in the capture phase ahead of the dialog, or check for an open dialog before acting.

Nothing existing claims **S** or **Y**, so those two additions collide with no in-app handler. Ctrl/Cmd+S must call `preventDefault()` to suppress the browser's own Save Page As.

---

## 4. Rich text and native undo

`rich(runs, onChange, includeToolbar, placeholder)` at [app.js#L825-L839](../../app/web/static/app.js#L825-L839) builds a `<div class="rich" contenteditable="true" role="textbox" aria-multiline="true">` and seeds it with HTML generated from the stored runs.

It uses `document.execCommand` in two places:

- the bold/italic/underline toolbar buttons — [L830](../../app/web/static/app.js#L830)
- paste, which is intercepted and re-issued as plain text — [L831](../../app/web/static/app.js#L831)

Input capture is a plain `input` listener at [L832](../../app/web/static/app.js#L832): `resize()` then `onChange(runsFrom(input))`. There is **no** `beforeinput` handler and **no** key handler on the editor. `runsFrom` at [L800-L813](../../app/web/static/app.js#L800-L813) walks the DOM, folds `b`/`strong`, `i`/`em`, `u` into run flags, merges adjacent identical runs, and trims whitespace-only runs at the edges.

Because typing and both `execCommand` calls go through the browser's native editing pipeline, each contenteditable maintains its own native undo stack. **Today that stack is unreachable.** Pressing Ctrl+Z inside a `.rich` field: the document listener fires, `preventDefault()` cancels native undo, the app undoes the last recorded *report-level* action, and the page reloads — destroying the DOM the native stack lived in.

The same is true inside every `<textarea>` and `<input>`:

| Control | Element | Line |
|---|---|---|
| scope text per channel | `textarea` | [L1357](../../app/web/static/app.js#L1357) |
| custom location entry | `textarea` | [L1637](../../app/web/static/app.js#L1637) |
| per-target location value | `textarea` | [L1682](../../app/web/static/app.js#L1682) |
| numbered/bulleted list items | `textarea` | [L2203](../../app/web/static/app.js#L2203) |
| table cell | `textarea` | [L2255](../../app/web/static/app.js#L2255) |
| code block | `textarea` | [L2330](../../app/web/static/app.js#L2330) |
| instance title | `input` | [L2330](../../app/web/static/app.js#L2330) |

Compounding it: while a field is focused its transaction stays open and `scheduleSave` pushes nothing ([L592-L599](../../app/web/static/app.js#L592-L599)), and `undo` finalizes that transaction before popping ([L748](../../app/web/static/app.js#L748)). So Ctrl+Z in a half-typed paragraph discards **the entire editing session in that field**, not the last word — and then reloads.

Whatever is decided for Ctrl+S, this is the part of the existing Ctrl+Z behaviour most likely to surprise a tester.

---

## 5. Pages and state

`app.js` is loaded by exactly three templates, always last and always after `diagnostics.js`, `theme.js`, `dialog.js`:

- [page1_setup.html#L12](../../app/web/templates/page1_setup.html#L12)
- [page2_findings.html#L6](../../app/web/templates/page2_findings.html#L6)
- [page2_editor.html#L3](../../app/web/templates/page2_editor.html#L3)

The home page loads `manager.js`; the library editor loads its own script. Neither has undo, redo, or a report save. The IIFE bails at [app.js#L2-L3](../../app/web/static/app.js#L2-L3) when there is no `main[data-report]`.

**All three report pages render all three buttons.** `#undo-button`, `#redo-button` inside `.history-controls`, and `#save-button`, are in the header markup of [page1_setup.html#L3](../../app/web/templates/page1_setup.html#L3), [page2_findings.html#L3](../../app/web/templates/page2_findings.html#L3), and [page2_editor.html#L3](../../app/web/templates/page2_editor.html#L3). So a keyboard binding needs no per-page conditional.

Page dispatch is a single ternary at [app.js#L2884](../../app/web/static/app.js#L2884): `root.id === "setup" ? setup() : continuousEditor();`. Setup and Findings both use `<main id="setup">` and are told apart by `data-step` (`"setup"` at [page1_setup.html#L4](../../app/web/templates/page1_setup.html#L4), `"findings"` at [page2_findings.html#L4](../../app/web/templates/page2_findings.html#L4)). The editor's `<main id="editor">` carries **no** `data-step`, so every `root.dataset.step === "setup"` test is false there.

Consequence: the two Setup-only guards inside `save()` are inert on Findings and Content. A keyboard save behaves differently per page purely through those guards.

`saveConflict` ([L109](../../app/web/static/app.js#L109)) is set by `markSaveConflict` at [L409-L451](../../app/web/static/app.js#L409-L451), which also forces `pendingSave`, persists the local draft, sets `#save-button dataset.action = "resolve"`, switches to `CONFLICT`, and opens a diagnostics panel offering *Save my version* (adopt `latest_saved_at`, bump the revision, re-save) and *Load latest* (clear the draft and history, set `allowUnsavedUnload`, reload). Cleared only by `clearSaveConflict` at [L404-L408](../../app/web/static/app.js#L404-L408).

**While a conflict is unresolved, a keyboard save that calls `save()` directly is a silent no-op** — the [L621](../../app/web/static/app.js#L621) guard returns `false` with no feedback. Routing through the button handler at least moves focus to the panel holding the resolution choices.

---

## 6. Data-layer constraints a keyboard trigger must respect

**Flush-before-navigate.** Next at [app.js#L1893-L1901](../../app/web/static/app.js#L1893-L1901) validates the page, awaits `pendingMutation`, awaits `save()`, and navigates only if `#save-button`'s `data-save-state` reads `saved`. Back at [L738-L745](../../app/web/static/app.js#L738-L745) awaits `pendingMutation` then navigates only on a truthy `save()`. `pendingMutation` ([L674-L682](../../app/web/static/app.js#L674-L682)) covers library inserts and evidence uploads, which reach the server outside the ordinary save.

**`pagehide`** at [L776-L781](../../app/web/static/app.js#L776-L781): returns immediately unless `pendingSave`, then clears the autosave timer, finalizes the open transaction, and writes the local draft synchronously.

**`beforeunload`** at [L782-L787](../../app/web/static/app.js#L782-L787): returns when `allowUnsavedUnload` is set or `saveRevision <= savedRevision`; otherwise persists the draft and prompts.

**`visibilitychange`** at [L788-L790](../../app/web/static/app.js#L788-L790): hidden plus `pendingSave` forces `void save()`.

**The local draft** lives in `localStorage["vulnreport-pending:{reportId}:{tabId}"]` ([L36](../../app/web/static/app.js#L36)) as the envelope written by `persistLocalDraft` at [L241-L254](../../app/web/static/app.js#L241-L254) — `{schemaVersion, reportId, tabId, baseSavedAt, capturedAt, editRevision: saveRevision, report}`. Queued at 150 ms ([L256-L258](../../app/web/static/app.js#L256-L258)) and removed only by a fully settled save ([L648](../../app/web/static/app.js#L648)).

**The canonical merge after save** is `applyCanonicalReport` at [L398-L403](../../app/web/static/app.js#L398-L403), which reconciles `report`, `previousReport`, **and** `activeTextTransaction.before` against the server's response before `applyServerMetadata`. This is why `previousReport` is not re-baselined while a transaction is open ([L644](../../app/web/static/app.js#L644)) — doing so would strand the transaction's `before` snapshot against a newer baseline.

**On the server**, `save_report` at [main.py#L645-L700](../../app/main.py#L645-L700) compares the body's `saved_at` against `prior.saved_at` and returns 409 before doing any work ([L652-L660](../../app/main.py#L652-L660)); runs `reconcile_targets` ([L662](../../app/main.py#L662)) with a 422 `referenced_scope_removed` when a finding would be stranded; overwrites `report_id` and `app_id` from the prior record ([L674-L675](../../app/main.py#L674-L675)); re-runs `setup_input_issues` ([L678-L685](../../app/main.py#L678-L685)); derives `app_id` when still `unnamed` ([L686-L687](../../app/main.py#L686-L687)); runs `provision_report` ([L688](../../app/main.py#L688)); and takes the lock for a second `saved_at` check inside `save_if_current` ([L691](../../app/main.py#L691)).

The practical upshot for a keyboard shortcut: **a PUT is never cheap.** It can rename the report folder, rebuild `scope_targets` from `scope_text`, and seed fragments. That is already true of the autosave and the button, so the requirement is only that a keyboard save must not fire more often than a button press would, and must not run concurrently with an existing save. The `saveInFlight` guard at [L622](../../app/web/static/app.js#L622) already provides the second half; key auto-repeat from a held Ctrl+S is the case to think about for the first.

---

## 7. Rules that exist in both Python and JavaScript

Undo and redo have **no Python counterpart**. `undoHistory`, `redoHistory`, `diff`, `applyChanges`, `restoreHistory`, and `finalizeTextTransaction` are client-only, and their result rides the ordinary PUT like any other edit.

Save does touch paired rules, through the two guards inside `save()`:

| Rule | Python | JavaScript | Where the keyboard path touches it |
|---|---|---|---|
| per-field character sets and wording | `setup_input_issues`, `CHARACTER_NAMES` | `characterRule` ([L1018](../../app/web/static/app.js#L1018)), `setupRules` ([L1032-L1041](../../app/web/static/app.js#L1032-L1041)) | `validateSetupInputs` at [L624](../../app/web/static/app.js#L624), server re-check at [main.py#L678](../../app/main.py#L678) |
| username shape | `USERNAME_PATTERN` | `setupRules.username` | same guard |
| test window start ≤ end | `TestWindow.validate_order` | `validateDateOrder` | same guard |
| which targets survive a scope-text edit | the target loop in `reconcile_targets` | `survivingAfterScopeText`, `scopeTextStrandedFindings` ([L1233](../../app/web/static/app.js#L1233), assigned to `strandedByScopeEdit` at [L1240](../../app/web/static/app.js#L1240)) | the stranding guard at [L628](../../app/web/static/app.js#L628); server half is the 422 at [main.py#L667-L673](../../app/main.py#L667-L673) |

**No new rule needs a twin, provided the shortcuts route into the existing `save()`, `undo()`, and `redo()` and re-implement none of these gates.** A binding that inlined its own "is it safe to save" test would create a third copy of a rule that already exists twice.

---

## Invariants in play

- **`saveInFlight` coalescing.** Break it and two PUTs race; the second carries the `saved_at` the first is about to invalidate, and the tester gets a spurious 409.
- **`saveRevision` / `savedRevision` ordering.** `savedRevision` must only ever be set to a revision the server confirmed. Set it optimistically and the unload prompt and the Next gate both go quiet while work is unsaved.
- **One field, one transaction.** `activeTextTransaction.action` is already on `undoHistory`. Push a second action for the same field and the stack grows one entry per keystroke, blowing the 20-entry cap in a sentence.
- **`previousReport` is re-baselined only when no transaction is open.** Violating this leaves `activeTextTransaction.before` describing a state that no longer precedes the transaction, so the finalized diff contains changes the tester did not make in that field.
- **`restoreHistory` rolls back on any storage failure.** The change is applied to `report` first; if the rollback path is skipped, a failed `sessionStorage` write leaves an undone report with no record of the undo.
- **`saved_at` is the only concurrency token.** A save that omits it, or sends a stale one, is rejected twice — once before validation and once under the lock.
- **Navigation only proceeds from a settled save.** Next reads `data-save-state`, not the boolean, so anything that writes that attribute out of band can let a page transition escape with unsaved work.

## Both-sides warning

Four rules in the save path are implemented in both Python and JavaScript and must change together if touched: the Setup character-set and username rules, the test-window date order, Setup completeness, and scope-target survival. Adding keyboard bindings does not require editing any of them — but any change that reshapes `save()`'s guard clauses does.

## Map drift

Corrected in [docs/DATA_MAP.md](../DATA_MAP.md):

- **Section 9** listed only `serverReport`, `previousReport`, and `activeTextTransaction.before` as client state, and mentioned undo only in a parenthetical. It never recorded `undoHistory`, `redoHistory`, their `sessionStorage` home, the 20-entry cap, the redo-stack clearing, the one-field-one-step transaction model, or the existing Ctrl/Cmd+Z binding. An "Undo and redo" subsection now covers all of it.
- **Section 10** stated that "every transition is a full page load via `window.location.assign`". It omitted `restoreHistory`, which is a fifth navigation path: it reloads via `window.location.reload()` after awaiting a save, ignores that save's result, sets `allowUnsavedUnload`, and relies on the recovery-selection key to re-adopt the undone draft. Added.

One precision note not worth a map edit: section 10 says "`save()` clears the autosave timer first", which is true of the sending path but not of function entry — a save refused by one of the five guard clauses leaves the debounce armed.

## Round 1 - Planner: proposal and open questions

# Keyboard save and undo — proposed change

*Six decisions are open; they are listed in section 5.*

## Understanding

Add a Ctrl/Cmd+S binding that produces exactly the same outcome as pressing the Save button — including the conflict routing, the reveal-mode Setup validation, and the retry-budget reset that the button handler performs and `save()` does not. Repair the Ctrl/Cmd+Z binding that already exists so that it no longer destroys a tester's in-progress typing and reloads the page when they meant to undo one word. Add no new persisted state, no new endpoint, and no new rule that would need a Python twin.

---

## 1. Blast radius

| File | What changes | Why |
|---|---|---|
| [app.js](../../app/web/static/app.js) | Extract the body of the `#save-button` click handler at [L691-L702](../../app/web/static/app.js#L691-L702) into a named `requestManualSave()`; rebind the button to it | The three things the handler does beyond `save()` — conflict routing, reveal-mode validation, `saveRetryCount = 0` — must be shared, not duplicated |
| [app.js](../../app/web/static/app.js) | Rewrite the document `keydown` listener at [L770-L774](../../app/web/static/app.js#L770-L774): add `s`, add an open-dialog guard, add an `event.repeat` guard, scope `z` by `activeTextEntry()`, optional `y` | One listener, one place to reason about modifier keys |
| [app.js](../../app/web/static/app.js) | Re-entrancy guard around `undo` / `redo` at [L747-L767](../../app/web/static/app.js#L747-L767) | Both are `async` and end in `window.location.reload()`; a keyboard makes double-fire trivial in a way a button click did not |
| [dialog.js](../../app/web/static/dialog.js) | **No change** | The backdrop already carries `data-dialog` at [L15-L16](../../app/web/static/dialog.js#L15-L16), so app.js can detect an open dialog with a DOM probe; exposing `openDialog` through `window.vrDialog` would add public API for nothing |
| [manager.js](../../app/web/static/manager.js) | **No change** | The home page never loads app.js, has no report and no save path. Ctrl+S there falls through to the browser, which is correct |
| [page1_setup.html](../../app/web/templates/page1_setup.html), [page2_findings.html](../../app/web/templates/page2_findings.html), [page2_editor.html](../../app/web/templates/page2_editor.html) | `title` / `aria-keyshortcuts` on `#undo-button` and `#redo-button` only | The header block is copied into all three templates, not shared. The **save** button's `title` is owned by `setSaveState` at [L205-L224](../../app/web/static/app.js#L205-L224) and would be overwritten, so a save hint belongs in app.js, not in markup |
| [tests/test_browser.py](../../tests/test_browser.py) | New Playwright cases (named per step in section 3) | Every behaviour here is browser-side; there is no Python surface to unit-test |
| [docs/DATA_MAP.md](../DATA_MAP.md) | The section 9 sentence asserting the keydown listener "calls `preventDefault()` regardless of focus, so native undo is suppressed" becomes false; section 9 also needs the new Ctrl+S entry point into `save()` | The map is the contract for how data moves; a stale sentence there is worse than no sentence |
| [app.css](../../app/web/static/app.css) | Only if open question 5 resolves toward a visible pulse on the save button | Default answer is no change |
| **Server: none** | `app/main.py`, `app/report_service.py`, `app/workspace.py`, `app/models.py`, `app/storage.py` untouched | No new field, no new route, no new validation. This is why no rule needs a Python/JavaScript twin |

---

## 2. Data risks

| Failure mode | Verdict | Reasoning and what handles it |
|---|---|---|
| Stale write | `clear` | No new mutation path. Ctrl+S routes into the existing `save()`, which PUTs the whole document carrying the `saved_at` that `applyCanonicalReport` last installed. The shortcut changes *when* an existing write happens, never *what* it carries |
| Lost update | `clear` | Server untouched; no read-then-write is added on either side. The browser's read-modify-write is `save()` itself, already serialised by `saveInFlight` |
| Orphan reference | `clear` | Nothing here creates or deletes a `frag_id`, `evidence_id`, or `scope.target_ids` entry. Undo/redo already replay whole-document diffs and the PUT still runs `validate_references` server-side |
| Silent stranding | `RISK` | A finding left with zero locations is caught by the stranded-scope guard at [L628-L632](../../app/web/static/app.js#L628-L632), which only *relabels the button*. If the tester is at the bottom of a long Setup page the button is off-screen and Ctrl+S looks dead. Handled by routing through `requestManualSave()`, which runs `validateSetupInputs(true)` — reveal mode scrolls to and focuses the first offender. A Ctrl+S that called `save()` directly would re-open this hole |
| Schema break | `clear` | Nothing persisted changes shape: not `draft.json`, not the `vulnreport-history:{reportId}` sessionStorage payload. No `load_path` repair, no migration step, and an existing draft loads unchanged |
| Request/response asymmetry | `clear` | No field is added to the request or expected in the response |
| Rule drift | `RISK` | Two ways to drift. First, writing a bespoke "is it safe to save?" test inside the key handler would create a **third** copy of the Setup character-set, username, date-order and scope-survival rules that already exist in Python and JavaScript. Handled by having the shortcut call the shared function and re-implement no gate. Second, the map sentence describing unconditional `preventDefault()` becomes wrong the moment text-field scoping lands. Handled by editing the map in the same change, not afterwards |
| Navigation trap | `RISK` | Not from save — a blocked Ctrl+S simply does not navigate. From **undo**: `restoreHistory` at [L492-L520](../../app/web/static/app.js#L492-L520) ends in `window.location.reload()` after awaiting a save whose result it never inspects. If the undone state no longer satisfies the current page's entry gate, the tester is bounced. That is pre-existing, but a repeating key makes it reachable by accident rather than by a deliberate click. Handled by the `event.repeat` guard plus the undo/redo re-entrancy guard; not otherwise addressed here |
| Derived-state fight | `clear` | A PUT re-derives `scope_targets` from `scope_text`, seeds fragments and can rename the report folder — but Ctrl+S sends exactly what the 5-second autosave would have sent, so `provision_report` gets no new opportunity to overwrite anything. The re-baseline suppression at [L644](../../app/web/static/app.js#L644) already refuses to move `previousReport` while a text transaction is open, so a save fired mid-typing does not corrupt the pending undo entry. The *consequence* of a mid-typing save is a focus problem, not a data one — see the last row |
| Backup exhaustion | `RISK` | There is one `draft.bak.json` slot, and "press Ctrl+S right after the autosave fired" is precisely a double write. Three gates already contain it: `saveInFlight` at [L622](../../app/web/static/app.js#L622) returns the running promise instead of issuing a second PUT; the nothing-to-save guard at [L623](../../app/web/static/app.js#L623) short-circuits a Ctrl+S that follows a settled save; and the new `event.repeat` guard stops a held key from queueing bursts. The proving test counts PUTs, not clicks |
| Key auto-repeat / double-fire | `RISK` | The current listener has **no** repeat guard, so holding Ctrl+Z today pops one action per repeat, each applying a diff, writing sessionStorage and scheduling a reload — several actions vanish on one intent. For save the damage is bounded by `saveInFlight`, but for undo it is not. Handled by `event.preventDefault()` first, then `if (event.repeat) return;`, plus a promise guard in `undo`/`redo` because those are `async` and two *distinct* keypresses can interleave during the save round-trip that precedes the reload |
| Focus-context correctness | `RISK` | Three parts. (a) Ctrl+S with focus in a text field runs `applyCanonicalReport`, which can rewrite the value of the field being typed in — canonical scope targets, a renamed engagement — and drop the caret. The Save button has the same exposure, but the keyboard invites it mid-sentence. Needs a test that asserts focus and selection survive. (b) With a confirmation dialog open, the capture-phase handler at [dialog.js#L70-L85](../../app/web/static/dialog.js#L70-L85) only claims Escape and Tab and does not stop propagation, so Ctrl+Z reaches app.js, undoes a report-level action and reloads the page while the modal's promise is still unsettled — the caller's continuation never runs. Handled by an early return when `[data-dialog]` is present. (c) The library combobox claims only arrows, Enter and Escape, so `s` reaches the document; saving during a library search is harmless |
| Open transaction at save time | `clear` (but worth stating) | `save()` does not call `finalizeTextTransaction()`. A Ctrl+S with a field focused persists the text to the server yet leaves the undo entry open, so a subsequent Ctrl+Z reverts that field to its state when focus entered it — *including work already saved*. That is the existing one-field-one-step model, unchanged by this work, and it is the strongest argument for section 4's recommendation |

---

## 3. Proposal

### 3.1 How Ctrl+S dispatches

**Extract, do not `.click()`, and do not call `save()` directly.**

Pull the body of the click handler at [L691-L702](../../app/web/static/app.js#L691-L702) into `requestManualSave()` and bind both the button and the shortcut to it. The three behaviours it owns are exactly the ones a tester needs from a keyboard save:

1. conflict routing — focuses `#app-diagnostics` instead of firing a save that the `saveConflict` guard would swallow silently;
2. `validateSetupInputs(true)` — paints, scrolls to and focuses the first invalid field, rather than only relabelling an off-screen button;
3. `saveRetryCount = 0` — a deliberate save restarts the backoff budget, which is the whole point of a manual save after a failure.

Rejected alternatives: `document.querySelector("#save-button")?.click()` works today only because the button is `disabled` exactly when there is nothing to save, which is incidental rather than designed — it makes the keyboard path depend on a DOM attribute whose meaning could change. Calling `save()` directly re-opens the silent-stranding and navigation-feedback holes in the risk table.

### 3.2 Behaviour in each state

| State when Ctrl+S is pressed | What happens |
|---|---|
| `unsaved` | `requestManualSave()` runs; button goes `saving` then `saved`. Identical to a click |
| `saved` (button disabled) | `preventDefault()` still fires so the browser's Save Page As never appears; `save()` returns `true` at [L623](../../app/web/static/app.js#L623) without a PUT. Nothing visible happens, which is correct — there is nothing to save |
| `failed` | Retry budget resets and a fresh PUT is attempted. This is the case where a keyboard save earns its keep |
| `conflict` unresolved | Focus moves to `#app-diagnostics` and its *Save my version* / *Load latest* choices. No PUT is attempted, and — unlike a bare `save()` — the tester sees why |
| Dialog open | `preventDefault()` to suppress the browser dialog, then return. The modal is the only thing the tester should be acting on, and its answer may itself mutate the report |
| Setup page, invalid or stranded | Reveal-mode validation scrolls to and focuses the offender; no PUT |

### 3.3 Auto-repeat

Order inside the listener: match the combo, `event.preventDefault()`, then `if (event.repeat) return;`, then act. `preventDefault` must come **before** the repeat bail, otherwise the second repeat of a held Ctrl+S opens the browser's save dialog. `saveInFlight` is the backstop, not the fix — it prevents a second PUT but not a second entry into the guard chain, and it does nothing at all for undo.

### 3.4 Ctrl+Y

**Yes.** One extra branch in the same listener, gated by the same dialog / repeat / text-field logic. Nothing in the app claims `y`, and it is the Windows redo convention that testers will try. On macOS `Cmd+Shift+Z` remains the idiomatic path; both simply call `redo()`.

### 3.5 Feedback

**No new UI surface.** The save button already carries state, is `aria-live="polite"`, and shows a timestamp in its `title`. Add a shortcut hint to the undo and redo buttons' `title` attributes in the three templates, and fold a hint into the string `setSaveState` writes for the save button. Every failure path the shortcut can hit is already visible: conflict moves focus to the diagnostics panel, invalid Setup scrolls to the offending field, a failed save shows "Save failed - Retry". The only silent case is "already saved", which is the only case where silence is the truth.

### 3.6 Sequence

No migration is required, and no step leaves the app in a state where a save could fail — every step is additive in the browser only.

| # | Step | Files | Test | Invariant it must not break |
|---|---|---|---|---|
| 1 | Extract `requestManualSave()`; rebind the button to it | app.js | Existing save-button cases in tests/test_browser.py must pass unchanged | The retry-budget reset stays on the manual path only — autosave must not reset `saveRetryCount` |
| 2 | Add the dialog guard, the repeat guard and the `s` branch to the listener | app.js | `test_ctrl_s_saves_and_suppresses_browser_dialog`; `test_ctrl_s_on_setup_with_invalid_field_reveals_the_error`; `test_ctrl_s_during_conflict_focuses_diagnostics`; `test_held_ctrl_s_issues_one_put` (dispatch a synthetic keydown with `repeat: true` and count PUTs — Playwright's `press` cannot set `repeat`) | `saveInFlight` coalescing; exactly one PUT per settled save |
| 3 | Scope `z` / `Shift+Z` by `activeTextEntry()` at [L577-L580](../../app/web/static/app.js#L577-L580) | app.js | `test_ctrl_z_in_a_text_field_uses_native_undo` — must assert the page did **not** reload and that the model matches the reverted field; `test_ctrl_z_outside_a_text_field_undoes_report_action` | The model must stay in sync with the field: native undo is expected to emit an `input` event with `inputType: "historyUndo"`, which the existing `input` listener consumes. **Verify this in the test before shipping** — if a target browser does not emit it, option B in section 4 is not viable as written |
| 4 | Re-entrancy guard on `undo` / `redo` | app.js | `test_double_ctrl_z_undoes_exactly_one_action` | `updateHistoryControls` at [L480-L485](../../app/web/static/app.js#L480-L485) stays the only writer of those buttons' `disabled` — the guard is a promise, not a DOM flag |
| 5 | Ctrl+Y alias | app.js | `test_ctrl_y_redoes` | Same guards as `z`; no separate code path |
| 6 | Update [docs/DATA_MAP.md](../DATA_MAP.md) sections 9 and 10 | DATA_MAP.md | n/a | Ship in the same change as step 3, not after — the existing "regardless of focus" sentence is falsified by it |
| 7 | Shortcut hints on undo/redo titles and the save-button label string | three templates, app.js | Covered by existing accessibility assertions | `setSaveState` remains the sole writer of `#save-button` |

Tests should use Playwright's `ControlOrMeta` modifier so macOS and Linux CI agree.

---

## 4. Recommendation on Ctrl+Z inside text fields

**Scope the shortcut: when `activeTextEntry()` returns an element, return early *without* `preventDefault()` and let the browser's native undo win.**

The predicate already exists at [L577-L580](../../app/web/static/app.js#L577-L580) and matches every text input, textarea and the `.rich` contenteditables — so this adds no new rule and no new copy of an existing one.

Why the status quo is untenable: one focused field is one undo step, and the transaction stays open while the field has focus. `undo()` finalizes that transaction before popping. So Ctrl+Z after typing three paragraphs into a finding discards all three, then reloads the page. In a tool whose purpose is writing long prose, that is the most likely keystroke doing the most destructive thing.

Costs of each option, stated plainly:

| Option | Cost |
|---|---|
| **Leave as-is** | The failure above stays. Every text field in the app is affected: scope text, custom location, list items, table cells, code blocks, instance titles, and every rich-text body |
| **Scope to native (recommended)** | (a) Report-level undo becomes unreachable *while a text field has focus* — the tester must click the Undo button, which blurs the field and finalizes the transaction first, so it still works, just not from the keyboard mid-field. (b) The native stack is per-element and dies when the DOM is re-rendered or the page navigates; the app's stack survives in sessionStorage. Two different lifetimes, and the tester is not told which one they are talking to. (c) When a field's native stack is exhausted, Ctrl+Z does nothing and does **not** fall through to app undo — and that cannot be fixed, see below |
| **Separate chord for report undo** (e.g. Ctrl+Alt+Z, which the current listener already ignores via its `altKey` bail) | Restores keyboard access to report-level undo from inside a field, at the cost of a chord nobody will discover and a third keyboard behaviour to document. Not recommended — the Undo button is visible and one click away |

**The two stacks cannot be merged, and no clever middle ground exists.** There is no API to read, count or test the browser's native undo stack. `document.execCommand("undo")` is deprecated and does not report whether it undid anything. `beforeinput` with `inputType === "historyUndo"` can be observed but gives no way to know that the *next* Ctrl+Z will find the stack empty. Any "fall through to app undo when native has nothing left" heuristic is a guess, and when the guess is wrong it silently eats a report-level action and reloads the page. The correct design is a clean boundary: inside a text field the browser owns undo; outside it the app does.

---

## 5. Open questions

1. **Ctrl+Z inside text fields — adopt native undo, or keep today's global behaviour?** This changes what the most-used keystroke does in the place testers spend most of their time, and the app's stack and the browser's stack can never be merged, so there is no outcome where one keypress serves both. Absent an answer I would scope to native, because the current behaviour can destroy an entire paragraph and reload the page in response to a keystroke that in every other application means "take back the last word".
2. **Should Ctrl+S be suppressed while a confirmation dialog is open, or should it save anyway?** A dialog's answer can itself mutate the report, so saving mid-decision persists a half-made choice. Absent an answer I would suppress it, while still calling `preventDefault()` so the browser's Save Page As never appears over the modal.
3. **Ctrl+Y as a redo alias — in or out?** One branch, no collisions, matches Windows convention. Absent an answer I would add it.
4. **Should the home page get a Ctrl+S binding?** It has no report and no save path. Absent an answer I would add nothing and let the browser handle the key there.
5. **Feedback when Ctrl+S is pressed and everything is already saved — silence, or a brief visual pulse on the save button?** Silence is truthful but gives no acknowledgement that the key was received. Absent an answer I would stay silent and avoid the CSS change.
6. **The conflict path uses `focus({preventScroll: true})`.** If the diagnostics panel is off-screen, a Ctrl+S during a conflict moves focus somewhere invisible and looks like nothing happened. Absent an answer I would leave it identical to the button's behaviour rather than making the keyboard path diverge.

---

## 6. What I would not do

- **Bind Ctrl+S to `#save-button.click()`.** It works today only because `disabled` happens to mean "nothing to save"; it couples the keyboard to a DOM attribute and skips nothing visibly when that coupling changes.
- **Attempt to merge or arbitrate between the native undo stack and `undoHistory`.** There is no way to inspect the native stack, so every heuristic eventually eats a report-level action at the moment the tester least expects it.
- **Remove the `window.location.reload()` from `restoreHistory` as part of this change.** It is the mechanism by which server-derived state and the page gate are re-read after an undo. It deserves to go, but not bundled with a keyboard binding.
- **Add a toast or snackbar for save confirmation.** The save button is the single status surface; a second one drifts out of agreement with the first.
- **Implement the undo/redo re-entrancy guard by disabling the buttons.** `updateHistoryControls` owns `disabled` on those two buttons, and a second writer would fight it.
- **Inline any "can I save right now?" logic into the key handler.** Those rules already exist twice, in Python and in JavaScript. A third copy is a bug waiting for a schedule.

## Round 2 - Oracle: verdict on the proposal

# Verdict: keyboard save and undo

Checked every claim against source. The shape is sound and the dispatch decision is right. Four things are wrong: one risk row is graded in the wrong direction, one risk row names a mitigation that does not exist, the dialog guard misses a modal, and one sequence step breaks three existing assertions.

---

## 1. Risk rows that are wrong

### `backup exhaustion` is marked `RISK` — it is `clear`

Already fully handled by shipped code, and the reasoning given for it is backwards.

`atomic_write_json` copies the current bytes to `<name>.bak.json` once per write ([storage.py#L18-L23](../../app/storage.py#L18-L23)), and `save_report` performs exactly one write per PUT, through `save_if_current` ([main.py#L691](../../app/main.py#L691)). So a second `draft.bak.json` write needs a second PUT.

A second PUT needs `pendingSave && saveRevision > savedRevision` to be true at [app.js#L623](../../app/web/static/app.js#L623), and only a new **edit** can make it true — `saveRevision` is bumped in `scheduleSave` ([L593](../../app/web/static/app.js#L593), [L613](../../app/web/static/app.js#L613)), on conflict resolution, in `restoreHistory`, and on draft recovery. Nothing else. "Press Ctrl+S right after the autosave fired" therefore issues **zero** PUTs, not two — the guard at L623 returns `true` without sending. During the round trip, `saveInFlight` at [L622](../../app/web/static/app.js#L622) returns the running promise.

The `event.repeat` guard is still worth adding, but it earns its place for **undo**, where there is no equivalent backstop. Do not justify it with backups; that justification is false and will mislead whoever reads the table next.

### `silent stranding` is correctly `RISK`, but the stated mitigation does not exist

The row says the hole is "handled by routing through `requestManualSave()`, which runs `validateSetupInputs(true)` — reveal mode scrolls to and focuses the first offender". It does not.

`validateSetupInputs` ([app.js#L1068-L1078](../../app/web/static/app.js#L1068-L1078)) collects `[data-setup-validated]` inputs whose `input.validity.valid` is false, and scrolls to `invalidInputs[0]`. Stranding is a different predicate entirely: `strandedByScopeEdit` is assigned `scopeTextStrandedFindings` at [L1240](../../app/web/static/app.js#L1240), defined at [L1233-L1239](../../app/web/static/app.js#L1233-L1239), and it returns **finding titles**. Its only feedback is the button relabel at [L630](../../app/web/static/app.js#L630). Nothing scrolls. Nothing focuses. `reportValidity()` is never reached, because a stranded finding is not an invalid input.

Worse, there is nothing on the page to scroll **to**: stranding names findings, and findings do not exist in the Setup DOM. So the "button is off-screen and Ctrl+S looks dead" problem the row correctly identifies is not closed by this plan at any level.

Two honest options, both bigger than the plan admits: either accept that the shortcut has exactly the same feedback as the autosave does today (button label only, and say so), or add a real surface — `#setup-validation-note` at [L534](../../app/web/static/app.js#L534) is the existing element for this and `updateSetupValidationNotice` ([L532-L559](../../app/web/static/app.js#L532-L559)) is the existing writer. Do not ship the row as written.

### `focus-context correctness` is correctly `RISK`, but sub-claim (a) is overstated

"Ctrl+S with focus in a text field runs `applyCanonicalReport`, which can rewrite the value of the field being typed in — and drop the caret."

`applyCanonicalReport` ([L398-L403](../../app/web/static/app.js#L398-L403)) and `reconcileCanonicalObject` ([L347-L397](../../app/web/static/app.js#L347-L397)) write the **JavaScript object graph**. I could not find a path that re-reads that graph back into a focused DOM node on the save path. The only DOM writes a settled save performs are `setSaveState` ([L205-L224](../../app/web/static/app.js#L205-L224)) and `updateEngagementName` ([L17-L23](../../app/web/static/app.js#L17-L23)); the `reportchange` event ([L319-L323](../../app/web/static/app.js#L319-L323)) drives only `updateReadinessPanel` ([L2531](../../app/web/static/app.js#L2531)). And the field most exposed to server rewriting — `scope_text` — is deliberately excluded from canonical reconciliation.

Keep the test the row asks for, but write it as a proof rather than a repair, and stop describing caret loss as established. It is not established in the source.

### Every other row is graded correctly

`stale write`, `lost update`, `orphan reference`, `schema break`, `request/response asymmetry`, `derived-state fight` — all `clear`, all verified. `rule drift`, `navigation trap`, `key auto-repeat`, `open transaction at save time` — all correct.

Two confirmations worth recording:

- `save()` genuinely never calls `finalizeTextTransaction()`. Checked the whole body, [L620-L672](../../app/web/static/app.js#L620-L672). The `open transaction at save time` row is right.
- `restoreHistory` genuinely reloads regardless of the save's outcome ([L513-L519](../../app/web/static/app.js#L513-L519)), and `save()` has five ways to return `false` without sending anything ([L621-L632](../../app/web/static/app.js#L621-L632)). The `navigation trap` row is right, and if anything understates it.

### One invariant in the sequence table is false

Step 1 lists "the retry-budget reset stays on the manual path only — autosave must not reset `saveRetryCount`".

Shipped code already violates it. `scheduleSave` sets `saveRetryCount = 0` on its first line, [L590](../../app/web/static/app.js#L590), on **every** edit; the settled-save path resets it again at [L651](../../app/web/static/app.js#L651). The real invariant is narrower: a manual save must be able to reset the budget **without an edit**, which is the only thing the button contributes. State it that way or the step's acceptance criterion cannot be met.

---

## 2. Files the planner missed

### The `data-dialog` probe is real but incomplete — there is a second modal

`backdrop.dataset.dialog = ""` is at [dialog.js#L16](../../app/web/static/dialog.js#L16), and the attribute is an exact proxy for "a `vrDialog` is open": the capture listener is registered at [L88](../../app/web/static/dialog.js#L88) and the backdrop appended at [L90](../../app/web/static/dialog.js#L90), both synchronously, and `settle` removes both at [L52-L53](../../app/web/static/dialog.js#L52). No false positives either — the buttons carry `data-dialog-action` ([L62](../../app/web/static/dialog.js#L62)), a different attribute name that `[data-dialog]` does not match. All three report templates load `dialog.js` before `app.js`.

**But there is a case where a modal is open and the attribute is absent.** The evidence lightbox at [app.js#L2010-L2016](../../app/web/static/app.js#L2010-L2016) builds a native `<dialog class="image-dialog">` and calls `showModal()`. It has no `data-dialog` attribute and never touches `vrDialog`. With a screenshot open full-size, `document.querySelector("[data-dialog]")` returns `null`, so Ctrl+Z undoes a report-level action and reloads the page out from under the lightbox — the exact failure the guard was written to prevent.

Use `document.querySelector("[data-dialog], dialog[open]")`. Add the lightbox to the test for step 2.

### The three templates are genuinely duplicated, and the buttons are there

Confirmed. `#undo-button`, `#redo-button` inside `.history-controls`, and `#save-button` appear verbatim in the header of [page1_setup.html#L3](../../app/web/templates/page1_setup.html#L3), [page2_findings.html#L3](../../app/web/templates/page2_findings.html#L3), and [page2_editor.html#L3](../../app/web/templates/page2_editor.html#L3). `_brand.html` is a real shared include but holds only the logo link. Three edits, not one.

One constraint the plan does not state: both buttons already carry `title="Undo last change"` **and** `aria-label="Undo last change"`, and the browser tests locate them by accessible name — [test_browser.py#L346](../../tests/test_browser.py#L346), [L351](../../tests/test_browser.py#L351), [L744](../../tests/test_browser.py#L744), [L747](../../tests/test_browser.py#L747). Change the `title` freely; if you touch `aria-label`, keep "Undo last change" as a substring or those four locators stop resolving.

### `activeTextEntry()` covers everything listed — and over-matches

[L577-L580](../../app/web/static/app.js#L577-L580) matches every `.rich` (the literal `contenteditable="true"` is written at [L826](../../app/web/static/app.js#L826)) and every textarea in the oracle's table: scope text [L1357](../../app/web/static/app.js#L1357), custom locations [L1637](../../app/web/static/app.js#L1637), per-target location value [L1682](../../app/web/static/app.js#L1682), list items [L2203](../../app/web/static/app.js#L2203), table cells [L2255](../../app/web/static/app.js#L2255), and the code block and instance title, which come from one branch that picks `textarea` or `input` and wires both at [L2341](../../app/web/static/app.js#L2341) and [L2343](../../app/web/static/app.js#L2343). (The oracle's table gave L2330 twice; that is one line, not two controls.)

**The over-match is the problem.** `input:not([type="checkbox"],[type="radio"],[type="file"])` also matches `input[type="date"]` — the test-window start and end dates at [L1302](../../app/web/static/app.js#L1302). A date picker has no native undo stack, so under the recommendation Ctrl+Z there becomes a **dead key**: the app declines to act and the browser has nothing to undo. Today it performs a report-level undo.

`activeTextEntry` is the right predicate for transaction bookkeeping, where over-matching is harmless. It is the wrong predicate for "the browser owns undo here", where over-matching silently removes a working key. Either narrow the scoping test to real text entry, or accept the date-field regression deliberately and write it down.

### The save button's `title` is genuinely futile in markup

Confirmed. `setSaveState` writes `saveButton.title` on **every** call, to `""` in every state except `saved` ([L205-L224](../../app/web/static/app.js#L205-L224)), and it is called once at module load ([L225](../../app/web/static/app.js#L225)). A markup `title` on `#save-button` is erased before the tester can hover it. The plan is right.

### Existing tests this would break

The step 1 extraction is behaviour-preserving and breaks nothing. **Step 7 breaks three assertions**, in the same file step 1 promises to leave passing. `setSaveState`'s label strings are asserted exactly:

| Assertion | What it pins |
|---|---|
| [test_browser.py#L205](../../tests/test_browser.py#L205) | `assertEqual(save_button.text_content(), "Unsaved changes")` |
| [test_browser.py#L211](../../tests/test_browser.py#L211) | `assertRegex(..., r"^Saved \d{2}:\d{2}$")` — anchored both ends |
| [test_browser.py#L212](../../tests/test_browser.py#L212) | `title` must start with `"Last saved "` |
| [test_browser.py#L770](../../tests/test_browser.py#L770) | `assertEqual(..., "Save failed - Retry")` |

So "fold a hint into the string `setSaveState` writes for the save button" is not "covered by existing accessibility assertions" — it **fails** them. Given open question 5's own default is silence, the cheapest resolution is to drop the save-button hint entirely and keep the shortcut hint on undo/redo only, where `title` is free.

Existing key-press tests: [L420](../../tests/test_browser.py#L420) presses Enter on Next, [L789-L791](../../tests/test_browser.py#L789-L791) drives the library combobox with ArrowDown and Enter. Neither uses a modifier, so there is no collision — but note that L791 depends on `stopImmediatePropagation()` at [app.js#L192](../../app/web/static/app.js#L192), so a document-level listener must keep claiming only `s`, `z`, `y`. No test presses a modifier key today; every case in section 3 is genuinely new.

### A fourth page the inventory never mentions

[library_editor.html](../../app/web/templates/library_editor.html) is a `<form>` with a "Save entry" submit button and an inline script at L76-L153. It loads neither `app.js` nor `dialog.js`, so Ctrl+S falls through to the browser's Save Page As on a page that visibly has unsaved edits and a Save button. Leaving it alone may be right — but open question 4 asks only about the home page, and the inventory says "three report pages" as if that were the whole surface. It is not.

### Twinned rules: none is broken, but the inventory is short

No Python/JavaScript pair is modified. The plan's four-row twin table is accurate for the rules `save()` gates on. For completeness, `app.js` also holds `requiresFragment` ([L96](../../app/web/static/app.js#L96), twin of `docx_report.generation_issues`), `RESOLVED_REMEDIATION` ([L98](../../app/web/static/app.js#L98), twin of `report_service.RESOLVED_REMEDIATION`), and an entire client-side `provision` ([L864](../../app/web/static/app.js#L864), twin of `report_service.provision`). None is touched here. They matter only as the reason the "no bespoke gate in the key handler" rule is non-negotiable — this file has more twins in it than the table implies.

### No server change is needed, and cache busting is automatic

`asset_v` is `_AssetVersion.__str__`, recomputed on every render from `max(mtime)` across `app/web/static/*.*` ([main.py#L52-L60](../../app/main.py#L52-L60)). Editing `app.js` and the templates busts the cache with no constant to bump. "Server: none" holds.

---

## 3. Persisted state: nothing changes shape

Confirmed on all four stores.

- **`draft.json`** reaches disk only through `atomic_write_json` ([storage.py#L18](../../app/storage.py#L18)), from `Report.model_dump`. No `models.py` change is proposed and none is needed. Every existing draft loads unchanged, and no legacy-repair entry is required in `load_path`.
- **`sessionStorage["vulnreport-history:{reportId}"]`** is written at [L487](../../app/web/static/app.js#L487) as `JSON.stringify({undoHistory, redoHistory})` and read at [L83](../../app/web/static/app.js#L83). The plan adds no key and no field; the re-entrancy guard is a module-scope promise and is never serialised. Untouched.
  - **One caveat on the guard.** Put it at the very top of `undo`/`redo`, ahead of `finalizeTextTransaction()` and the `pop()` at [L748-L750](../../app/web/static/app.js#L748-L750). A guard placed after the pop would drop an action on the floor: the stacks would have already moved, and the persisted copy written by `storeHistory` would disagree with the in-memory pair.
- **`localStorage["vulnreport-pending:{reportId}:{tabId}"]`** keeps the envelope written at [L241-L253](../../app/web/static/app.js#L241-L253) — `{schemaVersion: 1, reportId, tabId, baseSavedAt, capturedAt, editRevision, report}`. The boot reader at [L44-L64](../../app/web/static/app.js#L44-L64) still wraps a bare legacy report and still deletes anything whose `reportId` disagrees. Untouched.
- **`sessionStorage["vulnreport-recovery:{reportId}"]`** ([L25](../../app/web/static/app.js#L25), written at [L508](../../app/web/static/app.js#L508)) and **`sessionStorage["vulnreport-tab-id"]`** ([L28-L32](../../app/web/static/app.js#L28-L32)) are untouched.

Nothing on disk and nothing in browser storage changes shape. The `schema break` row is correct.

---

## 4. Does native undo fire an `input` event the app would consume?

**Half of this is settled by source, and it is the half that was actually in doubt. The other half cannot be settled by source and needs one test.**

### What the source settles

Every text control in this app commits to the model on the `input` event, and **nothing anywhere filters on `event.inputType`**. A search for `inputType` and `beforeinput` across `app.js` returns zero hits.

| Control | Handler |
|---|---|
| `.rich` contenteditable | `input.oninput = () => { resize(); onChange(runsFrom(input)); }` — [L832](../../app/web/static/app.js#L832) |
| fragment body `onChange` | `runs => { fragment.runs = runs; changed(); }` — [L2195](../../app/web/static/app.js#L2195), where `changed = () => scheduleSave()` — [L2192](../../app/web/static/app.js#L2192) |
| Setup fields | [L1119](../../app/web/static/app.js#L1119) |
| scope textarea | [L1365](../../app/web/static/app.js#L1365) |
| custom locations, location values | [L1637](../../app/web/static/app.js#L1637), [L1682](../../app/web/static/app.js#L1682) |
| list items, table cells, code block, instance title | [L2225](../../app/web/static/app.js#L2225), [L2263](../../app/web/static/app.js#L2263), [L2341](../../app/web/static/app.js#L2341), [L2343](../../app/web/static/app.js#L2343) |

So **if** the browser emits `input`, a `historyUndo` is indistinguishable from typing as far as this app is concerned: the handler rewrites the model, `scheduleSave()` runs, takes the early branch at [L592](../../app/web/static/app.js#L592) because the same field still owns the open transaction, bumps `saveRevision`, queues the local draft and the autosave, and pushes no new undo entry. That is precisely the desired outcome, and it needed checking — a single `onchange`-only or `keyup`-only text writer would have sunk the design. There is none.

Two adjacent facts, also from source, that the plan should carry:

- The scope textarea has a second handler, `textarea.onchange` at [L1368](../../app/web/static/app.js#L1368), which compares against a `scopeTextBefore` snapshot taken on `focus` ([L1367](../../app/web/static/app.js#L1367)) and opens `confirmScopeTextLoss` on commit. `change` does not fire on undo, only on commit, so a native undo inside that field updates the model and leaves the commit check comparing against the focus-time value — correct, but worth a test, because this is the one field where undo and a confirmation dialog can meet.
- `rich()` routes the bold/italic/underline toolbar through `document.execCommand` ([L830](../../app/web/static/app.js#L830)) and re-issues paste as `execCommand("insertText")` ([L831](../../app/web/static/app.js#L831)). Both push entries onto the native stack. So the first Ctrl+Z in a `.rich` may reverse a **formatting command or a paste**, not a word — a behaviour the tester did not ask for and the plan does not mention.

### What the source cannot settle

Whether the browser fires `input` at all for a native undo is user-agent behaviour, not repository behaviour. It is specified — `historyUndo` and `historyRedo` are defined `inputType` values and `input` is specified to fire for them in both `<textarea>` and `contenteditable` — but specified is not verified on the browser this ships against, and I will not grade a plan on a claim I cannot attribute to a file in this repository.

### What would settle it

One Playwright case per surface, asserting three things. The third is the one that matters.

1. Stamp a load marker in an init script (`window.__loadId = Math.random()`), open the Content page, type into a `.rich` body, wait for `#save-button[data-save-state="saved"]`.
2. Type more, then `page.keyboard.press("ControlOrMeta+z")`.
3. Assert: **(a)** `window.__loadId` is unchanged — no reload happened; **(b)** the DOM text reverted; **(c)** after the autosave settles, `main.workspace.load(report_id)` matches the reverted text.

(c) is non-negotiable. "DOM reverted but model stale" is the exact failure mode this question exists to rule out, and only a round trip to `draft.json` proves it did not happen — reading `dataset.report` will not do, because that is the server's seed and never changes after boot.

Run it three times: on a `.rich`, on the list textarea at [L2203](../../app/web/static/app.js#L2203) (sharpest case — its `oninput` rebuilds `fragment.items` by splitting and trimming lines, so a partial revert has somewhere to go wrong), and on a `.rich` whose last action was a toolbar `execCommand("bold")`.

If (c) fails on any target browser, the section 4 recommendation is not viable as written, and the fallback is the separate chord — not "leave as-is", which the plan itself argues is the most destructive option on the table.

---

## Invariants in play

- **`saveInFlight` coalescing** ([L622](../../app/web/static/app.js#L622)). It is what makes `backup exhaustion` a non-issue and what bounds a held Ctrl+S. Break it and two PUTs race on the same `saved_at`, producing a spurious 409.
- **A PUT requires a revision bump** ([L623](../../app/web/static/app.js#L623)). Only an edit produces one. Any shortcut that forces `pendingSave` directly would turn an idle keypress into a real write, and a real write into a lost backup.
- **One field, one transaction** ([L592-L599](../../app/web/static/app.js#L592-L599)). A native undo taking the early branch preserves this. A handler that pushed an action per `historyUndo` would blow the 20-entry cap in a sentence.
- **`previousReport` moves only when no transaction is open** ([L644](../../app/web/static/app.js#L644)). Untouched by this plan, and it is why a mid-typing keyboard save is safe.
- **`restoreHistory` rolls back on any storage failure** ([L500-L512](../../app/web/static/app.js#L500-L512)). The re-entrancy guard must not sit between the stack mutation and this rollback.
- **`updateHistoryControls` is the only writer of `#undo-button.disabled`** ([L480-L485](../../app/web/static/app.js#L480-L485)). The plan is right to insist the guard be a promise.

## Both-sides warning

No Python/JavaScript pair is modified by this plan, and none needs to be — provided the shortcuts call `requestManualSave()`, `undo()` and `redo()` and re-implement no gate. The four pairs `save()` gates on (Setup character sets and username, test-window order, Setup completeness, scope-target survival) stay untouched. Note only that `app.js` carries three further twins the plan's table omits — `requiresFragment` ([L96](../../app/web/static/app.js#L96)), `RESOLVED_REMEDIATION` ([L98](../../app/web/static/app.js#L98)), and the client-side `provision` ([L864](../../app/web/static/app.js#L864)) — which is why a bespoke "can I save?" test inside the key handler is worse than it looks.

## Map drift

Corrected in [docs/DATA_MAP.md](../DATA_MAP.md):

- **Section 12** described the confirmation guards as "the `window.confirm` guards". There is no `window.confirm` anywhere in `app.js`; all seven confirmation sites go through `window.vrDialog.confirm`. The distinction is load-bearing for this plan — a native `window.confirm` blocks the JavaScript thread, so no keydown could reach the app during one, and the entire dialog-guard analysis would be unnecessary. Corrected, and `settleScopeChange` re-described accurately.

Not corrected, deliberately: section 9's sentence that the keydown listener "calls `preventDefault()` regardless of focus, so native undo is suppressed" is **true today**. Step 6 falsifies it and must ship in the same change as step 3, exactly as the plan says.

## Round 2 - Planner: revised plan

# Keyboard save and undo — revised plan

*Supersedes the Round 1 proposal. Standalone: nothing earlier in this file is needed to read it. Six decisions are open; they are in section 3.*

## 1. Understanding

Add a Ctrl/Cmd+S binding that produces exactly the outcome of pressing the Save button — conflict routing, reveal-mode Setup validation, and the retry-budget reset that the button handler performs and `save()` does not — by extracting that handler into a named `requestManualSave()` and binding both the button and the key to it. Change what Ctrl/Cmd+Z does inside real text entry, so that it stops discarding a tester's entire editing session in a field and reloading the page. Give the stranded-findings refusal a surface a tester can actually see, because today it only relabels a button that can be scrolled off the top of a long Setup page. Add no persisted field, no endpoint, and no rule that would need a Python twin.

---

## 2. Blast radius

| File | What changes | Why |
|---|---|---|
| [app.js](../../app/web/static/app.js) L691-702 | Extract the `#save-button` click body into `requestManualSave()`; rebind the button to it | The three things the handler does beyond `save()` — conflict routing, `validateSetupInputs(true)`, `saveRetryCount = 0` — must be shared, not duplicated |
| [app.js](../../app/web/static/app.js) L770-774 | Rewrite the document `keydown` listener: add `s`, add a modal guard, add an `event.repeat` guard, scope `z` by a new predicate, optionally add `y` | One listener, one place to reason about modifier keys |
| [app.js](../../app/web/static/app.js) L747-767 | Re-entrancy guard at the **very top** of `undo` and `redo`, ahead of `finalizeTextTransaction()` and the `pop()` | Both are `async` and end in `window.location.reload()`; a guard placed after the pop drops an action on the floor, because the stacks have already moved and `storeHistory` has already persisted the move |
| [app.js](../../app/web/static/app.js) L577-580 | Add `nativeUndoOwner()` beside `activeTextEntry()`; leave `activeTextEntry()` untouched | `activeTextEntry` over-matches `input[type="date"]`. It is right for transaction bookkeeping, where over-matching is harmless, and wrong for "the browser owns undo here", where over-matching deletes a working key |
| [app.js](../../app/web/static/app.js) L532-559 | `updateSetupValidationNotice` composes one more message line from `strandedByScopeEdit()`; `requestManualSave` sets `validationAttempted` and scrolls the notice into view on a stranding refusal | The only existing surface that can name a stranded finding. `strandedByScopeEdit` defaults to `() => []` at [L122](../../app/web/static/app.js#L122), so the call is safe on every page |
| [dialog.js](../../app/web/static/dialog.js) | **No change** | The backdrop carries `data-dialog` at [L16](../../app/web/static/dialog.js#L16), an exact proxy for "a `vrDialog` is open". The probe in app.js becomes `[data-dialog], dialog[open]` to also catch the evidence lightbox |
| [manager.js](../../app/web/static/manager.js) | **No change** — pending open question 4 | The home page has no report and no save path |
| [library_editor.html](../../app/web/templates/library_editor.html) | **No change** — pending open question 4 | A fourth page with a visible "Save entry" submit button at [L69](../../app/web/templates/library_editor.html#L69) and an inline script, loading neither `app.js` nor `dialog.js`. Ctrl+S there opens the browser's Save Page As over unsaved edits |
| [page1_setup.html](../../app/web/templates/page1_setup.html), [page2_findings.html](../../app/web/templates/page2_findings.html), [page2_editor.html](../../app/web/templates/page2_editor.html) | `title` on `#undo-button` and `#redo-button` only. `aria-label` untouched | Three verbatim copies of the header, not a shared include. Four test locators resolve `get_by_role("button", name="Undo last change")` from `aria-label`; `title` is free to change. The **save** button gets no hint at all — see section 5, step 8 |
| [tests/test_browser.py](../../tests/test_browser.py) | New Playwright cases, named per step in section 5 | Every behaviour here is browser-side; there is no Python surface to unit-test |
| [docs/DATA_MAP.md](../DATA_MAP.md) | Section 9: the sentence that the keydown listener "calls `preventDefault()` regardless of focus, so native undo is suppressed" becomes false; add the Ctrl+S entry point into `save()` | That sentence is **true today** and stops being true at step 7. It ships in the same change, not after |
| [app.css](../../app/web/static/app.css) | No change unless open question 5 resolves toward a visible pulse | Default answer is no change |
| **Server: none** | `main.py`, `report_service.py`, `workspace.py`, `models.py`, `storage.py` untouched | No new field, route, or validation. `asset_v` is recomputed from static-file mtimes at [main.py#L52-L60](../../app/main.py#L52-L60), so cache busting is automatic |

---

## 3. Open questions

**1. Ctrl+Z inside text entry — hand it to the browser, or keep today's global behaviour?**
This changes the most-used keystroke in the place testers spend most of their time, and the two undo stacks can never be merged, so there is no outcome where one keypress serves both. Today: one focused field is one undo step, the transaction stays open while the field has focus, and `undo()` finalizes it before popping — so Ctrl+Z after typing three paragraphs into a finding discards all three and reloads the page. Absent an answer I would hand it to the browser, gated on the settling test in step 6 passing.
Two consequences to accept with that answer: report-level undo becomes unreachable from the keyboard while a text field has focus (the Undo button still works, and blurs the field first), and the first Ctrl+Z inside a `.rich` may reverse **a formatting command or a paste rather than a word**, because the B/I/U toolbar at [L830](../../app/web/static/app.js#L830) and the paste interception at [L831](../../app/web/static/app.js#L831) both go through `execCommand` and push native stack entries.

**2. Ctrl+S while a modal is open — suppress, or save anyway?**
A `vrDialog`'s answer can itself mutate the report, so saving mid-decision persists a half-made choice. Absent an answer I would suppress, while still calling `preventDefault()` so Save Page As never appears over the modal. The same guard covers the evidence lightbox.

**3. Ctrl+Y as a redo alias — in or out?**
One branch in the same listener, no collision with anything in the app, matches the Windows convention. Absent an answer I would add it.

**4. The two non-report pages — bind, or leave to the browser?**
The home page has no report and no save path; leaving it alone is uncontroversial. The **library editor** is different: it is a form with a "Save entry" submit button and visible unsaved edits, and Ctrl+S there opens Save Page As. Nothing is lost — the browser dialog is a confusion cost, not a data cost — but the inconsistency is real. Absent an answer I would leave both alone, because binding the library editor means a fourth, unshared copy of shortcut logic in an inline script for a page with one button. If you want parity it is `form.requestSubmit()` behind the same `preventDefault()`, and it should be its own change.

**5. Acknowledgement when Ctrl+S is pressed and everything is already saved — silence, or a brief pulse on the save button?**
Silence is truthful but gives no sign the key was received. Absent an answer I would stay silent and avoid the CSS change. Note that "fold a hint into the save-button label" is no longer on the table at all — see step 8.

**6. The conflict path uses `focus({preventScroll: true})`.**
If the diagnostics panel is off-screen, Ctrl+S during a conflict moves focus somewhere invisible and looks like nothing happened. Absent an answer I would leave the keyboard path identical to the button's behaviour rather than making them diverge.

Settled by the Round 2 verdict and therefore dropped: whether `save()` ever finalizes an open transaction (it does not), whether a markup `title` on `#save-button` survives (it does not), whether the extraction breaks existing tests (it does not), and whether any text control would fail to consume a synthetic `historyUndo` (none would — nothing in `app.js` reads `event.inputType`).

---

## 4. Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write | `clear` | No new mutation path. Ctrl+S routes into the existing `save()`, which PUTs the whole document carrying the `saved_at` that `applyCanonicalReport` last installed. The shortcut changes *when* an existing write happens, never *what* it carries |
| Lost update | `clear` | Server untouched. The browser's read-modify-write is `save()` itself, already serialised by `saveInFlight` at [L622](../../app/web/static/app.js#L622) |
| Orphan reference | `clear` | Nothing creates or deletes a `frag_id`, `evidence_id`, or `scope.target_ids` entry. Undo and redo already replay whole-document diffs, and the PUT still runs `validate_references` |
| Silent stranding | `RISK` | The guard at [L628-L632](../../app/web/static/app.js#L628-L632) calls `strandedByScopeEdit`, which is `scopeTextStrandedFindings` ([L1233-L1240](../../app/web/static/app.js#L1233-L1240)) and returns **finding titles**. Its only feedback is the button relabel at [L630](../../app/web/static/app.js#L630). Nothing scrolls, nothing focuses, and `validateSetupInputs` cannot help — it collects `[data-setup-validated]` inputs whose `validity.valid` is false ([L1068-L1078](../../app/web/static/app.js#L1068-L1078)), a different predicate, and a stranded finding is not an invalid input. There is also nothing on the Setup page to scroll *to*, because findings do not exist in the Setup DOM. **Decision: build the surface.** `#setup-validation-note` already exists for this and `updateSetupValidationNotice` ([L532-L559](../../app/web/static/app.js#L532-L559)) is already its sole writer, already composes `Missing:` and `Invalid:` lines, and is already used this way by the Next gate. Step 2 adds one message line and scrolls to it on a manual refusal. The alternative — accept button-label-only feedback, identical to the autosave — was rejected because it collapses the entire reason for routing through `requestManualSave()` rather than `save()` |
| Schema break | `clear` | Nothing persisted changes shape: not `draft.json`, not `sessionStorage["vulnreport-history:{reportId}"]`, not the `localStorage` draft envelope, not the recovery or tab-id keys. The re-entrancy guard is a module-scope promise and is never serialised. No `load_path` repair, no migration; every existing draft loads unchanged |
| Request/response asymmetry | `clear` | No field added to the request or expected in the response |
| Rule drift | `RISK` | A bespoke "is it safe to save?" test inside the key handler would be a **third** copy of rules that already exist twice, in Python and JavaScript: Setup character sets and username, test-window order, Setup completeness, scope-target survival. `app.js` also carries `requiresFragment` ([L96](../../app/web/static/app.js#L96)), `RESOLVED_REMEDIATION` ([L98](../../app/web/static/app.js#L98)) and a whole client-side `provision` ([L864](../../app/web/static/app.js#L864)) as further twins. Handled by calling `requestManualSave()`, `undo()` and `redo()` and re-implementing no gate. Second drift vector: the DATA_MAP sentence about unconditional `preventDefault()`, handled by shipping step 10 with step 7 |
| Navigation trap | `RISK` | Not from save — a blocked Ctrl+S simply does not navigate. From **undo**: `restoreHistory` ([L492-L520](../../app/web/static/app.js#L492-L520)) ends in `window.location.reload()` after awaiting a save whose result it never inspects, and `save()` has five ways to return `false` without sending anything. If the undone state no longer satisfies the page's entry gate, the tester is bounced. Pre-existing, but a repeating key makes it reachable by accident. Contained by the `event.repeat` guard and the re-entrancy guard; not otherwise addressed here |
| Derived-state fight | `clear` | A PUT re-derives `scope_targets` from `scope_text`, seeds fragments and can rename the report folder — but Ctrl+S sends exactly what the autosave would have sent, so `provision_report` gets no new opportunity. The re-baseline suppression at [L644](../../app/web/static/app.js#L644) already refuses to move `previousReport` while a transaction is open, so a save fired mid-typing does not corrupt the pending undo entry |
| Backup exhaustion | `clear` | **Corrected from Round 1, where this was graded `RISK` on backwards reasoning.** `atomic_write_json` copies to `<name>.bak.json` once per write ([storage.py#L18-L23](../../app/storage.py#L18-L23)) and `save_report` writes once per PUT ([main.py#L691](../../app/main.py#L691)), so a second backup needs a second PUT. A second PUT needs `pendingSave && saveRevision > savedRevision` at [L623](../../app/web/static/app.js#L623), and only a new **edit** bumps `saveRevision`. So "press Ctrl+S right after the autosave fired" issues **zero** PUTs, not two — the nothing-to-save guard returns `true` without sending. During the round trip, `saveInFlight` returns the running promise. Fully handled by shipped code |
| Key auto-repeat / double-fire | `RISK` | **For undo, not for save.** Holding Ctrl+Z today pops one action per repeat, each applying a diff, writing `sessionStorage` and scheduling a reload — several actions vanish on one intent, with no backstop anywhere. Save needs no protection from repeat (see the row above); the guard is cheap and uniform, so it covers both, but its justification is undo. Handled by `event.preventDefault()` first, then `if (event.repeat) return;`, plus the promise guard in `undo`/`redo`, because those are `async` and two *distinct* keypresses can interleave during the save round-trip that precedes the reload |
| Focus-context correctness | `RISK` | Two live parts, one demoted. **(a) Demoted to a proof, not a repair.** `applyCanonicalReport` ([L398-L403](../../app/web/static/app.js#L398-L403)) and `reconcileCanonicalObject` write the JavaScript object graph; no path re-reads that graph into a focused DOM node on the save path, the only DOM writes a settled save performs are `setSaveState` and `updateEngagementName`, and `scope_text` is excluded from reconciliation. Caret loss is **not** established in source. Keep the test as evidence that it stays that way. **(b)** With a `vrDialog` open, its capture-phase handler ([dialog.js#L70-L85](../../app/web/static/dialog.js#L70-L85)) claims only Escape and Tab and does not stop propagation, so Ctrl+Z reaches app.js, undoes a report-level action and reloads the page while the modal's promise is unsettled — the caller's continuation never runs. **(c)** The library combobox claims only arrows, Enter and Escape, so `s` reaches the document; saving during a library search is harmless |
| Modal probe incompleteness | `RISK` | `[data-dialog]` alone misses a second modal. The evidence lightbox at [L2010-L2016](../../app/web/static/app.js#L2010-L2016) builds a native `<dialog class="image-dialog">` and calls `showModal()`, with no `data-dialog` attribute and no `vrDialog` involvement. With a screenshot open full-size, `document.querySelector("[data-dialog]")` returns `null` and Ctrl+Z reloads the page out from under the lightbox — the exact failure the guard exists to prevent. Handled by `document.querySelector("[data-dialog], dialog[open]")`, with the lightbox in the step 3 test |
| Native undo / model divergence | `RISK` | The half of the native-undo question source cannot settle. Source **does** settle that every text control commits on `input` and that nothing in `app.js` reads `event.inputType` or `beforeinput`, so a `historyUndo` would be consumed exactly like typing: the handler rewrites the model, `scheduleSave()` takes the early branch at [L592](../../app/web/static/app.js#L592) because the same field still owns the open transaction, and no new undo entry is pushed. Whether the browser *emits* `input` for a native undo is user-agent behaviour no file in this repository can prove. Gated by the settling test in step 6; if it fails, step 7 does not ship |
| Dead-key regression on date inputs | `RISK` | `activeTextEntry()` matches `input:not([type="checkbox"],[type="radio"],[type="file"])`, which includes `input[type="date"]` — the test-window start and end at [L1302](../../app/web/static/app.js#L1302). A date picker has no native undo stack, so scoping by that predicate would make Ctrl+Z there a **dead key**, where today it performs a report-level undo. Handled by `nativeUndoOwner()`, an allow-list: `textarea`, `[contenteditable="true"]`, and `input` whose `type` is absent or one of text / search / url / email / tel / password. An allow-list rather than a longer `:not()` so a future input type defaults to the working behaviour |
| Open transaction at save time | `clear`, but stated | `save()` never calls `finalizeTextTransaction()` — verified across its whole body, [L620-L672](../../app/web/static/app.js#L620-L672). So Ctrl+S with a field focused persists the text yet leaves the undo entry open, and a later Ctrl+Z reverts that field to its state when focus entered it, *including work already saved*. That is the existing one-field-one-step model, unchanged here, and it is the strongest argument for the recommendation in open question 1 |

---

## 5. Plan

Every step is browser-side and additive; no migration is required and no step leaves the app in a state where a save could fail. Tests use Playwright's `ControlOrMeta` modifier so macOS and Linux CI agree.

| # | Step | Files | Test | Invariant it must not break |
|---|---|---|---|---|
| 1 | Extract `requestManualSave()` from the click handler at [L691-L702](../../app/web/static/app.js#L691-L702); rebind the button to it | app.js | Every existing save-button case in [tests/test_browser.py](../../tests/test_browser.py) passes unchanged, plus `test_manual_save_resets_retry_budget_without_an_edit` | **Restated from Round 1, which asserted something shipped code already violates.** `scheduleSave` zeroes `saveRetryCount` on its first line, [L590](../../app/web/static/app.js#L590), on every edit, and the settled-save path zeroes it again at [L651](../../app/web/static/app.js#L651). The real invariant is narrower: a manual save must be able to reset the budget **without an edit**. That is the button's only unique contribution and the only thing the test can assert |
| 2 | Stranding surface: `updateSetupValidationNotice` gains a message line from `strandedByScopeEdit()`; `requestManualSave` sets `validationAttempted` and scrolls `#setup-validation-note` into view when the stranding guard refuses | app.js | `test_manual_save_with_stranded_finding_names_it_in_the_setup_notice` — assert the finding's title appears in the notice and the notice is in the viewport | `updateSetupValidationNotice` stays the **sole writer** of `#setup-validation-note`; the autosave path is untouched, so the notice never reveals itself without a deliberate manual attempt. Ships before step 3 so the shortcut never exists with a silent refusal path |
| 3 | Keydown listener: add the `s` branch, the modal guard `document.querySelector("[data-dialog], dialog[open]")`, and `event.preventDefault()` **before** `if (event.repeat) return;` | app.js | `test_ctrl_s_saves_and_suppresses_browser_dialog`; `test_ctrl_s_on_setup_with_invalid_field_reveals_the_error`; `test_ctrl_s_during_conflict_focuses_diagnostics`; `test_ctrl_s_with_confirm_dialog_open_does_nothing`; `test_ctrl_z_with_evidence_lightbox_open_does_not_reload`; `test_held_ctrl_s_issues_one_put` (dispatch a synthetic keydown with `repeat: true` and count PUTs — Playwright's `press` cannot set `repeat`) | `saveInFlight` coalescing; exactly one PUT per settled save. `preventDefault` must precede the repeat bail or the second repeat of a held Ctrl+S opens Save Page As. The listener must keep claiming only `s`, `z`, `y`, because [test_browser.py#L791](../../tests/test_browser.py#L791) depends on the combobox's `stopImmediatePropagation()` at [app.js#L192](../../app/web/static/app.js#L192) |
| 4 | Re-entrancy guard at the **very top** of `undo` and `redo`, ahead of `finalizeTextTransaction()` and the `pop()` | app.js | `test_double_ctrl_z_undoes_exactly_one_action` | A guard after the pop drops an action: the stacks have moved and `storeHistory` has persisted a state the in-memory pair no longer matches. The guard is a module-scope promise, never a DOM flag — `updateHistoryControls` ([L480-L485](../../app/web/static/app.js#L480-L485)) stays the only writer of those buttons' `disabled`. It must not sit between the stack mutation and `restoreHistory`'s rollback ([L500-L512](../../app/web/static/app.js#L500-L512)) |
| 5 | Add `nativeUndoOwner()` beside `activeTextEntry()`; do not modify `activeTextEntry()` | app.js | `test_ctrl_z_in_a_date_field_still_undoes_a_report_action` | `activeTextEntry` keeps its current match set — transaction bookkeeping depends on the over-match being harmless there. Two predicates because there are two questions |
| 6 | **Settling test** — gates step 7, ships as a test before any behaviour change | tests/test_browser.py | Stamp `window.__loadId = Math.random()` in an init script, type, wait for `#save-button[data-save-state="saved"]`, type more, press `ControlOrMeta+z`, then assert **(a)** `__loadId` unchanged — no reload; **(b)** the DOM text reverted; **(c)** after the autosave settles, `main.workspace.load(report_id)` matches the reverted text. Run three times: on a `.rich`, on the list textarea at [L2203](../../app/web/static/app.js#L2203) (sharpest case — its `oninput` rebuilds `fragment.items` by splitting and trimming lines, so a partial revert has somewhere to go wrong), and on a `.rich` whose last action was a toolbar `execCommand("bold")` | **(c) is non-negotiable.** "DOM reverted but model stale" is the exact failure this question exists to rule out, and only a round trip to `draft.json` proves it did not happen. Reading `dataset.report` will not do — that is the boot seed and never changes after load. If (c) fails on any target browser, step 7 does not ship and the fallback is the separate chord (Ctrl+Alt+Z for report undo, which the current listener already ignores via its `altKey` bail), **not** "leave as-is", which is the most destructive option on the table. One cheaper variant exists — re-dispatching a synthetic `input` after allowing the native undo, so the commit does not depend on the browser emitting one — but it needs its own settling test, and the chord is the default until that test is run |
| 7 | Scope `z` and `Shift+Z` by `nativeUndoOwner()`: return early **without** `preventDefault()` | app.js | `test_ctrl_z_in_a_text_field_uses_native_undo` (no reload, model matches); `test_ctrl_z_outside_a_text_field_undoes_report_action`; `test_native_undo_in_scope_textarea_does_not_open_the_loss_dialog` | Conditional on step 6 and on open question 1. The scope textarea is the one field where undo and a confirmation dialog can meet: its `onchange` at [L1368](../../app/web/static/app.js#L1368) compares against a `scopeTextBefore` snapshot taken on `focus` ([L1367](../../app/web/static/app.js#L1367)) and opens `confirmScopeTextLoss` on commit. `change` does not fire on undo, only on commit, so a native undo updates the model and leaves the commit check comparing against the focus-time value — correct, and worth pinning |
| 8 | Shortcut hints on `#undo-button` and `#redo-button` `title` only, in all three templates. **No save-button hint** | three templates | Existing accessibility assertions | **Corrected from Round 1, which claimed this was "covered by existing assertions" when it in fact breaks four of them.** `setSaveState`'s strings are pinned exactly: `"Unsaved changes"` ([L205](../../tests/test_browser.py#L205)), `r"^Saved \d{2}:\d{2}$"` anchored at both ends ([L211](../../tests/test_browser.py#L211)), a `title` starting `"Last saved "` ([L212](../../tests/test_browser.py#L212)), and `"Save failed - Retry"` ([L770](../../tests/test_browser.py#L770)). Folding a hint into that string fails all four. Given open question 5's own default is silence, drop the hint rather than rewrite the assertions. Also: a markup `title` on `#save-button` is futile regardless — `setSaveState` overwrites it on every call, including once at module load. And keep `"Undo last change"` as a substring of `aria-label`, because four locators resolve the button by accessible name ([L346](../../tests/test_browser.py#L346), [L351](../../tests/test_browser.py#L351), [L744](../../tests/test_browser.py#L744), [L747](../../tests/test_browser.py#L747)) |
| 9 | Ctrl+Y alias | app.js | `test_ctrl_y_redoes` | Conditional on open question 3. Same modal, repeat and re-entrancy guards; no separate code path |
| 10 | Update [docs/DATA_MAP.md](../DATA_MAP.md) sections 9 and 10 | DATA_MAP.md | n/a | **Ships in the same change as step 7, not after.** Section 9's "regardless of focus, so native undo is suppressed" is true today and is falsified only by step 7 |

### How Ctrl+S dispatches

Extract, do not `.click()`, and do not call `save()` directly. `requestManualSave()` owns exactly the three behaviours a keyboard save needs: conflict routing (focus `#app-diagnostics` instead of firing a save the `saveConflict` guard would swallow silently), `validateSetupInputs(true)` (paint, scroll to and focus the first invalid field), and `saveRetryCount = 0` (a deliberate save restarts the backoff budget without an edit). Step 2 adds the fourth: reveal the stranding notice.

| State when Ctrl+S is pressed | What happens |
|---|---|
| `unsaved` | `requestManualSave()` runs; button goes `saving` then `saved`. Identical to a click |
| `saved` (button disabled) | `preventDefault()` still fires so Save Page As never appears; `save()` returns `true` at [L623](../../app/web/static/app.js#L623) without a PUT. Nothing visible happens, which is the truth |
| `failed` | Retry budget resets and a fresh PUT is attempted. This is the case where a keyboard save earns its keep |
| `conflict` unresolved | Focus moves to `#app-diagnostics` and its *Save my version* / *Load latest* choices. No PUT, and — unlike a bare `save()` — the tester sees why |
| Modal open (`vrDialog` or lightbox) | `preventDefault()`, then return |
| Setup, invalid field | Reveal-mode validation scrolls to and focuses the offender; no PUT |
| Setup, stranded finding | The notice names the finding and scrolls into view; no PUT |

---

## 6. What I would not do

- **Bind Ctrl+S to `#save-button.click()`.** It works today only because `disabled` happens to coincide with "nothing to save" — incidental, not designed — and it couples the keyboard to a DOM attribute whose meaning can drift.
- **Justify the `event.repeat` guard with backup exhaustion.** That justification is false: a repeated Ctrl+S issues zero extra PUTs, because only an edit bumps `saveRevision`. Keeping the wrong reason in the table would mislead whoever reads it next. The guard is for undo.
- **Fold a shortcut hint into the string `setSaveState` writes.** Four assertions pin those strings exactly; the hint buys a tooltip and costs four test rewrites.
- **Reuse `activeTextEntry()` as the undo-scoping predicate.** It matches date inputs, which have no native undo stack, turning a working key into a dead one.
- **Place the re-entrancy guard after the `pop()`.** The stacks have already moved and already been persisted; the second keypress is then silently discarded along with its action.
- **Touch `aria-label="Undo last change"`.** Four locators resolve on it.
- **Claim `applyCanonicalReport` drops the caret.** No path in source re-reads the object graph into a focused DOM node on the save path, and `scope_text` is excluded from reconciliation. The test stays, as a proof rather than a repair.
- **Write the stranding message into `#setup-validation-note` directly from `requestManualSave`.** That would be a second writer racing `updateSetupValidationNotice`, which re-renders on every `input` and `change` and would erase it on the next keystroke.
- **Attempt to merge or arbitrate the native and app undo stacks.** There is no API to read, count or test the native stack; `document.execCommand("undo")` is deprecated and reports nothing. Every fall-through heuristic eventually eats a report-level action at the worst moment.
- **Remove the `window.location.reload()` from `restoreHistory` here.** It is how server-derived state and the page gate are re-read after an undo. It deserves to go, but not bundled with a keyboard binding.
- **Add a toast or snackbar.** The save button is the single status surface; a second one drifts out of agreement with the first.
- **Implement the re-entrancy guard by disabling the buttons.** `updateHistoryControls` owns `disabled`; a second writer would fight it.

## Answers

1. **Ctrl+Z inside text entry — hand it to the browser.** Inside real text entry the browser owns undo, so Ctrl+Z takes back a word instead of discarding the whole field and reloading. Report-level undo stays available on the Undo button, which blurs the field and finalizes the transaction first. Two consequences accepted with this: the first Ctrl+Z in a rich-text body may reverse a `execCommand` formatting command or a paste rather than a word, and the whole step is **gated on the settling test** — if the browser does not commit a native undo back into the model, the fallback is the separate `Ctrl+Alt+Z` chord, not the status quo.
2. **Suppress both keys while a modal is open** — the `vrDialog` overlay and the native `<dialog>` evidence lightbox alike. Ctrl+S still calls `preventDefault()` so the browser's Save Page As never appears over the modal.
3. **Add Ctrl+Y** as a redo alias alongside the existing Ctrl/Cmd+Shift+Z.
4. **Leave the home page and the library editor alone.** The library-editor gap is recorded rather than fixed: Ctrl+S there opens Save Page As next to an unsaved form and a visible "Save entry" button. Parity is a `form.requestSubmit()` binding in that page's inline script and belongs in its own change.
5. **Stay silent** when Ctrl+S is pressed with nothing to save. No CSS change, no pulse. The save-button label hint is dropped regardless, because four assertions pin those strings exactly.
6. **The conflict path stays identical to the button's behaviour** — focus moves to `#app-diagnostics` with `preventScroll: true`. If that panel is off-screen it looks inert, but the keyboard path must not diverge from the click path; fixing the scroll is a separate change affecting both.

## Agreed plan

**What this delivers.** Ctrl/Cmd+S saves, behaving exactly as the Save button does. Ctrl/Cmd+Z stops destroying a field's entire editing session — inside text entry the browser's own undo takes the key. Ctrl/Cmd+Y joins Ctrl/Cmd+Shift+Z as redo. Both keys go inert while a modal is open, and neither can double-fire from a held key.

**Scope boundaries.** Browser-side only: no server file, no new persisted field, no endpoint, no migration. Nothing on disk or in browser storage changes shape, so every existing `draft.json` loads unchanged. No Python/JavaScript twinned rule is modified — which holds only because the shortcuts call the existing shared functions and re-implement no gate.

Steps are ordered so the app is never in a state where a shortcut exists with a silent or destructive path behind it.

### 1. Extract `requestManualSave()`
**Files:** [app.js](../../app/web/static/app.js) L691-702.
Pull the `#save-button` click body into a named function and rebind the button to it, so the keyboard and the button share one path. It owns three behaviours `save()` does not: conflict routing, `validateSetupInputs(true)` reveal mode, and `saveRetryCount = 0`.
**Test:** every existing save-button case passes unchanged, plus `test_manual_save_resets_retry_budget_without_an_edit`.
**Invariant:** a manual save must be able to reset the retry budget **without an edit**. (Not "autosave never resets it" — shipped code already zeroes it on every edit at L590 and again at L651. A reset with no edit behind it is the button's only unique contribution.)

### 2. Give the stranding refusal a visible surface
**Files:** [app.js](../../app/web/static/app.js) L532-559.
`updateSetupValidationNotice` gains one message line composed from `strandedByScopeEdit()`; `requestManualSave` sets `validationAttempted` and scrolls `#setup-validation-note` into view when the stranding guard refuses. Today that refusal only relabels a button that can be scrolled off a long Setup page, and `validateSetupInputs` cannot help — it matches invalid *inputs*, while stranding names *findings*, which do not exist in the Setup DOM.
**Test:** `test_manual_save_with_stranded_finding_names_it_in_the_setup_notice` — the finding's title appears in the notice and the notice is in the viewport.
**Invariant:** `updateSetupValidationNotice` stays the sole writer of `#setup-validation-note`; the autosave path is untouched, so the notice never reveals itself without a deliberate manual attempt. Ships **before** step 3 so the shortcut never exists with a silent refusal behind it.

### 3. Add the Ctrl+S branch and the shared guards
**Files:** [app.js](../../app/web/static/app.js) L770-774.
Add the `s` branch, the modal guard `document.querySelector("[data-dialog], dialog[open]")` — which must cover the native `<dialog>` lightbox, not just `[data-dialog]` — and `event.preventDefault()` **before** `if (event.repeat) return;`.
**Tests:** `test_ctrl_s_saves_and_suppresses_browser_dialog`; `test_ctrl_s_on_setup_with_invalid_field_reveals_the_error`; `test_ctrl_s_during_conflict_focuses_diagnostics`; `test_ctrl_s_with_confirm_dialog_open_does_nothing`; `test_ctrl_z_with_evidence_lightbox_open_does_not_reload`; `test_held_ctrl_s_issues_one_put` (synthetic keydown with `repeat: true`, counting PUTs — Playwright's `press` cannot set `repeat`).
**Invariants:** `saveInFlight` coalescing, exactly one PUT per settled save. `preventDefault` precedes the repeat bail, or the second repeat of a held Ctrl+S opens Save Page As. The listener keeps claiming only `s`, `z`, `y` — the library combobox's Enter handling depends on `stopImmediatePropagation()` at L192.

### 4. Re-entrancy guard on undo and redo
**Files:** [app.js](../../app/web/static/app.js) L747-767.
A module-scope promise guard at the **very top** of both functions, ahead of `finalizeTextTransaction()` and the `pop()`.
**Test:** `test_double_ctrl_z_undoes_exactly_one_action`.
**Invariant:** a guard placed after the pop drops an action — the stacks have already moved and `storeHistory` has already persisted a state memory no longer matches. It must also not sit between the stack mutation and `restoreHistory`'s rollback. It is a promise, never a DOM flag: `updateHistoryControls` stays the only writer of those buttons' `disabled`.

### 5. Add `nativeUndoOwner()`
**Files:** [app.js](../../app/web/static/app.js) L577-580.
A new allow-list predicate beside `activeTextEntry()`: `textarea`, `[contenteditable="true"]`, and `input` whose type is absent or one of text / search / url / email / tel / password. `activeTextEntry()` itself is **not** modified.
**Test:** `test_ctrl_z_in_a_date_field_still_undoes_a_report_action`.
**Invariant:** `activeTextEntry` over-matches `input[type="date"]`, which has no native undo stack. Reusing it would turn a working key into a dead one on the test-window dates. Two predicates because there are two questions: over-matching is harmless for transaction bookkeeping and harmful for "who owns undo here". An allow-list, so a future input type defaults to the working behaviour.

### 6. Settling test — gates step 7
**Files:** [tests/test_browser.py](../../tests/test_browser.py).
Stamp `window.__loadId = Math.random()` in an init script, type, wait for `#save-button[data-save-state="saved"]`, type more, press `ControlOrMeta+z`, then assert **(a)** `__loadId` unchanged — no reload; **(b)** the DOM text reverted; **(c)** after the autosave settles, `main.workspace.load(report_id)` matches the reverted text. Run on three surfaces: a `.rich` body; the list textarea at L2203 (sharpest — its `oninput` rebuilds `fragment.items` by splitting and trimming lines); and a `.rich` whose last action was a toolbar bold.
**Invariant:** **(c) is non-negotiable.** "DOM reverted but model stale" is the exact failure this exists to rule out, and only a round trip to `draft.json` proves it did not happen — reading `dataset.report` will not do, as that is the boot seed and never changes after load. Source already settles the other half: every text control commits on `input` and nothing in `app.js` reads `event.inputType`, so a `historyUndo` is consumed exactly like typing and pushes no new undo entry. **If (c) fails on any target browser, step 7 does not ship and the fallback is `Ctrl+Alt+Z` for report undo** (the current listener already ignores Alt), not "leave as-is".

### 7. Scope Ctrl+Z to `nativeUndoOwner()`
**Files:** [app.js](../../app/web/static/app.js) L770-774. Conditional on step 6 passing.
When `nativeUndoOwner()` matches, return early **without** `preventDefault()`, so the browser's undo wins.
**Tests:** `test_ctrl_z_in_a_text_field_uses_native_undo` (no reload, model matches); `test_ctrl_z_outside_a_text_field_undoes_report_action`; `test_native_undo_in_scope_textarea_does_not_open_the_loss_dialog`.
**Invariant:** the scope textarea is the one field where undo and a confirmation dialog can meet — its `onchange` compares against a `scopeTextBefore` snapshot taken on focus and opens `confirmScopeTextLoss` on commit. `change` does not fire on undo, only on commit, so a native undo updates the model and leaves the commit check comparing against the focus-time value. Correct, and worth pinning.

### 8. Shortcut hints on the undo and redo buttons
**Files:** [page1_setup.html](../../app/web/templates/page1_setup.html), [page2_findings.html](../../app/web/templates/page2_findings.html), [page2_editor.html](../../app/web/templates/page2_editor.html) — three verbatim copies of the header, not a shared include.
`title` only, on `#undo-button` and `#redo-button`. **No save-button hint.**
**Invariant:** do not touch `aria-label`; four test locators resolve those buttons by accessible name, which comes from `aria-label` and not `title`. A markup `title` on `#save-button` is futile anyway — `setSaveState` overwrites it on every call — and folding a hint into its label string would fail four assertions that pin `"Unsaved changes"`, `r"^Saved \d{2}:\d{2}$"`, a `title` starting `"Last saved "`, and `"Save failed - Retry"`.

### 9. Ctrl+Y redo alias
**Files:** [app.js](../../app/web/static/app.js) L770-774.
**Test:** `test_ctrl_y_redoes`.
**Invariant:** same modal, repeat and re-entrancy guards as `z`; no separate code path.

### 10. Update the data map
**Files:** [docs/DATA_MAP.md](../DATA_MAP.md) sections 9 and 10.
**Invariant:** **ships in the same change as step 7, not after.** Section 9's sentence that the listener "calls `preventDefault()` regardless of focus, so native undo is suppressed" is true today and is falsified only by step 7.

### Deliberately not done

- **No Ctrl+S on the library editor or the home page** (Answer 4). The library-editor inconsistency is recorded, not fixed.
- **No acknowledgement when there is nothing to save** (Answer 5).
- **No scroll fix on the conflict panel** (Answer 6) — it would change the button's behaviour too and belongs in its own change.
- **No removal of the `window.location.reload()` in `restoreHistory`.** It is how server-derived state and the page gate are re-read after an undo. It deserves to go, but not bundled with a keyboard binding.
- **No attempt to merge the native and app undo stacks.** There is no API to read or test the native stack; every fall-through heuristic eventually eats a report-level action at the worst moment.
- **No bespoke "is it safe to save?" test in the key handler.** Those rules already exist twice, in Python and JavaScript; a third copy is drift waiting to happen.

Tests use Playwright's `ControlOrMeta` modifier so macOS and Linux CI agree. No test in the suite presses a modifier key today, so every case above is new and collides with nothing.
