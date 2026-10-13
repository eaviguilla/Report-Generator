# Skip the border on an image that already has one

> **Status:** in-progress

## Request

> Let's remove the ordering in the report generated for the previous proof-of-concept evidence Because the images that we copy and paste already have borders, when we add another border, it's going to be twice as thick. If we can detect whether an image has a border, then add that function or checker before adding a border, or not.

Read as: "ordering" is "border", a dictation slip. The generator draws a 0.75 pt black border into the picture's pixels, so a picture that came out of an earlier Word report (by Retest import, editable import, or copy and paste) already has one and received a second. Each import and generate round added another: a 1920 px image came out 1926, 1932 and 1938 px wide on three generations, with a border of 3, 6 and 9 px.

## Answers

From a grilling session on 2026-10-13.

- **Q1, which images:** every image gets a border only if it has none, in every section. Previous Proof of Concept has no special rule. Considered and not chosen: Previous Proof of Concept never gets a border. It leaves the double border on images that an editable import puts in the current Proof of Concept, and it prints a new screenshot pasted into Previous Proof of Concept, or an image from a hand-written report whose border is Word's own outline, with no border at all.
- **Q2, how old images arrive:** a Retest import of a report this app made, and a picture copied out of Word and pasted into the Content page. A screenshot of a Word page is best effort.
- **Q3, a border the check finds:** leave it alone. The picture goes in as it is, with no resizing and no new border. Considered and not chosen: cut the old border off a copy and draw a standard one. It would fix old double borders and uneven thickness, but it trims pixels off dark-edged screenshots, needs a cap, and with a strict check misses a border that Word shrank. A prototype put it at about 215 lines against about 130. It can be added later on top of the same check.
- **The check, `_has_border`:** the outermost line of pixels is dark on all four sides, meaning at least 98% of the line at 64 or less out of 255 in every colour channel. Tested with Pillow on a generated border shrunk and blurred: found down to 40% of its size, blurred or not, and lost at 25%. A dark-mode screenshot or a solid black image counts as bordered and gets no border.
- **Where it runs:** at generation, on the stored image. Nothing is stored with the image, so no schema change and no migration. The Content page does not change. Earlier plans rejected a stored flag and cropping, and this change adds neither.
- **Import message:** the editable import keeps "rendered Word copies" and drops "may be resampled or receive another border", because a bordered image is no longer changed. It now reads "Imported images are rendered Word copies, not the original files." The Retest import never warned.
- **Reports already generated:** they keep any double border they carry. Nothing trims them.
- **Terms:** Image border, in GLOSSARY.md.
- **ADR:** none. The rule is easy to reverse, and this plan records why it replaces the earlier decision.
- **Open risk:** the level and the share are set from images shrunk and blurred with Pillow. There is no Word on the Mac this was built on, so what Word's copy does to the border is untested. If Word copies a picture at its on-screen size, a 155 mm picture is 586 px wide at 96 dpi, which is 30% of a 1920 px image and near the limit of what the check finds. One real pasted picture from Windows decides whether the level needs raising.

## Agreed plan

- [x] 1. Tests first, seen failing on the old code: `ImageBorderTests` in `tests/test_docx.py` (no second border, a shrunk and blurred border, and the dark-edge rows), the carried Previous Proof of Concept picture in `DocxReportTests`, and two tests in `tests/test_docx_import.py` (an imported image regenerates at its imported size, and the editable message).
- [x] 2. `_line_is_dark`, `_has_border` and `_png_stream` in `app/docx_report.py`, and `_bordered_image_stream` returns a bordered picture as it is.
- [x] 3. The editable import message in `app/docx_import.py`.
- [x] 4. Docs: `docs/DOCX_TEMPLATE.md` (two passages), `docs/ARCHITECTURE.md` (two lines), the Word pipeline instruction, regenerated into `.claude/rules/`, and GLOSSARY.md.
- [x] 5. A note in the two earlier plans that their decision to accept the double border no longer holds.
- [ ] 6. One real pasted picture checked on Windows.
- [x] 7. Committed as `e47d6bd`. The status stays in-progress until the Windows check in step 6.

## Next steps

1. `/diagnosing-bugs`: Only if the Windows check says a real pasted picture was not recognised. Its edge pixels set the darkness level.
