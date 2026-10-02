# Import reads Previous Proof of Concept headings as the current engagement's environments

Status: needs-triage

## What happens

A generated report prints an environment heading (`PROD:` or the non-production label) above proof-of-concept images, in Previous Proof of Concept as well as Proof of Concept. Previous Proof of Concept records an earlier engagement, but import treats its headings as evidence about this one.

- **Editable import** builds the tested environments from the test windows, the scope rows, and the environment of every imported image, including Previous Proof of Concept images (`evidence_environments` in `parse_report_docx`, read by `_editable_engagement`).
- **Component reports, both modes**: `_observed_environments` reads every environment heading in the document. When it sees more than one, `_component_rows` puts every component on Production and warns.

Example: a non-production-only retest whose Previous Proof of Concept shows last year's `PROD:` screenshot. Imported in editable mode, it comes back with Production ticked and no Production scope target, so Setup is incomplete until the tester unticks Production. In a mobile or thick client report, the component also lands on Production.

## Expected

Only Proof of Concept images count as evidence of the current engagement's environments. Previous Proof of Concept images keep their own environment and never add one to the engagement or decide a component's environment.

## Notes

- Found by reading the code; not reproduced yet.
- Retest import of web and API reports is unaffected: it takes tested environments from the scope rows only.
- Kept separate from the supporting-image change so that a failure in either can be traced on its own.
