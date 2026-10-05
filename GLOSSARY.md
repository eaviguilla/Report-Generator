# VulnReport

A local writer for pentest reports. A tester fills in Setup, Findings and Content, and the app builds the Word report from them.

## Language

**Acceptance**:
The server's decision to take a submitted report, after checking it and completing the parts the server owns. A report that fails a check gets a refusal instead.
_Avoid_: save rules, intake, accepting a draft

**Refusal**:
The answer acceptance gives a report it will not take, naming the rule the report broke, such as a save conflict, a removed scope target or an invalid Setup field.
_Avoid_: rejection

**Save conflict**:
The refusal a save gets when the report was saved somewhere else after this page last saved it. The tester then keeps their version or loads the latest one.
_Avoid_: stale save, 409

**Recovery copy**:
The copy of a report the browser keeps of edits the tester made on one page and the server has not saved yet, so a closed tab or a failed save does not lose them.
_Avoid_: local draft, recovery draft, snapshot

**Undo step**:
One change the tester made on one page, which Undo takes back and Redo brings back whole. Typing in one field until the tester leaves it is one undo step.
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

**Supporting image**:
A proof-of-concept image for a tested environment the finding does not affect.
_Avoid_: extra image, stale image

**Untested-environment image**:
An image outside Previous Proof of Concept whose environment is not a tested environment.
_Avoid_: environment-irrelevant image, stale image, orphaned image, out-of-scope image

**Word report**:
The Word document the app builds from a report.
_Avoid_: Word document report, generated report, docx, output file

**App window**:
The window the app opens in when it is started from Burp. It has no address bar and no tabs, and it is not Burp's browser.
_Avoid_: Burp browser, node app, popup
