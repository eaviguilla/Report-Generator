# Editable DOCX import

> **Status:** shipped · 2026-09-21 · `4c5fd78`

## Request

> Document generation and import
>
> I want to have an import option. The current import function is that I will import then add the report as a retest but I want the users to have an option to edit the imported document in the report generator instead of just auto import as a retest

## Round 1 - Oracle: how it works today

**Answer**

Today a generated DOCX has one unconditional meaning: the manager posts only the file, and the server turns every retained finding into retest state before the payload reaches `Report` validation. The existing `Report` and `Workspace.import_report` abstractions can already store an editable reconstruction, but the branch must happen before `_findings` drops Resolved findings and source sections, and its output must survive the first ordinary PUT without provisioning changing it.

**Evidence**

### Current request and save path

1. The manager's hidden input already accepts ZIP, JSON, and DOCX. Selecting any file runs the same `onchange`: it appends only `file` to `FormData`, posts `POST /reports/import`, reads only `report_id` from the response, and immediately navigates to `/reports/{id}/setup`. There is no import-mode value and the DOCX `summary` returned by the server is currently ignored ([home.html](../../app/web/templates/home.html#L4), [manager.js](../../app/web/static/manager.js#L147-L164)).
2. The route reads the upload under the bundle-size limit, detects DOCX by opening the ZIP and looking for `word/document.xml`, and calls `parse_report_docx` in the worker pool before the generic ZIP/JSON branch. It converts the parser's `{evidence_id: bytes}` result into `evidence/<evidence_id>.png`, then calls the same `Workspace.import_report` used by the other import formats ([main.py](../../app/main.py#L302-L313), [main.py](../../app/main.py#L554-L571)).
3. `parse_report_docx` opens the document, scans body tables into an unused `metadata` dictionary, reads only `segment` and `app_name` from the title, recovers web/API scope, calls `_findings`, and returns `(payload, evidence_bytes, summary)`. The payload deliberately supplies placeholder identity, blank/new-engagement fields, and a retest-shaped vulnerability list ([docx_import.py](../../app/docx_import.py#L578-L632)).
4. For DOCX, the first `Report` validation occurs inside `Workspace.import_report`. The `Report` before-validator normalises legacy app-type and scope shapes; the after-validator enforces cross-object references. `Workspace.import_report` then requires the evidence-file key set to equal the evidence metadata's file set, replaces `report_id`, `saved_at`, and `_folder_name_hint`, and calls `save` ([models.py](../../app/models.py#L342-L399), [workspace.py](../../app/workspace.py#L161-L179)).
5. `save` takes the per-report re-entrant process/OS lock and `_save_unlocked` chooses the folder, advances `saved_at` monotonically, writes `draft.json` through `atomic_write_json`, and sweeps files absent from the evidence registry. The DOCX evidence bytes are then written atomically *after* that locked JSON save; `Workspace.import_report` does not hold one outer lock across JSON plus all images, but it removes the entire new report directory if any evidence write fails ([workspace.py](../../app/workspace.py#L63-L96), [workspace.py](../../app/workspace.py#L161-L179), [workspace.py](../../app/workspace.py#L302-L377), [storage.py](../../app/storage.py#L18-L45)).
6. The import response exposes `source: "docx"` and the parser summary, but the browser discards both and lands on Setup. Setup itself has no route gate; Findings requires `setup_is_complete`, and Content additionally requires at least one finding and every finding to pass `finding_is_complete` ([main.py](../../app/main.py#L622-L649), [manager.js](../../app/web/static/manager.js#L154-L160), [report_service.py](../../app/report_service.py#L728-L789)).
7. Browser boot starts with `pendingSave = false`, so merely opening the imported draft does not PUT it. On Setup it seeds missing test-window objects and the client-only `scope_text` from stored targets; the first user edit/autosave or successful Next action sends the whole report and imported `saved_at` to `PUT /reports/{id}` ([app.js](../../app/web/static/app.js#L104-L180), [app.js](../../app/web/static/app.js#L725-L825), [app.js](../../app/web/static/app.js#L1539-L1578), [app.js](../../app/web/static/app.js#L2781-L2789)).
8. That first PUT reloads the prior draft, rejects an already-stale body, reconciles `scope_text`, restores the server-owned `report_id` and `app_id`, validates `Report`, checks the Setup/finding character rules, derives `app_id` if it is still `unnamed`, runs `provision_report`, and finally performs a locked `save_if_current`. The response contains the canonical provisioned report, which the browser merges back into live state ([main.py](../../app/main.py#L651-L713), [app.js](../../app/web/static/app.js#L411-L474)). `reconcile_targets` reuses a target ID only when its `(environment, channel, value)` triple is unchanged, so the current web/API imports retain their freshly minted target IDs across this first save ([report_service.py](../../app/report_service.py#L621-L721)).

### Where retest semantics become irreversible

`_summary_rows` initially recovers all three model statuses from the findings table. Inside `_findings`, however, a row outside `RETAINED_STATUSES = {open_new, open_previously_discovered}` is dropped before its detail sections or evidence are built. For each retained finding, a local `sections` dictionary temporarily holds the headings present in the DOCX, but the returned payload builds only Description, Recommended Remediation, and source Proof of Concept; it writes that source PoC as `previous_proof_of_concept`, creates a fresh current PoC, creates an empty In Conclusion, and hard-codes `open_previously_discovered` ([docx_import.py](../../app/docx_import.py#L35-L58), [docx_import.py](../../app/docx_import.py#L374-L414), [docx_import.py](../../app/docx_import.py#L443-L557)).

There is therefore no neutral parse result today. The raw ingredients exist only as local variables: the original status row for every summary entry, and raw section XML only for findings that survive the early status filter. They are not returned, and source Previous Proof of Concept, source In Conclusion, all Resolved detail content, and images found only in those discarded sections cannot be reconstructed from the function's output. Calling the current parser and trying to undo retest shaping afterward is too late.

The current import is also not a full provisioning fixed point. It emits `in_conclusion.fragments = []`, while `provision` inserts an empty paragraph into a present empty In Conclusion section. Thus the first PUT changes at least that section; it can also replace resolved remediation, normalise proof step/image slots, and assign the first affected environment to an image whose environment is unset ([docx_import.py](../../app/docx_import.py#L535-L550), [report_service.py](../../app/report_service.py#L281-L350), [report_service.py](../../app/report_service.py#L436-L480)). Existing tests assert the retest rewrite and evidence carry-over, but there is no import fixed-point assertion ([test_docx_import.py](../../tests/test_docx_import.py#L310-L350), [test_docx_import.py](../../tests/test_docx_import.py#L390-L421)).

### What the DOCX can and cannot preserve

| Area | Present/recoverable from the generated DOCX | Current import result and hard limits |
|---|---|---|
| Finding status and summary fields | The summary table carries title, likelihood, impact, severity, display number, and one of all three `Status` labels ([docx_import.py](../../app/docx_import.py#L374-L389), [models.py](../../app/models.py#L9-L17)). | Resolved is dropped; both open statuses become `open_previously_discovered`. An unknown or edited status maps to `None` and is also dropped, while the summary still calls the bucket `dropped_resolved` ([docx_import.py](../../app/docx_import.py#L35-L58), [docx_import.py](../../app/docx_import.py#L483-L495), [docx_import.py](../../app/docx_import.py#L631-L632)). Editable mode can represent all three known statuses without a schema change, but must define malformed/unknown-status behavior. |
| Source content sections | `SECTION_HEADINGS` recognises all five model sections. Open New documents normally contain only Description, Recommended Remediation, and current Proof of Concept; the other statuses use the five-section detail layout because generation selects sections by status ([docx_import.py](../../app/docx_import.py#L29-L42), [report_service.py](../../app/report_service.py#L251-L257), [docx_report.py](../../app/docx_report.py#L758-L790)). | Current import discards source Previous PoC and In Conclusion and promotes current PoC. Editable mode can preserve every *printed* section by building each recovered section before shaping. It cannot recover a model section that was carried but hidden when the DOCX was generated, nor internal `generated`, library-offer, or PoC-variant state that was never rendered. |
| Fragment fidelity | The parser recognises paragraphs, lists, tables, notes, images, code blocks, instance titles, captions, and basic bold/italic/underline runs ([docx_import.py](../../app/docx_import.py#L133-L220), [docx_import.py](../../app/docx_import.py#L253-L339)). | This is reconstruction, not draft deserialisation: every `frag_id` is new; list `continue_numbering`, image `width_mm`, generated markers, original image names, and some run-level structure are not recovered. A literal `N/A`, a generated `N/A`, an environment heading that looks like an instance title, and a user paragraph beginning with the note marker are not always distinguishable from template output. |
| Additional Information | Severity Review Tickets are present in non-Open-New detail layouts; Asia's Section table carries CVSS score/vector by finding title ([docx_import.py](../../app/docx_import.py#L43-L55), [docx_import.py](../../app/docx_import.py#L469-L520)). | Current import keeps these only for retained findings. A Resolved finding is dropped after its CVSS row is claimed, so all of its values are lost. The local CVSS predicates deliberately mirror the save allowlists; editable recovery must retain that parity ([docx_import.py](../../app/docx_import.py#L78-L105), [docx_import.py](../../app/docx_import.py#L483-L501)). |
| Web/API scope | The two scope tables identify environment and channel; finding detail tables identify affected locations. The parser mints targets and matches a finding by `(environment, value)` ([docx_import.py](../../app/docx_import.py#L349-L372), [docx_import.py](../../app/docx_import.py#L392-L414)). | Target IDs and order are reconstructed. If the same value exists in Web and API for one environment, the detail row has no channel in the lookup key, so one target wins. Unmatched detail locations become custom Web locations, losing their original channel. Also, despite its comment, `_scope_rows` treats each `w:br`-wrapped line as a separate target; there is no current rejoin logic ([docx_import.py](../../app/docx_import.py#L349-L372), [docx_report.py](../../app/docx_report.py#L395-L438)). |
| Mobile/Thick Client scope | Generation writes component value and description and names the component channel, but its Component table has no environment column; production-first ordering is the only environment signal ([docx_report.py](../../app/docx_report.py#L240-L261), [docx_report.py](../../app/docx_report.py#L472-L488)). | The parser reads only URL and API tables, so component targets/descriptions are currently lost and channels fall back to Web. Because the table does not encode where production ends and non-production begins, complete recovery of unused component targets is not established by the source format; this is a real fidelity ambiguity, not just an omitted branch. |
| Evidence | Embedded image bytes in sections passed to `_build_fragments` are extracted. The parser mints an evidence/fragment pair and recomputes dimensions and SHA-256 from the embedded bytes ([docx_import.py](../../app/docx_import.py#L223-L237), [docx_import.py](../../app/docx_import.py#L271-L291), [docx_import.py](../../app/docx_import.py#L560-L575)). | The DOCX holds a rendered image, not the original upload, so original bytes/name/upload time and editor width are unavailable. Current import never builds discarded sections, so their images never enter either the registry or file set. Editable mode must build all kept sections before assembling evidence, with every fragment reference backed by metadata and every metadata file supplied to `Workspace.import_report`. |
| Engagement fields | Generation emits app name, segment, report type, app owner, report date, tester, per-environment window dates/times, Web/API scope, limitations, and user accounts; the full accounts and limitations tables are populated separately ([docx_report.py](../../app/docx_report.py#L263-L306), [docx_report.py](../../app/docx_report.py#L456-L488)). | Current parsing preserves only app name, segment, and a recognised preset/legacy non-production label. It derives tested channels/environments from recovered Web/API targets and otherwise defaults to Web/Production. It explicitly blanks `app_owner`, `report_type`, `test_windows`, and `report_date`; omitted model fields become their defaults, including blank tester, `N/A` limitations, and one `N/A` account ([docx_import.py](../../app/docx_import.py#L238-L251), [docx_import.py](../../app/docx_import.py#L587-L628), [models.py](../../app/models.py#L233-L267)). Those rendered fields are potential recovery work, not proof of impossible recovery, but stable extraction from all four templates is not implemented today. A custom non-production label is recoverable only if it matches the finite known-label set and appears as an evidence heading. |
| Fields absent from DOCX | None. | `ci_number`, `bsn_number`, top-level `start_date`/`end_date`, `classification`, `template_set`, `app_version`, and internal library/offer state are not emitted by `_metadata`; exact values are unavailable from the generated document ([models.py](../../app/models.py#L199-L267), [docx_report.py](../../app/docx_report.py#L263-L294)). |
| IDs and timestamps | `display_id` is printed and is retained when it matches one to five digits. | `report_id`, `app_id`, vulnerability `uid`, target IDs, fragment IDs, and evidence IDs are not document identities and are minted anew; `Workspace.import_report` always replaces report identity and revision. Evidence upload time is import time. `app_id` starts as `unnamed` and the first PUT derives it from recovered CI, BSN, or app name; with CI/BSN unavailable, that means app name ([docx_import.py](../../app/docx_import.py#L68-L69), [docx_import.py](../../app/docx_import.py#L542-L555), [workspace.py](../../app/workspace.py#L24-L37), [workspace.py](../../app/workspace.py#L161-L172), [main.py](../../app/main.py#L700-L705)). |
| Report type and dates | The generated DOCX contains the report-type display label, full report date, and tested-environment window dates/times. Dates are rendered as English `Month D, YYYY` ([docx_report.py](../../app/docx_report.py#L229-L231), [docx_report.py](../../app/docx_report.py#L263-L289)). | Current parser ignores them and writes `report_type=None`, `report_date=None`, `test_windows={}`. The initial folder therefore uses the current month and provisional `Report` label; the first save that supplies a type can move that provisional report folder, using whichever report date is then in the draft ([docx_import.py](../../app/docx_import.py#L616-L628), [workspace.py](../../app/workspace.py#L49-L58), [workspace.py](../../app/workspace.py#L347-L371)). The planner must decide whether editable means restoring source dates/type or starting a new engagement. |

### Compatibility and current-history contradictions

- The existing schema already admits all three statuses and all five content types, so an editable result does not inherently require a schema version or draft migration. Existing JSON and ZIP imports already share `Workspace.import_report` and must remain outside any DOCX-only shaping choice ([models.py](../../app/models.py#L9-L20), [models.py](../../app/models.py#L140-L151), [main.py](../../app/main.py#L327-L380), [main.py](../../app/main.py#L554-L571)).
- A draft previously imported through today's retest path cannot be upgraded in place to editable: its Resolved findings, source Previous PoC, source In Conclusion, associated evidence, and original IDs were never saved. Recovery requires the source DOCX again.
- Requiring a new multipart mode would break callers that currently send only `file`; silently defaulting it would preserve protocol compatibility but makes one semantic path implicit. ZIP/JSON currently have no concept of mode, and `is_report_docx` branches on bytes rather than filename or MIME type ([manager.js](../../app/web/static/manager.js#L147-L155), [main.py](../../app/main.py#L302-L313), [main.py](../../app/main.py#L554-L571)).
- The shipped history is not an accurate implementation ledger here. It says `app_owner` is carried, tester/report date come from the app, `provision_report` moved to `report_service.py`, long wrapped scope values rejoin, the import is a provisioning fixed point, and the summary appears before navigation ([import-docx-as-retest-draft.md](import-docx-as-retest-draft.md#L746-L804)). Current source instead blanks those engagement values, keeps `provision_report` in `main.py`, splits wrapped lines, changes empty In Conclusion on first save, and ignores the summary ([docx_import.py](../../app/docx_import.py#L349-L372), [docx_import.py](../../app/docx_import.py#L578-L632), [main.py](../../app/main.py#L261-L265), [manager.js](../../app/web/static/manager.js#L147-L160)). The existing retest behavior and tests, not that plan text, are the compatibility baseline.

### Smallest plausible change boundary

The narrow existing seam is the DOCX branch of `POST /reports/import` and the shaping boundary inside `_findings`: add a DOCX-only request choice, preserve a neutral representation of each summary row plus every printed section before filtering, then shape either the current retest payload or an editable payload into the same `(payload, evidence, summary)` contract. Both results can continue through `Report.model_validate`, `Workspace.import_report`, the same response, and the same editor routes. This does not establish the final design; it only rules out a second endpoint, a second persistence path, or post-processing the already-lossy current payload as necessary abstractions.

One architectural constraint remains: `provision_report` currently lives in `main.py`, which imports `docx_import.py`. The parser cannot import that wrapper back without reversing the dependency. A fixed-point check or implementation must either use the lower-level `report_service.provision` and `sync_evidence_image_slots`, shape the payload explicitly to their result, or move the wrapper; the shipped plan's claimed move did not occur ([main.py](../../app/main.py#L22-L25), [main.py](../../app/main.py#L261-L265)).

### Ambiguities the planner must resolve

1. Define "editable" as preservation of the *visible generated document* or attempted restoration of the source draft. The latter is impossible for hidden status-inapplicable sections, internal IDs, library/offer state, original image metadata, and fields never emitted.
2. Decide whether all three known statuses are mandatory to preserve and whether an unknown/blank edited status rejects the DOCX or imports a visibly incomplete finding. Today's retest path silently drops it under a misleading `dropped_resolved` key.
3. Decide which rendered engagement values editable mode restores: report type, report date, test windows/times, tester, app owner, limitations, and all account rows. Also decide precedence when the title and a labelled field disagree, how `N/A` is interpreted, and whether the importer's tester/current date should replace source values.
4. Decide the identity rule for unavailable values. The source DOCX cannot supply CI, BSN, `app_id`, `report_id`, or internal child IDs; using fresh IDs is unavoidable, while deriving `app_id` from app name on first save changes how the editable copy relates to the original application identity.
5. Decide the supported scope promise. Web/API scope has duplicate-value, custom-channel, and wrapped-line ambiguities; Mobile/Thick Client lacks an encoded environment boundary. The planner must choose between best-effort reconstruction with explicit warnings, blocking unsupported documents, or requiring Setup repair.
6. Decide whether "preserve sections" includes document-edited content that current provisioning regards as derived. In particular, a Resolved remediation is replaced, empty In Conclusion gains a paragraph, current-proof slots are normalised, and an unlabeled image may gain an environment on first save.
7. Decide image fidelity: preserving the embedded DOCX raster is possible; restoring the original upload filename, bytes, timestamp, and width setting is not. Also decide whether an image with no recoverable environment stays unset for user repair or is assigned by provisioning.
8. Decide the request contract and user interruption: whether every DOCX requires an explicit choice, what an old client omitting mode means, whether mode on ZIP/JSON is rejected or ignored, and what cancel does. The current byte sniff means extension/MIME is suitable only for deciding whether to show a browser choice, not for server authority.
9. Decide what the user must see before navigation. The server already returns a summary, but the current manager never displays it; editable mode needs an explicit policy for reporting unrecoverable fields, unsupported scope, malformed statuses, and any content transformed by the chosen mode.

**Invariants in play**

| Invariant | Consequence if violated |
|---|---|
| A `Report` has unique target IDs, vulnerability IDs, display IDs (when present), content types per finding, and report-wide fragment IDs; every selected target and image evidence reference resolves, and evidence filenames match their IDs ([models.py](../../app/models.py#L374-L415)). | Import fails validation before persistence, or later edits point at the wrong scope/evidence. Neutral extraction must mint once and shaping must not duplicate or orphan those IDs. |
| `Workspace.import_report` requires exact equality between evidence metadata paths and supplied files ([workspace.py](../../app/workspace.py#L161-L168)). | Missing or extra extracted images reject the whole import. Keeping more sections in editable mode necessarily expands both sides of this set together. |
| Report JSON is atomic and locked per report; the first ordinary edit is optimistic-concurrency guarded by `saved_at` ([workspace.py](../../app/workspace.py#L63-L96), [workspace.py](../../app/workspace.py#L302-L367), [storage.py](../../app/storage.py#L18-L45)). | Bypassing `Workspace` introduces torn/lost writes. Import itself has no stale-write comparison because it creates a fresh ID; after navigation every PUT must retain the returned revision or receive 409. |
| The evidence registry is authoritative for `_drop_orphan_evidence`, not fragment reachability ([workspace.py](../../app/workspace.py#L347-L383)). | Dropping metadata deletes the PNG on save; dropping only a fragment reference leaves a registry/file orphan. Editable shaping must decide section retention before finalising the registry. |
| `provision_report` is server-owned on every PUT and controls status sections, generated remediation/conclusion state, and current-proof image slots ([main.py](../../app/main.py#L261-L265), [main.py](../../app/main.py#L700-L705), [report_service.py](../../app/report_service.py#L251-L350), [report_service.py](../../app/report_service.py#L436-L480)). | An imported shape that is not a fixed point changes on the first save, so "editable" content can disappear or move after the user enters Setup data. |
| Setup completeness gates Findings; finding completeness gates Content. Structural `Report` validity alone does neither ([main.py](../../app/main.py#L629-L649), [report_service.py](../../app/report_service.py#L728-L789)). | A successfully imported editable draft may still be unable to reach the editor. Missing engagement fields and zero-location findings must remain visible and repairable on the page that owns them. |
| Scope reconciliation treats `scope_text` as request-only state and preserves IDs by exact target identity ([report_service.py](../../app/report_service.py#L621-L721), [app.js](../../app/web/static/app.js#L1539-L1578)). | A recovery that changes channel/environment/value spelling causes new IDs; stale finding target IDs are then removed or can strand a finding and reject the save. |
| Initial identity is new, not restored: imported `report_id`/revision/folder hints are overwritten; `app_id` is later frozen after derivation ([workspace.py](../../app/workspace.py#L161-L172), [main.py](../../app/main.py#L680-L705)). | Treating a DOCX as an identity-bearing backup risks collision or overwrite. Editable means editable copy, not restoration of the original object identity. |

**Both-sides warning**

The DOCX parser, `Report.validate_references`, `Workspace.import_report`, upload limits, atomic writes, and stale-write comparison are server-only. The new mode token would be a new browser/server contract between `manager.js` and `main.import_report`, but it must remain request metadata rather than report data.

The imported shape is governed by existing Python/JavaScript twins that must remain aligned:

- status-to-section mapping, tester-work detection, provisioning, resolved remediation, and In Conclusion normalisation: `content_types_for_status`/`contentTypesForStatus`, `content_has_work`/`contentHasWork`, and `provision`/`provision` ([report_service.py](../../app/report_service.py#L251-L350), [app.js](../../app/web/static/app.js#L1060-L1153));
- affected environments/channels, custom-location cleaning, and evidence-slot normalisation: `location_lines`, `affected_environments`, `affected_channels`, `sync_evidence_image_slots` and their JavaScript counterparts ([report_service.py](../../app/report_service.py#L352-L480), [app.js](../../app/web/static/app.js#L1156-L1282));
- Setup and finding navigation gates: `setup_issues`/`setup_is_complete` and `finding_is_complete` versus `validateSetupPage` and `validateFindingsPage` ([report_service.py](../../app/report_service.py#L728-L789), [app.js](../../app/web/static/app.js#L2700-L2789));
- Additional Information character rules: Python save validation, JavaScript field validation, and the importer's local CVSS predicates all accept the same character categories ([report_service.py](../../app/report_service.py#L153-L224), [docx_import.py](../../app/docx_import.py#L78-L105));
- channel order/labels/component-channel classification and recognised non-production presets are represented on both sides; changing recoverable scope or label semantics in only one language can make the first save reinterpret an otherwise valid import ([models.py](../../app/models.py#L9-L29), [app.js](../../app/web/static/app.js#L1184-L1215)).

**Map drift**

None. The current data map correctly places `provision_report` in `main.py`, records DOCX import as retest-only, states that `import_report` itself bypasses provisioning/reconciliation, and describes the locking, evidence, and first-save rules ([DATA_MAP.md](../DATA_MAP.md#L38-L104), [DATA_MAP.md](../DATA_MAP.md#L153-L182)). The contradictions above are in the shipped plan history, not in `docs/DATA_MAP.md`, so the map was not changed.

## Round 1 - Scribe: the document side

**Bottom line**

An editable import can faithfully mean **a new draft whose generator-supported, visible semantics
match the supplied DOCX**. It cannot mean restoration of the draft that originally produced the
file. The DOCX is a presentation projection: it contains most visible engagement values, all
summary-table finding values, and every section that the finding's status prints, but it omits
internal identity, hidden status-inapplicable sections, source/provenance flags, and several scope
distinctions. This section does not revisit the route, storage, evidence-registry, or first-save
findings established by the Oracle above.

The right falsifiable contract is therefore semantic, not byte-for-byte: render a report, extract a
neutral document model, shape an editable draft, render that draft, and extract again. The two
neutral projections should agree on every supported visible value and fragment. Any named
exception should be surfaced to the user rather than silently presented as faithful recovery.

### What the generated document actually carries

#### Engagement and scope

The renderer writes the following values into every applicable canonical template:

- `segment`; `app_name` through both `app-name` and `report-name`; the display label for
	`report_type`; `app_owner`; `report_date`; `tester`; and production/non-production window start,
	end, and time. Dates have the fixed English form `Month D, YYYY`; missing values print as `N/A`.
	The four reversible report-type labels are `Annual Pentest`, `Retest`, `Deployment Pentest`, and
	`New Test` ([docx_report.py](../../app/docx_report.py#L229-L294),
	[report_service.py](../../app/report_service.py#L14-L20)).
- Every Web and API target value, separated by environment in the `URL(s) in Scope` and `API
	Routes` tables; the complete limitations value in the `Limitations` table; and every test-account
	role/username pair in cloned `User Roles` rows. The two numbered role/username tokens are only
	compatibility placeholders; the rebuilt table is the complete source for accounts
	([docx_report.py](../../app/docx_report.py#L456-L488)).
- In a component template, one `Mobile` or `Thick Client` display label and one `Component` row per
	target, carrying the target value and description. Rows are production first, then
	non-production, but there is no environment cell or boundary marker
	([docx_report.py](../../app/docx_report.py#L245-L261),
	[docx_report.py](../../app/docx_report.py#L481-L488)).

Those values are technically parseable from an unchanged generated file, even though today's
importer reads only a subset. Exact known display labels can be reverse-mapped, and the renderer's
date format can be parsed deterministically. There are nevertheless document-level ambiguities:

- `N/A` is both the renderer's missing-value sentinel and text a person can type. An `N/A`
	limitation, account row, date, time, caption, or empty section cannot always be distinguished
	from literal content ([docx_report.py](../../app/docx_report.py#L229-L234),
	[docx_import.py](../../app/docx_import.py#L68-L75)).
- `tested_channels` and `tested_environments` are not emitted as independent fields. Web and API
	tables exist even when their channel has no target, and both environment blocks exist even when
	one was not tested. Windows and non-`N/A` scope usually permit inference in a complete report,
	but an intentionally empty scope is indistinguishable from an untested channel/environment.
- Web/API scope has an explicit channel and environment because each has its own table and static
	environment rows. A component row retains value and description but not environment; row order
	alone cannot reveal how many rows belonged to production. The component caption can identify
	Mobile versus Thick Client, not the missing environment boundary.
- A finding detail table prints the final location strings grouped by environment, after applying
	target-specific display overrides and appending custom locations. It does not print channel,
	target identity, whether a value was selected or typed, or the original target value behind an
	override ([docx_report.py](../../app/docx_report.py#L1411-L1424)). Matching those strings back to
	global targets is therefore best effort. The same value in Web and API is intrinsically
	ambiguous, as is every unmatched location's channel.
- Generator wrapping is represented by `w:br` inside one scope/list paragraph. A neutral reader
	must treat the paragraph as the target or affected-location unit and join its internal wrap
	breaks. Splitting `cell.text` into lines turns one long generated endpoint into several targets
	([docx_report.py](../../app/docx_report.py#L386-L418),
	[docx_report.py](../../app/docx_report.py#L421-L442)).
- The custom non-production label is not used in the scope tables. It is printed as an evidence
	heading only when a proof section renders a non-production image, so a generated report without
	such an image does not carry the selected label at all
	([docx_report.py](../../app/docx_report.py#L812-L830),
	[docx_import.py](../../app/docx_import.py#L243-L251)).

#### Findings and status-dependent sections

The rebuilt findings summary is the authoritative complete list. Each row contains, in order,
`title`, `likelihood`, `impact`, `severity`, visible one-to-five-digit finding number (or blank),
and the exact label for all three known statuses: `Open (New)`, `Open (Previously Discovered)`, and
`Resolved`. Rows are sorted by severity and then title, so the source draft's list order is gone;
the visible document order is recoverable ([docx_report.py](../../app/docx_report.py#L48-L53),
[docx_report.py](../../app/docx_report.py#L490-L523)).

Each detail body repeats the title, severity, finding number, status, and affected-location text.
It adds severity-review ticket lines for the retest component, and an Asia template adds one
`Section` row per finding with title, severity, CVSS score, and CVSS vector. The Section number is a
Word reference to the finding heading, not report data, and is irrelevant to reconstruction
([docx_report.py](../../app/docx_report.py#L591-L632),
[docx_report.py](../../app/docx_report.py#L750-L790)).

The exact printed-section matrix is:

| Source status | Printed sections | Consequence for editable import |
|---|---|---|
| `open_new` | Description, Recommended Remediation, Proof of Concept | These three can be retained. Any Previous PoC or In Conclusion carried invisibly in the source draft is absent and unrecoverable. |
| `open_previously_discovered` | Description, Recommended Remediation, Previous Proof of Concept, Proof of Concept, In Conclusion | All five visible sections can be retained in their original roles. |
| `resolved` | Description, Recommended Remediation, Previous Proof of Concept, Proof of Concept, In Conclusion | All five visible sections can be retained and the status can remain Resolved. The finding component is structurally the same retest component used by previously discovered findings; the summary/detail status label is what distinguishes them. |

The renderer chooses `new_finding.docx` only for `open_new` and
`retest_finding.docx` for both other statuses, then splices only the anchors listed above
([docx_report.py](../../app/docx_report.py#L750-L810)). Consequently, an editable parser can
preserve every **printed** Previous PoC, current PoC, and In Conclusion, but it cannot recreate a
section suppressed by the source status.

Resolved remediation needs a narrower promise. In an app-generated report its visible text is the
fixed sentence `None, the vulnerability has been remediated.` because provisioning replaces the
whole section and marks the paragraph as generated ([report_service.py](../../app/report_service.py#L310-L323)).
The DOCX carries the sentence but not the `generated="resolved_remediation"` provenance marker. A
person may also edit that sentence in Word. The model can hold the edited remediation, but current
provisioning will overwrite it again while the status remains Resolved. Preserving a manually
edited Resolved remediation through the first editable save is therefore not merely an import-parser
problem; either that edit is declared unsupported or the status/provisioning rule must change.

Severity-review tickets are recoverable only from the retest component and only as numeric ticket
identifiers. The `GRIMPEN-` prefix belongs to the document and is stripped; manually added prose is
deliberately rejected rather than mined for plausible digits ([docx_report.py](../../app/docx_report.py#L768-L776),
[docx_import.py](../../app/docx_import.py#L84-L105)). CVSS values are recoverable only from either
Asia template's `Section` table. Absence of that optional table in either non-Asia template means
“not printed”, not a malformed report.

#### Fragments, formatting, and evidence

The document can express all eight editor fragment types: paragraph, numbered list, bulleted list,
table, note, image, code block, and instance title. Code/table captions precede their object using
`caption_fragment.docx`; image captions follow the image and are converted to native `SEQ Figure`
fields. Fragment recognition deliberately uses component fingerprints rather than style names
alone: image relationships, caption style, resolved numbering format, code shading, paragraph
alignment, paragraph-mark emphasis, and reserved instance text
([docx_import.py](../../app/docx_import.py#L1-L7),
[docx_import.py](../../app/docx_import.py#L108-L220)).

For an unchanged generated document, an editable import can retain fragment order, text, list
items, table cell text, captions, code newlines, instance-title text, and embedded images. The
current `runs_of` representation also matches every rich-text property the draft model knows:
bold, italic, and underline ([models.py](../../app/models.py#L74-L139),
[docx_import.py](../../app/docx_import.py#L165-L202)). “Preserve formatting” cannot mean arbitrary
Word formatting: font family/size/color, paragraph style, alignment, spacing, borders, table grid
widths, merged cells, pagination, and field formatting are not draft fields. On regeneration those
come from the canonical component documents again.

Several finer-grained values need explicit treatment before claiming a faithful round trip:

- The current note path strips `Note:` by replacing the result with one plain run, so bold/italic/
	underline inside a note are lost even though the model can express them
	([docx_import.py](../../app/docx_import.py#L321-L328)). It should remove the generated prefix while
	retaining the remaining runs.
- Adjacent list paragraphs are currently merged solely by fragment type. The generated OOXML does
	carry enough information to distinguish independent lists from a continued numbered-list chain:
	independent clones receive different numbering IDs, while `continue_numbering` reuses one ID in
	the same section ([docx_report.py](../../app/docx_report.py#L897-L932),
	[docx_components.py](../../app/docx_components.py#L242-L321)). A neutral reader must retain that
	identity long enough to rebuild fragment boundaries and `continue_numbering`; merely resolving
	bullet versus decimal is insufficient.
- One multiline paragraph or note is rendered as several paragraphs. After generation there is no
	unambiguous distinction between those lines and several adjacent source fragments with the same
	component formatting ([docx_report.py](../../app/docx_report.py#L1049-L1112)). Visible paragraphs
	can be preserved, but original fragment boundaries cannot.
- A table's cells and optional preceding caption are available, but the importer currently assumes
	the first row is a header and invents a blank body row when no second row exists
	([docx_import.py](../../app/docx_import.py#L223-L241)). A headerless one-row table is therefore
	ambiguous unless the neutral reader can prove header/body identity from the component row
	formatting. Merged cells and original column widths have no model representation.
- `N/A` generated for an empty content anchor looks exactly like a tester-authored paragraph whose
	entire text is `N/A` ([docx_report.py](../../app/docx_report.py#L878-L896)). Import needs one
	documented rule; it cannot recover intent.
- Generated labels are syntax, not content: `Note:`, `Instance N:`, `PROD:`, the chosen
	non-production label, and `Figure N.` are stripped on import. A user-authored fragment that
	deliberately matches one of those forms is indistinguishable from generator output
	([docx_import.py](../../app/docx_import.py#L256-L339)).

Images are recoverable as the raster embedded in the DOCX, with their visible caption and, in a PoC
section, an environment inferred from the preceding generated heading. Their displayed extent is
also present in the drawing XML, so editable import can recover the visible width in millimetres;
today it discards that value and writes `width_mm=None` ([docx_import.py](../../app/docx_import.py#L271-L291)).
The source setting itself is not fully recoverable: rendering clamps every image to 155 mm, so an
explicit 155, a missing width, and a larger requested width all become the same display width
([docx_report.py](../../app/docx_report.py#L1184-L1223)).

The embedded raster is also not the original upload. Before embedding, the renderer applies EXIF
orientation, converts to RGB, may upscale to 192 DPI at display width, and bakes the component's
0.75 pt black border into a new PNG ([docx_report.py](../../app/docx_report.py#L1427-L1489)). If that
extracted PNG is later rendered through the same path, another border is baked around the first.
That makes image appearance across `DOCX -> editable draft -> DOCX` a concrete unresolved blocker:
the import needs either a safe way to remove the known generated border, or a representation/render
rule that says the recovered image is already presentation-ready. Original bytes, file name,
format, EXIF, upload time, and shared evidence identity cannot be recovered. Two fragments that
originally referenced one evidence item may return as two equivalent new items.

### Meaning of “editable” by requested area

| Requested area | Technically expressible from the generated DOCX? |
|---|---|
| All known statuses | **Yes.** The exact status label is in every summary row. Unknown or blank edited labels need a reject/warn policy; they must not be treated as Resolved. |
| Previous PoC, current PoC, In Conclusion | **Yes when printed.** Preserve each under its own heading. Sections hidden by `open_new` are irreversibly absent. |
| Resolved remediation | **Visible text yes; stable arbitrary Word edits no.** Generated provenance is absent, and current provisioning overwrites remediation for a Resolved finding. |
| Paragraphs, lists, tables, code, notes, instance titles | **Visible semantics yes, exact source structure partly.** The fragment-boundary, list-continuation, note-run, and table-header qualifications above apply. |
| Formatting | **Only model formatting.** Bold/italic/underline can be recovered; canonical component styling is reapplied. Arbitrary Word styling cannot be represented. |
| Images | **Rendered evidence partly.** Embedded PNG, caption, PoC environment, and displayed width are available; original upload metadata is absent and the baked-border rerender problem must be solved. |
| Scope | **Web/API global rows mostly; finding associations and component scope partly.** Component environment, selected-versus-custom provenance, detail channel, and duplicate cross-channel values are not encoded. |
| Report type, report date, window dates/times, tester, app owner | **Yes for unchanged canonical output.** They are explicit display values; known labels and fixed-format dates can be reversed. `N/A` remains ambiguous. |
| Accounts and limitations | **Yes as visible rows/text.** An all-`N/A` placeholder row cannot be distinguished from an intentional all-`N/A` account, and literal `N/A` limitations collapse with blank. |
| Segment and app name | **Yes.** They occur in known template fields and the report title. Conflicting manually edited occurrences need a precedence/error rule. |
| Tested environments/channels and non-production label | **Only by inference.** Empty Web/API tables, the component environment boundary, and a custom label with no non-production evidence are not recoverable. |

IDs and editing metadata are outside a visible-document fidelity promise. The DOCX does not carry
report/application/target/finding/fragment/evidence identity, timestamps, library references,
offer state, `generated` markers, or the source ordering that existed before severity/title sorting.
It also does not emit CI/BSN identifiers, top-level engagement dates, classification as a dynamic
value, or `template_set` ([models.py](../../app/models.py#L199-L267),
[docx_report.py](../../app/docx_report.py#L263-L294)). Fresh identities and documented defaults are
therefore required even in editable mode.

### Template variants and integrity boundary

There are four supported masters on two axes: ordinary versus component scope, and non-Asia versus
Asia. `MAIN_THICK_MOBILE*` adds the `Component` table; `*_ASIA` adds the `Section` table. The choice
is made from the report before rendering, while optional-table population keys off actual table
presence ([docx_report.py](../../app/docx_report.py#L159-L166),
[docx_report.py](../../app/docx_report.py#L345-L360)). The importer should infer capabilities from
the document structure, then cross-check them against parsed labels; it should not infer a template
from the upload filename.

Generation has strong integrity checks:

- the main template must exist, carry the exact body-only `{{findings}}` anchor, and expose required
	tables by header;
- each summary cell must contain exactly one placeholder;
- every component must be non-empty, use only styles present in the master, carry no body
	relationships that would need remapping, and reference valid numbering definitions;
- every fragment/content anchor must occur exactly once, the image component must contain exactly
	one inline image with a border and paragraph alignment, and the table component must contain its
	expected prototype rows/grid; and
- no token or known marker may remain anywhere in the body, headers, or footers
	([docx_report.py](../../app/docx_report.py#L169-L207),
	[docx_components.py](../../app/docx_components.py#L44-L69),
	[docx_components.py](../../app/docx_components.py#L215-L289),
	[docx_report.py](../../app/docx_report.py#L1336-L1352),
	[docx_report.py](../../app/docx_report.py#L1470-L1496)).

Those checks do not prove provenance after the placeholders have been consumed. The generated DOCX
contains no explicit generator schema/version marker, and the current reader's integrity checks are
much weaker: it requires a readable package, a `Findings` summary, and three required section
headings for each retained finding it happens to match. A summary row without a matching
`ReportHeading2` body heading is silently omitted; a body heading not represented in the summary is
ignored; unknown statuses are dropped; duplicate section headings are merged; a missing detail
table becomes empty scope; and the optional Asia table is accepted by presence alone
([docx_import.py](../../app/docx_import.py#L374-L414),
[docx_import.py](../../app/docx_import.py#L443-L557),
[docx_import.py](../../app/docx_import.py#L578-L632)). That behavior is too permissive for an
“editable preserves this document” claim.

A neutral extraction should therefore validate at least:

1. the multiset of summary rows and finding body headings matches, including duplicate titles;
2. every status is known and each finding has exactly one section heading required by that printed
	 status, with no duplicate or out-of-order reserved headings;
3. the detail table, if required for scope recovery, is structurally recognisable and belongs to
	 the same finding;
4. optional `Component` and `Section` tables have the expected headers and row shapes, and their
	 presence does not contradict the parsed segment/component label;
5. every body element inside a recognised section is either intentionally ignored boilerplate or
	 represented as a fragment; and
6. every image relationship resolves to decodable bytes and every positional caption/environment
	 marker has exactly one plausible owner.

This should be a structural contract, not a byte hash of a template. Word legitimately rewrites
relationship IDs, numbering IDs, field caches, and other package details; exact package matching
would reject harmlessly opened-and-saved reports.

### Neutral parsing boundary

The current irreversible branch is inside `_findings`, before a section body is built: it claims a
summary/CVSS row, drops an unretained status, then maps the source Proof of Concept into Previous PoC
and creates a new current PoC ([docx_import.py](../../app/docx_import.py#L443-L557)). The neutral
boundary must be above those choices.

The document reader should produce one mode-independent extraction containing:

- raw and normalized engagement observations, template capabilities, scope/account/limitations
	rows, and diagnostics about conflicts or inference;
- one ordered record for every summary row, retaining the raw status label and normalized known
	status, scalar fields, matching detail table, tickets/CVSS, and **all section bodies under their
	original headings**;
- ordered, classified fragments with the information needed to distinguish list identity,
	captions, displayed image width, and reserved generated labels; and
- extracted image blobs attached to the section/image occurrence that owns them, not yet flattened
	into a report-wide evidence registry.

Only after that result is complete should two shapers run. The retest shaper can apply today's
filter/status/PoC transformation. The editable shaper can retain every known status and map each
printed section to the same content type. Evidence records should be materialized from the selected
shape's reachable image occurrences so neither mode leaks images from sections it intentionally
does not keep. Normalizing `Figure N.`, `Note:`, and `Instance N:` is document syntax and belongs in
neutral extraction; dropping statuses, renaming sections, seeding new PoC slots, or choosing
engagement defaults is mode shaping.

### Manually edited generated documents

Text edits inside an intact known field, table cell, or fragment are the supportable case. Word
edits that change structure are not automatically safe merely because the package still opens:

| Manual edit | Risk to reconstruction |
|---|---|
| Rename/delete/duplicate a reserved section heading | Content can merge into the wrong section or disappear. Exact heading text is currently the only section delimiter. |
| Change a finding title in only the summary or body | The summary and body no longer pair. With duplicate titles, order is part of the disambiguation. |
| Change a status label | It may no longer map to a known status. Current behavior silently drops it; editable mode must not. |
| Delete or restructure the finding detail table | Affected locations become empty or attach to the wrong finding. |
| Paste content with foreign styles/list definitions | Paragraph/list/note/code classification can change, or a list definition can be missing. |
| Type a reserved `PROD:`, non-production, `Instance N:`, `Note:`, or `Figure N.` form | User text can be consumed as generator syntax. |
| Move captions or images | Table/code captions can attach to the next compatible object; image captions and environment labels can attach by position. |
| Add headers, merged cells, text boxes, floating images, footnotes, comments, or tracked-change-only text | These are outside the current body paragraph/table and editor-fragment model and may be invisible to `python-docx` traversal. |
| Change one of several repeated metadata values | App name/type/date copies can disagree; there is no stored source-of-truth marker in the DOCX. |

The planner needs to define a supported-edit envelope. The defensible default is to accept content
edits that preserve generated structure, reject structural contradictions that would lose or
misassign content, and return warnings for explicit best-effort inferences. Silent omission is
incompatible with the purpose of editable mode.

### Smallest useful fixture and checks

No Microsoft Word process is needed for the semantic tests. `render_report_docx` creates the OOXML,
embeds images, and installs cached native caption values before `finalized_report` invokes the
Windows-only automation pass. Word then repaginates, updates story fields/TOC/table-of-figures,
removes page-leading blank paragraphs, updates page numbers, and flattens only computed Asia
section references ([main.py](../../app/main.py#L512-L525),
[docx_captions.py](../../app/docx_captions.py#L49-L115),
[docx_captions.py](../../app/docx_captions.py#L199-L245)). None of those operations supplies report
semantics consumed by the importer. Existing import tests already call the renderer directly for
this reason ([test_docx_import.py](../../tests/test_docx_import.py#L1-L24)).

The smallest fixture set is one synthetic report built in the test, plus parameterized template
selection; no new committed DOCX is necessary:

1. Build one complete Asia/component report with both environments, Web/API plus one component
	 channel, all engagement fields, two account rows, limitations, long wrapped scope values, and a
	 tiny real PNG. Give it three findings covering all three statuses. Across those findings, place
	 all eight fragment types, bold/italic/underline runs, multiline code, independent and continued
	 numbered lists, a headerless and a headed table, current/previous PoC images, tickets, and CVSS.
2. Render once and assert the neutral extraction before either mode: every summary row/status and
	 every printed section is present; metadata and explicit scope rows match; fragment order/types
	 and supported runs match; image bytes, caption, environment, and displayed width are accounted
	 for; and no unrepresented body element remains inside a section.
3. Shape that same extraction both ways. Editable assertions compare against the source's **visible
	 semantic projection**, not its IDs or hidden sections. Retest assertions retain the existing
	 dropped/rewritten/promoted behavior exactly. Validate both payloads as reports.
4. Render the editable result and neutral-extract it again. Compare the first and second neutral
	 projections. This is the check that will expose double image borders, lost width, changed list
	 continuation, `N/A` conversion, note emphasis, table-header guesses, and section movement that a
	 one-way parser assertion misses.
5. Run a four-row template matrix (`MAIN`, `MAIN_ASIA`, `MAIN_THICK_MOBILE`,
	 `MAIN_THICK_MOBILE_ASIA`) with the smallest valid report for each, asserting required and optional
	 table detection plus engagement fields. The current generation smoke test covers all four only
	 in the render direction ([test_docx.py](../../tests/test_docx.py#L1041-L1071)).
6. Mutate copies of the in-memory generated package for one safe text edit and the smallest unsafe
	 cases: unknown status, missing/duplicate section heading, summary/body title mismatch, malformed
	 detail table, unresolved image relationship, and displaced caption. Assert the planner's chosen
	 error/warning outcome and, critically, that no finding or section vanishes silently.
7. Exercise both the pre-Word form and a synthetic post-Word form with updated caption field text
	 and a flattened Asia Section reference. Existing pure-Python caption/field tests show those
	 transformations can be represented without COM; a Windows smoke remains appropriate only for
	 pagination and displayed TOC/table-of-figures behavior, which import does not consume
	 ([test_docx_captions.py](../../tests/test_docx_captions.py#L104-L165),
	 [test_docx.py](../../tests/test_docx.py#L1131-L1182)).

The existing all-fragment fixture is a useful seed but is insufficient by itself: it is one
`open_new`, production-Web, non-Asia report, and its assertion proves today's retest promotion rather
than editable section preservation ([test_docx_import.py](../../tests/test_docx_import.py#L50-L101),
[test_docx_import.py](../../tests/test_docx_import.py#L315-L350)).

### Source contradictions found

- [DOCX_TEMPLATE.md](../DOCX_TEMPLATE.md#L112-L116) describes CVSS import as ASCII regular
	expressions and “stricter than the save rule”. Current `_valid_cvss_score`/`_valid_cvss_vector`
	use Unicode-aware `isdecimal`/`isalpha`, and the test deliberately round-trips Arabic-Indic digits
	and Greek letters ([docx_import.py](../../app/docx_import.py#L78-L85),
	[test_docx_import.py](../../tests/test_docx_import.py#L188-L204)). The implementation and test,
	not that prose, are the current behavior.
- [test_docx_import.py](../../tests/test_docx_import.py#L207-L213) says three of four templates lack
	the Asia `Section` table. Template selection and the template contract show that both Asia
	variants have it, so two of four lack it ([DOCX_TEMPLATE.md](../DOCX_TEMPLATE.md#L5-L23)). The
	fixture matrix must cover both axes rather than preserve that comment's count.

### Questions the planner must resolve

1. Is the promise explicitly “preserve supported visible semantics in a new draft”, rather than
	 “restore the original draft”? The latter cannot be met from a DOCX.
2. In editable mode, should every unambiguous printed engagement value be restored: report type,
	 report/window dates and times, tester, app owner, accounts, and limitations? Document-side
	 evidence supports doing so; `N/A` and conflicting duplicate values still need rules.
3. What is the supported manual-edit envelope, and which anomalies reject the import versus import
	 with a warning? Unknown status, summary/body mismatch, duplicate/missing headings, and unreadable
	 content should never silently drop data.
4. How should intrinsically ambiguous scope be represented: component targets with no environment
	 boundary, duplicate Web/API values in a finding, unmatched detail locations with no channel,
	 and tested channels/environments with empty tables? The choices are block, import visibly
	 incomplete for Setup repair, or choose documented defaults and warn.
5. Does a lone visible `N/A` mean empty/default or literal content in each context? One global rule
	 is not sufficient because `N/A` can be a field sentinel, an empty-section placeholder, a caption,
	 or tester text.
6. Must manually edited Resolved remediation survive? If yes, parser work alone cannot satisfy it
	 while provisioning unconditionally regenerates that section.
7. Must a regenerated editable import preserve screenshot appearance? If yes, decide how to avoid a
	 second baked border and whether to recover displayed width from drawing extents.
8. Are only the four current canonical template structures supported, or must older generated
	 reports remain importable? There is no template/schema marker, so compatibility must be defined
	 by structural fingerprints and diagnostics.
9. When a field has several printed copies that disagree after manual editing, which copy wins, or
	 should the document be rejected? This applies especially to app name, report type/date, finding
	 title, severity, number, and status.

## Round 1 - Planner: proposal and open questions

### Understanding

When the manager selects a generated DOCX, the user chooses either **Retest draft** or **Editable
draft**, or cancels before any upload occurs. Retest remains today's transformation and remains the
default for callers that omit the new multipart field. Editable creates a new report identity whose
supported, visible document semantics can be changed in the existing generator: it restores every
unambiguous printed engagement value, all three known finding statuses, every section printed for
those statuses, supported fragment formatting, and reachable evidence. It does not claim to restore
the source draft, hidden sections, internal IDs, provenance, or original image uploads. Ambiguity is
reported rather than hidden, and structural damage that could lose or misassign content rejects the
editable import before `Workspace.import_report` writes anything.

### Blast radius

| File | Proposed change |
|---|---|
| `app/docx_import.py` | Split reading from shaping: one private neutral extraction, the current retest shaper, an editable shaper, mode-specific integrity decisions, engagement/scope recovery, reachable-evidence materialisation, displayed-width recovery, one-layer generated-border removal, and summaries/warnings. `parse_report_docx(data, mode="retest")` keeps its current tuple contract and default behavior. |
| `app/main.py` | Accept an optional DOCX-only multipart mode, keep omission backward-compatible with retest, validate and provision editable output in memory before the single import write, enforce final evidence equality, and return the selected mode plus the existing summary envelope. |
| `app/report_service.py` | Make Resolved-remediation provisioning reuse an already canonical generated paragraph instead of reminting it, so a provisioned editable draft is an actual fixed point without changing visible behavior. |
| `app/web/static/app.js` | Apply the same generated Resolved-remediation reuse rule in the existing `provision` twin. No DOCX parsing or editable shaping belongs in the browser. |
| `app/web/static/manager.js` | Ask for a DOCX mode through the existing three-action dialog, send the multipart token, cancel without a request, and show the returned transformation summary/warnings before navigating or staying on the manager. |
| `tests/test_docx_import.py` | Add neutral-extraction, two-shaper, four-template, malformed-document, fidelity round-trip, image, evidence, provisioning, request-compatibility, and route-write coverage while retaining every current retest assertion. |
| `tests/test_app.py` | Pin stable generated Resolved-remediation identity and unchanged visible provisioning semantics. |
| `tests/test_browser.py` | Cover mode choice, cancellation, bundle behavior, summary display, and the JavaScript half of stable Resolved remediation. |
| `docs/DATA_MAP.md` | Record the DOCX-only request metadata, neutral/two-shaper flow, editable pre-import provisioning, warning behavior, and stable generated-remediation rule. |
| `docs/DOCX_TEMPLATE.md` | Document the visible-semantic editable contract, integrity envelope, engagement/scope recovery, image width/border rule, and both current-template axes; correct the stale CVSS-regex/template-count statements while there. |

No model, schema version, workspace method, persistence format, template, resource, HTML, CSS, or
dialog implementation needs to change. The mode is request metadata, never report data.

### Open questions

1. **Is editable import a faithful editable copy of the visible report, including its engagement,
	 or a fresh engagement with only the findings copied?** This determines whether dates, tester,
	 owner, accounts, limitations, and report type are restored or blanked. **Recommended default:**
	 make it a new identity with the supplied report's visible engagement values restored. Retest is
	 already the product's fresh-engagement path, and blanking values in editable mode would make the
	 two choices overlap while weakening the fidelity promise.
2. **Should intrinsically ambiguous scope block the entire editable import, or enter a repairable
	 draft with explicit warnings?** The affected cases are component rows with no encoded environment
	 boundary, duplicate Web/API values, unmatched detail locations, and empty tables that do not prove
	 coverage. **Recommended default:** preserve every location string, choose the deterministic
	 fallbacks below, name every assumption in the result dialog, and land on Setup. Reject only when
	 content cannot be assigned without loss, not merely because an environment or channel needs
	 review.
3. **Must a manually edited remediation on a Resolved finding survive as editable text?** Keeping it
	 would reverse the existing product rule on both Python and JavaScript sides and unlock or redefine
	 a section the editor currently treats as generated. **Recommended default:** no; accept the exact
	 canonical generated sentence, but reject editable import with a specific error when a Resolved
	 remediation contains other content. Do not import it and erase it on the first save.
4. **What historical DOCX compatibility is promised?** The files carry no generator version, so
	 “all reports ever generated” cannot be verified from provenance. **Recommended default:** support
	 the four current canonical structural fingerprints plus already-known labels, and support manual
	 text edits that leave that structure intact. Reject unknown structural variants with a named
	 unsupported-format error instead of guessing that they are current templates.

The proposal and ordered steps below assume those recommended defaults. A different answer to
question 3 widens the change into the editor's Resolved-content ownership rule; a different answer to
question 2 changes whether ambiguous documents produce a draft at all.

### Proposed boundary and shaping

`parse_report_docx` remains the one public parser and continues returning `(payload, evidence_bytes,
summary)`. Internally it gains one mode-neutral extraction followed by one of two shapers:

1. **Neutral extraction** reads the document once into private dictionaries, not Pydantic/report
	 schema. It records all engagement observations and conflicts; template capabilities; ordered
	 scope, account, and limitation rows; one ordered record for every summary finding; its raw and
	 normalized status/scalars; its matched detail table; tickets/CVSS; every body element under its
	 original section heading; list numbering identity; supported run formatting; and each image's
	 bytes, owner, caption, environment observation, and drawing extent. It retains diagnostics for
	 unknown values, unmatched/duplicate structures, ambiguous inference, and unsupported body
	 elements. It does not filter a status, rename a section, seed retest content, mint evidence
	 metadata, or choose engagement defaults.
2. **Retest shaping** deliberately reproduces the current contract: keep only the statuses retained
	 today, rewrite them to `open_previously_discovered`, move source Proof of Concept to Previous
	 Proof of Concept, create a fresh current proof and empty conclusion, retain today's engagement
	 defaults, and preserve `retained`, `dropped_resolved`, and `statuses_rewritten` in the summary.
	 Omitting the mode invokes this path. Existing tests remain the compatibility oracle; additional
	 neutral observations must not leak into this payload as accidental behavior changes.
3. **Editable shaping** keeps all three known statuses and maps every section printed for that status
	 back to the same `Content.type`. It restores supported engagement and scope observations, applies
	 the explicit ambiguity rules below, and records warnings. Only after section selection does one
	 shared materialisation pass mint fresh target/finding/fragment/evidence IDs and build evidence
	 metadata/files from image occurrences reachable in the final contents. Thus neither mode can
	 leak an image from a section it discarded, and every emitted image reference, registry entry,
	 and file has exactly one matching owner.

The editable route validates the shaped `Report`, runs the existing `provision_report` once **in
memory**, validates again, and checks that provisioning did not remove or alter user-owned content.
It then calls `Workspace.import_report` once. This avoids importing an unprovisioned revision and
saving a second revision immediately afterward, which would consume the single backup. The fixed
point comparison excludes the new report identity, timestamps/folder hint, and app-owned generated
fragment identity, but requires exact stability of engagement values, statuses, source section
content/order, scope text/associations, evidence references, and evidence bytes. The small paired
Resolved-remediation change above makes even its generated fragment identity stable after the first
normalisation.

### UI and request contract

- The manager treats a `.docx` filename or DOCX MIME type as the cue to open `vrDialog.ask` with
	**Import as editable draft**, **Import as retest draft**, and **Cancel**. Cancel and Escape clear
	the file input and issue no request. ZIP and JSON continue directly with no chooser.
- The chosen token is sent as optional multipart field `docx_mode=editable|retest` beside `file`.
	The server still decides whether the bytes are a DOCX. A missing field means `retest` for existing
	clients and direct parser callers; an unknown token is 422; a supplied DOCX token on bytes that
	resolve to JSON/ZIP is 422 rather than silently pretending the choice applied.
- A successful DOCX response remains `{report_id, source: "docx", summary}` and adds `mode`; bundle
	responses remain unchanged. Retest summaries retain their current keys. Editable summaries carry
	imported finding/status counts, restored engagement categories, any provisioning normalisations,
	and a flat `warnings` list suitable for the existing dialog.
- Before navigation, the manager shows **Imported as editable draft** or **Imported as retest
	draft**, the concise counts, and every warning. **Open Setup** navigates to the new report;
	**Stay on reports** reloads the manager list so the already-created draft is visible. This second
	choice is not cancellation: cancellation exists only before upload.
- Every mode lands on Setup. Ambiguous or incomplete scope is therefore repairable before the
	existing Setup and Findings gates can block forward navigation; no new gate or redirect is added.

### Editable fidelity contract

| Area | Editable behavior | Warning or rejection boundary |
|---|---|---|
| Identity and unavailable fields | Mint a new report, finding, target, fragment, and evidence identity. Start `app_id` as `unnamed`; leave CI, BSN, top-level engagement start/end, and unprinted internal/library/offer state at model defaults. Classification, template set, and app version use current defaults. | The result dialog states that this is a new editable copy, not restoration of original identity or hidden draft state. No warning is needed per fresh ID. |
| Engagement fields | Restore unambiguous printed `segment`, `app_name`, `app_owner`, reversible `report_type`, `report_date`, `tester`, both test-window dates/times, every account row, and limitations. Infer tested environments/channels and the non-production label only from positive document evidence. | Distinct non-placeholder copies of the same field, unknown non-empty report-type/segment labels, and invalid non-empty dates reject editable import because the raw value has no lossless model representation. Metadata/table `N/A` means the renderer's missing/default value; one `N/A`/`N/A` account remains the model's placeholder row. |
| Statuses and scalar finding fields | Keep `open_new`, `open_previously_discovered`, and `resolved` exactly. Preserve title, valid display number, likelihood, impact, severity, tickets, and CVSS from the authoritative summary/optional tables after cross-checking repeated detail values. | Unknown/blank status, unknown enum values, duplicate display IDs, invalid non-empty ticket/CVSS text, or disagreement between summary and detail rejects editable import. Retest mode retains its legacy drop/rewrite behavior. |
| Source sections | Preserve every printed section under its original role: three for Open New and all five for Previously Discovered/Resolved. Preserve visible fragment order, captions, text, tables, code newlines, instance titles, and bold/italic/underline. Hidden source-draft sections remain unavailable. | Missing, duplicate, out-of-order, or status-incompatible reserved headings; unmatched summary/body findings; malformed owning detail tables; and detectable unrepresented content reject. Arbitrary Word styling outside the fragment model is dropped with a warning only when all text/content remains represented. A literal `N/A` inside a content section is retained as text rather than treated as metadata emptiness. |
| Lists, notes, and tables | Use numbering identity to retain independent list boundaries and `continue_numbering`; remove only the generated `Note:` prefix while preserving runs. Use component row formatting when it proves table header/body structure. | Ambiguous one-row/header structure is warned and imported with the visible row retained; missing numbering definitions, displaced captions, or structures that could attach content to the wrong fragment reject. Original multiline-fragment boundaries remain unrecoverable and are not claimed. |
| Resolved remediation | Recognize the exact generated sentence, emit it with `generated="resolved_remediation"`, and preserve its fragment ID through subsequent provisioning. | Any other visible Resolved-remediation content rejects under the recommended product default. It is never accepted and then silently overwritten. |
| Web/API scope | Join generator-internal wrap breaks within one paragraph, preserve explicit table environment/channel and row order, and link a finding location only when `(environment, value)` has one unambiguous target. | An unmatched detail location or duplicate cross-channel match is retained as a custom location under Web and named in warnings; no location string is dropped. A finding with no recoverable location remains present, is named in warnings, and is repaired on Findings after Setup. |
| Mobile/Thick Client scope | Restore the component channel, value, description, and row order. If only one environment is evidenced, use it. If both are possible and no boundary is encoded, assign global component rows to Production; detail rows still retain their printed environment as selected/custom finding locations. | Every defaulted component environment is listed in warnings. A conflicting component caption/template capability rejects. No inferred boundary is presented as recovered fact. |
| Coverage and non-production label | Infer coverage from non-empty scope, window, detail, and evidence observations in canonical order. With no positive signal, use Web/Production so the report remains schema-valid. Recover a non-production label only when its generated evidence-heading role is unambiguous; otherwise use `NON-PROD`. | Every coverage or label default appears in warnings. Empty template tables alone never assert that an app type/environment was tested. |
| Evidence ownership | Build every kept printed section before materialising evidence. Give each image occurrence fresh metadata/file identity, even if two occurrences contain the same raster. Assert reachable fragment IDs = registry IDs = supplied file IDs before persistence. | An unresolved relationship, undecodable image, duplicate ownership, or image in content that cannot be assigned safely rejects the import. There is no orphan registry entry or unreferenced file. |
| Image environment | Preserve a generated PoC environment heading. With one affected environment, infer it. With several and no heading, apply the same deterministic assignment that provisioning would make and warn; with no affected environment, leave it unset and warn for Findings/Content repair. | The in-memory provisioning pass must make no further unreported assignment. Previous PoC remains historical, but its environment still follows the existing server rule when one must be supplied. |
| Image width and border | Read displayed width from the drawing extent in millimetres, capped at the renderer's 155 mm maximum. Before saving the embedded PNG, compute the canonical 0.75 pt border thickness at that extent, verify all four outer strips are the generated black border, and crop exactly one layer. Regeneration then reapplies one border at the recovered width. Hash and dimensions describe the cropped stored PNG. | If the expected border cannot be proven, retain the raster, warn that a canonical border will be added on regeneration, and include this case in the semantic round-trip test. Never crop merely because an arbitrary number of edge pixels happen to be black. Original upload bytes/name/EXIF/time and a pre-clamp width are not recoverable. |
| Manual edits and malformed documents | Accept text and supported formatting edits inside intact canonical fields, rows, headings, and fragment structures. Use the summary/body multiset plus order to support duplicate titles. | Unknown status; summary/body mismatch; missing/duplicate reserved heading; malformed required table; unowned body content; unresolved image/caption; floating/text-box-only content; or any detectable omission/misassignment rejects the whole editable import before writing. Warnings are reserved for deterministic, non-destructive fallbacks. |
| Summary | Report counts by source status, restored engagement categories, sections/evidence imported, server-owned normalisations, zero-location findings, and every scope/image/style assumption. | A warning never substitutes for content that vanished. Anything the importer cannot retain or place safely is a hard error instead. |

### Data risks

| Failure mode | Verdict | Reason and control |
|---|---|---|
| Stale write | **clear** | Import creates a fresh report and has no prior revision to compare. The returned imported revision seeds Setup, and every later PUT continues to send `saved_at` in the JSON body. The mode never substitutes for that token. |
| Lost update | **clear** | No existing report is read then rewritten. Parsing, validation, and provisioning happen before the one `Workspace.import_report` call; existing workspace locking and rollback remain the only write path. |
| Orphan reference | **RISK** | Two shapes select different sections/images, and editable scope remints targets. Mint IDs once after shaping, validate all target/fragment/evidence references, derive the registry/files only from reachable image occurrences, and assert exact registry/file equality before import. |
| Silent stranding | **RISK** | Ambiguous or absent detail scope can leave a finding with zero locations, while choosing the wrong channel can hide the ambiguity. Preserve the finding and location text, warn by finding/location, land on Setup, and cover the zero-location path through the existing Findings gate. |
| Schema compatibility | **clear** | All required statuses, sections, engagement values, scope, and evidence already fit schema `1.4`. The mode and diagnostics stay outside `Report`; there is no version bump, migration, or load repair. |
| Provisioning fixed point / derived-state fight | **RISK** | Empty required sections, image environments/slots, conclusions, and Resolved remediation can change on first PUT. Provision once in memory before the only import write, reject unsupported Resolved edits, reuse canonical generated remediation IDs on both sides, and compare the user-owned projection before persistence and after a second provision pass. |
| Python/JavaScript rule drift | **RISK** | DOCX shaping is server-only, but Resolved provisioning has a browser twin and mode strings cross manager/server. Change the remediation rule in both files and add one test per side plus route/browser contract coverage for the exact mode tokens. No editable reconstruction logic is duplicated in JavaScript. |
| Request compatibility | **clear** | `docx_mode` is optional and omission means retest; JSON/ZIP requests without it are unchanged. Unknown tokens and a token supplied for non-DOCX bytes fail explicitly. The response only adds ignorable fields. |
| Request/response asymmetry | **clear** | The request-only mode is intentionally not echoed into report data; it appears only as response metadata. Existing request-only `scope_text` behavior is untouched. |
| Existing drafts | **clear** | Nothing rewrites drafts on disk and no field is added. A draft imported previously as retest cannot be upgraded because its source content is gone; the summary/documentation directs the user to re-import the source DOCX. Existing Resolved drafts only gain stable generated-fragment identity on their next ordinary save. |
| Navigation trap | **clear** | The route always opens Setup, the only page where inferred engagement/scope can be corrected. Findings and Content keep their current forward gates, and Back remains available; zero-location findings are not redirected to a page where they cannot be repaired. |
| Backup exhaustion | **clear** | Editable provisioning occurs in memory before `Workspace.import_report`. There is one new-report JSON write, not import followed by an immediate normalization save, so no pair of rapid writes consumes `draft.bak.json`. |

### Plan

- [ ] **Step 1 — Introduce neutral extraction behind the unchanged retest contract.** Files: `app/docx_import.py`, `tests/test_docx_import.py`. Refactor document reading so all findings/statuses/original sections and image occurrences exist before a mode decision, then implement the current logic as `_shape_retest`; keep `parse_report_docx(data)` defaulting to retest and preserve its tuple and summary keys. Focused tests: retain all existing import tests and add `test_neutral_extraction_keeps_every_status_and_printed_section_before_shaping` plus `test_retest_mode_is_the_backward_compatible_default`. Invariant: no current retest field, filter, PoC promotion, evidence carry-over, route result, or legacy caller changes.
- [ ] **Step 2 — Recover editable engagement and scope with explicit diagnostics.** Files: `app/docx_import.py`, `tests/test_docx_import.py`. Parse canonical metadata/tables across all four templates, apply context-specific `N/A` handling, join internal wrapping, restore account/limitation rows, and implement the Web/API/component inference and warning rules above. Focused tests: `test_editable_import_restores_every_printed_engagement_field`, `test_editable_scope_preserves_ambiguous_location_text_and_warns`, and a four-template capability matrix. Invariant: every source location string is represented or the import fails; a guessed channel/environment is never silent; engagement output validates without inventing unavailable identity.
- [ ] **Step 3 — Shape all statuses, sections, fragments, and evidence for editable mode.** Files: `app/docx_import.py`, `tests/test_docx_import.py`. Preserve the printed section matrix, note runs, numbering identity/continuation, table/caption ownership, tickets/CVSS, all reachable images, drawing width, and exactly one generated border layer; enforce the malformed/manual-edit boundary before materialising IDs and files. Focused tests: `test_editable_shape_keeps_all_known_statuses_and_printed_sections`, `test_editable_evidence_is_exactly_the_reachable_set`, `test_editable_image_width_and_single_border_survive_render_extract_render`, and parameterized unknown-status/heading/title/table/image corruption cases. Invariant: `Report.model_validate` passes, no source finding or represented body element disappears, IDs are unique, and every evidence reference has exactly one metadata/file counterpart.
- [ ] **Step 4 — Make generated Resolved remediation stable on both sides.** Files: `app/report_service.py`, `app/web/static/app.js`, `tests/test_app.py`, `tests/test_browser.py`. Reuse and normalize an existing `generated="resolved_remediation"` paragraph rather than replacing it with a fresh fragment; retain the current replacement behavior for any non-generated section outside editable import. Focused tests: `test_resolved_provisioning_reuses_the_generated_remediation_fragment` and `test_browser_resolved_provisioning_matches_the_server_without_reminting`. Invariant: visible Resolved behavior and reopening cleanup stay unchanged, while repeated provisioning is idempotent and the Python/JavaScript twins agree.
- [ ] **Step 5 — Add the backward-compatible route mode and one-write finalization.** Files: `app/main.py`, `tests/test_docx_import.py`. Accept optional `docx_mode`, reject invalid/misapplied values, select the shaper, validate editable output, provision it once in memory, assert its second-pass fixed point and evidence equality, then call the existing workspace import exactly once. Focused tests: `test_import_without_mode_remains_retest`, `test_route_imports_an_editable_docx_with_all_statuses`, `test_editable_import_is_unchanged_by_its_first_put`, `test_mode_is_rejected_for_a_bundle`, and `test_malformed_editable_import_writes_no_report_directory`. Invariant: old callers and ZIP/JSON behavior remain compatible; no unprovisioned or partially evidenced editable draft reaches disk.
- [ ] **Step 6 — Add mode choice, cancellation, and result disclosure to the manager.** Files: `app/web/static/manager.js`, `tests/test_browser.py`. Use `vrDialog.ask`, append the selected token, reset without fetching on cancel/Escape, and show the mode-specific summary/warnings with Open Setup/Stay on reports after success. Focused tests: `test_docx_import_offers_both_modes_and_cancel_sends_no_request`, `test_bundle_import_still_skips_the_mode_dialog`, and `test_docx_import_shows_warnings_before_navigation`. Invariant: the user knowingly chooses the transformation, cancellation creates nothing, and no warning is lost to immediate navigation.
- [ ] **Step 7 — Update contracts and run the focused regression set.** Files: `docs/DATA_MAP.md`, `docs/DOCX_TEMPLATE.md`, and, after Round 2 agreement, this handoff's implementation ledger/status. Correct the two established document-contract contradictions while recording the shipped behavior. Focused tests: `.venv/bin/python -m unittest tests.test_docx_import`, the named import/provision browser tests, then `.venv/bin/python scripts/relevant_tests.py --run` for the changed-file map. Invariant: documentation describes the code that shipped, current retest fixtures remain green, all four template variants pass without Word automation, and no full-suite-only platform failure is treated as part of this change.

### What I would not do

- **No post-processing of today's retest payload.** Resolved findings and original section roles are
	already gone by then; no later code can reconstruct them.
- **No second endpoint, workspace method, or persistence path.** One multipart field, the existing
	parser entry point, and `Workspace.import_report` are sufficient.
- **No `import_mode`, source-DOCX, provenance, or “already bordered” schema field.** None is needed
	after shaping, and each would burden every existing draft for request-time information.
- **No browser-side ZIP/DOCX parser.** Filename/MIME only decides whether to offer the chooser;
	server byte inspection remains authoritative.
- **No promise to restore the original draft.** Hidden sections, identities, offers, original image
	uploads, and unprinted fields are absent, so such a promise would be false.
- **No silent drop and no silent scope guess.** Representable text is retained with a warning;
	content that cannot be placed safely rejects the editable import.
- **No global relaxation of Resolved remediation without the product decision above.** Quietly
	preserving arbitrary Word edits would contradict the current locked/generated section on both
	sides; quietly overwriting them would discard user work.
- **No import-then-normalize save or preview endpoint.** In-memory finalization gives one atomic
	creation path and the existing response/dialog can disclose the result without consuming a
	backup or parsing the same document twice.

## Round 2 - Oracle: verdict on the proposal

**Answer**

Revise before agreement. The central boundary is sound: neutral extraction must happen before
`_findings` filters and renames content, `main.py` can legally validate and provision an editable
`Report` in memory, and the result can still reach one `Workspace.import_report` call without a
circular import or a second JSON save. The proposal is not factually closed yet: its unmatched-Web
scope fallback can strand or later delete recovered text, its literal fixed-point and atomic-write
language is too strong, its exact retest-compatibility claim is not covered by the proposed tests,
and its image-border rule cannot prove provenance and hard-codes a renderer value whose owner is the
fragment template.

The Resolved-remediation ID change is optional cleanup, not a prerequisite for editable import. It
is needed only if app-generated fragment identity is made part of the fixed-point contract; visible
and user-owned content can already be compared while excluding that generated ID.

### Every data-risk row, checked in both directions

| Planner row | Oracle verdict | Source check and correction |
|---|---|---|
| Stale write — **clear** | **Clear as scoped.** | Import creates a fresh report ID and has no prior revision to race. `Workspace.import_report` resets `report_id` and `saved_at`; the returned revision then seeds later optimistic PUTs ([workspace.py](../../app/workspace.py#L161-L179), [main.py](../../app/main.py#L651-L713)). This does not support the separate claim that the entire object is unchanged by its first PUT: `app_id` is still derived then and `saved_at` necessarily advances. |
| Lost update — **clear** | **Clear for lost updates; not an atomic-creation guarantee.** | Parsing and provisioning can finish before the one import call, and no existing report is rewritten. However, `Workspace.import_report` saves `draft.json`, releases that save lock, and only then writes PNGs; rollback removes the directory on failure, but another process can briefly observe JSON whose evidence files are not present ([workspace.py](../../app/workspace.py#L161-L179), [workspace.py](../../app/workspace.py#L302-L377)). “One existing persistence path” is accurate; “one atomic creation path” is not. |
| Orphan reference — **RISK** | **Confirmed. Control is almost right, but one stated equality is wrong.** | `Report.validate_references` requires every non-null image reference to exist, but permits unreferenced evidence metadata; `Workspace.import_report` separately requires metadata file paths to equal supplied file paths ([models.py](../../app/models.py#L374-L415), [workspace.py](../../app/workspace.py#L161-L168)). The asserted equality must be **non-null image `evidence_id`s = evidence-registry keys = IDs represented by supplied file paths**. Fragment IDs are a different namespace and cannot equal evidence IDs. Empty generated image slots have no evidence ID and are excluded. |
| Silent stranding — **RISK** | **Confirmed and not controlled by the proposal. Blocker.** | The fallback “put every unmatched detail location under Web” fails for API-only and component-only coverage. Both `scope_has_location` and its browser twin ignore custom locations outside tested channels, the Findings UI renders custom editors only for tested channels, and the first PUT's `reconcile_targets` removes out-of-coverage custom entries ([report_service.py](../../app/report_service.py#L621-L721), [report_service.py](../../app/report_service.py#L771-L789), [app.js](../../app/web/static/app.js#L1166-L1185), [app.js](../../app/web/static/app.js#L2475-L2513)). If it was the finding's only location, the PUT rejects as a removed reference; if another location remains, the unmatched text can be silently discarded. Landing on Setup does not by itself make that value visible or safe. |
| Schema compatibility — **clear** | **Clear.** | All proposed report values already fit schema `1.4`; mode and diagnostics remain outside `Report`, and omitted internal fields already have defaults ([models.py](../../app/models.py#L140-L151), [models.py](../../app/models.py#L199-L267), [models.py](../../app/models.py#L342-L415)). No migration or version bump is justified. |
| Provisioning fixed point / derived-state fight — **RISK** | **Confirmed, but the control is incomplete and the word “fixed point” is overloaded.** | `provision_report` can normalize sections and image slots in memory. A second pass can prove a **provisioning/user-owned projection** is stable. It cannot prove the whole persisted report is a fixed point: import and PUT own identity/revision fields, the first PUT derives `app_id`, and browser `scope_text` causes target reconciliation ([main.py](../../app/main.py#L261-L265), [main.py](../../app/main.py#L651-L713), [app.js](../../app/web/static/app.js#L1539-L1581)). Also, `Report.model_validate` does not run `setup_input_issues`, `finding_input_issues`, or component-scope validation, so a Word-edited value can import successfully and fail its first PUT ([report_service.py](../../app/report_service.py#L153-L224), [report_service.py](../../app/report_service.py#L621-L721)). The comparator and named test must state their exclusions and exercise a real first-PUT payload. |
| Python/JavaScript rule drift — **RISK** | **Real for the mode token; overstated for Resolved ID reuse.** | `manager.js` and `main.py` must agree on `editable` and `retest`. If Resolved reuse is implemented as a product rule, keeping `report_service.provision` and `app.js` conceptually aligned is prudent. It is not needed for the import's first-save path: browser `provision` is called only when adding a finding or changing status, not on boot or every save ([app.js](../../app/web/static/app.js#L1087-L1110), [app.js](../../app/web/static/app.js#L2589-L2607), [app.js](../../app/web/static/app.js#L3689-L3700)). Python alone currently remints the generated paragraph on every PUT. |
| Request compatibility — **clear** | **Clear at the server boundary, with a client-classification edge.** | An optional multipart `Form` field fits the existing `UploadFile` route; omission can retain retest, invalid values can return 422, and byte inspection can reject a valid mode on non-DOCX bytes before the JSON/ZIP parser runs ([main.py](../../app/main.py#L302-L380), [main.py](../../app/main.py#L554-L571)). Existing callers send only `file`. In the manager, filename/MIME is only a cue: a DOCX named `.zip` silently takes the omitted-mode retest path, while a bundle mislabeled `.docx` gets a chooser and then the proposed mode-on-bundle 422. That is a real edge against the blanket statement “ZIP and JSON continue directly.” |
| Request/response asymmetry — **clear** | **Clear.** | Echoing mode in the response but never writing it into `Report` is ordinary request metadata. It does not interact with the unrelated request-only `scope_text` field. |
| Existing drafts — **clear** | **Clear for schema/load compatibility.** | No model field changes. The 14 current `draft.json` files are schema `1.4`; the only two current Resolved findings are in Fragment Coverage Demo and both already hold one canonical `generated="resolved_remediation"` paragraph ([draft.json](../../data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json#L110-L194), [draft.json](../../data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json#L607-L730)). ID reuse would only stop that internal ID from changing on later saves. Legacy unmarked canonical paragraphs are already marked or cleared by `load_path` ([workspace.py](../../app/workspace.py#L267-L301)). |
| Navigation trap — **clear** | **Change to RISK until the scope fallback is corrected.** | Setup is the correct first page for engagement and global-target repair, and Findings remains reachable afterward. But an out-of-coverage custom location is not drawn on Findings and is stripped/rejected by reconciliation as described above. Separately, “Stay on reports” can reload the list, but new application groups render collapsed by default, so the imported row is not necessarily visible ([manager.js](../../app/web/static/manager.js#L48-L74)). |
| Backup exhaustion — **clear** | **Clear for report JSON.** | Provisioning before `Workspace.import_report` yields one JSON creation; a new path has no prior file to copy into `draft.bak.json` ([workspace.py](../../app/workspace.py#L161-L179), [storage.py](../../app/storage.py#L18-L45)). Evidence remains the existing later-write/rollback sequence, so this row must not be used to claim transactionality across JSON and PNGs. |

Three risks are missing from the table: accidental changes to the legacy retest projection during
the refactor, image/resource exhaustion while decoding and rewriting embedded rasters, and the
temporary JSON-before-PNG visibility window. The last is existing behavior rather than a reason to
invent a second persistence path, but it must be described honestly.

### Parser and shaping boundary

The proposed boundary matches the source. `_summary_rows` still knows all three statuses, but
`_findings` claims a row and optional CVSS row, drops every status outside
`RETAINED_STATUSES`, then builds only three source sections and rewrites source Proof of Concept to
Previous Proof of Concept ([docx_import.py](../../app/docx_import.py#L374-L414),
[docx_import.py](../../app/docx_import.py#L443-L557)). A neutral record above that branch is the
last place all printed statuses and original section roles coexist. Private dictionaries are also
the right boundary: the neutral representation has document observations and ambiguity that do not
belong in `Report`.

The two shapers can share ID/evidence materialisation only after each has chosen its sections. They
must not share mode-specific normalization accidentally. Current retest behavior includes all of
the following, whether desirable or not:

- each `w:br`-wrapped scope segment becomes a separate target because `_scope_rows` calls
	`splitlines()` despite its contrary comment;
- note content is flattened to one unformatted run;
- adjacent lists of the same type merge without consulting numbering identity;
- imported image width is `None`, and the already bordered embedded raster is retained;
- component scope and most engagement fields are ignored; and
- unknown statuses are silently included in `dropped_resolved` with Resolved findings.

Those behaviors are visible in the implementation ([docx_import.py](../../app/docx_import.py#L253-L339),
[docx_import.py](../../app/docx_import.py#L349-L372), [docx_import.py](../../app/docx_import.py#L483-L557),
[docx_import.py](../../app/docx_import.py#L578-L632)), but the present tests do not pin the wrapped
scope, note formatting, list boundary, image width/raster, or malformed-status cases
([test_docx_import.py](../../tests/test_docx_import.py#L255-L350)). “Keep every existing test green”
therefore does not establish “no current retest field changes.” Either those transformations stay
editable-only and receive explicit retest regression tests, or the compatibility claim is false.

Numbering identity supports the narrower visible contract. Different `numId`s distinguish
independent lists, and reuse across an intervening image supports a later fragment with
`continue_numbering=True`. Two adjacent source fragments in one continued chain are indistinguishable
from one list fragment with the same items; the proposal correctly cannot promise original fragment
boundaries, and tests must compare visible list sequence and continuation rather than source object
shape ([docx_report.py](../../app/docx_report.py#L897-L932),
[docx_components.py](../../app/docx_components.py#L242-L321)).

### In-memory provisioning and Resolved remediation

There is no import cycle in the proposed route. `main.py` already imports both `parse_report_docx`
and the lower-level provisioning functions, while neither `docx_import.py` nor `report_service.py`
imports `main.py` ([main.py](../../app/main.py#L20-L25), [main.py](../../app/main.py#L261-L265)). It
can validate the editable payload, call `provision_report` on that model, validate its dumped form
again, compare a documented projection after a second provisioning pass, and pass the dump and
evidence files to `Workspace.import_report`. That workspace method validates once more, replaces
identity/revision/folder hint, and performs one JSON save. No new workspace method and no second
save are required.

The fixed-point assertion must exclude at least `report_id`, `app_id`, `saved_at`,
`_folder_name_hint`, app-created empty seed fragments/slots, and any explicitly permitted generated
fragment identity. The proposed test name `test_editable_import_is_unchanged_by_its_first_put` is
false literally: with `app_id="unnamed"`, the first PUT derives it from the restored app name, and
every successful PUT changes `saved_at`. A useful test must also submit the `scope_text` that Setup
actually seeds from stored targets; PUT without it does not exercise target reconciliation or the
out-of-coverage deletion above ([workspace.py](../../app/workspace.py#L161-L179),
[main.py](../../app/main.py#L680-L708), [app.js](../../app/web/static/app.js#L1539-L1581)).

Current server provisioning always replaces a Resolved remediation with a freshly minted canonical
paragraph. That is the only reason repeated provisioning changes its fragment ID
([report_service.py](../../app/report_service.py#L281-L335)). Reusing an existing canonical generated
paragraph is compatible with current drafts if and only if the reuse arm requires one paragraph
marked `resolved_remediation`, rewrites its text/runs to the canonical sentence, and still drops all
other remediation fragments exactly as today's Resolved branch does. Reopening must continue to
remove the marked paragraph, while an unmarked tester paragraph with the same words must continue to
survive on an open finding ([test_app.py](../../tests/test_app.py#L638-L670)).

That change is not necessary if the fixed-point comparison excludes app-owned IDs. The proposed
JavaScript edit is especially over-scoped as a necessity: the browser does not provision on page
load or ordinary save. If stable ID is retained as a deliberate invariant, changing both
implementations avoids a conceptual twin drift; otherwise both edits and their tests can be dropped
without weakening editable import.

### Multipart and manager flow

The backend contracts fit FastAPI's current multipart route:

- optional omission can mean `retest` for old clients and direct parser callers;
- `editable` and `retest` can be validated as the only tokens;
- a valid token on bytes that fail `is_report_docx` can be rejected before `parse_import`; and
- JSON/ZIP requests with no token continue through the existing branch.

If consistent structured diagnostics matter, token validation must happen in the endpoint rather
than relying only on FastAPI's request-validation response, because the latter does not pass through
the app's `HTTPException` diagnostic wrapper. The source does not otherwise constrain whether a
misapplied valid token is rejected or ignored; that is product policy.

The existing dialog API can implement both interactions without changes. `vrDialog.ask` accepts an
arbitrary action array, supports a designated cancel action, maps Escape/backdrop to that action,
and renders warning entries with `textContent` ([dialog.js](../../app/web/static/dialog.js#L7-L102)).
`home.html` already loads it before `manager.js` and already accepts DOCX files
([home.html](../../app/web/templates/home.html#L1-L4)). For the post-import prompt, making **Stay on
reports** the cancel/safe action gives Escape the stated result. Reloading alone does not guarantee
the new row is visible because `load()` creates closed application groups unless their folder was
already open; the claim must either be weakened to “refreshes the list” or the browser behavior must
open/focus the imported row ([manager.js](../../app/web/static/manager.js#L48-L74)).

### Recovery rules against the current DOCX

| Area | Verdict from current producer structure |
|---|---|
| Printed engagement | Supported for unchanged current templates: segment, app-name copies, report-type label, owner, report date, tester, both windows, account rows, and limitations are all emitted in known locations ([docx_report.py](../../app/docx_report.py#L229-L306), [docx_report.py](../../app/docx_report.py#L421-L488)). `N/A`, conflicting copies, empty coverage tables, and unavailable CI/BSN/internal identity remain genuine ambiguities. The proposal's defaults/rejections are policy, not facts recovered from the file. Restored strings must also be checked against save-time input rules or explicitly left as repairable. |
| Web/API global scope and long values | Environment and channel are explicit. Each target occupies one paragraph; generator wrapping is one or more `w:br`s inside that paragraph, so joining runs inside a paragraph and treating paragraphs as target boundaries is supported ([docx_report.py](../../app/docx_report.py#L386-L438)). The same paragraph boundary exists for each finding-location bullet ([docx_report.py](../../app/docx_report.py#L666-L705)). This correction must not leak into retest mode if exact legacy behavior is promised. |
| Finding scope association | The detail table retains environment and displayed value, not channel, target ID, selected-versus-custom provenance, or the pre-override target value ([docx_report.py](../../app/docx_report.py#L1409-L1424)). Unique `(environment, value)` matching is supportable. Cross-channel duplicates and unmatched values are not recoverable facts; a fallback must remain in covered state through the first PUT. The proposed unconditional Web fallback fails that requirement. |
| Component scope | The component caption supplies Mobile versus Thick Client, and each row supplies value, description, and order. Production-first order is real, but no row or boundary identifies where production ends and non-production begins ([docx_report.py](../../app/docx_report.py#L240-L261), [docx_report.py](../../app/docx_report.py#L472-L488), [test_docx.py](../../tests/test_docx.py#L1072-L1092)). Assigning all rows to Production when both environments are evidenced is deterministic but not recovered truth; warning and Setup repair are mandatory. Component wrapped values must also be joined by row paragraph, not `cell.text.splitlines()`. |
| Statuses and sections | All three status labels and every status-printed section are present and fit the current model. Hidden sections are absent. Strict summary/body/status/heading checks are justified for editable mode, but applying them globally would narrow the more permissive current retest importer ([docx_report.py](../../app/docx_report.py#L490-L523), [docx_report.py](../../app/docx_report.py#L750-L810)). Duplicate-title pairing must be occurrence/order based for the summary, body, and Asia rows; title-only CVSS matching is not enough for two same-title findings with different values. |
| Fragment semantics | Current components support the eight model fragment types and bold/italic/underline. Note-prefix removal can preserve remaining runs; list numbering can preserve visible restart/continuation; exact multiline paragraph and adjacent continued-list object boundaries remain unknowable ([docx_import.py](../../app/docx_import.py#L108-L220), [docx_report.py](../../app/docx_report.py#L1049-L1112)). A one-row table needs the proposed warning because the model requires a header/body interpretation that the visible row alone does not settle. |
| Image bytes, environment, caption, and width | The embedded raster and relationship, positional caption, generated PoC environment heading, and both drawing extents are present. Width recovery is supported for an unmodified proportional inline drawing; the model has no height/crop/rotation fields, so a non-proportional resize, `a:srcRect` crop, rotation, floating drawing, or multiple drawings in one owner must be detected and rejected or warned according to the supported-edit policy ([docx_import.py](../../app/docx_import.py#L223-L291), [docx_report.py](../../app/docx_report.py#L1184-L1223)). Capping a manually enlarged extent at 155 mm changes visible output and cannot be called faithful without a warning. |
| Generated raster border | Current generation really bakes a black border into a PNG and removes the vector line before embedding. But the width comes from `resources/fragments/image_fragment.docx`, and the raster floor comes from `IMAGE_BORDER_RASTER_DPI=192`; 0.75 pt is only the current template value/fallback, not an importer-owned constant ([docx_report.py](../../app/docx_report.py#L1427-L1489)). Expected-thickness black strips can be verified, but their generator provenance cannot be proved after arbitrary image replacement. A hard-coded 0.75 pt crop is therefore a new drift point. The semantic round trip must cover exact current output, retained-uncertain borders, crop/distortion metadata, and rounding at several widths. |
| Image limits | The DOCX ZIP has compressed and expanded-size bounds, but `_evidence_records` currently opens images without the per-image byte, pixel, or report-evidence limits used by bundle/image upload paths ([main.py](../../app/main.py#L178-L188), [main.py](../../app/main.py#L327-L380), [docx_import.py](../../app/docx_import.py#L560-L575)). Cropping/resaving makes this omission more consequential. The proposal needs an explicit limit/error test before raster work; a compressed PNG with extreme dimensions is not controlled by the DOCX package's expanded-byte sum. |

### Compatibility, missing surfaces, and missing checks

No proposed report shape breaks an existing `draft.json`: no field or literal changes, and current
Resolved drafts already have the shape an ID-reuse arm would consume. A draft previously imported
as a retest still cannot become editable without the original DOCX because the discarded findings,
sections, and evidence are absent. The real compatibility risk is forward behavior of **new retest
imports** after the parser refactor, not loading existing JSON.

Files the proposal missed:

- `docs/ROUTES.md` currently describes `/reports/import` as ZIP/JSON only; the multipart field,
	DOCX modes, rejection contract, and response shape belong there ([ROUTES.md](../ROUTES.md#L35-L50)).
- `docs/ARCHITECTURE.md` describes the DOCX path only as starting a retest; it needs the two-mode
	boundary once that is current behavior ([ARCHITECTURE.md](../ARCHITECTURE.md#L131-L142)).
- `app/docx_report.py` and `resources/fragments/image_fragment.docx` are a producer-side contract
	for border recovery even if no edit is ultimately required. Treating 0.75 pt/192 DPI as copied
	importer constants without a shared source or drift test is unsafe.

The existing dialog implementation and `home.html` do not need changes. `app.js` does not need a
Resolved-remediation edit unless stable generated identity is retained as a new invariant.

Checks missing or insufficiently specific in the proposed plan:

1. A normalized golden retest projection covering wrapped scope, styled notes, independent and
	 continued lists, current bordered image bytes/`width_mm=None`, unknown status, ignored
	 engagement/component data, and the existing permissive structural cases. Existing import tests
	 do not pin these.
2. A first-PUT test built from the same `scope_text` Setup seeds, asserting the documented changes
	 to `app_id`/revision while proving source content, associations, and evidence remain stable.
3. API-only and component-only unmatched-location cases proving warning text remains visible and
	 the location survives reconciliation; plus a finding with another valid location, which is the
	 branch where out-of-coverage text can otherwise disappear silently.
4. Save-time-invalid restored engagement/component values, not only Pydantic-invalid values and
	 ticket/CVSS rules.
5. Duplicate-title Asia findings with distinct CVSS values, so occurrence pairing rather than title
	 lookup is proved.
6. Image pixel/byte/aggregate limits, border-thickness rounding, black-edged source content,
	 uncertain/no border, non-proportional extents, Word crop metadata, and post-Word caption/field
	 form. The current self-consistency hash assertion does not pin prior bytes or appearance.
7. Manager tests for Escape/no request, both mode tokens, Stay/reload visibility, a DOCX with an
	 unhelpful MIME type, a byte-valid DOCX mislabeled as ZIP, and non-DOCX bytes mislabeled as DOCX.
8. Route tests for omitted, invalid, and misapplied mode values with both DOCX and bundle/JSON
	 bodies, and an assertion that malformed editable input invokes no workspace write.

The additional twins in play are the renderer/importer border parameters, `reconcile_targets` plus
Setup's `scope_text` seeding, and save-time input validation versus the browser's field rules. They
matter to first-save stability even though the extraction itself remains server-only.

### Product questions still open after source verification

1. Whether editable means a visible-semantic copy including all printed engagement values, or a
	 fresh engagement carrying findings only. The document supports the former for unambiguous
	 current-template values; source cannot choose the product meaning.
2. Whether ambiguous scope blocks import or persists with a fallback and warning. If fallback is
	 chosen, the current unconditional Web rule must be replaced by a rule that stays visible and
	 survives current coverage/reconciliation; source cannot decide which ambiguous channel or
	 component environment is truthful.
3. Whether arbitrary Word-edited Resolved remediation is rejected, or whether the app's locked,
	 generated ownership rule changes. Current behavior supports the proposal's rejection default
	 but does not make that product choice mandatory.
4. Which historical DOCX structures editable mode promises. There is no generator-version marker,
	 so this can only be a structural support policy.
5. Whether a matching black strip is sufficient authority to crop an embedded image, or uncertain
	 images are retained with a known extra-border warning. The source proves current generation adds
	 the strip; it cannot prove a later Word image replacement inherited that provenance.
6. Whether “retest unchanged” includes today's parser bugs and losses (wrapped-target splitting,
	 note-format loss, list merging, bordered bytes, and permissive malformed handling) or permits
	 fixes while retaining only the high-level retest transformation. The current proposal says both.
7. Whether save-time-invalid but structurally representable Word edits reject editable import or
	 create a draft explicitly marked for repair. Pydantic validity alone does not answer this.

### Evidence

- Graph traversal identified the owning path as `docx_import.parse_report_docx` →
	`main.import_report`/`main.provision_report` → `Workspace.import_report`; source verification is
	above and in [docx_import.py](../../app/docx_import.py#L443-L632),
	[main.py](../../app/main.py#L261-L265), [main.py](../../app/main.py#L554-L571), and
	[workspace.py](../../app/workspace.py#L161-L179).
- Schema/reference behavior was verified in [models.py](../../app/models.py#L74-L151) and
	[models.py](../../app/models.py#L342-L415).
- Provisioning, coverage, reconciliation, and save gates were verified in
	[report_service.py](../../app/report_service.py#L251-L480),
	[report_service.py](../../app/report_service.py#L621-L789), and
	[main.py](../../app/main.py#L651-L713).
- Producer structure was verified in [docx_report.py](../../app/docx_report.py#L229-L306),
	[docx_report.py](../../app/docx_report.py#L386-L488),
	[docx_report.py](../../app/docx_report.py#L490-L810), and
	[docx_report.py](../../app/docx_report.py#L1184-L1489), with existing assertions in
	[test_docx.py](../../tests/test_docx.py#L40-L330), [test_docx.py](../../tests/test_docx.py#L480-L527),
	and [test_docx.py](../../tests/test_docx.py#L1004-L1110).
- Client behavior was verified in [dialog.js](../../app/web/static/dialog.js#L7-L102),
	[manager.js](../../app/web/static/manager.js#L48-L164), and
	[app.js](../../app/web/static/app.js#L1087-L1282),
	[app.js](../../app/web/static/app.js#L1539-L1581),
	[app.js](../../app/web/static/app.js#L2475-L2513).
- Current regression coverage was checked in [test_docx_import.py](../../tests/test_docx_import.py#L1-L421),
	[test_app.py](../../tests/test_app.py#L638-L670), and
	[test_browser.py](../../tests/test_browser.py#L4232-L4285).

### Invariants in play

- Neutral extraction may observe ambiguity; only a mode shaper may drop, rename, seed, default, or
	mint report identities. Moving any of those decisions earlier makes the other mode lossy.
- Every non-null image evidence reference must resolve, every registry item must have exactly one
	supplied path, and editable mode's selected image occurrences must leave no extra registry/file
	entries. Confusing fragment IDs with evidence IDs makes the check meaningless.
- A recovered custom location must use an engagement-covered environment and channel before the
	first PUT, or current Python and JavaScript rules treat it as out of scope and reconciliation can
	reject or remove it.
- “Provisioned” does not mean “save-valid”: Pydantic references, save-time character rules, target
	reconciliation, and navigation completeness are separate gates.
- Editable import creates a new identity. A semantic fixed point can preserve visible/user-owned
	content while report identity, revision, folder hint, and app-owned placeholders legitimately
	differ.
- Retest default compatibility includes direct Python callers and multipart callers that omit mode.
	Any neutral-parser improvement visible in that output is a behavior change even if old tests miss
	it.

### Both-sides warning

- The request token is a `manager.js`/`main.py` contract and must use the same two exact values.
- Scope fallback and first-save stability cross `report_service.reconcile_targets`,
	`scope_has_location`, Setup's `scope_text` seeding, and the Findings custom-location renderer in
	`app.js`; checking the parser alone is insufficient.
- If generated Resolved-fragment identity becomes an invariant, Python and JavaScript should retain
	the same canonical-recognition rule. Under current call sites only Python remints on ordinary
	save, so the JavaScript edit is not independently required by this feature.
- Image border removal is a `docx_report.py`/fragment-resource/`docx_import.py` producer-consumer
	contract. A copied numeric constant is a drift-prone third implementation.
- Ticket/CVSS acceptance remains a Python save/import/browser character-rule family. Restored values
	must not widen one member silently.

### Map drift

None. `docs/DATA_MAP.md` still correctly says DOCX import is currently retest-only, provisioning is
owned by `main.provision_report` on PUT rather than `Workspace.import_report`, and import bypasses
target reconciliation. The proposal would require the planned map update when implemented, not
during this review.

## Round 2 - Planner: revised plan

### Understanding

Add an explicit editable-DOCX choice to the existing import endpoint and parser entry point while
keeping `Report` and `Workspace.import_report` as the only model and persistence path. Editable
means a new report identity whose supported, visible document semantics become an ordinary draft;
it does not restore hidden source-draft state. The parser must observe all printed findings and
sections before either mode shapes them, and the resulting editable report must survive the exact
first PUT that Setup sends without losing scope text, source content, associations, or evidence.
Identity, revision, folder hints, and app-owned empty/generated fragments are explicitly outside
that semantic-stability promise.

### Oracle corrections accepted

| Oracle contradiction or blocker | Revised design |
|---|---|
| An unmatched detail location stored unconditionally under Web can be hidden, filtered, or deleted. | Remove that fallback from both shapers. An unmatched or cross-channel-ambiguous location becomes an ordinary, selected **review target** in the same printed environment and in a channel that is included in engagement coverage. It is therefore visible on Setup, seeds into `scope_text`, and survives reconciliation. Every assumption is warned. The alternative is to reject ambiguity; that product choice remains open below. |
| A whole imported report cannot be a literal first-PUT fixed point. | Use the precise user-owned semantic projection defined below. The first PUT is expected to derive `app_id`, advance `saved_at`, and may refresh `_folder_name_hint`; those are asserted as expected changes rather than called instability. |
| `Report.model_validate` does not prove save validity. | Before persistence, editable mode runs `setup_input_issues`, `finding_input_issues`, a browser-equivalent `scope_text` reconciliation dry run, model validation after reconciliation, and provisioning. Blank-but-repairable fields remain allowed; a nonblank value that the next PUT would reject aborts the import before any workspace write. |
| The prior evidence equality mixed fragment IDs with evidence IDs. | The required equality is: non-null image `evidence_id`s in kept fragments = report evidence-registry keys = evidence IDs represented by supplied paths. Separately, supplied paths must equal the registry's `EvidenceItem.file` values. `frag_id` remains an unrelated uniqueness namespace. |
| `Workspace.import_report` is not transactionally atomic across JSON and PNG files. | Describe it accurately: all parsing and canonicalisation happen before one call; that call atomically writes JSON, releases its save lock, then atomically writes each PNG and removes the new report directory on failure. The existing brief JSON-before-PNG visibility window remains. No new persistence path is proposed. |
| Stable Resolved-remediation fragment IDs are optional. | Drop the `report_service.py` and `app.js` ID-reuse change. App-owned generated IDs are excluded from the semantic projection. Editable mode accepts the canonical generated Resolved remediation and rejects arbitrary Word-edited remediation under the recommended ownership policy, so no user-visible invariant needs stable generated IDs. |
| Existing tests do not prove retest compatibility. | Replace the absolute compatibility claim with the exact contract below and add a normalized retest golden before refactoring. High-level retest shaping remains; a short, enumerated set of neutral parsing/data-loss fixes intentionally changes both modes. No other parser improvement may leak into retest. |
| Automatic border cropping cannot prove provenance and would copy renderer/template constants. | Never crop an imported raster. Retain the embedded PNG exactly, validate it against bounded resources, recover only representable inline display width, and warn that regeneration can resample it and add another canonical border. No border width or raster-DPI constant is copied into the importer. |
| Filename and MIME are not authoritative classifiers. | The manager asks the existing endpoint to classify bytes with a `prompt` sentinel. A DOCX response requests a mode without writing; the manager then resubmits with `editable` or `retest`. ZIP/JSON imports complete on the first request. Omitted mode remains legacy retest for non-manager callers. |
| Reloading the manager does not make a new row visible. | “Stay on reports” reloads, opens the application group containing the returned `report_id`, scrolls the row into view, and focuses its report link. It does not merely refresh collapsed groups. |
| Documentation and cross-side checks were incomplete. | Include `docs/ROUTES.md` and `docs/ARCHITECTURE.md`; test the manager/server mode tokens, renderer/importer image contract, Setup seed/reconciliation path, save validators, all four templates, duplicate-title Asia rows, post-Word fields, classification mistakes, and list visibility. |

### Blast radius

| File | Revised change |
|---|---|
| `app/docx_import.py` | Keep `parse_report_docx` as the public entry point; add a raw neutral extraction, explicit retest/editable shapers, occurrence-based finding/CVSS pairing, bounded image inspection, strict editable integrity checks, covered review-target creation, exact evidence materialisation, and mode summaries. Do not crop or resave imported images. |
| `app/main.py` | Extend `POST /reports/import` with optional `docx_mode`; implement the byte-authoritative `prompt`/`editable`/`retest` contract; pass existing configured resource limits into DOCX parsing; run editable save/reconciliation/provisioning preflight; compare the user-owned projection; and make one `Workspace.import_report` call. |
| `app/report_service.py` | Add the smallest server helper that serializes `scope_targets` into the same `scope_text` shape Setup seeds, so import preflight can call the existing `reconcile_targets` instead of duplicating its rules. Do not change provisioning or Resolved ownership. |
| `app/web/static/manager.js` | Use `vrDialog.ask` after server byte classification, resubmit the selected mode, show counts/warnings before navigation, and make Stay on reports reveal and focus the imported row. Filename/MIME remain only native picker hints. |
| `tests/test_docx_import.py` | Pin the retest compatibility projection and intentional shared fixes; cover neutral extraction, editable shaping, all statuses/sections, engagement, four templates, duplicate titles, malformed structure, safe review targets, bounded images, exact evidence sets, width, post-Word forms, and semantic round trips excluding known image-appearance limits. |
| `tests/test_app.py` | Cover save-time-invalid restored fields, `scope_text` serialization/reconciliation, expected first-PUT identity/revision changes, no-write failures, mode validation/misapplication, resource limits, and the existing JSON-before-PNG rollback behavior without claiming transactionality. |
| `tests/test_browser.py` | Cover prompt classification, both modes, Escape/no persistence, mislabeled files, warning disclosure, Setup-seeded scope, API/component review-target visibility, and Stay on reports opening/focusing the imported row. |
| `tests/test_docx.py`, `tests/test_docx_captions.py` | Exercise the producer/consumer image and pre-/post-Word field forms where existing renderer helpers are the fixture source; no Word automation is required for semantic import tests. |
| `docs/DATA_MAP.md` | Record the two DOCX shapes, shared neutral corrections, request-only mode/probe fields, pre-import reconciliation/save validation, review-target rule, semantic projection, evidence equality, and honest persistence sequence. |
| `docs/DOCX_TEMPLATE.md` | Document editable visible semantics, supported structural envelope, occurrence pairing, no-crop image policy and limits, warning boundaries, all four templates, and correct the stale CVSS-regex/template-count statements. |
| `docs/ROUTES.md` | Document DOCX byte classification, `prompt`/`editable`/`retest`, omission compatibility, misapplied-mode errors, no-write prompt response, and success response. |
| `docs/ARCHITECTURE.md` | Replace “DOCX starts a retest” with neutral extraction followed by the two shapers and one existing workspace import path. |

`app/models.py`, `app/workspace.py`, `app/web/static/app.js`, `app/web/static/dialog.js`, templates,
`app/docx_report.py`, and `resources/fragments/image_fragment.docx` do not change. Their existing
contracts are exercised. In particular, no schema field, migration, second endpoint, new workspace
method, dialog API, border constant, or JavaScript provisioning rule is added.

### Open questions

These three decisions change the output shape or ownership rule, so agreement is blocked until they
are recorded in `## Answers`. The plan below is written against each recommended option and must be
revised before implementation if a different option is chosen.

1. **What product does “editable” create?** Option A creates a new identity while restoring every
	 unambiguous, save-valid value visible in a structurally supported DOCX: engagement, scope,
	 findings, printed sections, supported formatting, and evidence. It rejects a nonblank printed
	 value that the ordinary save route would reject. Option B carries findings/content into a fresh
	 engagement and deliberately blanks dates, tester, owner, accounts, limitations, and report type.
	 Option A gives the two choices distinct meanings and matches “edit the imported document”; Option
	 B overlaps heavily with the existing retest transformation. **Recommendation: Option A.** Under
	 either option, support is structural: the four current canonical layouts and older files that
	 satisfy the same fingerprints are accepted; “every historical report” is not promised because
	 the DOCX contains no generator version.
2. **When a printed finding location has no provable channel, should import preserve it in a visible
	 review target or reject the document?** Option A creates/reuses a normal target in the printed
	 environment and a deterministic covered channel, selects it on the finding, and warns with the
	 finding, value, and assumed channel. This can temporarily overstate global scope, but Setup shows
	 exactly what must be reviewed and the first PUT cannot filter it out. Option B rejects every
	 intrinsically cross-channel ambiguity and asks the user to repair the DOCX before importing; it
	 avoids a wrong assumption but makes otherwise editable reports unusable. **Recommendation:
	 Option A**, with the deterministic rule and first-PUT proof below. The old custom-Web fallback is
	 not an option because it can silently discard user text.
3. **Can Word-edited remediation on a Resolved finding override the app's generated ownership rule?**
	 Option A accepts only the canonical generated sentence and rejects any other Resolved remediation
	 before import. Option B makes that section tester-owned, which requires a separate Python and
	 JavaScript provisioning/editor change and changes every Resolved draft, not just imported ones.
	 **Recommendation: Option A.** This keeps the feature inside the import boundary and is why stable
	 generated-fragment IDs are deliberately dropped from this plan.

### Compatibility contract

`parse_report_docx(data)` and an omitted multipart mode still select retest. Retest continues to:

- retain the same known statuses it retains today and rewrite them to
	`open_previously_discovered`;
- move source Proof of Concept into Previous Proof of Concept, seed a fresh current proof and empty
	conclusion, and keep the existing engagement-freshening policy except for scope needed to avoid
	data loss;
- mint fresh report/finding/target/fragment/evidence identities;
- keep embedded raster bytes as evidence and keep `width_mm=None`; and
- preserve the existing `retained`, `dropped_resolved`, and `statuses_rewritten` summary keys for
	valid inputs.

Retest is **not** bug-for-bug frozen. One neutral reader is the smaller and safer implementation,
and these corrections intentionally affect both modes:

1. one generated scope/location paragraph is one value, with internal `w:br` wrapping rejoined;
2. note prefix removal preserves the remaining bold/italic/underline runs;
3. numbering identity preserves visible independent-list boundaries and continuation;
4. duplicate-title findings and Asia rows pair by occurrence/order rather than a title-only lookup;
5. unknown status, summary/body mismatch, or another structural contradiction that would silently
	 omit a finding/section rejects instead of entering `dropped_resolved`;
6. unmatched/ambiguous locations use the covered review-target policy instead of custom Web, with
	 component channel observations retained when needed for a component-only report; and
7. DOCX/package/image resource limits reject inputs that were previously unbounded.

No other editable behavior leaks into retest. Retest does not restore owner, tester, dates, windows,
accounts, limitations, or arbitrary hidden sections; does not recover display width; does not adopt
editable-only strictness for representable style loss; and still performs the retest status/section
transformation. A normalized golden fixture records the legacy output and the seven named deltas,
including summaries and evidence bytes, before the parser is refactored.

### Neutral and editable shaping

The neutral result is a private document observation, not a `Report`. It retains raw metadata
observations and conflicts; template capabilities; scope/account/limitation rows; one ordered record
for every summary occurrence; the corresponding body/detail/Asia occurrence; raw and normalized
status/scalars; every original section body; list numbering identity; supported runs; and each image
occurrence with relationship bytes, caption/environment observations, and drawing metadata. It does
not filter statuses, choose engagement defaults, rename a section, mint report IDs, flatten evidence
into a registry, or decide an ambiguous channel.

The shaper chooses sections and policy first. Only then does one materializer mint IDs and create
evidence metadata/files from image occurrences reachable through the selected contents. This makes
the feature-level evidence invariant stricter than the model's minimum:

`non-null image evidence IDs == evidence-registry keys == IDs represented by supplied paths`, and
`supplied paths == EvidenceItem.file values`.

| Area | Editable rule under the recommended answers | Error/warning boundary |
|---|---|---|
| Identity and unavailable state | Create fresh IDs and import timestamps. Leave CI/BSN, top-level dates, source library/offer state, provenance, and other values absent from the DOCX at defaults. `app_id` begins `unnamed` and is derived on first PUT. | State plainly that this is a new editable copy, not restoration of source identity or hidden draft state. |
| Engagement | Restore unambiguous printed segment, app name, owner, reversible report type, report date, tester, both windows, accounts, and limitations. Treat metadata/table `N/A` as the renderer's empty/default sentinel; retain literal `N/A` inside finding content. | Conflicting non-placeholder copies, unknown nonempty labels, invalid nonempty dates, or a nonblank value rejected by ordinary save validation reject before persistence. Missing values remain repairable blanks. |
| Findings | Preserve all three known statuses, visible order, title, display number, likelihood, impact, severity, tickets, and CVSS. Pair duplicate titles by occurrence across summary, body, and Asia rows. | Unknown/blank status, invalid enums, duplicate display IDs, invalid ticket/CVSS text, or contradictory repeated scalars reject; nothing is silently classified as Resolved. |
| Sections and fragments | Preserve every section printed for its status in its original role; preserve visible fragment order/types, text, supported runs, captions, code newlines, list restart/continuation, table text, and instance titles. Hidden status-inapplicable source sections remain unavailable. | Missing/duplicate/out-of-order reserved headings, unmatched findings, unowned content, unresolved captions, or unsupported structures that could omit/misassign content reject. Representable style loss warns. One-row table header/body ambiguity keeps the visible row and warns. |
| Resolved remediation | Recognize the exact canonical generated sentence, mark it generated, and allow existing provisioning to remint app-owned structure before import. | Any other visible Resolved remediation rejects under recommended question 3; it is never accepted and then overwritten. |
| Web/API/component scope | Recover explicit Web/API environment/channel rows and component channel/value/description/order. Join only generator wrap breaks inside one paragraph. Component rows with no encoded environment boundary use Production and warn when both environments are otherwise evidenced. | Conflicting component template/caption rejects. Every assumed component environment is reported. No row is silently omitted. |
| Finding locations | Use the covered review-target algorithm below. Exact source text and printed environment are retained; source selected-vs-custom provenance is not claimed. | Every inferred channel and every promoted review target is named in warnings. If the chosen product answer is strict rejection, the same cases fail before persistence instead. |
| Evidence | Materialize only kept image occurrences. Preserve each embedded PNG byte-for-byte with fresh metadata, hash, dimensions, and import timestamp; preserve supported caption/environment and editable width. Two occurrences remain two evidence records because source sharing is unknowable. | Missing relationship, non-PNG/undecodable image, ambiguous owner, crop/rotation/floating/non-proportional drawing, or resource excess rejects. Original upload bytes/name/EXIF/time and shared identity are explicitly unavailable. |
| Manual edits and historical files | Accept supported text/format edits that retain the current structural fingerprints. Structural equivalence, not filename, MIME, relationship IDs, or package byte identity, defines support. | Unknown older structures and edits that move content into text boxes, floating shapes, comments, footnotes, tracked-change-only text, or ambiguous owners reject rather than disappear. |

### Covered review-target policy

The source detail table gives an environment and displayed location but not a channel or original
target identity. For each location occurrence, both shapers apply this ordered rule:

1. Join only internal generated wrap breaks and keep the resulting text exactly. If exactly one
	 global target matches `(environment, value)`, select its ID.
2. If several channels match, choose the first matching channel in canonical `CHANNELS` order and
	 warn that the channel is ambiguous. If none matches, choose the only positively evidenced
	 channel when there is one; otherwise choose the first covered channel in canonical order. A
	 component template's identified Mobile/Thick Client channel is positive evidence.
3. Reuse or create an ordinary `ScopeTarget` for `(environment, chosen_channel, value)`, add the
	 printed environment and chosen channel to engagement coverage if absent, and select that target
	 on the finding. Reuse the same review target for repeated identical occurrences. A synthesized
	 component target keeps an empty description, so Setup visibly asks the user to supply it rather
	 than inventing prose.
4. Put the assumption in the summary with finding title, exact location, printed environment,
	 chosen channel, and whether an existing or synthesized target was used. Do not annotate or alter
	 the stored location itself.
5. Before import, serialize all targets exactly as Setup does, call `reconcile_targets`, and require
	 the review target ID and every finding association to survive. A mismatch is an import error, not
	 a warning.

This deliberately promotes an ambiguous finding-only location into visible global scope. That is a
recoverable overstatement, unlike a custom entry under an uncovered channel: the row is visible on
Setup, its checkbox is visible on Findings, and the first PUT cannot filter it away. No editable or
retest shaper writes unmatched text into `custom_locations.web`.

### User-owned semantic projection and first PUT

Define `editable_projection(report, evidence_files)` as:

- every engagement value recovered from the document;
- scope targets as ordered `(environment, channel, value, description)` tuples, excluding
	`target_id`, plus each finding's selected targets resolved to those tuples and its exact covered
	custom-location values;
- finding order and every visible scalar, status, printed-section role/order, and non-app-owned
	fragment semantic value; omit `uid`, `frag_id`, `generated`, empty seed paragraphs/lists/image
	slots, and canonical generated Resolved remediation;
- image-fragment environment, caption, representable width, and an evidence fingerprint composed of
	SHA-256, pixel dimensions, and exact supplied bytes, rather than fresh `evidence_id`; and
- no report/application IDs, revision/folder hints, import timestamps, schema/default bookkeeping,
	or unprinted library/offer state.

The route compares this projection at three points: immediately after editable shaping, after
in-memory provisioning, and after a dry-run reconciliation using Setup-seeded `scope_text` followed
by validation and provisioning. Any change to the projection rejects the import. App-created empty
structure may appear between points, and generated fragment IDs may change, without failing the
comparison.

The integration test is a real route sequence, not a second call to `provision_report`:

1. POST an editable DOCX and load the newly persisted report plus its evidence bytes.
2. Build `scope_text` exactly as Setup seeds it from the imported targets, including component
	 `{component, description}` pairs, and PUT the complete report with the imported `saved_at`.
3. Assert the save-time validators execute and the response is 200; the same target IDs are reused,
	 every selected association and review target remains, and no custom/location text is filtered.
4. Assert `report_id` is unchanged, `app_id` changes from `unnamed` to `app_id_for(engagement)`, and
	 `saved_at` strictly advances. `_folder_name_hint` and app-owned empty/generated fragment IDs are
	 allowed to differ.
5. Assert `editable_projection` and all persisted evidence bytes are identical before and after the
	 PUT. Include API-only and component-only unmatched locations, plus a finding that has both a
	 normal selected target and a review target so the formerly silent partial-loss branch is covered.

### Image and resource policy

The importer never attempts to detect or remove the generated black raster border. A black edge is
valid source content after arbitrary Word replacement, while the real border width belongs to
`image_fragment.docx` and rasterisation DPI belongs to the renderer. Copying either into the reader
would create an unprovable, drifting crop rule.

For editable mode, recover `width_mm` only from one proportional inline drawing with no crop,
rotation, or distortion and with a representable width at or below 155 mm. Reject unsupported
drawing geometry rather than pretending it round-trips. Retest keeps `width_mm=None` by contract.
For every imported report containing evidence, the result dialog warns that the stored file is the
rendered raster embedded in Word, not the original upload, and regeneration may resample it or add
another canonical border, changing edge thickness/appearance. Pixel equality across a regenerated
DOCX is therefore not part of the semantic projection.

Use the route's existing configured limits rather than new copied constants:

- DOCX upload: `MAX_BUNDLE_BYTES`;
- expanded package: `MAX_BUNDLE_UNCOMPRESSED_BYTES` and `MAX_BUNDLE_FILES`;
- each embedded image: `MAX_IMAGE_BYTES`, decodable PNG, and `MAX_IMAGE_PIXELS` before any full
	decode; and
- all materialized evidence bytes: `MAX_REPORT_EVIDENCE_BYTES`.

Pass these values into the parser as keyword-only limits. Catch Pillow decompression-bomb errors,
verify dimensions/format, and count only selected image occurrences toward the final aggregate.
Because bytes are retained rather than cropped/resaved, there is no second expanded raster whose
size could escape accounting.

### Request, response, and manager flow

- `docx_mode` is optional request metadata, never report data. Accepted values are `prompt`,
	`editable`, and `retest`; only the latter two are persisted import modes. Unknown values return a
	structured 422.
- The manager sends `prompt` for every selected file. If bytes are a DOCX, the endpoint returns
	`{source: "docx", mode_required: true}` without parsing into a report or calling the workspace.
	The manager asks with the existing `vrDialog.ask`, then resubmits the same `File` with the chosen
	mode. Cancel/Escape clears the input and makes no second request; the classification upload has
	happened, but no report or evidence has been written.
- If `prompt` bytes are JSON/ZIP, the endpoint imports them normally in that first request. Thus a
	DOCX named `.zip` still gets a choice and a bundle named `.docx` does not get a false DOCX choice.
	Filename and MIME are not consulted for authority.
- Omitted `docx_mode` keeps old callers and direct parser calls on retest. `editable` or `retest`
	supplied for non-DOCX bytes is a structured 422 rather than silently ignored.
- A successful DOCX response carries `report_id`, `source: "docx"`, selected `mode`, and `summary`.
	Bundle response compatibility remains `report_id` plus `source: "bundle"`. Editable summary lists
	counts, restored categories, review targets, incomplete-but-repairable fields, and all fidelity
	warnings. Retest keeps its current keys and adds warnings only for the named shared corrections.
- After a successful DOCX import, show the summary before navigation. Open Setup navigates. Stay on
	reports calls `load()`, finds the returned report row, opens its containing application group,
	scrolls it into view, focuses the report link, and announces success. Every mode still starts at
	Setup; no new navigation gate is added.

### Data risks

| Failure mode | Verdict | Control or accepted residual risk |
|---|---|---|
| Stale write | **clear** | Import creates a fresh ID. The imported revision seeds the first PUT; that PUT still uses ordinary optimistic concurrency and intentionally advances `saved_at`. |
| Lost update | **clear** | No existing report is read and rewritten. All shaping happens before the one existing import call; later PUTs remain under `save_if_current`. This does not claim atomic creation across files. |
| Orphan reference | **RISK** | Materialize evidence only after mode section selection; assert non-null image evidence IDs = registry keys = supplied-path IDs, supplied paths = registry files, target references resolve, and all IDs remain unique before the workspace call. |
| Silent stranding | **RISK** | Never use out-of-coverage custom Web. Review targets are covered, Setup-visible, selected, and subjected to an actual reconciliation dry run plus API-only/component-only/partial-loss first-PUT tests. Strict rejection remains the alternative product answer. |
| Schema break | **clear** | No model field, literal, or schema version changes. Existing drafts and JSON/ZIP imports need no migration or load repair. Previously lossy retest imports still require their source DOCX to become editable. |
| Request/response asymmetry | **clear** | `docx_mode`/`mode_required` and `scope_text` are explicitly request-flow state, never `Report` fields. Success responses identify the selected mode; bundle shape remains compatible. |
| Rule drift | **RISK** | Exact mode tokens are manager/server twins; Setup target serialization is Python/JavaScript behavior; safe location reachability crosses reconciliation and Findings rendering; image handling crosses renderer/template/importer. Add focused contract tests for each. No Resolved-provisioning twin is changed. |
| Navigation trap | **RISK** | Review targets are visible on Setup and selected on Findings. Missing component descriptions may block forward navigation but are visible on the page that repairs them. The result dialog names them, and Stay opens/focuses the imported row. |
| Derived-state fight | **RISK** | Compare the defined projection across shape, provision, reconciliation, and provision; run a real first PUT. Exclude only named app-owned identity/revision/generated structure, never source-derived content or location/evidence semantics. |
| Backup exhaustion | **clear** | Preflight is in memory and creation performs one JSON save. No import-then-normalize save consumes the single backup. |
| Retest regression | **RISK** | Establish a normalized golden first, preserve high-level shaping, enumerate exactly seven shared fixes, and assert no other output delta. Omitted-mode and direct-call tests pin the default. |
| Image/resource exhaustion | **RISK** | Reuse package, member-count, per-image byte/pixel, and aggregate evidence limits; verify before decode/materialisation; test compressed extreme dimensions, too many entries, one oversized image, and aggregate overflow. |
| Partial creation visibility | **RISK** | Existing `Workspace.import_report` can briefly expose JSON before PNG writes and rolls the directory back on failure. Keep and document that behavior; do not call it transactional or add a second storage path in this feature. |
| Filename/MIME misclassification | **RISK** | Manager `prompt` delegates classification to server bytes. Test valid DOCX bytes under ZIP/octet-stream labels and bundle/JSON bytes under DOCX labels. |

### Plan

- [ ] **Step 1 — Pin the compatibility baseline and named deltas before refactoring.** Files: `tests/test_docx_import.py`, `tests/test_docx.py`. Add one normalized golden covering status filtering/rewriting, section promotion, summary keys, wrapped scope, styled notes, independent/continued lists, duplicate titles/CVSS, component-only scope, bordered image bytes with `width_mm=None`, unknown status, ignored retest engagement, and permissive structural cases. Encode the seven intentional shared changes separately. Focused tests: `test_retest_default_preserves_the_retest_projection_except_named_neutral_fixes`, `test_retest_mode_and_omitted_mode_are_equivalent`, and `test_duplicate_title_asia_rows_pair_by_occurrence`. Protected invariant: parser refactoring cannot silently broaden editable behavior into retest or hide an intentional compatibility change.
- [ ] **Step 2 — Introduce raw neutral extraction and the two shapers behind the existing parser entry point.** Files: `app/docx_import.py`, `tests/test_docx_import.py`. Make `parse_report_docx(data, mode="retest", ...)` read once into private observations, then shape retest or editable; retain every summary/body occurrence and original section before selecting; implement the strict structural envelope and occurrence pairing; preserve all known statuses/printed sections in editable; enforce the recommended canonical-only Resolved remediation rule. Focused tests: `test_neutral_extraction_keeps_every_status_and_original_section`, `test_editable_shape_preserves_the_visible_semantic_projection`, parameterized malformed/unknown-status/heading/body-owner tests, and the four-template matrix. Protected invariant: no source finding, printed section, or represented body element is filtered before the mode decision.
- [ ] **Step 3 — Make scope reconstruction visible and first-PUT safe.** Files: `app/docx_import.py`, `app/report_service.py`, `app/main.py`, `tests/test_docx_import.py`, `tests/test_app.py`, `tests/test_browser.py`. Implement covered review targets, component observations and warnings, the shared `scope_text` serializer, reconciliation dry run, ordinary save validators, and `editable_projection`. Reject any preflight projection change or removed reference. Focused tests: `test_api_only_unmatched_location_becomes_a_covered_review_target`, `test_component_only_review_target_is_visible_and_survives_reconciliation`, `test_one_valid_and_one_ambiguous_location_cannot_lose_the_ambiguous_text`, `test_setup_scope_seed_matches_the_server_serializer`, and invalid restored engagement/component/additional-information cases. Protected invariant: every printed location is either represented in visible covered state or the entire import fails before writing.
- [ ] **Step 4 — Bound evidence and adopt the no-crop fidelity contract.** Files: `app/docx_import.py`, `app/main.py`, `tests/test_docx_import.py`, `tests/test_docx.py`, `tests/test_docx_captions.py`. Pass existing configured limits into parsing; validate PNG format, bytes, pixels, member count, aggregate selected evidence, relationship ownership, and supported inline geometry; preserve bytes exactly; recover editable width only when representable; emit the appearance warning. Focused tests: per-image byte/pixel and aggregate limits, compressed extreme dimensions, too many package members, black-edged source, uncertain/no border retained unchanged, several width/rounding cases, crop/rotation/non-proportional rejection, exact current renderer output, and pre-/post-Word captions/fields. Protected invariant: import never crops user pixels, never allocates an unbounded raster, and every kept image has one exact registry/file/reference chain.
- [ ] **Step 5 — Add the byte-authoritative mode protocol and one-write import finalization.** Files: `app/main.py`, `tests/test_app.py`, `tests/test_docx_import.py`. Accept `prompt|editable|retest`, keep omission as retest, reject unknown or mode-on-non-DOCX requests, return no-write mode-required responses, preflight editable reports, then invoke `Workspace.import_report` once. Add the real POST/load/Setup-seeded-PUT test with expected `app_id` and `saved_at` changes, target-ID reuse, projection equality, evidence-byte equality, and save-time validation. Also assert malformed/preflight/resource failures call no workspace write, while an injected PNG-write failure retains current directory rollback semantics. Protected invariant: old callers remain usable, no unprovisioned editable revision reaches disk, and the design does not overstate JSON/PNG atomicity.
- [ ] **Step 6 — Add the manager choice, disclosure, and visible Stay result.** Files: `app/web/static/manager.js`, `tests/test_browser.py`. Send the prompt sentinel, ask only after authoritative DOCX classification, resubmit the chosen mode, clear on Escape/cancel, display counts and every warning, and reveal/focus the imported row when staying. Focused tests: both mode tokens; Escape makes no second request and the prompt created no report; DOCX named/MIME'd as ZIP/octet-stream; bundle/JSON named/MIME'd as DOCX; non-DOCX mode rejection; warning text rendered safely; Open Setup navigation; and Stay opening, scrolling to, and focusing a newly created application group. Protected invariant: the user knowingly chooses DOCX semantics, no warning is lost to immediate navigation, and the created draft is locatable without guessing which collapsed group contains it.
- [ ] **Step 7 — Update all four contracts and the implementation ledger.** Files: `docs/DATA_MAP.md`, `docs/DOCX_TEMPLATE.md`, `docs/ROUTES.md`, `docs/ARCHITECTURE.md`, and this handoff after agreement/implementation. Record the exact shipped decisions, correct the CVSS/template-count prose, tick the agreed steps, set the eventual shipped status/date/commit, and describe deviations. Focused check: search each contract for the old retest-only/ZIP-JSON-only statements and compare route/parser/model/workspace wording against source. Protected invariant: documentation never claims original-draft restoration, automatic border fidelity, or transactionality the code does not provide.
- [ ] **Step 8 — Run the focused regression set and refresh the graph.** Files: no product files beyond fixes exposed by these checks. Run `tests.test_docx_import`, the named import/reconciliation tests in `tests.test_app`, the named manager/Setup tests in `tests.test_browser`, and the relevant pure-Python renderer/caption cases; then run `scripts/relevant_tests.py --run` and `graphify update .`. Do not require Word automation for semantic import checks and do not treat the two documented macOS Word/`pywin32` failures as feature failures. Protected invariant: both modes, all four templates, both classification mistakes, the real first PUT, and resource/error paths are executable checks rather than prose claims.

### What I would not do

- **No custom-Web quarantine.** It is invisible or disposable outside Web coverage. A normal covered
	review target is visible and reconciles; strict rejection is the only safe alternative.
- **No new “unassigned location” schema field.** It would require model/browser/generator behavior,
	migration policy, and a new navigation gate for information the existing target UI can expose.
- **No duplication across every possible channel.** It preserves bytes but falsely multiplies the
	affected surface and can generate duplicate locations. One warned review target is reversible.
- **No post-processing of the current retest payload.** Resolved findings and original section roles
	are already gone. The branch must occur while the neutral record still owns them.
- **No second endpoint, parser, `Report` subtype, workspace method, or import-mode field on disk.**
	The existing endpoint, parser entry point, model, workspace import, and dialog are sufficient.
- **No import followed by an immediate normalizing save.** Preflight and canonicalization happen in
	memory so creation uses one report JSON write and does not consume a backup.
- **No claim of atomic report-plus-evidence creation.** Individual writes are atomic; the collection
	is not. Existing rollback is retained and the visibility window is documented.
- **No automatic border crop or “already bordered” report flag.** Provenance is absent, black pixels
	can be user content, and copied renderer/template constants would drift. Preserve bytes and warn.
- **No Resolved generated-fragment ID work.** It protects an internal identity excluded from the
	user-owned projection and adds a Python/JavaScript rule change unrelated to visible import value.
- **No filename/MIME authority and no browser ZIP parser.** Server byte inspection already exists;
	the prompt handshake reuses it without a dependency or a second classification implementation.
- **No claim that retest is bug-for-bug unchanged.** The seven shared corrections are named and
	tested; everything else remains mode-specific. Calling those changes “unchanged” would make the
	compatibility promise impossible to verify.
- **No best-effort acceptance when content cannot be assigned.** Warnings describe deterministic,
	reversible assumptions or known appearance limits. Any path that could omit, overwrite, or
	mis-own text/evidence rejects before `Workspace.import_report`.

## Answers

1. **Editable restores the visible report.** Create a new report identity, but restore every
	 unambiguous, save-valid value visible in the supported DOCX: engagement fields, scope, all known
	 finding statuses, every section printed for those statuses, supported formatting, and evidence.
	 IDs, hidden sections, provenance, library state, CI/BSN, and anything else the document does not
	 carry remain fresh or defaulted.
2. **Ambiguous locations become visible review targets.** Preserve the exact printed location and
	 environment, choose a deterministic channel already included in coverage (or add that coverage),
	 create or reuse a normal `ScopeTarget`, select it on the finding, and warn with the assumption.
	 The target must remain visible on Setup and Findings and survive a reconciliation dry run and the
	 first real PUT. Never quarantine unmatched text in an uncovered custom Web location.
3. **Noncanonical Resolved remediation is rejected.** Editable import accepts the app's exact
	 generated remediation sentence and marks it generated. Any other remediation content on a
	 Resolved finding returns a specific import error; this change does not redefine Resolved content
	 ownership or provisioning for existing reports.

## Agreed plan

Selecting a generated DOCX adds an explicit choice between **Editable draft** and **Retest draft**.
Editable creates a new report whose supported visible semantics match the document; it does not
claim to restore the original draft. Retest keeps the existing status/PoC transformation. ZIP and
JSON imports continue through the existing route and workspace path.

The manager first sends `docx_mode=prompt`, allowing the server to classify bytes without writing.
A DOCX returns `mode_required`; the manager then asks and resubmits `editable` or `retest`. Cancel
creates no report. JSON/ZIP imports complete on the first request. Existing callers that omit the
field retain retest behavior, and a DOCX mode on non-DOCX bytes is rejected. Import mode remains
request metadata and is never stored in `Report`.

Editable supports the four current canonical structures and older documents matching those
fingerprints. It preserves all three known statuses and every section printed for each status.
Structural contradictions that could omit or misassign content reject before persistence;
deterministic, reversible assumptions produce warnings. Embedded PNG bytes are retained exactly,
never cropped, and bounded by the existing package/image/report limits. The summary warns that they
are rendered Word copies and may be resampled or receive another border when regenerated.

The neutral reader intentionally corrects seven losses for both modes: wrapped scope paragraphs are
kept as one value; note formatting survives prefix removal; numbering identity preserves visible
list boundaries/continuation; duplicate-title findings and Asia rows pair by occurrence; unknown
statuses and structural contradictions reject rather than disappear; ambiguous locations use the
covered review-target rule; and DOCX/image resource limits are enforced. A golden retest projection
pins every other behavior, including its fresh-engagement policy and current summary keys.

- [x] **Step 1 — Pin the retest baseline and seven named corrections.** Files:
	`tests/test_docx_import.py`, `tests/test_docx.py`. Add a normalized golden covering status
	filtering/rewriting, PoC promotion, summary keys, engagement defaults, fragments, scope, duplicate
	titles/CVSS, component scope, image bytes, malformed input, and the seven intentional deltas.
	Tests: `test_retest_default_preserves_the_retest_projection_except_named_neutral_fixes`,
	`test_retest_mode_and_omitted_mode_are_equivalent`, and duplicate-title Asia pairing. **Invariant:**
	neutral-reader work cannot silently change retest beyond the enumerated corrections.

- [x] **Step 2 — Extract neutrally, then shape editable or retest.** Files: `app/docx_import.py`,
	`tests/test_docx_import.py`. Make `parse_report_docx(data, mode="retest", ...)` retain every
	summary/body occurrence, original status, printed section, fragment observation, and image owner
	before either shaper filters, renames, defaults, or mints IDs. Editable restores all supported
	visible engagement values and sections; it accepts only canonical generated Resolved remediation.
	Tests: neutral retention, all-status editable projection, four-template matrix, and parameterized
	malformed status/heading/body-owner cases. **Invariant:** no source finding, printed section, or
	represented body element is lost before the mode decision.

- [x] **Step 3 — Make recovered scope visible and first-save safe.** Files: `app/docx_import.py`,
	`app/report_service.py`, `app/main.py`, `tests/test_docx_import.py`, `tests/test_app.py`,
	`tests/test_browser.py`. Recover explicit Web/API/component targets; implement the covered
	review-target policy; add one server helper that serializes targets into the same `scope_text`
	shape Setup seeds; run save validators, reconciliation, validation, and provisioning in memory.
	Tests: API-only, component-only, and mixed valid/ambiguous locations; Setup/server serialization
	parity; invalid restored fields; and no-write preflight failures. **Invariant:** every printed
	location is visible in covered state and survives reconciliation, or the whole import fails before
	writing.

- [x] **Step 4 — Bound evidence and preserve imported pixels.** Files: `app/docx_import.py`,
	`app/main.py`, `tests/test_docx_import.py`, `tests/test_docx.py`, `tests/test_docx_captions.py`.
	Pass existing upload/package/member/image/pixel/aggregate limits into parsing; verify PNGs and
	image ownership before full materialization; preserve selected bytes exactly; recover editable
	width only from supported proportional inline geometry; reject crop, rotation, distortion,
	floating drawings, and unresolved relationships. Tests cover every limit, extreme dimensions,
	black-edged/no-border input, width rounding, unsupported geometry, and pre/post-Word caption
	forms. **Invariant:** import never removes user pixels or allocates an unbounded raster, and
	non-null image evidence IDs, registry keys, and supplied-file IDs are exactly equal.

- [x] **Step 5 — Add the byte-authoritative route protocol and one-write preflight.** Files:
	`app/main.py`, `tests/test_app.py`, `tests/test_docx_import.py`. Accept
	`prompt|editable|retest`; keep omission as retest; return a no-write `mode_required` response for
	prompted DOCX bytes; reject invalid or misapplied modes; compare the defined user-owned semantic
	projection before/after provisioning and reconciliation; then call `Workspace.import_report`
	once. Run a real POST/load/Setup-seeded-PUT test asserting target-ID reuse, content/evidence
	stability, expected `app_id` derivation, and increasing `saved_at`. Also pin no-write failures and
	existing directory rollback after an injected PNG-write failure. **Invariant:** no unprovisioned
	editable draft reaches disk, old callers remain valid, and the implementation does not claim
	transactionality across JSON and PNG writes.

- [x] **Step 6 — Add the manager choice and disclose the result.** Files:
	`app/web/static/manager.js`, `tests/test_browser.py`. Send the prompt sentinel for every selected
	file; ask with the existing dialog only after server DOCX classification; resubmit the chosen
	mode; clear on cancel/Escape; show counts and every warning before navigation. **Open Setup**
	navigates; **Stay on reports** reloads, opens the containing application group, scrolls the new
	row into view, and focuses its link. Tests cover both modes, cancel/no persistence, misleading
	filenames/MIME types, safe warning rendering, navigation, and row focus. **Invariant:** the user
	knowingly chooses DOCX semantics and neither warnings nor the newly created report disappear from
	view.

- [x] **Step 7 — Update the four contracts and implementation ledger.** Files:
	`docs/DATA_MAP.md`, `docs/DOCX_TEMPLATE.md`, `docs/ROUTES.md`, `docs/ARCHITECTURE.md`, and this
	plan. Document the two modes, visible-semantic boundary, review targets, validation/reconciliation
	preflight, evidence equality and limits, no-crop warning, prompt protocol, and existing
	JSON-before-PNG visibility window. Correct the known CVSS-regex and template-count prose drift.
	Check: search each document for obsolete retest-only and ZIP/JSON-only claims. **Invariant:** the
	contracts do not promise original-draft restoration, automatic border fidelity, or persistence
	atomicity the code does not provide.

- [x] **Step 8 — Run focused regressions and refresh the graph.** Files: only fixes exposed by the
	checks. Run `tests.test_docx_import`, the named import/reconciliation tests in `tests.test_app`,
	the named manager/Setup tests in `tests.test_browser`, relevant pure-Python renderer/caption tests,
	then `.venv/bin/python scripts/relevant_tests.py --run` and `graphify update .`. Microsoft Word is
	not required for semantic import tests; the two documented macOS Word/`pywin32` failures remain
	out of scope. **Invariant:** both modes, all four templates, byte-classification mistakes, first
	PUT behavior, and bounded error paths are executable checks rather than prose assumptions.

### Implementation deviations

The parser retained one public, locally branched extraction flow rather than introducing named
neutral/retest/editable shaper classes; structural validation, source-section construction, and
evidence ownership still occur before mode filtering, so the behavioral boundary is unchanged.
Most new image/resource mutations live in `tests/test_docx_import.py` instead of being split across
renderer/caption modules, with the existing pure-Python renderer and caption tests used as the
cross-module regression checks. Visual verification also exposed one mobile-only chooser wrap, so
three-action dialogs now stack below 760 px. The final relevant-test run passed every portable check;
the repository's two documented Microsoft Word/`pywin32` tests remained unavailable on macOS.

### Rejected alternatives

- Do not post-process today's retest payload: Resolved findings and original section roles are gone.
- Do not add a second endpoint, parser, report subtype, workspace method, schema field, or migration.
- Do not store ambiguous text in custom Web, duplicate it across channels, or add an unassigned
	location field. A warned covered review target is visible and reversible.
- Do not import and then normalize with a second save, or claim report-plus-evidence creation is
	transactional. Preflight in memory and keep the existing rollback path.
- Do not crop black borders or add an `already_bordered` flag. Border provenance is unavailable.
- Do not change Resolved provisioning or preserve arbitrary Word-edited Resolved remediation.
- Do not trust filename/MIME or parse DOCX in the browser. Server byte inspection remains the
	authority.