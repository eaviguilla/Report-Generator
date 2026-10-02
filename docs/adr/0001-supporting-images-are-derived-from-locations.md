---
status: accepted
---

# Supporting images are derived from a finding's locations, not stored

Whether a proof-of-concept image is required or supporting depends only on whether its environment is an affected environment of the finding, and an image prints whenever its environment is a tested environment. No field records that a tester chose an image as supporting. One rule then decides what prints, and no stored state can disagree with the finding's locations.

## Considered options

- **A stored flag on each image** marking it as deliberately supporting, so screenshots left behind by a location change could stay hidden. Rejected because the browser and the server would both have to keep it, an older build would drop it, and every draft written before it would have to be classified by guessing.
- **Keep hiding left-behind screenshots**, the outcome recorded in `docs/plans/retire-scope-mode-all.md` ("hidden-not-deleted is the intended outcome"). Rejected because, without the stored flag, a deliberate supporting image and a left-behind screenshot look the same.

## Consequences

- When a finding loses its last location in an environment that is still tested, that environment's screenshots stay in the report as supporting images unless the tester removes them. The Findings page asks; Setup's warnings say so.
- Adding a location in that environment later turns its supporting images into required ones.
- An untested-environment image stays with the finding and does not print.
