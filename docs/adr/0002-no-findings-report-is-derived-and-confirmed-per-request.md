---
status: accepted
---

# A no-findings report is derived from its empty finding list and confirmed on each Generate

A report is a no-findings report when it has no findings of any status. Nothing in the draft marks it: there is no Report Type value for it and no saved flag. The tester confirms it every time they generate, the confirmation travels with the Generate request as `confirm_no_findings`, and the server refuses a report with no findings that arrives without it.

## Considered options

- **A fifth Report Type value.** Rejected because the report type prints on the title line, so an annual pentest that found nothing would stop saying Annual Pentest.
- **A saved flag, set when the tester confirms.** Rejected because the browser and the server would both have to keep it, an older build would drop it, and it would go stale as soon as a finding is added or deleted in another tab.
- **A confirmation in the browser only.** Rejected because Generate builds from the saved report. If another tab deletes the last finding, a page that still shows it opens no dialog, and the server would print a report nobody confirmed.

## Consequences

- Adding a finding turns a no-findings report back into a normal one, and deleting the last finding turns a normal report into a no-findings report. There is nothing to reset either way.
- Every way to generate needs the confirmation: the Generate dialog, `?confirm_no_findings=true` on the download address, and `--no-findings` on `scripts/generate_report.py`.
- A refused request tells the tester to reload, because the page does not fetch the report again when Generate has nothing to save.
