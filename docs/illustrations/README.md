# Illustrations

Four mock-ups of the app for `docs/ARCHITECTURE.md`. They are drawings, not screenshots. The client, the API, the targets and the findings are invented. The severities, statuses, report types and app types are the product's own labels.

| Image | Shows |
|---|---|
| `tour.png` | Setup, Findings and Content side by side. Findings leads. |
| `step-1-setup.png` | The Setup page. |
| `step-2-findings.png` | The Findings page, with the first finding open on its affected targets. |
| `step-3-content.png` | The Content page, with a sketch of the Word page it feeds. |

Colors, radii and labels come from `app/web/static/taste.css` and `app/vocabulary.py`. The mark is a 72 px copy of `app/web/static/logo-red.png`, kept in `source/vulnreport-shared/logo.ts`. The shared folder also holds the look, the page parts and the invented data. Each scene imports it.

## Rebuild

The scenes use the Stageshow kit from `.claude/skills/stageshow`, imported as `../../kit`.

1. Copy the skill folder (`.claude/skills/stageshow`) to a scratch folder outside the repository, because `skills-lock.json` hashes the vendored copy. Copy `source/*` into that copy's `examples/` folder and run `npm install` there.
2. Start Vite after the copy, because it reads the example folders once: `node node_modules/vite/bin/vite.js playground --config playground/vite.config.ts --port 5190`.
3. Film a scene at 2x: `node scripts/film.mjs "http://127.0.0.1:5190/?capture=vulnreport-tour" --still --pad 0 --gate --out tour.png`. Set `CHROME_PATH` if Chrome is not installed in the usual place.
4. Repeat with `vulnreport-setup`, `vulnreport-findings` and `vulnreport-content`. A rebuild on the Mac that drew them matched all four stills byte for byte.

## Where each scene started

- Tour started from `window-row`. Three windows share one top and height, the outer two are cut by the stage, and only the lead has words.
- Setup and Findings started from `static-card`. One window sits on the top gutter and runs off the bottom.
- Content started from `static-card` and `overlap`. The Word page crosses the window's left edge and covers only the finding list, which is bars.

## Left out and not checked

- Light theme only. The app also has a dark theme.
- The fonts are the system font of the Mac that filmed them. The app asks for Aptos and Segoe UI.
- The pages are simplified. The tour table has no Likelihood, Impact or Vuln ID column. Setup shows four of the nine Application fields and the Production row of Test Coverage, and leaves out Test Accounts and Limitations. Content has Description and Remediation closed and no "Still to complete" panel.
- The Word page is drawn. This Mac cannot generate a report.
- Stills only. There is no motion, no 390 px pass and no narrow design.
- Every scene passes `film.mjs --gate` and `layout.mjs --strict`. Three "near aligned" notes remain. Each is a text that starts 13 px in from another because a bordered box sits between them, as on the product's own pages.
- The builder judged the stills against `references/verify.md` and the nearest gold example. No second person reviewed them.
- Nobody has viewed the stills in GitHub's renderer, light or dark. The only comparison with the live app was a look at 1280 px screenshots.
