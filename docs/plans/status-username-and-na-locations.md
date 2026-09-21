# Open (Resolved on Non-Prod), username spaces, and N/A as a bulleted list

> **Status:** shipped · 2026-09-21 · `e998ab5`
>
> All seventeen agreed steps landed. Four things deviated, and the first is the one worth reading.
>
> **Step D3 was wrong as written, and a failing test found it.** The plan said to normalise the
> detail Status cell and "carve out the case where both labels are official but different". Doing
> exactly that still refused the motivating document: when only the summary cell is hand-edited, the
> untouched detail cell holds a label this app *knows*, which then disagrees with the fallback. The
> condition had to be inverted — compare the two cells **only when both** name a known status —
> rather than carved out. The plan's own test for D3 is what caught it.
>
> **A test was replaced rather than updated.** The round 3 plan had
> `test_malformed_editable_import_writes_no_report_directory` updated to assert a new refusal reason.
> Once R2 became R2′ its whole premise — an unknown status refuses — was the behaviour being removed,
> so it is now `test_an_unrecognised_status_is_assumed_rather_than_refusing_the_document` and proves
> the import succeeds, assumes Previously Discovered, pads the sections, and warns. The "malformed
> writes nothing" guarantee it used to carry is still held by the two truncated-row tests beside it.
>
> **Step B1's test matches on the wrong string from the plan.** The plan said to find the
> "Non-Production Location cell"; the renderer prints the configurable environment name, which is
> "Lower Region Environment:" by default. The test matches on `Environment:` so a renamed environment
> does not break it.
>
> **Two steps were merged in the code.** D4 and D5 both sit in the same `expected_sections` / editable
> branch region and read as one change; they are ticked separately because they protect different
> gates. Nothing was dropped.
>
> Verified: 200 Python tests and 153 browser tests pass. The two failures that remain are the
> pre-existing macOS ones needing Microsoft Word — `test_generate_docx_route_uses_template_and_report_filename`
> and `test_complete_report_saves_generated_docx_to_generated_folder`. **The Word-side round trip for
> the new status is therefore unproven on this machine**: only a generate-then-import on Windows shows
> that `Open (Resolved on Non-Prod)` survives byte-identical, the hyphen in particular.

## Request

Three changes, batched. The user's ask, verbatim:

> do not overcomplicate this
>
> allow spaces in username field
>
> add another option in the finding status. Open (Resolved on Non-Prod)
>
> when generating affected locations, if the affected location of an environment is empty, it prints
> N/A. this is already correct or the current process. but the change I want is that even if it is
> N/A, make it a bulleted list so that it is consistent with non empty affected locations.

Coordinator's note on sizing: **large, and it reaches the document.** Changes 1 and 3 are small on
their own, but change 2 adds a value to the finding status enum — a changed field that decides which
content sections a finding prints and that is written into every saved draft. Both rounds run, and
`scribe` joins round 1 because change 3 is purely a document-layout question and the new status will
reach the document too.

## Round 1 - Oracle: how it works today

### Sizing, plainly

The three are not the same size, and the coordinator's note overstates two of them.

- **Change 1 is trivial.** Four edits in two files: two whole-value shape regexes and two
  per-character allowlists. No model change, no migration, no new twin. Two existing tests assert
  the *current* behaviour (a space is invalid) and must be inverted.
- **Change 3 is trivial and is not in the data layer at all.** The data layer never produces `N/A`
  for affected locations. One early return in the Word pipeline decides it. Nothing in
  `models.py`, `report_service.py`, `workspace.py`, `storage.py`, `main.py` or `app.js` needs to
  change. It is entirely `scribe`'s.
- **Change 2 is the real one.** 38 sites read, label, branch on, or default the status across four
  Python modules and three JavaScript files. Most fall through correctly for free; five are
  exhaustive tables that do not, and one of those raises `KeyError` at generation time.

---

### Change 1 - allow spaces in the username field

#### Where the rule lives: four patterns, not two

Each side carries **two** patterns. One decides valid/invalid; the other exists only to name the
offending character in the message. The planner needs all four or the message and the verdict drift.

