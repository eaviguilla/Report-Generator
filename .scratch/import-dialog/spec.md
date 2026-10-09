# Import opens a dialog that takes a dropped file

Status: done (2026-10-09)

## Problem Statement

On the Reports page, Import opens the operating system's file picker straight away. A tester who already has last year's Word report open in a folder window still has to browse to it, because the page takes no dragged file. Dropping one on the page is worse: the browser opens or downloads the file, and the tester leaves the app.

For a Word report, the choice of how to import comes after the file, in a second pop-up with "Import as editable draft" and "Import as retest draft", and the page sends the file to the server twice. When an import fails, the message appears in the page's error panel, and trying the other choice means clicking Import and finding the file again. A Word report that fails shows a message starting "Select a valid VulnReport export:", which names the wrong kind of file. The pop-ups also say "draft", where testers say retest and editable copy.

## Solution

Import opens the import dialog, titled "Import a report". Its drop area reads "Click to choose, or drag a file here". The tester drags a Word report (.docx), an export (.zip) or a report's draft.json onto it, or clicks it to open the file picker. The dialog holds one file and shows its name.

For a Word report, two buttons at the bottom, Retest and Editable copy, each with one line saying what it does, import the file that way. For an export or a draft.json, one Import button imports it unchanged. Nothing imports until the tester clicks a button. Progress, failures and a Word report's result show inside the dialog, and after a failure the file stays there so the tester can try again. While the dialog is closed, a file dropped on the Reports page does nothing.

## User Stories

Opening the dialog and giving it a file

1. As a tester, I want Import to open a dialog instead of the file picker, so that I can drag a Word report straight from a folder window.
2. As a tester, I want to drop a file on the dialog's drop area, so that I don't have to browse to a file I can already see.
3. As a tester, I want to click the drop area to open the file picker, so that I can still browse for a file.
4. As a tester using only the keyboard, I want to reach the drop area with Tab and open the file picker with Enter or Space, so that I can import without a mouse.
5. As a tester, I want the drop area to show that it will take the file while I drag one over the dialog, so that I know where to let go.
6. As a tester, I want the file picker to list Word reports, exports and draft.json files, so that it doesn't offer files the dialog won't take.
7. As a tester, I want the dialog to show the name of the file it holds, so that I can check I picked the right one before importing.
8. As a tester, I want a second file I drop or choose to replace the first, so that fixing a wrong pick takes one more drop.
9. As a tester, I want to pick the same file again after closing the dialog, so that a second try doesn't need a renamed copy.
10. As a tester, I want a file that doesn't end in .docx, .zip or .json turned away at once with "Import takes a Word report (.docx), an export (.zip), or a report's draft.json.", so that I learn what the dialog takes before anything is sent.
11. As a tester, I want a drop of several files to import nothing and say "Drop one file at a time.", so that I never import a file I didn't mean to.
12. As a tester, I want a file the dialog turns away to leave the file it already holds in place, so that a stray drop doesn't cost me my pick.

Importing a Word report

13. As a tester, I want nothing picked when the dialog opens, so that every Word report import is a choice I made.
14. As a tester, I want Retest and Editable copy buttons at the bottom of the dialog, so that the click that chooses is the click that imports.
15. As a tester, I want one line under Retest reading "Starts the next test from the open findings. Each one's proof of concept becomes its previous proof of concept.", so that I know what a retest import does.
16. As a tester, I want one line under Editable copy reading "Brings the report back as it reads, so you can change it and build it again.", so that I know what an editable copy is.
17. As a tester, I want both buttons disabled until a Word report is in the dialog, so that I can't start an import with nothing to import.
18. As a tester, I want a retest import to leave Report type blank, so that I choose the next test's report type and a wrong one never reaches the Word report's title.
19. As a tester, I want a retest import and an editable copy to keep doing what they do today, so that only the way I give the app the file changes.

Importing an export or a draft.json

