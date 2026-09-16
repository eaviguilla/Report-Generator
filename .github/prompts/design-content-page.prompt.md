---
description: "Build or redesign page 3, the Content editor, to its requirements."
argument-hint: "What to change"
agent: "agent"
tools: [read, edit, search]
---

Page 3 of 3 of a pentest-report tool: the Content page, where a tester writes each finding's body then generates the Word file. Flag anything you can't meet.
## Context
`GET /reports/{id}/edit`, `<main id="editor" data-report data-library>`, `app.js` → `continuousEditor()`. No router, framework or build step: the server embeds the report as JSON in `data-report`, the client parses it once as truth, navigation is full page loads. Library key here is `library_entries`; `/edit` bounces to `/findings` on an incomplete finding.

## Layout
Header: brand, engagement name, theme toggle, undo, redo, and a save button labelled from `data-save-state` that doubles as the conflict control. Stepper: Setup and Findings back-link, Content current.
Left rail: one button per finding, sorted severity then title, with ID, severity dot and active state; under it a collapsible Engagement scope listing each environment's dates, test time and targets.
Centre: one finding. Right rail: issue count, gap list, and a note that these are details still to fill in, not app errors.
Footer: Previous, Generate, live-region status. With no findings, an Add vulnerability button opens one. Skip link first, `aria-label` on icon controls, a real combobox for the title, deliberate focus moves, both themes.

## Finding card
Title is a button that becomes a library combobox; renaming **never replaces content**. Read-only colour-coded Likelihood, Impact, Severity, Vuln ID, Status. Affected locations grouped Production / Non-Production, per-finding overrides before target values. One collapsible block per content entry with a fragment count; expand/collapse **preserves reading position**.

## Sections
`open_new`: Description, Recommended Remediation, Proof of Concept; other statuses add Previous PoC and In Conclusion. Owned by server `provision`, mirrored client-side, never decided in the view. Recommended Remediation locks when `resolved`.
Add-menu: the first two take paragraph, list, image, table, note, code_block; PoC sections swap paragraph for instance_title; In Conclusion takes paragraph and note. Menu only; the schema allows anything, so never drop an unexpected fragment.

## Fragments
Chrome: drag handle, type tag, move up/down, Delete; reorder by button and drag-drop, `tabIndex=-1` so the field is the tab stop. Delete is disabled with a tooltip wherever provisioning would recreate it: the last fragment in Description or Recommended Remediation, the last `numbered_list`, Previous-PoC image, or PoC image for an affected environment.
paragraph: contenteditable, B/I/U, auto-grow, paste as plain text. note: same, no toolbar. lists: one textarea, one line per item, live markers. table: auto-sizing cells, add row/column. code_block: monospace.

## Evidence
Adjacent images form one movable set. Per tile: paste to attach (an unfocused paste fills the first empty on-screen slot, never one in Previous PoC), drag-in file, Browse/Replace, modal preview, caption, draggable position, Add a screenshot. Environment is auto-set and shown as text when one environment is affected, else a select — **except Previous PoC, which offers both and starts unset**. Uploads flush the report first and send `X-Report-Saved-At`.

## Library offers
Each section holding library content shows a **state-derived banner**, never a modal and never an automatic write: *Use library version*, *Add library content*, *Keep mine*. The first two record the choice in `content_offer_resolved[section]`, Proof of Concept in `poc_variant`/`poc_variant_declined`; Previous PoC offers nothing.

## Readiness panel
Gaps grouped per finding; each row's Go to selects, scrolls, focuses and leaves a highlight **held in state, not a lingering class**, cleared on the next click. Placeholder text warns, all else errors; drives the issue count and Generate's disabled state.
Gaps: missing name, assessment field or affected location; Description and Recommended Remediation need a fragment; text, list items and table cells need content, though PoC steps collapse to one message; images need environment, file and caption for still-affected environments, each of which needs a PoC image.

## Saving
Debounced autosave; local draft on `pagehide`; undo/redo; `beforeunload` while dirty; Previous navigates only if `await save()` succeeded; a 409 offers *Save my version* / *Load latest* and suspends saving. Restore the centre pane's `scrollTop` across re-renders.
## Will break if wrong
`frag_id` is unique **report-wide** — remint anything copied or the save fails validation. One content block per section type. Image slots are only added; a stale one is hidden by environment gating, not deleted. Section-by-status, image sync, affected environments and app types, PoC selection and readiness live in **both Python and JavaScript**; change them in pairs.
