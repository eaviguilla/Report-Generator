# When the content offers should fire

> **Status:** shipped · 2026-09-16 · `e7b843a`

## Request

> For description and recommended remediation:
> Prompt for replace, add, or retain should happen when
> a fragment is modified/deleted in that content (or if the data from that content is not equal to the vuln library), vuln name is modified to a vuln that has description and recommended remediation in the vuln library
>
> prompt in recommended remediation if vuln was changed from resolved to open (basically the data is again, not equal to the vuln library).
>
> for the POC, prompt for replace, add, or retain if
> POC is empty, vuln is changed to a vuln with a poc in vuln library
>
> prompt to add the default value of the in concluisions content if
> fragment is deleted or cleared (yes it is okay to show even if they are the ones that deleted it)
>
> prompt to update the default value (with new value) of the in conclusions context text field if
> finding name is changed, status is changed.
>
> prompt to add the last line of the POC to in conclusions text field when
> the last line of POC is modified, there is a new last line, the in conlusion is equal to its default while poc has value in it.
>
> for the description and recommended remediation, I was thinking if we need a checker if they are equal to the vuln library data to know when to prompt. since if the finding name is changed to a vuln from library, this prompt will trigger as well. i am not that sure.

## Round 1 - Oracle: how it works today

### 1. Every offer and prompt on the Content and Findings pages

Your list of five is **correct and complete for banners**, but it is missing one modal and mislabels one. The full set is below. The Content page has **zero** `vrDialog` modals of its own except one reached through the finding-title editor; everything else there is an inline, state-derived banner. `window.confirm` appears nowhere.

#### Content page

