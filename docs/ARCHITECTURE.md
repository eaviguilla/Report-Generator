# How this app works

A plain-language description of what the app does, what it is built from, and how a report becomes
a Word document.

---

## What it is for

It writes penetration test reports. A security tester fills in three screens, and the app produces
a finished Microsoft Word document that matches the company's report template exactly.

It runs on the tester's own machine. Starting it opens a small web server on that computer, and the
browser talks only to that. Nothing goes to the internet.

---

## Tech stack

| Technology | What it is | Responsibilities in this app |
|---|---|---|
| **Python** | A general-purpose programming language. | • Everything that runs outside the browser<br>• Report validation, storage and document generation |
| **FastAPI** | A Python framework for building web servers and APIs. | • Defines every address the browser can call<br>• Serves the three screens<br>• Handles saving, loading, uploading, importing and generating<br>• Enforces the step order, so a screen cannot be opened out of turn |
| **Uvicorn** | A lightweight web server that runs Python applications. | • Listens for the browser's requests and passes them to FastAPI<br>• Picks a free port on startup so several copies can run side by side |
| **Pydantic** | A data validation library. Data shapes are described as Python classes, and anything that doesn't fit is rejected. | • Defines what a valid report is<br>• Checks every report when saved and when opened<br>• Refuses corrupted or hand-edited files rather than half-loading them<br>• Upgrades reports written by older versions of the app |
| **Jinja2** | A templating engine that fills placeholders in a page with real values. | • Builds the three screens before they are sent to the browser<br>• Passes the starting report data into the page |
| **python-multipart** | A parser for the format browsers use when uploading files. | • Receives screenshot uploads<br>• Receives an imported report file |
| **Pillow** | Python's main image-processing library. | • Converts uploaded screenshots to a consistent format<br>• Records image dimensions<br>• Rejects images crafted to be enormous when decompressed<br>• Resizes each screenshot and draws its border for the document |
| **python-docx** | A library for reading and writing Microsoft Word documents, which are really zip archives of XML. | • Opens the master template and the content building blocks<br>• Assembles the report document<br>• Turns image captions into real Word caption fields<br>• Reads a finished report back apart when importing |
| **pywin32** | A package giving Python access to Windows' automation system, which lets one program control another. | • Opens a connection to Microsoft Word<br>• Drives the final layout pass<br>• Windows only |
| **Microsoft Word** | The word processor itself, installed on the tester's machine. | • Lays out the finished document<br>• Repaginates and refreshes fields<br>• Builds the table of contents and the table of figures<br>• Nothing else can do this, because only Word knows where the pages break |
| **HTML, CSS, JavaScript** | The browser's own languages. No framework and no build step. | • The three screens and everything the tester interacts with<br>• Automatic saving<br>• A local backup copy of the report<br>• Live checking of what is still missing |

**Two things worth noting.** There is **no database** — each report is a single text file on the
tester's machine, alongside its screenshots. And there is **no frontend framework** — no React, no
Vue, no compilation step, so there is nothing to build before the app will start.

---

## How the app works

### The three steps

**Step one — the engagement.** Who was tested, the application name, the client segment, the
tester's name, the dates. Which environments were in scope, Production or Non-Production or both,
and which kinds of application: web, API, mobile. Then the actual list of addresses and endpoints
that were tested.

**Step two — the findings.** A table of the vulnerabilities discovered. Each gets a name, a
likelihood, an impact, a severity, a status, and a choice of which scope targets it affects. The
tester can tick targets from step one, or type in extra endpoints by hand.

**Step three — the writing.** For every finding: a description, a recommended remediation, a proof
of concept with numbered steps, and screenshots. On a retest there are two extra sections — last
year's proof of concept, kept for comparison, and a conclusion saying whether the issue is now
resolved.

The steps are ordered. The findings screen will not open until the engagement details are complete,
and the writing screen will not open until every finding has a name, a severity and at least one
affected location. **Going back is always allowed**, because a tester may need to correct a date or
an address at any point.

### Saving

The tester never presses save. About five seconds after they stop typing, the browser sends the
whole report to the local server. FastAPI receives it, Pydantic checks it, and it is written to
disk. The previous version is kept as a backup, so the last good copy always survives.

Three things protect the work:

- **A conflict check.** Every save carries a timestamp of the version it was based on. If the file
  on disk has changed since — because the report is open in a second tab — the save is refused
  rather than silently overwriting the other one.
- **A browser-side copy.** The report is also held in the browser's own storage, so a crash or an
  accidental tab close before a save loses nothing.
- **A flush before leaving.** Moving between the three screens forces a save first, and refuses to
  move if that save fails.

---

## How a report becomes a Word document

Four stages, and the last one is the surprising part.

### 1. Choose the master template

The app ships with several finished Word documents designed by a person, one per report style and
region. They look exactly like a real report but contain placeholder markers where content belongs.
**python-docx** opens the right one and works with its internal structure.

### 2. Splice in the content

Rather than building Word formatting from scratch in code — which is painful and never quite
matches house style — the app keeps a tiny Word document for *every kind of content block*: a
paragraph, a numbered list, a bulleted list, a table, a code block, a note, an image, a caption.
There are separate ones for each severity heading, and for new findings versus retested findings.

To add a paragraph, **python-docx** opens the little paragraph document, copies its internal
formatting, swaps the placeholder text for the tester's words, and drops it into the main document.
The result matches house style because the styling came from a real Word file a human made, not
from code imitating one.

Screenshots go in at this stage too. **Pillow** prepares each image at the right size and draws its
border, before **python-docx** places it in the document.

### 3. Make the captions real

Still using **python-docx**, image captions are converted into genuine Word caption fields — the
kind Word numbers automatically. That is what keeps "Figure 1, Figure 2, Figure 3" correct, and
what allows a table of figures to exist at all.

At this point the document is complete but *unlaid-out*: the contents page is a placeholder and no
page numbers are real.

### 4. Hand the document to Word itself

**pywin32** opens a connection to **Microsoft Word**, launching it invisibly in the background.
Through that connection the app asks Word to repaginate, refresh every field, rebuild the table of
contents and the table of figures, repaginate a second time, then correct the page numbers in the
contents. Then save and close.

This stage exists because **only Word knows where the pages break.** A contents page saying
"Findings …… page 12" needs to know what is actually on page 12, and that needs a real layout
engine. **python-docx** can build content but cannot lay it out — it has no concept of a page. So
python-docx builds the document and Word finishes it.

Because Word can only safely do one thing at a time, generating is queued, so two reports never go
through Word at once. This is also the one part of the app that requires Windows, since **pywin32**
and Word automation exist only there.

---

## Importing a finished report

The manager sends the selected file to the server for byte-based classification. A generated Word
report then offers two explicit choices. **Retest draft** keeps the established transformation:
retained findings become Previously Discovered, the visible proof of concept becomes history, and a
fresh proof and screenshot slots are created for the new test. **Editable draft** instead keeps all
known statuses and every supported section visible in the document, along with recoverable
engagement fields, scope, Additional Information, and evidence.

Editable import creates a new report from the document's visible semantics; it does not reconstruct
the original hidden draft, IDs, or upload metadata. Ambiguous scope is placed in visible review
targets and named in warnings. Unsupported structure or values that would be lost reject the whole
import. **python-docx** performs the structural read, while **Pillow** verifies bounded embedded PNGs.
Before the one workspace write, the server runs the same scope reconciliation, field validation,
and provisioning rules used by an ordinary save and proves that a second pass does not alter the
imported user content. The manager shows counts, transformations, and warnings before opening Setup
or revealing the new report in the list.
