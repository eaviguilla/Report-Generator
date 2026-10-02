---
status: accepted
---

# The Burp build opens the app window in Edge or Chrome

From: [The Burp build opens the app window](../plans/burp-app-window.md)

Replaces the "Browser" choice in [Host the app from a Burp Suite extension](../plans/burp-extension-launcher.md), which opened the system default browser.

When the Burp tab starts the app, it opens the app window in Edge, or in Chrome when Edge is missing. The extension starts that browser itself, with no address bar and with its own profile in the release folder. It never uses Burp's browser and never falls back to the default browser. If neither Edge nor Chrome is installed, nothing opens, and the tab names the browsers it looked for and prints the address.

## Considered options

- **Burp's browser.** It ships with Burp, so every machine running the extension has it. Rejected because, started outside Burp on Windows, it cannot start its sandbox ("Sandbox cannot access executable … Access is denied"), its network service crashes, and the window comes up blank. repgen-web's Burp launcher hit this and dropped it. The workarounds either turn off part of the sandbox, in a window that displays proof-of-concept payloads, or change permissions inside Burp's install.
- **The system default browser**, the launcher plan's choice. Rejected because it shows an address bar and tabs, and the app becomes one more tab in the tester's own browser.
- **The default browser as a last resort**, as repgen-web does when it finds neither Edge nor Chrome. Rejected because the address bar is what this decision removes. Edge ships with Windows 10 and 11, so a Windows machine reaches that case only when Edge was removed and Chrome was never installed.

## Consequences

- The app window opens only on Windows, where the Burp build runs. Anywhere else the tab opens nothing and prints the address.
- The window and the app stop together. When the server ends, whether by Stop, Force stop or a crash, the extension ends the browser it started without asking it first. Unloading the extension ends it at once, since nothing watches the server after that. When that browser exits, the extension stops the app as if Stop were pressed. A polite close was rejected because it needs a Windows-only way to close another program's window and makes Stop wait on a "Leave site?" answer.
- Ending the browser this way can lose the last second of typing. The page keeps each edit in the browser's local storage 150 ms after it is typed, but the browser writes local storage to disk in batches, five seconds apart by default. The window is started with `--enable-aggressive-domstorage-flushing`, which brings that to one second. An edit typed within that second before the browser ends is lost.
- A browser left running on the profile from an earlier session, after Burp was killed, cannot be tied to the app. Before opening a window, the extension checks the profile's lock file and asks the tester to close that window first. A browser that ends within three seconds of starting gave its window to one already running, so it does not stop the app either.
- The window's profile holds its unsaved edits, undo history, theme choice and cache. Deleting the release folder deletes it. Bring over does not move it, so unsaved edits stay behind with the old release.
- Unsaved edits that a tester's usual browser held before this change are not offered in the app window.
- The window's traffic stays out of Burp's Proxy history. Edge and Chrome send `127.0.0.1` traffic directly even when a system proxy is set.
- Ctrl+N in the app window still opens an ordinary browser window, with an address bar.
