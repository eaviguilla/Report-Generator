# Rename runs acceptance

Status: needs-triage

`PATCH /reports/{id}/name` checks only the application name, with the same rule Setup uses since
`a2b2eac`. Through acceptance, a rename from the home page would be refused over any other invalid
field, which the home page can neither show nor fix.

Likely outcome: keep the rename as it is and close this as `wontfix`, unless a reason to run the
other checks appears.

From [docs/plans/report-acceptance.md](../../../docs/plans/report-acceptance.md).

## Next steps

1. `/triage`: The issue expects to close as wontfix unless a reason to run the other checks appears.
