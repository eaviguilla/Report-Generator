# Limitations suggestion, and non-production labels as free text

> **Status:** shipped · 2026-09-17 · `330d7d9`

Two changes to the Setup page, coupled by one non-obvious constraint: the second writes the
label into the first's field, so the label's legal characters are bounded by the Limitations
rule, not just by what Word can print.

## Settled decisions

1. **The suggested sentence follows the tester's label**, uppercased — not a fixed "NON-PROD".
   With the new default it reads exactly as asked; a tester who picks UAT gets a report whose
   Limitations agrees with its own evidence headings.
2. **One validated text field**, not a closed set plus an override. `OTHERS` is a dropdown
   affordance and is never stored; whatever is stored *is* the label.
3. **DOCX import learns the known labels** and adopts whichever it matched. This also repairs the
   same bug for `TEST/MO` and `DEV`, which is already live today.
4. Showcase script moves to presets (`MOD`, `STAGE`). The banner offers on empty as well as `N/A`.

## What stays out

**No persisted dismissal field.** The banner's whole condition is "has the tester written
limitations yet", which is readable from the field itself. `conclusion_offer_resolved` had to be
persisted because it records *which text* was put to the tester and a list item has nothing stable
to point at; here there is one string. A field would also be permanent: the comment on
`content_offer_resolved` records why a declared field cannot later be dropped. A dismissal held in
a module-local `Set` does not survive a reload, which is the same trade the Content page makes.

**No Python twin for the sentence.** `status_conclusion_runs` has a Python half for one reason:
`provision` re-derives the conclusion on every save, so the server must recognise its own sentence
to avoid overwriting the tester. Nothing re-derives `limitations` — `provision_report` touches
vulnerabilities only, and `docx_report` prints the string verbatim. A Python copy would be a rule
with no enforcement point.

**No uppercasing on save.** The value stays as typed; `_environment_label` uppercases at render.
A field that rewrites itself as you type is the most irritating thing a text input can do.

**No `load_path` repair.** Widening the type is strictly permissive, every stored value still
validates, and a repair rewrites the file — burning the single `draft.bak.json` level for a no-op.

## New rules that exist twice

| Rule | Twin? |
|---|---|
| Label character set | **Yes, unavoidable.** Client-only lets a hand-edited value through; Python-only turns a typo into a 422 the tester cannot pre-empt. Same shape as `limitations`. |
| Preset list | **Weak yes**, created by decision 3. Canonical tuple in `models.py`, imported by `docx_import`. |
| Default `"NON-PROD"` | No — the server always sends a value, so the client needs no seed. |
| "OTHERS is never stored" | No. Client-only by construction; the server cannot tell a sentinel from a tester who genuinely labels their environment OTHERS. |
| The suggested sentence | No. Client-only, per above. |

## Character set

Letters, digits, space, hyphen, slash — reusing the existing `userRole` pairing verbatim rather
than inventing one. Four constraints pin it:

- **Must be a subset of the Limitations set**, or an accepted suggestion 422s the next save.
- **Slash is already proven** — `TEST/MO` renders as `TEST/MO:` today with no escaping.
- **Colon must be excluded** — the import matcher builds `f"{label.upper()}:"`, so a colon
  produces a doubled heading and collides with `INSTANCE_PREFIX` handling.
- **No newlines, no empty** — a newline splits the heading; `"".upper()` renders a bare `:`.

Trim on input: the importer compares against `.strip()`ped document text, so a stored `" UAT"`
renders `" UAT:"`, reads back as `"UAT:"`, and fails to match.

## Steps

Ordered so no intermediate state has a failing save.

1. **Widen the model.** `models.py` — `NonProductionLabel` becomes a bounded `str`, default
   `"NON-PROD"`, with a stripping validator; add `NON_PRODUCTION_LABEL_PRESETS`.
   *Test:* `tests.test_app`, the optional-setup-defaults test. Prove an existing `"UAT"` draft
   still loads by loading one, not by reasoning about it.
2. **Repair the test that rides the old default.** `tests/test_docx.py` asserts `"UAT:"` appears
   twice while its fixture never sets the label. Pin the label in the fixture so it tests the
   renderer. *Test:* `tests.test_docx`.
3. **Server character rule**, gated on `"non_production" in tested_environments`, mirroring the
   `test_windows` loop. *Test:* `tests.test_app` character-validation test, plus a case proving the
   label is not validated while non-production is unselected.
4. **JavaScript twin** of that rule in `setupRules`, wired with `wireSetupRule`.
   *Test:* `tests.test_browser` setup-character test — its assertion that the browser message is
   byte-identical to the server's is this twin's only drift guard.
5. **Dropdown plus OTHERS.** Free text appears when the stored value is not a preset **or** OTHERS
   is picked, pre-filled. *Test:* new browser test. The invariant that matters: **opening Setup
   never changes the stored label** — assert on the saved value, not the control.
6. **Import recognises the known labels.** *Test:* new `tests.test_docx_import` test round-tripping
   a non-prod evidence image; the existing fixture is production-only.
7. **Showcase script** to presets. No test; run it once by hand.
8. **Hoist `buildOffer` / `offerButton`** to module scope — they are pure, but live inside
   `continuousEditor()`, which never runs on Setup. *Test:* an existing Content offer test;
   `refreshContentOffers` compares `outerHTML`, so markup drift would swap buttons under clicks.
9. **CSS**: add `#setup > section > .content-offer` to the three inline-margin selector lists, or
   the banner sits flush while everything around it is inset. *Test:* none.
10. **Render the offer** inside `setup()`, inserted before `.limitations-field`, hooked to
    `reportchange`, guarded by `activeTextEntry()` because the banner sits directly above the
    textarea. *Test:* new browser test. **The banner never writes on render — only the button.**
11. **Accept via a dispatched `input` event**, not by assigning `.value`. Assignment fires no event,
    so a field left invalid by earlier typing keeps its `setCustomValidity` message and `save()`
    refuses a value that is now clean.
12. **`docs/DATA_MAP.md`** §6 and §12, plus the "Last verified" line.

## Known limitation

A tester who types a custom label still gets the broken import round trip — the heading is the
label's only appearance in the document, and there is nothing else to recover it from. They can
correct the label in Setup after importing.