20. As a tester, I want one Import button in place of Retest and Editable copy while an export or a draft.json is in the dialog, so that I'm not asked a question that doesn't apply to it.
21. As a tester, I want an export or a draft.json to come back exactly as it was saved, so that nothing in it changes on the way in.
22. As a tester, I want Setup to open as soon as an export or a draft.json is imported, as it does today, so that I can carry on with the report.
23. As a tester, I want a Word report saved under a .zip or .json name to be asked about, with Retest, Editable copy and the line "This file is a Word report. Choose how to import it.", so that a misnamed file never imports in a way I didn't choose.

While a file imports

24. As a tester, I want the dialog to show the file's name and that it is importing, so that I know the app is working.
25. As a tester, I want every button disabled while a file imports, so that a second click can't start a second import.
26. As a tester, I want Escape, Close and a click outside to do nothing while a file imports, so that the result and its warnings can't be lost.

When an import fails

27. As a tester, I want the server's message shown inside the dialog, so that I see why without looking elsewhere on the page.
28. As a tester, I want the error code shown under the message, so that the failure can be found in the error log.
29. As a tester, I want the file to stay in the dialog after a failure, so that I can click the other button or drop another file without finding the file again.
30. As a tester whose Word report can't become an editable copy, for example because a Resolved finding's remediation was edited, I want to click Retest on the same file, so that I can still start the next test from it.
31. As a tester, I want a Word report that fails to say "This Word report can't be imported:" and the reason, so that the message names the file I gave it.
32. As a tester, I want an export or a draft.json that fails to keep "Select a valid VulnReport export:" before the reason, so that a technical reason still tells me what file was expected.

When a Word report imports

33. As a tester, I want the result to replace the drop area in the same dialog, so that I don't get a second pop-up.
34. As a tester, I want the result titled "Imported as a retest" or "Imported as an editable copy", so that I can see which choice was used.
35. As a tester, I want the result to show the number of findings, the count for each status, and for an editable copy the number of evidence images, so that I can check the import brought everything across.
36. As a tester, I want a retest import's result to name the findings that changed from Open (New) to Open (Previously Discovered) and the Resolved or Closed findings left out, so that nothing changes without my knowing.
37. As a tester, I want every warning from the import listed in the result, so that I can check each assumption the import made.
38. As a tester, I want Open Setup and Stay on reports at the bottom of the result, so that I choose where to go next.
39. As a tester, I want Stay on reports to close the dialog and show the new report's row, with its application opened and the row focused, so that I can find the report in the list.
40. As a tester, I want Escape, Close or a click outside the result to do the same as Stay on reports, so that closing never hides where the new report went.

Closing the dialog

41. As a tester, I want Escape, a Close button, or a click outside the dialog to close it while nothing is importing, so that I can back out at any time.
42. As a tester, I want closing the dialog to forget the file it held, so that it opens empty next time.
43. As a tester, I want focus to go back to the Import button when I close the dialog without importing, so that I keep my place on the page.

Drops on the page

44. As a tester, I want a file dropped anywhere on the page while the dialog is open to go to the dialog, so that a drop that misses the drop area isn't opened or downloaded by the browser.
45. As a tester, I want a file dropped on the Reports page while the dialog is closed to do nothing, so that the browser doesn't open or download it and take me off the page.

The Burp build and assistive technology

46. As a tester using the Burp build, I want dragging a file onto the dialog to work in the app window, so that importing works the same there.
47. As a tester using a screen reader, I want the dialog announced by its title, and its progress and failure text read out when they change, so that I know what happened without seeing it.

## Implementation Decisions

