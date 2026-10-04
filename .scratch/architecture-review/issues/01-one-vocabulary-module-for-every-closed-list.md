# One vocabulary module for every closed list

Status: done

Found by the [2 October 2026 review](../report.html#review-2026-10-02-c1), recommendation 1 and its top recommendation, rated Strong, in-process.

## Problem

Twelve closed lists, such as statuses, segments, app types and field character sets, were spelled 32 times across nine files, so adding the GFT segment took three hand edits and an update to the test that pins the option list.

## Solution

One Python module owns the lists, every page embeds them as JSON, and the JavaScript and templates read them from there.

## Benefits

- A new segment is one edit.
- 32 spellings become 12.
- Leverage: eight files read one table.
- Tests that pinned a copy of a list become unnecessary.

## Files

- `app/models.py`, `app/report_service.py`, `app/docx_report.py`, `app/docx_import.py`, `app/main.py`
- `app/web/static/app.js`, `app/web/static/manager.js`
- `app/web/templates/page1_setup.html`, `app/web/templates/library_editor.html`

## Outcome

Done in `37593ea`, "refactor: serve every closed list to the browser from one vocabulary". `client_vocabulary()` in `app/vocabulary.py` builds the JSON object that `_vocabulary.html` writes into every page. DATA_MAP §12, under "Closed lists are not twins", describes it.
