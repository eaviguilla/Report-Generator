---
status: accepted
---

# The Burp build opens the app window in Edge or Chrome

From: [The Burp build opens the app window](../plans/burp-app-window.md)

Replaces the "Browser" choice in [Host the app from a Burp Suite extension](../plans/burp-extension-launcher.md), which opened the system default browser.

When the Burp tab starts the app, it opens the app window in Edge, or in Chrome when Edge is missing. The extension starts that browser itself, with no address bar and with a browser folder of its own in the release folder, which it empties before each new window and deletes when the window closes. It never uses Burp's browser and never falls back to the default browser. If neither Edge nor Chrome is installed, nothing opens, and the tab names the browsers it looked for.

Amended 2026-10-03: the browser folder was first kept between sessions. It is now thrown away, so the window never carries an account, history or data from one session to the next.

Amended 2026-10-23: an empty folder did not stop Edge signing in. The app window showed "we are now syncing your browsing data across all your devices", because Edge signs a new browser folder in to the Windows account when that account is a Microsoft or work account. The window now starts with `--disable-sync` and `--disable-features=msEdgeSyncService,msEdgeAccountSSO`. Chrome gets the same flags and ignores the two Edge feature names.

Amended 2026-10-26: the tab never shows the address, in any state, so that nothing in it hints that a web app is running. When no window can open (off Windows, or with neither browser), the tab says so and no longer tells the tester where the app is.

## Considered options

- **Burp's browser.** It ships with Burp, so every machine running the extension has it. Rejected because, started outside Burp on Windows, it cannot start its sandbox ("Sandbox cannot access executable … Access is denied"), its network service crashes, and the window comes up blank. repgen-web's Burp launcher hit this and dropped it. The workarounds either turn off part of the sandbox, in a window that displays proof-of-concept payloads, or change permissions inside Burp's install.
- **The system default browser**, the launcher plan's choice. Rejected because it shows an address bar and tabs, and the app becomes one more tab in the tester's own browser.
- **The default browser as a last resort**, as repgen-web does when it finds neither Edge nor Chrome. Rejected because the address bar is what this decision removes. Edge ships with Windows 10 and 11, so a Windows machine reaches that case only when Edge was removed and Chrome was never installed.

## Consequences

- The app window opens only on Windows, where the Burp build runs. Anywhere else the tab opens nothing and says so.
- The window and the app stop together. When the server ends, whether by Stop, Force stop or a crash, the extension ends the browser it started without asking it first. Unloading the extension ends it at once, since nothing watches the server after that. When that browser exits, the extension stops the app as if Stop were pressed. A polite close was rejected because it needs a Windows-only way to close another program's window and makes Stop wait on a "Leave site?" answer.
- Ending the browser discards what the page kept in it: an edit typed in the seconds before, if it had not reached the app yet, undo history and the theme choice. Reports themselves are saved by the app in the data folder and are unaffected.
- A browser left running on the browser folder from an earlier session, after Burp was killed, cannot be tied to the app. Before opening a window, the extension checks the folder's lock file and asks the tester to close that window first. A browser that ends within three seconds of starting gave its window to one already running, so it does not stop the app either.
- The browser folder holds nothing between sessions: no account sign-in, sync, imported browser data, cookies, cache or unsaved edits. Two cases leave files until the next window starts, which empties the folder first: Burp killed while the window is open, and a browser helper process still holding a file after five tries a second apart.
- Sync and account sign-in are off through those launch flags, not through a setting in the folder. Microsoft does not document the two feature names, so a later Edge version may stop respecting them, and a policy that forces sign-in or sync on a managed machine may override them. If the notice returns, look here first.
- Unsaved edits that a tester's usual browser held before this change are not offered in the app window.
- The window's traffic stays out of Burp's Proxy history. Edge and Chrome send `127.0.0.1` traffic directly even when a system proxy is set.
- Ctrl+N in the app window still opens an ordinary browser window, with an address bar.