- The Reports page gets an import dialog, and the Import button opens it instead of the hidden file input. The hidden file input stays as the file picker behind the drop area, with its accept list unchanged (.docx, .zip, .json and their MIME types). Its value clears after each pick, so the same file can be picked again.
- The dialog is part of the Reports page's code. The shared prompt helper takes only a message, a list and buttons, so it can't hold a drop area. The dialog still behaves like the shared dialogs: its backdrop carries the same marker, so code that checks for an open dialog sees it; it has role dialog, aria-modal and a labelled title; focus stays inside while it is open and goes back where it was on close; Escape and a click on the backdrop close it. It reuses the shared dialog styling. Its progress and failure text sit in a live region.
- The drop area marks itself while a file is dragged over the dialog, the way an evidence image slot does.
- The dialog has these states. A file the dialog takes moves it to a holding state, and a click starts the import.
  - Empty: the drop area, with Retest and Editable copy disabled.
  - Holding a Word report: the file's name, with Retest and Editable copy enabled.
  - Holding an export or a draft.json: the file's name, with one Import button in place of the two.
  - Importing: the file's name and "Importing...", every button disabled, closing ignored.
  - Failed: the holding state for the same file, with the message and error code shown.
  - Result: a Word report's result in place of the drop area, with Open Setup and Stay on reports.
  An export or a draft.json that imports leaves the dialog for Setup.
- The dialog sorts a file by the end of its name, ignoring case: .docx is a Word report, .zip an export, .json a draft.json. It turns away any other file, and any drop with more than one file. A file it turns away does not replace the held file. The server still decides from the bytes, as before.
- The import route's contract does not change. The dialog uses it like this:
  - A Word report goes up once, with `docx_mode` set to `retest` or `editable` by the button clicked.
  - An export or a draft.json goes up with `docx_mode=prompt`. Export or draft.json bytes import at once. Word report bytes come back as `mode_required` with nothing written, and the dialog moves to holding a Word report for the same file, with the line "This file is a Word report. Choose how to import it."
  - Nothing is sent when a file lands. Only a click sends a request, so a drop never writes a report.
- The page no longer sends every file with `prompt` first. The second pop-up that asked editable or retest goes away, with its strings "Import report DOCX", "Import as editable draft" and "Import as retest draft".
- The server changes in one place. When the uploaded bytes are a Word report, a 422 for a failure to read or check it reads "This Word report can't be imported: " and the reason. Exports and draft.json keep "Select a valid VulnReport export: " and the reason. The 413 limit messages, the 422 for an unknown `docx_mode`, and the 422 for a mode sent with bytes that are not a Word report keep their text.
- The result shows what today's summary pop-up shows: the finding count, each status's count with its label from the vocabulary, the evidence image count when the summary has one, then the notices (findings rewritten to Open (Previously Discovered), Resolved or Closed findings left out, warnings and normalizations). Its title is "Imported as a retest" or "Imported as an editable copy", and its sentence reads "Review the report in Setup before continuing." Notice text goes in as text, never as markup.
- Stay on reports, and any other way of closing the result, closes the dialog, clears the application search, reloads the list, opens the new report's application, scrolls its row into view, focuses the row's link, and sets the status line to "Report imported.", as today.
- A failure shows the message and the code line that the page's error panel shows today (operation, status, code and reference) inside the dialog. The page's error panel stays closed for import failures.
- The Reports page handles file drags on the whole window. While the dialog is open, a drop anywhere goes to the dialog. While it is closed, the page cancels the browser's default handling and does nothing else. Drags that carry no files are left alone.

## Testing Decisions

- A good test here does what a tester does on the Reports page and checks what the dialog shows, where the page goes, and which reports exist afterwards. It does not look at the dialog's internal state or markup beyond roles, names and visible text.
- Two seams, both existing, agreed with the user:
  1. The Reports page in `tests/test_browser.py`. A test gives the dialog a file through the hidden file input, or fires a `drop` event carrying a `File`, since a test can't drag from a folder window. Prior art: the Word report import tests that set files on `#import-report` and click "Import as editable draft" or "Import as retest draft", including the ones for cancel, Stay on reports focusing the new row, warnings rendered as text, misleading file names, and a second pick of the same file.
  2. `POST /reports/import` through the Python test client, for the message prefix. Prior art: the route tests in `tests/test_docx_import.py` that post through their `_import` helper, and the editable copy tests that expect a Resolved finding with edited remediation to fail.
