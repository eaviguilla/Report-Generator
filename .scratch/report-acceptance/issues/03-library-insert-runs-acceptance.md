# Library insert runs acceptance

Status: needs-triage

`POST /reports/{id}/library/{library_id}` builds the new finding inside the route, provisions only
that finding, and saves after checking the revision header. It runs none of the field checks.

Through acceptance, an insert would be refused whenever any other field in the stored report is
invalid, and every finding would be provisioned rather than only the new one. Building the finding
from the library entry could also move out of the route on its own, without acceptance.

To decide: is a refusal on the Findings page over an unrelated field wanted, or should only the
finding-building move?

From [docs/plans/report-acceptance.md](../../../docs/plans/report-acceptance.md).
