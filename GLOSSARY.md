# VulnReport

A local writer for pentest reports. A tester fills in Setup, Findings and Content, and the app builds the Word report from them.

## Language

**Acceptance**:
The server's decision to take a submitted report, after checking it and completing the parts the server owns. A report that fails a check gets a refusal instead.
_Avoid_: save rules, intake, accepting a draft

**Refusal**:
The answer acceptance gives a report it will not take, naming the rule the report broke, such as a stale save, a removed scope target or an invalid Setup field.
_Avoid_: rejection

**Provisioning**:
The server completing a finding with the sections its status requires, their seed fragments, and an image slot for each environment the finding affects.
