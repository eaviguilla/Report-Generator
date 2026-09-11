# Form Dependency Contract

The three authoring routes are views over one `Report`. Dependencies remain explicit and domain-specific; there is no generic propagation engine.

| Source | Source page | Dependent | Dependent page | Direction | Owner | Behavior when source changes |
|---|---|---|---|---|---|---|
| `engagement.tested_environments` | Setup | `engagement.test_windows`, visible scope inputs | Setup | One-way | Selected environments | Keep stored window values, but render and validate only selected environments. |
| `scope_text[environment][channel]` | Setup | `scope_targets[]` | Setup | One-way | Scope text | Backend reconciliation preserves stable target IDs. Removing a target still referenced by a finding blocks the save. |
| `scope_targets[].target_id/value` | Setup | `vulnerabilities[].scope.target_ids/location_values` | Findings | One-way | Scope target | Existing selections follow stable IDs. A selected target's location starts from its scope value and then becomes finding-owned editable text. |
| Finding scope and selected environments | Findings | Proof-of-concept image slots and `fragment.environment` | Content | One-way | Finding scope | Add one missing slot per affected environment and preserve extra or uploaded images. Never delete evidence automatically. |
| `vulnerabilities[].status` | Findings / Content | Required content blocks | Content | One-way | Status | Re-provision the allowed block set. Ask before discarding blocks or replacing remediation text. |
| `vulnerabilities[].status` | Findings / Content | Default remediation for resolved findings | Content | One-way | Status | Replace remediation only when the user confirms the destructive status change. |
| `vulnerabilities[].title/status` | Findings / Content | Default conclusion paragraph | Content | Seeded, then editable | Conclusion after manual edit | Recompute only while the paragraph is empty or still matches a generated default; preserve custom prose. |
| Vulnerability library selection | Findings / Content | Finding assessment and content | Findings / Content | One-time copy | Finding after insertion | Copy the library entry, assign fresh fragment IDs, then treat the report copy as independent. |
| Evidence upload result | Content | `report.evidence[evidence_id]` and image `fragment.evidence_id` | Content | Server command | Server response | Apply the returned evidence record and revision together, then persist the linked fragment in the next report save. |

## Invariants

- No row is truly bidirectional. Editable seeded values transfer ownership to the user instead of writing back to their source.
- Backend validation and provisioning remain authoritative.
- Canonical save responses may add defaults or slots, but must not overwrite edits made after that request's snapshot.
- Scope-target removal is rejected while any finding references the target; it is never propagated as silent data loss.