# GWAM report name

> **Status:** ready-for-human, 2026-10-22. Steps 1 to 8 landed in code on 2026-10-22 and their tests pass here; the one step left is the check in Word on Windows (step 9).
>
> Settled in a `/grill-with-docs` session on 2026-10-22. The plan rewrote 12 lines in the four Word masters, and the owner approved that edit in the session.

## Request

> for gwam segment only, when it gets selected, add another field in the setups page for the report name as they have a different report name than other segments. this should also reflect in the generated report where report names are displayed including the footer. But the app name in the generated report still should go where app name goes in the report.

## Answers

[GLOSSARY.md](../../GLOSSARY.md) defines the terms this plan uses: Segment, Application name and Report name.

### What the report name is

The session first read the report name as the middle part of the title line. The owner corrected that:

> the report name field will be the whole title name as well as the document name after generation. app name and report name are different. the report name for jh is JH - appnamehere - Annual Pentest 2026. the appname is the 'appnamehere'. see in the report template that there are tags for appname only. but if the tag is with a tag of segment and report type, then it is a report name and will be replaced by the value in the report name field in the setup page if the user selected gwam

So the report name is the whole string. For GWAM the tester types all of it and the app prints it as typed. For every other segment the app builds it. The owner said the shape of a GWAM name does not matter.

| Name | Prints at |
|---|---|
| Report name | the cover title, footers 5 and 8 of every master, the file name of the Word report and the file name of the Export ZIP |
| Application name | the cover table's Application cell, the two "the X application team" sentences, the "X PENTEST" heading and its contents line, the scope sentence and its table caption, the Findings Summary caption, the banner and the home list |

### The Report Name field

- Only GWAM has it. One named list in the code, `REPORT_NAME_SEGMENTS`, holds the segments that have their own report name. GWAM is its only member, so a second segment is a one-line edit.
- It sits directly after Application Name, shows only while the segment is GWAM, starts empty, and has the required star only while shown. Its `title` reads "Printed on the cover and in the footers, and used as the file name." It has no placeholder.
- An empty name for GWAM is an Issue. The tester cannot go past Setup or build the Word report. There is no fallback to the application name, because that would print the wrong name with nothing on screen to say so.
- Characters are those of Application Name (letters, digits, spaces and `-:;.()[]#`) plus `/` and the en dash, up to 200 UTF-16 units. The Application Name rule does not change. The en dash is there because the masters print en dashes, so an Editable copy of an old GWAM report fills the field with them.
- It is checked, and counted as an Issue, only while the segment is GWAM. Switching the segment away hides the field and keeps its text. Nothing prints or checks the text, and switching back shows it again. This is also why a kept hidden value can never block a save.
- Existing GWAM drafts have no name, so they show the Issue until the tester types one. Nothing on disk is rewritten. A one-time fill would use up each draft's single `draft.bak.json` and print the application name as the report name.
- The data is `Engagement.report_name: str = ""`. The schema stays at 1.4 with no repair, as `network` did ([DATA_MAP.md](../DATA_MAP.md) §6). A schema bump would make every draft and export fail to load.

### The Word report

- The cover title and footers 5 and 8 each hold only `{{report-name}}`, in all four masters. The owner chose that over a generator rule that recognises a line made of the segment, name and report type tokens, and approved editing the masters, including removing the cover's plain `2026`.
- GWAM prints the Report Name as typed. Every other segment prints the built name: the segment, the application name, the report type label and the Report Date's year, joined with en dashes, which is the cover's form today.
- Two visible changes for every non-GWAM report, accepted by the owner. The cover's year follows the Report Date instead of the master's plain `2026`. The footers gain the year, and their first dash becomes an en dash so they match the cover.
- The footer text `GCSAppSec_Report2026v1` stays. It looks like a template ID, not a year.
- `{{report-name}}` stops meaning the application name. Today it holds that value, and only footers 5 and 8 carry it. `{{app-name}}` is unchanged.

### File names

A GWAM Word report and its Export ZIP are named from the Report Name. The name is cleaned as `report_export_filename` cleans parts today (illegal characters removed, non-ASCII dropped), with the en dash turned into a hyphen first, and cut at 150 characters. That is about the longest name the app already makes, and the files go into `generated/` under the project folder, where Windows stops paths at 260 characters. A name that cleans to nothing falls back to today's name. Other segments keep today's name.

### Import

The importer finds the cover title as it does today: the first of the first 20 body paragraphs that splits on a spaced dash into three or more parts, the first part being a segment. For a segment in `REPORT_NAME_SEGMENTS`:

