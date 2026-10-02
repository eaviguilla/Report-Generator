# Retest DOCX imports run acceptance

Status: needs-triage

A DOCX imported in retest mode skips `finalize_editable_import` and goes straight to
`Workspace.import_report`, so it gets the same model-only validation as a bundle. Its retained
findings are provisioned on the first autosave, and a value the field rules refuse surfaces then as
a 422.

Running acceptance at import would provision the retained findings before the tester sees them, and
would refuse a document whose printed values the field rules reject.

To decide: refuse at import, or keep importing and let the first save report it?

From [docs/plans/report-acceptance.md](../../../docs/plans/report-acceptance.md).

## Next steps

1. `/triage`: Filed by the report-acceptance plan. Nobody has evaluated it yet.
2. `/implement`: Small once agreed. Run acceptance on retest imports.