- The existing browser import tests move to the dialog. One test helper, which opens Import, gives the dialog a file and clicks a named button, keeps each of them short.
- New browser tests cover: an empty dialog with both buttons disabled; a dropped Word report imported as a retest and as an editable copy; an export and a draft.json each showing one Import button and opening Setup; a second file replacing the first; a wrong file type and a several-file drop each turned away while the held file stays; a Word report named .zip being asked about, with no report written before the click; buttons disabled and closing ignored while an intercepted request holds the import back; a failure showing message and code with the file kept, then the other button succeeding; closing forgetting the file; a drop on the closed page leaving the page in place; a drop outside the drop area landing in the open dialog; and Enter on the drop area opening the file picker.
- New route tests: a Word report that fails answers 422 starting "This Word report can't be imported:"; an export that fails keeps "Select a valid VulnReport export:". The protocol tests for `prompt`, a mode sent with export bytes, and an unknown mode stay as they are.
- Every new test must be able to fail. Before calling the work done, break one rule, such as replacing the held file, and watch its test fail.
- While building, run `scripts/relevant_tests.py --run`. Before calling it done, run it with `--affected --run`.

## Out of Scope

- Removing ZIP or JSON import, or the Export button. This was considered and dropped.
- Any change to what a retest import keeps or an editable copy restores, or to any import limit.
- Setting Report type on a retest import.
- Importing an export or a draft.json as a retest.
- Importing several files in one go.
- Opening the dialog by dropping a file on the closed page.
- The import route's request contract: its `docx_mode` values and its sorting of files by bytes.
- The wording of the 422 for a file named .docx whose bytes are not a Word report.
- Renaming the `dropped_resolved` summary key, which `docs/DATA_MAP.md` says is kept on purpose.

## Further Notes

- `GLOSSARY.md` gained Editable copy, Retest import and Export while this spec was worked out. Use them in the dialog's text, the docs and the commit, and drop "draft" from the import results.
- Update in the same work: the import protocol section of `docs/ROUTES.md`, and the import paragraph of `docs/DATA_MAP.md` that says the manager first posts `docx_mode=prompt`. Follow the data-layer instructions when editing the data map.
- The web-client trap applies. No stylesheet brings back the browser's `[hidden]` rule, so a button that sets its own `display` needs its own `[hidden]` rule when the dialog swaps the two buttons for Import.
- The editable copy plan's rule, that the tester knowingly chooses how a Word report imports, still holds. The click is the choice, and a misnamed Word report is asked about.
- The Burp build opens the app in an Edge or Chrome app window ([ADR 0003](../../docs/adr/0003-burp-build-opens-an-app-window-in-edge-or-chrome.md)), which takes file drops like a browser tab. A real drag from a folder window can only be checked by hand, on Windows, in a browser tab and in the app window.

## What deviated

Built as specified, in one change. The dialog lives in `manager.js` with its own Tab trap, a copy of the eight lines in `dialog.js`, because the shared helper cannot hold a drop area. A click outside also cancels its own mousedown: without that, the press moved focus off the Import button after the dialog closed, which story 43 forbids. The Reports page's status line no longer reports progress ("Checking import...", "Import cancelled." are gone); only "Report imported." remains. The route test for the new prefix uses an editable copy only: a retest does not read the Limitations table, so the broken document that fails an editable copy imports as a retest, and the browser test for story 30 relies on exactly that. Story 18 (Report type left blank) gained a check in the dropped Word report test. The "Last verified" line of `docs/DATA_MAP.md` was left alone, since the import paragraph changed only in how the page calls the route.

## Next steps

1. On Windows, drag a Word report, an export and a draft.json from a folder window onto the dialog, once in a browser tab and once in the Burp build's app window (stories 5 and 46). No test can do a real drag.
