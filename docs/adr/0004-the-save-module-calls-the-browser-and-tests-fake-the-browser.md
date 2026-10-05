---
status: accepted
---

# The save module calls the browser directly, and its tests fake the browser

From: [Give the save machine its own module and a seam](../../.scratch/architecture-review/issues/06-give-the-save-machine-its-own-module-and-a-seam.md)

The save module, `app/web/static/save.js`, calls `fetch`, Web Storage and timers directly. Its tests fake them with Playwright: `page.route` answers saves, `page.clock` moves time, and a blank page served from a made-up address gives real Web Storage. We rejected passing them in, as the 3 October 2026 review proposed, because that adds three inputs, a real and a fake version of each, and hand-written server replies that can stop matching the server. A test builds its refused-save reply from the server's own Python code instead.

## Considered options

- **Pass the server, storage and a clock in, with JavaScript fakes in tests.** This was the review's proposal. Rejected for the cost above.
- **Pass only the server in, and let Playwright fake storage and time.** Rejected, because a hand-written server reply is the fake most likely to stop matching.
