# Add vulns to the library

> **Status:** planning · 2026-09-22

## Request

> add a function to add vulns

## Coordinator's framing, before round 1

The request is partly already built, and that changes what the exchange is for.

**What exists.** [app/web/templates/library_editor.html](app/web/templates/library_editor.html#L71)
has a "New entry" button; it prompts for a library ID and posts to `create_entry`
([app/library_editor.py](app/library_editor.py#L101)), which appends the entry, re-sorts by title,
validates the whole document through `LibraryDocument`, and promotes it atomically. Adding a vuln
works today.

**What is missing.** The created entry is written with `contents: []`, and the editor form has no
control for `contents` at all — it edits the ID, title, tags, likelihood, impact, severity, status,
the tester-input flag, and `proof_of_concept`, and nothing else. `contents` is the body of the
finding, and [app/main.py](app/main.py#L831) deep-copies it straight into the new `Vulnerability` on
insert. So a vuln added through the editor reaches a report with no description and no recommended
remediation.

**Measured, not assumed.** Against `resources/vuln_library.json` (schema 1.4, 51 entries):

| Fact | Value |
|---|---|
| Entries with no `contents` | **0 of 51** |
| Content types in use | `description` 51, `recommended_remediation` 51 |
| Content types never used | `previous_proof_of_concept`, `proof_of_concept`, `in_conclusion` |
| Fragment types in use | `paragraph` 102, `note` 34, `bulleted_list` 24, `table` 22 |

Every entry has exactly a description and a remediation. An entry created by the editor would be the
only one in the library without them, so this is not a missing nicety — it is the one shape the
whole library follows and the editor cannot produce.

**Therefore the change is:** let the editor author an entry's `contents`, so that adding a vuln
produces a usable one. The five `ContentType` values are at [app/models.py](app/models.py#L35).

**Size: large, scribe in.** Both rounds. Large because `contents` is copied verbatim into every
report that inserts the entry, and fragment IDs carry a uniqueness invariant enforced by
`validate_fragment_ids`. The scribe is in because those fragments are rendered into the `.docx`, so
"which fragment types may be authored here" is a document question the data layer cannot answer.

## Round 1 - Oracle: how it works today

**Answer.** `LibraryEntry.contents` is a plain `list[Content]` re-using the report's own fragment
models, so authoring it by hand means producing exactly the JSON a finding already stores — with one
extra rule the report does not have (`frag_id` unique within the entry) and one the report has that
the entry does not (`contents[].type` unique). `insert_library` deep-copies it, remints every
`frag_id`, pre-answers `content_offer_resolved`, then runs `provision`. Three of the five content
types are effectively unauthorable today: `in_conclusion` is silently discarded on insert,
`proof_of_concept` collides with the entry's own `proof_of_concept` dict, and
`previous_proof_of_concept` survives but renders nowhere on a new finding. And the insert path never
re-validates the `Report`, so an entry carrying an `image` fragment with an `evidence_id` writes a
draft that will not load again.

---

### 1. The library entry shape

`LibraryEntry` is at [app/library.py](app/library.py#L11). `contents` is declared at
[app/library.py](app/library.py#L21) as `list[Content] = Field(default_factory=list)` — the same
`Content` the report uses, imported from `models` at [app/library.py](app/library.py#L8). There is
**no library-specific content model**: what an author writes into an entry is byte-for-byte what a
finding stores.

**`Content`** ([app/models.py](app/models.py#L141)) has exactly two keys:

| Key | Type | Required |
|---|---|---|
| `type` | `ContentType` — one of `description`, `recommended_remediation`, `previous_proof_of_concept`, `proof_of_concept`, `in_conclusion` ([app/models.py](app/models.py#L35)) | yes |
| `fragments` | `list[Fragment]` | no, defaults `[]` |

`fragments: []` validates. Section membership is not checked here — see §2 for what `provision`
does with it.

**`Fragment`** ([app/models.py](app/models.py#L138)) is a discriminated union on `type` with seven
members. Every one requires `frag_id: StableId` and a literal `type`. `StableId`
([app/models.py](app/models.py#L36)) is `^[A-Za-z0-9][A-Za-z0-9_.-]*$`, 1–128 characters — so a
`frag_id` may not start with `-` or `_`, and may not contain a space, `:`, `/` or `#`. The library's
own convention is `<library_id>-<letter><n>`, e.g. `VDB-012-d1`
([resources/vuln_library.json](resources/vuln_library.json#L1919)).

The four types the coordinator measured in use, spelled out exactly:

| type | Extra keys | Floors and defaults |
|---|---|---|
| `paragraph` ([app/models.py](app/models.py#L82)) | `runs: list[Run]`, `generated: "status_conclusion" \| "resolved_remediation" \| None` | `runs` defaults `[]`; **an entry must never set `generated`** — `provision` rewrites or strips anything carrying it ([app/report_service.py](app/report_service.py#L322)) |
| `note` ([app/models.py](app/models.py#L110)) | `runs: list[Run]` | defaults `[]`. No caption, no `generated` |
| `bulleted_list` / `numbered_list` ([app/models.py](app/models.py#L93)) | `items: list[ListItem]`, `continue_numbering: bool` | **`items` has `min_length=1`** — the one hard floor a textarea author can trip. `continue_numbering` defaults `False`; no entry in the library sets it |
| `table` ([app/models.py](app/models.py#L102)) | `caption: str \| None`, `header: list[ListItem]`, `rows: list[list[ListItem]]` | all three default (`None`, `[]`, `[]`). An entirely empty table **validates** and is then blocked at generation by `generation_issues` ([app/docx_report.py](app/docx_report.py#L155)). Every table in the library today has `"caption": null` |

A **`ListItem`** ([app/models.py](app/models.py#L89)) is `{"runs": [...]}` and nothing else. `runs`
defaults `[]`, so `{"runs": []}` is a legal empty list item — which is exactly how the report editor
represents an empty line ([app/web/static/app.js](app/web/static/app.js#L3294)).

A **`Run`** ([app/models.py](app/models.py#L75)) is the atom of rich text:
`{"text": str, "bold": bool, "italic": bool, "underline": bool}`. **`text` is the only required
field on the whole fragment tree that has no default** — a run without `text` fails validation. The
three flags default `False`. There is no colour, no size, no link; the library's `_README` says so
in as many words ([resources/vuln_library.json](resources/vuln_library.json#L20)). Newlines live
*inside* `text`: `VDB-012`'s description holds `"...vulnerability.\n\n(insert additional
description for the vulnerability)"` as a single run
([resources/vuln_library.json](resources/vuln_library.json#L1923)).

The remaining three fragment types are legal in an entry but appear **zero times** in any entry's
`contents` today: `image` ([app/models.py](app/models.py#L116)), `code_block`
([app/models.py](app/models.py#L125)), `instance_title` ([app/models.py](app/models.py#L132)).
`image` is dangerous — see §3.

**`validate_fragment_ids`** ([app/library.py](app/library.py#L26)) flattens
`self.contents[*].fragments[*].frag_id` and raises `"library entry contains duplicate fragment IDs"`
if any repeats. Note precisely what it does *not* cover: it reads `self.contents` only, so a
`frag_id` in `contents` may collide with one in `proof_of_concept` without complaint.
`validate_proof_of_concept` ([app/library.py](app/library.py#L33)) checks each channel's list
**separately**, with a comment saying that is deliberate.

**What `LibraryEntry` does not validate.** Duplicate `contents[].type` is not checked — see §3.
Which fragment type may appear in which section is not checked. Whether `description` or
`recommended_remediation` exists at all is not checked; `contents: []` is a valid entry.

### 2. The insert path

`insert_library` is at [app/main.py](app/main.py#L823). In order:

1. `Vulnerability(...)` is constructed with `contents=copy.deepcopy(entry.get("contents", []))`
   ([app/main.py](app/main.py#L831)). `entry` is a plain dict — `Library.__init__` stores
   `model_dump(mode="json")` results ([app/library.py](app/library.py#L66)) — so pydantic re-parses
   the copy through `Content`/`Fragment` on construction. **A malformed entry would have been
   refused at library load, not here.**
2. `vulnerability.content_offer_resolved = {content.type: entry["library_id"] for content in
   vulnerability.contents}` ([app/main.py](app/main.py#L834)). This is the field's only Python
   writer. It is **write-only** — nothing reads it on either side; the Content-page offer keys off
   `content_offer_dismissed` and a content comparison instead
   ([app/web/static/app.js](app/web/static/app.js#L1442)). It is pre-answered so a finding that *is*
   the entry does not immediately get a banner offering to install the text it was born with. Only
   the sections actually present in `contents` get a key, so an entry with `contents: []` produces
   `{}`.
3. `assign_fresh_fragment_ids(vulnerability)` ([app/report_service.py](app/report_service.py#L574))
   overwrites **every** `frag_id` in `contents` with `f_<8 hex>`. The library's own ids never reach
   a report.
4. `provision(vulnerability)` ([app/report_service.py](app/report_service.py#L281)) — this is where
   authored content can be reshaped or lost. Detail below.
5. `sync_evidence_image_slots`, then `applicable_poc_variants`, then `apply_poc_variant` if exactly
   one variant applies ([app/main.py](app/main.py#L838)).
6. `save_if_current` ([app/main.py](app/main.py#L845)).

**What `provision` does to authored contents.** A library-inserted finding has the default status
`open_new` ([app/models.py](app/models.py#L207)), so `content_types_for_status` returns
`["description", "recommended_remediation", "proof_of_concept"]`
([app/report_service.py](app/report_service.py#L251)). Then:

- `existing = {content.type: content for content in vulnerability.contents}`
  ([app/report_service.py](app/report_service.py#L284)) — **a dict, so two contents of the same type
  silently collapse to the last one.**
- `carried` ([app/report_service.py](app/report_service.py#L289)) keeps an unprinted section only if
  `content.type != "in_conclusion"` and `content_has_work(content)`.
- `vulnerability.contents` is rebuilt as the printed types **in `content_types_for_status` order**,
  followed by the carried ones ([app/report_service.py](app/report_service.py#L290)).

Consequences, per content type an author could write:

| Authored type | What survives an insert |
|---|---|
| `description` | survives intact, order preserved within the section |
| `recommended_remediation` | survives, **unless** the fragment carries `generated: "resolved_remediation"`, which is stripped ([app/report_service.py](app/report_service.py#L322)) |
| `previous_proof_of_concept` | carried if `content_has_work`, but `open_new` does not print it, and the editor renders only printed sections ([app/web/static/app.js](app/web/static/app.js#L4198)) — so it is **invisible until the tester changes the status** |
| `proof_of_concept` | copied, then `ensure_proof_steps` prepends an empty `numbered_list` if the section has none ([app/report_service.py](app/report_service.py#L244)). If the entry also has `proof_of_concept` steps for exactly one applicable channel, `apply_poc_variant(mode="replace")` **deletes every non-image fragment** ([app/report_service.py](app/report_service.py#L595)). At insert time the finding has no targets, so `affected_channels` is empty and no variant applies — but the moment the tester picks a location the Content page offers the steps, and accepting wipes the authored section |
| `in_conclusion` | **silently discarded.** `carried` excludes it by name; `content_offer_resolved["in_conclusion"]` is written and then points at a section that no longer exists |

**A finding on disk after an insert.**
[data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json#L95)
is a `VDB-012` insert. It carries `library_ref: {library_id, source_id, inserted_at}`,
`content_offer_resolved: {"description": "VDB-012", "recommended_remediation": "VDB-012"}`, and five
`contents` in `content_types_for_status` order. Its two description fragments are word-for-word the
entry's ([resources/vuln_library.json](resources/vuln_library.json#L1914)) with `f_91113b71` /
`f_6fd06372` in place of `VDB-012-d1` / `VDB-012-d3`, and every optional key materialised —
`"bold": false`, `"generated": null` — because the server round-trips through `model_dump`.

**What breaks if `contents` is empty.** Nothing raises. `provision` sees three missing sections and
seeds them from `required_fragments` ([app/report_service.py](app/report_service.py#L291)): an empty
`paragraph` for description, an empty `paragraph` for remediation, and `numbered_list` + `image` for
proof of concept. The finding saves, loads, and opens. What fails is later and quieter:

- `generation_issues` emits `"<title>: description text is required"` and the same for remediation
  ([app/docx_report.py](app/docx_report.py#L135)), blocking DOCX output.
- The Content page offers **nothing**: `pendingLibraryOffers` filters on
  `libraryContentFor(entry, type).length` ([app/web/static/app.js](app/web/static/app.js#L1438)), so
  an entry with no contents produces no banner. The tester gets a blank finding with no route back
  to the library. This is the whole cost the coordinator's framing names, and it is silent.

**What breaks if `contents` holds an unexpected content type.** `ContentType` is a closed five-member
`Literal`, so nothing outside those five can be stored at all — a sixth value fails at library load
and `_write_validated` returns 422. Within the five, the failure modes are the silent ones tabled
above: `in_conclusion` vanishes, `proof_of_concept` is a coin-flip against the PoC offer,
`previous_proof_of_concept` is invisible. None of them error; all of them lose content.

A more serious one: `pendingLibraryOffers` hardcodes `["description", "recommended_remediation"]`
([app/web/static/app.js](app/web/static/app.js#L1434)). A title-match swap on the Findings page
applies only the non-content fields ([app/web/static/app.js](app/web/static/app.js#L2338)); content
arrives solely through those two banners. **So anything authored outside those two sections is
reachable by the insert path and by no other path.**

### 3. Invariants that constrain this change

**Fragment ID uniqueness is per entry, over `contents` only.** `validate_fragment_ids`
([app/library.py](app/library.py#L26)) is a `LibraryEntry` validator. `LibraryDocument.validate_entries`
([app/library.py](app/library.py#L51)) checks `entry_count` against `len(entries)` and `library_id`
uniqueness — **nothing checks `frag_id` across entries.** Two entries sharing `frag_id` `x1` is legal
today and would break nothing on insert, because both copy paths remint:
`assign_fresh_fragment_ids` on the server ([app/report_service.py](app/report_service.py#L574)) and
`remintFragments` in the browser ([app/web/static/app.js](app/web/static/app.js#L1343)), whose
comment states the reason. The report-wide rule is `Report.validate_references`
([app/models.py](app/models.py#L402)): `frag_id` unique across the entire report, raising
`duplicate fragment id:` — which is also the **only** reason string
`Workspace.list_legacy_reports` marks as repairable
([app/workspace.py](app/workspace.py#L147)).

**`StableId`** ([app/models.py](app/models.py#L36)) applies to `frag_id`, `library_id`, `uid`,
`report_id`, `target_id`, and the `content_offer_*` values. For an authoring form the practical
constraints are: first character alphanumeric, then alphanumerics plus `_ . -`, 1–128 characters. A
generated id must be produced somewhere — the editor currently mints `f"{library_id}-{variant}-poc"`
for PoC steps ([app/library_editor.py](app/library_editor.py#L30)), which is the pattern to follow.

**Duplicate content types are a real hole.** `Report.validate_references` raises
`duplicate content type for finding` ([app/models.py](app/models.py#L396)), but `LibraryEntry` has no
such check, and `provision`'s `existing` dict ([app/report_service.py](app/report_service.py#L284))
collapses a duplicate to the last one before the report is ever validated. So an entry with two
`description` sections **does not error anywhere** — it loses the first one silently on every insert.
If the editor can produce a list of sections, it must enforce uniqueness itself or the entry model
must gain the check.

**The insert path never re-validates the `Report`.** `insert_library` appends to
`report.vulnerabilities` ([app/main.py](app/main.py#L837)) — a plain list append, which runs no
validator — and `Workspace._save_unlocked` writes `report.model_dump(...)` directly
([app/workspace.py](app/workspace.py#L368)) without re-validating. So an entry carrying an
`ImageFragment` with a non-null `evidence_id` copies a reference to evidence the report does not
have, writes it to disk, and the draft then fails `Report.model_validate` on the next load
([app/models.py](app/models.py#L407), `"image fragment references missing evidence"`). That reason
is **not** repairable ([app/workspace.py](app/workspace.py#L147)), so the report is bricked short of
hand-editing JSON. No entry has an image fragment today; nothing prevents one.

**Ordering.** The order of `contents` in an entry is irrelevant — `provision` rebuilds the list in
`content_types_for_status` order on every insert and every PUT
([app/report_service.py](app/report_service.py#L290), twinned at
[app/web/static/app.js](app/web/static/app.js#L1102)). Fragment order **inside** a section is
preserved verbatim and is the author's to decide. Entries are themselves sorted by
`title.casefold()` on create ([app/library_editor.py](app/library_editor.py#L125)) but not on save,
so editing a title leaves the list unsorted until the next create.

### 4. The existing drafts on disk

Seven `draft.json` files under `data/apps/`. **Four carry findings with a non-null `library_ref`**:

| Draft | Library-sourced findings |
|---|---|
| [Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd](data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json#L89) | 1 (`VDB-047`) |
| [Prompt_Reference/2026-09_Annual_Pentest_5395baea9d23](data/apps/Prompt_Reference/2026-09_Annual_Pentest_5395baea9d23/draft.json#L81) | 2 |
| [Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json#L95) | 14 |
| Northstar_Banking/2026-09_Report_84b9ebe1bbdd, Fragment_Coverage_Demo, Image_Error_Probe | 0 — `"library_ref": null` |

**Their contents relative to the entry.** `VDB-012` in the QA draft
([draft.json](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json#L113))
holds both description paragraphs with the entry's exact run text and new `f_` ids; the remediation
paragraph likewise. The differences are entirely mechanical: reminted `frag_id`s, optional keys
materialised (`bold`/`italic`/`underline`/`generated`), and the three sections `provision` added that
the entry never had. Where a tester has since edited, `content_offer_dismissed` records a
fingerprint — `{"description": "620-c8fe841a", ...}` — and that is how the banner stays quiet.

`VDB-047` in the Northstar draft ([draft.json](data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json#L96))
shows the other half: `content_offer_resolved` holds both sections but the remediation paragraph has
`"runs": []` — the tester emptied it. Nothing repairs that; it is simply an incomplete finding.

**What disk constrains.** Nothing forbids a new entry shape: `library_ref` stores only
`library_id`, `source_id`, `inserted_at` ([app/models.py](app/models.py#L194)), never a copy of the
entry's contents, and no draft references a `frag_id` from the library. What disk *does* constrain is
`library_id`: 17 findings across four drafts point at ids in `resources/vuln_library.json`, and
`libraryEntryFor` ([app/web/static/app.js](app/web/static/app.js#L1256)) returns `null` when the id
is gone — silently disabling every offer for that finding. The editor already treats `library_id` as
immutable for this reason ([app/library_editor.py](app/library_editor.py#L76)). `source_id` is
carried through unchanged and is `int | str` ([app/library.py](app/library.py#L13)); `create_entry`
defaults it to the `library_id` when the payload omits it
([app/library_editor.py](app/library_editor.py#L114)).

One thing worth naming: **the entire library, `contents` and all, is serialised into a `data-library`
attribute on every page** ([app/main.py](app/main.py#L719), [app/main.py](app/main.py#L728),
[app/main.py](app/main.py#L741); read at
[app/web/static/app.js](app/web/static/app.js#L117)). `resources/vuln_library.json` is ~5,000 lines
for 51 entries. Whatever authoring adds to `contents` is paid on every Setup, Findings and Content
page load, in an HTML attribute.

### 5. Both-sides rules this change touches

Three copy sites, not two. The library editor page is the third, and it is the one that forgets —
its own comment says so ([app/web/templates/library_editor.html](app/web/templates/library_editor.html#L80)).

| Rule | Python | JavaScript (`app.js`) | Library editor page |
|---|---|---|---|
| which fragment types a section may hold | **none — no Python owner at all** | `allowed` ([app/web/static/app.js](app/web/static/app.js#L121)) | would become a **second** copy |
| the default shape of a new fragment | the `required_fragments` arms in `provision` ([app/report_service.py](app/report_service.py#L291)) — partial, only paragraph/numbered_list/image | `newFragment` ([app/web/static/app.js](app/web/static/app.js#L2801)) — complete, all seven types | would become a **third** copy |
| which content types exist | `ContentType` ([app/models.py](app/models.py#L35)) | `contentNames` ([app/web/static/app.js](app/web/static/app.js#L120)) and `contentTypesForStatus` ([app/web/static/app.js](app/web/static/app.js#L1082)) | absent today; a section picker adds one |
| canonical app-type order | `CHANNELS` ([app/models.py](app/models.py#L15)) | `CHANNELS` in `app.js` | `variants` ([app/web/templates/library_editor.html](app/web/templates/library_editor.html#L82)) — already the known third copy |
| a list fragment always has ≥ 1 item | `ListFragment.items` `min_length=1` ([app/models.py](app/models.py#L96)) | the `lines.length ? lines : [""]` fallback in the list textarea ([app/web/static/app.js](app/web/static/app.js#L3294)) | `_steps_to_fragments` returns `[]` rather than an itemless fragment ([app/library_editor.py](app/library_editor.py#L30)) |
| placeholder text detection | `PLACEHOLDER_TEXT` ([app/docx_report.py](app/docx_report.py#L67)) | `placeholderPattern` ([app/web/static/app.js](app/web/static/app.js#L3486)) | none — but an author writing `(insert … )` arms both, which is how `requires_tester_input` entries work by design |

**The sharpest of these is `allowed`.** It exists **only** in JavaScript; `Content.fragments` accepts
any fragment type and `Report.validate_references` never looks at section membership. `allowed`
governs the add-fragment `<select>` alone ([app/web/static/app.js](app/web/static/app.js#L4100)) —
`renderFragment` ([app/web/static/app.js](app/web/static/app.js#L3145)) switches on the fragment's
own type and renders anything. Note the asymmetries an author would be exposed to: `table` is allowed
in `description`/`recommended_remediation` but **not** in either proof-of-concept section, and
`paragraph` is allowed in `description`/`recommended_remediation`/`in_conclusion` but **not** in
either proof-of-concept section. `CONVERTIBLE_SECTIONS` ([app/web/static/app.js](app/web/static/app.js#L1315))
deliberately contradicts `allowed` for conversion, with a comment explaining why. Any fragment-type
picker in the library editor is a second statement of a rule that currently has exactly one home and
no drift guard.

**Testing.** `tests/test_app.py::test_the_library_editor_offers_every_channel_the_model_knows`
([tests/test_app.py](tests/test_app.py#L559)) is the **only** test that reads
`library_editor.html`, and it checks the channel list. No test drives the editor's routes; no browser
test loads the page. Whatever this change adds to the editor starts uncovered.

### 6. The editor's own safety story

`_write_validated` ([app/library_editor.py](app/library_editor.py#L131)) is three gates:

1. `LibraryDocument.model_validate(document)` on the in-memory dict — catches every model rule
   above, returns 422 with the pydantic message.
2. Write to `tempfile.mkstemp` in the **same directory**, then `Library(temporary)` — the real boot
   constructor ([app/library.py](app/library.py#L63)) run against the real bytes, so a file that
   would not start the app never replaces a good one.
3. `os.replace(temporary, library_path)` — atomic on the same filesystem.

**Is that sufficient for larger writes?** For *validity*, yes: gate 2 is stronger than what
`atomic_write_json` does for drafts, because it re-reads and re-parses the actual bytes. Three gaps
matter more as writes get bigger:

- **There is no backup.** `storage.atomic_write_json` copies the current file to `<name>.bak.json`
  before replacing it ([docs/DATA_MAP.md](docs/DATA_MAP.md#L69)); `_write_validated` does not.
  A *valid but wrong* write — an author who clears a description, or whose browser posts a stale
  `contents` — is unrecoverable from inside the app. Git is the only backup, and
  `resources/vuln_library.json` is the tracked copy that `package_release.py` ships.
- **The whole document is rewritten every time.** `save_entry` reads the file, mutates one entry,
  and writes all 51 back ([app/library_editor.py](app/library_editor.py#L67)). There is no
  read-modify-write lock and no revision token — nothing like the `saved_at` guard reports have.
  Two editor tabs open on different entries will silently overwrite each other, last write wins.
  That is survivable for six scalar fields and much less so for a body of prose.
- **A partial-field PUT is the current contract.** `save_entry` applies only keys present in the
  payload, and `contents` is not among them — it appears in `library_editor.py` exactly once, at
  [app/library_editor.py](app/library_editor.py#L122), writing `[]` on create. The GET payload
  ([app/library_editor.py](app/library_editor.py#L47)) also omits `contents`, so the page cannot
  currently even *see* them. Both ends need the key added, and round-tripping prose through the
  page is what makes the missing lock start to bite.
  currently even *see* them. Both ends need the key added, and round-tripping prose through the
  page is what makes the missing lock start to bite.

**Loaded at import, and what a bad write costs.** `library = Library.load_or_empty(configured_library)`
runs at module scope ([app/main.py](app/main.py#L42)), before any route exists. `load_or_empty`
([app/library.py](app/library.py#L71)) swallows `OSError` and `ValueError` and serves an **empty**
library with `load_error` set, so the app still boots — but every entry disappears, every finding's
`libraryEntryFor` returns `null`, and every offer goes quiet with no message on the report pages.
`_rebind_library` ([app/main.py](app/main.py#L900)) uses the same forgiving constructor, so a bad
write that somehow slipped past the gates would empty the running app's library **without an error
to the browser** — the PUT would return 200. The editor is registered only when
`VULNREPORT_LIBRARY_EDITOR` is set and the file exists ([app/main.py](app/main.py#L897)), and
`library_editor.py` is untracked by design ([app/library_editor.py](app/library_editor.py#L1)), which
also means anything built here ships to nobody unless that decision changes.

---

### Invariants in play

- **`frag_id` unique within a library entry's `contents`** ([app/library.py](app/library.py#L26)).
  Violated: the entry fails validation, `_write_validated` returns 422, the library is unchanged.
- **`frag_id` unique across a whole report** ([app/models.py](app/models.py#L402)). Cannot be
  violated from the library because both copy paths remint; if it ever were, the draft demotes to
  the manager's legacy list and is the one reason marked repairable.
- **`contents[].type` unique within a finding** ([app/models.py](app/models.py#L396)). Not mirrored
  on `LibraryEntry`; `provision` collapses the duplicate before validation ever sees it, so the
  failure is silent loss rather than an error.
- **`ListFragment.items` `min_length=1`** ([app/models.py](app/models.py#L96)). Violated: 422 at
  library write. This is the floor a naive "one item per line" textarea trips on an empty box.
- **`Run.text` required** ([app/models.py](app/models.py#L76)). Violated: 422 at library write.
- **`StableId` pattern on `frag_id`** ([app/models.py](app/models.py#L36)). Violated: 422 at library
  write.
- **Every referenced `evidence_id` exists in `report.evidence`** ([app/models.py](app/models.py#L407)).
  Violated by an `image` fragment authored into an entry: the insert **succeeds and persists**, and
  the draft is unloadable and not repairable from then on.
- **`generated` is the app's marker, not an author's** ([app/report_service.py](app/report_service.py#L322)).
  Violated: `provision` strips or rewrites the fragment on the first save.

### Both-sides warning

Four pairs are in scope, and the library editor page is a third site for two of them:

- **`allowed`** — one home only, [app/web/static/app.js](app/web/static/app.js#L121). Restating it
  in `library_editor.html` creates a pair with no Python referee and no drift guard.
- **`newFragment`** — [app/web/static/app.js](app/web/static/app.js#L2801) against the partial
  `required_fragments` arms in [app/report_service.py](app/report_service.py#L291). A library-editor
  fragment builder is a third.
- **`provision` / `content_types_for_status`** — [app/report_service.py](app/report_service.py#L251)
  and [app/web/static/app.js](app/web/static/app.js#L1082). Untouched by authoring `contents`, but
  they are what decides whether an authored section survives, so any decision about which sections
  are authorable is a decision about these two together.
- **`ensure_proof_steps` / `apply_poc_variant`** — [app/report_service.py](app/report_service.py#L244)
  and [app/report_service.py](app/report_service.py#L595), against
  [app/web/static/app.js](app/web/static/app.js#L1309) and
  [app/web/static/app.js](app/web/static/app.js#L1360) — are what would fight an authored
  `proof_of_concept` section.

### Map drift

Two corrections made to [docs/DATA_MAP.md](docs/DATA_MAP.md#L220), §7 *"Proof-of-concept steps from
the library"*, and its "Latest verification" line bumped to 2026-09-22.

1. It read *"A `LibraryEntry` may carry `proof_of_concept`, keyed by `Channel` (`web`, `api`,
   `mobile`)"*. `Channel` has been a four-member `Literal` including `thick_client`
   ([app/models.py](app/models.py#L12)) and the editor has shipped a `poc_thick_client` textarea
   ([app/web/templates/library_editor.html](app/web/templates/library_editor.html#L67)) since before
   this exchange. Corrected to all four, and the measurement extended: **no entry defines steps for
   `mobile` or `thick_client`**, so both are as empty as `mobile` alone was recorded to be.
2. The map had **nothing at all** on `LibraryEntry.contents` — the one field this change is about.
   §7 now records that it is `list[Content]` imported straight from `models` rather than a
   library-specific schema, that `validate_fragment_ids` scopes uniqueness to one entry's `contents`
   and neither across entries nor against its own `proof_of_concept`, that both copy paths remint so
   none of it reaches a report, and the two rules `LibraryEntry` omits that `Report` enforces
   (duplicate content types, which `provision` silently collapses; and section/fragment membership,
   which has no Python owner).

The editor's own write path — `_write_validated`, the missing backup, the whole-document
last-write-wins rewrite — is still undocumented. That belongs in the map when this change ships, not
before, because its shape is exactly what round 2 is for.

## Round 1 - Scribe: the document side

**Answer.** All four measured fragment types render, and all four are authorable from a textarea —
but only `paragraph` and `note` are *safely* authorable from a plain one, because a newline means
something different in each of the four and `table` needs a grid a single textarea cannot express.
Two hard aborts are reachable by ordinary typed text and neither is a validation error the author
will ever see in the editor: **any `{{…}}` pair anywhere in a body kills generation at the very last
step**, and so does the bare substring **`-vuln`** — which a URL or a CVE-ish identifier can carry
innocently. The document does not care about the order of `contents`, and it agrees with the oracle
that only `description`, `recommended_remediation` and `proof_of_concept` are reachable for a new
finding: the other two anchors do not exist in `new_finding.docx`. The round trip is lossy in one
way that matters: **a multi-line `note` comes back as N separate notes and regenerates as
"Note: … / Note: … / Note: …"**.

---

### 1. What the document can render, and what each type requires

`_render_component_fragment` ([app/docx_report.py](app/docx_report.py#L951)) is the single switch.
Every branch clones a small Word file from `resources/fragments/` and splices the author's runs into
its one token — `FRAGMENT_COMPONENT_FILES` ([app/docx_report.py](app/docx_report.py#L77)) is the
whole map:

| Fragment | Component file | Token | Arm | Needs to be present |
|---|---|---|---|---|
| `paragraph` | `paragraph_fragment.docx` | `{{paragraph-fragment}}` | [L963](app/docx_report.py#L963) | nothing; `runs: []` renders an empty paragraph |
| `note` | `note_fragment.docx` | `{{note-fragment}}` | [L965](app/docx_report.py#L965) | nothing; the `Note: ` lead-in is the component's, never the author's |
| `bulleted_list` | `bulleted_fragment.docx` | `{{bullet-list-fragment}}` | [L967](app/docx_report.py#L967) | ≥1 item (model floor), and the component supplies the numbering the clone is remapped onto |
| `numbered_list` | `numbered_fragment.docx` | `{{numbered-list-fragment}}` | [L967](app/docx_report.py#L967) | as above, plus `continue_numbering` only means anything inside one section |
| `table` | `table_fragment.docx` | `{{table-header-cell}}`, `{{table-body-cell}}` | [L1013](app/docx_report.py#L1013) → [`_render_table_component`](app/docx_report.py#L1228) | **a rectangular grid** — see below |
| `code_block` | `code_fragment.docx` | `{{code-fragment}}` | [L988](app/docx_report.py#L988) | a `caption` renders *before* it through `caption_fragment.docx` |
| `instance_title` | `title_fragment.docx` | `{{instance-fragment}}` | [L1002](app/docx_report.py#L1002) | the app renumbers it per section and rewrites the label; the author's text is only the suffix ([app/docx_report.py](app/docx_report.py#L837)) |
| `image` | `image_fragment.docx` | — | [L1015](app/docx_report.py#L1015) | **an `evidence_id` resolving inside the report**, or generation raises ([app/docx_report.py](app/docx_report.py#L1197)) |

Non-image fragments always render: `fragment_applies` ([app/report_service.py](app/report_service.py#L418))
only filters on an `environment` attribute, which only `ImageFragment` has.

**Safe from a plain textarea:** `paragraph` and `note`. Both are "runs in, paragraph out", both treat
a newline sensibly (a new paragraph), and neither has a structural floor. `bulleted_list` is safe if
the textarea is line-per-item *and* refuses to emit a fragment for an empty box — `items` has
`min_length=1` ([app/models.py](app/models.py#L96)) and an empty textarea is the obvious way to trip
it.

**Not safe from a plain textarea:** `table`, and `image` is not authorable at all.

**`table` specifically.** `_render_table_component` ([app/docx_report.py](app/docx_report.py#L1228))
takes the column count as `max(len(header), *(len(row) for row in rows), 1)` and then *rebuilds the
grid* — if that count differs from the prototype's, it throws the component's authored column widths
away and divides the table width equally ([app/docx_report.py](app/docx_report.py#L1287),
[app/docx_report.py](app/docx_report.py#L1292)). Three consequences for an authoring form:

- **Ragged rows render, they do not fail.** A row shorter than the header gets empty cells
  (`runs = source_row[column_index].runs if column_index < len(source_row) else []`,
  [app/docx_report.py](app/docx_report.py#L1272)), and `generation_issues` never notices because it
  only walks cells that exist ([app/docx_report.py](app/docx_report.py#L153)). The tester gets blank
  cells in a delivered report with no warning. **A pipe-delimited textarea must pad or reject;
  nothing downstream will.**
- **`header: []` is legal and renders rows only** ([app/docx_report.py](app/docx_report.py#L1252)) —
  but it does not survive the round trip (§4).
- **Every cell must have text.** `generation_issues` ([app/docx_report.py](app/docx_report.py#L152))
  emits `"<title>: every table cell is required"` for an empty cell *and* for a table with no cells
  at all. So an empty table validates at the library, inserts fine, and blocks the report.

**`note` specifically.** It carries no structure of its own. The one thing worth knowing is that the
`Note: ` prefix lives in `note_fragment.docx`, and the renderer strips it from every continuation
line ([app/docx_report.py](app/docx_report.py#L1101)) so a multi-line note prints the prefix once.
An author who types `Note: ` themselves gets `Note: Note: …`. Nothing detects that.

**`table` captions are new territory.** Every table in the library today has `"caption": null`, and
the caption path — `_render_caption_component` ([app/docx_report.py](app/docx_report.py#L1171)),
which uses the `FiguresandTables` style — is exercised in reports only by code-block captions.
`add_native_image_captions` ([app/docx_captions.py](app/docx_captions.py#L199)) requires the caption
paragraph to sit **directly under an image** ([app/docx_captions.py](app/docx_captions.py#L407)), so
a table caption is *not* converted into a `SEQ Figure` field and does not consume a figure number.
**Whether it nevertheless lands in the table of figures depends on how the TOF field in each
`MAIN*.docx` is written — by style or by `SEQ` identifier — and I cannot read that from this
repository.** If the editor is going to expose a table caption, settle that in Word first.

### 2. What token replacement does to authored text

The coordinator's recollection is **half right, and the half that is wrong is the more useful half.**

**Newlines are not flattened on this path; they are honoured, differently per type.** The shared
helper is `_set_run_text` ([app/docx_components.py](app/docx_components.py#L548)), reached from
`replace_component_token_runs` → `_replace_pattern_with_runs`
([app/docx_components.py](app/docx_components.py#L478)). It normalises `\r\n` and `\r` to `\n` and
writes a real `w:br` per newline. The flattening the coordinator remembers belongs to the *string*
path, `replace_component_token` → `replace_pattern_across_text_nodes`
([app/docx_components.py](app/docx_components.py#L390)), which drops the raw character into a `w:t`
where Word reads it as whitespace. That path handles `{{finding_title}}`, `{{vuln_severity}}`,
`{{vuln_id}}` and `{{status}}` ([app/docx_report.py](app/docx_report.py#L766)) — engagement and
finding scalars, **not fragment bodies**. The comment at
[app/docx_report.py](app/docx_report.py#L774) names the distinction explicitly.

So, per type, one newline typed into a textarea becomes:

| Type | A `\n` becomes |
|---|---|
| `paragraph` | **a new paragraph.** `_render_multiline_text_component` ([app/docx_report.py](app/docx_report.py#L1080)) splits the runs at newlines ([app/docx_report.py](app/docx_report.py#L1051)) and deep-copies the component paragraph per line, so spacing and style are right and no `w:br` survives. Run formatting carries across the split. Proved by `test_multiline_text_fragments_render_as_paragraphs_not_manual_breaks` ([tests/test_docx.py](tests/test_docx.py#L999)) |
| `note` | a new paragraph, with `Note: ` removed from every continuation ([app/docx_report.py](app/docx_report.py#L1101)) |
| a list item | a **soft line break inside that bullet**, via `w:br`, and the paragraph gets `keepLines` so Word will not split it across a page ([app/docx_report.py](app/docx_report.py#L1040)) |
| a table cell | a soft line break inside the cell |
| `code_block` | a soft line break inside the one code paragraph |

A blank line (`\n\n`) in a `paragraph` renders an empty paragraph between two full ones — which is
what `VDB-012`'s description relies on. `_trim_trailing_empty_paragraphs`
([app/docx_report.py](app/docx_report.py#L1116)) removes only *trailing* ones, so interior blank
lines survive the render. They do not survive the round trip (§4), and on Windows
`_remove_page_leading_blank_paragraphs` ([app/docx_captions.py](app/docx_captions.py#L174)) deletes
any that Word ends up placing alone at the top of a page.

**Braces: confirmed, and worse than "aborts generation".** `_unresolved_placeholders`
([app/docx_report.py](app/docx_report.py#L1493)) runs as the **last** step of
`render_report_docx`, after the findings body is already spliced in, and scans the finished
document's visible text for `\{\{.*?\}\}`. A proof-of-concept body containing `{{7*7}}` produces:

```
ReportGenerationError: Unresolved template placeholders: {{7*7}}
```

The message names the template, not the finding, not the section, not the library entry. There is no
earlier guard — `generation_issues` says nothing about braces, and the library editor's
`LibraryDocument` validation cannot, because braces are legal text everywhere else. A payload
library is precisely where `{{7*7}}`, `${7*7}` and `{{config}}` live. `${…}` and `{7*7}` are
harmless; only a `{{` with a later `}}` on the same paragraph matters (the join is per-root and
`.` does not cross the newline `_element_text` inserts between roots).

**`-vuln` and friends: a second, unsignposted abort.** The same function unions in
`UNRESOLVED_MARKERS` ([app/docx_report.py](app/docx_report.py#L58)) as **casefolded substrings** of
the whole document:

```
"-vuln", "-affected-location", "-fragments-here", "-step-1-here",
"-step-2-here", "-images-and-caption-here", "brief-explanation-here"
```

These exist to catch a component anchor that never got replaced. They do not distinguish an anchor
from a tester's prose. `https://target.example/api-vuln`, `sqli-vuln`, a Burp issue name — anything
carrying the literal `-vuln` — fails the report with `Unresolved template placeholders: -vuln`. This
is not hypothetical text for a vulnerability library.

**Other characters.**

- **Backslashes, quotes, `<`, `>`, `&`, `%`:** nothing special. They are set as XML text and escaped
  by lxml. No token syntax uses them.
- **Leading or trailing spaces:** preserved — `_preserve_text_spaces`
  ([app/docx_components.py](app/docx_components.py#L647)) sets `xml:space="preserve"` when needed.
- **Tabs:** pass through into `w:t` as literal tabs. The renderer never writes a `w:tab`, though the
  importer reads one back as `\t` ([app/docx_import.py](app/docx_import.py#L204)).
- **ASCII control characters** (`\x00`–`\x08`, `\x0b`, `\x0c`, `\x0e`–`\x1f`, e.g. the `ESC` in an
  ANSI-coloured terminal transcript): there is **no sanitiser anywhere on this path**. `Run.text` is
  a bare `str` ([app/models.py](app/models.py#L76)), `LibraryEntry` re-uses it unchanged, and
  `_set_run_text` assigns it straight to an lxml text node. lxml refuses XML-1.0-invalid characters
  on assignment, so the expected outcome is a raw `ValueError` — **not** a `ReportGenerationError`,
  so it would surface as a 500 rather than a generation issue. **I have not executed this**; I can
  only say the code has no guard and the exception type would not be the handled one. If the plan
  accepts pasted terminal output, this is worth one throwaway check before shipping.

### 3. Does the document constrain the content types?

**It agrees with the oracle, and it adds a reason rather than a new rule.**

`_render_finding_component` ([app/docx_report.py](app/docx_report.py#L752)) picks
`new_finding.docx` for `open_new` and `retest_finding.docx` for everything else, then fills anchors
([app/docx_report.py](app/docx_report.py#L786)):

| Anchor | Content type | Present for `open_new`? |
|---|---|---|
| `{{description-fragments-here}}` | `description` | yes |
| `{{recommended-remediation-fragments-here}}` | `recommended_remediation` | yes |
| `{{poc-fragments-here}}` | `proof_of_concept` | yes |
| `{{prev-poc-fragments-here}}` | `previous_proof_of_concept` | **no** — only added when `status != "open_new"` |
| `{{conclusion-fragments-here}}` | `in_conclusion` | **no** |

A library insert produces an `open_new` finding, so `new_finding.docx` has **no anchor at all** for
the other two — that is why the oracle's "invisible until the tester changes the status" is also
true of the document, and it is structural rather than incidental. `_component_anchor_index`
([app/docx_report.py](app/docx_report.py#L1343)) demands **exactly one** matching paragraph and
raises otherwise, so the two absent anchors are not merely unused; they cannot be present in
`new_finding.docx`.

**Order of `contents` is irrelevant to the document.** Sections render in the order the anchors sit
in the Word component, which is the component author's decision, not the data's. Fragment order
*within* a section is preserved exactly.

**An absent content type does not blank the section — it prints `N/A`.**
`_render_component_content` ([app/docx_report.py](app/docx_report.py#L880)) takes `content=None` and
renders a paragraph reading `N/A`. In practice `generation_issues` blocks first (`"<title>:
description needs at least one fragment"`, [app/docx_report.py](app/docx_report.py#L125), and
`"<title>: description text is required"`, [app/docx_report.py](app/docx_report.py#L134)) — but with
`allow_incomplete=True`, which is how the app renders a draft preview, an entry authored without a
description silently ships a finding whose Description reads `N/A`. That is the visible cost of
`contents: []`, and it is worth quoting to whoever asks why this change is needed.

**One constraint the document adds that nothing else states:** `PLACEHOLDER_TEXT`
([app/docx_report.py](app/docx_report.py#L67)) matches `(insert …)` and `insert <technology|version|
eol date|cves|latest> … here` anywhere in a fragment's text, and `generation_issues`
([app/docx_report.py](app/docx_report.py#L156)) turns it into `"<title>: replace placeholder text in
<section>"`. This is the mechanism `requires_tester_input` entries run on, so it is a *feature* for
an authoring form — but it means an author who writes an ordinary sentence containing a parenthetical
that begins with the word "insert" has, without knowing it, made every report using that entry
un-generatable until the tester edits it.

### 4. The import round trip

`_build_fragments` ([app/docx_import.py](app/docx_import.py#L340)) reconstructs fragments from
paragraph *formatting*, via `classify_paragraph` ([app/docx_import.py](app/docx_import.py#L175)),
which tests in this order: image → `FiguresandTables` style → `w:numPr` → code shading `F1F4F8` →
justified alignment → `Instance n:` text → bold paragraph mark → italic paragraph mark → paragraph.
Nothing about the library survives; every `frag_id` and `evidence_id` is reminted
([app/docx_import.py](app/docx_import.py#L84)).

| Authored | Comes back as | Lossy? |
|---|---|---|
| single-line `paragraph` | `paragraph`, runs and bold/italic/underline intact | no |
| **multi-line `paragraph`** | **N separate `paragraph` fragments**, and the blank separator lines are dropped (`if not text.strip(): continue`, [app/docx_import.py](app/docx_import.py#L435)) | **yes** — one fragment becomes many, and re-generating loses the blank-line spacing |
| single-line `note` | `note`, with `Note: ` stripped back off ([app/docx_import.py](app/docx_import.py#L242)). Covered by `test_the_note_prefix_is_not_kept_as_content` ([tests/test_docx_import.py](tests/test_docx_import.py#L966)) and `test_note_runs_and_numbered_list_boundaries_survive` ([tests/test_docx_import.py](tests/test_docx_import.py#L852)) | no |
| **multi-line `note`** | **N separate `note` fragments.** The continuation paragraphs are deep copies of the note component, so they keep its italic paragraph mark and classify as notes; they just lack the prefix. Regenerating prints `Note: ` on **every** one | **yes, and visibly** |
| `bulleted_list` | `bulleted_list`; consecutive items sharing a `numId` re-merge into one fragment ([app/docx_import.py](app/docx_import.py#L424)). A `\n` inside an item round trips, because `runs_of` reads `w:br` back as `\n` ([app/docx_import.py](app/docx_import.py#L204)) | no |
| `table` with a header | `table`; `_table_fragment` ([app/docx_import.py](app/docx_import.py#L320)) always takes row 0 as the header | no |
| **`table` with `header: []`** | `table` **with the first data row promoted to the header** | **yes** — the header/body distinction is a render-time decision the document does not record |
| **`table` with a header and no rows** | `table` with a synthetic all-empty body row (`rows[1:] or [[…]]`, [app/docx_import.py](app/docx_import.py#L327)) | **yes** — and that empty row then trips `"every table cell is required"` on the next generation |
| `table` caption | recovered only from a preceding `FiguresandTables` paragraph; `null` stays `null` | no, for today's entries |
| `code_block` | `code_block`, identified purely by the `F1F4F8` shading fill | no |
| `instance_title` | `instance_title` with `Instance n:` stripped | no |

Two further notes. A **bold** paragraph mark classifies as `instance_title`, and an **italic** one as
`note` — but only the *paragraph mark*, deliberately, so run-level emphasis the author applies inside
a paragraph does not reclassify it ([app/docx_import.py](app/docx_import.py#L164)). And the sections
themselves are matched on exact printed heading text, `SECTION_HEADINGS`
([app/docx_import.py](app/docx_import.py#L40)) — so content only comes back into the section the
document printed it under.

**The one that matters for this plan:** if the editor offers a single textarea per fragment and
accepts newlines, then `paragraph` and `note` both become *fragment multipliers* on the round trip,
and `note` additionally gains a repeated `Note: ` lead-in on the next render. If a multi-line body
is wanted, the honest options are (a) accept the split and say so, or (b) make the textarea emit one
fragment per line at authoring time so the stored shape already matches what comes back.

### 5. Everything that aborts generation, reachable by typed text

`ReportGenerationError` is caught and surfaced as a 422; anything else is a 500. Ordered by how
likely a human is to hit it:

| # | Trigger | Where | Result |
|---|---|---|---|
| 1 | any `{{…}}` pair in any body text | [app/docx_report.py](app/docx_report.py#L206), via [L1493](app/docx_report.py#L1493) | `Unresolved template placeholders: {{…}}` — **422, message does not name the finding** |
| 2 | the substring `-vuln` (or `-affected-location`, `-fragments-here`, `-step-1-here`, `-step-2-here`, `-images-and-caption-here`, `brief-explanation-here`) anywhere in the document text | [app/docx_report.py](app/docx_report.py#L58) | as above |
| 3 | a `(insert …)` parenthetical, or `insert version … here` | [app/docx_report.py](app/docx_report.py#L156) | `replace placeholder text in <section>` — a blocking issue, by design |
| 4 | any empty table cell, or a table with no cells | [app/docx_report.py](app/docx_report.py#L152) | `every table cell is required` |
| 5 | a `paragraph`/`note` whose runs are all whitespace | [app/docx_report.py](app/docx_report.py#L134) | `<section> text is required` |
| 6 | a list item whose runs are all whitespace | [app/docx_report.py](app/docx_report.py#L136) | `<section> list item text is required` |
| 7 | a `code_block` with whitespace-only text | [app/docx_report.py](app/docx_report.py#L150) | `code_block text is required` |
| 8 | a body paragraph whose **entire** text is one of the five anchor tokens, e.g. a description consisting solely of `{{poc-fragments-here}}` | [app/docx_report.py](app/docx_report.py#L1343) | `Expected exactly one {{poc-fragments-here}} component anchor; found 2` — contrived, but it is a `fullmatch` and it does fire |
| 9 | an XML-1.0-invalid control character (`ESC`, `NUL`, …) pasted from a terminal transcript | [app/docx_components.py](app/docx_components.py#L548) | expected `ValueError` from lxml → **500, not 422**. *Unverified — see §2* |
| 10 | an `image` fragment authored into an entry | [app/docx_report.py](app/docx_report.py#L1197) | `Missing evidence for image fragment …` — but per the oracle the draft is already unloadable before this is reached |

Items 1, 2 and 9 are the ones worth acting on, because they are the only three that a tester cannot
diagnose from the message and that no editor-side validation currently catches. Items 3–7 are
`generation_issues` entries: they name the finding and the section, they appear in the UI's
completeness list, and they are the system working.

### The Word pass, and what cannot be answered here

`update_docx_bytes_with_word` ([app/docx_captions.py](app/docx_captions.py#L101)) is called
unconditionally from the generate route ([app/main.py](app/main.py#L527)) and needs `pywin32` plus
an installed Word ([app/docx_captions.py](app/docx_captions.py#L55)). It repaginates, updates every
story's fields, updates and then re-paginates the tables of contents and figures, and deletes blank
paragraphs stranded at the top of a page ([app/docx_captions.py](app/docx_captions.py#L174)).

Nothing in it is fragment-type-specific, so I do not expect authored `contents` to interact with it —
with one caveat I cannot settle from this repository: **whether a `FiguresandTables`-styled table
caption is collected by the table of figures**, and **where Word chooses to break a page around a
long authored table or a multi-paragraph note**. `_keep_tables_with_lead_in`
([app/docx_report.py](app/docx_report.py#L1123)) and `_keep_broken_lines_together`
([app/docx_report.py](app/docx_report.py#L1040)) exist to influence that, but only Word decides.
Neither question is answerable on macOS; both need one generated report opened in Word.

---

### Document-side constraints on this change

- **Two fragment types are safely textarea-authorable** (`paragraph`, `note`); `bulleted_list` needs
  a ≥1-item floor; `table` needs a grid, not a box.
- **`{{`…`}}` and `-vuln` must be screened at authoring time**, or the failure lands on a tester
  generating a report weeks later with a message that names the template.
- **`new_finding.docx` has no anchor for `previous_proof_of_concept` or `in_conclusion`**, which is
  the document's own confirmation of the oracle's "only two sections are honestly authorable".
- **A multi-line `note` does not survive the round trip**, and degrades visibly into repeated
  `Note: ` lead-ins.
- **A `table` with no header row does not survive the round trip** — the first data row is promoted.

## Round 1 - Planner: proposal and open questions

## Round 2 - Oracle: verdict on the proposal

## Round 2 - Planner: revised plan

## Answers

## Agreed plan