**Python - the shape test** ([app/report_service.py](app/report_service.py#L21)):

```python
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._@\\-]*[A-Za-z0-9])?$")
```

**Python - the message allowlist**, inside `setup_input_issues`
([app/report_service.py](app/report_service.py#L185-L187)):

```python
if account.username and account.username != "N/A" and not USERNAME_PATTERN.fullmatch(account.username):
    issue = invalid_character_issue(f"Username {index}", account.username, "._@\\-", allow_spaces=False)
    issues.append(issue or f"Username {index} must start and end with a letter or number")
```

**JavaScript - the message allowlist** ([app/web/static/app.js](app/web/static/app.js#L1472)):

```javascript
const usernameCharacters = characterRule("Username", /^[A-Za-z0-9._@\\-]$/);
```

**JavaScript - the shape test**, folded into the same rule object
([app/web/static/app.js](app/web/static/app.js#L1497)):

```javascript
username: {...usernameCharacters, valid:value => !value || value === "N/A" || /^[A-Za-z0-9](?:[A-Za-z0-9._@\\-]*[A-Za-z0-9])?$/.test(value), message:label => `${label} must start and end with a letter or number`},
```

Both character classes contain `\\`, which is one literal backslash inside a class - the set is
letters, digits, `.`, `_`, `@`, `\`, `-`. The backslash is there for `DOMAIN\user`, and
[tests/test_app.py](tests/test_app.py#L258) pins `DOMAIN\qa.user@example` as a value that must save.

The **smallest correct change is four edits**: add a space to the interior class of both shape
regexes, add a space to the JS per-character regex, and drop `allow_spaces=False` from the Python
`invalid_character_issue` call (its default is `True` -
[app/report_service.py](app/report_service.py#L128-L135)). Nothing else.

One pre-existing asymmetry to leave alone: Python's message allowlist tests `str.isalpha()`, so it
accepts any Unicode letter, while `USERNAME_PATTERN` is ASCII-only. A value like `josé` therefore
fails the shape test but yields no invalid character, falling through to
`"must start and end with a letter or number"`, whereas the browser's ASCII-only per-character
regex names `é` as invalid. The two sides already print different sentences for that input. Adding a
space does not touch it, and fixing it is not part of this request.

#### What else the rule constrains

Nothing where a space is unsafe.

- **Not a filename, not a path.** `report_export_filename` builds from segment, application name,
  report type and year only ([app/report_service.py](app/report_service.py#L228-L241)). The folder
  names derive from `app_name` and `report_type`. `engagement.tester` is a different field from
  `test_accounts[].username`. Username reaches no path segment anywhere.
- **It is a DOCX token**, twice, and both are plain text substitution:
  `values[f"username{index + 1}"]` ([app/docx_report.py](app/docx_report.py#L298)) and the
  test-accounts table cell ([app/docx_report.py](app/docx_report.py#L476)). The column beside it,
  `user_role`, **already allows spaces** today - its rule is
  `invalid_character_issue(f"User role {index}", account.user_role, "/-")` with `allow_spaces`
  defaulting to `True` ([app/report_service.py](app/report_service.py#L184)), and
  [tests/test_app.py](tests/test_app.py#L258) saves `"Admin-2 / QA"`. So the document already
  carries spaces in that table.
- **Round-trip from a generated document** reads both cells back verbatim through `_visible_value`
  and maps blank to `"N/A"` ([app/docx_import.py](app/docx_import.py#L513-L519)). `scribe` should
  confirm there is no whitespace splitting on the way back, but the shape of the code says there is
  not.

#### How `N/A` and the start/end rule interact with interior spaces

- **`N/A` is exempt by literal comparison on both sides** - `account.username != "N/A"`
  ([app/report_service.py](app/report_service.py#L185)) and `value === "N/A"`
  ([app/web/static/app.js](app/web/static/app.js#L1497)) - because `/` is not in the allowed set and
  never will be. Adding a space changes nothing here; the exemption is still required. It is also
  the field's default ([app/models.py](app/models.py#L190-L191)) and the recovery fallback
  ([app/web/static/app.js](app/web/static/app.js#L1557)).
- **The anchors keep leading and trailing spaces invalid**, which is the half worth keeping:
  `^[A-Za-z0-9] ... [A-Za-z0-9]$` still refuses `" admin"` and `"admin "`. A one-character username
  still passes, because the middle group is optional.
- **The cost is a mid-typing 422.** `setup_input_issues` runs on every `PUT` and returns 422
  `invalid_setup` ([app/main.py](app/main.py#L782-L789)), autosave fires on a 5000 ms idle timer,
  and **nothing on the client blocks a save on setup rules** - `validateSetupInputs`
  ([app/web/static/app.js](app/web/static/app.js#L1514-L1525)) is reached only through
  `validateSetupPage` ([app/web/static/app.js](app/web/static/app.js#L2707)), which only `#next`
  calls. So while the value sits at `"john "` on the way to `"john smith"`, the backend save is
  rejected. This is **not new in kind** - `"john."` does exactly the same today - but a trailing
  space is a far more natural pause point than a trailing dot, so it will be hit. Two honest
  options: accept it (the value settles and the next autosave succeeds), or strip the username
  before validating. I am not recommending; that is the planner's call.

#### Invariants in play

- `TestAccount.username` is a plain `str` with the default `"N/A"`
  ([app/models.py](app/models.py#L190-L191)). There is no length bound and no `field_validator`; the
  entire rule is the save-time check above.
- The rule runs **at save, not at load**. A hand-edited draft with an illegal username loads fine
  and then 422s - the same behaviour every other Setup field has.
- Widening a character set is strictly permissive, so every value that validated before still does.
  No `load_path` repair is needed and adding one would be wrong: it would rewrite every draft to
  change nothing and burn the single `draft.bak.json` level.

#### What drafts on disk look like

22 files carry a username. **20 hold exactly `"N/A"`.** The only two real values are `qa.customer`
and `qa.admin`, in
`data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json`. Nothing on disk
contains a space, so no draft changes meaning.

#### Both-sides warning

`USERNAME_PATTERN` ([app/report_service.py](app/report_service.py#L21)) and `setupRules.username`
([app/web/static/app.js](app/web/static/app.js#L1497)) are a named twin in
[docs/DATA_MAP.md](docs/DATA_MAP.md) §12. The per-character halves -
`invalid_character_issue(..., "._@\\-", allow_spaces=False)`
([app/report_service.py](app/report_service.py#L186)) and `usernameCharacters`
([app/web/static/app.js](app/web/static/app.js#L1472)) - are a **second, unnamed twin**, and they
are what produce the message text. The drift guard is
`tests/test_browser.py::test_setup_inputs_report_character_and_date_errors_before_save`, which
asserts the browser's `validationMessage` is byte-identical to the server's issue string.

**Two tests assert the behaviour being removed and must be inverted in the same change:**

- [tests/test_app.py](tests/test_app.py#L236) - `{"user_role": "Admin", "username": "bad user"}`
  must produce `'Username 1 contains invalid character: " " (space)'`.
- [tests/test_browser.py](tests/test_browser.py#L133) - the same string, as a browser
  `validationMessage`, with `"bad user"` as the invalid value and `"DOMAIN\qa.user@example"` as the
  valid one.

---

### Change 2 - a fourth finding status, `Open (Resolved on Non-Prod)`

#### The enum

[app/models.py](app/models.py#L10):

```python
Status = Literal["open_new", "open_previously_discovered", "resolved"]
```

The field is `status: Status = "open_new"` ([app/models.py](app/models.py#L207)). A closed `Literal`
with a default, no `field_validator`, no before-validator normalisation, and **no legacy token
table** - unlike `Channel` (which has `LEGACY_TEST_TYPE_CHANNELS`) and `Scope.mode` (which has
`RETIRED_SCOPE_MODES`). A status value is what it says it is.

#### Every site that enumerates, labels, branches on, or defaults the status

The critical distinction is between **fall-through sites** (written as `== "open_new"` or
`== "resolved"`, so a fourth value automatically lands in the other arm) and **exhaustive sites**
(a table or tuple that must be extended or the value is invisible, mislabelled, or fatal).

**Python - data layer**

| Site | What it does | New value |
|---|---|---|
| [app/models.py](app/models.py#L10) | the `Literal` | **must extend** |
| [app/models.py](app/models.py#L207) | `status: Status = "open_new"` | unchanged |
| [app/report_service.py](app/report_service.py#L251-L256) `content_types_for_status` | `if status == "open_new"` return 3 sections, else return 5 | falls through to the 5-section arm |
| [app/report_service.py](app/report_service.py#L283) `provision` | calls the above | free |
| [app/report_service.py](app/report_service.py#L313) `provision` | `if vulnerability.status == "resolved"` writes `RESOLVED_REMEDIATION` with `generated="resolved_remediation"`, else strips it | falls through to the editable arm |
| [app/report_service.py](app/report_service.py#L326) `provision` | `status = "Resolved" if ... == "resolved" else "Open"` for the conclusion sentence | falls through to `"Open"` |
| [app/report_service.py](app/report_service.py#L806) `finding_is_complete` | truthiness only (`and vulnerability.status`) | free |
| [app/workspace.py](app/workspace.py#L292-L296) `load_path` | `if stale and vulnerability.get("status") == "resolved"` marks the legacy boilerplate paragraph; **`elif stale` empties its runs and rewrites the file** | falls through to the emptying arm - see the sharp edge below |
| [app/main.py](app/main.py#L262-L266) `provision_report` | does **not** branch on status at all | free |

**Python - document layer** (`scribe` owns the detail; listed so the planner has the complete set)

| Site | What it does | New value |
|---|---|---|
| [app/docx_report.py](app/docx_report.py#L48-L52) `STATUS_LABELS` | three-key dict | **must extend** |
| [app/docx_report.py](app/docx_report.py#L516) | `STATUS_LABELS[finding.status]` in the summary table | **bare index - `KeyError` at generation if not extended** |
| [app/docx_report.py](app/docx_report.py#L769) | `STATUS_LABELS[finding.status]` into the `{{status}}` token | **same `KeyError`** |
| [app/docx_report.py](app/docx_report.py#L117) `generation_issues` | `set(content_types_for_status(...))` | free |
| [app/docx_report.py](app/docx_report.py#L759) | `"new_finding.docx" if status == "open_new" else "retest_finding.docx"` | falls through to the retest template |
| [app/docx_report.py](app/docx_report.py#L790) | `if finding.status != "open_new"` adds the previous-PoC and conclusion anchors | falls through correctly |
| [app/docx_import.py](app/docx_import.py#L53-L58) `STATUS_BY_LABEL` / `LABEL_BY_STATUS` | label to value both ways | **must extend, or a generated document cannot be re-imported** |
| [app/docx_import.py](app/docx_import.py#L59) `RETAINED_STATUSES` | `{"open_new", "open_previously_discovered"}` | **must extend, or a retest import silently drops the finding** as if Resolved ([app/docx_import.py](app/docx_import.py#L929-L932)) |
| [app/docx_import.py](app/docx_import.py#L929) | `if status == "resolved"` enforces untouched remediation on editable import | falls through |
| [app/docx_import.py](app/docx_import.py#L941-L953) | retest rewrites everything retained to `open_previously_discovered` | decision needed: does the new status survive a retest import, or become previously-discovered? |
| [app/docx_import.py](app/docx_import.py#L1157-L1161) | `status_counts` built over a literal 3-tuple | **must extend, or the import summary never counts the new status** |

**JavaScript**

| Site | What it does | New value |
|---|---|---|
| [app/web/static/app.js](app/web/static/app.js#L119) `statuses` | `[["open_new","Open (New)"], ["open_previously_discovered","Open (Previously Discovered)"], ["resolved","Resolved"]]` - **the one source of the dropdown and of every status label in the client** | **must extend** |
| [app/web/static/app.js](app/web/static/app.js#L277) `optionLabel` | looks up `statuses`, falls back to title-casing the key | free once `statuses` is extended |
| [app/web/static/app.js](app/web/static/app.js#L279) `select` | renders `<option>` from the value list | free |
| [app/web/static/app.js](app/web/static/app.js#L2561) | `select(statuses.map(x=>x[0]), finding.status)` - the Findings-table dropdown, **built in JavaScript, not in any template** | free |
| [app/web/static/app.js](app/web/static/app.js#L1075-L1077) `contentTypesForStatus` | twin of the Python function | falls through |
| [app/web/static/app.js](app/web/static/app.js#L1055) `syncConclusion` | `=== "resolved" ? "Resolved" : "Open"` | falls through |
| [app/web/static/app.js](app/web/static/app.js#L1103) `provision` | resolved remediation boilerplate | falls through |
| [app/web/static/app.js](app/web/static/app.js#L1125) `offerConclusionRewrite` | gate on `contentTypesForStatus(...).includes("in_conclusion")` | free |
| [app/web/static/app.js](app/web/static/app.js#L1128) `offerConclusionRewrite` | status word | falls through to `"Open"` |
| [app/web/static/app.js](app/web/static/app.js#L1430) `pendingLibraryOffers` | suppresses the remediation offer while resolved | falls through - the offer stays on |
| [app/web/static/app.js](app/web/static/app.js#L2284) `updateFindingSummary` | `if (!finding.status) missing.push("status")` | free |
| [app/web/static/app.js](app/web/static/app.js#L2591-L2601) the status `onchange` | recomputes sections, warns about hidden work, warns about replacing the remediation (`nextStatus === "resolved"`), then `provision` + conclusion offer | falls through |
| [app/web/static/app.js](app/web/static/app.js#L2650) `addFinding` | seeds `status:"open_new"` | unchanged |
| [app/web/static/app.js](app/web/static/app.js#L3694) new finding from the editor | seeds `status:"open_new"` | unchanged |
| [app/web/static/app.js](app/web/static/app.js#L2754) | `[likelihood, impact, severity, status].map(value => !value)` | free |
| [app/web/static/app.js](app/web/static/app.js#L3372) `additionalInformationFields` | `if (finding.status !== "open_new")` shows Severity Review Tickets | falls through - the new status shows the ticket field |
| [app/web/static/app.js](app/web/static/app.js#L3408) `fragmentIssues` | printed sections | free |
| [app/web/static/app.js](app/web/static/app.js#L3460) readiness | truthiness only | free |
| [app/web/static/app.js](app/web/static/app.js#L3769) the finding-card chip | `statuses.find(...)?.[1] \|\| finding.status` - prints the raw key if `statuses` is not extended | free once extended |
| [app/web/static/app.js](app/web/static/app.js#L3827) conclusion offers | gated on `contentTypesForStatus` | free |
| [app/web/static/app.js](app/web/static/app.js#L3866) and [L3883](app/web/static/app.js#L3883) | `=== "resolved" ? "Resolved" : "Open"` for the restore and add-sentence offers | falls through |
| [app/web/static/app.js](app/web/static/app.js#L4027) | locks the remediation editor while resolved | falls through - stays editable |
| [app/web/static/app.js](app/web/static/app.js#L4110) `printedContents` | `contentTypesForStatus` | free |
| [app/web/static/manager.js](app/web/static/manager.js#L208) | `{open_new:"Open New", open_previously_discovered:"Previously Discovered", resolved:"Resolved"}` with a `\|\| key` fallback | **should extend** - otherwise the DOCX import summary prints the raw key |

**Templates enumerate nothing.** [app/web/templates/page2_findings.html](app/web/templates/page2_findings.html)
carries only a `<th>Status</th>`; the `<select>` and its options are built in JavaScript. The
`status` field in [app/web/templates/library_editor.html](app/web/templates/library_editor.html#L56)
is the **library entry's** approval status, a different thing entirely, and is not affected.

#### What each status means for which sections print

`content_types_for_status` is the single owner ([app/report_service.py](app/report_service.py#L251-L256)):

- `open_new` prints **description, recommended remediation, proof of concept**.
- **every other value** prints those three plus **previous proof of concept** and **in conclusion**.

That is the whole rule. It is written as one `if`, so `Open (Resolved on Non-Prod)` gets the
five-section set for free, with no edit. The document mirrors it: `new_finding.docx` for `open_new`,
`retest_finding.docx` otherwise ([app/docx_report.py](app/docx_report.py#L759)), and only the latter
carries `{{severity-review-tickets}}`, which is why the editor shows the Severity Review Tickets
field for `!== "open_new"` ([app/web/static/app.js](app/web/static/app.js#L3372)).

**The new status should behave exactly like `open_previously_discovered`.** Not like `resolved`:
`resolved` is the only value that force-writes the remediation boilerplate, locks the remediation
editor, suppresses the library remediation offer, writes `Resolved` into the conclusion sentence,
and gets dropped by a retest import. `Open (Resolved on Non-Prod)` is an **open** finding by its own
name, so every one of those `resolved` branches should stay in its else-arm - which is what happens
with no code change at all.

#### Adding a value: safe. Removing it later: a one-way door.

**Adding breaks nothing on disk.** Widening a `Literal` is strictly permissive. All 14 drafts carry
only `open_new`, `open_previously_discovered` or `resolved` (45 occurrences across 10 files
including backups). No `load_path` repair is needed, and adding one would be wrong for the same
reason it was wrong for `non_production_label`: it rewrites every draft to change nothing and burns
the single `draft.bak.json` level.

**Removing it later is not recoverable through the UI.** A draft holding a removed value fails
`Report.model_validate` on load, which demotes it to the manager's legacy list
([app/workspace.py](app/workspace.py#L132-L147)). That list marks an entry `repairable` **only** when
the reason contains `"duplicate fragment id:"` ([app/workspace.py](app/workspace.py#L147)), and
`repair_duplicate_fragment_ids` refuses anything else
([app/workspace.py](app/workspace.py#L217-L237)). So the draft would need hand-editing on disk.
Exactly the precedent recorded for `non_production_label` in
[docs/DATA_MAP.md](docs/DATA_MAP.md) §6.

#### The resolved-remediation boilerplate and the status-conclusion sentence

**The boilerplate is driven by `status == "resolved"` and nothing else**, in four places:
`provision` ([app/report_service.py](app/report_service.py#L313)), its JavaScript twin
([app/web/static/app.js](app/web/static/app.js#L1103)), the editor lock
([app/web/static/app.js](app/web/static/app.js#L4027)), and the legacy repair in `load_path`
([app/workspace.py](app/workspace.py#L292-L296)). The new status takes the else-arm everywhere,
which is correct: an open finding gets an editable, empty remediation.

**Sharp edge worth stating.** `load_path`'s `elif stale:` arm **empties the runs and rewrites the
file** when a finding is not `resolved` and its remediation is a single unmarked paragraph reading
exactly `"None, the vulnerability has been remediated."` So moving a finding from Resolved to the
new status, where that sentence was written before the `generated` marker existed, blanks the
remediation on the next load. That is the intended behaviour and is identical to what
`open_previously_discovered` does today - but it is a Python-only rule that a search for `.status`
misses, because it reads `vulnerability.get("status")` on a raw mapping.

**The conclusion sentence needs nothing.** The builder is called with a *status word*, computed as
`"Resolved" if status == "resolved" else "Open"` ([app/report_service.py](app/report_service.py#L326)
and four JavaScript sites), and the recogniser matches `(?:Open|Resolved)` only
([app/report_service.py](app/report_service.py#L497)). The new status therefore produces
`The finding "X" is still Open.` with zero edits, and every sentence already on disk keeps matching.

If the planner instead wants the sentence to name the new status, that is a **three-part change with
a migration hazard**: `status_conclusion_runs`, `STATUS_CONCLUSION_PATTERN`, and their JavaScript
twins must change together, the recogniser must keep the old alternation or every default sentence
on disk stops being recognised and freezes at its stored wording, and
`test_the_conclusion_recogniser_matches_what_the_builder_writes` is the pin. My reading of the
source is that leaving the sentence at `Open` is both correct and free.

#### Invariants in play

- `Status` is closed. A value not in the `Literal` fails validation on **load** (demoting the whole
  draft) and on **save** (422 `invalid_report`). There is no coercing before-validator for status,
  unlike `Scope.mode`.
- `content_types_for_status` is the **single owner** of printed sections. `provision` carries an
  unprinted section that holds work, **except `in_conclusion`**, which is dropped outright on a move
  to `open_new` and re-created empty on the way back
  ([app/report_service.py](app/report_service.py#L286-L288), mirrored at
  [app/web/static/app.js](app/web/static/app.js#L1093-L1095)). A move between
  `open_previously_discovered` and the new status prints the same five sections, so nothing is
  carried, hidden or dropped - the quietest possible transition.
- `Report.validate_references` does not constrain status at all; which sections a status requires is
  `provision`'s job, not the model's.

#### Both-sides warning

Every one of these is implemented twice and must change together:

| Rule | Python | JavaScript |
|---|---|---|
| status to section list | `content_types_for_status` | `contentTypesForStatus` |
| the status labels | `docx_report.STATUS_LABELS`, `docx_import.STATUS_BY_LABEL` / `LABEL_BY_STATUS` | `statuses` in `app.js`, **and a third copy**, `labels` in `manager.js` |
| resolved remediation boilerplate | `provision` (`RESOLVED_REMEDIATION`), plus `workspace.load_path`'s repair | `provision`, plus the editor lock |
| the default In Conclusion sentence | `status_conclusion_runs`, `STATUS_CONCLUSION_PATTERN` | `statusConclusionRuns`, `STATUS_CONCLUSION_PATTERN` |
| finding completeness | `finding_is_complete` | `validateFindingsPage`, `updateFindingSummary` |
| generation readiness | `generation_issues` | `updateReadinessPanel`, `fragmentIssues` |

`tests/test_browser.py::test_browser_readiness_verdict_matches_server_generation_issues` is the only
contract test, and it covers generation readiness alone. **The status-label tables have no drift
guard**, and there are now four copies of them.

---

### Change 3 - `N/A` as a bulleted list

#### Where the values come from, and what "empty" looks like in the data

The model side is `Scope` ([app/models.py](app/models.py#L149-L153)):

```python
mode: Literal["custom"] = "custom"
target_ids: list[str] = Field(default_factory=list)
location_values: dict[str, str] = Field(default_factory=dict)
custom_locations: dict[Environment, dict[Channel, list[str]]] = Field(default_factory=dict)
```

`_finding_locations` ([app/docx_report.py](app/docx_report.py#L1412-L1425)) is the only thing that
turns those into per-environment lists:

```python
def _finding_locations(report: Report, finding: Vulnerability) -> dict[str, list[str]]:
    values = {"production": [], "non_production": []}
    ...
```

It **always returns both keys**, and returns `[]` - never `"N/A"`, never `None` - for an environment
the finding does not touch. So "empty for this environment" is represented as **an empty list**, and
it is produced one line before the document consumes it. There is no draft field that says
"no locations here"; the absence of any `target_id` in that environment and of any surviving typed
line *is* the representation. Note also that a finding with **no** location at all cannot reach
generation: `scope_has_location` ([app/report_service.py](app/report_service.py#L784-L801)) fails,
`finding_is_complete` fails, and `generation_issues` blocks. The empty case being asked about is
always "one environment has locations, the other does not".

Two cleaning rules feed it. Selected targets take
`finding.scope.location_values.get(target_id, target.value)` - the per-finding override if one
exists, otherwise the Setup value. Typed endpoints go through `location_lines`
([app/report_service.py](app/report_service.py#L353-L366)), which drops blanks, `#` comment lines
and repeats. **`location_lines` has a named JavaScript twin, `locationLines`**, but
`_finding_locations` itself has **no twin** - generation is server-only, which
[docs/DATA_MAP.md](docs/DATA_MAP.md) §12 already records.

#### Where the `N/A` fallback is decided

**Not in the data layer.** It is decided at document time, in one early return in
`_replace_token_with_bullets` ([app/docx_report.py](app/docx_report.py#L701-L713)):

```python
def _replace_token_with_bullets(document, elements, token, values, component_root) -> None:
    """Swap a cell token for real bullet-list paragraphs cloned from the bullet fragment."""
    pattern = re.compile(r"\{\{\s*" + re.escape(token) + r"\s*\}\}", re.IGNORECASE)
    if not values:
        replace_component_token_runs(elements, token, [Run(text="N/A")])
        return
```

Called once per environment for the `prod_affected_locations` and `non-prod-affected-locations`
tokens ([app/docx_report.py](app/docx_report.py#L778-L782)). The empty branch **returns before the
bullet-fragment clone path is reached**, which is precisely why the current output is a bare
paragraph rather than a bullet. Making `N/A` consistent means not taking that early return -
handing `["N/A"]` to the same clone path the non-empty case uses. That is one edit in one function
in `scribe`'s file, and **no data-layer change is required or appropriate**.

There is no second `N/A` for these tokens anywhere: no model default, no `report_service` fallback,
no client-side equivalent. Every other `N/A` in the codebase belongs to a different field
(`_display_value`, the test-accounts table, the scope table, severity tickets) and none of them
routes through `_replace_token_with_bullets`.

#### A genuine Python/JavaScript divergence in this area

Worth naming because it changes what "empty" can mean, and because it is not in
[docs/DATA_MAP.md](docs/DATA_MAP.md):

- Python: `finding.scope.location_values.get(target_id, target.value)`
  ([app/docx_report.py](app/docx_report.py#L1418)) - the default applies only when the **key is
  absent**.
- JavaScript: `finding.scope.location_values?.[targetId] || target.value`
  ([app/web/static/app.js](app/web/static/app.js#L3756)) - `||` also catches the **empty string**.

A tester who clears a selected location's override textarea writes `""` into `location_values`
([app/web/static/app.js](app/web/static/app.js#L2549-L2551) and
[L2627](app/web/static/app.js#L2627)); nothing trims it and `reconcile_targets` only prunes keys
whose target is gone ([app/report_service.py](app/report_service.py#L736-L738)). The editor chip
then shows the original Setup value while the document prints an **empty line** - and because the
list is non-empty, the `N/A` fallback is not reached either. Change 3 will not fix that, and does
not need to, but if the planner wants "blank means N/A" to hold generally, this is the second place
it leaks.

#### Invariants in play

- `_finding_locations` returns both environment keys unconditionally, so a caller never has to
  handle a missing key - only an empty list.
- `location_lines` is the single owner of which typed lines count, with `locationLines` as its
  twin; it is applied to `custom_locations` only, never to `location_values`.
- `scope_has_location` guarantees a generated finding has at least one location **somewhere**, so
  `N/A` only ever describes one environment of a finding that has locations in the other.

---

### Map drift

**None found.** Every claim in [docs/DATA_MAP.md](docs/DATA_MAP.md) that I checked against source in
these three areas held: the username twin (§12), `content_types_for_status` as single owner (§7),
the `in_conclusion` carry exception (§7 and §12), the conclusion builder/recogniser pair (§12),
`location_lines` and its twin (§7), and "which locations a finding prints - none" on the JavaScript
side (§12). Nothing in `docs/DATA_MAP.md` was edited.

Two things are **absent** from the map rather than wrong in it, and would be worth adding when this
work lands: the `location_values` `get` / `||` divergence described above, and the fact that
`workspace.load_path` is a fourth Python site branching on `status == "resolved"`.

## Round 1 - Scribe: the document side

Scope: the Word pipeline only — `app/docx_report.py`, `app/docx_components.py`, `app/docx_import.py`
and `resources/`. The oracle's account of the data layer is not repeated. Sizing from where I sit:
**change 1 costs the document nothing, change 3 is one line, change 2 is four small table entries
spread over two files.** Nothing here needs a new `.docx`.

### Change 3 - what the bullet path actually does

One function, [app/docx_report.py](app/docx_report.py#L702-L736), and one caller.

**The non-empty path, step by step (L714-L736).**

1. `filename, bullet_token = FRAGMENT_COMPONENT_FILES["bulleted_list"]`
   ([L714](app/docx_report.py#L714)) resolves to `("bulleted_fragment.docx", "bullet-list-fragment")`
   from the table at [L77-L85](app/docx_report.py#L77). The cloned source is therefore
   `resources/fragments/bulleted_fragment.docx` — **the same component a tester's bulleted-list
   fragment uses inside a finding's body.** There is no separate "location bullet" document.
2. It finds the one paragraph whose flattened text matches `{{token}}`
   ([L716-L718](app/docx_report.py#L716)), using `_element_text`, which collapses whitespace so a
   token split across `w:t` nodes still matches.
3. `numbering_ids: dict[tuple[Path, int], int] = {}` is declared **inside the per-paragraph loop**
   ([L719](app/docx_report.py#L719)). That is deliberate: every bullet in one cell shares one
   `numId`, and Production and Non-Production each get their own. The same one-cache-per-cell shape
   is described in [docs/plans/numbered-list-continuation.md](docs/plans/numbered-list-continuation.md#L177).
4. Per value, `clone_component_elements` ([app/docx_components.py](app/docx_components.py#L44-L69))
   deep-copies the component's body, validates its style ids against the target document, and calls
   `_remap_numbering` ([app/docx_components.py](app/docx_components.py#L254-L312)), which copies the
   component's `w:abstractNum` and `w:num` into the report's numbering part under fresh ids with a
   fresh `w:nsid`.
5. **Numbering and style come from the component, not from code.** The renderer never writes
   `w:numPr`, `w:ind`, `w:numFmt` or a bullet glyph. The pinned evidence is
   [tests/test_docx.py](tests/test_docx.py#L479-L486): every location paragraph has
   `style.name == "List Paragraph"`, has a `w:numPr` under its `w:pPr`, and the cell text contains no
   `\u2022` — "the bullet glyph must come from the list style, not the text". Indent likewise: it is
   whatever the Word author gave `bulleted_fragment.docx`, carried in the cloned `w:pPr` and the
   copied abstract numbering. Nothing in the pipeline can tell you the numeric indent; only the
   component can.
6. The value becomes exactly one run:
   `[Run(text="\n".join(_wrap_long_value(value, LOCATION_WRAP_CHARACTERS)))]`
   ([L729](app/docx_report.py#L729)) through `replace_component_token_runs`, whose `_set_run_text`
   turns each `\n` into a real `w:br`. **A wrapped location is one bullet with an internal break, not
   two bullets** — asserted at [tests/test_docx.py](tests/test_docx.py#L484).
7. The only formatting the code forces is alignment: `_align_left`
   ([app/docx_report.py](app/docx_report.py#L739-L748)) removes every `w:jc` from the cloned
   paragraph and sets `left`, because the component is authored justified and a justified one-line
   bullet stretches ugly. Pinned at [tests/test_docx.py](tests/test_docx.py#L482).
8. **Insertion:** `paragraph.addprevious(node)` ([L734](app/docx_report.py#L734)) puts each cloned
   node immediately before the token paragraph, then
   `paragraph.getparent().remove(paragraph)` ([L735](app/docx_report.py#L735)) deletes the token
   paragraph and the function `return`s ([L736](app/docx_report.py#L736)). The bullets therefore
   occupy the token paragraph's position inside the same table cell, below the environment heading
   paragraph that the template supplies.

### Change 3 - what the `N/A` early return does instead

```python
if not values:                                                        # L711
    replace_component_token_runs(elements, token, [Run(text="N/A")])  # L712
    return                                                            # L713
```

`replace_component_token_runs` ([app/docx_components.py](app/docx_components.py#L77-L82)) rewrites
the token **in place**. The template's own paragraph survives with its style, its `w:jc`, its indent
and its `w:numPr` if it had one; only the text inside changes. The template paragraph carries no
bullet — that is precisely the reported symptom, and the code path guarantees the paragraph is
untouched apart from its text, so there is nothing else it could be.

Concretely, the Location cell for an empty environment today is **two paragraphs**: the environment
heading (`Production Environment:` / `<LABEL> Environment:`), then a plain, template-formatted
paragraph reading `N/A`. A populated cell is heading + one `List Paragraph` bullet per value — see
[tests/test_docx.py](tests/test_docx.py#L238-L247), which asserts the cell reads
`"Production Environment:\nhttps://…\nhttps://…"` with two bulleted paragraphs.

After the change the empty cell is heading + one bulleted `List Paragraph` reading `N/A`. **The
paragraph count does not change** — 2 before, 2 after. Only the paragraph's identity does: template
paragraph replaced by a clone of `bulleted_fragment.docx`.

### Change 3 - yes, it is genuinely one line

Replace [L711-L713](app/docx_report.py#L711) with:

```python
values = values or ["N/A"]
```

Nothing downstream assumes a non-empty source:

- `for value in values` ([L720](app/docx_report.py#L720)) simply runs once.
- `_wrap_long_value("N/A", 74)` ([app/docx_report.py](app/docx_report.py#L386-L409)) returns
  `["N/A"]` — three characters is under the limit, the `while` never enters, so no `w:br`.
- `_remap_numbering` copies one abstract + one num as it would for any value.
  `_restart_numbering_levels` ([app/docx_components.py](app/docx_components.py#L352-L399)) skips any
  level whose `w:numFmt` is `bullet`, so no `startOverride` is written and no restart logic runs.
- The token is still consumed, because `paragraph.getparent().remove(paragraph)` still fires, so
  `_unresolved_placeholders` ([app/docx_report.py](app/docx_report.py#L1492)) stays satisfied and
  generation does not abort.

Two honest side effects, neither a blocker:

- **Reach.** The empty branch replaced the token in *every* matching paragraph; the bullet path
  handles the **first** match and returns. Each finding template carries each location token once,
  so this is equivalent in practice — but it is a real difference in the function's contract.
- **Numbering-part growth.** Each empty environment now adds one `w:abstractNum` + one `w:num` to
  the report's numbering part, where before it added none. That is the same growth every non-empty
  environment already causes, and nothing caps it; for a 30-finding report it is 60 numbering
  definitions instead of ~45. Word tolerates this today.

### Change 3 - callers: exactly one, and it is only affected locations

`_replace_token_with_bullets` is called **once**, at
[app/docx_report.py](app/docx_report.py#L782), inside a two-iteration loop over
`("prod_affected_locations", locations["production"])` and
`("non-prod-affected-locations", locations["non_production"])`
([L778-L782](app/docx_report.py#L778)). A repo-wide search finds no other call in `app/`, `tests/`
or `scripts/`; the only other hits are prose in
[docs/plans/asia-additional-information.md](docs/plans/asia-additional-information.md#L689) and
[docs/plans/numbered-list-continuation.md](docs/plans/numbered-list-continuation.md#L177). **Changing
this function cannot alter any other part of the document.**

The helper the empty branch calls, `replace_component_token_runs`, *does* have many other callers —
severity review tickets ([L777](app/docx_report.py#L777)), every fragment body, the bullet path
itself. The proposed edit deletes the **call**, not the helper, so none of them moves.

**The other `N/A`s are unrelated and must stay put.** `_set_cell_lines(..., lines or ["N/A"])`
([L432](app/docx_report.py#L432)) for the scope, accounts and component tables; `_display_value`
([L234](app/docx_report.py#L234)); the empty-content paragraph
([L900](app/docx_report.py#L900)); severity tickets ([L776](app/docx_report.py#L776)). None routes
through `_replace_token_with_bullets`.

One consequence the planner should state out loud rather than discover later: the **Limitations**
cell goes the opposite way. `_center_plain` ([app/docx_report.py](app/docx_report.py#L445-L454))
exists specifically to *strip* `w:numPr` and `w:ind` and centre the text when limitations read `N/A`
or `NA` ([L468-L470](app/docx_report.py#L468)), because that cell's style is a bullet list and a
lone centred `N/A` was judged to read better. After this change the two tables disagree on purpose:
affected locations bullet their `N/A`, Limitations de-bullets its own. That is defensible — one is a
list of many things, the other is a single statement — but it should be a decision, not an accident.

### Change 3 - import round-trip: the risk is already closed, and this does not reopen it

**Short answer: no. `docx_import` cannot turn a bulleted `N/A` into scope data, and the bullet is
invisible to it.**

`_detail_locations` ([app/docx_import.py](app/docx_import.py#L694-L746)) is the only reader that
builds scope from that cell. It reads the cell as plain paragraphs
([L704](app/docx_import.py#L704)), treats `paragraphs[0]` as the environment heading
([L705-L711](app/docx_import.py#L705)), then for each remaining paragraph:

```python
for paragraph in paragraphs[1:]:      # L712
    value = _visible_value(paragraph) # L713
    if not value:                     # L714
        continue                      # L715
```

`_visible_value` ([app/docx_import.py](app/docx_import.py#L90-L93)) returns `""` for exactly
`"N/A"`. **So `N/A` is discarded before the matching logic runs.** It never becomes a `ScopeTarget`,
never enters `target_ids`, and never raises a "review the app type" warning.

Crucially, **this reader inspects text, never list formatting.** It does not look at `w:numPr` in
the detail table at all. The importer's numbering inspection lives elsewhere — `_fragment_kind`
([app/docx_import.py](app/docx_import.py#L179-L183)) and
[L233](app/docx_import.py#L233) — and applies only to fragment bodies inside a finding's *sections*,
not to the detail table. Adding a bullet to the `N/A` paragraph is therefore a no-op on import.

`_observed_environments` ([app/docx_import.py](app/docx_import.py#L670-L692)) is the other reader of
that cell and applies the same filter before counting an environment as observed:
`if not any(_visible_value(value) for value in paragraphs[1:]): continue`
([L678-L680](app/docx_import.py#L678)). An `N/A`-only environment is not observed, bulleted or not.

**This is already exercised on macOS.** Several import tests build production-only reports — e.g.
[tests/test_docx_import.py](tests/test_docx_import.py#L774-L797) and
[L799-L818](tests/test_docx_import.py#L799) — so the Non-Production location row renders `N/A`
today, is imported, and `Report.model_validate(payload)` passes with exactly one target. Those
assertions are on text, so they keep passing with the bullet.

**What only Word can settle:** whether the bulleted `N/A` *looks* right once the Word pass
repaginates. Nothing in this repository can answer that; it needs a Windows render and a human
looking at the page.

### Change 3 - test coverage, and the gap

- [tests/test_docx.py](tests/test_docx.py#L445) selects the Location cell by
  `"prod.example.test/accounts" in cell.text`, so it picks the **Production** cell and is unaffected.
- [tests/test_docx.py](tests/test_docx.py#L238-L247) likewise asserts only the Production cell.
- **No existing test asserts the shape of an empty environment's Location cell.** The change lands
  green with nothing proving it, so a new assertion belongs in the same commit: a finding with
  production-only locations, then assert the Non-Production cell's second paragraph has a `w:numPr`
  and reads `N/A`.

Tests the planner should expect to run for change 3: `tests.test_docx` and `tests.test_docx_import`
(scope map row for `app/docx_*.py`).

### Change 2 - where the status label reaches the document

Two sites, both bare dict indexes on `STATUS_LABELS`
([app/docx_report.py](app/docx_report.py#L48-L52)), and the oracle's identification is correct.

| Line | What the label becomes | Mechanism |
|---|---|---|
| [L516](app/docx_report.py#L516) | the **sixth cell** of the findings summary table row | `_replace_cell_placeholder(cell, value, font_color=None, font_size_pt=None)` — no colour, no size override, so it keeps the prototype cell's own formatting |
| [L769](app/docx_report.py#L769) | the value of the **`{{status}}` token** in the finding detail table | `replace_component_token` → `_replace_token` ([app/docx_components.py](app/docx_components.py#L385-L396)) |

So: **a table cell, and a token — never a heading.** Headings are severity, from
`SEVERITY_COMPONENT_FILES`, and are untouched by this change.

`"status"` is **not** in `RATING_COLOR_TOKENS`
([app/docx_components.py](app/docx_components.py#L25-L31)), so no font colour is applied — a longer
label inherits the template's formatting and simply wraps inside its column. How
`Open (Resolved on Non-Prod)` (26 characters, vs 28 for `Open (Previously Discovered)`) actually
lays out in those two columns is a Word question, but it is **shorter than the longest label already
printing**, so there is no new layout risk.

Both sites read the one dict, so summary and detail cannot drift — which matters because the
importer cross-checks them and raises `'"X" summary and detail values do not match.'`
([app/docx_import.py](app/docx_import.py#L895-L901)).

**Failure mode if `STATUS_LABELS` is not extended:** a raw `KeyError` inside `render_report_docx`,
not a `ReportGenerationError`. It escapes as a 500 with no readable message rather than the
"Unresolved template placeholders" style the rest of the pipeline uses. Adding the fourth key is the
whole fix; there is no argument for adding a `.get()` fallback, because a label the app invented for
an unknown status would then be written into a document and read back as garbage.

### Change 2 - nothing in `resources/` enumerates the status

`resources/finding_types/` holds exactly two files: `new_finding.docx` and `retest_finding.docx`.
The choice is a single expression:

```python
template_name = "new_finding.docx" if finding.status == "open_new" else "retest_finding.docx"  # L759
```

The new status takes the retest template with **no edit and no new file**. Status is a *token value*
inside those documents, not a per-status document. Contrast `SEVERITY_COMPONENT_FILES`
([app/docx_report.py](app/docx_report.py#L69-L75)), which **is** a per-value file map — that is why
a new *severity* would be a genuinely large change and a new *status* is not.

`resources/fragments/` is per fragment type and knows nothing about status.
`resources/severity_titles/` is per severity. `resources/fixtures/` holds one unrelated file,
`report-name.docx`. **No `.docx` needs to be made or edited for any of the three changes.**

Worth stating because it is the payoff: the retest template is the one carrying
`{{severity-review-tickets}}`, `Previous Proof of Concept:` and `In Conclusion:`, so the new status
prints all three — exactly matching the five-section set `content_types_for_status` gives it, with
no document-side work.

### Change 2 - what `docx_import` must learn

Two entries, both in [app/docx_import.py](app/docx_import.py#L53-L59), plus one cosmetic:

1. **`STATUS_BY_LABEL`** ([L53-L57](app/docx_import.py#L53)) — needs
   `"Open (Resolved on Non-Prod)": "open_resolved_on_non_prod"` (or whatever the value is named).
   Without it `_summary_rows` ([L643-L656](app/docx_import.py#L643)) stores `status: None` and
   `_findings` raises `'"X" has an unknown finding status.'`
   ([L777-L780](app/docx_import.py#L777)). **Loud and safe — the import refuses rather than
   corrupts.** `LABEL_BY_STATUS` is derived from it at [L58](app/docx_import.py#L58), so both of its
   uses come free: the section-structure error message
   ([L886-L887](app/docx_import.py#L886)) and the summary/detail cross-check
   ([L898](app/docx_import.py#L898)).
2. **`RETAINED_STATUSES`** ([L59](app/docx_import.py#L59)) — needs the new value.
   `if mode == "retest" and row["status"] not in RETAINED_STATUSES`
   ([L922-L924](app/docx_import.py#L922)) otherwise appends the finding to `dropped` and `continue`s.
   **This is the one silent failure in the whole change:** an *open* finding vanishes from a retest
   import and is disclosed under the key `dropped_resolved`, which is a lie about why. Miss this and
   nothing errors.
3. **`status_counts`** ([L1158-L1161](app/docx_import.py#L1158)) iterates the literal tuple
   `("open_new", "open_previously_discovered", "resolved")`. Not extending it means the editable
   import summary never mentions the new status; the findings themselves import correctly. Cosmetic,
   one string, same file.

`expected_sections` needs **nothing**: the branch is `if row["status"] != "open_new"`
([L880-L885](app/docx_import.py#L880)), so the new status expects the five-section structure the
retest template produces.

**A decision, not a defect — and it belongs to the planner.** The retest branch
([L941-L954](app/docx_import.py#L941)) rewrites *every* retained finding to
`open_previously_discovered`, unconditionally. So a document printed with
`Open (Resolved on Non-Prod)` comes back from a **retest** import as `Open (Previously Discovered)`,
and only `open_new` findings are disclosed in `statuses_rewritten`
([L944-L945](app/docx_import.py#L944)) — so this rewrite would be **invisible in the summary**.
**Editable** import keeps the status verbatim ([L926-L928](app/docx_import.py#L926)). Two coherent
answers: leave it (the retest's premise is that the finding is being re-tested afresh, which is why
the status is normalised), or add the new status to the `rewritten` disclosure so the tester is told.
Leaving it is the smaller change and, I think, the right one; disclosing it is one `or` on L944.

The `resolved`-only remediation check ([L929-L940](app/docx_import.py#L929)) is keyed on
`status == "resolved"`, so the new status falls through to the editable arm with no edit. Correct:
it is an open finding.

### Change 2 - sections rendered: nothing beyond the data side

Document-side gates, both falling through correctly with no edit:

- `_render_finding_component` adds the previous-PoC and conclusion anchors on
  `if finding.status != "open_new"` ([L790](app/docx_report.py#L790)).
- `generation_issues` builds `printed = set(content_types_for_status(finding.status))`
  ([L117](app/docx_report.py#L117)) and only requires fragments for printed sections.

`{{severity-review-tickets}}` is replaced unconditionally
([L777](app/docx_report.py#L777)); on `new_finding.docx` the token does not exist and the call is a
no-op. The new status uses the retest template, so it **will** print a
`Severity Review Ticket (if applicable):` line — `N/A` when the tester leaves it empty
([L776](app/docx_report.py#L776)). That is consistent with `open_previously_discovered` and is
presumably wanted, but it is the one visible document difference between the new status and
`open_new` that nobody has named yet.

### Change 2 - documentation that goes stale

Not edited — this is planning — but [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md) becomes wrong in
two places the moment this ships, and I own that file:

- [L218-L220](docs/DOCX_TEMPLATE.md#L218): "`open_previously_discovered` and `resolved` findings use
  `resources/finding_types/retest_finding.docx`".
- [L248-L250](docs/DOCX_TEMPLATE.md#L248): `{{severity-review-tickets}}` "prints for
  `open_previously_discovered` and `resolved` findings and never for `open_new`".

And for change 3, [L232-L235](docs/DOCX_TEMPLATE.md#L232) says affected locations render as a real
bulleted list "one bullet per location" — after the change it should say the `N/A` placeholder is
bulleted too.

### Change 1 - the username does reach the document, and a space is inert

Two routes, both plain text substitution:

1. **`{{username1}}` / `{{username2}}`** — built by `_metadata` at
   [app/docx_report.py](app/docx_report.py#L296-L298) via `_display_value`, substituted by
   `_replace_metadata` ([L309-L318](app/docx_report.py#L309)). They are **not** in
   `PLAIN_METADATA_TOKENS` ([L55](app/docx_report.py#L55)), so only the braced `{{…}}` pattern
   matches — there is no bare-word matching that a space could confuse.
   [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L206) calls these compatibility placeholders; the
   real table is rebuilt regardless.
2. **The User Roles table** — [app/docx_report.py](app/docx_report.py#L476):
   `_set_cell_lines(row.cells[1], [_display_value(account.username)])`, with `wrap=None`. So
   `_add_wrapped_run` ([L411-L417](app/docx_report.py#L411)) takes the `limit is None` branch and
   adds the whole value as **one run with no `w:br`**. There is no splitting on whitespace anywhere
   in this path.

Layout: the column width is the template's `tblGrid`, which the renderer never touches. A username
with spaces wraps inside its column exactly the way `user_role` — which already permits spaces and
is already tested with `"Admin-2 / QA"` — does today. Where the line breaks is Word's decision and
only Word settles it, but nothing in this repository branches on the space.

Filename: **no.** The username reaches no path segment.

Import: `_test_accounts` ([app/docx_import.py](app/docx_import.py#L510-L519)) reads
`_visible_value(cell.text)`, which is `value.strip()` ([L90-L93](app/docx_import.py#L90)) — interior
whitespace preserved **exactly**. Note the contrast with `_clean`
([L84-L87](app/docx_import.py#L84)), which collapses runs of whitespace via
`" ".join(value.split())`; accounts do **not** use it, so `"john  smith"` with two spaces survives a
round trip verbatim. If a canonical single-space form is wanted, that is a save-time decision in the
data layer, not a document one.

One pre-existing hazard worth a sentence, unchanged by this request:
`_unresolved_placeholders` ([app/docx_report.py](app/docx_report.py#L1492)) scans the **rendered**
document, so a username containing `{{`…`}}` or one of the seven `UNRESOLVED_MARKERS` substrings
([L56-L64](app/docx_report.py#L56)) would abort generation with a message about template
placeholders. The allowlist admits no braces before or after this change, so adding a space creates
no new exposure.

### Smallest correct edit, document side

| Change | Edit | Where |
|---|---|---|
| 3 | **one line** — `values = values or ["N/A"]` replacing the early return | [app/docx_report.py](app/docx_report.py#L711-L713) |
| 2 | one key | `STATUS_LABELS`, [app/docx_report.py](app/docx_report.py#L48-L52) |
| 2 | one key | `STATUS_BY_LABEL`, [app/docx_import.py](app/docx_import.py#L53-L57) |
| 2 | one member | `RETAINED_STATUSES`, [app/docx_import.py](app/docx_import.py#L59) |
| 2 | one string | the `status_counts` tuple, [app/docx_import.py](app/docx_import.py#L1160) |
| 1 | **none** | the document needs no change |

Plus one new test for the empty-environment Location cell, and the three
[docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md) corrections listed above.

## Round 1 - Planner: proposal and open questions

### Understanding

Three unrelated changes batched into one commit. **Change 1** widens the username allowlist to admit
interior spaces - four edits across two files, two existing test rows inverted, nothing stored
changes meaning. **Change 3** makes the empty-environment `N/A` placeholder a real bullet instead of
a bare paragraph - one line in the Word renderer, with the data layer untouched. **Change 2** adds a
fourth value to the finding status enum, `Open (Resolved on Non-Prod)`, which behaves in every
respect like `open_previously_discovered`: it takes the retest template, prints the five-section set,
leaves the remediation editable, and never triggers a `resolved` branch. That behaviour is free -
every one of those rules is written as `== "open_new"` or `== "resolved"`, so the new value lands in
the correct arm with no edit. What is **not** free is the five exhaustive tables that enumerate the
status, two of which fail loudly and one of which fails silently.

### Sizing: two of the three are approve-and-forget

The user asked not to overcomplicate this, so the most useful thing I can say first is where the
attention should not go.

- **Change 1 carries essentially no risk.** It is strictly permissive - every value that validated
  before still does. No draft on disk contains a space in a username (oracle: 20 of 22 hold exactly
  `"N/A"`, the other two are `qa.customer` and `qa.admin`). No filename, no path, no token match, no
  import splitting. The document already prints spaces in the adjacent `user_role` column.
- **Change 3 carries essentially no risk.** It is one line in one function with exactly one caller,
  and the scribe walked the import path to confirm `N/A` is discarded before any matching happens
  and that the importer never inspects list formatting in that cell. The paragraph count in the cell
  does not even change - 2 before, 2 after.
- **Change 2 is where the attention belongs**, and almost all of it is on *naming*, not mechanics.
  The mechanics are seven one-line edits. The naming is a one-way door.

Changes 1 and 3 can be approved without reading further. The rest of this section is about change 2.

### One correction to the oracle

The oracle's decision on change 1 rests on this claim:

> nothing on the client blocks a save on setup rules - `validateSetupInputs` is reached only through
> `validateSetupPage`, which only `#next` calls

That is not what `save()` does. [app/web/static/app.js](app/web/static/app.js#L769-L772):

```javascript
if (root.dataset.step === "setup" && !validateSetupInputs(false)) {
  setSaveState(SAVE_STATES.UNSAVED, "Correct invalid Setup fields");
  return false;
}
```

`save()` gates **every** save on the Setup step - autosave included - on
`validateSetupInputs(false)`, which reads `input.validity.valid` across every `[data-setup-validated]`
input ([app/web/static/app.js](app/web/static/app.js#L1514-L1525)); `wireSetupRule` keeps that
validity current on each `input` event ([L1500-L1513](app/web/static/app.js#L1500)).

So while the username reads `"john "` the client **does not send the request at all**. There is no
422. The save is deferred with `pendingSave` still true and the state line reading
`Correct invalid Setup fields`, and the next keystroke that makes the value valid reschedules it.
Identical to what `"john."` does today, and self-clearing. This turns the oracle's first decision
from a data question into a cosmetic one - see Q3.

Everything else in both reports I checked against and accept as written.

### Blast radius

| File | What changes | Change |
|---|---|---|
| [app/report_service.py](app/report_service.py#L21) | `USERNAME_PATTERN` interior class gains a space | 1 |
| [app/report_service.py](app/report_service.py#L186) | `allow_spaces=False` dropped from the Username call | 1 |
| [app/web/static/app.js](app/web/static/app.js#L1472) | `usernameCharacters` class gains a space - **twin of the row above** | 1 |
| [app/web/static/app.js](app/web/static/app.js#L1497) | inline shape regex gains a space - **twin of `USERNAME_PATTERN`** | 1 |
| [tests/test_app.py](tests/test_app.py#L236) | negative case swapped from space to `/`; positive username gains a space | 1 |
| [tests/test_browser.py](tests/test_browser.py#L133) | the same row, **swapped not deleted** | 1 |
| [app/models.py](app/models.py#L10) | `Status` gains a fourth member | 2 |
| [app/docx_report.py](app/docx_report.py#L48-L52) | `STATUS_LABELS` gains a key | 2 |
| [app/docx_import.py](app/docx_import.py#L53-L57) | `STATUS_BY_LABEL` gains a key; `LABEL_BY_STATUS` derives free | 2 |
| [app/docx_import.py](app/docx_import.py#L59) | `RETAINED_STATUSES` gains a member | 2 |
| [app/docx_import.py](app/docx_import.py#L1160) | the `status_counts` tuple gains a string | 2 |
| [app/web/static/app.js](app/web/static/app.js#L119) | `statuses` gains a pair - **twin of `STATUS_LABELS`** | 2 |
| [app/web/static/manager.js](app/web/static/manager.js#L208) | `labels` gains a key - **third copy of the same table** | 2 |
| [app/docx_import.py](app/docx_import.py#L944) | *only if Q2 answers "disclose"* - the new status joins `statuses_rewritten` | 2 |
| [app/web/static/manager.js](app/web/static/manager.js#L200) | *only if Q2 answers "disclose"* - the notice wording widens | 2 |
| [app/docx_report.py](app/docx_report.py#L711-L713) | the empty early return becomes `values = values or ["N/A"]` | 3 |
| [tests/test_app.py](tests/test_app.py) | new: the new status saves and prints the five-section set | 2 |
| [tests/test_docx_import.py](tests/test_docx_import.py#L685) | a fourth finding in the all-statuses round trip | 2 |
| [tests/test_docx_import.py](tests/test_docx_import.py#L1004) | a retest import retains the new status | 2 |
| [tests/test_browser.py](tests/test_browser.py) | new: the option exists, selects, and labels | 2 |
| [tests/test_docx.py](tests/test_docx.py) | new: the empty environment's Location cell is a bullet | 3 |
| [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L218-L220), [L232-L235](docs/DOCX_TEMPLATE.md#L232-L235), [L248-L250](docs/DOCX_TEMPLATE.md#L248-L250) | the three corrections the scribe listed | 2, 3 |
| [docs/DATA_MAP.md](docs/DATA_MAP.md) | §7 the fourth status value; §12 the status-label table as a four-copy twin | 2 |

**Deliberately not touched:** `app/workspace.py`, `app/storage.py`, `app/main.py`,
`resources/**` (no `.docx` needs editing or creating), every `provision` branch,
`content_types_for_status` and `contentTypesForStatus`, and the conclusion builder/recogniser pair.

### Open questions

Four, in the order they block work. Q1 blocks everything; Q3 and Q4 are confirmations where doing
nothing is the answer I recommend.

#### Q1 - what is the new status called, exactly, in three places? *(blocking)*

Three strings are needed, and only the first is irreversible.

1. **The stored key**, in `Status` and every table. Recommend `open_resolved_on_non_prod`.
2. **The dropdown label**, in `statuses` ([app/web/static/app.js](app/web/static/app.js#L119)).
   Recommend `Open (Resolved on Non-Prod)` - the user's own words.
3. **The document label**, in `STATUS_LABELS` and `STATUS_BY_LABEL`. These two **must be
   byte-identical to each other** or a generated report cannot be re-imported. Making them identical
   to the dropdown as well costs nothing and is what the other three statuses already do. Recommend
   the same string a third time.

**Why the key matters more than the labels.** Labels are changeable later at the cost of one
regeneration. The stored key is a one-way door: once a draft on disk holds it, renaming it makes
that draft fail `Report.model_validate` on load, which demotes it to the manager's legacy list, and
that list only offers repair when the reason contains `"duplicate fragment id:"`
([app/workspace.py](app/workspace.py#L147)). Recovery means hand-editing JSON on disk. This is the
`non_production_label` precedent recorded in [docs/DATA_MAP.md](docs/DATA_MAP.md) §6.

**One wrinkle worth thirty seconds and no code.** The non-production environment's *name* is
configurable - `NON-PROD`, `MOD`, `UAT`, `STAGE`, or a typed value
([app/models.py](app/models.py#L29-L31)). A report whose non-production environment is labelled
`UAT` would still print a status reading `Open (Resolved on Non-Prod)`. Making the label follow
`non_production_label` is rejected below; if the user would rather it read generically, the moment
to choose a wording like `Open (Resolved on Non-Production)` is now, before any draft holds it.

*Absent an answer:* `open_resolved_on_non_prod` / `Open (Resolved on Non-Prod)` in all three places.

#### Q2 - does a retest import keep the new status, or quietly rename it? *(the scribe's decision)*

Today the retest branch rewrites **every** retained finding to `open_previously_discovered`
unconditionally, and `statuses_rewritten` discloses only findings that were `open_new`
([app/docx_import.py](app/docx_import.py#L941-L954)). So a finding the tester deliberately marked
`Open (Resolved on Non-Prod)` comes back renamed, with no notice anywhere.

- **(a) Leave it, silent.** Zero code. The retest's premise is that the finding is being tested
  afresh, which is why the status is normalised at all. The scribe recommends this.
- **(b) Leave it, disclosed.** One `or` on [L944](app/docx_import.py#L944) so the new status joins
  `statuses_rewritten`, plus widening the manager notice, which currently reads "N Open New
  finding(s) were changed to Previously Discovered for retesting"
  ([app/web/static/manager.js](app/web/static/manager.js#L200)) and would otherwise be wrong for
  this value. Two small edits, not one.
- **(c) Retain it verbatim.** Skip the rewrite for the new status. Largest change, and I think
  wrong: a retest is precisely the run in which "resolved on non-prod" stops being true.

**Recommendation: (b).** The user is adding this status to record a distinction they care about;
renaming it with no notice is the kind of quiet loss that later reads as "the app changed my data".
It is an honest disagreement with the scribe, whose (a) is defensible and free - if the user wants
the smaller commit, (a) is fine and this plan drops one sub-step.

*Absent an answer:* (b).

#### Q3 - the trailing-space autosave: accept, or strip? *(the oracle's decision, re-scoped)*

Given the correction above, the real behaviour while the username reads `"john "` is: the Setup save
state shows `Correct invalid Setup fields` and the save waits. Nothing is rejected, nothing is lost,
and it clears itself on the next keystroke.

**Recommendation: accept it - no code.** Stripping server-side would make the PUT response differ
from what the client sent, and `reconcileCanonicalObject`
([app/web/static/app.js](app/web/static/app.js#L433-L481)) overwrites the live value whenever it
still equals what was sent - so the value would change under the user's caret. That trades a
transient status line for a mid-typing edit of the user's own input.

*Absent an answer:* accept, no step.

#### Q4 - does the new status print the same sections as `open_previously_discovered`?

**Recommendation: yes, by doing nothing.** `content_types_for_status` is a single
`if status == "open_new"` ([app/report_service.py](app/report_service.py#L251-L256)), so the new
value prints description, recommended remediation, previous proof of concept, proof of concept and
in conclusion for free, and `docx_report` picks `retest_finding.docx` for free
([app/docx_report.py](app/docx_report.py#L759)).

Three visible consequences to confirm now rather than discover in a rendered report:

1. The finding prints a **Previous Proof of Concept** heading and an **In Conclusion** heading.
2. The default In Conclusion sentence reads `The finding "X" is still Open.` - not "Resolved on
   Non-Prod". Making it name the new status is rejected below.
3. The editor shows **Severity Review Tickets** and the document prints
   `Severity Review Ticket (if applicable):`, reading `N/A` when the tester leaves it empty
   ([app/docx_report.py](app/docx_report.py#L776)). The scribe flagged this as the one visible
   document difference from `open_new` that nobody had named.

*Absent an answer:* all three as described, no code.

### Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write | clear | No new mutation route. Status rides the existing `PUT /reports/{id}`, which already carries `saved_at` in the body; changes 1 and 3 add no route at all. |
| Lost update | clear | Nothing new reads then writes. `load_path`'s existing read-modify-write is untouched because no repair is being added - see *What I would not do*. |
| Orphan reference | clear | The one section dropped outright on a move to `open_new` is `in_conclusion`, which admits only `paragraph` and `note` ([app/web/static/app.js](app/web/static/app.js#L121)) - no `evidence_id` can live there. Dropping a whole `Content` takes its fragments with it, so no `frag_id` is stranded. Moves between `open_previously_discovered` and the new status carry everything (oracle: same five sections, the quietest possible transition). |
| Silent stranding | **RISK** | `RETAINED_STATUSES` ([app/docx_import.py](app/docx_import.py#L59)). Left unextended, a retest import drops an **open** finding and discloses it under `dropped_resolved` - a lie about why. The scribe calls this "the one silent failure in the whole change". Closed by Step C3. |
| Schema break | **RISK, one direction only** | Adding is permissive: all 14 drafts hold only the three existing values (oracle), so nothing on disk stops loading and no repair is needed. **Removing or renaming later is not recoverable through the UI** ([app/workspace.py](app/workspace.py#L147)). The stored key must be right in the first commit, which is why Q1 blocks. |
| Request/response asymmetry | clear | `status` is a stored model field echoed by `model_dump`; unlike `scope_text` it is not client-only. The PUT response is merged back through `applyCanonicalReport` ([app/web/static/app.js](app/web/static/app.js#L483-L488)) carrying the same value the client sent. |
| Rule drift | **RISK, two separate ones** | **(a)** The status label exists in **four** places - `STATUS_LABELS`, `STATUS_BY_LABEL`, `statuses` in `app.js`, `labels` in `manager.js` - and the oracle confirms **no drift guard covers them**. Mitigation here is ordering, not a new contract test: C4 goes last, so a half-finished change leaves the value unselectable rather than unprintable. **(b)** Change 1 touches the *unnamed* username twin whose only guard is the row at [tests/test_browser.py](tests/test_browser.py#L133); deleting that row instead of swapping its invalid character removes the guard silently. Step A2 exists for nothing else. |
| Navigation trap | clear | Status has a default and every completeness check is truthiness only - `finding_is_complete` ([app/report_service.py](app/report_service.py#L806)) and `updateFindingSummary` ([app/web/static/app.js](app/web/static/app.js#L2284)). No new required field and no new gate, so no page can become unreachable. |
| Derived-state fight | clear as planned; **RISK if Q3 answers "strip"** | `provision_report` does not branch on status at all ([app/main.py](app/main.py#L262-L266)) and every `provision` branch keys on `== "resolved"` or `== "open_new"`, so the new value takes else-arms and the server writes nothing back. But server-side username stripping would return a value the client did not send, and `reconcileCanonicalObject` would write it into the live report under the caret. That is the strongest argument for Q3's recommended answer. |
| Backup exhaustion | clear, **conditional** | Only because no migration is planned. A `load_path` repair for the new status would rewrite every draft to change nothing and burn the single `draft.bak.json` level ([docs/DATA_MAP.md](docs/DATA_MAP.md) §6). Adding one turns this row red. |
| Generation crash *(extra row)* | **RISK** | `STATUS_LABELS[finding.status]` is a bare index at [app/docx_report.py](app/docx_report.py#L516) and [L769](app/docx_report.py#L769). Unextended, the first generation of a new-status finding raises a raw `KeyError` inside `render_report_docx` - a 500 with no readable message rather than a `ReportGenerationError`. Closed by Step C2, and ordering C2 before C4 means it cannot be reached even mid-implementation. |
| Autosave rejection while typing *(extra row)* | clear - **the oracle's premise is wrong** | `save()` gates on `validateSetupInputs(false)` on the Setup step ([app/web/static/app.js](app/web/static/app.js#L769-L772)), so a half-typed `"john "` is never sent and never 422s. See the correction above. |
| `N/A` bullet on import *(extra row)* | clear | `_visible_value` returns `""` for exactly `"N/A"` ([app/docx_import.py](app/docx_import.py#L90-L93)), so it is discarded before matching; `_detail_locations` reads text and never inspects `w:numPr`. The scribe checked this and named the production-only import tests that already exercise the `N/A` cell today. |
| Legacy remediation blanking on `resolved` → new status *(extra row)* | clear, pre-existing | `load_path`'s `elif stale:` arm empties an unmarked legacy `"None, the vulnerability has been remediated."` paragraph for any non-`resolved` status ([app/workspace.py](app/workspace.py#L292-L296)). The new value inherits exactly what `open_previously_discovered` does today. No behaviour changes and no step is warranted - worth knowing, not worth coding around. |

### Plan

Three independent groups. A and B can be implemented, reviewed or dropped without touching C.
Within C the order matters and is explained at C4.

#### Group A - allow spaces in the username

Suite: `tests.test_app` for A1, `tests.test_browser` for A2.

- [ ] **Step A1 - widen the username character set on both sides.**
  Files: [app/report_service.py](app/report_service.py#L21) (`USERNAME_PATTERN` interior class),
  [app/report_service.py](app/report_service.py#L186) (drop `allow_spaces=False`),
  [app/web/static/app.js](app/web/static/app.js#L1472) (`usernameCharacters`),
  [app/web/static/app.js](app/web/static/app.js#L1497) (the inline shape regex).
  Put the space where it cannot form a range - immediately after the `[`, giving
  `[ A-Za-z0-9._@\\-]` - so the trailing `-` stays literal in all four patterns.
  Test: `tests/test_app.py::test_setup_input_validation_rejects_unapproved_characters_and_date_order`
  - swap the negative case `"bad user"` for `"bad/user"` expecting
  `'Username 1 contains invalid character: "/" (slash)'`, and change the positive case's username
  from `DOMAIN\qa.user@example` to `DOMAIN\qa user@example` so one value proves the backslash pin
  and the new space in the same assertion.
  Invariant: the start/end anchors stay, so a leading or trailing space is still invalid, and `N/A`
  stays exempt by literal comparison on both sides.

- [ ] **Step A2 - keep the message drift guard alive.**
  File: [tests/test_browser.py](tests/test_browser.py#L133).
  **Swap the row in place, do not delete it:**
  `("Username 1", "bad/user", "DOMAIN\\qa user@example", 'Username 1 contains invalid character: "/" (slash)')`.
  Test: `tests.test_browser::test_setup_inputs_report_character_and_date_errors_before_save`.
  Invariant: the browser's `validationMessage` stays byte-identical to the server's issue string for
  the one field whose per-character allowlist has no other guard.

#### Group B - `N/A` as a bulleted list

Suite: `tests.test_docx` and `tests.test_docx_import`.

- [ ] **Step B1 - stop taking the empty early return.**
  File: [app/docx_report.py](app/docx_report.py#L711-L713) - replace the three lines with
  `values = values or ["N/A"]`.
  Test: new, in [tests/test_docx.py](tests/test_docx.py) - render a production-only finding, then
  assert the Non-Production Location cell's second paragraph is styled `List Paragraph`, carries a
  `w:numPr` under its `w:pPr`, reads `N/A`, and that the cell text contains no `\u2022`. The scribe
  confirms no existing test asserts the empty cell at all, so without this the change lands green
  with nothing proving it.
  Invariant: the token paragraph is still removed, so `_unresolved_placeholders` stays satisfied and
  generation does not abort; `_visible_value` still maps `N/A` to `""` on import, so the round trip
  is unchanged.

- [ ] **Step B2 - correct the template document.**
  File: [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L232-L235) - say the `N/A` placeholder is
  bulleted too. Test: none.

#### Group C - the fourth finding status

Suite: `tests.test_app` for C1, `tests.test_docx_import` for C2 and C3, `tests.test_browser` for C4.
**Q1 must be answered before Step C1.**

- [ ] **Step C1 - extend the enum, server side only.**
  File: [app/models.py](app/models.py#L10) - `Status` gains the agreed key.
  Test: new, in [tests/test_app.py](tests/test_app.py) - PUT a finding carrying the new status,
  expect 200, and assert `content_types_for_status(<new>)` returns the five-section set.
  Invariant: no `load_path` repair and no migration. Widening a `Literal` is permissive, so every
  draft on disk still loads unchanged and the single `draft.bak.json` level stays unspent.

- [ ] **Step C2 - teach the document the label.**
  File: [app/docx_report.py](app/docx_report.py#L48-L52) - `STATUS_LABELS` gains the key.
  Test: extend `tests/test_docx_import.py::test_editable_mode_keeps_all_statuses_and_printed_sections`
  with a fourth finding carrying the new status, asserting both its status and its five printed
  section types survive a render-then-import round trip. That one test covers the render, the label,
  the summary/detail cross-check and `STATUS_BY_LABEL` together.
  Invariant: the two bare indexes at [L516](app/docx_report.py#L516) and
  [L769](app/docx_report.py#L769) read the one dict, so the summary table and the detail token
  cannot disagree - which is what the importer's `'"X" summary and detail values do not match.'`
  check depends on. Closes the `KeyError` 500.

- [ ] **Step C3 - teach the importer the label, and keep the finding.**
  Files: [app/docx_import.py](app/docx_import.py#L53-L57) `STATUS_BY_LABEL` (`LABEL_BY_STATUS`
  derives free), [L59](app/docx_import.py#L59) `RETAINED_STATUSES`,
  [L1160](app/docx_import.py#L1160) the `status_counts` tuple. **If Q2 answers "disclose":** also
  [L944](app/docx_import.py#L944) and the notice wording at
  [app/web/static/manager.js](app/web/static/manager.js#L200).
  Test: one new assertion alongside
  `tests/test_docx_import.py::test_a_generated_report_imports_as_a_retest_draft` - a new-status
  finding is retained by a retest import and does not appear in `dropped`.
  Invariant: **no open finding is ever dropped by a retest import and reported as
  `dropped_resolved`.** This is the only failure in the whole change that produces no error.

- [ ] **Step C4 - open the dropdown. Last.**
  Files: [app/web/static/app.js](app/web/static/app.js#L119) `statuses`,
  [app/web/static/manager.js](app/web/static/manager.js#L208) `labels`.
  Test: one new browser test - the option exists with the agreed label, selecting it renders the
  five sections, and the finding-card chip prints the label rather than the raw key.
  Invariant: the client never offers a status the server would 422, and nothing can reach a document
  that cannot be labelled. **This step is the gate that lets the value into a saved draft, so every
  consumer must already handle it.** Doing C4 before C1 lets a user save a value the model rejects;
  before C2 it lets them reach a `KeyError` at generation; before C3 it lets a retest import eat
  their finding.

- [ ] **Step C5 - correct the two stale document-doc claims and record the twin.**
  Files: [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L218-L220) and
  [L248-L250](docs/DOCX_TEMPLATE.md#L248-L250) (both enumerate the statuses that use
  `retest_finding.docx` and print `{{severity-review-tickets}}`); [docs/DATA_MAP.md](docs/DATA_MAP.md)
  §7 for the fourth status value and §12 for the status-label table as a **four-copy twin with no
  drift guard**. While there, add the two absences the oracle found: the `location_values`
  `get` versus `||` divergence, and `workspace.load_path` as a fourth Python site branching on
  `status == "resolved"`.
  Test: none.

### What I would not do

1. **No `load_path` repair or migration for the new status.** Widening a `Literal` is permissive and
   every draft on disk already validates. A repair would rewrite 14 files to change nothing and
   consume the single `draft.bak.json` level - the `non_production_label` precedent. It turns the
   backup-exhaustion row red in exchange for nothing.
2. **No `.get()` fallback on `STATUS_LABELS`.** Tempting, because the bare index is a 500. But an
   invented label would be written into a document and read back as garbage, and `STATUS_BY_LABEL`
   would refuse it on import. The `KeyError` is the correct failure - loud, at generation, before
   anything is written. Extend the dict.
3. **No new drift-guard test for the four status-label tables.** It is the honest gap the oracle
   names, but building one means asserting a JavaScript array against two Python dicts and a second
   JavaScript object - a contract-test harness for a table that changes about once a year. Ordering
   C4 last buys the practical half of it. Record the gap in `DATA_MAP.md` and move on.
4. **No status-aware In Conclusion sentence.** It is a three-part change across
   `status_conclusion_runs`, `STATUS_CONCLUSION_PATTERN` and both JavaScript twins, and the
   recogniser must keep the old `(?:Open|Resolved)` alternation forever or every default sentence
   already on disk stops matching and freezes at its stored wording. Wildly out of proportion to
   "add an option to a dropdown".
5. **No dynamic status label following `non_production_label`.** `STATUS_BY_LABEL` is a static
   reverse map; a per-report label makes a generated document un-importable unless the importer
   learns every preset and every typed custom value.
6. **No server-side username stripping** - see Q3. It would put the server in a fight with the
   client over a field the user is actively typing in.
7. **No fix for the two adjacent divergences the oracle found** - the `location_values`
   `get` versus `||` empty-string leak, and the Unicode-letter asymmetry in the username message.
   Both are real, neither is in this request, and both would enlarge a change the user asked to keep
   small. They go in `DATA_MAP.md` as known, not into this commit.
8. **No change to the Limitations `N/A`.** `_center_plain` ([app/docx_report.py](app/docx_report.py#L445-L454))
   deliberately strips the bullet and centres it. After Step B1 the two tables disagree on purpose -
   affected locations is a list of many things, Limitations is one statement. The scribe asked that
   this be a decision rather than an accident: this is the decision, and the user can object to it
   here.

## Round 2 - Oracle: verdict on the proposal

Short version: the planner's correction of me is **right**, the seven-edit blast radius is **complete**
for code, and every draft on disk is **safe**. Three risk rows need rewording and one documentation
site is missing from Step C5. Nothing here changes the plan's shape.

### 1. The save gate exists. My round-1 claim is withdrawn.

The planner is correct and I was wrong. [app/web/static/app.js](app/web/static/app.js#L767-L770),
inside `save()`:

```javascript
if (root.dataset.step === "setup" && !validateSetupInputs(false)) {
  setSaveState(SAVE_STATES.UNSAVED, "Correct invalid Setup fields");
  return false;
}
```

I read `validateSetupInputs`'s *call sites inside `setup()`* and missed this one at module scope.
The chain is real end to end: `validateSetupInputs` is assigned at
[app/web/static/app.js](app/web/static/app.js#L1514) (module-level `let ... = () => true` at
[L196](app/web/static/app.js#L196)), it filters `root.querySelectorAll("[data-setup-validated]")` on
`input.validity.valid`, and the username inputs are genuinely in that set -
`wireSetupRule(usernameInput, setupRules.username, ...)` at
[app/web/static/app.js](app/web/static/app.js#L1664) sets `dataset.setupValidated` and calls
`setCustomValidity` on every `input` event ([L1500-L1513](app/web/static/app.js#L1500)).

**Treat my round-1 sentence "nothing on the client blocks a save on setup rules" as withdrawn. Do
not plan against it.** Every ordinary route to the server funnels through `save()` and inherits the
gate: the idle timer ([L337-L339](app/web/static/app.js#L337)), the Save button (which gates a
second time with `reveal=true`, [L846](app/web/static/app.js#L846)), `#next`
([L2781-L2784](app/web/static/app.js#L2781)), `.back-link` ([L893](app/web/static/app.js#L893)),
`visibilitychange` ([L945](app/web/static/app.js#L945)), Generate
([L860](app/web/static/app.js#L860)), library insert ([L2675](app/web/static/app.js#L2675)),
evidence upload ([L2823](app/web/static/app.js#L2823)) and conflict resolution
([L520](app/web/static/app.js#L520)).

Two of the routes you asked me to check are **not** holes:

- **No keyboard save.** The only global key handler is
  [app/web/static/app.js](app/web/static/app.js#L918-L922), and it matches Ctrl/Cmd+Z and
  Ctrl/Cmd+Shift+Z only. There is no Ctrl+S.
- **No beforeunload flush to the server.** `pagehide`
  ([L932-L936](app/web/static/app.js#L932)) calls `persistLocalDraft()` and nothing else;
  `beforeunload` ([L938-L943](app/web/static/app.js#L938)) does the same and prompts. Neither sends
  a `PUT`.

### 2. The gate is step-scoped, and undo/redo walks around it

The gate's condition is `root.dataset.step === "setup"`. The username is a Setup field, but it rides
in the same report object that **every** page saves. So any route that puts an invalid Setup value
into `report` while the tester is on Findings or Content produces an ungated `PUT`, and
`setup_input_issues` runs on every `PUT` ([app/main.py](app/main.py#L785-L791)) and answers 422
`invalid_setup`.

**The reachable route is undo/redo, and it is not exotic.**

- The history lives in `sessionStorage` under `vulnreport-history:{reportId}`
  ([L64](app/web/static/app.js#L64)), is read at load ([L110](app/web/static/app.js#L110)) and
  rewritten on every action ([L574](app/web/static/app.js#L574)). `sessionStorage` survives same-tab
  navigation, so **actions recorded on Setup are still in the stack on Findings**.
- The Ctrl+Z handler is registered on `document` unconditionally
  ([L918](app/web/static/app.js#L918)), and `#undo-button` / `#redo-button` are in the header of
  **all three** pages ([page1_setup.html](app/web/templates/page1_setup.html#L3),
  [page2_findings.html](app/web/templates/page2_findings.html#L3),
  [page2_editor.html](app/web/templates/page2_editor.html#L3)).
- `restoreHistory` ([L579-L605](app/web/static/app.js#L579)) mutates `report` with `applyChanges` and
  then calls `save()` directly. Off Setup, the gate is skipped.

Concretely, with the space allowed: type `john ` into Username and click away. `finalizeTextTransaction`
([L556-L566](app/web/static/app.js#L556)) closes one action `N/A -> "john "`. The save is blocked and
you stay on Setup. Return, type `smith`; a second action `"john " -> "john smith"` is recorded, the
value is valid, the save lands, `#next` to Findings. **Ctrl+Z on Findings undoes that second action,
putting `"john "` back into `report`, and `save()` sends it.** 422.

Three details make the aftermath worse than a transient error, and all three are pre-existing:

1. `restoreHistory` sets `allowUnsavedUnload = true` and reloads **regardless of whether the save
   succeeded** ([L603-L605](app/web/static/app.js#L603)), so the diagnostic is wiped off the screen.
2. It first writes `recoverySelectionKey = localDraftKey` ([L594](app/web/static/app.js#L594)), so the
   invalid draft is *restored* on the reload ([L90-L97](app/web/static/app.js#L90)) and
   `queueBackendSave()` fires again ([L947-L951](app/web/static/app.js#L947)). The second 422 is not
   auto-retried - the retry arm requires `!error.status || error.status >= 500`
   ([L818](app/web/static/app.js#L818)) - so it settles at "Save failed - Retry".
3. `.back-link` navigates only `if (await save())` ([L893](app/web/static/app.js#L893)) and `#next`
   likewise ([L2783-L2787](app/web/static/app.js#L2783)). **Both directions are now blocked, and the
   only page holding the offending field is the one the tester cannot reach.**

A second, quieter variant: the gate reads the **DOM**, not `report`. `restoreHistory` does not
re-render, so even on Setup an undo is judged against the pre-undo input values. And a local
recovery draft restored while on Findings or Content
([L90-L97](app/web/static/app.js#L90) then [L947-L951](app/web/static/app.js#L947)) saves ungated for
the same reason.

**Does this change Q3? No - keep "accept, no code".** The identical sequence with `"john."` produces
the identical 422 today; a trailing space only makes the blur-boundary pause more likely. Stripping
server-side would close this one case and open the `reconcileCanonicalObject` fight the planner
correctly names. What should change is the **wording** of the risk row, from "never sent and never
422s" to "not sent by the typing path; undo/redo and draft recovery on another page are not gated".
Q3 is a confirmation, not a decision - it does not need to be put to the user as a choice.

### 3. Risk rows: five confirmed, three need rewording

**Confirmed as written**, each verified in source:

| Row | Verification |
|---|---|
| Silent stranding | `RETAINED_STATUSES` [app/docx_import.py](app/docx_import.py#L59); the drop is [L922-L924](app/docx_import.py#L922) and it is disclosed under `dropped_resolved` at [L1151-L1155](app/docx_import.py#L1151). Genuinely the only silent failure. |
| Schema break one-way | `list_legacy_reports` sets `"repairable": "duplicate fragment id:" in reason` ([app/workspace.py](app/workspace.py#L132-L148)); `repair_duplicate_fragment_ids` raises for anything else ([L217-L240](app/workspace.py#L217)). The manager path behaves exactly as assumed. |
| Rule drift, both halves | Four label copies confirmed: [app/docx_report.py](app/docx_report.py#L48-L52), [app/docx_import.py](app/docx_import.py#L53-L58), [app/web/static/app.js](app/web/static/app.js#L119), [app/web/static/manager.js](app/web/static/manager.js#L208). No drift guard covers them. |
| Generation crash | Bare indexes confirmed at [app/docx_report.py](app/docx_report.py#L516) and [L769](app/docx_report.py#L769). |
| Derived-state fight, conditional | `provision_report` ([app/main.py](app/main.py#L262-L266)) calls `provision` and `sync_evidence_image_slots` and branches on status nowhere. |
| Orphan reference | `allowed.in_conclusion` is `["paragraph","note"]` ([app/web/static/app.js](app/web/static/app.js#L121)) - no image type, so no `evidence_id` can be stranded. |

One footnote on the orphan row: dropping `in_conclusion` leaves any
`content_offer_dismissed["in_conclusion"]` and `content_offer_resolved["in_conclusion"]` key behind.
`ContentType` still admits the key, so nothing fails validation and nothing reads the latter at all
([docs/DATA_MAP.md](docs/DATA_MAP.md) §6). Harmless - but "nothing is left behind" is not quite true,
and it costs one clause to say so.

**Three rows marked `clear` that are not, and one that is right but overstated.**

**(a) "Autosave rejection while typing - clear" is half right.** See section 2. Reword to name the
step-scoping and the undo/redo route. No step follows.

**(b) "Schema break" understates the door, because the key does not only live on disk.** The
planner's reasoning covers `draft.json`. The stored key also lands in **two browser stores that no
server-side migration can ever reach**:

- `localStorage["vulnreport-pending:{reportId}:{tabId}:{uuid}"]` holds the **entire report**
  ([app/web/static/app.js](app/web/static/app.js#L316-L323)).
- `sessionStorage["vulnreport-history:{reportId}"]` holds the before/after values of up to twenty
  actions ([L574](app/web/static/app.js#L574)).

Neither is validated on read - `report = selectedDraft.envelope.report`
([L94](app/web/static/app.js#L94)) is raw JSON assigned straight into report state. So if the value
is ever renamed or the change reverted - including simply opening an older build from a `dist/` zip -
a restored draft or an undone action carries the dead key into `report` and the next save is 422
`invalid_report`, with no way out but *Load latest* ([L521-L531](app/web/static/app.js#L521)), which
discards the local work.

Worse, it is **invisible until the save**: `select(statuses.map(x => x[0]), finding.status)`
([L2561](app/web/static/app.js#L2561)) emits options for the known values only, and with no matching
`selected` option and no placeholder arm (the placeholder requires `nullable || values === severity`,
[L279](app/web/static/app.js#L279)) the browser displays the **first** option - Open (New) - while
`report` still holds the unknown key. The finding-card chip
([L3769](app/web/static/app.js#L3769)) falls back to the raw key, so the table row and the chip
disagree and neither is what will be saved. This does not change the plan; it sharpens why Q1 blocks
and why "recovery means hand-editing JSON" is optimistic - it also means clearing browser storage.

**(c) "Navigation trap - clear" is correct for change 2 and wrong as a general statement.** No new
required field and no new gate is added, so nothing about the status makes a page unreachable - agreed.
But the app already has the trap described in section 2: an invalid Setup value in `report` while off
Setup blocks Back and Next together. Change 1 makes it marginally more likely rather than creating it.
Name it in the row; do not code around it in this change.

**(d) "Lost update - clear" is right, with one thing worth knowing.** `load_path`
([app/workspace.py](app/workspace.py#L272-L299)) already performs a read-modify-write and calls
`atomic_write_json` whenever `repaired`, **on load, before any save**. Nothing about this change
touches it - but the planner's neighbouring "backup exhaustion" row implies a new migration is the
only way to spend the single `draft.bak.json` level, and that is not so.

### 4. Files and twins: the code list is complete; one documentation site is missing

I re-checked every twin I named in round 1 against Step C1-C5. **All of them are accounted for**, and
in each case the planner's reason for touching or not touching is the one the source supports:

| Twin | Verdict |
|---|---|
| `content_types_for_status` / `contentTypesForStatus` | correctly **not touched** - [app/report_service.py](app/report_service.py#L251-L256) is a single `if status == "open_new"` and the JS mirror at [app/web/static/app.js](app/web/static/app.js#L1075-L1077) matches |
| the four label tables | all four in the blast radius |
| resolved-remediation boilerplate | correctly untouched. `provision`'s else-arm strips any fragment marked `generated == "resolved_remediation"` and seeds an empty paragraph ([app/report_service.py](app/report_service.py#L313-L322)); mirrored at [app/web/static/app.js](app/web/static/app.js#L1103) and the editor lock at [L4027](app/web/static/app.js#L4027); `workspace.load_path`'s `elif stale` arm ([app/workspace.py](app/workspace.py#L292-L297)) inherits `open_previously_discovered`'s behaviour exactly |
| conclusion builder / recogniser | correctly untouched |
| completeness and readiness | truthiness only, confirmed at [app/report_service.py](app/report_service.py#L806) and [app/web/static/app.js](app/web/static/app.js#L2284) |

**Nothing in `app/`, `tests/`, `scripts/` or `resources/` is missing from the step list.** `scripts/`
is clean: [scripts/generate_showcase_reports.py](scripts/generate_showcase_reports.py#L459) uses one
status and [scripts/compose_component_test.py](scripts/compose_component_test.py#L48) hardcodes one
label; neither enumerates. Templates enumerate nothing, as round 1 said.

**The one miss is in Step C5.** [docs/DATA_MAP.md](docs/DATA_MAP.md#L411) carries a **Segment x Status
matrix** describing which Additional Information fields are visible:

| Segment | Open (New) | Open (Previously Discovered) | Resolved |
|---|---|---|---|
| Asia | CVSS pair | all three | all three |
| JH, GWAM | **hidden** | tickets only | tickets only |

It needs a fourth column, and it behaves like `open_previously_discovered` because
`additionalInformationFields` gates on `status !== "open_new"`
([app/web/static/app.js](app/web/static/app.js#L3372)). C5 names §7 and §12 generically but not this
table, and it is the only place in the map that enumerates the statuses exhaustively. One further
site goes stale and is probably not worth a step: [docs/PLAN.md](docs/PLAN.md#L169) enumerates
"Open (Previously Discovered) and Resolved" for In Conclusion.

**Is `RETAINED_STATUSES` the only importer-side list?** No - there are **four** importer-side
enumerations, and the planner has all four:

1. `STATUS_BY_LABEL` ([app/docx_import.py](app/docx_import.py#L53-L57))
2. `LABEL_BY_STATUS`, derived ([L58](app/docx_import.py#L58))
3. `RETAINED_STATUSES` ([L59](app/docx_import.py#L59))
4. the literal tuple in `status_counts` ([L1157-L1161](app/docx_import.py#L1157)), which I confirm is
   **editable-mode only** - it sits inside `if mode == "editable":`

Every other importer site is a `==` or `!=` comparison that falls through correctly:
[L655](app/docx_import.py#L655), [L778-L780](app/docx_import.py#L778),
[L881](app/docx_import.py#L881), [L922](app/docx_import.py#L922), [L929](app/docx_import.py#L929),
[L943](app/docx_import.py#L943), [L953](app/docx_import.py#L953). So `RETAINED_STATUSES` is the only
**membership set**, and the planner's list of four is complete.

### 5. No draft on disk is broken by adding the value

I searched every JSON under `data/apps/`, including the `.bak.json` siblings. **45 `status` values
across 10 files, and all 45 are one of the three existing keys.** The largest is
`Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json` with 14
findings, all `open_new` except one `open_previously_discovered`;
`Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json` is the only file carrying all
three. The remaining drafts hold no findings and therefore no status at all.

Widening a `Literal` is strictly permissive, so **every one of them loads unchanged**, no `load_path`
repair is needed, and adding one would be wrong for the reason the planner gives. The planner's claim
is confirmed; the only correction is arithmetic - it is 10 files rather than 14 drafts, because most
drafts carry no findings.

### Map drift

**None corrected.** Every claim in [docs/DATA_MAP.md](docs/DATA_MAP.md) I checked this round held
against source: `content_types_for_status` as single owner (§7), the `in_conclusion` carry exception
(§7), the Additional Information visibility rule and its matrix (§12), the legacy-report repair gate
(§6), and the `non_production_label` one-way-door precedent (§6). Nothing in the map was edited.

Three things are **absent** from the map rather than wrong in it, and Step C5 should carry all three
rather than the two it currently lists:

1. The `location_values` `get` versus `||` divergence (round 1).
2. `workspace.load_path` as a fourth Python site branching on `status == "resolved"` (round 1).
3. **That `save()`'s Setup validity gate is step-scoped, and that undo/redo and draft recovery reach
   `save()` from every page** - the finding in section 2. This is the one a future reader is most
   likely to get wrong, because I got it wrong in both directions in one exchange.

## Round 2 - Planner: revised plan

This is round 1 with the oracle's three corrections folded in. The shape is unchanged: three
independent groups, seven one-line code edits for the status, four for the username, one for the
bullet. Nothing below is a rewrite of a step that already passed verification.

### What changed from round 1

Three things, all of them reasoning rather than steps, plus one file added to one step.

1. **The save gate is step-scoped, and undo/redo walks around it.** My round-1 correction of the
   oracle was right as far as it went - `save()` does gate on `validateSetupInputs(false)`
   ([app/web/static/app.js](app/web/static/app.js#L767)) - but that gate reads
   `root.dataset.step === "setup"`, while undo/redo is global and `restoreHistory` calls `save()`
   directly. The consequence is now stated as accepted rather than left unsaid; see *Stated
   assumptions* below and the reworded risk row.
2. **The schema-break risk is wider than disk.** The stored status key also lands in `localStorage`
   (the whole report) and `sessionStorage` (undo diffs), neither validated on read, neither
   reachable by a server-side migration. Folded into that row's reasoning.
3. **Step C5 gains [docs/DATA_MAP.md](docs/DATA_MAP.md#L411)'s Segment x Status matrix**, which
   needs a fourth column. It is the only place in the map that enumerates the statuses exhaustively.

Confirmed by the oracle and carried forward unchanged: the seven-edit list is complete, all six
status twins are accounted for, `RETAINED_STATUSES` is the only importer-side membership set, and
all 45 status values across the real drafts under `data/apps/` are existing keys, so adding the enum
value breaks nothing on disk. One arithmetic correction to my round-1 wording: it is 45 values
across 10 files, not 14 drafts, because most drafts carry no findings.

**Q3 is no longer a question.** My recommended answer survived the oracle's correction, so it is
recorded as an assumption below. Two questions remain.

### Stated assumptions - decided, not asked

**Assumption 1 - the trailing space is accepted, with a known consequence off the Setup page.**
No code. Two behaviours follow, and the second is the one worth writing down:

- *On Setup, while typing.* `save()` gates every save - autosave included - on
  `validateSetupInputs(false)` ([app/web/static/app.js](app/web/static/app.js#L767)), so a value
  sitting at `"john "` is never sent. The save state line reads `Correct invalid Setup fields` and
  the next keystroke that makes the value valid reschedules the save. Nothing is lost.
- *Off Setup, via undo/redo or draft recovery.* The gate's condition is
  `root.dataset.step === "setup"`, but the history lives in `sessionStorage` and survives navigation,
  the Ctrl+Z handler is registered on `document` on all three pages, and `restoreHistory` mutates
  `report` and calls `save()` directly. **So Ctrl+Z on Findings can put `"john "` back into `report`
  and send it, producing a 422 `invalid_setup`; `.back-link` and `#next` both navigate only on a
  successful save, so both directions are then blocked and the only page holding the field is the
  one the tester cannot reach.**

**This is accepted, deliberately.** The identical sequence with `"john."` reaches the identical 422
today - the trap is pre-existing and change 1 only makes the pause point more natural. The two ways
out both cost more than they buy: stripping the username server-side would return a value the client
did not send, and `reconcileCanonicalObject` ([app/web/static/app.js](app/web/static/app.js#L433))
would write it into the live report under the user's caret; widening the gate to cover every page is
a change to undo/redo, which is not what was asked for here. Step A3 writes the consequence into the
map so the next person to touch `save()` finds it. If the user would rather not accept it, the
alternative is a separate change to `restoreHistory`, not an edit to the username rule.

**Assumption 2 - the new status prints the same sections as `open_previously_discovered`**, by doing
nothing. `content_types_for_status` is a single `if status == "open_new"`
([app/report_service.py](app/report_service.py#L251)), so the new value prints description,
recommended remediation, previous proof of concept, proof of concept and in conclusion for free, and
`docx_report` picks `retest_finding.docx` for free ([app/docx_report.py](app/docx_report.py#L759)).
Three visible consequences, confirmed here rather than discovered in a rendered report: the finding
prints a **Previous Proof of Concept** and an **In Conclusion** heading; the default In Conclusion
sentence reads `The finding "X" is still Open.`, not "Resolved on Non-Prod"; and the editor shows
**Severity Review Tickets**, with the document printing `Severity Review Ticket (if applicable):`
and reading `N/A` when left empty ([app/docx_report.py](app/docx_report.py#L776)).

### Open questions

Two. Q1 blocks Group C entirely. Q2 changes the size of one sub-step. Groups A and B need neither.

#### Q1 - what is the new status called, exactly, in three places? *(blocking)*

Three strings are needed, and only the first is irreversible.

1. **The stored key**, in `Status` and every table. Recommend `open_resolved_on_non_prod`.
2. **The dropdown label**, in `statuses` ([app/web/static/app.js](app/web/static/app.js#L119)).
   Recommend `Open (Resolved on Non-Prod)` - the user's own words.
3. **The document label**, in `STATUS_LABELS` and `STATUS_BY_LABEL`. These two **must be
   byte-identical to each other** or a generated report cannot be re-imported. Making them identical
   to the dropdown as well costs nothing and is what the other three statuses already do.

**Why the key matters more than the labels, restated with the oracle's correction.** Labels are
changeable later at the cost of one regeneration. The stored key is a one-way door in **three**
stores, not one:

- On disk, a renamed key makes an existing `draft.json` fail `Report.model_validate` on load, which
  demotes it to the manager's legacy list, and that list only offers repair when the reason contains
  `"duplicate fragment id:"` ([app/workspace.py](app/workspace.py#L147)).
- In `localStorage`, the pending-draft entry holds the **entire report**
  ([app/web/static/app.js](app/web/static/app.js#L316)) and is assigned straight into report state
  on recovery with no validation ([L94](app/web/static/app.js#L94)).
- In `sessionStorage`, the undo history holds before/after values for up to twenty actions
  ([L574](app/web/static/app.js#L574)), equally unvalidated.

A server-side migration can reach none of the last two. And the failure is **invisible until the
save**: the dropdown renders options for known values only, so an unknown key displays as the first
option - Open (New) - while `report` still holds the unknown value, and the finding-card chip
([L3769](app/web/static/app.js#L3769)) falls back to the raw key, so the two disagree and neither is
what will be saved. Recovery is not just hand-editing JSON; it also means clearing browser storage.
This is the `non_production_label` precedent in [docs/DATA_MAP.md](docs/DATA_MAP.md) §6, with two
extra stores attached.

**One wrinkle worth thirty seconds and no code.** The non-production environment's *name* is
configurable - `NON-PROD`, `MOD`, `UAT`, `STAGE`, or a typed value
([app/models.py](app/models.py#L29)). A report whose non-production environment is labelled `UAT`
would still print a status reading `Open (Resolved on Non-Prod)`. Making the label follow
`non_production_label` is rejected below; if a generic wording like
`Open (Resolved on Non-Production)` is wanted, now is the moment, before any draft holds it.

*Absent an answer:* `open_resolved_on_non_prod` / `Open (Resolved on Non-Prod)` in all three places.

#### Q2 - does a retest import keep the new status, or quietly rename it?

Today the retest branch rewrites **every** retained finding to `open_previously_discovered`
unconditionally, and `statuses_rewritten` discloses only findings that were `open_new`
([app/docx_import.py](app/docx_import.py#L941)). So a finding the tester deliberately marked
`Open (Resolved on Non-Prod)` comes back renamed, with no notice anywhere.

- **(a) Leave it, silent.** Zero code. The retest's premise is that the finding is being tested
  afresh, which is why the status is normalised at all. The scribe recommends this.
- **(b) Leave it, disclosed.** One `or` at [app/docx_import.py](app/docx_import.py#L944) so the new
  status joins `statuses_rewritten`, plus widening the manager notice, which currently reads "N Open
  New finding(s) were changed to Previously Discovered for retesting"
  ([app/web/static/manager.js](app/web/static/manager.js#L200)) and would otherwise be wrong for
  this value. Two small edits, not one.
- **(c) Retain it verbatim.** Skip the rewrite for the new status. Largest change, and I think
  wrong: a retest is precisely the run in which "resolved on non-prod" stops being true.

**Recommendation: (b).** The user is adding this status to record a distinction they care about;
renaming it with no notice is the kind of quiet loss that later reads as "the app changed my data".
It is an honest disagreement with the scribe, whose (a) is defensible and free - if the user wants
the smaller commit, (a) is fine and Step C3 drops its optional half.

*Absent an answer:* (b).

### Blast radius

| File | What changes | Change |
|---|---|---|
| [app/report_service.py](app/report_service.py#L21) | `USERNAME_PATTERN` interior class gains a space | 1 |
| [app/report_service.py](app/report_service.py#L186) | `allow_spaces=False` dropped from the Username call | 1 |
| [app/web/static/app.js](app/web/static/app.js#L1472) | `usernameCharacters` class gains a space - **twin of the row above** | 1 |
| [app/web/static/app.js](app/web/static/app.js#L1497) | inline shape regex gains a space - **twin of `USERNAME_PATTERN`** | 1 |
| [tests/test_app.py](tests/test_app.py#L236) | negative case swapped from space to `/`; positive username gains a space | 1 |
| [tests/test_browser.py](tests/test_browser.py#L133) | the same row, **swapped not deleted** | 1 |
| [docs/DATA_MAP.md](docs/DATA_MAP.md) | §12: the step-scoped save gate and the undo/redo route around it | 1 |
| [app/docx_report.py](app/docx_report.py#L711) | the empty early return becomes `values = values or ["N/A"]` | 3 |
| [tests/test_docx.py](tests/test_docx.py) | new: the empty environment's Location cell is a bullet | 3 |
| [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L232) | the `N/A` placeholder is bulleted too | 3 |
| [app/models.py](app/models.py#L10) | `Status` gains a fourth member | 2 |
| [app/docx_report.py](app/docx_report.py#L48) | `STATUS_LABELS` gains a key | 2 |
| [app/docx_import.py](app/docx_import.py#L53) | `STATUS_BY_LABEL` gains a key; `LABEL_BY_STATUS` derives free | 2 |
| [app/docx_import.py](app/docx_import.py#L59) | `RETAINED_STATUSES` gains a member | 2 |
| [app/docx_import.py](app/docx_import.py#L1160) | the `status_counts` tuple gains a string | 2 |
| [app/web/static/app.js](app/web/static/app.js#L119) | `statuses` gains a pair - **twin of `STATUS_LABELS`** | 2 |
| [app/web/static/manager.js](app/web/static/manager.js#L208) | `labels` gains a key - **third copy of the same table** | 2 |
| [app/docx_import.py](app/docx_import.py#L944) | *only if Q2 answers "disclose"* - the new status joins `statuses_rewritten` | 2 |
| [app/web/static/manager.js](app/web/static/manager.js#L200) | *only if Q2 answers "disclose"* - the notice wording widens | 2 |
| [tests/test_app.py](tests/test_app.py) | new: the new status saves and prints the five-section set | 2 |
| [tests/test_docx_import.py](tests/test_docx_import.py#L685) | a fourth finding in the all-statuses round trip | 2 |
| [tests/test_docx_import.py](tests/test_docx_import.py#L1004) | a retest import retains the new status | 2 |
| [tests/test_browser.py](tests/test_browser.py) | new: the option exists, selects, and labels | 2 |
| [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L218), [L248](docs/DOCX_TEMPLATE.md#L248) | the status lists for `retest_finding.docx` and `{{severity-review-tickets}}` | 2 |
| [docs/DATA_MAP.md](docs/DATA_MAP.md#L411) | **new in round 2** - the Segment x Status matrix gains a fourth column; §7 the fourth value; §12 the four-copy label twin | 2 |

**Deliberately not touched:** `app/workspace.py`, `app/storage.py`, `app/main.py`, `resources/**`
(no `.docx` needs editing or creating), every `provision` branch, `content_types_for_status` and
`contentTypesForStatus`, the conclusion builder/recogniser pair, and `restoreHistory`.

### Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write | clear | No new mutation route. Status rides the existing `PUT /reports/{id}`, which already carries `saved_at` in the body; changes 1 and 3 add no route at all. |
| Lost update | clear | Nothing new reads then writes, and no repair is being added - see *What I would not do*. Worth knowing rather than acting on: `load_path` ([app/workspace.py](app/workspace.py#L272)) already performs a read-modify-write and calls `atomic_write_json` whenever `repaired`, on load and before any save, so a new migration is not the only way to spend a backup level. |
| Orphan reference | clear | The one section dropped outright on a move to `open_new` is `in_conclusion`, which admits only `paragraph` and `note` ([app/web/static/app.js](app/web/static/app.js#L121)) - no `evidence_id` can live there. Dropping a whole `Content` takes its fragments with it, so no `frag_id` is stranded. Moves between `open_previously_discovered` and the new status carry everything. One clause of honesty: any `content_offer_dismissed["in_conclusion"]` / `content_offer_resolved["in_conclusion"]` key is left behind, which `ContentType` still admits and nothing reads - harmless, but not literally nothing. |
| Silent stranding | **RISK** | `RETAINED_STATUSES` ([app/docx_import.py](app/docx_import.py#L59)). Left unextended, a retest import drops an **open** finding at [L922](app/docx_import.py#L922) and discloses it under `dropped_resolved` ([L1151](app/docx_import.py#L1151)) - a lie about why. The one silent failure in the whole change. Closed by Step C3. |
| Schema break | **RISK, one direction, three stores** | Adding is permissive: all 45 status values across the 10 real drafts hold only the three existing keys, so nothing on disk stops loading and no repair is needed. **Renaming or reverting later is not recoverable through the UI**, and not only on disk - the key also lands in `localStorage` as the whole report ([app/web/static/app.js](app/web/static/app.js#L316)) and in `sessionStorage` as undo diffs ([L574](app/web/static/app.js#L574)), neither validated on read and neither reachable by a server-side migration. A stale key then displays as **Open (New)** in the dropdown while `report` holds the dead value, with the finding-card chip showing the raw key - invisible until the save 422s, with no way out but *Load latest*, which discards the local work. This is why Q1 blocks and why the stored key must be right in the first commit. |
| Request/response asymmetry | clear | `status` is a stored model field echoed by `model_dump`; unlike `scope_text` it is not client-only. The PUT response is merged back through `applyCanonicalReport` ([app/web/static/app.js](app/web/static/app.js#L483)) carrying the same value the client sent. |
| Rule drift | **RISK, two separate ones** | **(a)** The status label exists in **four** places - `STATUS_LABELS`, `STATUS_BY_LABEL`, `statuses` in `app.js`, `labels` in `manager.js` - and **no drift guard covers them** (oracle, confirmed in source). Mitigation is ordering, not a new contract test: C4 goes last, so a half-finished change leaves the value unselectable rather than unprintable. **(b)** Change 1 touches the *unnamed* username twin whose only guard is the row at [tests/test_browser.py](tests/test_browser.py#L133); deleting that row instead of swapping its invalid character removes the guard silently. Step A2 exists for nothing else. |
| Navigation trap | clear for change 2; **pre-existing trap named for change 1** | No new required field and no new gate, and every status completeness check is truthiness only - `finding_is_complete` ([app/report_service.py](app/report_service.py#L806)) and `updateFindingSummary` ([app/web/static/app.js](app/web/static/app.js#L2284)) - so nothing about the status makes a page unreachable. But the app **already** has the trap described in *Assumption 1*: an invalid Setup value sitting in `report` while the tester is off Setup blocks `.back-link` and `#next` together, because both navigate only on a successful save. Change 1 makes it marginally more likely; it does not create it, and this change does not code around it. |
| Derived-state fight | clear | `provision_report` does not branch on status at all ([app/main.py](app/main.py#L262)) and every `provision` branch keys on `== "resolved"` or `== "open_new"`, so the new value takes else-arms and the server writes nothing back. This row would turn red only under the rejected username-stripping alternative, where the server returns a value the client did not send and `reconcileCanonicalObject` writes it in under the caret. |
| Backup exhaustion | clear, **conditional** | Only because no migration is planned. A `load_path` repair for the new status would rewrite every draft to change nothing and burn the single `draft.bak.json` level ([docs/DATA_MAP.md](docs/DATA_MAP.md) §6). Adding one turns this row red. |
| Generation crash *(extra row)* | **RISK** | `STATUS_LABELS[finding.status]` is a bare index at [app/docx_report.py](app/docx_report.py#L516) and [L769](app/docx_report.py#L769). Unextended, the first generation of a new-status finding raises a raw `KeyError` inside `render_report_docx` - a 500 with no readable message rather than a `ReportGenerationError`. Closed by Step C2, and ordering C2 before C4 means it cannot be reached even mid-implementation. |
| Autosave rejection while typing *(extra row, reworded in round 2)* | clear for the typing path; **accepted known consequence elsewhere** | The typing path is gated: `save()` checks `validateSetupInputs(false)` on the Setup step ([app/web/static/app.js](app/web/static/app.js#L767)), so a half-typed `"john "` is never sent. But the gate is **step-scoped**, and undo/redo and local draft recovery reach `save()` from every page - `restoreHistory` ([L579](app/web/static/app.js#L579)) mutates `report` and calls `save()` directly, with the history surviving navigation in `sessionStorage`. Ctrl+Z on Findings can therefore send `"john "` and 422, then block Back and Next together. Pre-existing and reachable today with `"john."`; accepted, not coded around. Step A3 records it in the map. |
| `N/A` bullet on import *(extra row)* | clear | `_visible_value` returns `""` for exactly `"N/A"` ([app/docx_import.py](app/docx_import.py#L90)), so it is discarded before matching; `_detail_locations` reads text and never inspects `w:numPr`. |
| Legacy remediation blanking on `resolved` → new status *(extra row)* | clear, pre-existing | `load_path`'s `elif stale:` arm empties an unmarked legacy `"None, the vulnerability has been remediated."` paragraph for any non-`resolved` status ([app/workspace.py](app/workspace.py#L292)). The new value inherits exactly what `open_previously_discovered` does today. No behaviour changes and no step is warranted. |

### Plan

Three independent groups. **A and B can be implemented, reviewed or dropped without touching C**,
and neither needs an answer to Q1 or Q2. Within C the order matters and is explained at C4.

#### Group A - allow spaces in the username

Suite: `tests.test_app` for A1, `tests.test_browser` for A2, none for A3.

- [ ] **Step A1 - widen the username character set on both sides.**
  Files: [app/report_service.py](app/report_service.py#L21) (`USERNAME_PATTERN` interior class),
  [app/report_service.py](app/report_service.py#L186) (drop `allow_spaces=False`),
  [app/web/static/app.js](app/web/static/app.js#L1472) (`usernameCharacters`),
  [app/web/static/app.js](app/web/static/app.js#L1497) (the inline shape regex).
  Put the space where it cannot form a range - immediately after the `[`, giving
  `[ A-Za-z0-9._@\\-]` - so the trailing `-` stays literal in all four patterns.
  Test: `tests/test_app.py::test_setup_input_validation_rejects_unapproved_characters_and_date_order`
  - swap the negative case `"bad user"` for `"bad/user"` expecting
  `'Username 1 contains invalid character: "/" (slash)'`, and change the positive case's username
  from `DOMAIN\qa.user@example` to `DOMAIN\qa user@example` so one value proves the backslash pin
  and the new space in the same assertion.
  Invariant: the start/end anchors stay, so a leading or trailing space is still invalid, and `N/A`
  stays exempt by literal comparison on both sides.

- [ ] **Step A2 - keep the message drift guard alive.**
  File: [tests/test_browser.py](tests/test_browser.py#L133).
  **Swap the row in place, do not delete it:**
  `("Username 1", "bad/user", "DOMAIN\\qa user@example", 'Username 1 contains invalid character: "/" (slash)')`.
  Test: `tests.test_browser::test_setup_inputs_report_character_and_date_errors_before_save`.
  Invariant: the browser's `validationMessage` stays byte-identical to the server's issue string for
  the one field whose per-character allowlist has no other guard.

- [ ] **Step A3 - record the accepted consequence in the map.**
  File: [docs/DATA_MAP.md](docs/DATA_MAP.md) §12 - one short entry: `save()`'s Setup validity gate
  is **step-scoped** (`root.dataset.step === "setup"`), while `restoreHistory` and local draft
  recovery call `save()` from every page, so an invalid Setup value can leave the client via undo
  and 422, blocking Back and Next together.
  Test: none.
  Invariant: the next person to widen a Setup rule or touch `save()` finds this written down rather
  than rediscovering it. *(The oracle placed this in Step C5; it is here instead so Group A stays
  self-contained and change 1 can ship without the status work.)*

#### Group B - `N/A` as a bulleted list

Suite: `tests.test_docx`, plus `tests.test_docx_import` once at the end.

- [ ] **Step B1 - stop taking the empty early return.**
  File: [app/docx_report.py](app/docx_report.py#L711) - replace the three lines with
  `values = values or ["N/A"]`.
  Test: new, in [tests/test_docx.py](tests/test_docx.py) - render a production-only finding, then
  assert the Non-Production Location cell's second paragraph is styled `List Paragraph`, carries a
  `w:numPr` under its `w:pPr`, reads `N/A`, and that the cell text contains no `\u2022`. No existing
  test asserts the empty cell at all, so without this the change lands green with nothing proving it.
  Invariant: the token paragraph is still removed, so `_unresolved_placeholders` stays satisfied and
  generation does not abort; `_visible_value` still maps `N/A` to `""` on import, so the round trip
  is unchanged.

- [ ] **Step B2 - correct the template document.**
  File: [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L232) - say the `N/A` placeholder is bulleted
  too. Test: none.

#### Group C - the fourth finding status

Suite: `tests.test_app` for C1, `tests.test_docx_import` for C2 and C3, `tests.test_browser` for C4.
**Q1 must be answered before Step C1. Q2 only changes the size of C3.**

- [ ] **Step C1 - extend the enum, server side only.**
  File: [app/models.py](app/models.py#L10) - `Status` gains the agreed key.
  Test: new, in [tests/test_app.py](tests/test_app.py) - PUT a finding carrying the new status,
  expect 200, and assert `content_types_for_status(<new>)` returns the five-section set.
  Invariant: no `load_path` repair and no migration. Widening a `Literal` is permissive, so every
  draft on disk still loads unchanged and the single `draft.bak.json` level stays unspent.

- [ ] **Step C2 - teach the document the label.**
  File: [app/docx_report.py](app/docx_report.py#L48) - `STATUS_LABELS` gains the key.
  Test: extend `tests/test_docx_import.py::test_editable_mode_keeps_all_statuses_and_printed_sections`
  with a fourth finding carrying the new status, asserting both its status and its five printed
  section types survive a render-then-import round trip. That one test covers the render, the label,
  the summary/detail cross-check and `STATUS_BY_LABEL` together.
  Invariant: the two bare indexes at [L516](app/docx_report.py#L516) and
  [L769](app/docx_report.py#L769) read the one dict, so the summary table and the detail token
  cannot disagree - which is what the importer's `'"X" summary and detail values do not match.'`
  check depends on. Closes the `KeyError` 500.

- [ ] **Step C3 - teach the importer the label, and keep the finding.**
  Files: [app/docx_import.py](app/docx_import.py#L53) `STATUS_BY_LABEL` (`LABEL_BY_STATUS` derives
  free), [L59](app/docx_import.py#L59) `RETAINED_STATUSES`, [L1160](app/docx_import.py#L1160) the
  `status_counts` tuple. **If Q2 answers (b) disclose:** also [L944](app/docx_import.py#L944) and
  the notice wording at [app/web/static/manager.js](app/web/static/manager.js#L200).
  Test: one new assertion alongside
  `tests/test_docx_import.py::test_a_generated_report_imports_as_a_retest_draft` - a new-status
  finding is retained by a retest import and does not appear in `dropped`.
  Invariant: **no open finding is ever dropped by a retest import and reported as
  `dropped_resolved`.** This is the only failure in the whole change that produces no error.

- [ ] **Step C4 - open the dropdown. Last.**
  Files: [app/web/static/app.js](app/web/static/app.js#L119) `statuses`,
  [app/web/static/manager.js](app/web/static/manager.js#L208) `labels`.
  Test: one new browser test - the option exists with the agreed label, selecting it renders the
  five sections, and the finding-card chip prints the label rather than the raw key.
  Invariant: the client never offers a status the server would 422, and nothing can reach a document
  that cannot be labelled. **This step is the gate that lets the value into a saved draft - and into
  `localStorage` and `sessionStorage` - so every consumer must already handle it.** Doing C4 before
  C1 lets a user save a value the model rejects; before C2 it lets them reach a `KeyError` at
  generation; before C3 it lets a retest import eat their finding.

- [ ] **Step C5 - correct the stale documentation and record the twin.**
  Files: [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L218) and
  [L248](docs/DOCX_TEMPLATE.md#L248) (both enumerate the statuses that use `retest_finding.docx` and
  print `{{severity-review-tickets}}`); [docs/DATA_MAP.md](docs/DATA_MAP.md) §7 for the fourth status
  value, §12 for the status-label table as a **four-copy twin with no drift guard**, and **new in
  round 2** the **Segment x Status matrix** at [L411](docs/DATA_MAP.md#L411), which needs a fourth
  column behaving like `open_previously_discovered` because `additionalInformationFields` gates on
  `status !== "open_new"` ([app/web/static/app.js](app/web/static/app.js#L3372)). While there, add
  the two absences the oracle found in round 1: the `location_values` `get` versus `||` divergence,
  and `workspace.load_path` as a fourth Python site branching on `status == "resolved"`.
  Test: none.
  Invariant: the map's only exhaustive status enumeration does not silently omit the new value.

### What I would not do

1. **No `load_path` repair or migration for the new status.** Widening a `Literal` is permissive and
   every draft on disk already validates. A repair would rewrite files to change nothing and consume
   the single `draft.bak.json` level - the `non_production_label` precedent. It turns the
   backup-exhaustion row red in exchange for nothing.
2. **No `.get()` fallback on `STATUS_LABELS`.** Tempting, because the bare index is a 500. But an
   invented label would be written into a document and read back as garbage, and `STATUS_BY_LABEL`
   would refuse it on import. The `KeyError` is the correct failure - loud, at generation, before
   anything is written. Extend the dict.
3. **No new drift-guard test for the four status-label tables.** It is the honest gap the oracle
   confirms, but building one means asserting a JavaScript array against two Python dicts and a
   second JavaScript object - a contract-test harness for a table that changes about once a year.
   Ordering C4 last buys the practical half of it. Record the gap in `DATA_MAP.md` and move on.
4. **No status-aware In Conclusion sentence.** It is a three-part change across
   `status_conclusion_runs`, `STATUS_CONCLUSION_PATTERN` and both JavaScript twins, and the
   recogniser must keep the old `(?:Open|Resolved)` alternation forever or every default sentence
   already on disk stops matching and freezes at its stored wording. Out of proportion to "add an
   option to a dropdown".
5. **No dynamic status label following `non_production_label`.** `STATUS_BY_LABEL` is a static
   reverse map; a per-report label makes a generated document un-importable unless the importer
   learns every preset and every typed custom value.
6. **No server-side username stripping.** See *Assumption 1*. It would put the server in a fight
   with the client over a field the user is actively typing in.
7. **No widening of the `save()` Setup gate, and no change to `restoreHistory`.** The undo/redo 422
   is real and now written down, but fixing it means either running Setup validation against
   `report` rather than the DOM on every page, or making `restoreHistory` not reload when the save
   failed. Both are changes to undo/redo, reachable today without this change, and not what was
   asked for. It belongs in its own plan.
8. **No fix for the two adjacent divergences the oracle found** - the `location_values` `get` versus
   `||` empty-string leak, and the Unicode-letter asymmetry in the username message. Both are real,
   neither is in this request. They go in `DATA_MAP.md` as known, not into this commit.
9. **No change to the Limitations `N/A`.** `_center_plain`
   ([app/docx_report.py](app/docx_report.py#L445)) deliberately strips the bullet and centres it.
   After Step B1 the two tables disagree on purpose - affected locations is a list of many things,
   Limitations is one statement. The scribe asked that this be a decision rather than an accident:
   this is the decision, and the user can object to it here.

## Answers

**Q1 — what is the new status called?** Stored key `open_resolved_on_non_prod`; label
`Open (Resolved on Non-Prod)` in both the Findings dropdown and the document. Fixed text, not
following the configurable non-production environment name, because a label that varies would break
reading a finished document back into a draft.

**Q2 — retest import: silent rename or disclosed?** *Neither.* The user rejected the premise and
asked for different behaviour:

> Can we inherit the Open (Resolved on Non-Prod) from the imported report? also, if there are any
> more value other than the 4 official status, then just make the status in the findings tab empty
> which they need to fill first before going to the contents page.

This replaces Q2 with two new requirements:

- **R1 — inherit, do not rewrite.** A retest import carrying `Open (Resolved on Non-Prod)` keeps
  that status rather than being rewritten to `Open (Previously Discovered)`. The question of whether
  to disclose a rename is moot; there is no rename.
- **R2 — unknown status becomes empty and blocks.** Any status value in an imported document that is
  not one of the four official statuses is imported as an **empty** status. The finding then reads as
  incomplete on the Findings page and the tester must set it before reaching Content.

**Q3 — trailing-space username: accept or strip?** Not asked. Recorded as a stated assumption in the
round 2 plan: accept it, write no code. The oracle confirmed the same 422 is reachable today with
`"john."`, and stripping would start a `reconcileCanonicalObject` fight.

**Q4 — does the new status print the same sections as Previously Discovered?** Settled without asking.
Every content-section rule is written as `== "open_new"` or `== "resolved"`, so the new value falls
through to the Previously Discovered behaviour with no edit.

### R2 changes the schema, so it reopens the exchange

`app/models.py:10` defines `Status = Literal["open_new", "open_previously_discovered", "resolved"]`
and `app/models.py:207` declares `status: Status = "open_new"` — required, with no empty state. An
empty status is therefore **not currently representable on the model**, so R2 is a schema change to
the field that decides which sections a finding prints, not an importer tweak.

R1 moves work into the importer that was not there at round 1. Per the coordinating prompt, that
calls for a further `scribe` pass, and the schema question calls for a further `loremaster` pass,
before the plan is revised.

### R2 withdrawn and replaced — the user's final answer

After reading the round 3 plan, the user withdrew R2 and replaced it:

> do not refuse it outright. rather, we go with the initial plan. If the status is not on the 4
> official status, Open (New), Open (Previously Discovered), Open (Resolved on Non-Prod), and
> Resolved. then it will be automatically assigned as Open (Previously Discovered).

**R2 is therefore dead.** There is no empty status and no navigation gate. The replacement, R2′:

- **R2′ — unknown falls back, it does not empty and does not refuse.** A status label in an imported
  document that is not one of the four official labels is imported as `open_previously_discovered`.
  Nothing is refused for carrying an unrecognised status, including the case where only one of the
  two Status cells was hand-edited — which was Stated Assumption 5, now overruled.

This is a **simplification**, and it deletes most of Group D. Gone: the nullable model field, the
blank dropdown option, the `KeyError` 500s from indexing on `None`, and the conclusion-sentence
guard — none are reachable when the status is always one of four known values. `Status | None` is
**not** wanted; the schema change is withdrawn with the requirement that caused it.

One reading is adopted without asking, because it follows from the rule rather than extending it:
**normalise each Status cell before comparing them.** An unrecognised label in either cell becomes
`open_previously_discovered`, so the two cells then agree and nothing is refused. Two cells holding
*different but official* statuses still disagree and are still refused — that is a genuine
inconsistency in the document, not an unrecognised value, and the user's instruction does not reach
it.

## Round 3 - Oracle: can a finding have no status?

**Answer.** No finding can hold an empty status today - the model default, the three creation sites
and the importer's own guard all make one, and the Findings `<select>` offers no blank option. The
codebase already has a precedent for "not chosen yet" on this row: `likelihood`, `impact` and
`severity` are all `Severity | None = None`, so the representable form of R2 is `Status | None = None`
and nothing else. The navigation gate already blocks an empty status and needs no new code, and **no
server-side gate rejects an incomplete finding on save** - `finding_input_issues` never looks at
status - so an imported draft with empty statuses lands and saves. R2 is cheap on the save path. The
one thing that is not free is the `<select>` itself: with no blank option it silently displays
`Open (New)` for an empty value, which both hides the error outline and makes the block unclearable.

### 1. Empty status is not reachable today, and `!finding.status` is symmetry not history

**The select offers no blank option.** One helper renders all four assessment dropdowns
([app/web/static/app.js](app/web/static/app.js#L279)):

```javascript
const select = (values, current, nullable = false) => `<select>${nullable || (!current && values === severity) ? `<option value="" disabled ${!current ? "selected" : ""}>-</option>` : ""}${values.map(...).join("")}</select>`;
```

The placeholder appears when `nullable` is true, or when the value list **is the `severity` array by
identity**. The row markup ([app/web/static/app.js](app/web/static/app.js#L2561)) calls it four times:

```javascript
<td>${select(severity, finding.likelihood, true)}</td><td>${select(severity, finding.impact, true)}</td><td>${select(severity, finding.severity)}</td>
... <td>${select(statuses.map(x=>x[0]), finding.status)}</td>
```

Likelihood and impact pass `nullable = true`. Severity passes the `severity` array itself, so it
matches the identity arm. Status passes `statuses.map(x=>x[0])` - a **new array**, never `=== severity` -
with `nullable` defaulting to false. **The status dropdown can never render a blank option.**

**Nothing can produce an empty value either.** `addFinding` sets `status:"open_new"`
([app/web/static/app.js](app/web/static/app.js#L2650)); the list-paste finding does the same
([L3694](app/web/static/app.js#L3694)); the model default is `"open_new"`
([app/models.py](app/models.py#L207)); and the importer refuses an unrecognised label outright rather
than passing `None` through - `STATUS_BY_LABEL.get(cells[5])`
([app/docx_import.py](app/docx_import.py#L655)) yields `None`, and
[L778-L780](app/docx_import.py#L778) raises `'"X" has an unknown finding status.'` before any finding
is built. So `!finding.status` at [app/web/static/app.js](app/web/static/app.js#L2284) is **dead
today**. It is there because it sits in a list with three fields that genuinely are nullable, not
because anyone reached it.

**If the client did hold one, the save fails.** `Report.model_validate`
([app/main.py](app/main.py#L779-L782)) raises on `""` or `null` against the `Literal`, and the route
returns `422 invalid_report` carrying the pydantic error list. On the client that is not a 409 and
not a 5xx, so `save()` takes the last arm
([app/web/static/app.js](app/web/static/app.js#L808-L821)): `pendingSave = true`,
`persistLocalDraft()`, a "Save failed" diagnostic banner, **and no retry**. The tester keeps editing a
report that is only in `localStorage`. That is the failure mode R2 must avoid, and it is avoided only
by making the value representable on the model.

### 2. The smallest representable form: follow `likelihood` / `impact` / `severity`

The codebase already answers this. All three comparators are nullable on the model
([app/models.py](app/models.py#L204-L207)):

```python
    likelihood: Severity | None = None
    impact: Severity | None = None
    severity: Severity | None = None
    status: Status = "open_new"
```

`Severity` itself ([L9](app/models.py#L9)) contains no empty member - "unset" is `None`, **outside**
the `Literal`, never a member of it. Every consumer then tests truthiness, not equality:
`finding_is_complete` ([app/report_service.py](app/report_service.py#L806)) chains
`likelihood and impact and severity and status`, and the client mirrors it at
[app/web/static/app.js](app/web/static/app.js#L2754).

So the precedent is unambiguous: **`status: Status | None = None`**. Adding `""` to the `Literal`
would be the only form that diverges from the three fields beside it, and it would put an empty
string into `STATUS_BY_LABEL`'s value space and into every `status == "..."` comparison as a real
member rather than an absence. There is no third convention in this codebase for an unset enum.

Two consequences that come free from following the precedent:

- JSON round-trips as `null` (`model_dump(mode="json")`), and `!finding.status` is already falsy for
  `null`, so no client predicate changes.
- `labelAssessmentPlaceholders` ([app/web/static/app.js](app/web/static/app.js#L2242-L2246)) already
  walks `["Likelihood", "Impact", "Severity", "Status"]` and renames any `option[value=""]` it finds
  to the column label. Give the status select a placeholder and it is labelled "Status" with no edit.

### 3. What breaks when status is empty

**Crashes - the two bare dict indexes, both already gated.**

| Site | Result on empty |
|---|---|
| [app/docx_report.py](app/docx_report.py#L516) `STATUS_LABELS[finding.status]` (summary table) | `KeyError`, **but unreachable from the route** |
| [app/docx_report.py](app/docx_report.py#L769) `"status": STATUS_LABELS[finding.status]` (detail token) | `KeyError`, same gate |

This is the opposite of round 1's new-status case. There, the value was truthy so `finding_is_complete`
passed and the `KeyError` was live. Here `generation_issues` calls `finding_is_complete` first
([app/docx_report.py](app/docx_report.py#L110-L112)), an empty status makes it false, and
`finalized_report` raises `422 "Complete the report before generating it"`
([app/main.py](app/main.py#L518-L520)) before any rendering. **An empty status cannot reach either
index through the app.** It can through `scripts/generate_report.py --allow-incomplete`
([scripts/generate_report.py](scripts/generate_report.py#L18-L31)), which skips the issue raise at
[app/docx_report.py](app/docx_report.py#L180-L181) - a developer script, not a tester path.

**Wrong results - everything written as `== "open_new"` treats "unset" as "previously discovered".**

| Site | Result on empty |
|---|---|
| [app/report_service.py](app/report_service.py#L251-L256) `content_types_for_status` | **Wrong**: returns the five-section retest list, including `in_conclusion` |
| [app/web/static/app.js](app/web/static/app.js#L1075) `contentTypesForStatus` (twin) | **Wrong**, identically |
| [app/report_service.py](app/report_service.py#L283) `provision` | **Wrong**: provisions `previous_proof_of_concept` and `in_conclusion` for a finding with no status |
| [app/docx_report.py](app/docx_report.py#L759) `template_name` | **Wrong**: picks `retest_finding.docx` |
| [app/docx_report.py](app/docx_report.py#L790) `if finding.status != "open_new"` | **Wrong**: binds the prev-PoC and conclusion anchors |
| [app/web/static/app.js](app/web/static/app.js#L3372) `additionalInformationFields` | **Wrong**: shows Severity Review Tickets for a finding with no status |
| [app/web/static/app.js](app/web/static/app.js#L3769) finding-card chip | **Cosmetic**: `statuses.find(...)?.[1] || finding.status` yields `""`, an empty chip |
| [app/docx_import.py](app/docx_import.py#L1158-L1161) `status_counts` | **Cosmetic**: comprehension over the three keys, so empty-status findings are simply uncounted in the import summary |
| [app/web/static/manager.js](app/web/static/manager.js#L208) `labels` | Not reached - the `.filter(([, count]) => count)` above it drops any key `status_counts` never produced |

The three document-side wrong results (`template_name`, the `!= "open_new"` anchors, and
`content_types_for_status` inside `generation_issues`) are all downstream of the same 422, so none of
them reaches a document.

`provision` is the one that **persists**. It runs on every save
([app/main.py](app/main.py#L801)) and writes into the stored draft. For an empty status it creates
five sections rather than three. That mostly self-heals - picking `Open (New)` later re-runs
`provision`, and `in_conclusion` is the one section deliberately **not** carried
([app/report_service.py](app/report_service.py#L288)) so it is dropped rather than left stale - but
for one save cycle the draft on disk holds retest-shaped sections for a finding that has no status.

**The status-conclusion sentence.** [app/report_service.py](app/report_service.py#L326):

```python
        status = "Resolved" if vulnerability.status == "resolved" else "Open"
```

An empty status yields `"Open"`. For a **fresh** finding this is harmless: `if not paragraphs`
([L336](app/report_service.py#L336)) inserts an empty paragraph and never writes the sentence. For an
**imported** finding whose document already carried "The finding "X" is still Open.",
`default_conclusion_span` matches it, and [L345](app/report_service.py#L345) **re-derives** the
sentence with the word "Open" for a finding that has no status. Wrong, and written to disk. The JS
twins at [app.js L1055](app/web/static/app.js#L1055), [L1128](app/web/static/app.js#L1128),
[L1152](app/web/static/app.js#L1152), [L3866](app/web/static/app.js#L3866) and
[L3883](app/web/static/app.js#L3883) all use the same `=== "resolved" ? ... : "Open"` shape and behave
the same way.

**Sensible fall-through - no action needed.** The resolved-remediation boilerplate
([app/report_service.py](app/report_service.py#L313), JS twin
[L1103](app/web/static/app.js#L1103)) tests `== "resolved"`, so an empty status correctly gets no
boilerplate and an empty tester-owned paragraph. `workspace.load_path`'s stale-evidence repair
([app/workspace.py](app/workspace.py#L292)) tests `== "resolved"` and correctly does nothing. The
Content-page readiness check ([app/web/static/app.js](app/web/static/app.js#L3460)) tests
`.every(Boolean)` over the four fields and correctly reports "assessment details" missing.

### 4. The navigation gate already exists - but the select hides it

**Yes, and it needs no new rule.** `validateFindingsPage`
([app/web/static/app.js](app/web/static/app.js#L2750-L2755)):

```javascript
    const validateFindingsPage = reveal => {
      const incomplete = report.vulnerabilities.map((finding, index) => ({
        index,
        title: !finding.title?.trim(),
        assessment: [finding.likelihood, finding.impact, finding.severity, finding.status].map(value => !value),
        location: !scopeHasLocation(finding)
      })).filter(finding => finding.title || finding.assessment.some(Boolean) || finding.location);
```

and the Next button ([L2781-L2789](app/web/static/app.js#L2781)):

```javascript
    document.querySelector("#next").onclick = async event => {
      event.preventDefault();
      if (!validateCurrentPage(true)) return;
```

Status is already the fourth element of `assessment`, so an empty value already blocks Next.
Direct-URL navigation is closed too: `GET /reports/{id}/edit` redirects to
`/reports/{id}/findings?incomplete=findings` unless every finding passes `finding_is_complete`
([app/main.py](app/main.py#L737-L738)), which requires a truthy status
([app/report_service.py](app/report_service.py#L806)). **R2 needs no new gate.**

**What it does need is the blank option**, and this is the part that is easy to miss. With no
`option[value=""]`, a `<select>` whose options carry no `selected` attribute falls back to index 0 -
so an empty-status row **displays "Open (New)"** and `control.value === "open_new"`. Two things follow:

- `showFindingValidationErrors` toggles the error class on `!control.value`
  ([app/web/static/app.js](app/web/static/app.js#L2255)). That is false, so **the status select gets
  no red outline** while `setSaveState` tells the tester to "complete the highlighted fields". Nothing
  is highlighted.
- The row's `onchange` reads `event.target.value`
  ([app/web/static/app.js](app/web/static/app.js#L2590-L2600)). Picking the option the box **already
  shows** fires no `change` event, so `finding.status` stays empty and Next stays blocked with no
  visible cause. The tester has no way out except choosing a status they did not want, then choosing
  back.

Passing `nullable = true` at [L2561](app/web/static/app.js#L2561) closes both, and matches how
likelihood and impact already behave - including the `disabled` on the placeholder, which stops a
tester returning a finding to "no status" once they have set one.

### 5. Server-side twin of the gate: there is none, so the import lands

**Nothing on the save path rejects an incomplete finding.** `PUT /reports/{id}`
([app/main.py](app/main.py#L744-L812)) runs, in order: the 409 revision check, `reconcile_targets`,
`normalise_scope_modes`, `Report.model_validate`, `setup_input_issues`, `finding_input_issues`,
`provision_report`, `save_if_current`. The only finding-level validator is
`finding_input_issues`, and it checks **exactly one field**
([app/report_service.py](app/report_service.py#L199-L215)):

```python
    for finding in report.vulnerabilities:
        if finding.severity_review_tickets:
```

It never reads `status`, `severity`, `likelihood`, `impact`, `title` or `scope`. That is by design -
the surrounding docstring says blank draft fields are not errors - and it is why a half-filled
Findings page saves today with three null assessment fields.

So the **only** server-side rejection of an empty status is the `Literal` on the field itself
([app/models.py](app/models.py#L207)). Widen it to `Status | None = None` and the save path stops
objecting entirely: `finding_is_complete` is consulted only by the `GET /edit` redirect
([app/main.py](app/main.py#L737)) and by `generation_issues`
([app/docx_report.py](app/docx_report.py#L110)), both of which **redirect or 422 the generate**,
neither of which touches storage. **A tester can import a draft full of empty statuses, save it,
close the app, and come back to it.** R2 is cheap.

The one residual is §3's `provision`: it runs on that same save and will shape empty-status findings
as retest findings. It does not block anything and it corrects itself on the next save after a status
is chosen, but it is the reason an empty status is not completely inert on the server.

**Invariants in play**

- **"Unset" on an assessment field is `None`, outside the `Literal`.** Break it by adding `""` as a
  member and every `status == "open_new"` comparison acquires a fourth real value to consider, and
  `STATUS_BY_LABEL` gains an empty-string key with no label to map to.
- **The client never offers a status the server would 422.** Widening the model must land before the
  blank option, exactly as round 2's Step C4 ordering argues for the new status.
- **`content_types_for_status` is the single owner of which sections a status prints.** An empty
  status has no answer to that question; it currently gets the retest answer by falling off the end of
  an `if`.
- **No gate on the save path may reject a draft.** `finding_input_issues` deliberately tolerates
  blank fields so a work-in-progress always saves. An empty status must stay inside that tolerance or
  the import cannot land.

**Both-sides warning**

Four pairs are involved and each must change together:

| Rule | Python | JavaScript |
|---|---|---|
| sections a status prints | `content_types_for_status` ([app/report_service.py](app/report_service.py#L251)) | `contentTypesForStatus` ([app/web/static/app.js](app/web/static/app.js#L1075)) |
| finding readiness | `finding_is_complete` ([app/report_service.py](app/report_service.py#L806)) | `validateFindingsPage` ([app/web/static/app.js](app/web/static/app.js#L2754)) and the readiness panel ([L3460](app/web/static/app.js#L3460)) |
| the conclusion sentence's status word | `provision` ([app/report_service.py](app/report_service.py#L326)) | `syncConclusion` ([app/web/static/app.js](app/web/static/app.js#L1055)) and four more |
| status label table | `STATUS_LABELS` ([app/docx_report.py](app/docx_report.py#L48)), `STATUS_BY_LABEL` ([app/docx_import.py](app/docx_import.py#L53)) | `statuses` ([app/web/static/app.js](app/web/static/app.js#L119)), `labels` ([app/web/static/manager.js](app/web/static/manager.js#L208)) |

None of the four needs an edit for R2 as such - all of them already fall through on a falsy value -
but the first three each produce a **wrong** fall-through per §3, so whichever of them the planner
decides to make status-aware must be changed on both sides in the same commit.

**Map drift**

None. [docs/DATA_MAP.md](docs/DATA_MAP.md#L120) lists the finding fields without asserting
nullability per field, and §12's twin table
([docs/DATA_MAP.md](docs/DATA_MAP.md#L363)) already names `content_types_for_status` /
`contentTypesForStatus` correctly. Nothing in the map contradicts the source as it stands today. If
R2 ships, §7 needs `status` moved into the nullable group beside `likelihood`, `impact` and
`severity` - that is already inside the round 2 plan's Step C5.

## Round 3 - Scribe: inheriting and rejecting statuses on import

**Answer.** R1 is two edits, not one: `RETAINED_STATUSES` only decides drop-versus-keep, and a
second, unconditional line rewrites every retained finding's status regardless. R2 is cheaper than it
looks on the parse side - the label map already yields `None` for an unrecognised cell and one raise
is all that stands in the way - but three lines downstream index a dict with that value and two of
them raise `KeyError`, which the import route does not catch, so an unhandled `None` is a **500, not
a 422**. One further site is not obvious and is the difference between R2 working and R2 rejecting
the user's motivating document: an editable import is validated *and provisioned* before it is
written, and the provisioning equality check fails when the document's section count disagrees with
what an empty status provisions.

### 1. How a document's status cell becomes a stored key

**One exact-text dictionary lookup, no fuzz, no regex.** The summary table is the only place a status
is read; the detail table's Status cell is only ever compared, never parsed.

`_summary_rows` ([app/docx_import.py](app/docx_import.py#L643-L657)) reads row by row, and the status
is the sixth cell:

```python
        cells = [cell.text.strip() for cell in row.cells]
        if len(cells) < 6 or not cells[0]:
            continue
        rows.append({
            "title": cells[0], "likelihood": cells[1].lower() or None, "impact": cells[2].lower() or None,
            "severity": cells[3].lower() or "informational", "display_id": cells[4],
            "status": STATUS_BY_LABEL.get(cells[5]),
        })
```

The map ([app/docx_import.py](app/docx_import.py#L53-L58)) is a literal label-to-key dict plus its
inverse. `.get`, so an unrecognised label is already `None` at this point - **the parse step does not
need to change for R2 at all.**

**What it does with an unrecognised label right now: rejects the whole document, before any finding
is built** ([app/docx_import.py](app/docx_import.py#L777-L780)):

```python
    summary_rows = _summary_rows(document)
    unknown = [row["title"] for row in summary_rows if row["status"] is None]
    if unknown:
        raise ReportImportError(f'"{unknown[0]}" has an unknown finding status.')
```

`ReportImportError` is a `ValueError`, so the route turns it into
`422 Select a valid VulnReport export: "X" has an unknown finding status.`
([app/main.py](app/main.py#L659-L660)) and nothing is written. One finding with a bad cell loses the
whole import - which is exactly the behaviour the user is asking to replace.

So **R2's parse cost is a three-line deletion.** Everything else R2 costs is downstream of that
deletion, in §3.

The one thing the row must also keep is the **raw cell text**. Three sites below need it, so add it
beside the mapped value in the same dict:

```python
            "status": STATUS_BY_LABEL.get(cells[5]), "status_label": cells[5],
```

### 2. R1 - inheriting the new status is two edits, and the set is not the important one

**Adding the key to `RETAINED_STATUSES` is necessary but not sufficient.** That set is consulted at
exactly one place, and it only decides whether the finding is skipped
([app/docx_import.py](app/docx_import.py#L922-L924)):

```python
        if mode == "retest" and row["status"] not in RETAINED_STATUSES:
            dropped.append(title)
            continue
```

The rewrite is **31 lines further down and unconditional**
([app/docx_import.py](app/docx_import.py#L940-L953)):

```python
        else:
            # Every retained finding becomes previously discovered: it is the only status that keeps
            # a previous proof of concept, and the recovered steps are exactly that.
            if row["status"] == "open_new":
                rewritten.append(title)
            source_by_type = {content["type"]: content for content in source_contents}
            contents = [ ... ]
            status = "open_previously_discovered"
```

`status` is assigned from a literal, not from `row`. Add the key to the set on its own and the new
status stops being dropped and starts being **renamed** instead - the exact behaviour R1 rejects, and
silently, because `rewritten` is only appended for `open_new`.

**The two edits.**

- **[app/docx_import.py](app/docx_import.py#L922)** - invert the membership test rather than
  extending the set:

  ```python
        if mode == "retest" and row["status"] == "resolved":
  ```

  Extending the set instead would work for R1, but R2 then forces `None` into it as a member, which
  reads as nonsense, and every future status has to be remembered here. The inverted form is
  self-maintaining, and it matches the name of the thing it feeds, `dropped_resolved`.
  `RETAINED_STATUSES` ([app/docx_import.py](app/docx_import.py#L59)) then has **no remaining
  reference** in `app/` or `tests/` - delete it.
- **[app/docx_import.py](app/docx_import.py#L953)** - inherit instead of assign:

  ```python
            status = "open_previously_discovered" if row["status"] == "open_new" else row["status"]
  ```

  `open_previously_discovered` maps to itself, so this is a no-op for today's only retained non-new
  status; the new status and (per R2) `None` pass through.

**The comment above it becomes false and should change in the same edit.** "it is the only status
that keeps a previous proof of concept" stops being true the moment a second open status exists. The
reshaping itself is still right for the new status: an `Open (Resolved on Non-Prod)` finding being
retested wants last round's steps as its previous proof of concept and an empty new one, which is
what the fixed five-content list at [L946-L952](app/docx_import.py#L946-L952) already builds.

**Both counters then report correctly with no further change.** `rewritten` is appended only inside
`if row["status"] == "open_new"` ([L943](app/docx_import.py#L943)), which after the edit is exactly
the set of findings whose status changed - so
`statuses_rewritten` ([L1154](app/docx_import.py#L1154)) and the manager's sentence "N Open New
findings were changed to Previously Discovered" ([app/web/static/manager.js](app/web/static/manager.js#L197-L200))
stay true. `dropped` is appended only in the inverted test, so `dropped_resolved`
([L1153](app/docx_import.py#L1153)) becomes literally accurate rather than accidentally accurate.
Note that without the inversion it would **not** be: an unknown-status finding would be listed to the
tester as a *Resolved* finding that was not included.

### 3. R2 - what an empty status costs the importer

**No, the importer does not currently guarantee a status - it guarantees one only because of the
raise in §1.** Remove it and `row["status"]` is `None` through the whole per-finding loop. Four sites
see it, in this order.

**a. The section-structure gate, and a `KeyError` in its own error message**
([app/docx_import.py](app/docx_import.py#L880-L887)):

```python
        expected_sections = ["description", "recommended_remediation", "proof_of_concept"]
        if row["status"] != "open_new":
            expected_sections = [ ...five... ]
        if section_order != expected_sections:
            raise ReportImportError(f'"{title}" does not have the expected section structure for {LABEL_BY_STATUS[row["status"]]}.')
```

`None != "open_new"` is true, so an unknown status **demands the five-section retest structure**. A
hand-edited `Open (New)` finding carries three, fails the test, and the failure message evaluates
`LABEL_BY_STATUS[None]` → `KeyError`. `KeyError` is not in the route's except tuple
([app/main.py](app/main.py#L659)), so this surfaces as an **unhandled 500**, not a 422.

Smallest fix that makes the gate mean something for an unknown status - accept either shape, and use
the raw label in the message:

```python
        allowed = [content_types_for_status("open_new"), content_types_for_status("")]
        if row["status"] is not None:
            allowed = [content_types_for_status(row["status"])]
        if section_order not in allowed:
            raise ReportImportError(f'"{title}" does not have the expected section structure for {row["status_label"]}.')
        expected_sections = section_order
```

`content_types_for_status` ([app/report_service.py](app/report_service.py#L251)) returns exactly the
two lists this block writes out by hand, and `docx_import` already imports from `report_service`
([L25](app/docx_import.py#L25)), so this also removes a duplicated literal rather than adding one.

**b. The summary-versus-detail consistency check, same bare index**
([app/docx_import.py](app/docx_import.py#L895-L901)):

```python
        repeated = {
            "Severity": row["severity"].title(),
            "ID": row["display_id"],
            "Status": LABEL_BY_STATUS[row["status"]],
        }
```

`KeyError` again, for **every** unknown-status finding, whatever its structure. Fix by comparing the
raw text, which is what is actually in both cells:

```python
            "Status": row["status_label"],
```

This is a **strict no-op for known statuses**: `STATUS_BY_LABEL.get(cells[5])` only returned a key
because `cells[5]` was a key of `STATUS_BY_LABEL`, and `LABEL_BY_STATUS` inverts it exactly, so the
compared string is byte-identical today.

Read what that check then does to the user's case, because it is the sharp edge of R2. The two Status
cells - summary table and detail table - must agree. A document from an older release agrees with
itself, so it imports as empty. A **hand-edited** document where somebody typed over one of the two
cells does not, and is rejected with `'"X" summary and detail values do not match.'` The existing
test at [tests/test_docx_import.py](tests/test_docx_import.py#L1081-L1093) is exactly this shape - it
writes `"Pending"` into the summary cell only - so after R2 it still returns 422, for a different
reason. **Planner decision:** keep the check (a document whose two views disagree is genuinely
ambiguous, and refusing it is defensible), or drop the Status key when the summary label is unknown -
`if row["status"] is not None` around that one entry - making the summary cell authoritative under
R2. I would keep it and be explicit in the release note; it is one line either way.

**c. The retest drop.** `None not in RETAINED_STATUSES` is true, so an unknown-status finding would be
**dropped and reported as Resolved** on a retest import. The §2 inversion to `== "resolved"` fixes
this at the same time - which is why the two requirements share an edit.

**d. `status_counts`** ([app/docx_import.py](app/docx_import.py#L1157-L1161), editable mode only) is a
comprehension over a literal three-tuple. Empty-status findings are simply uncounted, so the summary
reads "12 findings · 5 Open New, 4 Previously Discovered" and the arithmetic quietly does not add up.
Make the tuple self-maintaining rather than extending it by hand:

```python
                for status in STATUS_BY_LABEL.values()
```

That picks up the new status from the label map for free and still omits `None`, which has no label.
To make the omission visible, **replace the deleted raise with a warning rather than nothing** -
`warnings` is already a parameter of `_findings` ([L775](app/docx_import.py#L775)) and surfaces in
both modes ([L1173-L1174](app/docx_import.py#L1173-L1174), rendered as notices at
[app/web/static/manager.js](app/web/static/manager.js#L206)):

```python
    for row in summary_rows:
        if row["status"] is None:
            warnings.append(f'"{row["title"]}": the status "{row["status_label"]}" was not recognised; set a status on the Findings page.')
```

Naming the findings is the whole point of R2 - the user's complaint is silence, and an import that
silently blanks three statuses has only moved the silence.

**Does anything between parsing and saving reject or re-default a `None` status? Yes - two gates, and
the second is the one that bites.**

- **The model, on both paths.** Retest goes straight to `workspace.import_report`
  ([app/main.py](app/main.py#L651)), whose first statement is `Report.model_validate(payload)`
  ([app/workspace.py](app/workspace.py#L163)). Editable goes through `finalize_editable_import` first,
  whose first statement is also `Report.model_validate(payload)`
  ([app/main.py](app/main.py#L590)). So **`Status | None` must land in the model before any importer
  edit is testable**; until it does, every unknown-status document 422s with a pydantic error instead
  of the old message. Nothing defaults the value back - `reconcile_targets` and
  `normalise_scope_modes` never read status, and `provision` writes contents, never the status field.
- **The editable path's provisioning equality check, which rejects the import outright.**
  `finalize_editable_import` runs `provision_report` and then compares
  ([app/main.py](app/main.py#L605-L608)):

  ```python
      before_provision = _provisioned_projection(report)
      provision_report(report)
      if _editable_user_projection(report) != imported_user:
          raise ValueError("Server provisioning would alter imported user content")
  ```

  `provision` rebuilds the contents list as `[existing.get(t) or Content(type=t) for t in types] + carried`
  ([app/report_service.py](app/report_service.py#L285-L291)), where `types` is
  `content_types_for_status(status)`. For `None` that is the **five**-section list. An unknown-status
  finding whose document carried **three** sections therefore arrives with three contents and leaves
  provisioning with five - the projections compare the contents list positionally, so they differ,
  and the import dies as `422 Select a valid VulnReport export: Server provisioning would alter
  imported user content`. Today this can never happen, because `expected_sections` is derived from the
  status and always equals `content_types_for_status(status)`.

  One line restores that invariant, immediately before the `mode == "editable"` branch at
  [L926](app/docx_import.py#L926):

  ```python
        by_type = {content["type"]: content for content in source_contents}
        source_contents = [by_type.get(t, {"type": t, "fragments": []}) for t in content_types_for_status(row["status"])]
  ```

  Canonical order matters, not just membership - `provision` emits `types` order, and appending the
  missing sections to the end would put `proof_of_concept` before `previous_proof_of_concept` and fail
  the same comparison. This is a **no-op for every known status**, because `expected_sections` already
  equals `content_types_for_status(row["status"])` for all four.

**Retest mode needs none of that.** It writes through `workspace.import_report` with no provisioning
and no projection check, and its branch already builds the fixed five-content list, which is exactly
what `content_types_for_status(None)` returns - so the first `PUT` after the import provisions to an
identical shape and nothing churns.

### 4. The round trip

**The new status, generated and re-imported: yes, both modes, once §2's two edits land.** The
generator writes the same label into both cells from one dict, the summary cell parses back through
`STATUS_BY_LABEL`, and the structures line up: a non-`open_new` status renders from
`retest_finding.docx` with five sections, and `expected_sections` for a non-`open_new` status is the
five-section list. Editable import assigns `status = row["status"]`
([L928](app/docx_import.py#L928)) and returns the same key. Retest import inherits it through the
edited [L953](app/docx_import.py#L953). Note the round trip is **not** identity in retest mode by
design: the proof of concept moves to previous proof of concept and a fresh empty one is built. That
is the intended retest behaviour and is unchanged by R1.

One caveat I cannot settle from this repository: the lookup is exact string equality on
`cell.text.strip()`, so the label survives only if Word leaves `Open (Resolved on Non-Prod)`
byte-identical - the hyphen in particular. Nothing in the app transforms it (python-docx writes the
literal, and the automation pass repaginates and refreshes fields rather than re-typing text), and
autoformat dash substitution applies to typed input, not programmatic text. But only a generate-then-
import on a Windows box with Word actually proves it, and that is the check worth running once.

**The user's real case - free text in the status cell - works, with one qualifier.** After R2, a
document whose Status cells read `Pending`, or carry a label from a release this app no longer knows,
imports the finding with **no status** instead of being rejected, and instead of being silently read
as something it is not. The qualifier is §3b: **both** Status cells must carry that same text. An
older-release document satisfies that automatically - both cells come from one dict - so the "document
written by an older version" case is clean. A document where a person typed over only the summary cell
hits the summary/detail mismatch check, which is the planner decision named in §3b.

And the finding then behaves as R2 asks: the client blocks Next on a falsy status with no new code
(per the oracle's §4), and it cannot reach the document, because `finding_is_complete` fails and
`GET /reports/{id}/edit` redirects before generation is ever offered.

### 5. Everything in the importer that enumerates a status

Confirmed exhaustively for `app/docx_import.py` - every occurrence of `status`, `open_new` and
`resolved` in the file. Beyond `RETAINED_STATUSES` and the label map there are **four** sites, and
none of them is a membership set:

| Site | Shape | Behaviour on the new status | Behaviour on `None` |
|---|---|---|---|
| [L881](app/docx_import.py#L881) `if row["status"] != "open_new"` | fall-through | correct - five sections | **wrong** - demands five, see §3a |
| [L887](app/docx_import.py#L887) `LABEL_BY_STATUS[row["status"]]` | **bare index** | fine once the map is extended | **`KeyError` → 500** |
| [L898](app/docx_import.py#L898) `LABEL_BY_STATUS[row["status"]]` | **bare index** | fine once the map is extended | **`KeyError` → 500** |
| [L953](app/docx_import.py#L953) `status = "open_previously_discovered"` | **literal assignment** | **wrong** - silent rename, see §2 | would rename an empty status too |
| [L1158-L1160](app/docx_import.py#L1158-L1160) `status_counts` | literal 3-tuple | uncounted | uncounted |
| [L929](app/docx_import.py#L929) `if status == "resolved"` | fall-through | correct - no remediation check | correct |
| [L943](app/docx_import.py#L943) `if row["status"] == "open_new"` | fall-through | correct - not reported as rewritten | correct |

[L667](app/docx_import.py#L667) requires a row *labelled* `Status` in the detail table but never reads
its value, and `is_report_docx` does not look at statuses at all. Nothing else in the file enumerates
them.

### Smallest edit list, importer side

Model first (`Status | None = None`), then, all in [app/docx_import.py](app/docx_import.py):

1. **[L53-L58](app/docx_import.py#L53-L58)** - add `"Open (Resolved on Non-Prod)": "open_resolved_on_non_prod"` to `STATUS_BY_LABEL`. *(Round 1; listed only for ordering.)*
2. **[L655](app/docx_import.py#L655)** - carry the raw cell as `"status_label": cells[5]`.
3. **[L778-L780](app/docx_import.py#L778-L780)** - delete the raise; append a per-finding warning instead.
4. **[L880-L887](app/docx_import.py#L880-L887)** - accept either structure when the status is unknown; put `row["status_label"]` in the message.
5. **[L898](app/docx_import.py#L898)** - compare `row["status_label"]`, not `LABEL_BY_STATUS[...]`.
6. **[L922](app/docx_import.py#L922)** - `row["status"] == "resolved"`; delete `RETAINED_STATUSES` at [L59](app/docx_import.py#L59).
7. **[L926](app/docx_import.py#L926)** - re-order and pad `source_contents` to `content_types_for_status(row["status"])`.
8. **[L953](app/docx_import.py#L953)** - inherit unless `open_new`; rewrite the comment above it.
9. **[L1160](app/docx_import.py#L1160)** - count over `STATUS_BY_LABEL.values()`.
10. **[L25](app/docx_import.py#L25)** - import `content_types_for_status` alongside `RESOLVED_REMEDIATION`.

Ten lines, one deletion, one comment. Two existing tests change meaning:
[tests/test_docx_import.py](tests/test_docx_import.py#L1081) (unknown status is no longer a rejection -
and as written it still 422s on the *mismatch* check, so it must edit both cells to test what it
claims to), and whichever retest test pins that a non-`open_new` status is rewritten
([L466](tests/test_docx_import.py#L466), [L1008](tests/test_docx_import.py#L1008)) needs a companion
asserting the new status is **not** in `statuses_rewritten`.

## Round 3 - Planner: plan revised for R1 and R2

### Understanding

Four changes now, not three. **A** widens the username allowlist to admit interior spaces - four
edits, two test rows inverted. **B** makes the empty-environment `N/A` a real bullet - one line in
the Word renderer. **C** adds `open_resolved_on_non_prod` / `Open (Resolved on Non-Prod)` to the
status enum, which behaves exactly like `open_previously_discovered` for free because every rule is
written as `== "open_new"` or `== "resolved"`; what is not free is the tables that enumerate the
status. **D** is new, and it is now the largest part: a retest import must **inherit** the new status
rather than rewrite it (R1), and any status label the app does not recognise must import as an
**empty** status that blocks the tester on the Findings page rather than rejecting the whole document
(R2). R2 is a schema change - `status: Status | None = None` - and it turns three places that index a
dict by status into unhandled 500s, one place that silently drops the finding, one place that rejects
the entire import, and one dropdown that shows the tester "Open (New)" while the value is empty.

### What changed from round 2

Six things, all in Group D, which did not exist in round 2. Groups A, B and C carry forward unchanged
except that C loses two sub-edits to D.

1. **R1 is two edits, not one.** `RETAINED_STATUSES` ([app/docx_import.py](app/docx_import.py#L922))
   only decides drop-versus-keep; the rewrite is a separate **unconditional** assignment at
   [L953](app/docx_import.py#L953). Adding the key to the set alone converts a silent drop into a
   silent rename - the exact behaviour R1 rejects. Round 2's Step C3 was therefore wrong on its own.
   The set is inverted to `== "resolved"` and deleted.
2. **R2 is a 500, not a 422.** Two bare `LABEL_BY_STATUS[row["status"]]` indexes
   ([L887](app/docx_import.py#L887), [L898](app/docx_import.py#L898)) raise `KeyError` on `None`, and
   `KeyError` is not in the import route's except tuple ([app/main.py](app/main.py#L659)) - it is a
   `LookupError`, not a `ValueError`. Unhandled 500.
3. **A site nobody covered in rounds 1 or 2.** `finalize_editable_import`'s projection equality check
   ([app/main.py](app/main.py#L605-L608)) **rejects the whole import** when the document's section
   count disagrees with what an empty status provisions: a three-section document arrives with three
   contents and leaves `provision_report` with five, so `_editable_user_projection` differs and the
   import dies as `Server provisioning would alter imported user content`. One re-order/pad of
   `source_contents` in the importer restores the invariant. Retest mode is unaffected - it writes
   through `workspace.import_report` with no provisioning and no projection check.
4. **The status `<select>` never renders a blank option**, so an empty status displays as
   **Open (New)** while `report` holds nothing. The error outline keys on `!control.value`, which is
   false, so nothing is highlighted; and picking the option the box already shows fires no `change`
   event, so the tester cannot clear the block. One word (`nullable = true`) and R2 ships a working
   gate instead of a trap.
5. **The generation `KeyError` step survives for the new status but not for the empty one.**
   `generation_issues` calls `finding_is_complete` first ([app/docx_report.py](app/docx_report.py#L110)),
   so an empty status 422s at `Complete the report before generating it` before either bare index is
   reached. Step C2 stays; no extra step is needed for `None`.
6. **`provision` and the empty status - decided, and it splits in two.** The section-shaping half is
   **acceptable with no step**: `provision` gives an empty-status finding the five-section shape for
   one save cycle, and picking a status re-runs it, dropping `in_conclusion` outright and dropping an
   untouched `previous_proof_of_concept` because `content_has_work` is false. Nothing is lost and
   nothing is user-visible. The conclusion-sentence half **needs a step**, because it is not merely
   cosmetic on the editable path: `provision` re-derives a recognised default sentence with the word
   `Open` ([app/report_service.py](app/report_service.py#L326)), so a document whose unknown status
   had printed `The finding "X" is still Resolved.` has that sentence rewritten inside
   `finalize_editable_import`, the projection check fires, and **R2's motivating document is
   rejected**. Two one-line guards - Python and its JavaScript twin - close it, and they also stop
   the app asserting "still Open" about a finding whose status it has just refused to read.

### Stated assumptions

Settled without asking. Each is one line to reverse if the user disagrees.

1. **Names.** Stored key `open_resolved_on_non_prod`; label `Open (Resolved on Non-Prod)`, fixed
   text, byte-identical in the dropdown, `STATUS_LABELS` and `STATUS_BY_LABEL`. Not following the
   configurable non-production environment name, because a label that varies per report makes a
   finished document un-importable.
2. **Trailing-space username: accepted, no code.** The typing path is gated by
   `validateSetupInputs(false)` inside `save()` ([app/web/static/app.js](app/web/static/app.js#L767)),
   so `"john "` is never sent. The gate is step-scoped and undo/redo reaches `save()` from every
   page, so a 422 is still reachable off Setup - pre-existing, identical with `"john."` today,
   recorded in the map by Step A3 rather than coded around.
3. **The new status prints the same sections as `open_previously_discovered`**, by doing nothing.
   It therefore prints **Previous Proof of Concept** and **In Conclusion** headings, shows
   **Severity Review Tickets** in the editor and `Severity Review Ticket (if applicable):` in the
   document, and its default conclusion sentence reads `The finding "X" is still Open.`
4. **Empty status is `Status | None = None`**, following `likelihood` / `impact` / `severity`, not a
   new `""` member of the `Literal`. One consequence worth naming: the field default flips from
   `"open_new"` to `None`, so a hand-edited or third-party JSON payload that **omits** `status`
   now loads as empty and blocks on the Findings page instead of silently asserting Open (New). Every
   in-app creation site seeds `"open_new"` explicitly, so nothing the app itself writes changes.
5. **Flagged for the user to overrule - the summary/detail Status consistency check stays as it is.**
   A document whose two Status cells disagree is still refused outright with
   `'"X" summary and detail values do not match.'` ([app/docx_import.py](app/docx_import.py#L899)),
   which means a document where somebody hand-edited **only** the summary cell is rejected rather
   than imported as empty. R2's disclosure for the case that *is* accepted - both cells carrying the
   same unrecognised text - is the per-finding warning added in Step D4, which surfaces through the
   existing `warnings` plumbing in both modes ([L1173](app/docx_import.py#L1173)) and renders as a
   notice ([app/web/static/manager.js](app/web/static/manager.js#L206)). This is the scribe's own
   recommendation and it is one line either way: dropping the `Status` key from `repeated` when
   `row["status"] is None` would make the summary cell authoritative instead.

### Open questions

**None block implementation.** Assumption 5 is the only judgement call left, and it is recorded above
rather than asked because the scribe recommended it and the alternative is a one-line change that can
be made after the fact. If the user wants a half-hand-edited document to import as empty rather than
be refused, say so and Step D5 gains one conditional.

### Blast radius

| File | What changes | Change |
|---|---|---|
| [app/report_service.py](app/report_service.py#L21) | `USERNAME_PATTERN` interior class gains a space | A |
| [app/report_service.py](app/report_service.py#L186) | `allow_spaces=False` dropped from the Username call | A |
| [app/web/static/app.js](app/web/static/app.js#L1472) | `usernameCharacters` class gains a space - **twin of the row above** | A |
| [app/web/static/app.js](app/web/static/app.js#L1497) | inline shape regex gains a space - **twin of `USERNAME_PATTERN`** | A |
| [tests/test_app.py](tests/test_app.py#L236) | negative case swapped from space to `/`; positive username gains a space | A |
| [tests/test_browser.py](tests/test_browser.py#L133) | the same row, **swapped not deleted** | A |
| [docs/DATA_MAP.md](docs/DATA_MAP.md) | §12: the step-scoped save gate and the undo/redo route around it | A |
| [app/docx_report.py](app/docx_report.py#L711) | the empty early return becomes `values = values or ["N/A"]` | B |
| [tests/test_docx.py](tests/test_docx.py) | new: the empty environment's Location cell is a bullet | B |
| [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L232) | the `N/A` placeholder is bulleted too | B |
| [app/models.py](app/models.py#L10) | `Status` gains `open_resolved_on_non_prod` | C |
| [app/docx_report.py](app/docx_report.py#L48) | `STATUS_LABELS` gains a key | C |
| [app/docx_import.py](app/docx_import.py#L53) | `STATUS_BY_LABEL` gains a key; `LABEL_BY_STATUS` derives free | C |
| [app/web/static/app.js](app/web/static/app.js#L119) | `statuses` gains a pair - **twin of `STATUS_LABELS`** | C |
| [app/web/static/manager.js](app/web/static/manager.js#L208) | `labels` gains a key - **third copy of the same table** | C |
| [tests/test_app.py](tests/test_app.py) | new: the new status saves and prints the five-section set | C |
| [tests/test_docx_import.py](tests/test_docx_import.py#L685) | a fourth finding in the all-statuses round trip | C |
| [tests/test_browser.py](tests/test_browser.py) | new: the option exists, selects, and labels | C |
| [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L218), [L248](docs/DOCX_TEMPLATE.md#L248) | the status lists for `retest_finding.docx` and `{{severity-review-tickets}}` | C |
| [docs/DATA_MAP.md](docs/DATA_MAP.md#L411) | the Segment x Status matrix gains a fourth column; §7 the fourth value; §12 the four-copy label twin | C |
| [app/models.py](app/models.py#L207) | `status: Status \| None = None` | D |
| [app/report_service.py](app/report_service.py#L251) | `content_types_for_status(status: str \| None)` - hint only, the body already falls through | D |
| [app/report_service.py](app/report_service.py#L326-L345) | the conclusion re-derivation arm is skipped when the status is empty | D |
| [app/web/static/app.js](app/web/static/app.js#L1055-L1063) | `syncConclusion` - **twin of the row above** | D |
| [app/web/static/app.js](app/web/static/app.js#L2561) | the status `select` gains `nullable = true` | D |
| [app/docx_import.py](app/docx_import.py#L25) | import `content_types_for_status` alongside `RESOLVED_REMEDIATION` | D |
| [app/docx_import.py](app/docx_import.py#L59) | `RETAINED_STATUSES` **deleted** - no remaining reference | D |
| [app/docx_import.py](app/docx_import.py#L655) | the summary row carries `"status_label": cells[5]` | D |
| [app/docx_import.py](app/docx_import.py#L778-L780) | the unknown-status raise **deleted**, replaced by a per-finding warning | D |
| [app/docx_import.py](app/docx_import.py#L880-L887) | accept either section structure when the status is unknown; the message uses the raw label | D |
| [app/docx_import.py](app/docx_import.py#L898) | the consistency check compares `row["status_label"]`, not a dict index | D |
| [app/docx_import.py](app/docx_import.py#L922) | `not in RETAINED_STATUSES` becomes `== "resolved"` | D |
| [app/docx_import.py](app/docx_import.py#L926) | `source_contents` re-ordered and padded to `content_types_for_status(row["status"])` | D |
| [app/docx_import.py](app/docx_import.py#L953) | inherit the status unless it was `open_new`; the comment above it rewritten | D |
| [app/docx_import.py](app/docx_import.py#L1160) | `status_counts` iterates `STATUS_BY_LABEL.values()` | D |
| [tests/test_docx_import.py](tests/test_docx_import.py#L1081) | **changes meaning**: an unknown status is no longer a rejection; the test must edit both cells or assert the mismatch reason | D |
| [tests/test_docx_import.py](tests/test_docx_import.py#L466), [L1008](tests/test_docx_import.py#L1008) | companion assertions: the new status is **not** in `statuses_rewritten` and not in `dropped` | D |
| [tests/test_app.py](tests/test_app.py), [tests/test_browser.py](tests/test_browser.py) | new: an empty status saves, blocks Next, and shows a labelled blank option | D |
| [docs/DATA_MAP.md](docs/DATA_MAP.md) | §7: `status` joins the nullable group; the import's unknown-status behaviour | D |

**Deliberately not touched:** [app/workspace.py](app/workspace.py), [app/storage.py](app/storage.py),
[app/main.py](app/main.py) (the projection check is satisfied from the importer, not relaxed),
`resources/**` (no `.docx` needs editing or creating), `content_types_for_status` and
`contentTypesForStatus` bodies, the `resolved` remediation boilerplate, `STATUS_CONCLUSION_PATTERN`
and its twin, `finding_input_issues`, and `restoreHistory`.

### Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write | clear | No new mutation route. Status rides the existing `PUT /reports/{id}`, which carries `saved_at` in the body; the import routes are unchanged in shape. |
| Lost update | clear | Nothing new reads then writes. Worth knowing rather than acting on: `load_path` ([app/workspace.py](app/workspace.py#L272)) already does a read-modify-write on load, so a new migration is not the only way to spend a backup level. |
| Orphan reference | clear | The one section dropped on a move to `open_new` is `in_conclusion`, which admits only `paragraph` and `note` ([app/web/static/app.js](app/web/static/app.js#L121)) - no `evidence_id` can be stranded, and dropping a `Content` takes its fragments with it. The D6 pad creates contents with `fragments: []`, referencing nothing. One clause of honesty: a `content_offer_dismissed["in_conclusion"]` key is left behind, which `ContentType` still admits and nothing reads. |
| Silent stranding | **RISK, R1's whole point** | [app/docx_import.py](app/docx_import.py#L922) drops any status outside `RETAINED_STATUSES` on a retest import and reports it under `dropped_resolved` - a lie about why. `None` would be dropped too. Closed by **Step D3**, which inverts the test to `== "resolved"` so the counter becomes literally accurate rather than accidentally accurate. |
| Silent rename *(new for R1)* | **RISK** | [L953](app/docx_import.py#L953) assigns `status = "open_previously_discovered"` from a literal, unconditionally, and `rewritten` is appended only for `open_new` - so extending the set without touching this line turns a silent drop into a **silent rename**. Closed by **Step D3**, which inherits instead. `open_previously_discovered` maps to itself, so it is a no-op for today's data. |
| Schema break | **RISK, one direction, three stores** | Adding a member and adding `\| None` are both permissive: all 45 status values across the 10 real drafts are existing keys, so nothing on disk stops loading and no repair is needed. **Renaming or reverting later is not recoverable through the UI** - and the key lives in `localStorage` as the whole report ([app/web/static/app.js](app/web/static/app.js#L316)) and in `sessionStorage` as undo diffs ([L574](app/web/static/app.js#L574)), neither validated on read, neither reachable by a server-side migration. A stale key displays as **Open (New)** while `report` holds the dead value, invisible until the save 422s. The names in Assumption 1 must be right in the first commit. |
| Unhandled 500 on import *(new for R2)* | **RISK** | `LABEL_BY_STATUS[row["status"]]` at [L887](app/docx_import.py#L887) and [L898](app/docx_import.py#L898) raises `KeyError` on `None`; `KeyError` is a `LookupError`, so the route's `except (... ValidationError, ValueError)` ([app/main.py](app/main.py#L659)) does not catch it. Closed by **Step D5**, which compares the raw cell text instead - a strict no-op for known statuses, because `STATUS_BY_LABEL` and `LABEL_BY_STATUS` are exact inverses. |
| Whole-import rejection *(new for R2)* | **RISK** | `finalize_editable_import` compares `_editable_user_projection` before and after `provision_report` ([app/main.py](app/main.py#L605-L608)), and the projection keeps every content entry. `content_types_for_status(None)` is the five-section list, so a three-section unknown-status document goes 3 → 5 and the import dies with `Server provisioning would alter imported user content`. Closed by **Step D6**, which re-orders *and* pads `source_contents` in the importer - order matters, because `provision` emits `types` order and appending to the end puts `proof_of_concept` before `previous_proof_of_concept`. No-op for all four known statuses. |
| Whole-import rejection, second route *(new for R2)* | **RISK** | The same projection check fires when `provision` **re-derives the conclusion sentence**: a document whose unknown status had printed `The finding "X" is still Resolved.` matches `default_conclusion_span`, is rewritten with the word `Open` ([app/report_service.py](app/report_service.py#L345)), and the projection differs. Closed by **Step D7**. Today this is invisible because the derived word always equals the printed word. |
| Request/response asymmetry | clear | `status` is a stored model field echoed by `model_dump`; `None` round-trips as JSON `null` and `!finding.status` is already falsy for it, so no client predicate changes. |
| Rule drift | **RISK, three now** | **(a)** The status label exists in **four** places - `STATUS_LABELS`, `STATUS_BY_LABEL`, `statuses`, `manager.js` `labels` - with **no drift guard**. Mitigated by ordering: C4 last. **(b)** Change A touches the unnamed username twin whose only guard is [tests/test_browser.py](tests/test_browser.py#L133); Step A2 exists for nothing else. **(c)** *New:* the conclusion status word is a twin - `provision` ([app/report_service.py](app/report_service.py#L326)) and `syncConclusion` ([app/web/static/app.js](app/web/static/app.js#L1055)) - and Step D7 must change both in the same commit, or the browser writes `Open` into a statusless finding on the next title keystroke ([L2565](app/web/static/app.js#L2565)) and the two sides disagree about what is on disk. |
| Navigation trap | **RISK, closed by one word** | The gate itself needs no new code: status is already the fourth element of `assessment` in `validateFindingsPage` ([app/web/static/app.js](app/web/static/app.js#L2754)), and `GET /reports/{id}/edit` redirects unless every finding passes `finding_is_complete` ([app/main.py](app/main.py#L737)). But `select(statuses.map(x=>x[0]), finding.status)` passes neither `nullable` nor the `severity` array by identity ([L279](app/web/static/app.js#L279)), so no blank option is rendered: an empty status **displays Open (New)**, gets no error outline because `showFindingValidationErrors` keys on `!control.value` ([L2255](app/web/static/app.js#L2255)), and choosing the option already shown fires no `change`. The tester is blocked with nothing highlighted and no way to unblock. Closed by **Step D2**. |
| Derived-state fight | **accepted, no step for the shaping half** | `provision` runs on every save ([app/main.py](app/main.py#L801)) and shapes an empty-status finding as a retest finding - five contents rather than three. It does not block anything, it writes only empty sections, and it self-corrects: picking a status re-runs `provision`, which drops `in_conclusion` outright and drops an untouched `previous_proof_of_concept` because `content_has_work` is false. Accepted. The conclusion-sentence half of the same function is **not** accepted - see the two rejection rows above and Step D7. |
| Backup exhaustion | clear, **conditional** | Only because no migration is planned. A `load_path` repair for either enum change would rewrite every draft to change nothing and burn the single `draft.bak.json` level ([docs/DATA_MAP.md](docs/DATA_MAP.md) §6). |
| Generation crash | **RISK for the new status only** | `STATUS_LABELS[finding.status]` is a bare index at [app/docx_report.py](app/docx_report.py#L516) and [L769](app/docx_report.py#L769). Unextended, the first generation of a new-status finding is a raw `KeyError` inside `render_report_docx` - a 500. Closed by **Step C2**. **Not** a risk for the empty status: `generation_issues` calls `finding_is_complete` first ([L110](app/docx_report.py#L110)), so `finalized_report` raises `422 Complete the report before generating it` ([app/main.py](app/main.py#L518)) before rendering. The one way to reach it is `scripts/generate_report.py --allow-incomplete`, a developer script, and that is accepted. |
| Import summary arithmetic *(new for R2)* | **RISK, cosmetic** | `status_counts` iterates a literal three-tuple ([L1158](app/docx_import.py#L1158)), so the new status is uncounted and empty-status findings make the totals not add up - "12 findings · 5 Open New, 4 Previously Discovered". Closed by **Step D8** (iterate `STATUS_BY_LABEL.values()`, self-maintaining) plus Step D4's warning, which names every finding whose status was not recognised. `manager.js` `labels` is not reached for a missing key because the `.filter(([, count]) => count)` above it drops it. |
| Save-path rejection *(new for R2)* | clear | `finding_input_issues` reads **only** `severity_review_tickets` ([app/report_service.py](app/report_service.py#L199-L215)) and never looks at status, so once the model admits `None` nothing on the save path objects. A tester can import a draft full of empty statuses, save it, close the app and come back to it. This is the invariant R2 depends on and Step D1 must not break it. |
| Autosave rejection while typing | clear for the typing path; **accepted elsewhere** | `save()` gates on `validateSetupInputs(false)` on the Setup step ([app/web/static/app.js](app/web/static/app.js#L767)), so a half-typed `"john "` is never sent. The gate is step-scoped and `restoreHistory` calls `save()` from every page, so Ctrl+Z on Findings can send it and 422, then block Back and Next together. Pre-existing and reachable today with `"john."`. Step A3 records it. |
| `N/A` bullet on import | clear | `_visible_value` returns `""` for exactly `"N/A"` ([app/docx_import.py](app/docx_import.py#L90)), so it is discarded before matching; `_detail_locations` reads text and never inspects `w:numPr`. |
| Legacy remediation blanking | clear, pre-existing | `load_path`'s `elif stale:` arm empties an unmarked legacy remediation paragraph for any non-`resolved` status ([app/workspace.py](app/workspace.py#L292)). Both the new status and `None` inherit exactly what `open_previously_discovered` does today. |
| Empty finding-card chip *(new for R2)* | clear, cosmetic | `statuses.find(...)?.[1] \|\| finding.status` ([app/web/static/app.js](app/web/static/app.js#L3769)) yields `""` for an empty status, so the card shows no status chip. The Findings row is the authoritative view and Step D2 makes it explicit there. No step. |

### Plan

Four groups. **A and B are independent of everything and of each other** - each is one line of
behaviour plus its test, and either can ship alone. **C and D are one unit**: D3 is what stops a
retest import eating a new-status finding, so C must not reach the dropdown before D is done.

**The one cross-group ordering rule: Step C4 is the last code step in the commit.** It is the gate
that lets the new value into a saved draft, into `localStorage` and into `sessionStorage`, so every
consumer - model, document, importer - must already handle it.

#### Group A - allow spaces in the username

Suite: `tests.test_app` for A1, `tests.test_browser` for A2, none for A3.

- [ ] **Step A1 — widen the username character set on both sides.**
  Files: [app/report_service.py](app/report_service.py#L21) (`USERNAME_PATTERN` interior class),
  [app/report_service.py](app/report_service.py#L186) (drop `allow_spaces=False`),
  [app/web/static/app.js](app/web/static/app.js#L1472) (`usernameCharacters`),
  [app/web/static/app.js](app/web/static/app.js#L1497) (the inline shape regex).
  Put the space where it cannot form a range - immediately after the `[`, giving
  `[ A-Za-z0-9._@\\-]` - so the trailing `-` stays literal in all four patterns.
  Test: `tests/test_app.py::test_setup_input_validation_rejects_unapproved_characters_and_date_order`
  - swap the negative case `"bad user"` for `"bad/user"` expecting
  `'Username 1 contains invalid character: "/" (slash)'`, and change the positive case's username
  from `DOMAIN\qa.user@example` to `DOMAIN\qa user@example` so one value proves the backslash pin
  and the new space in the same assertion.
  Invariant: the start/end anchors stay, so a leading or trailing space is still invalid, and `N/A`
  stays exempt by literal comparison on both sides.

- [ ] **Step A2 — keep the message drift guard alive.**
  File: [tests/test_browser.py](tests/test_browser.py#L133).
  **Swap the row in place, do not delete it:**
  `("Username 1", "bad/user", "DOMAIN\\qa user@example", 'Username 1 contains invalid character: "/" (slash)')`.
  Test: `tests.test_browser::test_setup_inputs_report_character_and_date_errors_before_save`.
  Invariant: the browser's `validationMessage` stays byte-identical to the server's issue string for
  the one field whose per-character allowlist has no other guard.

- [ ] **Step A3 — record the accepted consequence in the map.**
  File: [docs/DATA_MAP.md](docs/DATA_MAP.md) §12 - one short entry: `save()`'s Setup validity gate is
  **step-scoped** (`root.dataset.step === "setup"`), while `restoreHistory` and local draft recovery
  call `save()` from every page, so an invalid Setup value can leave the client via undo and 422,
  blocking Back and Next together.
  Test: none.
  Invariant: the next person to widen a Setup rule finds this written down rather than rediscovering it.

#### Group B - `N/A` as a bulleted list

Suite: `tests.test_docx`, plus `tests.test_docx_import` once at the end.

- [ ] **Step B1 — stop taking the empty early return.**
  File: [app/docx_report.py](app/docx_report.py#L711) - replace the three lines with
  `values = values or ["N/A"]`.
  Test: new, in [tests/test_docx.py](tests/test_docx.py) - render a production-only finding, then
  assert the Non-Production Location cell's second paragraph is styled `List Paragraph`, carries a
  `w:numPr` under its `w:pPr`, reads `N/A`, and that the cell text contains no `\u2022`. No existing
  test asserts the empty cell at all.
  Invariant: the token paragraph is still removed, so `_unresolved_placeholders` stays satisfied and
  generation does not abort; `_visible_value` still maps `N/A` to `""` on import, so the round trip
  is unchanged.

- [ ] **Step B2 — correct the template document.**
  File: [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L232) - say the `N/A` placeholder is bulleted
  too, and that Limitations deliberately goes the other way. Test: none.

#### Group C - the fourth finding status

Suite: `tests.test_app` for C1, `tests.test_docx_import` for C2 and C3, `tests.test_browser` for C4.

- [ ] **Step C1 — extend the enum, server side only.**
  File: [app/models.py](app/models.py#L10) - `Status` gains `open_resolved_on_non_prod`.
  Test: new, in [tests/test_app.py](tests/test_app.py) - PUT a finding carrying the new status,
  expect 200, and assert `content_types_for_status("open_resolved_on_non_prod")` returns the
  five-section set.
  Invariant: no `load_path` repair and no migration. Widening a `Literal` is permissive, so every
  draft on disk still loads unchanged and the single `draft.bak.json` level stays unspent.

- [ ] **Step C2 — teach the document the label.**
  File: [app/docx_report.py](app/docx_report.py#L48) - `STATUS_LABELS` gains
  `"open_resolved_on_non_prod": "Open (Resolved on Non-Prod)"`.
  Test: extend `tests/test_docx_import.py::test_editable_mode_keeps_all_statuses_and_printed_sections`
  with a fourth finding carrying the new status, asserting both its status and its five printed
  section types survive a render-then-import round trip.
  Invariant: the two bare indexes at [L516](app/docx_report.py#L516) and
  [L769](app/docx_report.py#L769) read the one dict, so the summary table and the detail token cannot
  disagree - which is what the importer's consistency check depends on. Closes the `KeyError` 500.

- [ ] **Step C3 — teach the importer the label.**
  File: [app/docx_import.py](app/docx_import.py#L53) - `STATUS_BY_LABEL` gains the same string as its
  key; `LABEL_BY_STATUS` derives free.
  Test: covered by the extended C2 test, which exercises the render, the label, the summary/detail
  cross-check and `STATUS_BY_LABEL` together.
  Invariant: the document label and the dropdown label are the same bytes, so a report this app
  generated can always be read back.

- [ ] **Step C4 — open the dropdown. Last code step in the commit.**
  Files: [app/web/static/app.js](app/web/static/app.js#L119) `statuses`,
  [app/web/static/manager.js](app/web/static/manager.js#L208) `labels`.
  Test: one new browser test - the option exists with the label `Open (Resolved on Non-Prod)`,
  selecting it renders the five sections, and the finding-card chip prints the label rather than the
  raw key.
  Invariant: the client never offers a status the server would 422, and nothing can reach a document
  or an import that cannot handle it. Before C1 a user could save a value the model rejects; before
  C2 they could reach a `KeyError` at generation; **before D3 a retest import would eat the finding.**

- [ ] **Step C5 — correct the stale documentation and record the twin.**
  Files: [docs/DOCX_TEMPLATE.md](docs/DOCX_TEMPLATE.md#L218) and [L248](docs/DOCX_TEMPLATE.md#L248)
  (both enumerate the statuses that use `retest_finding.docx` and print `{{severity-review-tickets}}`);
  [docs/DATA_MAP.md](docs/DATA_MAP.md) §7 for the fourth value, §12 for the status-label table as a
  **four-copy twin with no drift guard**, and the **Segment x Status matrix** at
  [L411](docs/DATA_MAP.md#L411), which needs a fourth column behaving like
  `open_previously_discovered` because `additionalInformationFields` gates on `status !== "open_new"`
  ([app/web/static/app.js](app/web/static/app.js#L3372)). While there, add the two absences the
  oracle found in round 1: the `location_values` `get` versus `||` divergence, and
  `workspace.load_path` as a fourth Python site branching on `status == "resolved"`.
  Test: none.
  Invariant: the map's only exhaustive status enumeration does not silently omit the new value.

#### Group D - import: inherit (R1) and empty unknown (R2)

Suite: `tests.test_app` for D1, `tests.test_browser` for D2 and the JavaScript half of D7,
`tests.test_docx_import` for D3-D6 and D8.

- [ ] **Step D1 — make "no status" representable.**
  Files: [app/models.py](app/models.py#L207) - `status: Status | None = None`;
  [app/report_service.py](app/report_service.py#L251) - widen the `content_types_for_status` hint to
  `str | None` (the body already falls through correctly).
  Test: new, in [tests/test_app.py](tests/test_app.py) - PUT a finding with `"status": null`, expect
  **200**, reload and assert it persisted as `null`; assert `finding_is_complete` is false for it and
  that `GET /reports/{id}/edit` redirects to `?incomplete=findings`.
  Invariant: **no gate on the save path may reject a draft.** `finding_input_issues` deliberately
  tolerates blank fields so work in progress always saves; an empty status must stay inside that
  tolerance or the import cannot land. Follows `likelihood` / `impact` / `severity` - `None` outside
  the `Literal`, never `""` inside it.

- [ ] **Step D2 — give the status select a blank option. Before any import can produce one.**
  File: [app/web/static/app.js](app/web/static/app.js#L2561) - pass `nullable = true` to the status
  `select`, matching likelihood and impact.
  Test: new browser test - a finding whose status is empty renders a **selected** placeholder (not
  Open (New)), `labelAssessmentPlaceholders` names it `Status`, the control carries the error class
  after a blocked Next, and choosing a real status clears the block.
  Invariant: the placeholder stays `disabled`, so a status cannot be returned to empty once set - the
  empty state is import-only. The dropdown must never display a value `report` does not hold.

- [ ] **Step D3 — R1: inherit on retest instead of renaming, and stop lying about why.**
  File: [app/docx_import.py](app/docx_import.py) - [L922](app/docx_import.py#L922) becomes
  `if mode == "retest" and row["status"] == "resolved":`; delete `RETAINED_STATUSES`
  ([L59](app/docx_import.py#L59)), which then has no reference in `app/` or `tests/`;
  [L953](app/docx_import.py#L953) becomes
  `status = "open_previously_discovered" if row["status"] == "open_new" else row["status"]`; rewrite
  the comment above it, which claims previously-discovered "is the only status that keeps a previous
  proof of concept" and stops being true here.
  Test: `tests/test_docx_import.py::test_a_generated_report_imports_as_a_retest_draft` - a
  new-status finding is retained, keeps its status, and appears in neither `dropped` nor
  `statuses_rewritten`; the existing pins at [L466](tests/test_docx_import.py#L466) and
  [L1008](tests/test_docx_import.py#L1008) must still show `open_new` → `open_previously_discovered`.
  Invariant: **no open finding is ever dropped by a retest import and reported as
  `dropped_resolved`, and no status is changed without appearing in `statuses_rewritten`.** Both
  counters become literally accurate: `rewritten` is appended only for `open_new`, which after this
  edit is exactly the set whose status changed. Inverting rather than extending also keeps `None` out
  of a membership set, where it would read as nonsense.

- [ ] **Step D4 — R2: accept an unrecognised label and say so.**
  File: [app/docx_import.py](app/docx_import.py) - [L655](app/docx_import.py#L655) carries the raw
  cell as `"status_label": cells[5]` beside the mapped value; delete the unknown-status raise at
  [L778-L780](app/docx_import.py#L778) and append one warning per affected finding instead, naming
  the finding and the unrecognised text and telling the tester to set a status on the Findings page.
  `warnings` is already a parameter of `_findings` ([L775](app/docx_import.py#L775)) and surfaces in
  both modes ([L1173](app/docx_import.py#L1173)).
  Test: `tests/test_docx_import.py` - a document with an unrecognised label in **both** Status cells
  imports with `status: None` on that finding, writes a draft, and returns a summary warning naming
  the finding and the text. Update
  `test_malformed_editable_import_writes_no_report_directory` ([L1081](tests/test_docx_import.py#L1081)),
  which edits only the summary cell: it still 422s and still writes nothing, but now on
  `summary and detail values do not match` - assert the new reason so the test keeps proving what its
  name claims.
  Invariant: `STATUS_BY_LABEL.get` already yields `None`, so the parse step itself needs no change -
  the only thing standing between the document and an empty status is that one raise. An import that
  silently blanks a status has only moved the silence, which is why the warning is part of this step
  rather than a follow-up.

- [ ] **Step D5 — R2: stop the two `KeyError` 500s.**
  File: [app/docx_import.py](app/docx_import.py) - [L880-L887](app/docx_import.py#L880): when
  `row["status"]` is `None`, accept **either** `content_types_for_status("open_new")` or
  `content_types_for_status(None)` as the section order, set `expected_sections = section_order`, and
  put `row["status_label"]` in the failure message instead of `LABEL_BY_STATUS[...]`;
  [L898](app/docx_import.py#L898): compare `row["status_label"]`. Import `content_types_for_status`
  at [L25](app/docx_import.py#L25).
  Test: `tests/test_docx_import.py` - a three-section document whose Status cells both read an
  unrecognised label imports cleanly (proving the structure gate no longer demands five sections),
  and the whole suite still passes for the four known statuses.
  Invariant: **no import failure may leave the route's except tuple** - `KeyError` is a `LookupError`
  and would surface as an unhandled 500 ([app/main.py](app/main.py#L659)). Comparing the raw cell is
  a strict no-op for known statuses, because `STATUS_BY_LABEL` and `LABEL_BY_STATUS` are exact
  inverses, so the compared string is byte-identical today. Using `content_types_for_status` also
  removes a duplicated literal rather than adding one. Per Assumption 5 the consistency check itself
  stays: a document whose two Status cells disagree is still refused.

- [ ] **Step D6 — R2: keep the editable import from rejecting itself.**
  File: [app/docx_import.py](app/docx_import.py#L926) - immediately before the
  `if mode == "editable":` branch, re-order and pad `source_contents` to
  `content_types_for_status(row["status"])`, filling any missing section with
  `{"type": t, "fragments": []}`.
  Test: `tests/test_docx_import.py` - an **editable** import of a three-section document with an
  unrecognised status returns 200, writes a draft, and the saved finding has the five contents in
  `content_types_for_status` order with the two new ones empty.
  Invariant: **what the importer hands to `finalize_editable_import` must already be the shape
  `provision` will produce**, or `_editable_user_projection` differs and the import is refused with
  `Server provisioning would alter imported user content` ([app/main.py](app/main.py#L605-L608)).
  Canonical **order** matters, not just membership - appending the missing sections would put
  `proof_of_concept` before `previous_proof_of_concept` and fail the same comparison. No-op for all
  four known statuses, because `expected_sections` already equals `content_types_for_status(status)`
  for each of them. Retest mode needs nothing: it writes through `workspace.import_report` with no
  provisioning, and its branch already builds exactly the five-content list.

- [ ] **Step D7 — R2: do not assert "still Open" about a finding with no status.**
  Files: [app/report_service.py](app/report_service.py#L332) - guard the `elif default is not None:`
  arm on a truthy `vulnerability.status`, leaving the imported sentence verbatim;
  [app/web/static/app.js](app/web/static/app.js#L1063) - the same guard on `syncConclusion`'s
  `defaultParagraph` arm. Leave the `if not paragraphs:` arm running on both sides so the two
  provisioners still agree on shape.
  Test: `tests/test_app.py` - `provision` on a finding with `status=None` whose `in_conclusion`
  carries `The finding "X" is still Resolved.` leaves the runs untouched, and re-running after a
  status is chosen re-derives the sentence correctly; plus a browser assertion that editing the title
  of an empty-status finding does not rewrite the sentence
  ([app/web/static/app.js](app/web/static/app.js#L2565) calls `syncConclusion` on every keystroke).
  Invariant: **the two provisioners must stay identical.** If only Python is guarded, the browser
  rewrites the sentence on the next keystroke and the client and server disagree about what is on
  disk. This is also the second route by which an editable import of R2's motivating document would
  otherwise be rejected outright.

- [ ] **Step D8 — make the import summary add up.**
  File: [app/docx_import.py](app/docx_import.py#L1160) - iterate `STATUS_BY_LABEL.values()` rather
  than the literal three-tuple.
  Test: `tests/test_docx_import.py` - an editable import containing the new status counts it, and one
  containing an empty status is not counted there but **is** named in `warnings` (Step D4).
  Invariant: the counter is self-maintaining, so the next status added to the label map is counted
  without anyone remembering this line; `None` stays out because it has no label.

- [ ] **Step D9 — record the new shape in the map.**
  File: [docs/DATA_MAP.md](docs/DATA_MAP.md) §7 - move `status` into the nullable group beside
  `likelihood`, `impact` and `severity`, and state the import rule in one line: an unrecognised status
  label imports as empty with a warning, a retest import inherits every status except `open_new`, and
  a document whose two Status cells disagree is refused.
  Test: none.
  Invariant: the map does not go on saying status is always set.

### What I would not do

1. **No `load_path` repair or migration for either enum change.** Both are permissive and every draft
   on disk already validates. A repair would rewrite files to change nothing and consume the single
   `draft.bak.json` level - the `non_production_label` precedent.
2. **No `""` member in the `Literal`.** It would put an empty string into `STATUS_BY_LABEL`'s value
   space and make every `status == "..."` comparison consider a fourth real value rather than an
   absence, and it would be the only assessment field on the row not following `None`.
3. **No `.get()` fallback on `STATUS_LABELS`.** An invented label would be written into a document
   and read back as garbage. The `KeyError` is the correct failure for an unknown status at
   generation; extend the dict. (The importer's two indexes are different: there the value is
   legitimately `None`, so Step D5 removes the index rather than defaulting it.)
4. **No extension of `RETAINED_STATUSES`.** Adding the key satisfies R1's letter and breaks its
   spirit - the finding stops being dropped and starts being renamed, silently. Inverting the test
   and deleting the set is the same size and is self-maintaining.
5. **No relaxing of the `finalize_editable_import` projection check**, and no edit to
   [app/main.py](app/main.py). It is the thing that guarantees an editable import is not quietly
   altered on the way in. Step D6 satisfies it from the importer instead, which is where the shape is
   decided.
6. **No new drift-guard test for the four status-label tables.** Building one means asserting a
   JavaScript array against two Python dicts and a second JavaScript object, for a table that changes
   about once a year. Ordering C4 last buys the practical half. Record the gap in `DATA_MAP.md`.
7. **No status-aware In Conclusion sentence for the new status.** Step D7 only *suppresses* the
   sentence when there is no status; it does not teach the builder a new word. Teaching it one means
   changing `status_conclusion_runs`, `STATUS_CONCLUSION_PATTERN` and both twins together, and the
   recogniser must keep `(?:Open|Resolved)` forever or every sentence already on disk stops matching.
8. **No dynamic status label following `non_production_label`.** `STATUS_BY_LABEL` is a static
   reverse map; a per-report label makes a generated document un-importable.
9. **No server-side username stripping, no widening of the `save()` Setup gate, no change to
   `restoreHistory`.** The undo/redo 422 is real, pre-existing, reachable today, and belongs in its
   own plan. Step A3 writes it down.
10. **No fix for the two adjacent divergences the oracle found** - the `location_values` `get` versus
    `||` empty-string leak and the Unicode-letter asymmetry in the username message. Both are real,
    neither is in this request; they go in `DATA_MAP.md` as known.
11. **No change to the Limitations `N/A`.** `_center_plain` ([app/docx_report.py](app/docx_report.py#L445))
    deliberately strips the bullet and centres it. After Step B1 the two tables disagree on purpose:
    affected locations is a list of many things, Limitations is one statement.

## Round 4 - Scribe: unknown status falls back to Previously Discovered

R2′ deletes most of Group D, as the user expects. It does not delete as much as the question
assumes: **D5 does not die, it halves**, and the half that survives is the one that decides whether
the motivating document imports at all. Everything below is read out of
[app/docx_import.py](app/docx_import.py) at the lines named.

### Verdict in one line each

| Step | Round 3 purpose | Under R2′ |
|---|---|---|
| D1 | `Status \| None` on the model | **dies** |
| D2 | blank option in the status select | **dies** |
| D3 | R1: inherit on retest | **survives unchanged** |
| D4 | delete the raise, set `None`, warn | **changes** — set `open_previously_discovered` at parse; keep the warning, in `warnings` |
| D5 | two `KeyError` 500s + tolerate either section order | **halves** — the `KeyError` half dies, the section-order half is now load-bearing |
| D6 | pad `source_contents` before the editable branch | **survives, narrowed** — reachable only if D5's surviving half lands |
| D7 | guard the conclusion sentence on a truthy status | **dies** |
| D8 | count over `STATUS_BY_LABEL.values()` | **survives, for a different reason** (Group C, not R2) |
| D9 | `DATA_MAP.md` §7 | **changes** — no nullable move, one line on the fallback |

### 1. D1, D2 and D7 die. D5 does not.

**D1 — dies.** [app/models.py](app/models.py#L10) and [app/models.py](app/models.py#L207) stay as
they are, and `content_types_for_status(status: str)`
([app/report_service.py](app/report_service.py#L251)) keeps its `str` hint. Nothing else wanted the
nullable field. Confirmed.

**D2 — dies.** [app/web/static/app.js](app/web/static/app.js#L119) gains a fourth `[key, label]`
pair for Step C4 and nothing else; no `nullable = true`, no disabled placeholder. An empty status is
now unreachable from every direction — the model default, the three creation sites, and the importer
which, after D4, resolves every cell to one of four keys. Confirmed.

**D7 — dies.** Both provisioners read the status through a ternary, not an index:
[app/report_service.py](app/report_service.py#L326) is
`status = "Resolved" if vulnerability.status == "resolved" else "Open"` and its twin is
[app/web/static/app.js](app/web/static/app.js#L1128). Neither can see a falsy status after R2′, and
neither would crash if it did — D7 existed only so the app would not assert "still Open" about a
finding whose status it had refused to read. There is no such finding now. Confirmed. (The sentence
still reads "still Open" for `open_resolved_on_non_prod`; that is Decision 2 in Group C, already
accepted, and untouched here.)

**D5 — half of it is still needed, and it is the half that matters.** D5 carried two things:

1. *The two `KeyError` 500s* — [app/docx_import.py](app/docx_import.py#L887) and
   [app/docx_import.py](app/docx_import.py#L898), both `LABEL_BY_STATUS[row["status"]]`. With the
   fallback applied at parse time, `row["status"]` is always one of the four keys and
   `LABEL_BY_STATUS` holds all four after Step C3. **This justification dies.** L898 still changes,
   but as part of §3 below, not to avoid a crash.
2. *Tolerating either section order* — [app/docx_import.py](app/docx_import.py#L880-L887). **This
   does not die.** See §4: it is the first thing that refuses the user's document, ahead of the
   consistency check and far ahead of the projection check.

### 2. D4 — the exact edit, and where the warning belongs

The raise at [app/docx_import.py](app/docx_import.py#L778-L780) does not become "set `None` and
warn". Under R2′ the fallback belongs **at parse time**, in `_summary_rows`, so that one expression
owns the rule and every later site reads an official key.

Add beside `_clean` ([app/docx_import.py](app/docx_import.py#L84-L88)):

```python
STATUS_FALLBACK = "open_previously_discovered"


def _status_of(label: str) -> str:
    """R2′: anything that is not one of the four official labels reads as previously discovered."""
    return STATUS_BY_LABEL.get(_clean(label), STATUS_FALLBACK)
```

Then [app/docx_import.py](app/docx_import.py#L655):

```python
            "status": _status_of(cells[5]), "status_label": cells[5],
```

`status_label` is still required — not for an error message this time, but because after the
fallback collapses them there is no other way to tell "the cell said Previously Discovered" from
"the cell said something we did not recognise". §3 and §4 both need that distinction.

Then delete [app/docx_import.py](app/docx_import.py#L778-L780) and warn in place:

```python
    for row in summary_rows:
        if _clean(row["status_label"]) not in STATUS_BY_LABEL:
            warnings.append(f'"{row["title"]}": the status "{row["status_label"]}" was not recognised and was set to Open (Previously Discovered).')
```

**Yes, keep the warning, and `warnings` is the right home — `statuses_rewritten` is the wrong one,
for two reasons that are both in the client.**
[app/web/static/manager.js](app/web/static/manager.js#L197-L201) reads `statuses_rewritten` **only
when `result.mode === "retest"`**, so a fallback on an editable import would be recorded and never
shown. And it renders the list with fixed wording — `"N Open New findings were changed to Previously
Discovered for retesting"` — which is a false sentence about a finding whose cell read `Pending`.
`warnings` has neither problem: it is surfaced in editable mode at
[app/docx_import.py](app/docx_import.py#L1168) and in retest mode at
[app/docx_import.py](app/docx_import.py#L1172-L1173), and
[app/web/static/manager.js](app/web/static/manager.js#L206) pushes it into the same notice list in
both.

### 3. Where the normalisation goes — and the check is *not* the first refusal

**The comparison reads the raw detail cell, so parse-time normalisation does not make it agree for
free.** The check is [app/docx_import.py](app/docx_import.py#L895-L901):

```python
        repeated = {
            "Severity": row["severity"].title(),
            "ID": row["display_id"],
            "Status": LABEL_BY_STATUS[row["status"]],
        }
        if any(_clean(detail_values.get(label, "")) != _clean(value) for label, value in repeated.items()):
            raise ReportImportError(f'"{title}" summary and detail values do not match.')
```

`detail_values` is built two lines above from `cell.text.strip()`
([app/docx_import.py](app/docx_import.py#L890-L894)) — raw text, never mapped. So a summary cell
reading `Pending` becomes `open_previously_discovered`, `LABEL_BY_STATUS` turns that back into
`Open (Previously Discovered)`, and it is compared against the literal string `Pending` from the
detail table. **Mismatch, refused.** The detail side needs its own pass through `_status_of`:

```python
        repeated = {
            "Severity": row["severity"].title(),
            "ID": row["display_id"],
        }
        if any(_clean(detail_values.get(label, "")) != _clean(value) for label, value in repeated.items()) \
                or _status_of(detail_values.get("Status", "")) != row["status"]:
            raise ReportImportError(f'"{title}" summary and detail values do not match.')
```

**Verified against the adopted reading, and it under-delivers on one case R2′ names explicitly.**
Normalising both cells gives:

| Summary cell | Detail cell | Result |
|---|---|---|
| unrecognised | unrecognised | both → previously discovered · **imports** |
| unrecognised | `Open (Previously Discovered)` | both → previously discovered · **imports** |
| unrecognised | `Open (New)`, `Resolved`, `Open (Resolved on Non-Prod)` | **refused** |
| `Open (New)` etc. | unrecognised | **refused** |
| two different official labels | — | **refused** (intended) |

Rows 3 and 4 are *"only one of the two Status cells was hand-edited"*, which R2′ says must not be
refused. The existing test is exactly that shape:
[tests/test_docx_import.py](tests/test_docx_import.py#L1084) writes `Pending` into the summary cell
only, on a fixture finding whose status is `open_new`
([tests/test_docx_import.py](tests/test_docx_import.py#L77)). Normalising both cells still refuses
it.

**The one-line completion**, if the user's sentence is to be honoured literally: compare the two
cells only when **both** carry official labels.

```python
        detail_label = _clean(detail_values.get("Status", ""))
        if detail_label in STATUS_BY_LABEL and _clean(row["status_label"]) in STATUS_BY_LABEL \
                and STATUS_BY_LABEL[detail_label] != row["status"]:
            raise ReportImportError(f'"{title}" summary and detail values do not match.')
```

Two official labels that differ are still refused, which is the carve-out the user kept. One
unrecognised label on either side makes the summary cell authoritative and imports. **Recommended**,
because R2′ names this case in its own sentence and the adopted reading does not reach it.

### 4. D6 survives — but the structure gate refuses the document first

**The projection check is the third refusal, not the first.** For a hand-edited three-section
document in editable mode, in execution order:

1. [app/docx_import.py](app/docx_import.py#L880-L887) — `row["status"]` is now
   `open_previously_discovered`, so `expected_sections` is the five-section list, `section_order` has
   three, and it raises `'"X" does not have the expected section structure for Open (Previously
   Discovered).'` **This fires first, inside `_findings`.**
2. §3's consistency check, at [app/docx_import.py](app/docx_import.py#L900).
3. `finalize_editable_import`'s `_editable_user_projection` comparison at
   [app/main.py](app/main.py#L607-L608) — **yes, it still rejects**, exactly as the question
   supposes: `provision` rebuilds contents as `content_types_for_status(status)`
   ([app/report_service.py](app/report_service.py#L285-L291)), which for previously-discovered is
   five, against the three the importer handed over.

So **D6 is still required, unchanged in code**, and the padding line round 3 wrote is byte-identical
under R2′ because `content_types_for_status(row["status"])` now always takes an official key. Only
its trigger narrows: it fires solely for a fallback finding whose document carried three sections.

But D6 is **unreachable unless D5's section-order half lands too** — step 1 above kills the document
before `source_contents` is ever built. The two stand or fall together. The surviving form of D5 is
one conditional at [app/docx_import.py](app/docx_import.py#L880-L886):

```python
        expected_sections = content_types_for_status(row["status"])
        if _clean(row["status_label"]) not in STATUS_BY_LABEL and section_order == content_types_for_status("open_new"):
            expected_sections = section_order
        if section_order != expected_sections:
            raise ReportImportError(f'"{title}" does not have the expected section structure for {row["status_label"]}.')
```

Strict for every official status, relaxed only for a fallback finding, and it replaces the
hand-written literal lists with the single owner at
[app/report_service.py](app/report_service.py#L251) (needs `content_types_for_status` added to the
import at [app/docx_import.py](app/docx_import.py#L25)).

**If the user would rather refuse a three-section unrecognised-status document** — a defensible
reading, since the refusal is about *structure*, not about the status — then D5 and D6 both die and
Group D shrinks to D3, D4, D8, D9. That is the one decision left in this group.

**Retest mode needs neither.** Its branch builds a fixed five-content list from
`source_by_type["description"]`, `["recommended_remediation"]` and `["proof_of_concept"]`
([app/docx_import.py](app/docx_import.py#L945-L953)) — all three keys are present in the
three-section and the five-section shapes alike, and it writes through `workspace.import_report` with
no projection check.

### 5. What R2′ breaks that R2 did not: nothing in the counters

**The fallback and the retest rewrite are disjoint by construction, so no finding is counted twice
and none is mislabelled.**

- The fallback always yields `open_previously_discovered`. The retest rewrite fires only on
  `row["status"] == "open_new"` ([app/docx_import.py](app/docx_import.py#L943)). A fallback finding
  therefore reaches L943 already previously-discovered, is not appended to `rewritten`, and inherits
  its status unchanged through D3's edited L953. One cause, one counter, once.
- The reverse cannot happen either: no unrecognised label can produce `open_new`, so nothing lands in
  `statuses_rewritten` that was actually a fallback.
- `dropped_resolved` is safe, and R2′ is **better** than R2 here. Round 3 §3c noted that a `None`
  status would satisfy `not in RETAINED_STATUSES` at
  [app/docx_import.py](app/docx_import.py#L922) and be silently dropped and reported as Resolved. A
  fallback status cannot be `resolved`, so after D3's `== "resolved"` inversion no unrecognised-status
  finding is ever dropped.
- `status_counts` ([app/docx_import.py](app/docx_import.py#L1158-L1160), editable only) stays
  literally true: a fallback finding's stored status *is* previously-discovered, so counting it there
  is accurate, and the `warnings` entry from §2 says where it came from. D8 is still needed, but for
  Group C — `STATUS_BY_LABEL.values()` is what picks up the fourth status; nothing is uncounted on
  R2′'s account because there is no uncountable value left.
- `retained` is unaffected: a fallback finding is retained in both modes.

**The one thing R2′ genuinely widens** is silence. R2 refused an unrecognised status loudly; R2′
accepts it and changes it. The warning in §2 is the whole of the disclosure, so it is not optional —
without it, a document whose Status cells were tampered with imports clean and reads as if the app
had always understood them.

### Revised Group D edit list

[app/docx_import.py](app/docx_import.py) only, plus one documentation line. Model untouched, client
untouched apart from Step C4.

1. **[L25](app/docx_import.py#L25)** — import `content_types_for_status` beside `RESOLVED_REMEDIATION`. *(only with D5/D6)*
2. **[L84-L88](app/docx_import.py#L84-L88)** — add `STATUS_FALLBACK` and `_status_of`.
3. **[L655](app/docx_import.py#L655)** — `"status": _status_of(cells[5]), "status_label": cells[5],`.
4. **[L778-L780](app/docx_import.py#L778-L780)** — delete the raise; warn per fallback row. *(D4)*
5. **[L880-L887](app/docx_import.py#L880-L887)** — tolerate the three-section order for a fallback finding; use `status_label` in the message. *(D5, surviving half)*
6. **[L895-L901](app/docx_import.py#L895-L901)** — normalise the detail Status cell; compare only when both labels are official. *(§3)*
7. **[L922](app/docx_import.py#L922)** — `== "resolved"`; delete `RETAINED_STATUSES` at [L59](app/docx_import.py#L59). *(D3, unchanged)*
8. **[L953](app/docx_import.py#L953)** — inherit unless `open_new`; rewrite the comment above it. *(D3, unchanged)*
9. **[L926](app/docx_import.py#L926)** — pad and re-order `source_contents` to `content_types_for_status(row["status"])`. *(D6, only with edit 5)*
10. **[L1160](app/docx_import.py#L1160)** — count over `STATUS_BY_LABEL.values()`. *(D8)*
11. **`docs/DATA_MAP.md` §7** — one line: an unrecognised Status cell imports as Open (Previously Discovered) and is named in the import warnings. `status` stays required. *(D9)*

Two existing tests change meaning:
[tests/test_docx_import.py](tests/test_docx_import.py#L1081-L1092) stops being a rejection test —
under edit 6 it imports, so it must assert the warning and the stored status instead of a 422 — and
whichever retest test pins the rewrite ([L466](tests/test_docx_import.py#L466),
[L1008](tests/test_docx_import.py#L1008)) needs a companion proving a fallback finding appears in
`warnings` and **not** in `statuses_rewritten`.

## Agreed plan

Four independent groups. **A and B ship alone.** **C and D are one commit** — before D3, a retest
import would silently eat a finding carrying the new status, so the dropdown must not open until the
importer can keep it.

**Ordering rule:** C4 is the last code step. The client must never offer a status that the server
would reject, that generation would crash on, or that an import would discard.

### Decisions taken, so nobody reopens them

1. Stored key `open_resolved_on_non_prod`; label `Open (Resolved on Non-Prod)` in the dropdown and in
   the document, as fixed text. The non-production environment name is configurable, so a report
   using `UAT` still prints `Non-Prod` — a label that followed the setting would break reading a
   finished document back into a draft.
2. The new status prints the same five sections as `Open (Previously Discovered)`, with no code.
   Every section rule is written as `== "open_new"` or `== "resolved"`, so it falls through.
3. **There is no empty status.** The requirement that needed one was withdrawn; `status: Status`
   stays required and `Status | None` is not wanted. An unrecognised status label in an imported
   document becomes `open_previously_discovered`.
4. A trailing space mid-typing stays invalid and no code compensates. The same 422 is already
   reachable with `"john."`, and stripping would fight `reconcileCanonicalObject`.
5. **Nothing is refused for carrying an unrecognised status**, including a document where only one of
   the two Status cells was hand-edited. This is the literal reading of "do not refuse it outright",
   and it is what keeps steps D3, D4 and D5 in the plan. Refusing that one document instead would
   shrink Group D to D1, D2, D6 and D7 — say so if you would rather have the smaller change.
6. No migration and no `load_path` repair for either enum change. Both widen rather than narrow, so
   every draft on disk still validates, and a repair would spend the single `draft.bak.json` level to
   change nothing.

### Group A — spaces in usernames

- [x] **Step A1 — widen the character set on both sides.** `app/report_service.py` (`USERNAME_PATTERN`,
  and drop `allow_spaces=False`) and `app/web/static/app.js` (`usernameCharacters` and the inline
  shape regex). Put the space immediately after the `[` so the trailing `-` cannot form a range.
  *Test:* `tests/test_app.py::test_setup_input_validation_rejects_unapproved_characters_and_date_order`
  — swap the negative case to `"bad/user"` and make the positive case `DOMAIN\qa user@example`, so one
  value proves the backslash and the new space together. *Invariant:* the start/end anchors stay, so a
  leading or trailing space is still invalid and `N/A` stays exempt on both sides.
- [x] **Step A2 — keep the message-drift guard alive.** `tests/test_browser.py` — swap the row in
  place, do not delete it. *Invariant:* the browser's `validationMessage` stays byte-identical to the
  server's issue string for the one field whose allowlist has no other guard.
- [x] **Step A3 — record the accepted consequence.** `docs/DATA_MAP.md` §12 — `save()`'s Setup gate is
  step-scoped, while `restoreHistory` and draft recovery call `save()` from any page, so an invalid
  Setup value can leave via undo and 422, blocking Back and Next together. *Test:* none.

### Group B — `N/A` as a bulleted list

- [x] **Step B1 — stop taking the empty early return.** `app/docx_report.py` — replace the three lines
  with `values = values or ["N/A"]`. *Test:* new in `tests/test_docx.py` — render a production-only
  finding and assert the Non-Production Location cell's second paragraph is `List Paragraph`, carries
  `w:numPr`, reads `N/A`, and that the cell contains no literal bullet character. No existing test
  asserts the empty cell at all. *Invariant:* the token paragraph is still removed so
  `_unresolved_placeholders` stays satisfied, and `_visible_value` still maps `N/A` to empty on
  import, so the round trip is unchanged.
- [x] **Step B2 — correct the template document.** `docs/DOCX_TEMPLATE.md` — say the `N/A` placeholder
  is bulleted, and that Limitations deliberately goes the other way. *Test:* none.

### Group C — the fourth status

- [x] **Step C1 — extend the enum, server side only.** `app/models.py`. *Test:* new in
  `tests/test_app.py` — PUT a finding with the new status, expect 200, and assert
  `content_types_for_status` returns the five-section set. *Invariant:* no migration; widening a
  `Literal` is permissive.
- [x] **Step C2 — teach the document the label.** `app/docx_report.py` `STATUS_LABELS`. *Test:* extend
  `tests/test_docx_import.py::test_editable_mode_keeps_all_statuses_and_printed_sections` with a
  fourth finding. *Invariant:* the summary table and the detail token read one dict, so they cannot
  disagree — which is what the importer's consistency check depends on. Closes a `KeyError` at
  generation.
- [x] **Step C3 — teach the importer the label.** `app/docx_import.py` `STATUS_BY_LABEL`. *Test:*
  covered by C2's extension. *Invariant:* the document label and the dropdown label are the same
  bytes, so a report this app generated can always be read back.
- [x] **Step C4 — open the dropdown. Last code step.** `app/web/static/app.js` `statuses` and
  `app/web/static/manager.js` `labels`. *Test:* new browser test — the option exists, selecting it
  renders five sections, and the finding chip prints the label rather than the raw key. *Invariant:*
  the client never offers a status the server, the document or the importer cannot handle.
- [x] **Step C5 — correct the stale documentation.** `docs/DOCX_TEMPLATE.md` (two places enumerate the
  statuses using the retest template), `docs/DATA_MAP.md` §7, §12 — and the Segment × Status matrix,
  which needs a fourth column behaving like previously-discovered because
  `additionalInformationFields` gates on `status !== "open_new"`. Record the status label as a
  four-copy twin with no drift guard. *Test:* none.

### Group D — import: inherit (R1), and fall back rather than refuse (R2′)

- [x] **Step D1 — R1: inherit on retest instead of renaming.** `app/docx_import.py` — invert the test
  to `== "resolved"` and delete `RETAINED_STATUSES`; make the rewrite line map only `open_new`; fix the
  comment above it, which stops being true. *Test:* `test_a_generated_report_imports_as_a_retest_draft`
  — a new-status finding is retained, keeps its status, and appears in neither `dropped` nor
  `statuses_rewritten`, while the existing `open_new` pins still hold. *Invariant:* **no open finding
  is dropped and reported as `dropped_resolved`, and no status changes without appearing in
  `statuses_rewritten`.** Extending the set instead would convert a silent drop into a silent rename.
- [x] **Step D2 — R2′: fall back to Previously Discovered at parse time, and say so.**
  `app/docx_import.py` — apply the fallback in `_summary_rows` so `row["status"]` is never unknown,
  and delete the unknown-status raise. Keep a warning naming the finding and the unrecognised text.
  *Test:* a document with an unrecognised label imports with `status: "open_previously_discovered"`
  and returns a warning naming the finding and the text. *Invariant:* the warning belongs in
  `warnings`, **not** `statuses_rewritten` — the client only renders that list in retest mode, and its
  wording would be false for a fallback. An import that silently changes a status is the thing the
  tester would otherwise be trusting blindly.
- [x] **Step D3 — R2′: stop the consistency check refusing a one-cell hand-edit.**
  `app/docx_import.py` — the comparison reads the raw detail cell, so parse-time normalisation is
  necessary but not sufficient: normalise the detail cell too, and carve out the case where both
  labels are official but different. *Test:* a document with an unrecognised label in **one** cell
  imports; a document whose two cells hold different *official* statuses is still refused.
  *Invariant:* an unrecognised value is not an inconsistency. Two official statuses that disagree
  still are, and that refusal stays.
- [x] **Step D4 — R2′: tolerate a section count that does not match the fallback.**
  `app/docx_import.py` — accept either the `open_new` or the previously-discovered section order for a
  finding that took the fallback. *Test:* a three-section document with an unrecognised label imports
  cleanly. *Invariant:* this is the **first** gate that refuses a hand-edited document — ahead of the
  consistency check and the projection check — so without it D3 buys nothing.
- [x] **Step D5 — R2′: keep the editable import from rejecting itself.** `app/docx_import.py` —
  re-order and pad `source_contents` to `content_types_for_status` before the editable branch.
  *Test:* an editable import of a three-section document with an unrecognised label returns 200 and
  saves five contents in canonical order. *Invariant:* **what the importer hands to
  `finalize_editable_import` must already be the shape `provision` will produce**, or the projection
  check refuses the import. Order matters, not just membership. Unreachable unless D4 lands.
- [x] **Step D6 — make the import summary add up.** `app/docx_import.py` — iterate
  `STATUS_BY_LABEL.values()` rather than the literal three-tuple. *Test:* an editable import counts a
  finding carrying the new status. *Invariant:* the counter becomes self-maintaining. This one is for
  Group C's sake, not R2′'s.
- [x] **Step D7 — record the new shape.** `docs/DATA_MAP.md` — one line: a retest import inherits
  every status except `open_new`, an unrecognised status label imports as Previously Discovered with a
  warning, and two cells holding different official statuses are still refused. *Test:* none.

### Withdrawn from the round 3 plan

The nullable model field, the blank dropdown option, the two `KeyError` 500s from indexing on `None`,
and the conclusion-sentence guard. All four existed only to support an empty status, and none is
reachable when every finding carries one of four known values. The counters need no protection
against double-counting: the fallback and the retest rewrite are disjoint by construction.

### Not doing

No migration or `load_path` repair for either enum change. No change to the Limitations `N/A`, which
deliberately strips its bullet and centres — after B1 the two tables differ on purpose, because
affected locations is a list of many things and Limitations is one statement.

### Known, not in this request

The `location_values` `get`-versus-`||` divergence and the Unicode-letter asymmetry in the username
message. Both real, both recorded in `DATA_MAP.md` rather than fixed here.