| # | Offer | Show condition (as written) | Writes on accept | Records the answer | Server twin |
|---|---|---|---|---|---|
| 1 | Description / Recommended Remediation library offer | [app.js#L3191](app/web/static/app.js#L3191) gates on section type; [app.js#L3193](app/web/static/app.js#L3193) `pendingLibraryOffers(finding).find(candidate => candidate.type === content.type)` | `replace` → `content.fragments = remintFragments(libraryFragments)`; `merge` → appends after existing (existing kept only if `written`); `keep` → nothing ([app.js#L3196-L3206](app/web/static/app.js#L3196-L3206)) | `finding.content_offer_resolved[content.type] = entry.library_id` ([app.js#L3200](app/web/static/app.js#L3200)) — written for **all three** buttons including Keep | **Write-only twin.** [main.py#L730](app/main.py#L730) pre-answers the field on insert. No Python reads it. |
| 2 | Proof-of-concept library offer | [app.js#L3144-L3146](app/web/static/app.js#L3144-L3146) `pendingLibraryOffers(finding).find(offer => offer.type === "proof_of_concept")?.variants` | `applyPocVariant(finding, steps, picked, "replace"\|"merge")` ([app.js#L3154-L3157](app/web/static/app.js#L3154-L3157)) | accept → `poc_variants`; refuse → `poc_variant_declined` ([app.js#L3163-L3165](app/web/static/app.js#L3163-L3165)) | **Yes**, full twin: [apply_poc_variant](app/report_service.py#L496) / [applyPocVariant](app/web/static/app.js#L1195), [applicable_poc_variants](app/report_service.py#L320) / [applicablePocVariants](app/web/static/app.js#L1120) |
| 3 | In Conclusion proof-of-concept-step offer | [app.js#L3095-L3099](app/web/static/app.js#L3095-L3099): section is `in_conclusion`, status prints it, `pocLastStep(finding)` non-empty, and that text is not in `conclusion_offer_resolved` | three arms at [app.js#L3103-L3108](app/web/static/app.js#L3103-L3108): insert in front of the sentence within the same paragraph, overwrite a previously quoted paragraph, or unshift a new paragraph | `finding.conclusion_offer_resolved = [...new Set([...resolved, lastStep])]` ([app.js#L3112](app/web/static/app.js#L3112)) — written for **both** Use it and Dismiss | **No.** Field round-trips only; no Python reader. |
| 4 | In Conclusion restore-default banner | [app.js#L3124-L3125](app/web/static/app.js#L3124-L3125): at least one text-less paragraph exists **and** `!content.fragments.some(hasDefaultStatusConclusion)` | `emptied[emptied.length - 1].runs = statusConclusionRuns(title, statusWord)` ([app.js#L3136](app/web/static/app.js#L3136)) — last emptied paragraph, in place | **Nothing.** Purely state-derived; re-appears the moment the paragraph is emptied again | Half: the sentence builder/recogniser is twinned ([status_conclusion_runs](app/report_service.py#L408)), the banner is not |
| 5 | Replace-or-keep conclusion dialog, from the editor's title field | [app.js#L3039-L3040](app/web/static/app.js#L3039-L3040) `finishTitle` → `syncConclusion` then `await offerConclusionRewrite(finding)` | `first.runs = statusConclusionRuns(...)` ([app.js#L1066](app/web/static/app.js#L1066)) | **Nothing.** No memory at all | No |

#### Findings page

| # | Prompt | Condition | Notes |
|---|---|---|---|
| 6 | Replace-or-keep conclusion, on committed title | [app.js#L2029](app/web/static/app.js#L2029), inside `titleInput.onchange` | fires after a possible library swap |
| 7 | Replace-or-keep conclusion, on status change | [app.js#L2061](app/web/static/app.js#L2061) | strictly after the status dialog resolves |
| 8 | Status-change confirm | [app.js#L2054](app/web/static/app.js#L2054): `hidden.length \|\| replacesRemediation` | `replacesRemediation` is `next === "resolved" && current !== "resolved"` — **one-directional; there is no dialog on resolved → open** |
| 9 | Scope-loss confirm | [app.js#L1790](app/web/static/app.js#L1790), `settleScopeChange` | evidence removal |
| 10 | Delete-finding confirm | [app.js#L2097](app/web/static/app.js#L2097) | |

**Correction to your list:** what you called "the replace-or-keep dialog on title/status change" is a single function, `offerConclusionRewrite`, with **three** call sites ([app.js#L2029](app/web/static/app.js#L2029), [app.js#L2061](app/web/static/app.js#L2061), [app.js#L3040](app/web/static/app.js#L3040)), one of which is on the Content page. It is separate from the status-change confirm at [app.js#L2054](app/web/static/app.js#L2054), which is about hidden sections and the remediation overwrite.

**Also note:** the readiness panel renders every `pendingLibraryOffers` result as a "Suggested" warning row ([app.js#L2861-L2870](app/web/static/app.js#L2861-L2870)), never counted toward the verdict. Offers 3, 4 and 5 have no readiness presence at all.

---

### 2. "Is this equal to the library" — what exists and what it costs

#### `sameFragments`

```js
const sameFragments = (left, right) => JSON.stringify(left, (key, value) => key === "frag_id" ? undefined : value)
  === JSON.stringify(right, (key, value) => key === "frag_id" ? undefined : value);
```
[app.js#L1226-L1227](app/web/static/app.js#L1226-L1227)

- **Compares:** the entire fragment array as serialised JSON — order, types, every run, every flag, `generated`, `caption`, `evidence_id`, table cells.
- **Ignores:** `frag_id` only.
- **Called from exactly one place:** [app.js#L1239](app/web/static/app.js#L1239), inside `pendingLibraryOffers`. Nowhere else.
- **It is not a text comparison.** An added empty `code_block` or `table` makes it false.

Key-order risk is **not** a problem here: library entries are dumped through Pydantic (`self.entries = [entry.model_dump(mode="json") for entry in document.entries]`, [library.py#L65](app/library.py#L65)) and the report is dumped the same way ([main.py#L708](app/main.py#L708)), so both sides carry the same field set in declaration order — `{frag_id, type, runs, generated}` with runs as `{text, bold, italic, underline}`. Equality is genuinely achievable, and I confirmed it against real data (below).

#### `content_offer_resolved` and `conclusion_offer_resolved`

| Field | Type | Default | Writers | Python readers |
|---|---|---|---|---|
| `content_offer_resolved` | `dict[ContentType, StableId]` ([models.py#L197](app/models.py#L197)) | `{}` via `default_factory` | [main.py#L730](app/main.py#L730) (`insert_library`), [app.js#L1821](app/web/static/app.js#L1821) (reset to `{}` on entry swap), [app.js#L3200](app/web/static/app.js#L3200) (all three buttons) | **none** |
| `conclusion_offer_resolved` | `list[str]` ([models.py#L201](app/models.py#L201)) | `[]` via `default_factory` | [app.js#L3112](app/web/static/app.js#L3112) only | **none** |

Both are plain (not `Optional`). Missing key and `[]`/`{}` validate; explicit `null` fails. Confirmed by grep across `app/`: the only Python occurrence outside `models.py` is the writer at `main.py#L730`.

#### Does a library entry's content ever end up byte-identical in a finding?

Traced through [insert_library](app/main.py#L719-L740):

```
Vulnerability(..., contents=copy.deepcopy(entry["contents"]))   # main.py:727
content_offer_resolved = {content.type: library_id ...}          # main.py:730
assign_fresh_fragment_ids(vulnerability)                         # main.py:731
provision(vulnerability)                                         # main.py:732
sync_evidence_image_slots(vulnerability, report)                 # main.py:734
apply_poc_variant(...) if exactly one variant                    # main.py:738
```

Answering each section separately:

- **`description` — YES, byte-identical.** `provision` seeds `required_fragments` only into a section with **no** fragments ([report_service.py#L207-L209](app/report_service.py#L207-L209)). A library entry always supplies a description, so nothing is seeded, nothing is reordered, nothing is stripped. Only `frag_id` changes, and `sameFragments` ignores it.
- **`recommended_remediation` — YES for `open_new` and `open_previously_discovered`.** The `else` branch keeps every fragment whose `generated != "resolved_remediation"` ([report_service.py#L229-L232](app/report_service.py#L229-L232)); library fragments have `generated=None`, so all survive. **NO for `resolved`** — the section is wholesale replaced by the boilerplate paragraph ([report_service.py#L222-L228](app/report_service.py#L222-L228)). A library insert is always `open_new`, so the insert path is safe.
- **`proof_of_concept` — NEVER.** Three separate mutations guarantee it: `provision` seeds `["numbered_list", "image"]` into the empty section ([report_service.py#L200-L206](app/report_service.py#L200-L206)), `ensure_proof_steps` guarantees a leading `numbered_list` ([report_service.py#L155-L159](app/report_service.py#L155-L159)), and `sync_evidence_image_slots` appends one image slot per affected environment ([report_service.py#L344](app/report_service.py#L344)). Also structural: library POC steps live in the separate `proof_of_concept: dict[Channel, list[Fragment]]` field ([library.py#L23](app/library.py#L23)), **not** in `contents`, so there is nothing for `sameFragments` to compare against. This is why `pendingLibraryOffers` never routes POC through it ([app.js#L1241-L1243](app/web/static/app.js#L1241-L1243)).

The client mirror `applyLibraryEntry` ([app.js#L1817-L1827](app/web/static/app.js#L1817-L1827)) is different: it **never copies content**. It writes `title`, `likelihood`, `impact`, `severity`, `library_ref`, clears the three answer fields, and calls `syncConclusion`. A finding retitled from the Findings page therefore keeps whatever content it had, which is why `sameFragments` returns false for it.

#### What a library entry's `contents` actually holds

Counted across [resources/vuln_library.json](resources/vuln_library.json):

- **51 entries** (`entry_count: 51`, and 51 `library_id` keys at the entry indent level).
- **102 content sections total = exactly 2 per entry.** Every entry has **one `description` and one `recommended_remediation`**, and nothing else. There are **zero** entries with one and not the other, and **zero** entries carrying `proof_of_concept`, `previous_proof_of_concept`, or `in_conclusion` in `contents`.
- **Zero empty fragments.** A search for `"fragments": []`, `"runs": []`, and `"items": []` returns no matches anywhere in the file.
- **12 entries carry `proof_of_concept`**, all with both `web` and `api`, **none with `mobile`**. (Lines 74, 1026, 1179, 2610, 2823, 2965, 3125, 3436, 3596, 3757, 3989, 4243.) The map's claim here is correct.
- Fragment types in `recommended_remediation` are not uniformly paragraphs — VDB-047 is `bulleted_list` + `note` ([vuln_library.json#L4716-L4759](resources/vuln_library.json#L4716-L4759)).

---

### 3. Status transitions

#### What happens to `recommended_remediation` on resolved → open

Both sides, in `provision`:

```python
else:
    # Reopening a finding leaves boilerplate describing a remediation that no longer happened.
    kept = [fragment for fragment in remediation.fragments if getattr(fragment, "generated", None) != "resolved_remediation"]
    remediation.fragments = kept or [ParagraphFragment(frag_id=..., type="paragraph", runs=[])]
```
[report_service.py#L229-L232](app/report_service.py#L229-L232), twinned at [app.js#L1043-L1046](app/web/static/app.js#L1043-L1046).

**The marker is `ParagraphFragment.generated == "resolved_remediation"`** ([models.py#L74](app/models.py#L74)). It is set on the way in at [report_service.py#L227](app/report_service.py#L227) / [app.js#L1041](app/web/static/app.js#L1041), and backfilled for pre-marker drafts by [workspace.load_path](app/workspace.py#L285-L293).

#### What is in the section after a reopen

**A single paragraph with `runs: []` — an empty paragraph.** Not the prior content, and not the library content. Going resolved discarded the whole prior section ([report_service.py#L223](app/report_service.py#L223) assigns, it does not append), so there is nothing left to restore; the `kept or [...]` fallback then manufactures an empty paragraph.

It is **not** equal to the library entry's remediation, and cannot be.

This is visible on disk. [data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json](data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json#L122-L129) — finding `v_852106ea`, `library_ref` VDB-047, status `open_previously_discovered`, remediation is exactly one `f_b34bbb64` paragraph with `"runs": []`, while VDB-047 in the library carries a four-item `bulleted_list` plus a `note`.

#### Does anything re-offer the library remediation after a reopen?

**No.** Three things would each have to pass, and one fails:

1. `finding.status === "resolved" && type === "recommended_remediation"` filter — passes after reopen ([app.js#L1234](app/web/static/app.js#L1234)).
2. `libraryContentFor(entry, type).length` — passes, VDB-047 has content.
3. `sameFragments(...)` — passes (empty paragraph ≠ library), so this would *allow* the offer.
4. **`finding.content_offer_resolved?.[type] !== entry.library_id` — FAILS.** [app.js#L1235](app/web/static/app.js#L1235).

That same Northstar draft shows `content_offer_resolved: {"description": "VDB-047", "recommended_remediation": "VDB-047"}` ([draft.json#L96-L99](data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json#L96-L99)), written by `insert_library` at creation. **`content_offer_resolved` is the specific thing blocking a re-offer after a reopen**, and it is a permanent latch: nothing ever removes a key except the wholesale `= {}` reset when the library entry itself changes ([app.js#L1821](app/web/static/app.js#L1821)).

There is also **no event** to hang a reopen trigger on other than the status `<select>` at [app.js#L2044](app/web/static/app.js#L2044), which lives on the Findings page, not the Content page.

---

### 4. The proof-of-concept offer

#### Show condition, verbatim chain

```js
const applicablePocVariants = finding => {
  const available = libraryEntryFor(finding)?.proof_of_concept || {};
  const channels = affectedChannels(finding);
  return CHANNELS.filter(channel => channels.includes(channel) && (available[channel] || []).length);
};
```
[app.js#L1120-L1124](app/web/static/app.js#L1120-L1124)

```js
const variants = applicablePocVariants(finding)
  .filter(variant => !(finding.poc_variants || []).includes(variant) && !(finding.poc_variant_declined || []).includes(variant));
if (variants.length) offers.push({type:"proof_of_concept", entry, variants});
```
[app.js#L1241-L1243](app/web/static/app.js#L1241-L1243)

Then at render: `pendingLibraryOffers(finding).find(offer => offer.type === "proof_of_concept")?.variants || []`, shown iff `offered.length` ([app.js#L3146-L3147](app/web/static/app.js#L3146-L3147)).

**Channels gate it twice.** First `affectedChannels(finding)` ([app.js#L1105-L1118](app/web/static/app.js#L1105-L1118)) resolves the finding's selected `target_ids` to their targets' channels, plus typed `custom_locations` filtered against `engagement.tested_environments` / `tested_channels`. Second, the entry must carry steps for that channel. Since no library entry has `mobile` steps, a mobile-only finding is never offered anything. And since a freshly inserted finding has `Scope(mode="custom")` with **no** `target_ids` ([main.py#L727](app/main.py#L727)), `affected_channels` returns `[]` and the server's auto-install at [main.py#L736-L739](app/main.py#L736-L739) can never fire on insert — it only fires if an import path supplies scope first.

Python twin ([report_service.py#L320-L324](app/report_service.py#L320-L324)) tests `channel in (available or {})` rather than checking list length; equivalent in practice because `LibraryEntry.validate_proof_of_concept` rejects an empty list ([library.py#L36-L38](app/library.py#L36-L38)).

#### What "POC is empty" would mean

You are right to flag this. `ensure_proof_steps` guarantees a `numbered_list` first in the section ([report_service.py#L155-L159](app/report_service.py#L155-L159), [app.js#L1183-L1185](app/web/static/app.js#L1183-L1185)), and `sync_evidence_image_slots` appends an image per affected environment ([report_service.py#L344](app/report_service.py#L344), [app.js#L1140-L1163](app/web/static/app.js#L1140-L1163)). **A `proof_of_concept` section is therefore never `fragments: []` on a provisioned finding.** Every draft on disk confirms it — e.g. [draft.json#L182-L207](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json#L182-L207) shows a `numbered_list` with a single `{"runs": []}` item plus two blank image slots.

**There is an existing "has the tester written any steps" predicate**, and it is one line:

```js
const written = content.fragments.some(fragment => fragment.type !== "image" && fragmentHasContent(fragment));
```
[app.js#L3148](app/web/static/app.js#L3148)

`fragmentHasContent` ([app.js#L973-L976](app/web/static/app.js#L973-L976)) counts runs, list-item runs, table cells, `fragment.text`, `fragment.caption`, and `evidence_id`. Today `written` only swaps button labels ("Fill from library" vs "Use saved steps", "Dismiss" vs "Keep mine") at [app.js#L3161-L3163](app/web/static/app.js#L3161-L3163). **It does not gate whether the banner shows.** The nearest server equivalent is `content_has_work` ([report_service.py#L169](app/report_service.py#L169)) / `contentHasWork` ([app.js#L1019-L1026](app/web/static/app.js#L1019-L1026)), which additionally discounts app-generated boilerplate.

#### Does it fire when the finding's name is changed to a library entry with a POC?

**From the Findings page: yes.** [app.js#L2026-L2031](app/web/static/app.js#L2026-L2031) — `titleInput.onchange` finds an exact case-insensitive title match, and if the id differs calls `replaceFromLibrary` → `applyLibraryEntry`, which sets `library_ref` and clears `poc_variants` and `poc_variant_declined` ([app.js#L1818-L1822](app/web/static/app.js#L1818-L1822)). The offer then appears on the Content page at the next render, provided the finding's channels intersect the entry's step channels. The same holds for clicking a row combobox result ([app.js#L2022](app/web/static/app.js#L2022)). This is pinned by `test_switching_library_entries_reoffers_poc_for_the_same_channel` ([test_browser.py#L1670](tests/test_browser.py#L1670)).

**From the Content page's own title editor: no.** [app.js#L3050-L3057](app/web/static/app.js#L3050-L3057) sets `titleInput.value = entry.title` and calls `finishTitle()`, which writes only `finding.title` ([app.js#L3038](app/web/static/app.js#L3038)). No `library_ref` is written, so `libraryEntryFor` still resolves to the old entry or `null`. The in-source comment says so explicitly: *"Renaming here never replaces content; library swaps belong to the Findings page."*

---

### 5. In Conclusion

#### Banner A — quote the last proof-of-concept step

```js
if (content.type === "in_conclusion" && contentTypesForStatus(finding.status).includes("in_conclusion")) {
  const resolved = finding.conclusion_offer_resolved || [];
  const lastStep = pocLastStep(finding);
  if (lastStep && !resolved.includes(lastStep)) {
```
[app.js#L3095-L3098](app/web/static/app.js#L3095-L3098)

Inside it, the primary button's label and target are decided by:
```js
const first = content.fragments.find(fragment => fragment.type === "paragraph");
const firstText = first ? conclusionText(first) : "";
const sentenceStart = first ? defaultConclusionStart(firstText) : -1;
const prefix = sentenceStart >= 0 ? firstText.slice(0, sentenceStart).trimEnd() : firstText;
const quoted = first && resolved.includes(prefix) ? first : null;
```
[app.js#L3099-L3103](app/web/static/app.js#L3099-L3103)

#### Banner B — restore the default sentence

```js
const emptied = content.fragments.filter(fragment => fragment.type === "paragraph" && !fragmentHasText(fragment));
if (emptied.length && !content.fragments.some(hasDefaultStatusConclusion)) {
```
[app.js#L3124-L3125](app/web/static/app.js#L3124-L3125)

Note this one is **not** gated on `contentTypesForStatus` — it sits inside the same `if` block as Banner A, so it inherits that gate from [app.js#L3095](app/web/static/app.js#L3095).

#### `offerConclusionRewrite`

```js
async function offerConclusionRewrite(finding) {
  const conclusion = finding.contents?.find(content => content.type === "in_conclusion");
  if (!conclusion || !contentTypesForStatus(finding.status).includes("in_conclusion")) return false;
  const first = conclusion.fragments.find(fragment => fragment.type === "paragraph");
  if (!first || first.generated || !fragmentHasText(first) || hasDefaultStatusConclusion(first)) return false;
```
[app.js#L1053-L1058](app/web/static/app.js#L1053-L1058)

**Fires when:** the section exists and the status prints it, a paragraph exists, it has no `generated` marker, it has text, and it does **not** contain the recognised sentence anywhere. That is, *tester prose only*.

**Suppressed when:** no conclusion section; status is `open_new`; no paragraph; `generated` is set; paragraph is text-less; paragraph still contains the sentence (including a quoted step + sentence, since `hasDefaultStatusConclusion` uses `defaultSpanIn`, not the tail test).

**Awaited at three call sites:** [app.js#L2029](app/web/static/app.js#L2029) (Findings row title `onchange`), [app.js#L2061](app/web/static/app.js#L2061) (Findings row status `onchange`, strictly after the status dialog), [app.js#L3040](app/web/static/app.js#L3040) (editor `finishTitle`).

#### `default_conclusion_start` / `defaultConclusionStart`

```python
def default_conclusion_start(text: str) -> int | None:
    span = default_conclusion_span(text)
    return span[0] if span is not None and span[1] == len(text.rstrip()) else None
```
[report_service.py#L432-L440](app/report_service.py#L432-L440); JavaScript returns `-1` instead of `None` ([app.js#L135-L138](app/web/static/app.js#L135-L138)).

**The sentence is matched as a TAIL, not as a whole paragraph.** `default_conclusion_span` scans right-to-left for `The finding "` and returns the first suffix that full-matches the pattern ([report_service.py#L419-L429](app/report_service.py#L419-L429)); `default_conclusion_start` then additionally requires the span to end at `len(text.rstrip())`. So text *before* the sentence is allowed, text *after* it is not.

**Consumers:** the only consumer of `default_conclusion_start` on either side is the JavaScript Banner A at [app.js#L3101](app/web/static/app.js#L3101). The Python function has **no in-app caller** — `provision` uses `default_conclusion_span` ([report_service.py#L237](app/report_service.py#L237)), `generation_issues` uses `default_conclusion_span` ([docx_report.py#L119](app/docx_report.py#L119)), and `content_has_work` uses `is_default_status_conclusion` ([report_service.py#L176](app/report_service.py#L176)). It exists as the twin of the JavaScript one and as a test surface.

#### What "the in conclusion is equal to its default" means in code today

**Three different predicates, and they are not interchangeable:**

| Predicate | Meaning | Used by |
|---|---|---|
| `is_default_status_conclusion` / `isDefaultStatusConclusion` | span is exactly `(0, len(text.rstrip()))` — the paragraph is *nothing but* the sentence | `content_has_work` ([report_service.py#L176](app/report_service.py#L176)), `contentHasWork` ([app.js#L1021](app/web/static/app.js#L1021)) |
| `hasDefaultStatusConclusion` / `span is not None` | the paragraph *contains* the sentence anywhere | `syncConclusion` selection ([app.js#L995-L1000](app/web/static/app.js#L995-L1000)), `provision` selection ([report_service.py#L237-L238](app/report_service.py#L237-L238)), `offerConclusionRewrite` ([app.js#L1058](app/web/static/app.js#L1058)), Banner B ([app.js#L3125](app/web/static/app.js#L3125)), `generation_issues` ([docx_report.py#L115-L121](app/docx_report.py#L115-L121)) |
| `defaultConclusionStart(text) >= 0` | the paragraph *ends with* the sentence | Banner A only ([app.js#L3101](app/web/static/app.js#L3101)) |

There is **no** predicate anywhere meaning "the conclusion text field equals the value the app last derived for it". The sentence is re-derived from `(title, status)` on demand rather than stored and compared.

---

### 6. Change detection

#### Which triggers have a real event today

| Your trigger | Real event exists? | Where |
|---|---|---|
| "finding name is changed" | **Yes**, three of them | Findings row `oninput` [app.js#L2023](app/web/static/app.js#L2023), Findings row `onchange` [app.js#L2026](app/web/static/app.js#L2026), editor `finishTitle` [app.js#L3035](app/web/static/app.js#L3035) |
| "status is changed" | **Yes**, one | Findings status `onchange` [app.js#L2044](app/web/static/app.js#L2044). The editor shows status as a read-only chip ([app.js#L3016](app/web/static/app.js#L3016)) |
| "a fragment is deleted" | **Yes**, two | [app.js#L2403](app/web/static/app.js#L2403) (image tile) and [app.js#L2485](app/web/static/app.js#L2485) (other fragments) — both `splice` then `rerender()` |
| "a fragment is cleared" | **No event.** Only `oninput`/`onchange` per field, which fire on every keystroke with no notion of "now empty" | `rich()` `oninput` [app.js#L967](app/web/static/app.js#L967); list textarea `oninput` |
| "a fragment is modified" | **No event.** Same problem: per-keystroke only, no commit boundary for the list textarea | |
| "the last line of POC is modified" / "there is a new last line" | **No event.** `pocLastStep` is a pure derivation over current state ([app.js#L1209-L1223](app/web/static/app.js#L1209-L1223)); nothing watches it | |
| "data is not equal to the vuln library" | **Derived only**, via `sameFragments` at render | [app.js#L1239](app/web/static/app.js#L1239) |

So: title and status and fragment-deletion are events; **everything about text content is state-derived**.

#### The autosave / undo machinery

```js
function scheduleSave() {
  saveRetryCount = 0;
  const textEntry = activeTextEntry();
  if (textEntry && activeTextTransaction?.input === textEntry) { ...; queueReportChange(); return; }
  if (!textEntry) finalizeTextTransaction();
  const changes = diff(previousReport, report);
  if (changes.length) {
    const action = {changes};
    undoHistory.push(action);
    ...
    activeTextTransaction = textEntry ? {input:textEntry, before:clone(previousReport), action} : null;
    storeHistory();
    previousReport = clone(report);
  }
  ...
  queueReportChange();
}
```
[app.js#L708-L735](app/web/static/app.js#L708-L735)

- `diff(before, after, path)` — recursive structural diff producing `{path, beforePresent, before, afterPresent, after}` records ([app.js#L532-L543](app/web/static/app.js#L532-L543)).
- `previousReport` — the undo baseline, re-cloned whenever a diff is banked ([app.js#L104](app/web/static/app.js#L104), reassigned at L733, L597, L604).
- `activeTextTransaction` — `{input, before, action}`, opened on the first edit in a focused field so the whole field session is one undo step.
- `finalizeTextTransaction()` — recomputes `action.changes = diff(activeTextTransaction.before, report)`, splices out an empty net diff, and re-clones `previousReport` ([app.js#L596-L605](app/web/static/app.js#L596-L605)). Called from `focusout` ([app.js#L703](app/web/static/app.js#L703)), `pagehide` ([app.js#L871](app/web/static/app.js#L871), [app.js#L910](app/web/static/app.js#L910)), the top of `undo`, list paste ([app.js#L2566](app/web/static/app.js#L2566), [app.js#L2575](app/web/static/app.js#L2575)), and `scheduleSave` when nothing is focused.
- `queueReportChange()` — 100 ms debounce, then `document.dispatchEvent(new Event("reportchange"))` ([app.js#L385-L390](app/web/static/app.js#L385-L390)). Listeners: `updateSetupSectionSummaries` ([app.js#L675](app/web/static/app.js#L675)) and `updateReadinessPanel` ([app.js#L2931](app/web/static/app.js#L2931)).

**Is there already a "what changed since the last save" computation?** Yes, in two forms, and both are usable but imperfect for your purpose:

1. **`diff(previousReport, report)` inside `scheduleSave`** ([app.js#L721](app/web/static/app.js#L721)). This is the closest thing to a change feed. Its `changes` array carries full paths like `["vulnerabilities", 3, "contents", 1, "fragments", 0, "items", 2, "runs", 0, "text"]`, so *"a fragment in `recommended_remediation` was modified"* and *"the last item of the POC list changed"* are both extractable from it. **Caveat:** while a text field is focused, `scheduleSave` takes the early-return branch at [app.js#L711-L718](app/web/static/app.js#L711-L718) and **never computes a diff at all** — so per-keystroke text edits produce no change records until `finalizeTextTransaction` runs on blur.
2. **`finalizeTextTransaction`** ([app.js#L598](app/web/static/app.js#L598)) recomputes the full field-session diff on `focusout`. That is a real "the tester finished editing this field, and here is exactly what changed" signal — the only commit-boundary event the list textarea has. A trigger could hang off it.

The `reportchange` event is debounced and carries **no payload** — it is a "recompute yourself" ping, not a change feed.

#### Every caller of `render()` in the editor

`render` is defined at [app.js#L2932](app/web/static/app.js#L2932). Callers:

| Line | Trigger |
|---|---|
| [L2916](app/web/static/app.js#L2916) | readiness-panel "Go to" that must switch finding or expand a section |
| [L2948](app/web/static/app.js#L2948) | empty-state "Add vulnerability" |
| [L2965](app/web/static/app.js#L2965) | nav rail finding jump |
| [L3041](app/web/static/app.js#L3041) | `finishTitle` (title committed) |
| [L3079](app/web/static/app.js#L3079) | content-section expand/collapse toggle |
| [L3113](app/web/static/app.js#L3113) | Banner A resolve (both Use it and Dismiss) |
| [L3137](app/web/static/app.js#L3137) | Banner B "Put it back" |
| [L3158](app/web/static/app.js#L3158) | POC offer install |
| [L3165](app/web/static/app.js#L3165) | POC offer refuse |
| [L3206](app/web/static/app.js#L3206) | description/remediation offer resolve (all three buttons) |
| [L3234](app/web/static/app.js#L3234) | "+ Add a fragment" menu |
| [L3285](app/web/static/app.js#L3285) | initial render at the end of `continuousEditor()` |

Plus the `rerender` alias, which **is** `render` passed down as the third argument to `renderFragment` / `renderEvidenceSet` ([app.js#L3247](app/web/static/app.js#L3247), [app.js#L3252](app/web/static/app.js#L3252)): 14 call sites at [L2269](app/web/static/app.js#L2269), [L2298](app/web/static/app.js#L2298), [L2379](app/web/static/app.js#L2379), [L2403](app/web/static/app.js#L2403), [L2426](app/web/static/app.js#L2426), [L2445](app/web/static/app.js#L2445), [L2469](app/web/static/app.js#L2469), [L2485](app/web/static/app.js#L2485), [L2493](app/web/static/app.js#L2493), [L2518](app/web/static/app.js#L2518), [L2636](app/web/static/app.js#L2636), [L2647](app/web/static/app.js#L2647), [L2651](app/web/static/app.js#L2651), [L2662](app/web/static/app.js#L2662) — fragment delete, image environment change, evidence upload/remove, table row/column add/remove.

**Nothing in that list is a text edit.** `rich()`'s `oninput` calls `onChange` then `scheduleSave`, never `render` ([app.js#L967](app/web/static/app.js#L967)) — deliberately, because re-rendering would destroy the caret. Undo/redo re-render by doing a full `window.location.reload()` ([app.js#L591](app/web/static/app.js#L591)).

**Consequence for your plan:** a state-derived banner keyed on typed text appears only after the tester deletes a fragment, toggles a section, adds a fragment, clicks another banner, switches findings, or reloads. Typing into the POC list and then looking at the In Conclusion section in the same expanded view will not produce a banner.

---

### 7. Invariants and twins

#### Must change in pairs (verified against source, not the map)

| Rule | Python | JavaScript |
|---|---|---|
| which sections a status prints | [content_types_for_status](app/report_service.py#L162) | [contentTypesForStatus](app/web/static/app.js#L1015) |
| section provisioning + seed fragments | [provision](app/report_service.py#L192) | [provision](app/web/static/app.js#L1027) |
| one numbered list always survives | [ensure_proof_steps](app/report_service.py#L155) | [ensureProofSteps](app/web/static/app.js#L1183) |
| resolved remediation boilerplate + marker | [report_service.py#L20](app/report_service.py#L20), [#L222-L232](app/report_service.py#L222-L232) | [app.js#L115](app/web/static/app.js#L115), [#L1041-L1046](app/web/static/app.js#L1041-L1046) |
| whether a section holds tester work | [content_has_work](app/report_service.py#L169) | [contentHasWork](app/web/static/app.js#L1019) |
| the conclusion sentence, builder and recogniser | [status_conclusion_runs](app/report_service.py#L408), [STATUS_CONCLUSION_PATTERN](app/report_service.py#L405) | [app.js#L117-L122](app/web/static/app.js#L117-L122) |
| locating the sentence in a paragraph | [default_conclusion_span](app/report_service.py#L419), [default_conclusion_start](app/report_service.py#L432), [is_default_status_conclusion](app/report_service.py#L442) | [app.js#L123-L138](app/web/static/app.js#L123-L138), [isDefaultStatusConclusion](app/web/static/app.js#L985) |
| splitting runs at the boundary | [_runs_up_to](app/report_service.py#L449) / [_runs_after](app/report_service.py#L463) | `runsUpTo` / `runsAfter` ([app.js#L139-L160](app/web/static/app.js#L139-L160)) |
| which conclusion paragraph the app may write | conclusion block in [provision](app/report_service.py#L233-L250) | [syncConclusion](app/web/static/app.js#L991-L1013) |
| library POC selection | [applicable_poc_variants](app/report_service.py#L320) | [applicablePocVariants](app/web/static/app.js#L1120) |
| installing POC steps, replace/merge | [apply_poc_variant](app/report_service.py#L496) | [applyPocVariant](app/web/static/app.js#L1195) |
| collapsing adjacent step lists | [merge_step_lists](app/report_service.py#L482) | [mergeStepLists](app/web/static/app.js#L1188) |
| image slot sync | [sync_evidence_image_slots](app/report_service.py#L344) | [syncEvidenceImageSlots](app/web/static/app.js#L1140) |
| a printed section that must never be empty | [docx_report.py#L115](app/docx_report.py#L115) | `requiresFragment` [app.js#L112](app/web/static/app.js#L112) |
| a conclusion still holding the default sentence | [docx_report.py#L117-L124](app/docx_report.py#L117-L124) | `fragmentIssues` |
| affected channels / environments | [affected_channels](app/report_service.py#L298), `affected_environments` | [affectedChannels](app/web/static/app.js#L1105), [affectedEnvironments](app/web/static/app.js#L1101) |

#### Client-only today, and would stay client-only

- **All five offers and banners themselves.** Nothing in Python renders, decides, or suppresses one.
- **`sameFragments`** ([app.js#L1226](app/web/static/app.js#L1226)) and **`pendingLibraryOffers`** ([app.js#L1230](app/web/static/app.js#L1230)) — no Python counterpart exists or is referenced.
- **`pocLastStep`** ([app.js#L1209](app/web/static/app.js#L1209)) — no Python counterpart.
- **`offerConclusionRewrite`** ([app.js#L1053](app/web/static/app.js#L1053)).
- **`applyLibraryEntry` / `replaceFromLibrary`** ([app.js#L1813-L1827](app/web/static/app.js#L1813-L1827)) — the whole Findings-page title-swap path.
- **`fragmentHasContent`** ([app.js#L973](app/web/static/app.js#L973)) — related to but distinct from `content_has_work`.
- **`deletionBlockedReason`** ([app.js#L1167](app/web/static/app.js#L1167)) and all confirmation dialogs.
- **Reading `content_offer_resolved` and `conclusion_offer_resolved`.** The server writes the first at insert and round-trips both; it reads neither.

#### What the readiness contract test covers here

`test_browser_readiness_verdict_matches_server_generation_issues` ([test_browser.py#L1962](tests/test_browser.py#L1962)) drives a real browser, mirrors the save route with `main.provision_report` + `workspace.save`, and asserts `#issue-count[data-state]` and the Generate button against `generation_issues`. Nine cases ([test_browser.py#L2010](tests/test_browser.py#L2010)): `unchanged`, `blank_caption`, `placeholder_text`, `no_affected_location`, `missing_rating`, `stale_image_for_unaffected_environment`, `default_conclusion_left_in_place`, `conclusion_section_emptied`, `quoted_step_before_default_conclusion`.

**In this area it covers the conclusion rules only** — the last three cases. It does **not** cover: any offer's show condition, `sameFragments`, `content_offer_resolved`, `conclusion_offer_resolved`, `pocLastStep`, POC variant gating, or the resolved → open remediation transition. Those have narrower coverage elsewhere:

- [test_app.py#L1422](tests/test_app.py#L1422) `test_a_library_insert_does_not_offer_back_the_content_it_just_copied` — asserts `insert_library` pre-answers `content_offer_resolved`.
- [test_app.py#L1795](tests/test_app.py#L1795) `test_the_conclusion_offer_memory_round_trips_and_refuses_null`.
- [test_browser.py#L1463](tests/test_browser.py#L1463), [#L1533](tests/test_browser.py#L1533), [#L1670](tests/test_browser.py#L1670), [#L1718](tests/test_browser.py#L1718) — POC offer visibility.
- [test_browser.py#L1831](tests/test_browser.py#L1831), [#L1873](tests/test_browser.py#L1873) — Banner A.
- [test_browser.py#L1216](tests/test_browser.py#L1216) — the description/remediation offer not gaining an empty paragraph.

**There is no test at all for Banner B (restore default)** — a search for `data-conclusion-restore` across `tests/` returns nothing.

---

### 8. Drafts on disk

**Seven `draft.json` files, 23 findings, 17 with a `library_ref`.**

#### `content_offer_resolved` and `conclusion_offer_resolved` — complete census

| Report | Findings | `content_offer_resolved` | `conclusion_offer_resolved` |
|---|---|---|---|
| [Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235](data/apps/Fragment_Coverage_Demo/2026-09_Annual_Pentest_b0867e631235/draft.json) | 5, all `library_ref: null` | `{}` ×5 | `["Observe an authenticated session for the first account in the table."]` on the first; `[]` ×4 |
| [Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd](data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json) | 1, VDB-047 | `{description: "VDB-047", recommended_remediation: "VDB-047"}` | `["fg"]` |
| [Northstar_Banking/2026-09_Report_84b9ebe1bbdd](data/apps/Northstar_Banking/2026-09_Report_84b9ebe1bbdd/draft.json) | 1, `library_ref: null` | **key absent** (legacy draft, still carries retired `poc_variant: null`) → defaults to `{}` | key absent → `[]` |
| [Prompt_Reference/2026-09_Annual_Pentest_5395baea9d23](data/apps/Prompt_Reference/2026-09_Annual_Pentest_5395baea9d23/draft.json) | 2, VDB-015 and VDB-050 | `{}` ×2 | `[]` ×2 |
| [Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json) | 14, all with `library_ref` | see below | `[]` ×14 |
| unnamed/2026-09_Report_404ecd327eea | 0 | — | — |
| unnamed/2026-09_Report_d96116840c2f | 0 | — | — |

Vuln_Library_QA, per finding:

| Entry | `content_offer_resolved` | `poc_variants` |
|---|---|---|
| VDB-012 | both keys | `[]` |
| VDB-014 | `{}` | `[]` |
| VDB-015 | **`recommended_remediation` only** | `["web","api"]` |
| VDB-026 | both keys | `[]` |
| VDB-028 | both keys | `[]` |
| VDB-032 | `{}` | `[]` |
| VDB-035 | `{}` | `[]` |
| VDB-036 | both keys | non-empty |
| VDB-039 | both keys | non-empty |
| VDB-040 | **`description` only** | non-empty |
| VDB-041, VDB-042, VDB-043, VDB-048 | `{}` ×4 | `[]` |

Totals across all 23 findings: **7 have at least one `content_offer_resolved` key** (5 with both, 2 with one); **16 have `{}` or the key absent**. **2 findings have a non-empty `conclusion_offer_resolved`**; 21 have `[]`.

#### Byte-equality against the library

Scope note, so the next agent does not over-read this: I byte-compared **5 of the 17** `library_ref` findings against their library entries by reading both sides in full. The other 12 (VDB-028, VDB-032, VDB-035, VDB-036, VDB-039, VDB-040, VDB-041, VDB-042, VDB-043, VDB-048, VDB-050, and Prompt_Reference's second finding) I did **not** read end to end; I can see their `content_offer_resolved` state but not their equality state. I have no terminal in this session, so this could not be scripted.

What the five show:

| Finding | description equal? | recommended_remediation equal? | Why |
|---|---|---|---|
| Northstar VDB-047 | **YES** — single paragraph, identical text ([draft.json#L104-L120](data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json#L104-L120) vs [vuln_library.json#L4701-L4714](resources/vuln_library.json#L4701-L4714)) | **NO** — draft holds one empty paragraph; library holds `bulleted_list` + `note`. This is a resolved → open round trip | latch at `content_offer_resolved` suppresses both today |
| QA VDB-012 | **NO** — draft has the library's two paragraphs **plus a third `code_block` with `text: ""`** the tester added ([draft.json#L140-L143](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json#L140-L143)) | **NO** — library's single paragraph **plus an empty 2×1 `table`** ([draft.json#L160-L181](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json#L160-L181)) | latch suppresses both |
| QA VDB-014 | **YES** (2 paragraphs, texts match) | **YES** (1 paragraph, text matches [vuln_library.json#L1405-L1417](resources/vuln_library.json#L1405-L1417)) | `content_offer_resolved: {}`, so **`sameFragments` alone** is what suppresses the offer here |
| QA VDB-015 | **YES** (2 paragraphs, match [vuln_library.json#L37-L58](resources/vuln_library.json#L37-L58)) | **YES** (1 paragraph, matches [vuln_library.json#L59-L72](resources/vuln_library.json#L59-L72)) | description has **no** latch key; `sameFragments` is the only suppressor |
| QA VDB-026 | **YES** (1 paragraph) | **YES** (2 paragraphs + `note`, exact order and text, [vuln_library.json#L564-L609](resources/vuln_library.json#L564-L609)) | latch also set |

#### What this means for an equality-based trigger

**It would fire immediately on existing work, and not rarely.** Of the five I verified, **two findings** (VDB-047's remediation, VDB-012's both sections) already differ from their library entry while carrying a `content_offer_resolved` latch that currently hides that fact. The VDB-012 case is the sharpest: the *only* difference is an empty `code_block` and an empty `table` the tester dropped in and never filled. A pure `sameFragments` trigger treats that as "the tester diverged from the library" and re-offers to overwrite prose that is byte-identical to the library.

Conversely, **three findings are exactly equal**, and two of those (VDB-014, VDB-015's description) are suppressed *today* by `sameFragments` alone with no latch — so the equality check is already load-bearing and already correct in those cases.

#### On your open question

> *"for the description and recommended remediation, I was thinking if we need a checker if they are equal to the vuln library data to know when to prompt. since if the finding name is changed to a vuln from library, this prompt will trigger as well."*

Reporting only what is established in source, without recommending a design:

- **The checker already exists and already runs on exactly that path.** `applyLibraryEntry` clears `content_offer_resolved` to `{}` ([app.js#L1821](app/web/static/app.js#L1821)), which is precisely the "finding name changed to a library vuln" case you describe — and at that moment `sameFragments` at [app.js#L1239](app/web/static/app.js#L1239) is the *only* thing left deciding whether the banner shows. That is the situation QA VDB-014 and VDB-015 are in on disk right now.
- **Its current sensitivity is structural, not semantic.** It compares serialised fragment arrays, so an empty table or an unfilled code block flips it to "differs" (VDB-012). There is no text-only or normalised comparison anywhere in the codebase.
- **The latch and the equality check are ANDed, not ORed** ([app.js#L1234-L1240](app/web/static/app.js#L1234-L1240)): every filter must pass for the offer to appear. So today equality can only *suppress* an offer, never cause one. Making equality a *trigger* would be a new direction of causation for that field.

---

### Map drift — corrected in `docs/DATA_MAP.md`

Three places where the source contradicted the map. Source wins; I updated the map and recorded the verification in its header line.

1. **§1 directory tree and §2 identity table — folder naming was two schemes out of date.** The map said `<LETTER>_<app_id>/` (e.g. `X_unnamed`) and `<YYYY-MM>_Report_<report_id[2:]>` derived from the save-time month, both attributed to `Workspace._save_unlocked`. The source says the app folder is `safe_name(engagement.app_name, "unnamed")` with no letter prefix ([workspace.py#L46-L52](app/workspace.py#L46-L52)) and the report folder is `<YYYY-MM>_<ReportTypeLabel>_<report_id[2:]>` from `engagement.report_date` and `report_type` ([workspace.py#L55-L59](app/workspace.py#L55-L59)). Disk agrees: `data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/`.
2. **§2 "Folder migration" — said there is one migration gated on `X_unnamed`.** There are **two independent** renames, and the report folder has its own provisional-label gate ([workspace.py#L346-L363](app/workspace.py#L346-L363)). A vacated app folder is also `rmdir`'d, which the map did not mention.
3. **§12 — `offerConclusionRewrite` "awaited at all five client-side title and status writes".** It is awaited at **three**; the other two (`titleInput.oninput`, `applyLibraryEntry`) re-derive via `syncConclusion` without prompting. The map's own next sentence already half-admitted this.

Everything else I checked in §6, §7, §8 and §12 matched source, including the `content_offer_resolved` / `conclusion_offer_resolved` descriptions, the 12-entry POC count, `insert_library`'s pre-answering, and the two-arm conclusion selection with no "first text-less paragraph" arm.

## Round 1 - Planner: proposal and open questions

### Understanding

You want six prompts to fire in situations where, today, four of them are silently suppressed and two never re-render. The thread running through all six is not "the section differs from the library" — it is **"the section has lost its content and the library still has some."** Three of your six bullets already work exactly as you describe (name-change re-offer, In Conclusion default rewrite, In Conclusion last-step quote); one is already handled silently by the server; and the two genuinely missing behaviours are a *permanent* memory flag that never releases, and the fact that banners are only recomputed when the page redraws, which typing never does.

---

### A. Blast radius

| File | Change | Why |
|---|---|---|
| [app/web/static/app.js](app/web/static/app.js) — `pendingLibraryOffers` (L1230–1248) | One added clause per section family: the `content_offer_resolved` latch and `poc_variant_declined`/`poc_variants` are bypassed when the section holds no content | The only place offers are decided; the readiness panel and both banners read it |
| [app/web/static/app.js](app/web/static/app.js) — `buildContentBlock` (L3082–L3216) | Extract the four banner bodies into one pure `contentOffersFor(finding, content)` returning nodes, rendered into a dedicated `.offer-slot` inserted after the heading | Today the banners can only be built by `render()`; this gives them a second, caret-safe renderer |
| [app/web/static/app.js](app/web/static/app.js) — near `document.addEventListener("reportchange", updateReadinessPanel)` (L2931) | New read-only listener `refreshContentOffers()` that refills every `.offer-slot` except in the block containing the active element | `reportchange` already fires 100 ms after every keystroke; this is the missing cadence, at zero new plumbing |
| [app/web/static/app.js](app/web/static/app.js) — `sameFragments` (L1226) | **No change** | It stays a suppressor; see decision 2 |
| [app/report_service.py](app/report_service.py) | **No change** | Deliberate: no server twin, see decision 5 |
| [app/models.py](app/models.py) | **No change** | Deliberate: no new persisted field, see decision 1 |
| [tests/test_browser.py](tests/test_browser.py) | 6 new tests (5 new behaviours + the missing Banner B test) | Every rule here is client-side; the scope map routes `app.js` to `tests.test_browser` |
| [tests/test_app.py](tests/test_app.py) | 1 new test asserting `content_offer_resolved` survives a status-change save untouched | Pins "the server must never clear the latch" so a future twin cannot be added by accident |
| [docs/DATA_MAP.md](docs/DATA_MAP.md) | Section 6's `content_offer_resolved` paragraph gains the release condition; section 7 unchanged | Required by the data-layer maintenance contract |
| [docs/plans/content-offer-triggers.md](docs/plans/content-offer-triggers.md) | Append "Round 2 – decisions" | Keeps the oracle's record and the decision in one file |

**Duplicated rules touched: none.** Everything changed is in the client-only column of the oracle's twin table. That is a deliberate property of the design, not luck.

---

### C. Design decisions

**1. The trigger should be the existing latch, plus one escape hatch: emptiness. Not equality.**

Answering your open question directly: **no, you do not need an equality checker to decide when to prompt.** You already have one (`sameFragments`), it already runs, and it should stay pointed the way it is — as a *suppressor* that stops a finding being offered back the text it was born with. Turning it into a trigger reverses its direction of causation and immediately produces the wrong answer (see decision 2).

The rule becomes: the latch suppresses the offer **unless the section holds nothing**. In code terms, one added clause:

```
.filter(type => finding.content_offer_resolved?.[type] !== entry.library_id
              || !sectionHasContent(finding, type))
```

This delivers your first three bullets: name changed to a library vuln (already worked — the latch is wiped by `applyLibraryEntry`), fragment deleted until the section is bare, and the resolved → open case, which falls out for free because a reopened remediation *is* an empty paragraph.

Rejected: option (iv), deriving an event from `finalizeTextTransaction`'s diff. It is real and it would work, but it buys nothing the state-derived version doesn't already give, and it reintroduces the two failure modes the current banners were explicitly designed out of — a missed event and a double-fire. The in-source comment at the POC offer says so in as many words.

**2. Keep `sameFragments` structural. An empty `code_block` counts as divergence, and that is correct.**

Your VDB-012 finding on disk differs from its library entry only by an empty code block and an empty table. Under a pure-equality trigger it would immediately offer to overwrite prose that is byte-for-byte identical. Under this design that same divergence is harmless, because divergence alone no longer causes anything — it only *fails to suppress*, and the latch is still suppressing. A suppressor's dangerous failure is being too strong (silence); normalising the comparison would make it stronger. Leave it alone.

**3. "A fragment is modified" should NOT re-offer. I do not believe you want it.**

Read your own two bullets side by side. For In Conclusion you wrote "*yes it is okay to show even if they are the ones that deleted it*" — you granted that licence explicitly, and only there. For description and remediation you wrote "modified/deleted" and then immediately reached for "or if the data is not equal to the library," which reads like someone looking for a way to *detect* the reopen case, not like someone asking to be interrupted mid-edit. A tester who rewords library prose — the normal workflow — would get a permanent banner asking them to put it back. This is the one point I'd most want you to confirm, and it is open question 1.

**4. "POC is empty" means no written steps — the predicate that already exists.**

`written = content.fragments.some(f => f.type !== "image" && fragmentHasContent(f))`, live today at the POC banner where it only swaps button labels. It excludes images on purpose: a screenshot is not a step, and "I have a screenshot but no steps" is exactly the state you want offered. Promote it from a label-chooser to a suppressor-override, so an emptied proof of concept re-offers regardless of `poc_variants` and `poc_variant_declined`. No new predicate, no new field. (Whether it should also override `poc_variants`, not just declines, is open question 3.)

**5. Resolved → open must NOT clear the remediation latch, and must NOT get a server twin.**

It doesn't need to. The reopen leaves one empty paragraph; emptiness bypasses the latch; the offer appears. Actively clearing the latch would mean mutating a field that records the tester's answer, from inside `provision` — derived-state code that runs on every save on both sides. The browser would clear it, the server would clear it again, and a tester who then pressed "Keep mine" could have that answer wiped by the next save. That is the derived-state-fight failure mode with a data-loss tail, for a behaviour we get for free.

**6. The In Conclusion "update the default with the new value" prompt already exists. So does the last-step prompt. Neither needs a rule change.**

`offerConclusionRewrite` is wired to all three title commits and the status change. When the paragraph still holds the app's own sentence it is rewritten *silently* — correctly, because there is nothing of yours to lose. When it holds your prose, you get the dialog. And Banner A already re-offers a changed last line, because `conclusion_offer_resolved` stores the text, so reworded text is a new key.

Likewise **Banner B needs no change.** Deleting the last paragraph is blocked (`in_conclusion` is in `requiresFragment`); deleting a paragraph while leaving only a note is silently repaired by `syncConclusion` on the next save; and deleting the sentence while leaving your own prose *should not* prompt — that's a finished conclusion. What's missing for all three of these is not a rule. It is cadence.

**7. Banners must appear without a re-render, and the cheapest safe mechanism already exists.**

`scheduleSave` calls `queueReportChange()` on every path — including the early-return branch taken while a text field has focus — and that dispatches a debounced `reportchange` 100 ms later. `updateReadinessPanel` already listens to it and rebuilds itself from state. Add a second listener that refills the banner slots, **skipping any `[data-content-type]` block containing `document.activeElement`.** That one guard buys three things at once: no layout shift under the cursor, no button swapped out from under a click, and the In Conclusion banner appearing the instant you leave the POC list.

The hard invariant: `refreshContentOffers` must never call `scheduleSave`. A write inside a `reportchange` listener is a feedback loop that hammers the backend and burns through the single `draft.bak.json` on every pass.

**8. Four changes, in this order: cadence, then description/remediation, then reopen verification, then POC.**

Cadence first because it is a pure refactor with no rule change, it makes the existing banners honest, and it is what makes steps 2–4 observable and testable at all. Fragment *deletion* already re-renders, so step 2's delete path would work without step 1 — but its clear-by-typing path would not.

---

### D. Open questions

**Three decisions are waiting.** The other two are: whether the Content page's own title box should swap library entries the way the Findings page does (today it deliberately does not), and whether an emptied proof of concept should re-offer steps you previously *installed*, not just ones you previously declined. I'll raise those after this one.

**Question 1 — when you edit library wording, should the app keep offering to put the original back?**

*Background.* When you pull a finding in from the library, it arrives with the library's Description and Recommended Remediation already in it, and the app records that you've "answered" those two sections so it stops offering them. That record never releases. It is why reopening a resolved finding leaves you with a blank remediation and no way to get the library's version back — the fix everyone agrees on.

The question is how far to release it.

*Option A (my recommendation): release only when the section is empty.* You delete or clear everything in a section, and the banner comes back offering the library's version. You edit the wording, add a sentence, restructure it — nothing happens, because the section still holds your work.

*Option B: release whenever the section differs from the library in any way.* This is closer to your literal wording. It also means the banner returns the moment you change a single word, and stays there permanently, because you're never going back to matching the library exactly. On today's data it would also fire on a finding that differs from the library only by an empty code block and an empty table someone dropped in — offering to overwrite text that is already identical.

*Tradeoff.* Option A can't help you if you *partially* mangle a section and want the original back; you'd have to clear it first. Option B can't be dismissed permanently for anyone who customises library prose, which is most of the time.

*My recommendation: Option A.* It delivers every case you described — the reopen, the accidental delete, the name change — without turning the banner into something you learn to ignore.

---

### B. Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| Stale write | **clear** | No new route and no new mutation path. Every banner write already goes through `scheduleSave` → `PUT` with `saved_at` in the body. |
| Lost update | **clear** | No server change at all, so nothing new reads-then-writes outside `Workspace._locked`. |
| Orphan reference | **clear**, non-obviously | Widening the offer means "Use library version" (which calls `dropUnreferencedEvidence`) can be clicked in more states. But it only becomes clickable when the section holds no content, and `fragmentHasContent` counts `evidence_id` as content — so an offerable section provably has no evidence to orphan. For the proof of concept, `applyPocVariant` preserves every image by construction in both modes. |
| Silent stranding | **clear** | Scope, environments and `target_ids` are untouched. |
| Schema break | **clear** | No new persisted field. Every existing `draft.json` loads byte-identically, `validate_references` is unaffected, no `load_path` repair needed. This is the main reason I rejected storing a fingerprint of the answered content. |
| Existing drafts start showing offers | **RISK, bounded and intended** | 17 findings on disk carry a `library_ref`; 9 have an empty latch and already see offers today, so nothing changes for them. **At most the 8 with a latch set can change**, and only where a section currently holds no work. I verified one that does: Northstar `v_852106ea` (VDB-047, reopened) gains a Remediation banner and a "Suggested" readiness row — which is precisely the outcome you asked for. The other 7 need a sweep before shipping; that is step 0 below, not a guess. |
| Request/response asymmetry | **clear** | No field is sent that isn't returned. Nothing new is sent at all. |
| Rule drift (Python/JS twins) | **clear, by design choice** | Every function touched — `pendingLibraryOffers`, `sameFragments`, `fragmentHasContent`, the banners — is client-only in the oracle's own twin table. I deliberately chose `fragmentHasContent` over the twinned `contentHasWork`: the two give identical answers on every reachable state for these sections, but `contentHasWork` is owned by the status-carry rule, and borrowing it would mean a future change there silently moved the offers. |
| Readiness and the contract test | **clear** | Offers render as `suggestion: true` warning rows and are never counted toward the verdict or the Generate button. `test_browser_readiness_verdict_matches_server_generation_issues` compares the verdict against `generation_issues`, which cannot move. The panel gains rows; the verdict does not. |
| Navigation trap | **clear** | No offer gates any page. |
| Derived-state fight | **clear, but load-bearing on one guard** | `provision` seeds starter fragments only `if (!content.fragments.length)`. An emptied section still holds one text-less paragraph, so the server leaves it alone and the offer is stable across saves rather than flickering. And `deletionBlockedReason` makes zero fragments unreachable for both sections. If either guard is ever relaxed, this breaks. |
| Backup exhaustion | **RISK — the single most dangerous bug available here** | `refreshContentOffers` runs inside a `reportchange` listener. If it ever writes to `report` and calls `scheduleSave`, that dispatches another `reportchange`, which refreshes again: an unbounded loop of PUTs, each consuming the one-deep `draft.bak.json`. Mitigated by making the function read-only and pinning that with an assertion test, not a comment. |
| Banner acts on text the tester didn't read | **RISK, mitigated** | A refresh tick between reading a banner and clicking it could swap the button for one carrying different text. The per-block active-element skip covers it: a focused banner's block is never refreshed. |

---

### E. Plan

**Step 0 — Sweep the 8 latched findings.** Load each `data/apps/*/*/draft.json`, and for every finding with a `library_ref` and a non-empty `content_offer_resolved`, report which of its Description / Recommended Remediation sections hold no `fragmentHasContent` fragment. *No files change.* This converts "at most 8 findings can change" into an exact list before any of it ships. **Invariant protected:** we never discover the blast radius from a user's screenshot.

**Step 1 — Make banners renderable without `render()`.**
*Files:* [app/web/static/app.js](app/web/static/app.js) — extract the four banner bodies from `buildContentBlock` into `contentOffersFor(finding, content)`; add an `.offer-slot` node; add the `refreshContentOffers` listener beside `updateReadinessPanel`.
*Tests:* `tests/test_browser.py::test_the_conclusion_offer_appears_without_a_rerender_after_a_step_is_typed`, `::test_refreshing_offers_does_not_change_the_report` (stringify `report` before and after a tick), and the missing `::test_clearing_the_conclusion_offers_the_standard_sentence_back` for Banner B.
*Invariants:* the refresh is read-only and never calls `scheduleSave`; the caret and `document.activeElement` survive a tick; a block containing the active element is never rebuilt. **No rule changes in this step** — the banner set is identical before and after, which is what makes it reviewable.

**Step 2 — Release the latch on an empty Description or Recommended Remediation.**
*Files:* [app/web/static/app.js](app/web/static/app.js) — one added `.filter` clause in `pendingLibraryOffers`.
*Tests:* `tests/test_browser.py::test_emptying_a_library_section_offers_it_back` and — the more important one — `::test_editing_a_library_section_does_not_offer_it_back`.
*Invariant:* the resolved-remediation exclusion stays the **first** filter, or a resolved finding's locked remediation would read as empty and offer itself.

**Step 3 — Prove the reopen case, and pin that no server twin appears.**
*Files:* none in `app/`; this step asserts that step 2 already did the work.
*Tests:* `tests/test_browser.py::test_reopening_a_resolved_finding_offers_the_library_remediation`; `tests/test_app.py::test_a_status_change_leaves_the_content_offer_memory_untouched` (save a reopen, assert `content_offer_resolved` round-trips byte-identical).
*Invariant:* `provision` never mutates `content_offer_resolved` on either side. The Python test is the guard rail that stops someone "helpfully" adding the twin later.

**Step 4 — Release the proof-of-concept suppressors on an empty section.**
*Files:* [app/web/static/app.js](app/web/static/app.js) — `pendingLibraryOffers`' `variants` clause reuses the `written` predicate; move it up from the banner so both read one source.
*Test:* `tests/test_browser.py::test_a_declined_poc_offer_returns_once_the_steps_are_emptied`.
*Invariants:* images are excluded from "written" and preserved by `applyPocVariant` in both modes; `applicablePocVariants`' channel gating is untouched, so a mobile-only finding is still offered nothing.

**Step 5 — Documentation.** [docs/DATA_MAP.md](docs/DATA_MAP.md) section 6 gains the latch's release condition; [docs/plans/content-offer-triggers.md](docs/plans/content-offer-triggers.md) gains a "Round 2 – decisions" section. Required by the data-layer maintenance contract. No tests.

---

### What I would not do

**I would not store a snapshot or hash of the content each offer was answered against.** It is the obvious way to express "has this drifted since you decided," and it is a trap. It adds a persisted field to `Vulnerability`, so every existing draft needs a default and a decision about what a missing value means; it needs a writer at four call sites, each of which can now record a stale snapshot if it runs in the wrong order; and the moment the server touches the same section — which `provision` does on every single save — the stored snapshot and the live content disagree for reasons that have nothing to do with the tester. It would turn a two-line client-side filter into a schema change with a migration, a twin obligation, and a new class of drift bug, to express a rule that "is the section empty" already expresses correctly using data that is already on disk.

## Round 2 - Oracle: verdict on the proposal

### Headline: the missing risk row

**Under Option A, the Dismiss / Keep-mine button on an empty section is a no-op, and the banner becomes undismissable.**

The keep arm writes the latch and nothing else:

```js
(finding.content_offer_resolved ||= {})[content.type] = entry.library_id;
if (mode !== "keep") { ... }
```
[app.js#L3200-L3203](app/web/static/app.js#L3200)

Then it calls `render()` ([app.js#L3206](app/web/static/app.js#L3206)), which re-runs `pendingLibraryOffers`. The proposed clause is `latch !== library_id || !sectionHasContent(...)`. The section is still empty — Keep changed no fragments — so the right side is still true, the offer is still pending, and the banner is redrawn identically. The same applies to the POC "Dismiss"/"Keep mine" arm, which writes `poc_variant_declined` ([app.js#L3163-L3166](app/web/static/app.js#L3163)) and likewise changes no fragments.

This is not a corner case. It lands exactly on Northstar `v_852106ea` — the reopened remediation the planner names as the design's proof. Reopen a finding, get the banner as intended, press Dismiss, and the banner is still there. Forever.

The design needs a third arm: Keep must either write something that counts as content, or the release condition must be "empty **and** the latch was not answered since the section became empty" — which is a state the current field cannot express, and which is precisely the fingerprint the planner (correctly) refused to add. This is the one open problem in the proposal, and it is not in the risk table.

---

### 1. Risk-row verdicts

| Row | Planner | Verdict | Evidence |
|---|---|---|---|
| Stale write | clear | **CONFIRMED** | Every banner arm ends `render(); scheduleSave();` ([app.js#L3206](app/web/static/app.js#L3206), [#L3158](app/web/static/app.js#L3158)); no new route |
| Lost update | clear | **CONFIRMED** | No `app/` Python change proposed; `provision_report` only calls `provision` + `sync_evidence_image_slots` ([main.py#L261-L265](app/main.py#L261)) |
| Orphan reference | clear, non-obviously | **CONFIRMED, both halves** | see below |
| Silent stranding | clear | **CONFIRMED** | no scope path touched |
| Schema break | clear | **CONFIRMED** | see §3 |
| Existing drafts show offers | RISK, bounded | **CONFIRMED as a risk; the supporting numbers are wrong** | see §3 |
| Request/response asymmetry | clear | **CONFIRMED** | |
| Rule drift | clear, by design | **WRONG as written, conclusion still safe** | see below |
| Readiness / contract test | clear | **CONFIRMED** | offers enter as `suggestion: true`, excluded from `issues` and from the Generate gate ([app.js#L2861-L2870](app/web/static/app.js#L2861)) |
| Navigation trap | clear | **CONFIRMED** | |
| Derived-state fight | clear, load-bearing on one guard | **CONFIRMED for description/remediation; INCOMPLETE for POC** | see below |
| Backup exhaustion | RISK | **CONFIRMED, both sub-claims** | see below |
| Banner swapped mid-click | RISK, mitigated | **CONFIRMED as a risk, mitigation is partial** | see Decision 7 |
| *(missing)* Dismiss is a no-op | — | **RISK, unmitigated** | headline above |

#### Orphan reference — CONFIRMED, and the POC half survives your objection

`fragmentHasContent` does count `evidence_id`:

```js
|| Boolean(fragment.text?.trim() || fragment.caption?.trim() || fragment.evidence_id);
```
[app.js#L976](app/web/static/app.js#L973)

So a description/remediation section that reads as empty holds no image, and `dropUnreferencedEvidence(previousEvidence)` ([app.js#L978-L982](app/web/static/app.js#L978)) can delete nothing that was not already unreferenced — it only removes IDs that were in this finding *before* the replace and are no longer used by any finding.

For the proof of concept your objection is right about the premise and wrong about the consequence. `written` does exclude images ([app.js#L3148](app/web/static/app.js#L3148)), so a POC with an uploaded screenshot and no typed steps **does** qualify as empty. But `applyPocVariant` in `replace` mode lifts every image out first and re-appends it:

```js
const images = proof.fragments.filter(fragment => fragment.type === "image");
const kept = mode === "merge" ? proof.fragments.filter(f => f.type !== "image") : [];
proof.fragments = [...mergeStepLists([...kept, ...remintFragments(steps)]), ...images];
```
[app.js#L1193-L1199](app/web/static/app.js#L1193), twinned at [report_service.py#L496-L514](app/report_service.py#L496)

And it never calls `dropUnreferencedEvidence`. The screenshot survives with its `evidence_id` and caption intact. **No orphan.** The only fallout is cosmetic: the primary button reads "Fill from library" rather than "Use saved steps" on a section that visibly holds a screenshot.

#### Rule drift — WRONG as written

The claim is that `fragmentHasContent` and `contentHasWork` "give identical answers on every reachable state for these sections". They do not. `contentHasWork` skips any paragraph carrying a `generated` marker or the default sentence:

```js
.filter(fragment => !(fragment.generated || isDefaultStatusConclusion(fragment)))
```
[app.js#L1020-L1021](app/web/static/app.js#L1020), twinned at [report_service.py#L169-L189](app/report_service.py#L169)

Both states you named are reachable:

- **`recommended_remediation` on a resolved finding.** `provision` assigns exactly one paragraph with `generated:"resolved_remediation"` and the boilerplate text ([app.js#L1041](app/web/static/app.js#L1041), [report_service.py#L222-L228](app/report_service.py#L222)). `fragmentHasContent` → **true**. `contentHasWork` → **false**.
- **`in_conclusion` holding only the default sentence.** `fragmentHasContent` → **true**. `contentHasWork` → **false**.

Does it matter where the planner uses it? No — the resolved case is excluded by the first filter in `pendingLibraryOffers` ([app.js#L1233](app/web/static/app.js#L1230)) and `in_conclusion` is never routed through that function. So the *conclusion* holds. But the stated reason is false, and a reader who trusts it will assume the two are interchangeable elsewhere, which is the exact failure the row was written to prevent.

**This also makes Decision 1's own step-2 invariant note wrong.** The planner writes: *"the resolved-remediation exclusion stays the first filter, or a resolved finding's locked remediation would read as empty and offer itself."* Under `fragmentHasContent` — the predicate they chose — a resolved remediation reads as **full**, because the boilerplate has text. That invariant is only true under `contentHasWork`. The plan is internally inconsistent between its risk table and its step list.

#### Derived-state fight — confirmed for two sections, incomplete for the third

Both `provision` implementations seed only into a section with zero fragments:

- JS: `if (content.fragments.length || !required[content.type]) return;` [app.js#L1036](app/web/static/app.js#L1036)
- Python: `if content.fragments or content.type not in required_fragments: continue` [report_service.py#L206-L208](app/report_service.py#L206)

So an emptied section keeps its one text-less paragraph and the offer is stable across saves. **CONFIRMED on both sides.**

`deletionBlockedReason` does make zero fragments unreachable for description and recommended remediation:

```js
if (requiresFragment.includes(content.type)) {
  return content.fragments.length === 1 ? `${contentNames[content.type]} always keeps one fragment.` : null;
}
```
[app.js#L1155-L1158](app/web/static/app.js#L1155), with `requiresFragment = ["description","recommended_remediation","in_conclusion"]` ([app.js#L113](app/web/static/app.js#L113)). **CONFIRMED.**

For `proof_of_concept` the guarantee is a different rule, and the planner's row does not say so. `requiresFragment` does not contain it; the floor is the numbered-list branch ([app.js#L1161](app/web/static/app.js#L1155)) backed by `ensureProofSteps` ([app.js#L1171](app/web/static/app.js#L1171)) / `ensure_proof_steps` ([report_service.py#L155-L159](app/report_service.py#L155)). That is a **twinned** rule, unlike `deletionBlockedReason`, which is client-only. Step 4 therefore rests on a Python/JavaScript pair, and the row's blanket "everything touched is client-only" is one word too strong.

#### Backup exhaustion — both sub-claims CONFIRMED

`scheduleSave` calls `queueReportChange()` on the focused early-return branch **and** on the tail:

```js
if (textEntry && activeTextTransaction?.input === textEntry) { ...; queueReportChange(); return; }
...
queueReportChange();
```
[app.js#L708-L735](app/web/static/app.js#L708)

And there is a precedent for a read-only `reportchange` listener: `updateReadinessPanel` ([registered at app.js#L2931](app/web/static/app.js#L2931)) reads `report`, writes only DOM, `revealedSlots` and `panel.innerHTML`, and never assigns into `report` or calls `scheduleSave` during the listener pass. Its only `render()` call sits inside a click handler, not the listener body. **The pattern the planner wants already exists and already obeys the invariant.**

---

### 2. What the planner missed

#### a. CSS — three direct-child selectors break under the `.offer-slot` wrapper

`.content-block` is a grid whose children are styled positionally, in two stylesheets:

```css
.content-block > *:not(.content-toggle) { margin-inline: 11px; }
.content-block > .content-toggle + *    { margin-top: 10px; }
.content-block > :last-child            { margin-bottom: 11px; }
```
[taste.css#L3102-L3112](app/web/static/taste.css#L3102), duplicated at [taste.css#L1366-L1376](app/web/static/taste.css#L1366), with `display: grid` at [taste.css#L1343](app/web/static/taste.css#L1343)

An always-present `.offer-slot` becomes `.content-toggle + *`. Every block that currently has **no** banner loses the 10 px gap under its heading (the first fragment is no longer the adjacent sibling) and gains a 10 px margin on an empty zero-height grid item instead. That is a visible regression on every section, every finding, on load. Either the slot must be omitted when empty, or these three rules need `:not(.offer-slot:empty)` handling. The planner's "nothing else depends on `buildContentBlock`'s structure" is wrong.

`.poc-offer` / `.content-offer` themselves are class-keyed ([overrides.css#L299-L306](app/web/static/overrides.css#L299)) and survive the move.

#### b. The readiness panel's "go to" arrow depends on `data-offer-for`

```js
: contentType ? pane.querySelector(`[data-offer-for="${contentType}"]`) || pane.querySelector(`[data-content-type="${contentType}"]`)
```
[app.js#L2920](app/web/static/app.js#L2920)

Only two banners carry it — the POC offer ([app.js#L3154](app/web/static/app.js#L3154)) and the description/remediation offer ([app.js#L3211](app/web/static/app.js#L3211)). `contentOffersFor` must preserve it, and the refresh must not leave the attribute on a detached node while the panel is mid-jump. Banners A and B carry no `data-offer-for` and have no readiness row, so they are unaffected.

`showReviewTarget` keys on `data-fragment-id` ([app.js#L2732-L2738](app/web/static/app.js#L2732)) and is not affected.

#### c. Collapsed blocks have no slot

`buildContentBlock` returns early before any banner is built: `if (!isExpanded) return block;` ([app.js#L3086](app/web/static/app.js#L3086)). `refreshContentOffers` must tolerate a missing slot rather than assume one per `[data-content-type]`.

#### d. The active-element skip does not cover paired blocks

Description and remediation are rendered into one `.content-row`, as are the two proofs:

```js
pairUp("description", "recommended_remediation");
pairUp("previous_proof_of_concept", "proof_of_concept");
```
[app.js#L3270-L3271](app/web/static/app.js#L3270)

Grid rows share a height. Skipping only the block that contains `document.activeElement` still lets its **sibling** grow or shrink by a banner's height, which moves the caret's block on screen. The mitigation needs to be per-`.content-row`, not per-`.content-block`.

#### e. No Python interaction from promoting `written` — CONFIRMED

`applicable_poc_variants` reads scope and the entry's channels only; it never consults `poc_variants` or `poc_variant_declined`:

```python
channels = set(affected_channels(vulnerability, report))
return [channel for channel in CHANNELS if channel in channels and channel in (available or {})]
```
[report_service.py#L320-L324](app/report_service.py#L320)

And the auto-install at `insert_library` cannot fire on the insert path regardless, because the finding is constructed with `Scope(mode="custom")` and no targets ([main.py#L727](app/main.py#L719)), so `affected_channels` returns `[]` and `len(variants) == 1` is never true. `written` has no Python counterpart to drift from. **The planner is right here.**

#### f. Tests

**None break outright.** The ones that come closest, and why they survive:

- [test_browser.py#L1476-L1491](tests/test_browser.py#L1476) `test_a_finding_is_offered_only_the_app_types_it_has_not_installed` and [#L1533-L1562](tests/test_browser.py#L1533) `test_unchecking_a_location_in_the_page_withdraws_that_app_types_offer` both assert `.poc-offer` counts against `poc_variants: ["web"]`. They would break under the aggressive answer to open question 3 (override `poc_variants` too, not just declines) **except** that their fixture writes a real step: `_complete_finding` sets `numbered_list.items[0].runs = [Run(text="Complete proof step")]` ([test_browser.py#L1436-L1438](tests/test_browser.py#L1431)), so `written` is true and the override never engages. That is luck, not coverage — the aggressive variant is untested in either direction.
- [test_browser.py#L1216-L1253](tests/test_browser.py#L1216), [#L1256-L1286](tests/test_browser.py#L1256), [#L1289-L1315](tests/test_browser.py#L1289), [#L1318-L1360](tests/test_browser.py#L1318) all locate banners with `.content-block` filters and `get_by_role("button", ...)`, so the slot refactor is transparent to them — provided the banner stays a descendant of `.content-block`.
- [test_browser.py#L1736-L1737](tests/test_browser.py#L1736) asserts `previous.locator(".poc-offer").count() == 0`. A refresh that fills slots by `[data-content-type]` without re-checking the section type would regress this.
- [test_app.py#L1422-L1442](tests/test_app.py#L1422) `test_a_library_insert_does_not_offer_back_the_content_it_just_copied` keeps its meaning: an inserted finding's sections hold the entry's content, so the new clause never fires.

#### g. The Content page's title editor still does not swap entries — CONFIRMED

```js
// Renaming here never replaces content; library swaps belong to the Findings page.
item.onclick = () => { const entry = ...; if (entry) { titleInput.value = entry.title; finishTitle(); } };
```
[app.js#L3051-L3055](app/web/static/app.js#L3052), and `finishTitle` writes only `finding.title`, `syncConclusion`, `offerConclusionRewrite` ([app.js#L3035-L3042](app/web/static/app.js#L3035)). No `library_ref` write. **Still true.**

---

### 3. `draft.json` on disk

**No migration needed. CONFIRMED.** No new persisted field; `content_offer_resolved` already defaults to `{}` via `default_factory` ([models.py#L197](app/models.py#L197)); `validate_references` has nothing to say about it; `load_path` needs no repair entry.

#### The sweep the planner deferred

Every finding on disk with a `library_ref` and a non-empty `content_offer_resolved` — 8 of them, matching the planner's count:

| Report | Entry | Latch | Description holds content? | Remediation holds content? | Gains a banner? |
|---|---|---|---|---|---|
| [Northstar_Banking/…0931592e4fdd](data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json#L96) (only finding, `v_852106ea`) | VDB-047 | both | yes | **no** — one paragraph, `"runs": []` ([draft.json#L122-L132](data/apps/Northstar_Banking/2026-09_Annual_Pentest_0931592e4fdd/draft.json#L122)) | **YES — Recommended Remediation** |
| [Vuln_Library_QA](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json#L102) | VDB-012 | both | yes | yes (paragraph + empty table) | no |
| [same](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json#L440) | VDB-015 | remediation | yes | yes | no |
| [same](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json#L608) | VDB-026 | both | yes | yes | no |
| [same](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json#L732) | VDB-028 | both | yes | yes | no |
| [same](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json#L1609) | VDB-036 | both | yes | yes | no |
| [same](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json#L1844) | VDB-039 | both | yes | yes | no |
| [same](data/apps/Vuln_Library_QA_-_Merged_References/2026-09_Annual_Pentest_c6ff01abda9e/draft.json#L2079) | VDB-040 | description | yes | (unlatched) | no |

**Exact answer: one finding, one banner.** Northstar `v_852106ea`'s Recommended Remediation, plus one "Suggested" readiness row. The planner's guess was right; the blast radius is now measured rather than bounded.

#### "9 findings already see offers today" — WRONG, but the conclusion survives

The claim is unverified and false for at least one case. Round 1 established that QA VDB-014 is byte-identical to its library entry in **both** sections, so `sameFragments` ([app.js#L1226-L1227](app/web/static/app.js#L1226)) suppresses both offers today despite an empty latch.

The right argument is simpler and stronger: **the new clause is OR'd onto a filter those 9 findings already pass**, so it cannot change their outcome in either direction. Whether they see an offer today is irrelevant. That includes Prompt_Reference's `v_empty` (VDB-050), whose description and remediation are both empty paragraphs with an empty latch ([draft.json#L177-L196](data/apps/Prompt_Reference/2026-09_Annual_Pentest_5395baea9d23/draft.json#L177)) — it sees offers today and will see the same offers after.

---

### Attacks on the design decisions

#### Decision 1 — resolved → open "falls out for free": CONFIRMED

A reopened remediation is `{type:"paragraph", runs:[]}` ([report_service.py#L230-L232](app/report_service.py#L229), [app.js#L1044-L1045](app/web/static/app.js#L1041)). Against `fragmentHasContent`: `fragmentHasText` false; `(undefined || []).some` false ×3; `Boolean(undefined || undefined || undefined)` false. **Reads as empty.** The mechanism works — it is only the Dismiss arm that then traps the tester.

#### Decision 6 — "both In Conclusion prompts already work, only cadence is missing": ONE of your three bullets is genuinely satisfied

**Bullet 3 (quote the last POC step) — SATISFIED, and broader than you asked.** You asked for it only when the conclusion is at its default; Banner A fires whenever `pocLastStep` is non-empty and unanswered, regardless of what the conclusion holds ([app.js#L3095-L3098](app/web/static/app.js#L3095)). Reworded text is a new key, so a modified last line re-offers. Cadence is indeed the only gap.

**Bullet 1 (restore the default when a fragment is deleted or cleared) — PARTIALLY satisfied.** Banner B keys on text-less **paragraphs** ([app.js#L3124-L3125](app/web/static/app.js#L3124)), so *cleared* is covered. *Deleted* splits three ways: the last fragment cannot be deleted at all ([app.js#L1155-L1158](app/web/static/app.js#L1155)); deleting one of two paragraphs and leaving prose correctly shows nothing; but **deleting the only paragraph while a note remains shows no banner** — `emptied` is empty because a note is not a paragraph. The planner says `syncConclusion` silently repairs that, and it does ([app.js#L998-L1000](app/web/static/app.js#L991): no paragraphs → `unshift(newFragment("paragraph"))` → fill with the sentence). But the client's `syncConclusion` is not called on save; only the server's `provision` is ([main.py#L263](app/main.py#L261)). So the tester sees a note-only conclusion until the page reloads, and the repair *writes* the sentence rather than *offering* it — the opposite of what you asked for.

**Bullet 2 (prompt to update the default when name or status changes) — NOT satisfied, and the planner is substituting judgment for source.** `offerConclusionRewrite` returns `false` without prompting in exactly the case you described:

```js
if (!first || first.generated || !fragmentHasText(first) || hasDefaultStatusConclusion(first)) return false;
```
[app.js#L1057](app/web/static/app.js#L1053)

A conclusion that *is* the default sentence is rewritten silently. You asked to be prompted for that; the app deliberately does not. The planner's "correctly, because there is nothing of yours to lose" is a defensible argument, but it is a **design disagreement with your request presented as a verified "already works"**. It should be an open question, not a settled row.

One more limit on all three: every conclusion prompt is gated on `contentTypesForStatus(finding.status).includes("in_conclusion")` ([app.js#L3095](app/web/static/app.js#L3095)), and `open_new` has no In Conclusion section ([app.js#L1015-L1017](app/web/static/app.js#L1015), [report_service.py#L162-L167](app/report_service.py#L162)). None of this fires on a new finding.

#### Decision 7 — `reportchange` while typing: the premise is CONFIRMED, the consequence is worse than described

Typing does reach it. A rich-text fragment's `oninput` calls `onChange`, which is `runs => { fragment.runs = runs; changed(); }` with `changed = () => scheduleSave()` ([app.js#L963](app/web/static/app.js#L960), [app.js#L2521](app/web/static/app.js#L2521)); the list textarea's `oninput` does the same ([app.js#L2555-L2560](app/web/static/app.js#L2555)). `scheduleSave` reaches `queueReportChange()` on the focused branch, which dispatches 100 ms later ([app.js#L385-L390](app/web/static/app.js#L385)). **Yes, `reportchange` fires while a field is focused.**

But the planner's stated benefit — *"the In Conclusion banner appearing the instant you leave the POC list"* — understates what the skip actually permits. The In Conclusion block does **not** contain the active element while you type in the POC list, so it is refreshed on every tick. Banner A's message embeds `pocLastStep` verbatim:

```js
buildOffer("content-offer", `Start the conclusion with your last step: "${lastStep}"`)
```
[app.js#L3116](app/web/static/app.js#L3116)

and the list textarea rewrites `fragment.items` on every keystroke ([app.js#L2556-L2558](app/web/static/app.js#L2555)). So the banner's quoted text churns character by character, 10 times a second, while you type the last step. Worse: because `conclusion_offer_resolved` stores the **text**, a step you already dismissed re-qualifies the moment you type one more character into it, so a dismissed banner flickers back mid-word. Banner A needs to be debounced or excluded from the fast path.

---

### Invariants in play

- **`provision` may never seed into a non-empty section** ([app.js#L1036](app/web/static/app.js#L1036), [report_service.py#L206](app/report_service.py#L206)). Relax it and an emptied section refills, the offer vanishes on save, and the whole Option A rule is dead.
- **`requiresFragment` keeps description, remediation and conclusion at ≥1 fragment** ([app.js#L113](app/web/static/app.js#L113), [app.js#L1156](app/web/static/app.js#L1155)). Relax it and `content.fragments === []` becomes reachable, which `docx_report.generation_issues` reports as an error ([docx_report.py#L114-L115](app/docx_report.py#L114)).
- **`ensure_proof_steps` keeps one numbered list in both proof sections** ([report_service.py#L155-L159](app/report_service.py#L155), [app.js#L1171-L1173](app/web/static/app.js#L1171)). This, not `requiresFragment`, is what makes step 4's "empty" well-defined.
- **`applyPocVariant` preserves images in both modes** ([app.js#L1195-L1199](app/web/static/app.js#L1193), [report_service.py#L505-L508](app/report_service.py#L496)). This is the only thing standing between a widened POC offer and a deleted screenshot.
- **A `reportchange` listener must not write `report`** — a write there calls `scheduleSave`, which dispatches `reportchange` again ([app.js#L735](app/web/static/app.js#L708)), and each pass consumes the single `draft.bak.json`.

### Both-sides warning

Step 4 is **not** purely client-side, contrary to the blast-radius table's "duplicated rules touched: none". Its floor is `ensure_proof_steps` / `ensureProofSteps` and `apply_poc_variant` / `applyPocVariant`, both twinned. Nothing in step 4 requires editing either, but a reviewer told "nothing twinned is touched" will not check them when the rule shifts. The accurate statement is: *no twinned function is modified; two are newly depended upon.*

Steps 1, 2 and 3 are genuinely client-only.

### Map drift

**None.** I re-checked every `docs/DATA_MAP.md` statement this round touched — section 6's `content_offer_resolved` and `conclusion_offer_resolved` paragraphs, `insert_library`'s pre-answering and its ordering before `apply_poc_variant` ([main.py#L730](app/main.py#L719)), section 7's `provision` / `ensure_proof_steps` / `sync_evidence_image_slots` guarantees, and the `apply_poc_variant` replace/merge description. All match source. No edits made.

---

**One decision is waiting.** The Dismiss-is-a-no-op defect has to be resolved before step 2 can ship, and it is the planner's to solve, not mine — but it changes which of your two options is buildable, so you should see it before the next round.

## Round 2 - Planner: revised plan

### Understanding

Six prompts should fire in situations where today they are suppressed or never redrawn. The unifying rule is still **"the section has lost its content and the library still has some"**, not "the section differs from the library". Two things block that today: `content_offer_resolved` is a permanent latch that never releases, and banners are only built by `render()`, which typing never calls. The oracle confirmed the rule works and measured its blast radius at exactly one existing finding — but it also found that releasing the latch on emptiness makes the Dismiss button write a value that changes nothing, so the banner redraws forever. Fixing that without inventing a persisted fingerprint is the centre of this revision, and the answer is that dismissal is remembered **for the session only**, the same way the readiness panel already remembers which evidence slots it has sent you to.

---

### A. Blast radius

| File | Change | Why |
|---|---|---|
| [app/web/static/app.js](app/web/static/app.js) — `pendingLibraryOffers` (L1230–L1248) | Two added clauses: release the latch / the decline list when the section holds nothing; drop anything in the new `dismissedOffers` set. The `written` predicate moves up from the POC banner so both read one source. | The single owner of "what is outstanding"; both banners and the readiness panel read it |
| [app/web/static/app.js](app/web/static/app.js) — beside `pendingLibraryOffers` | New `const dismissedOffers = new Set()`, deliberately never persisted | Must be visible to `pendingLibraryOffers`, which is declared outside `continuousEditor` |
| [app/web/static/app.js](app/web/static/app.js) — `buildContentBlock` (L3082–L3216) | The four banner bodies extracted into `contentOffersFor(finding, content)` returning an array of nodes. **No wrapper element.** `buildContentBlock` appends the returned nodes exactly where it appends banners today. | Gives the banners a second, caret-safe renderer without changing the DOM shape |
| [app/web/static/app.js](app/web/static/app.js) — the `keep` arm (L3200) and the POC `refuse` arm (L3163) | Each adds its key to `dismissedOffers` alongside the persisted write it already does | Makes Dismiss mean something on an empty section |
| [app/web/static/app.js](app/web/static/app.js) — beside `document.addEventListener("reportchange", updateReadinessPanel)` (L2931) | New read-only listener `refreshContentOffers()` | The missing cadence, on an event that already fires |
| [app/web/static/app.js](app/web/static/app.js) — the existing `focusout` handler (L700–L706) | One added `queueReportChange()` inside the existing `if (!activeTextEntry())` branch | Guarantees a tick lands after you leave a field; that branch already carries the exact guard the refresh needs |
| [app/web/static/taste.css](app/web/static/taste.css), [app/web/static/overrides.css](app/web/static/overrides.css) | **No change** — see decision 3 | |
| [app/report_service.py](app/report_service.py), [app/models.py](app/models.py) | **No change**, deliberately | No new persisted field, no server twin |
| [tests/test_browser.py](tests/test_browser.py) | 10 new tests | Every rule here is client-side |
| [tests/test_app.py](tests/test_app.py) | 1 new test | Pins "the server must never touch the latch" |
| [docs/DATA_MAP.md](docs/DATA_MAP.md) | §6 gains the release condition; §12 gains the session-scoped dismissal and the refresh listener | Required by the data-layer maintenance contract |

**Twinned rules: none modified, two newly depended upon.** Correcting the Round 1 overstatement: step 4's definition of "an empty proof of concept" rests on `ensure_proof_steps` / `ensureProofSteps`, and its safety on `apply_poc_variant` / `applyPocVariant`. Both are Python/JavaScript pairs. Neither is edited, but a reviewer told "nothing twinned is touched" would not check them. Steps 1, 2 and 3 are genuinely client-only.

---

### B. Open questions

**Four decisions are waiting.** Only the first needs an answer before anything is built; the other three gate work that is not in the ordered plan below. They are all written out so this document stands alone, but answer them one at a time.

#### Question 1 — when you edit library wording, should the app keep offering to put the original back?

*Background.* When you pull a finding in from the library, it arrives with the library's Description and Recommended Remediation already filled in, and the app records that you have "answered" those two sections so it stops offering them. That record never releases. It is why reopening a resolved finding leaves you with a blank Recommended Remediation and no way to get the library's version back. Everyone agrees that case should be fixed. The question is how far to open the door.

*Option A — the banner comes back only when a section is empty.* You delete or clear everything in a section, and the offer returns. You reword it, add a sentence, restructure it — nothing happens, because your work is still there.

*Option B — the banner comes back whenever the section differs from the library at all.* This is closer to your literal wording. It also means the offer returns the moment you change one word and never goes away again, because you are never going back to matching the library exactly. On the reports currently on disk it would also fire on a finding whose only difference from the library is an empty code block and an empty table somebody dropped in and never filled — offering to overwrite text that is already identical.

*Tradeoff.* Option A cannot help if you half-mangle a section and want the original back; you would have to clear it first. Option B cannot be dismissed for good by anyone who customises library prose, which is most of the time.

*My recommendation: Option A.* It covers every case you described — the reopen, the accidental delete, the name change — without turning the banner into something you learn to ignore.

#### Question 2 — should the title box **inside** the Content page swap library content, the way the Findings list does?

Today there are two places to rename a finding. On the Findings list, picking a library name swaps in that entry and offers you its Description and Remediation. On the Content page, the title box lets you pick the same names but deliberately only changes the words in the title — it never touches content, and there is a comment in the code saying so on purpose. So the same action in two places gives you different results, and which one you get depends on which screen you happened to be on.

*If you say yes,* renaming on the Content page behaves like the Findings list: the offer banners appear underneath. *If you say no,* it stays as it is and the inconsistency stays too. *Absent an answer I would leave it alone*, because changing it means a rename can suddenly present an offer to overwrite the section you are looking at.

#### Question 3 — if you delete every step you installed from the library, should the app offer them again?

The proof of concept remembers two things: which sets of saved steps you installed, and which you turned down. The plan already re-offers the ones you **turned down** if the steps end up empty. The open part is the ones you **installed**.

*If you say yes,* deleting all the steps you pulled in brings the offer back, so an accidental clear-out is recoverable. *If you say no,* installing is final: once you have taken the library's steps, emptying them means you meant to write your own. *Absent an answer I would say no*, because two existing tests rely on an installed set staying installed, and they only pass today by luck — their fixture happens to type a real step.

#### Question 4 — when you rename a finding or change its status, should the app ask before rewriting the standard closing sentence?

You asked to be prompted to update the In Conclusion sentence when the name or status changes. I told you in Round 1 that this already happens. It does not, and I should not have said so.

What actually happens: if you have written your own conclusion, you get a dialog asking whether to replace it. If the conclusion is still the app's own standard sentence, it is **rewritten silently** with the new name or status, with no prompt at all.

*If you say "leave it",* silence stays — the argument being that there is nothing of yours to lose, so an extra click every time you correct a typo in a finding's name is pure friction. *If you say "prompt me",* you get a dialog on every rename and every status change of every finding whose conclusion you have not personally written yet, which on a fresh report is all of them. *Absent an answer I would leave it silent*, but that is my judgement overriding your stated request, which is why it is a question and not a decision.

---

### C. Design decisions

#### 1. Dismiss is remembered for the session, not written to the file

**The defect, restated.** Under Option A the offer shows while a section is empty. Pressing Dismiss writes the latch (which for a reopened finding already holds that exact value) and changes no fragments. The section is still empty, so the offer is still pending and the banner redraws identically. Forever. This lands on Northstar `v_852106ea`, the reopened remediation this whole design was built to fix.

**The fix.** A plain in-memory `Set` of dismissed offers, keyed `finding.uid | content type | library id` (and `| app type` for proof-of-concept steps). The existing Dismiss and Keep-mine arms add their key; `pendingLibraryOffers` drops anything in the set. Nothing is saved to disk. Reloading the page brings the banner back if — and only if — the section is still empty.

**Why a session-scoped memory is honest here and not a cop-out.** An empty Description or Recommended Remediation is *already* a blocking error on the readiness panel: `generation_issues` reports `"<section> text is required"` for any paragraph with no text ([docx_report.py#L127-L128](app/docx_report.py#L127-L128)), and the Generate button is disabled while it stands. The same is true of an empty steps list. So "empty forever" is not a state you can finish a report in. The banner is a quiet suggestion sitting beside an error that is already shouting, and the moment you type one word into the section both go away — the banner permanently, because the latch is set and the section is no longer empty. Dismiss means "not now, I am about to write my own", which is exactly what it is for, and that intent does not outlive the session.

**There is already a precedent for exactly this, in this file.** `revealedSlots` ([app.js#L2712](app/web/static/app.js#L2712)) is an in-memory `Set` the readiness panel uses to suppress rows, carrying the comment *"Deliberately never saved"*. Same shape, same scope, same reasoning.

**Rejected alternatives.**

- *A sentinel in the existing latch* (writing `"VDB-047:empty"` instead of `"VDB-047"`). It is the fingerprint under another name, and it does not even work: `content_offer_resolved` is typed `dict[ContentType, StableId]` and `StableId` is `^[A-Za-z0-9][A-Za-z0-9_.-]*$` ([models.py#L24](app/models.py#L24)), which rejects a colon. Any separator I picked would be smuggling a second meaning through a field the server writes plainly at `insert_library`.
- *A new persisted field.* Schema change, a default and a meaning for every draft already on disk, a writer at several call sites that can each record it in the wrong order, and a standing argument with `provision`, which rewrites these sections on every save. This is what I refused in Round 1 and the reasons have not moved.
- *Making Keep write content.* Seeding a placeholder paragraph so the section stops reading as empty means writing text you did not author into a section that is already flagged as incomplete. Worse than the bug.
- *Removing the Dismiss button when the section is empty.* Leaves the banner undismissable, just without the lie of a button. This is the fallback if you reject the session set, not a design.

#### 2. The refresh runs only when no text field has focus

The oracle found three separate problems with refreshing on every `reportchange` tick: the caret's own block moves; its **paired** block in the same grid row moves it too, because description sits beside remediation in one `.content-row` and grid rows share a height; and the In Conclusion banner, which quotes your last proof-of-concept step verbatim, rewrites that quote character by character about ten times a second while you type — including flickering a step you already dismissed back into view mid-word.

All three collapse into one condition: **`refreshContentOffers` returns immediately if `activeTextEntry()` is non-null.** No per-block skip, no per-row bookkeeping, no special case for the conclusion banner.

The cost is latency — a banner appears when you leave the field rather than while you are typing in it. That is the better behaviour anyway: a banner that materialises under your cursor while you are deleting text pushes the line you are editing down the screen.

The cadence is guaranteed by one added line. The `focusout` handler at [app.js#L700-L706](app/web/static/app.js#L700) already runs a microtask and already checks `if (!activeTextEntry())`; adding `queueReportChange()` there dispatches a tick once focus has settled. `queueReportChange` writes nothing, so this is safe inside a focus handler.

#### 3. There is no `.offer-slot`. The DOM shape does not change at all

Round 1 proposed wrapping the banners in a permanent slot element. That breaks three positional CSS rules — `.content-block` is a grid whose children are styled by position, in rules duplicated at [taste.css#L1366-L1376](app/web/static/taste.css#L1366) and [taste.css#L3102-L3112](app/web/static/taste.css#L3102) — so every section without a banner would lose the gap under its heading and gain a margin on an empty grid item. Visible on every finding, on load.

The wrapper was only ever an anchor, and it is not needed. `refreshContentOffers` removes the block's existing `:scope > .content-offer, :scope > .poc-offer` children and inserts the fresh ones after `.content-guidance` if present, otherwise after `.content-toggle` — which is exactly where `buildContentBlock` puts them today. **With no banner the block is byte-identical to today; with banners it is byte-identical to today.** Zero CSS changes, zero stylesheet duplication to keep in step.

#### 4. The refresh compares before it replaces

`contentOffersFor` builds the fresh nodes; if their serialised markup matches what is already in the block, the refresh returns without touching the DOM. On a typical tick nothing has changed, so nothing is replaced. This removes the "a button was swapped out from under a click" risk almost entirely — the DOM is only disturbed when the offer genuinely changed — and it means the readiness panel's "go to" arrow, which resolves `[data-offer-for="<type>"]`, is not chasing a node that gets replaced underneath it on every tick.

#### 5. `fragmentHasContent`, and the real reason

Correcting the Round 1 risk row, which was wrong as written. `fragmentHasContent` and `contentHasWork` do **not** give identical answers. `contentHasWork` discounts any paragraph carrying a `generated` marker or the standard conclusion sentence, so they disagree in two reachable states: a resolved finding's remediation boilerplate (`fragmentHasContent` true, `contentHasWork` false) and an In Conclusion holding only the default sentence (same split).

`fragmentHasContent` is still the right choice, for two reasons that are actually true:

- **Neither disagreement is reachable at the point of use.** A resolved remediation never reaches the emptiness test — it is removed by the first filter in `pendingLibraryOffers` ([app.js#L1234](app/web/static/app.js#L1234)) — and `in_conclusion` is never routed through that function at all.
- **Ownership.** `contentHasWork` is twinned and owned by the status-carry rule in `provision`. Borrowing it would mean a future change to what "work" means for carrying sections silently moved which offers appear.

#### 6. Resolved → open still needs no server twin and no latch clearing

A reopen leaves one paragraph with no runs ([report_service.py#L229-L232](app/report_service.py#L229), twinned at [app.js#L1041-L1046](app/web/static/app.js#L1041)). That reads as empty, so the offer appears with no extra machinery. Actively clearing the latch inside `provision` would mean derived-state code on both sides overwriting a record of your answer on every save — the exact fight the design is built to avoid.

---

### D. Data risks

| Failure mode | Verdict | Reasoning |
|---|---|---|
| **Dismiss is a no-op / undismissable banner** | **RISK — mitigated by decision 1** | Keep and Dismiss change no fragments, so an emptiness-based release redraws the banner identically. The session-scoped `dismissedOffers` set is what makes the button do something. Pinned by a test that dismisses on an empty section and asserts the banner is gone. |
| Stale write | clear | No new route, no new mutation path. Every banner arm already ends `render(); scheduleSave();` → `PUT` with `saved_at` in the body. |
| Lost update | clear | No Python change; nothing new reads-then-writes outside `Workspace._locked`. |
| Orphan reference | clear | A description or remediation that reads as empty holds no image, because `fragmentHasContent` counts `evidence_id`, so `dropUnreferencedEvidence` can remove nothing that was not already unreferenced. `applyPocVariant` lifts images out and re-appends them in **both** modes and never calls `dropUnreferencedEvidence`, so a screenshot with no typed steps survives a replace. |
| Silent stranding | clear | No scope, environment or `target_ids` path is touched. |
| Schema break | clear | No new persisted field. `dismissedOffers` never leaves memory. Every `draft.json` loads unchanged; `validate_references` is unaffected; no `load_path` repair. |
| Existing drafts start showing offers | **RISK — measured, one finding** | Exactly one: Northstar `v_852106ea`'s Recommended Remediation gains one banner and one "Suggested" readiness row, which is precisely the case you asked for. The other seven latched findings all hold content in both sections. The nine unlatched findings cannot change either way, because the new clause is OR'd onto a filter they already pass. |
| Request/response asymmetry | clear | Nothing new is sent. |
| Rule drift | clear, **for corrected reasons** | See decision 5. No twinned function is modified; `ensure_proof_steps`/`ensureProofSteps` and `apply_poc_variant`/`applyPocVariant` are newly depended upon and must be named as such in review. |
| Navigation trap | clear | No offer gates any page. |
| Derived-state fight | clear, **load-bearing on two guards** | `provision` seeds starter fragments only into a section with zero fragments ([app.js#L1036](app/web/static/app.js#L1036), [report_service.py#L206-L208](app/report_service.py#L206)), so an emptied section keeps its one text-less paragraph and the offer is stable across saves. For description and remediation, `deletionBlockedReason` + `requiresFragment` make zero fragments unreachable. For the proof of concept the floor is `ensure_proof_steps`/`ensureProofSteps` instead — a twinned pair. If any of these is relaxed, the rule breaks. |
| Backup exhaustion | **RISK — mitigated** | `refreshContentOffers` runs inside a `reportchange` listener. A write there would call `scheduleSave`, dispatching `reportchange` again: unbounded PUTs, each consuming the single `draft.bak.json`. Mitigated by making the function read-only and pinning it with a test that stringifies `report` before and after a tick — not with a comment. `updateReadinessPanel` is the existing precedent for a read-only listener. |
| Banner text churns while typing | **RISK — mitigated by decision 2** | The conclusion banner embeds the last proof step verbatim and the list textarea rewrites it on every keystroke, so it would churn ~10×/second and a dismissed step would flicker back mid-word. The refresh does nothing while a text field has focus. |
| Caret moves under the tester | clear, **by the same guard** | Covers both the block being typed in and its paired sibling in the same `.content-row`, since neither is refreshed while anything is focused. |
| Banner swapped mid-click | clear | The refresh compares serialised markup and returns without touching the DOM when unchanged (decision 4), and cannot run while a field is focused. |
| CSS regression on every section | clear, **by decision 3** | No wrapper element, so the three positional `.content-block > …` rules — duplicated in two places in `taste.css` — see the same child sequence they see today. |
| Readiness "go to" arrow breaks | clear | `contentOffersFor` reproduces `data-offer-for` on the two banners that carry it. The arrow's target is resolved inside a double `requestAnimationFrame`, and a refresh cannot interleave within it; the compare-before-replace guard keeps the node alive across ticks. |
| Collapsed section gets banners injected | clear | The refresh only visits `.content-block.is-expanded`. `buildContentBlock` returns before any banner for a collapsed section, so there is nothing to keep in step. |
| Previous proof of concept gains a POC banner | clear | `contentOffersFor` takes the `content` and reproduces the same `content.type === "proof_of_concept"` gate, so the existing assertion that the previous-proof block holds zero `.poc-offer` still holds. |
| Readiness verdict moves | clear | Offers enter as `suggestion: true` warning rows, excluded from the count and from the Generate gate. `test_browser_readiness_verdict_matches_server_generation_issues` compares against `generation_issues`, which cannot move. The panel gains rows; the verdict does not. |

---

### E. Plan

Round 1's step 0 is gone — the oracle performed the sweep: one finding, one banner, recorded above.

#### Step 1 — Give the banners a second renderer, with no rule change

*Files:* [app/web/static/app.js](app/web/static/app.js). Extract the four banner bodies from `buildContentBlock` into `contentOffersFor(finding, content)` returning an array of nodes. Add `refreshContentOffers` beside the `updateReadinessPanel` listener. Add `queueReportChange()` to the existing `focusout` branch.

*Tests, in [tests/test_browser.py](tests/test_browser.py):*
- `test_refreshing_offers_does_not_change_the_report` — stringify `report` before and after a tick, assert identical.
- `test_a_section_with_no_offer_keeps_the_children_it_has_today` — assert the expanded block's direct children are heading then fragment, with nothing between.
- `test_the_conclusion_offer_appears_after_a_step_is_typed_and_the_field_is_left`.
- `test_the_conclusion_offer_does_not_change_while_the_step_is_being_typed` — assert the banner's quoted text is unchanged across keystrokes.
- `test_a_collapsed_section_survives_an_offer_refresh`.
- `test_clearing_the_conclusion_offers_the_standard_sentence_back` — the Banner B test that has never existed.

*Invariants:* the set of banners produced by `render()` is identical before and after this step, which is what makes it reviewable. The refresh never assigns into `report` and never calls `scheduleSave`. The refresh does nothing while `activeTextEntry()` is non-null. Expanded blocks only. Direct-child sequence unchanged in both the banner and no-banner states.

#### Step 2 — Release the latch on an empty Description or Recommended Remediation, with a Dismiss that works

*Files:* [app/web/static/app.js](app/web/static/app.js) — one added clause in `pendingLibraryOffers`, the `dismissedOffers` declaration, one added line in the `keep` arm.

*Tests:*
- `test_emptying_a_library_section_offers_it_back`.
- `test_editing_a_library_section_does_not_offer_it_back` — the more important of the two.
- `test_dismissing_an_offer_on_an_empty_section_hides_it` — the headline defect.
- `test_filling_an_empty_section_from_the_library_hides_the_offer`.

*Invariants:* the `status === "resolved"` filter stays first. **Correcting Round 1's stated reason:** it is not there to stop a resolved remediation reading as empty — under `fragmentHasContent` the boilerplate reads as full, because it has text. It is there because a resolved finding's remediation block renders `"Locked for resolved findings."` with no fragment editors at all, so a banner there would offer an action the tester cannot complete. `dismissedOffers` is never serialised, never sent, and never read by Python.

#### Step 3 — Prove the reopen case and pin that no server twin appears

*Files:* none in `app/`. This step asserts step 2 already did the work.

*Tests:* [tests/test_browser.py](tests/test_browser.py)`::test_reopening_a_resolved_finding_offers_the_library_remediation`; [tests/test_app.py](tests/test_app.py)`::test_a_status_change_leaves_the_content_offer_memory_untouched` — save a reopen through the real route, assert `content_offer_resolved` round-trips byte-identical.

*Invariant:* `provision` never mutates `content_offer_resolved` on either side. The Python test is the guard rail that stops someone helpfully adding the twin later.

#### Step 4 — Release the proof-of-concept decline on an empty section

*Files:* [app/web/static/app.js](app/web/static/app.js) — the `variants` clause reuses `written`, hoisted out of the banner so both read one source; the `refuse` arm adds its session key.

*Tests:* `test_a_declined_poc_offer_returns_once_the_steps_are_emptied`; `test_dismissing_the_returned_poc_offer_hides_it`; re-run `test_a_finding_is_offered_only_the_app_types_it_has_not_installed`, `test_unchecking_a_location_in_the_page_withdraws_that_app_types_offer`, and the previous-proof-of-concept zero-offer assertion.

*Invariants:* images are excluded from "written" and preserved by `applyPocVariant` in both modes — this is the only thing standing between a widened offer and a deleted screenshot. The channel gating in `applicablePocVariants` is untouched, so a mobile-only finding is still offered nothing. **Both-sides note for the reviewer:** this step's definition of "empty" rests on `ensure_proof_steps`/`ensureProofSteps` and its safety on `apply_poc_variant`/`applyPocVariant`, both twinned pairs. Neither is edited. Whether an *installed* set also re-offers is question 3 and is not in this step.

#### Step 5 — Documentation

[docs/DATA_MAP.md](docs/DATA_MAP.md) §6 gains the latch's release condition and the note that it is no longer the sole suppressor; §12 gains the session-scoped dismissal and the `reportchange` refresh, with the "deliberately never saved" reasoning recorded the way `revealedSlots` records its own. [docs/plans/content-offer-triggers.md](docs/plans/content-offer-triggers.md) gains the agreed decisions. No tests.

---

### F. What I would not do

**I would not store a snapshot or hash of the content each offer was answered against.** It is the obvious way to express "has this drifted since you decided", and it is a trap: a persisted field on `Vulnerability`, a default and a meaning for every draft already on disk, a writer at four call sites that can each record it stale, and a standing disagreement with `provision`, which rewrites these sections on every save for reasons that have nothing to do with the tester. It turns a two-line client filter into a schema change with a migration, a twin obligation and a new class of drift bug.

**I would not fix the Dismiss defect by persisting a "dismissed while empty" flag**, which is the same trap wearing a smaller hat. Dismissal is an intent about the next few minutes, not a fact about the report, and it belongs in memory.

**I would not refresh the banners on every keystroke.** The temptation is that it feels more responsive. It makes the conclusion banner rewrite its quoted text ten times a second, flickers a dismissed step back mid-word, and moves the line you are editing down the screen — including from the block *next* to the one you are typing in, because they share a grid row. Refreshing only when focus has left costs a fraction of a second and removes four risks at once.

**I would not wrap the banners in a slot element.** It reads as tidier and it silently breaks the spacing of every section of every finding, through positional CSS rules that are duplicated in two places and would both need to stay in step forever.

## Answers

### 1. Should the library offer return only when a section is empty, or whenever it differs from the library?

**Answered: Option B** — whenever it differs. Plus an explicit instruction: *"also, Fix the prompts as they only come up after refresh"*, which is the cadence work already in the plan's step 1.

This overrides the planner's recommendation of Option A. Consequences accepted: an offer stands on any customised section, and the section that differs from its entry only by an empty code block and an empty table will show one.

### 2. Under Option B, what does Dismiss mean?

**Answered: Option 2** — dismissal is remembered until the text changes again.

This was forced by the choice above. Under "show whenever it differs", the existing Dismiss writes a record and changes no text, so the offer still qualifies and the banner redraws unchanged — the button would do nothing. Option 2 is the only shape that both honours Option B and leaves the banner dismissable across sessions.

**It requires the persisted fingerprint the planner rejected twice**, in Round 1's "What I would not do" and again in Round 2. The user chose it with the cost stated: new data in every draft, a meaning for drafts that predate it, and a new thing that can fall out of step with the section. The planner must now specify it rather than refuse it.

### 3. Should the app prompt before rewriting the standard closing sentence on a rename or status change?

**Answered: Option B** — prompt every time, as originally requested.

This overrides the planner's recommendation of Option A. The planner's Round 1 claim that this "already works" was false; the oracle established that a conclusion still holding the app's own sentence is rewritten silently, which is exactly the case the user asked to be prompted for. Consequence accepted: a dialog on every rename and status change of every finding whose conclusion the tester has not personally written.

### 4. If every installed library step is deleted, should the steps be offered again?

**Answered: Option A** — offer them again, matching the behaviour now chosen for Description and Recommended Remediation.

### 5. Option B puts up to 28 banners on a customised report. Keep it, or split the surfaces? *(raised by the planner's addendum)*

**Answered: Option 1** — build Option B exactly as specified. The planner offered a split where the banner appears only on an empty section while the readiness panel lists every section that differs; the user declined it.

Costs accepted, with numbers stated at the time of asking: up to 28 banners and 28 "Suggested" readiness rows on opening a customised 14-finding report; up to 84 dismissal clicks across three editing passes, because a dismissal releases whenever the text changes again; and a measured 3 banners today on the drafts on disk, rising toward 27 as the 12 unverified findings are checked.

### Not asked

The planner's question about whether the Content page's own title box should swap library entries the way the Findings list does was **not put to the user**. The planner's stated default applies: leave it alone, because a rename there would otherwise present an offer to overwrite the section the tester is looking at. Recorded so the next person knows it was a decision, not an oversight.

## Round 3 - Planner: design addendum after the answers

### A. What `content_offer_resolved` becomes under Option B

**It becomes dead as a suppressor, and it cannot be kept in any weakened form.**

`pendingLibraryOffers` runs four filters in series ([app.js#L1233-L1240](app/web/static/app.js#L1233-L1240)):

1. not (`status === "resolved"` and `recommended_remediation`)
2. `content_offer_resolved?.[type] !== entry.library_id` — the latch
3. `libraryContentFor(entry, type).length`
4. `!sameFragments(section, libraryFragments)` — the equality suppressor

Filter 4 **is** Option B, already written. It passes exactly when the section differs. The only state where filter 2 suppresses but filter 4 does not is "section differs **and** latch holds this entry's id" — which is precisely the state Option B exists to surface. So filter 2 must be deleted outright; any retained form of it re-suppresses the thing you asked for.

The server-side pre-answer at [main.py#L730](app/main.py#L730) is also now redundant, for a checkable reason: at insert the description is byte-identical to the entry (nothing reorders it — `provision` seeds only into a zero-fragment section) and the remediation is byte-identical too because insert always produces `open_new`, whose branch keeps every fragment without a `resolved_remediation` marker. Filter 4 alone keeps the insert silent.

**Decision: the field stays declared, stops being read, and keeps every writer it has.**

- Not removed. Pydantic v2 ignores unknown keys, so deleting the field would silently drop it from all 23 findings on their next save — real deletion, no migration, no warning, for no benefit beyond tidiness.
- Writers stay (`insert_library`, `applyLibraryEntry`'s reset, the three offer arms). A field that is written-but-unread is inert; a field that is declared-but-stale is a trap for the next reader who finds a 2026 value and believes it.
- `test_a_library_insert_does_not_offer_back_the_content_it_just_copied` ([test_app.py#L1422](tests/test_app.py#L1422)) stays green but stops describing behaviour. It must be joined by a browser test that asserts the *behaviour* — an inserted finding shows zero `.content-offer` — otherwise nothing pins "insert is silent" once the latch is out of the path.
- Add `test_the_content_offer_latch_no_longer_suppresses_an_offer`: a finding whose latch names its entry and whose description differs shows the banner. This is the guard against someone restoring filter 2.

---

### B. The fingerprint

#### B0 — The finding that reshapes this whole section

**The existing `sameFragments` normalisation is not stable across a save round-trip, so hashing it or storing it verbatim both fail in the same way: the dismissal would be undone by its own save, seconds later, without the tester touching anything.**

Two confirmed asymmetries between a client-built fragment and the same fragment after it comes back from the server:

| | Client, freshly typed | After `applyCanonicalReport` |
|---|---|---|
| `runsFrom` deletes false flags ([app.js#L941](app/web/static/app.js#L941)) | `{text:"x"}` | `{text:"x",bold:false,italic:false,underline:false}` |
| `newFragment("paragraph")` sets no `generated` ([app.js#L2230](app/web/static/app.js#L2230)) | `{frag_id,type,runs}` | `{frag_id,type,runs,generated:null}` |

The server dumps with `model_dump(mode="json", by_alias=True)` and no `exclude_none` ([main.py#L708](app/main.py#L708)), so every optional field is emitted explicitly. On the way back, `reconcileCanonicalObject` finds runs have no `stableItemKey` (the key list is `uid, frag_id, target_id, evidence_id, type` — a `Run` has none), falls to the unkeyed branch, and splices the canonical runs over the live ones ([app.js#L459-L461](app/web/static/app.js#L459)). The three `false` keys arrive.

Sequence: press Dismiss → fingerprint recorded → `scheduleSave()` → response merges → runs change shape → next `render()` recomputes → mismatch → **banner back**. This is not an edge case; it is every section the tester has typed into.

#### B1 — The normaliser

One shared function, replacing the `JSON.stringify`-with-replacer trick. Arrays, not objects, so key order is not even a question; every optional is **coerced**, not stripped, so absent/`null`/`false` collapse to one token.

```js
// Absent, null and false read the same to a tester, but the server dumps every optional field
// explicitly, so a typed section changes shape the first time it is saved. Coerce, do not strip.
const normalizedRuns = runs => (runs || []).map(run => [run.text || "", run.bold ? 1 : 0, run.italic ? 1 : 0, run.underline ? 1 : 0]);
const normalizedCells = cells => (cells || []).map(cell => normalizedRuns(cell.runs));
const normalizedSection = fragments => JSON.stringify((fragments || []).map(fragment => [
  fragment.type, normalizedRuns(fragment.runs), normalizedCells(fragment.items),
  normalizedCells(fragment.header), (fragment.rows || []).map(normalizedCells),
  fragment.text || "", fragment.caption || "", fragment.evidence_id || "",
  fragment.environment || "", fragment.generated || "",
]));
const sameFragments = (left, right) => normalizedSection(left) === normalizedSection(right);
```

`width_mm` is deliberately absent: it is layout, not content, and images only live in proof sections, which do not use the fingerprint.

Redefining `sameFragments` in terms of the same function is mandatory, not tidiness. If the trigger and the dismissal disagree about what "the same" means, you get banners that show and self-dismiss, or dismissals that never take. **VDB-012's case survives:** an empty `code_block` and an empty `table` are still extra array entries with their own `type` token, so that finding still reads as "differs" — the outcome you accepted explicitly.

#### B2 — Hash, not content

**Store a hash.** The verbatim-string argument ("no new algorithm") is void, because B0 shows a new normaliser is required regardless. Once you are writing a normaliser, hashing it is four more lines.

Size, quantified. Library descriptions run 300–700 characters of text (VDB-015's is ~600 + ~80; VDB-014's ~520 + ~90); normalised form adds roughly 40 bytes per fragment. So a library-sized fingerprint is 0.4–0.9 kB, and 2 sections × 14 findings ≈ **15–25 kB** of duplicated prose in `draft.json`. That alone would be tolerable. What is not tolerable is where else it goes:

- `previousReport = clone(report)` on every banked diff, plus `activeTextTransaction.before = clone(previousReport)` ([app.js#L725-L733](app/web/static/app.js#L725))
- `persistLocalDraft()` → `localStorage.setItem(JSON.stringify({…report}))` on a 150 ms debounce ([app.js#L302-L312](app/web/static/app.js#L302)) — and localStorage is ~5 MB per origin, scanned across *multiple* draft keys at boot ([app.js#L61](app/web/static/app.js#L61))
- `undoHistory` change records in `sessionStorage`, 20 deep ([app.js#L561](app/web/static/app.js#L561), [app.js#L96](app/web/static/app.js#L96)) — a verbatim fingerprint makes each dismissal a multi-kB `before`/`after` pair
- `draft.bak.json`, which duplicates the whole file on every save

And the bound is wrong in the first place: under Option B the fingerprint records the **tester's** section, not the library's, and a tester's Description is unbounded — one pasted 10-row table is 2–4 kB. Twenty-eight of those, cloned per keystroke, is not a rounding error.

Secondary but real: a verbatim fingerprint puts two copies of the same prose in the draft, and the next person to read a draft during a bug report has to work out which one is live.

```js
// 32-bit FNV-1a over the normalised section. Client-only: Python stores the string and never
// computes it, so this is not a twin. A collision hides one banner on one section until the
// next edit, which is why 32 bits is enough.
const sectionFingerprint = fragments => {
  const text = normalizedSection(fragments);
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) { hash ^= text.charCodeAt(index); hash = Math.imul(hash, 0x01000193); }
  return `${text.length}-${(hash >>> 0).toString(16)}`;
};
```

The length prefix costs ~5 bytes and means a collision needs the same length *and* the same 32-bit hash. `crypto.subtle.digest` is rejected for a checkable reason, not taste: it is async, and `pendingLibraryOffers` is synchronous and called during render.

**Your "no new twin" premise is confirmed, with one caveat in B5.**

#### B3 — Field, type, default, model

Beside its two siblings on `Vulnerability` ([models.py#L197-L201](app/models.py#L197)):

```python
    # The section content each library offer was last answered against, as an opaque client-computed
    # fingerprint. Releases the moment the section is edited again. No Python reader or writer.
    content_offer_dismissed: dict[ContentType, StableId] = Field(default_factory=dict)
```

`StableId` is `^[A-Za-z0-9][A-Za-z0-9_.-]*$`, max 128 ([models.py#L24](app/models.py#L24)). `<decimal>-<hex>` matches it and is at most ~16 characters. Typing it as `StableId` rather than `str` follows `content_offer_resolved`'s precedent exactly and gives free rejection of anyone smuggling prose into the field.

#### B4 — Migration

A missing key means "no answer recorded for this section", which is the correct starting state for all 23 findings on disk: none of them has ever been dismissed under a rule that did not exist. `default_factory=dict` makes both the absent key and `{}` validate.

**`load_path` needs no repair entry, and adding one would be actively wrong.** `load_path` repairs shapes that are *incorrect* — a list fragment with no items, boilerplate missing its marker ([workspace.py#L271-L296](app/workspace.py#L271)). An absent dismissal record is not incorrect. A repair that back-filled fingerprints from current content would pre-dismiss every banner on every existing draft, which is the exact opposite of what Option B was chosen for.

#### B5 — The `null` rule

Both siblings are plain, not `Optional`; a missing key and `{}` validate, explicit `null` returns 422. Declared identically, `content_offer_dismissed` follows. Pinned by a test mirroring `test_the_conclusion_offer_memory_round_trips_and_refuses_null` ([test_app.py#L1795](tests/test_app.py#L1795)).

Client side, the write uses the `||=` idiom already in place at [app.js#L3200](app/web/static/app.js#L3200): `(finding.content_offer_dismissed ||= {})[content.type] = …`. Never `delete`-then-null.

**Caveat on "no twin".** Typing the value as `StableId` makes the hash *alphabet* a contract: if the JS ever emits a character outside `[A-Za-z0-9_.-]`, every save 422s. That is a one-way coupling, not a twin — Python validates a shape it never produces — but it needs a test: `test_a_content_offer_fingerprint_round_trips_and_refuses_null`, plus a browser assertion that a dismissal survives a save-and-reload, which is what would catch an alphabet drift in practice.

#### B6 — `reconcileCanonicalObject`

**Rides the generic merge. Do not add it to the exclusion list.**

The exclusion list is `saved_at`, `app_id`, `_folder_name_hint`, `scope_text` ([app.js#L427](app/web/static/app.js#L427)) — three server-owned fields the client must never fight, and one client-only field the server never echoes. `content_offer_dismissed` is neither: it is client-authored and server-round-tripped, exactly like `content_offer_resolved`, which is not excluded.

The merge is free here. Python never modifies the field, so `sent === canonical` always, and the `sameValue(sentValue, canonicalValue)` early return at [app.js#L432](app/web/static/app.js#L432) skips the key on every reconcile. Excluding it would be strictly worse: after a 409 "Load latest", a legitimately returned value could not propagate.

#### B7 — Who writes it, and when, relative to `provision`

**All three arms write it, from the section's post-mutation content, inside the click handler.** Order: (1) mutate `content.fragments`, (2) `content_offer_dismissed[type] = sectionFingerprint(content.fragments)`, (3) `render()`, (4) `scheduleSave()`.

`merge` in particular *must* write it: "Add below" appends library content to the tester's, so the section still differs from the entry and the banner would re-offer the instant it was accepted. `replace` produces byte-equality and does not strictly need it, but writing it in all three arms makes the rule one sentence — *the banner records what the section looked like when you left it* — instead of three.

**The `provision` fight you were warned about does not materialise, and the reason is structural.** `provision` runs on both sides on every save ([main.py#L261-L265](app/main.py#L261)). It can change these sections three ways: seeding starter fragments into a zero-fragment section; replacing the remediation with boilerplate on resolve; stripping `resolved_remediation` fragments on reopen. In every case where it changes the section, the fingerprint no longer matches and the dismissal releases — which is the right answer each time, and in the reopen case is the behaviour this whole plan exists to produce. **The field is a function of what `provision` produced, so it can never contradict `provision`.** That is the property a persisted `dismissed: true` boolean would not have had, and it is why this shape is safe where my Round 1 objection assumed it would not be.

The one hard rule: never recompute the fingerprint on load or on save, and never write it from a `reportchange` listener — that is the unbounded-PUT loop that eats the single `draft.bak.json`.

**One ordering hazard, new.** `applyLibraryEntry` resets `content_offer_resolved = {}` on an entry swap ([app.js#L1821](app/web/static/app.js#L1821)). The fingerprint is of the *section*, not the entry, so a dismissal recorded against VDB-014 would still suppress VDB-036's offer if the tester swaps entries without editing the section. `applyLibraryEntry` must clear `content_offer_dismissed` on the same line.

#### B8 — Does the proof of concept need a fingerprint? No.

Answer 4 makes the POC trigger **emptiness**, not difference: library POC steps live in `LibraryEntry.proof_of_concept` ([library.py#L23](app/library.py#L23)), not in `contents`, so `sameFragments` never applies to them and "differs from the library" is undefined for this section. The predicate is binary — `written` ([app.js#L3148](app/web/static/app.js#L3148)) — and a fingerprint of an empty section is a constant, so it would carry no information.

But the Dismiss-is-a-no-op defect reappears in exactly the same shape: pressing Dismiss writes `poc_variant_declined` and changes no fragments, so `!written` still holds and the banner redraws. **The fix needs no new field, because `poc_variant_declined` already is the persisted record of a dismissal.** The only change needed is which list `written` overrides:

```js
const variants = applicablePocVariants(finding)
  .filter(variant => !(finding.poc_variant_declined || []).includes(variant))
  .filter(variant => !written || !(finding.poc_variants || []).includes(variant));
```

Answer 4 is satisfied (deleting installed steps re-offers, because `poc_variants` no longer suppresses when empty), Dismiss works and persists, and `applyPocVariant` already clears the decline for a channel it installs ([app.js#L1204](app/web/static/app.js#L1204)) so the two lists stay coherent.

**One asymmetry to accept knowingly:** a tester who *declines* and later empties the steps is offered nothing, whereas one who *installs* and empties is re-offered. Declines are permanent, installs are not. Getting the offer back after a decline means re-picking the entry on the Findings page, which clears both lists.

---

### C. Answer 3 — the conclusion prompt

#### C1 — The thing that breaks the obvious implementation

**`syncConclusion` has already rewritten the sentence by the time `offerConclusionRewrite` runs, at all three call sites.** Findings `onchange` reaches it via the preceding `oninput` or via `applyLibraryEntry`; the status handler reaches it through `provision` ([app.js#L1114](app/web/static/app.js#L1114)); the editor's `finishTitle` calls it directly on the line above ([app.js#L3039](app/web/static/app.js#L3039)). So `hasDefaultStatusConclusion(first)` is true at prompt time *because the rewrite already happened*. A dialog asking "should I replace it?" would be asking permission for something done.

**And "Keep mine" on boilerplate is unimplementable without a schema change.** If the tester kept the old sentence, the server's `provision` sees a paragraph that still `has_default_status_conclusion` ([report_service.py#L237-L238](app/report_service.py#L237)) and rewrites it to the new name on the very next autosave. A two-arm dialog there would promise a refusal the app silently undoes — the exact failure I am told not to accept.

#### C2 — What changes

**The early return loses exactly one clause.** `if (!first || first.generated || !fragmentHasText(first) || hasDefaultStatusConclusion(first)) return false;` → drop `hasDefaultStatusConclusion(first)`. That clause is the one that makes boilerplate silent, and it is the one you are overriding. The other three stay as null/empty guards; after `syncConclusion` two of them are already unreachable, and removing them changes nothing while costing a review argument.

**Capture before, prompt after.** The paragraph's runs are captured at the top of each call site, before `syncConclusion` runs, so the dialog can quote what it *was*. This needs no signature change to `syncConclusion` — which matters, because `syncConclusion` is the twin of `provision`'s conclusion block ([report_service.py#L233-L250](app/report_service.py#L233)) and changing its shape on one side only is rule drift.

**Suppress when the sentence did not actually change.** Compute `derived`; if it is byte-identical to the recognised span in the captured text, return `false` without prompting. This is not rate-limiting and not a lie — nothing changed. It kills two real cases: an `onchange` that fires with an unaltered value, and `open_new → open_previously_discovered`, which both map to `"Open"` in `statusConclusionRuns` and therefore produce an identical sentence.

**Two dialog shapes, chosen by whether the captured text was boilerplate:**

- *Tester prose* (captured text contains no recognised sentence) — unchanged copy, unchanged two arms. Today this branch is reached because `hasDefaultStatusConclusion` was false; it still is. Returns `true` when it rewrote.
- *Boilerplate* (captured text contains one) — a **one-button notice**, not a choice:
  - title: `The closing sentence was updated`
  - message: `The standard closing sentence now reads "<derived>". Replace it with your own wording before generating.`
  - one action: `OK`
  
  Built with `window.vrDialog.ask({…, actions:[{key:"ok", label:"OK", tone:"primary"}]})` — `ask` already takes arbitrary action lists ([dialog.js#L9](app/web/static/dialog.js#L9)), so `dialog.js` does not change.
  
  **Returns `false`, not `true`** — `syncConclusion` already performed the write, so the notice itself changed nothing and the caller has nothing to re-render for. This is load-bearing; see C4.

The current copy, `This finding's conclusion reads "…"`, stays only on the prose branch, where it is accurate. It never appears for a sentence the app wrote.

#### C3 — The Findings page, per committed edit

`titleInput.onchange` fires once per *commit* — blur or Enter — and only when the value actually changed; `oninput` handles keystrokes and does not prompt ([app.js#L2023](app/web/static/app.js#L2023)). So a 40-character rename produces one notice on blur, not forty. Tabbing through untouched title fields is silent. The editor's `finishTitle` is guarded by `titleCommitted` ([app.js#L3035](app/web/static/app.js#L3035)), so Enter-then-blur fires once.

**No rate limiting beyond the unchanged-sentence suppression.** The remaining volume — one notice per genuine rename, one per genuine status change — is the volume you asked for.

#### C4 — Collision with the status dialog

The existing ordering survives. The status handler awaits the confirm, then awaits `offerConclusionRewrite`, with the comment that says why ([app.js#L2060](app/web/static/app.js#L2060)). `vrDialog` settles an open dialog when a second opens ([dialog.js#L11](app/web/static/dialog.js#L11)), and the `await` prevents that here.

**A new collision does appear, on a path that was previously silent.** If the tester blurs a title field *by clicking the status select in the same row*, the title notice opens; the `change` event then fires and `ask` calls `openDialog.settle("cancel")` on it. For a one-button notice, `cancelKey` resolves to the last action — `"ok"` — so the notice vanishes unread. The tester misses one informational message. Accepted, and listed as a risk.

What is **not** accepted is the second-order version: if the notice branch returned `true`, `titleInput.onchange` would run `renderFindings()` while the status dialog is open, detaching the `event.target` the status handler holds and leaving the row's DOM stale against the model. Returning `false` from the notice branch removes this entirely, which is why C2 specifies it.

---

### D. Answer 4 — re-offering installed steps

The `pendingLibraryOffers` change is in B8. The `written` predicate moves up from the banner at [app.js#L3148](app/web/static/app.js#L3148) so the banner and the decision read one source.

**The two tests that pass by luck:**

- `test_a_finding_is_offered_only_the_app_types_it_has_not_installed` ([test_browser.py#L1463](tests/test_browser.py#L1463))
- `test_unchecking_a_location_in_the_page_withdraws_that_app_types_offer` ([test_browser.py#L1533](tests/test_browser.py#L1533))

Both assert `.poc-offer` counts against `poc_variants: ["web"]`, and both survive only because `_complete_finding` writes `numbered_list.items[0].runs = [Run(text="Complete proof step")]` ([test_browser.py#L1438](tests/test_browser.py#L1431)), making `written` true so the override never engages. Nothing in either test says that is why.

**New test, same fixture, opposite branch:** `test_emptying_the_installed_steps_offers_them_again` — VDB-036, `poc_variants: ["web"]`, web + api scope, but with the numbered list cleared to `[{"runs": []}]` before saving. Assert `.poc-offer` count is 1 and `data-poc-offer` is `"web api"`: neither channel is installed-with-content, so both are offered. The pair now brackets the rule, and the older test's assertion stops being a coincidence.

Second new test: `test_declining_the_returned_poc_offer_keeps_it_hidden_across_a_reload` — dismiss on the emptied section, reload, assert zero. This is the POC half of the Dismiss defect, and it is the test that proves `poc_variant_declined` is doing the job a fingerprint would otherwise have to.

---

### E. Revised data risks

Only rows that changed, plus new ones.

| Failure mode | Round 2 | Now | Reasoning |
|---|---|---|---|
| **Schema break** | clear | **RISK** | New persisted field on `Vulnerability`. Missing key means "never answered", which is correct for all 23 findings on disk; `default_factory=dict` validates it. No `load_path` repair, and a back-fill repair would be actively wrong (B4). The `StableId` type makes the hash alphabet a save-blocking contract (B5). |
| **Round-trip instability** | — | **RISK — mitigated by B1** | Confirmed, not theoretical: `runsFrom` deletes false flags, the server returns them, and `reconcileCanonicalObject` splices the canonical runs over the live ones. Without the coercing normaliser, a dismissal is undone by its own save. |
| **Dismiss is a no-op** | mitigated by a session `Set` | **mitigated by the fingerprint** | Persisted, survives reload, releases on edit. |
| **Dismissal survives an entry swap** | — | **RISK — mitigated** | The fingerprint is of the section, not the entry, so a dismissal against VDB-014 would suppress VDB-036's offer. `applyLibraryEntry` must clear it on the same line that clears `content_offer_resolved`. |
| **Draft size and clone cost** | — | **RISK — mitigated by the hash** | A verbatim fingerprint duplicates unbounded tester content into `draft.json`, `draft.bak.json`, a per-keystroke `clone(report)`, a 150 ms-debounced localStorage write against a 5 MB shared budget, and 20 deep of `sessionStorage` undo records. The hash is ≤16 characters. |
| **Existing drafts start showing offers** | RISK — 1 banner measured | **RISK — 3 measured, up to 27** | Recomputed below. |
| **Derived-state fight with `provision`** | clear, load-bearing on two guards | **clear, for a better reason** | Every way `provision` can change these sections also releases the dismissal, and releasing is the right answer in each case — the reopen case most of all. The field is a function of `provision`'s output, so it cannot contradict it (B7). |
| Rule drift | clear | **clear, with a named coupling** | No Python writer or reader; the hash is JS-only, so no twin. But Python validates the value against `StableId`, so the hash alphabet is a one-way contract that needs a test (B5). `sameFragments` is redefined, and it is client-only — there is no Python counterpart to keep in step. |
| **Conclusion notice fires when nothing changed** | — | **RISK — mitigated** | `open_new → open_previously_discovered` yields an identical sentence, because both map to `"Open"`. Suppressed by comparing the derived sentence against the captured one (C2). |
| **"Keep mine" on boilerplate would not survive a save** | — | **RISK — designed out** | The server re-derives any paragraph that still contains a recognised sentence. A two-arm dialog would promise a refusal the next autosave undoes. Hence a one-button notice (C1, C2). |
| **Title notice cancelled by the status dialog** | — | **RISK — accepted** | Blurring a title field by clicking the status select settles the notice unread. Cost: one missed informational message. The worse version — `renderFindings()` during an open dialog — is removed by returning `false` from the notice branch (C4). |
| Backup exhaustion | RISK — mitigated | **RISK — unchanged, wider surface** | Same loop, same mitigation. Option B produces far more banners, so `refreshContentOffers` does more work per tick; it must still never write. |

#### Blast radius under Option B, recomputed

The oracle's census: 17 findings carry a `library_ref`; 5 were byte-compared in full, 12 were not. Under Option A exactly one finding gained a banner, because the release condition was emptiness and only one section on disk is empty.

Under Option B the condition is difference, so the oracle's equality verdicts map straight onto banners:

| Finding | Description | Remediation | Banners |
|---|---|---|---|
| Northstar VDB-047 | equal | **differs** (empty paragraph vs `bulleted_list` + `note`) | **1** |
| QA VDB-012 | **differs** (extra empty `code_block`) | **differs** (extra empty `table`) | **2** |
| QA VDB-014 | equal | equal | 0 |
| QA VDB-015 | equal | equal | 0 |
| QA VDB-026 | equal | equal | 0 |

**Measured floor: 3 banners across 2 findings, and 3 new "Suggested" readiness rows** — up from 1 under Option A. The 12 unverified findings contribute 0 to 24 more, so the true figure is **between 3 and 27**.

Two notes on the floor's soundness. The oracle compared by reading text, which is closer to the coercing normaliser than to strict JSON, so its three "equal" verdicts hold under B1 and might not have held under the old strict `sameFragments` — adopting the normaliser makes the floor *more* reliable, not less. And the 5 verified were not a random sample; they were the interesting ones.

---

### F. Revised steps

**Step 0 — the field. NEW, and it must be first.**
*Files:* [app/models.py](app/models.py) — `content_offer_dismissed` beside its siblings.
*Tests:* [tests/test_app.py](tests/test_app.py)`::test_a_content_offer_fingerprint_round_trips_and_refuses_null`, mirroring [test_app.py#L1795](tests/test_app.py#L1795).
*Invariant:* a client that writes this field must never receive a 422. Any later step writes it, so if the model lands second, every save fails in between.

**Step 1 — the normaliser. NEW, replacing part of Round 2's step 2.**
*Files:* [app/web/static/app.js](app/web/static/app.js) — `normalizedSection`, `sectionFingerprint`; `sameFragments` redefined in terms of the first.
*Tests:* [tests/test_browser.py](tests/test_browser.py)`::test_a_section_typed_to_match_the_library_reads_as_unchanged_after_a_save` — type the library's exact text, save, assert no banner before **and** after the round trip. This is the B0 regression test and it fails today.
*Invariant:* the trigger and the dismissal use one normalisation. Never two.

**Step 2 — cadence. CHANGED from Round 2's step 1 only in volume.**
*Files:* [app/web/static/app.js](app/web/static/app.js) — extract the four banner bodies into `contentOffersFor(finding, content)` returning nodes with no wrapper; add `refreshContentOffers` beside the `updateReadinessPanel` listener; add `queueReportChange()` to the existing `focusout` branch.
*Tests:* `::test_refreshing_offers_does_not_change_the_report`; `::test_a_section_with_no_offer_keeps_the_children_it_has_today`; `::test_the_conclusion_offer_appears_after_a_step_is_typed_and_the_field_is_left`; `::test_a_collapsed_section_survives_an_offer_refresh`; `::test_clearing_the_conclusion_offers_the_standard_sentence_back` (Banner B, which has never had a test).
*Invariants:* the banner set produced by `render()` is identical before and after this step. The refresh never assigns into `report`, never calls `scheduleSave`, does nothing while `activeTextEntry()` is non-null, visits expanded blocks only, compares serialised markup before replacing, and preserves `data-offer-for`. No `.offer-slot` — the three positional `.content-block > …` rules are duplicated at [taste.css#L1366](app/web/static/taste.css#L1366) and [taste.css#L3102](app/web/static/taste.css#L3102) and a wrapper breaks both.

**Step 3 — Option B. CHANGED from Round 2's step 2.**
*Files:* [app/web/static/app.js](app/web/static/app.js) — delete the `content_offer_resolved` filter; add the `content_offer_dismissed` filter; write the fingerprint in all three arms after their mutation; clear it in `applyLibraryEntry`.
*Tests:* `::test_editing_a_library_section_offers_it_back`; `::test_dismissing_an_offer_keeps_it_hidden_across_a_reload`; `::test_editing_a_dismissed_section_offers_it_again`; `::test_adding_below_does_not_immediately_re_offer`; `::test_swapping_library_entries_clears_a_dismissal`; `::test_an_inserted_finding_shows_no_content_offer`; `::test_the_content_offer_latch_no_longer_suppresses_an_offer`.
*Invariants:* the `status === "resolved"` filter stays **first** — not because a resolved remediation reads as empty (it does not; the boilerplate has text) but because that block renders `Locked for resolved findings.` with no fragment editors, so a banner there offers an action the tester cannot complete. The fingerprint is written only in click handlers, never on load, save, or a `reportchange` tick.

**Step 4 — reopen proof and the no-twin pin. UNCHANGED.**
*Files:* none in `app/`.
*Tests:* `tests/test_browser.py::test_reopening_a_resolved_finding_offers_the_library_remediation`; `tests/test_app.py::test_a_status_change_leaves_the_content_offer_memory_untouched` — extend to assert **both** `content_offer_resolved` and `content_offer_dismissed` round-trip byte-identical through a real reopen save.
*Invariant:* `provision` never mutates either field, on either side.

**Step 5 — the proof-of-concept offer. CHANGED from Round 2's step 4 by answer 4.**
*Files:* [app/web/static/app.js](app/web/static/app.js) — `written` hoisted out of the banner; it overrides `poc_variants` only, never `poc_variant_declined`.
*Tests:* `::test_emptying_the_installed_steps_offers_them_again`; `::test_declining_the_returned_poc_offer_keeps_it_hidden_across_a_reload`; re-run both lucky tests and the previous-proof zero-offer assertion at [test_browser.py#L1736](tests/test_browser.py#L1736).
*Invariants:* images are excluded from `written` and preserved by `applyPocVariant` in both modes — the only thing standing between a widened offer and a deleted screenshot. Channel gating in `applicablePocVariants` is untouched. **Reviewer note:** this step's definition of "empty" rests on `ensure_proof_steps`/`ensureProofSteps` and its safety on `apply_poc_variant`/`applyPocVariant`, both twinned pairs; neither is edited, both are newly depended upon.

**Step 6 — the conclusion notice. NEW, last.**
*Files:* [app/web/static/app.js](app/web/static/app.js) — `offerConclusionRewrite` loses `hasDefaultStatusConclusion(first)`, gains the pre-`syncConclusion` capture, the unchanged-sentence suppression, and the boilerplate notice branch; the three call sites pass the captured runs.
*Tests:* `::test_renaming_a_finding_announces_the_new_closing_sentence`; `::test_renaming_a_finding_with_a_written_conclusion_still_asks_before_replacing`; `::test_moving_between_the_two_open_statuses_does_not_announce_anything`; `::test_the_status_dialog_still_settles_before_the_conclusion_prompt`.
*Invariants:* `syncConclusion`'s signature does not change on either side. The notice returns `false` so no caller re-renders during an open dialog. The status confirm is still strictly awaited before the notice.

**Step 7 — documentation.** [docs/DATA_MAP.md](docs/DATA_MAP.md) §6 gains `content_offer_dismissed` and records that `content_offer_resolved` is now write-only on both sides; §12 gains the notice and the refresh listener. Required by the data-layer maintenance contract.

---

### G. What I would still push back on

You have the fingerprint specified and it is buildable. Two things I do not think you have been shown.

**1. A customised report opens with up to 28 banners, and the readiness panel gains up to 28 suggestion rows.**

Option B's condition is "differs from the library". A tester who customises library prose — your normal workflow — makes every section differ. A 14-finding report has 28 candidate sections, and every `pendingLibraryOffers` result also becomes a "Suggested" warning row in the readiness panel ([app.js#L2861-L2870](app/web/static/app.js#L2861)). The panel is your triage surface; 28 permanent suggestion rows is not a triage surface.

The measured version, on the drafts you have now: 3 banners today, rising toward 27 as the 12 unverified findings are checked. The Option A version was 1.

**2. The fingerprint makes the dismissal per-edit, which means the pathological workflow is the normal one.**

A dismissal releases the moment the section changes. So: write the Description, dismiss the banner; proofread and fix a typo, banner returns, dismiss again; proofread again, dismiss again. Three editing passes over 14 findings × 2 sections is **up to 84 dismissal clicks in one report**, and the banner is always offering to overwrite prose the tester deliberately wrote. That is not a fingerprint bug — it is what "remembered until the text changes again" means when the trigger is "the text is not the library's".

**What I would offer instead, if you want Option B's reach without the noise:** keep Option B as the trigger, but split the two surfaces. The **banner** shows only when the section is empty (Option A's condition), and the **readiness panel's suggestion row** uses Option B's condition, so "the library still has a version of this" is always one click away from the panel but never sits on top of the section you are writing. The `pendingLibraryOffers` return would carry a `reason` of `"empty"` or `"differs"`, and the banner filters on the first. It costs one field on the offer object and no schema change beyond what is already specified, and it keeps the fingerprint — which is still needed for the panel row to be dismissable.

I have specified what you chose, in full, above. This is an alternative, not a refusal.

## Agreed plan

Seven ordered steps. Each names its files, its test, and the invariant it must not break. Everything below is client-side except step 0, which adds one field.

### What is being built

1. **The library offer returns whenever a section differs from its library entry**, not only when the section is empty. The permanent `content_offer_resolved` latch stops gating it.
2. **Dismissing an offer is remembered until the section changes again**, via a new persisted fingerprint of the section at the moment it was answered.
3. **Offers appear without a page refresh.** Today a banner is only built by a full re-render, which typing never triggers.
4. **Deleting every library step re-offers them.** Declining still sticks.
5. **Renaming a finding or changing its status announces the new closing sentence**, instead of rewriting it silently.

### The three decisions that shape it

- **`content_offer_resolved` becomes write-only.** Under "offer whenever it differs", the only state the latch suppresses is exactly the state the change exists to surface, so its filter is deleted. The field stays declared and keeps every writer — removing it would silently drop the key from all 23 findings on their next save, since Pydantic ignores unknown keys.
- **The fingerprint is a hash, not the content.** A verbatim copy would duplicate unbounded tester prose into `draft.json`, `draft.bak.json`, a per-keystroke `clone(report)`, a debounced `localStorage` write against a 5 MB shared budget, and 20 deep of `sessionStorage` undo records. The hash is at most 16 characters.
- **The "Keep mine" arm of the conclusion prompt is unimplementable on boilerplate**, because the server re-derives any paragraph still containing the recognised sentence on the very next save. So the boilerplate case is a **one-button notice**, not a choice; only a tester-written conclusion gets a real replace-or-keep dialog.

### The defect this design exists to avoid

Normalisation must be **round-trip stable**. `runsFrom` deletes `false` flags client-side; the server dumps every optional field explicitly; `reconcileCanonicalObject` splices the canonical runs back over the live ones. So a freshly typed `{text:"x"}` becomes `{text:"x",bold:false,italic:false,underline:false}` seconds later. A fingerprint over today's strict comparison would therefore be invalidated **by its own save**, un-dismissing the banner without the tester touching anything. The normaliser coerces absent/`null`/`false` to one token rather than stripping keys, and `sameFragments` is redefined in terms of it so the trigger and the dismissal can never disagree about what "the same" means.

### Ordered steps

**Step 0 — the field. Must be first.**
*Files:* [app/models.py](../../app/models.py) — `content_offer_dismissed: dict[ContentType, StableId] = Field(default_factory=dict)` on `Vulnerability`, beside `content_offer_resolved` and `conclusion_offer_resolved`.
*Test:* [tests/test_app.py](../../tests/test_app.py) — the field round-trips through a real `PUT` and an explicit `null` is rejected, mirroring the existing conclusion-memory test.
*Invariant:* a missing key means "never answered", which is correct for all 23 findings on disk; `default_factory` validates both absent and `{}`. **No `load_path` repair** — back-filling fingerprints from current content would pre-dismiss every banner on every existing draft, the exact opposite of the intent. The value is typed `StableId`, so the hash alphabet is a save-blocking contract: any character outside `[A-Za-z0-9_.-]` 422s every save.

**Step 1 — the normaliser.**
*Files:* [app/web/static/app.js](../../app/web/static/app.js) — `normalizedSection`, `sectionFingerprint` (32-bit FNV-1a with a length prefix), and `sameFragments` redefined in terms of the first.
*Test:* type the library's exact text into a section, save, and assert no banner appears **before or after** the round trip. This test fails today.
*Invariant:* one normalisation, shared by the trigger and the dismissal. `crypto.subtle.digest` is not usable — it is async and `pendingLibraryOffers` is called synchronously during render.

**Step 2 — offers appear without a re-render.**
*Files:* [app/web/static/app.js](../../app/web/static/app.js) — extract the four banner bodies into `contentOffersFor(finding, content)` returning nodes; add a `refreshContentOffers` listener beside `updateReadinessPanel`; add `queueReportChange()` to the existing `focusout` branch.
*Tests:* a refresh tick does not change `report`; a section with no offer keeps exactly the children it has today; the conclusion offer appears after a step is typed and the field is left; a collapsed section survives a refresh; and the restore-default banner gets its first test ever.
*Invariants:* **no wrapper element.** `.content-block` is a grid styled by child position, in three rules duplicated at [taste.css](../../app/web/static/taste.css) lines 1366-1376 and 3102-3112; a permanent slot becomes `.content-toggle + *` and costs every section its heading gap. The refresh never assigns into `report` and never calls `scheduleSave` — a write inside a `reportchange` listener dispatches another `reportchange`, an unbounded PUT loop that consumes the single `draft.bak.json` each pass. It does nothing while `activeTextEntry()` is non-null, which covers the caret's own block *and* its paired sibling in the same `.content-row`. Expanded blocks only. Compare serialised markup before replacing. Preserve `data-offer-for`, which the readiness panel's "go to" arrow resolves.

**Step 3 — offer whenever the section differs.**
*Files:* [app/web/static/app.js](../../app/web/static/app.js) — delete the `content_offer_resolved` filter; add the `content_offer_dismissed` filter; write the fingerprint in all three arms *after* their mutation; clear it in `applyLibraryEntry`.
*Tests:* editing a library section offers it back; dismissing keeps it hidden across a reload; editing a dismissed section offers it again; "Add below" does not immediately re-offer; swapping library entries clears a dismissal; an inserted finding shows no offer; and the retired latch no longer suppresses anything.
*Invariants:* the `status === "resolved"` filter stays **first** — not because a resolved remediation reads as empty (it does not, the boilerplate has text) but because that block renders "Locked for resolved findings." with no fragment editors, so a banner there offers an action the tester cannot complete. The fingerprint is written only in click handlers, never on load, save, or a refresh tick. `applyLibraryEntry` must clear `content_offer_dismissed` on the same line it clears `content_offer_resolved`, because the fingerprint is of the *section* and would otherwise suppress a different entry's offer. The "Add below" arm **must** write the fingerprint: it appends library content to the tester's, so the section still differs and would re-offer instantly.

**Step 4 — prove the reopen case, and pin that no server twin appears.**
*Files:* none in `app/`.
*Tests:* reopening a resolved finding offers the library remediation; and a status-change save round-trips **both** `content_offer_resolved` and `content_offer_dismissed` byte-identical.
*Invariant:* `provision` never mutates either field on either side. This is the guard rail against someone later "helpfully" clearing the latch server-side — derived-state code on both sides overwriting a record of the tester's answer on every save.

**Step 5 — re-offer deleted library steps.**
*Files:* [app/web/static/app.js](../../app/web/static/app.js) — hoist the existing `written` predicate out of the banner so the banner and the decision read one source; it overrides `poc_variants` only, never `poc_variant_declined`.
*Tests:* emptying installed steps offers them again; declining the returned offer keeps it hidden across a reload; plus a re-run of the two existing tests that currently pass only by luck, because their fixture happens to type a real step.
*Invariants:* the proof of concept needs **no fingerprint** — library steps live outside `contents`, so "differs from the library" is undefined there and the trigger is emptiness, for which `poc_variant_declined` is already a persisted dismissal. Images are excluded from `written` and preserved by `applyPocVariant` in both modes, which is the only thing standing between a widened offer and a deleted screenshot. Channel gating is untouched. Accepted asymmetry: declining is permanent, installing is not.

**Step 6 — announce the new closing sentence.**
*Files:* [app/web/static/app.js](../../app/web/static/app.js) — `offerConclusionRewrite` drops its `hasDefaultStatusConclusion` early return, captures the paragraph's runs *before* `syncConclusion` rewrites them, suppresses when the derived sentence is unchanged, and gains a one-button notice branch for boilerplate.
*Tests:* renaming announces the new sentence; renaming with a written conclusion still asks before replacing; moving between the two open statuses announces nothing; and the status dialog still settles before the conclusion prompt.
*Invariants:* `syncConclusion`'s signature does not change on either side — it is the twin of `provision`'s conclusion block. The notice returns `false`, so no caller re-renders the Findings table while a dialog is open. The unchanged-sentence suppression is load-bearing: `open_new → open_previously_discovered` both map to "Open" and would otherwise announce a change that did not happen. Accepted risk: blurring a title field by clicking the status select in the same row settles the notice unread, costing one informational message.

**Step 7 — documentation.** [docs/DATA_MAP.md](../DATA_MAP.md) §6 gains `content_offer_dismissed` and records that `content_offer_resolved` is now write-only on both sides; §12 gains the refresh listener and the conclusion notice. Required by the maintenance contract at the top of that file.

### Costs accepted, to be stated in the release note

- **Up to 28 banners and 28 "Suggested" readiness rows** on opening a customised 14-finding report, because every section a tester has reworded differs from the library permanently.
- **Up to 84 dismissal clicks** across three editing passes over such a report, since a dismissal releases whenever the section changes again.
- **3 banners appear immediately** on the drafts currently on disk, across 2 findings, rising toward 27 as the 12 unverified findings are checked.
- **One finding differs from its entry only by an empty code block and an empty table** and will show two banners offering to overwrite prose that is already word-for-word identical.
- The **Content page's own title box still does not swap library entries** the way the Findings list does. Left alone deliberately: a rename there would otherwise present an offer to overwrite the section being read.

