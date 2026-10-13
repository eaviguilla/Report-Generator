# VulnReport

A local writer for pentest reports. A tester fills in Setup, Findings and Content, and the app builds the Word report from them.

## Language

**Acceptance**:
The server's decision to take a submitted report, after checking it and completing the parts the server owns. A report that fails a check gets a refusal instead.
_Avoid_: save rules, intake, accepting a draft

**Refusal**:
The answer the server gives a report it will not take, whether a save or an import, naming the rule the report broke. Examples are a save conflict, a removed scope target, an invalid Setup field, and a finding heading with no finding row left to pair with.
_Avoid_: rejection

**Save conflict**:
The refusal a save gets when the report was saved somewhere else after this page last saved it. The tester then keeps their version or loads the latest one.
_Avoid_: stale save, 409

**Recovery copy**:
The copy of a report the browser keeps of edits the tester made on one page and the server has not saved yet, so a closed tab or a failed save does not lose them.
_Avoid_: local draft, recovery draft, snapshot

**Undo step**:
One change the tester made on one page, which Undo takes back and Redo brings back whole. Typing in one field until the tester leaves it is one undo step. A paste is its own undo step.
_Avoid_: history entry, undo action, undo entry

**Issue**:
Something in a report that the tester must fix before they can go past Setup or Findings, or build the Word report. A library offer is not an issue, and the server's answer to a save it will not take is a refusal, not an issue.
_Avoid_: blocker, error, problem, gap

**Finding**:
One entry in a report about a vulnerability, with its severity, status and affected locations. A Resolved or Closed finding is still a finding.
_Avoid_: vulnerability, when meaning the entry in the report

**No-findings report**:
A report with no findings of any status: nothing new, previously discovered, resolved or closed.
_Avoid_: clean report, empty report, no-vulnerability report, report type

**Provisioning**:
The server completing a finding with the sections its status requires, their seed fragments, and an image slot for each affected environment.

**Tested environment**:
An environment the engagement covers, chosen on Setup.
_Avoid_: covered environment, selected environment

**Affected environment**:
A tested environment in which a finding has at least one location.
_Avoid_: affected location environment, located environment

**Scope target**:
One thing the engagement may test, in one tested environment and app type. For Web and API it is whatever the tester names, such as a URL, hostname or IP range; for Mobile and Thick Client it is a named component.
_Avoid_: target, scope line, scope entry, asset

**Test account**:
An account on the application under test that the tester used, named by its user role and username.
_Avoid_: user, credential, login

**Network access**:
The access the tester had to the application: from inside the client's network (Internal) or from outside it (External).
_Avoid_: network type, exposure

**Instance title**:
A heading in a finding's content that starts one instance of the finding. The Word report prints it as "Instance n:" followed by the tester's words, numbered from 1 in each section.
_Avoid_: instance heading, instance label

**Environment label**:
The line above proof-of-concept images that names their environment: `PROD:`, or the non-production label in capitals, such as `UAT:`. The Word report prints one before the first image of each environment, and again after an instance title.
_Avoid_: environment title, environment tag, image label

**Image border**:
The thin black line around an image in the Word report. An image that already has one when the tester adds it, such as a picture copied out of an earlier Word report, does not get a second.
_Avoid_: frame, outline

**Supporting image**:
A proof-of-concept image for a tested environment the finding does not affect.
_Avoid_: extra image, stale image

**Untested-environment image**:
An image outside Previous Proof of Concept whose environment is not a tested environment.
_Avoid_: environment-irrelevant image, stale image, orphaned image, out-of-scope image

**Word report**:
The Word document the app builds from a report.
_Avoid_: Word document report, generated report, docx, output file

**Findings Summary table**:
The table under the Findings Summary heading of a Word report, with one finding row per finding.
_Avoid_: summary section, summary table

**Finding row**:
One row of the Findings Summary table, holding a finding's title, likelihood, impact, severity, ID and status. A row inside a finding table is not a finding row.
_Avoid_: summary row, finding summary row

**Finding heading**:
A finding's title in the Word report, above its table and its sections.
_Avoid_: finding detail, detail heading

**Finding table**:
The two-column table under a finding heading. It repeats the finding's severity, ID and status and lists its affected locations.
_Avoid_: detail table, detail section, finding detail

**Section**:
One of the labelled parts of a finding in the Word report: Description, Recommended Remediation, Previous Proof of Concept, Proof of Concept and In Conclusion. The finding's status decides which it prints.
_Avoid_: detail section, block

**Editable copy**:
A new report the app builds from a Word report so that it reads the same: every finding, status, printed section and engagement detail. What the Word report does not print starts fresh.
_Avoid_: editable draft, editable import, restored report

**Retest import**:
Importing a Word report to start the next test of the same application from its open findings, each with its proof of concept moved to Previous Proof of Concept. It leaves the report type for the tester, because the next test may be an annual pentest rather than a retest.
_Avoid_: retest draft, retest type

**Export**:
The ZIP the app downloads for one report, holding the report and its evidence images. Import takes it back unchanged.
_Avoid_: bundle, ZIP bundle, backup

**App window**:
The window the app opens in when it is started from Burp. It has no address bar and no tabs, and it is not Burp's browser.
_Avoid_: Burp browser, node app, popup