- **Editable copy.** `report_name` is the title paragraph as printed. `app_name` is the value in the cover's Application cell, with the title's middle parts, as read today, when the cell is empty. A report made before this change has the same text in both places and imports with a Report Name equal to its old title. A stored value that breaks the character rule stays savable and shows as an Issue on Setup, as any imported value does.
- **Retest import.** `app_name` comes from the cell and the segment is GWAM. `report_name` stays empty, because the old name carries the old test's type and year, and the Issue asks for the new one.
- **Unknown last part.** In an Editable copy, a title whose last part is not a known report type gives a warning and leaves `report_type` empty, instead of the "Unknown report type" refusal. A free-text name can end in anything. Retest import never reads the type.
- **No segment first.** A title that does not start with a segment gives nothing, as today, and the tester picks GWAM and types the name again.

Other segments import exactly as they do today.

### Not done

- No check that the typed name agrees with Report Type or Report Date.
- No prefill of the Report Name and no fill of existing GWAM drafts.
- No change to the Application Name rule.
- The banner and the home list keep showing the application name.

## Agreed plan

Write each test first and watch it fail. Steps 5 and 6 land in one commit: with only step 5, the footers would print the segment and report type twice.

- [x] **Step 1. Field, list and vocabulary.** [app/models.py](../../app/models.py): add `report_name: str = ""` to `Engagement`, with a comment like the one on `network`, and `REPORT_NAME_SEGMENTS: tuple[Segment, ...] = ("GWAM",)` beside `Segment`. [app/vocabulary.py](../../app/vocabulary.py): `client_vocabulary()` sends `report_name_segments`. No schema bump and no `load_path` repair.
  *Test:* a `draft.json` with no `report_name` loads with `""` and round-trips (the `network` precedent in `tests/test_app.py`), and the vocabulary carries the list.

- [x] **Step 2. Rules in Python and JavaScript.** [app/report_service.py](../../app/report_service.py): add `CHARACTER_RULES["report_name"]` with label "Report name", symbols `-:;.()[]#/` plus `\u2013`, and `max_length=200`. `setup_field_refusals` checks it only when the segment is in `REPORT_NAME_SEGMENTS`, right after `app_name`. `setup_results` adds the issue `missing_report_name` directly after `missing_segment`, with the message "Enter the report name." in `format_rule_message`. [app/web/static/rules.js](../../app/web/static/rules.js): the same three changes in `fieldRefusals`, `setupResults` and `formatRuleMessage`, reading the list from `vocabulary.report_name_segments`.
  *Tests:* the shared cases in `tests/test_rule_cases.py` that `test_setup_results`, `test_setup_field_refusals` and `test_rule_messages` run against both languages. Cases: GWAM with a blank name, GWAM with `&`, GWAM with 201 characters, GWAM with `/` and an en dash (no result), and JH with an invalid hidden value (no result). Also a save refusal and a save that ignores a hidden value in `tests/test_acceptance.py`.

- [x] **Step 3. Setup page.** [app/web/templates/page1_setup.html](../../app/web/templates/page1_setup.html): after the Application Name label, a label "Report Name" holding `<input data-path="engagement.report_name">`, hidden by default. [app/web/static/app.js](../../app/web/static/app.js) `setup()`: add `setupRules.report_name = setupRule("report_name")`, so the existing `[data-path]` loop binds the value, the character check and the 200-unit limit. Show or hide the label on load, on every segment change and after Undo or Redo. Add the star and `aria-required` only while it is shown, not through the static `REQUIRED_SETUP_FIELDS` map, and keep that map's comment true. `validateSetupPage` gets `["missing_report_name", "report_name"]` in `requiredMetadata`, after `app_name`, which is page order.
  *Tests:* `tests/test_browser.py`. Hidden for JH and shown for GWAM. Starred only for GWAM, with `test_setup_stars_exactly_the_fields_that_block_next` still true. Next blocked on an empty GWAM name. The text kept across GWAM, JH and GWAM. Undo and Redo of the segment change show and hide the field. `/` and the en dash accepted, `&` refused with the field's message.

- [x] **Step 4. The report name and the file names.** [app/report_service.py](../../app/report_service.py): add `report_name_for(report)`, which returns the typed name for a segment in `REPORT_NAME_SEGMENTS` and otherwise the built name, with `N/A` for a missing part as `_metadata` does for the other tokens. `report_export_filename` uses the cleaned Report Name for those segments, as the answers above describe, and keeps today's builder otherwise.
  *Tests:* `tests/test_app.py` next to `test_report_management_lifecycle`. The ZIP route, the download and the saved copy for a GWAM and a JH report, including `/`, `:` and an en dash in the name, a name over 150 characters, and an empty name.

- [x] **Step 5. Generator.** [app/docx_report.py](../../app/docx_report.py): `_metadata` sets `"report-name"` to `report_name_for(report)`. `_replace_metadata` replaces `report-name` after every other token and `report-name` leaves `PLAIN_METADATA_TOKENS`. The value is free text, and `replace_pattern_across_text_nodes` re-searches its own output, so a typed bare `report-name` would loop forever and a typed `app-name` would be rewritten.
  *Test:* no master or component document carries a bare `report-name`, and a GWAM name containing `app-name` and `report-name` renders as typed.

