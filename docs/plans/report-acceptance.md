# Report acceptance: one module for what a save must pass

> **Status:** done · 2026-10-02 · `af37291`
>
> **From:** [One module accepts every draft on the write path](../../.scratch/architecture-review/issues/02-one-module-accepts-every-draft-on-the-write-path.md)
>
> **What deviated.**
> - `save_report` now hands `save_if_current` the stored revision instead of `client_saved_at or
>   prior.saved_at`. It is the same value: `acceptance.check` has already refused any other revision
>   the body named, and a body naming none always fell back to the stored one.
> - More doc edits than the agreed list. These now name acceptance: the **Server** line in
>   `.github/copilot-instructions.md`, the Saving and editable-import passages in
>   `docs/ARCHITECTURE.md`, the PUT row and editable-import passage in `docs/ROUTES.md`, and the file
>   list in DATA_MAP's maintenance note. The data-layer instruction gained a line saying that a
>   change to what `acceptance.check` refuses, or to its order, needs a DATA_MAP update.
>
> **2026-10-02, later the same day:** Q13 called `loremaster`, `scribe`, `tactician` and `invader`
> retired, reflecting that Claude Code had no wrappers for them at the time. They were restored
> (Claude wrappers added in `.claude/agents/`) the same day; "retired" no longer holds, and the
> reference-cleanup follow-up it implied does not apply.

## Request

Candidate 2 from the architecture review of 2026-10-02. A save's checks and provisioning ran as ten
inline steps in the PUT route, and `finalize_editable_import` repeated seven of them by hand. Move
the sequence into one module that both call, without changing behaviour. The decisions below came
from a grilling session. No planning agents ran, because the specialist agents are no longer used.

## Answers

- **Q1, where the module stops:** rules only. It takes the stored report and the submitted version,
  and returns the checked report or raises a refusal. Each caller does its own write.
- **Q2, move or fix:** move only. Same steps, order, messages and status codes. Behaviour changes
  become later changes.
- **Q3 and Q5, the name:** Report acceptance, `app/acceptance.py`. GLOSSARY.md defines Acceptance,
  Refusal and Provisioning. Considered and not chosen: save rules, save preparation, report intake.
- **Q4, home:** its own file.
- **Q6, interface:** two steps, `check` and `provision`, because the editable import needs the
  report between them. Accepted consequence: an editable import that fails both its location check
  and a field check now names the fields. A test pins it.
- **Q7, refusals:** `Refusal`, a `ValueError`, with one subclass per rule carrying its data:
  `InvalidScope`, `ScopeTargetRemoved` and `InvalidFields`. Callers write the words. A stale body
  raises `StaleReportError`, and pydantic's `ValidationError` passes through. `InvalidFields` carries
  the Setup and finding lists together.
- **Q8, callers now:** the PUT save and the editable import. Bundle imports, retest DOCX imports,
  library insert and rename keep their current paths; see Follow-ups.
- **Q9, tests:** every existing test stays. The 29 browser fixture calls use `acceptance.provision`.
  New tests call the module directly.
- **Q10:** the explicit `normalise_scope_modes` calls in both callers go, because validating gives
  the same report without them. The one in `repair_duplicate_fragment_ids` stays.
- **Q11:** this plan was written from the grilling session, with no agent rounds.
- **Q12:** the follow-ups are listed here and filed under `.scratch/report-acceptance/issues/`.
- **Q13:** references to the retired agents in the data-layer instruction, DATA_MAP and
  copilot-instructions are left for a separate cleanup.

## Agreed plan

- [x] 1. Add `app/acceptance.py` with `check`, `provision`, `Refusal`, `InvalidScope`,
  `ScopeTargetRemoved` and `InvalidFields`.
- [x] 2. `save_report` copies the stored id and app id onto the body, calls `check`, names an
  unnamed report, calls `provision`, and writes with `save_if_current`. Remove
  `main.provision_report`.
- [x] 3. `finalize_editable_import` calls `check` and `provision`, keeping its three fidelity checks,
  its notice and its second provisioning pass.
- [x] 4. Drop the two explicit `normalise_scope_modes` calls and correct its docstring.
- [x] 5. Tests: `tests/test_acceptance.py`, with each refusal beside a passing case, provisioning,
  and the retired-scope order; `test_editable_preflight_names_invalid_fields_before_scope_reconciliation_loss`;
  the 29 fixture calls in `test_browser.py`.
- [x] 6. Docs: DATA_MAP §5, §7, §8, §12, its verification note and its maintenance note; the
  data-layer instruction's `applyTo` and invariant, regenerated into `.claude/rules/`; the Saving
  and editable-import passages in ARCHITECTURE.md; the PUT row and editable-import passage in
  ROUTES.md; GLOSSARY.md.
- [x] 7. File the four follow-ups.

## Follow-ups

Each changes behaviour, so each needs its own decision first.

1. [Bundle imports run acceptance](../../.scratch/report-acceptance/issues/01-bundle-imports-run-acceptance.md)
2. [Retest DOCX imports run acceptance](../../.scratch/report-acceptance/issues/02-retest-docx-imports-run-acceptance.md)
3. [Library insert runs acceptance](../../.scratch/report-acceptance/issues/03-library-insert-runs-acceptance.md)
4. [Rename runs acceptance](../../.scratch/report-acceptance/issues/04-rename-runs-acceptance.md)
