# VulnReport

A local writer for pentest reports. A tester fills in Setup, Findings and Content, and the app builds the Word report from them.

## Language

**Acceptance**:
The server's decision to take a submitted report, after checking it and completing the parts the server owns. A report that fails a check gets a refusal instead.
_Avoid_: save rules, intake, accepting a draft

**Refusal**:
The answer acceptance gives a report it will not take, naming the rule the report broke, such as a stale save, a removed scope target or an invalid Setup field.
_Avoid_: rejection

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

**Supporting image**:
A proof-of-concept image for a tested environment the finding does not affect.
_Avoid_: extra image, stale image

**Untested-environment image**:
An image outside Previous Proof of Concept whose environment is not a tested environment.
_Avoid_: environment-irrelevant image, stale image, orphaned image, out-of-scope image

**Word report**:
The Word document the app builds from a report.
_Avoid_: Word document report, generated report, docx, output file
