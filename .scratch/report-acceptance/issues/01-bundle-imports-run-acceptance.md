# Bundle imports run acceptance

Status: needs-triage

A JSON or ZIP bundle import goes through `Workspace.import_report`, which only validates the model.
Scope reconciliation, the Setup and finding field checks, and provisioning wait for the first
autosave. A bundle holding a value the field rules refuse, such as a hand-edited file, imports
cleanly and then its first save returns a 422.

Running `acceptance.check` and `acceptance.provision` before the write would refuse that bundle at
import, and would provision it at import instead of on the first save.

To decide: should the import refuse such a bundle, or import it and let the tester correct it, as now?

From [docs/plans/report-acceptance.md](../../../docs/plans/report-acceptance.md).

## Next steps

1. `/triage`: Filed by the report-acceptance plan. Nobody has evaluated it yet.
2. `/implement`: Small once agreed. Run acceptance before the import writes the bundle.
