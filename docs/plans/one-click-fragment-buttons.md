# One-click fragment buttons on the Content page

> **Status:** done · 2026-10-22 · `5e63b3d`, and the look changed in `8dc5afe`

## Request

> what if, in the contents page, instead of a new fragment button, we add all the fragments as buttons so they only need to click once. there will be no selection.

Read as: the "+ Add a fragment" dropdown at the bottom of each open section becomes a row of buttons, one per fragment type that section allows. Today a paragraph takes three clicks: open the dropdown, pick the type, click into the new fragment, because nothing moves the cursor there. The change makes it one.

## Answers

From a grilling session on 2026-10-21.

- **Q1, which types:** each section keeps the types it allows today. Description and Recommended Remediation offer paragraph, numbered list, bulleted list, image, table, note and code block. Previous Proof of Concept and Proof of Concept offer numbered list, image, bulleted list, instance title, note and code block. In Conclusion offers paragraph and note. So the Table button exists only in Description and Recommended Remediation. Considered and not chosen: every type in every section. The list is `allowed` in `app.js`, which has no Python owner, and the server and the Word build handle any type anywhere. No reason for the Proof of Concept limits is recorded, and a note already converts to a paragraph there. Letting a Proof of Concept hold paragraphs and tables is a separate rule change.
- **Q2, where a button sits and what a click does:** one row at the bottom of each open section, where the dropdown is. A click appends the fragment at the end of the section, and the arrows and dragging still move it. Considered and not chosen: a row at the top of each section, a strip between every two fragments, and one toolbar that adds to the section last clicked in. The row stays next to where the new fragment appears, and no ordering rule changes.
- **Q3, after the click:** the new fragment takes the cursor and scrolls into view. For an image the new slot is armed, so Ctrl+V or Cmd+V pastes into it, and clicking the slot still opens the file picker. Considered and not chosen: opening the file picker on the Image click.
- **Q4, keyboard:** each row is one Tab stop. The arrow keys move between its buttons, and Enter or Space adds. From a section's last fragment, one Tab reaches its row. Move up, Move down and the drag handle stay out of the Tab order, as today. Considered and not chosen: every button its own Tab stop, which adds seven stops at the end of each section, and mouse-only buttons.
- **Q5, other controls:** none change. The "change to…" dropdown and the screenshot environment picker stay. "Add another screenshot" stays and keeps inserting after the last screenshot of its own set. It was first marked for removal as redundant, then kept once the cost showed: with the Image button always appending at the end, a screenshot meant for Instance 1 would land after Instance 2.
- **Q6, table:** a new table has two header cells and one body row of two cells, with the cursor in the first header cell. Today it has one header cell and one body cell. A table has no size picker, so the button needs a fixed start, and the grilling chose this one.
- **Q7, term:** Fragment is in GLOSSARY.md. The row shows only type names, and "fragments" stays in each section's count.
- **Q8, look:** the icon bar, B, was picked on 2026-10-21 from A pills, B icon bar and C text links. It was then refined after a UI/UX review into B2, which was accepted the same day. B2 changes B in six ways. The tray and the name slot below were replaced on 2026-10-22, see Follow-up.
  - It leads with a plus and the word Add, so the bar is not read as a text-formatting toolbar.
  - It shows the name of the hovered or focused icon in a fixed slot at its right. B used a tooltip that covered the fragment above and needed a hover to appear.
  - It groups the icons by purpose, with one divider between groups, and keeps one order in every section: paragraph, then numbered and bulleted list, then image, table and code block, then note and instance title. A section that lacks a type lacks its icon.
  - It sits in a quiet tray, and the hovered icon lifts out of it.
  - A new fragment arrives with a short accent ring.
  - The red to-fill-in ring on a new empty field waits until the cursor has left it once.
  
  Considered and not chosen: A and C. The drawback of an icon-only bar stays, because a first-time tester has to hover to learn an icon, and the name slot is the answer to it. The buttons were 34 by 34 px, well over the 24 px minimum of WCAG 2.2. They are 24 by 24 now, see Follow-up.
- **ADR:** none. Every choice here is easy to reverse.
- **What the code does today:** `appendFragmentMenu` in `buildContentBlock` (`app/web/static/app.js`) builds the dropdown. Its `onchange` calls `newFragment`, sets an image's environment, pushes onto `content.fragments`, then calls `render()` and `scheduleSave()`. Nothing focuses the new fragment. `newFragment("table")` has no other caller, and the server has no twin of it. The data layer does not change, so there is no Python change and no restart. JavaScript and CSS reload.
- **Open risks:**
  - `render()` rebuilds the pane and restores the scroll, once at once and again a frame later, so focusing the new fragment has to come after that, or the restore undoes the scroll into view.
  - `scheduleSave()` has to run before the cursor moves into the new field. If it runs after, the add joins the typing as one Undo step.
  - A save replaces the cell objects of a table, so a cell handler must look the cell up by position. `cellInput` captured the cell objects until `80bb61a` fixed it.
  - The pane redraws after every add, so the row's remembered button resets to the first one.
  - `test_a_table_edit_on_screen_survives_adding_a_row` waits for more than 2 cell inputs. A two-column table already has 4, so the test would pass without proving the redraw. It needs a threshold above 4.
  - How heavy up to 28 buttons look when every section is open was a judgment for the prototype, and B2 was chosen for it. Fit was answered for the tray look, and again for the dashed strip in the Follow-up.
  - The red ring on a new empty field is the app's own. `updateReadinessPanel` puts `is-incomplete` on every fragment that has an issue, so a one-click add shows an error on a field the tester has had no time to fill. The prototype can hold it back only with CSS. The app has already styled the field red by then, and its box-shadow transition fades the ring out over about 120 ms unless the CSS also turns the transition off. In the real change the app should keep a freshly added fragment out of the incomplete set until its first blur, so no ring starts.