- [x] **Step 6. Masters (approved by the owner).** A one-off script, not kept in the repo, rewrites 12 paragraphs: the cover title in `word/document.xml` and the lines in `word/footer5.xml` and `word/footer8.xml`, in `MAIN.docx`, `MAIN_ASIA.docx`, `MAIN_THICK_MOBILE.docx` and `MAIN_THICK_MOBILE_ASIA.docx`. Each paragraph keeps its paragraph properties and its first run, whose text becomes `{{report-name}}`, and loses the other runs. Read on 2026-10-22: each of the three paragraphs is identical across the four masters, holds only runs, and has no run formatting that the replacement would lose. The one exception is a 14 pt run on footer 5's closing braces, which token replacement already drops. Before and after, compare every other zip member of each master and confirm it is unchanged, and keep the member order.
  *Tests:* each master's cover title, footer 5 and footer 8 hold only `{{report-name}}`. Extend `test_every_shipped_template_renders_without_unresolved_placeholders` and the render tests in `tests/test_docx.py` over the four masters with a JH and a GWAM report. The cover and both footers print the expected name. The application name still prints in the cover table's Application cell and the other places in the table above. `GCSAppSec_Report2026v1` still prints.

- [x] **Step 7. Import.** [app/docx_import.py](../../app/docx_import.py): add `APPLICATION_COVER_LABEL = "Application"`, read through `_labelled_value` as `NETWORK_COVER_LABEL` is. The label is unique in the masters: two paragraphs, both followed by the same value. Then the four cases in "Import" above.
  *Tests:* `tests/test_docx_import.py`. Each case, and a round trip: generate a GWAM report with a free-text name that starts with `GWAM - `, import it as an Editable copy, and get the same Report Name and application name back. `test_an_unknown_report_type_in_the_cover_title_lists_the_known_ones` and `test_every_segment_the_model_allows_parses_back_out_of_a_title` still pass.

- [x] **Step 8. Callers and docs.**
  - [scripts/generate_showcase_reports.py](../../scripts/generate_showcase_reports.py): the GWAM report, Meridian Commerce API, gets a report name, or it stops generating.
  - Fixtures in the tests that build, save or generate a GWAM report get one.
  - [DATA_MAP.md](../DATA_MAP.md): §6 for the field, §12 for the twin rules (the named list, the required name, the refusals) and §13 for the hidden value that is kept and ignored.
  - [DOCX_TEMPLATE.md](../DOCX_TEMPLATE.md): the token table, the cover and footer lines, and the import contract. That section says the importer's segment list is a separate copy. The code derives it with `get_args(Segment)`, so correct it while editing.
  - The comment in `app.js` near the Non-Production picker calls its label a "report name". Reword it to "label".
  - Run `scripts/relevant_tests.py --affected --run` once. Then tick the steps and write what deviated here.

- [ ] **Step 9. Check in Word, on Windows (needs a person).** Generate one GWAM report with a long name, about 150 characters, and one JH report. Check the cover title, both footers and the page count, and the file names. Only Word shows where pages break, and the long name may wrap. Set the status to `ready-for-human` while this is the only step left, and to `done` with the commit when it is checked.

### Traps

- A name containing `-vuln` or one of the other markers in `UNRESOLVED_MARKERS` aborts generation as "unresolved placeholders", because that check scans the whole rendered text. It already does this for any printed text, such as an application name. This plan does not change it.
- The cover's year now follows the Report Date. A report dated January 2027 for a December 2026 test prints 2027.
- The importer reads a title only when a segment comes first, so a GWAM name that does not start with the segment cannot be read back.

## What deviated

Steps 1 to 8 landed as agreed, but Setup needed more than the plan said. Hiding the field had to hide its message wrapper too, with a `[hidden]` rule for each because both set a `display`. A refusal left on a hidden field made Next focus nothing when another field was wrong, so hiding now blurs the field first and clears its refusal; the Spec review found that. The Application card's "n of 9" count included the hidden field until a test made it skip hidden ones; the browser check found that. `CONDITIONAL_SETUP_FIELDS` maps the new issue to its field beside `REQUIRED_SETUP_FIELDS`, and `vrRules.hasOwnReportName` is the one JavaScript test of the named list. Three existing tests changed with the field: the retest projection gained `report_name`, the every-segment title test types a name for GWAM, and the required-segment test types one after choosing GWAM. `resources/report-name.docx`, which both release scripts ship and nothing renders, still holds the old footer line.

## Next steps

1. `/implement`: On Windows with Word, generate one GWAM report with a long name, about 150 characters, and one JH report. Check the cover title, both footers, the page count and the file names, then tick step 9 and mark the plan done with the commit.