- **Assumed, not asked.** Say so if one is wrong.
  - Each button creates what the dropdown creates today, except Table.
  - An Image click keeps choosing the first affected environment that has no screenshot yet.
  - Every open section that shows the dropdown today shows a row, Previous Proof of Concept included. A collapsed section, and a Recommended Remediation locked by a Resolved finding, show none.
  - Each icon has a name in sentence case, shown in the slot, and the row is always visible. The order is B2's, not each section's old one (Q8), and was accepted with B2. Proof of Concept used to offer numbered list, image, bulleted list, instance title, note and code block.
  - An add is its own Undo step, and typing in the new fragment is the next one, as today.
  - `allowed` stays in JavaScript.
  - "Add another screenshot" also takes the cursor and arms its new slot, so both ways of adding a screenshot behave alike.

## Agreed plan

- [x] 1. `/prototype`: throwaway looks for the row, on the real Content page, so one can be picked. Built and checked in a browser on 2026-10-21: A pills, B icon bar, B2 (the refined B) and C text links, in light and dark. B2 was accepted. The looks are on the throwaway branch `prototype/one-click-fragment-buttons` (`4972c7b`), not on main. The prototype drives the old dropdown, so it runs against that commit's parent, `f84f40e`.
- [x] 2. Tests first, seen failing on the old code, in `tests/test_browser.py`. A helper adds a fragment through the row and replaces the 19 dropdown call sites. New tests: each section's row offers exactly its types in order; a click appends at the end; the cursor lands in the new fragment for every type, and in a table's first header cell; Image arms paste; a row is one Tab stop, the arrow keys move between its buttons, and Enter and Space add; a new table has two header cells and a body row of two; a collapsed section and a locked remediation have no row; no `select.add-fragment` remains; Add another screenshot still inserts after its set and arms its new slot; the name slot shows the hovered or focused icon's name and shifts nothing; a new fragment shows no red ring until the cursor leaves it, for a paragraph, a list and a table. Raise the threshold in `test_a_table_edit_on_screen_survives_adding_a_row`.
- [x] 3. `app/web/static/app.js`: replace `appendFragmentMenu` with the row. Extract `addFragment(type)` from the old `onchange`, call `scheduleSave()` before moving focus, and focus the new fragment after the redraw. Arm paste for an image, and change the `newFragment("table")` start. Keep a fragment added through the row out of the incomplete set in `updateReadinessPanel` until its first blur, and give it the arrival ring.
- [x] 4. Styles: drop the `.add-fragment` select rules in `taste.css` and `app.css`, and add the B2 row styles: the tray, the groups, the name slot and the arrival ring. Keep `.evidence-add`.
- [x] 5. Docs: the "Add a fragment" mention in `docs/DATA_MAP.md` and its Last verified line, and a line in the web-client instruction, regenerated into `.claude/rules/`, if the focus-after-redraw order proves a trap.
- [x] 6. A real-browser check, then `scripts/relevant_tests.py --affected --run` and pyflakes. The check ran in the VS Code browser and in Playwright scripts, not through the `playwright-cli` skill.
- [x] 7. Tick these boxes, set the status to `done` with the date and commit, and add one paragraph on what deviated.

## What deviated

The plan said `cellInput` already looked a cell up by position. It captured the cell objects, so a table cell typed into after an autosave lost its text when the tester went back to Findings. That was fixed first, as its own commit with its own test (`80bb61a`), because a two-column table makes it easier to hit. The shipped buttons were 34 by 34 px and not 36 by 34, and the row dropped its name under the buttons in narrow sections. The look was replaced on 2026-10-22, see Follow-up. Home, End and wrap-around on the arrow keys came from the prototype and were not in Q4. A new fragment also scrolls whole into view, because focusing a field showed only its caret. Code review found that redrawing the review panel at the moment the red ring is released lost a click that began on the panel, so the release now waits 100 ms. A stale fixture in `test_keyboard_library_selection_and_fragment_movement` (a finding with no severity is sent back from Content) was fixed on its own in `f84f40e`. "Add another screenshot" arms and focuses its new slot, as assumed.

## Follow-up, 2026-10-22: the look

The shipped row did not match the page around it. The page's own controls are 20 to 22 px with 9 to 11 px text on 3 px corners, and "Add another screenshot" is a dashed 32 px button. The row had 34 px buttons, 18 px icons, 12 px bold text, a filled tray on 6 px corners and an accent-blue name. Three looks were tried on the real Content page, with the shipped row beside them: a dashed strip, a band like a fragment head, and lowercase text links. The dashed strip won, with three changes. The strip is as wide as its buttons, it is centred in the section, and the hovered name shows at its right, outside it.

What it is now: a 32 px dashed strip with 24 px buttons and 14 px icons, which is the WCAG 2.2 minimum target size. It is centred with `justify-self: center`. The space above it and the space below it are both 11 px. The name is 9.5 px monospace and out of the layout, so it moves nothing. At the narrowest two-column width (444 px) the longest name ends 21 px inside the section, which clips at its padding box. A section narrower than about 400 px, which is a window under about 430 px, clips the longest names. The old row wrapped its name there, and wrapping was what the new look gave up. The tray's border, fill and radius, the 34 px buttons and the name slot that sat in the row's flow, all in Q8, are gone. The `.add-row-tray` element stays as a plain wrapper for the button groups. The behaviour of the buttons, the cursor, the Tab stop and the arrow keys did not change.

The change is in `8dc5afe`. The three looks are on the branch `prototype/add-row-matches-content-page` (`3621b9e`). They restyle the row of `5e63b3d`, so they run against `fe9f953`.
