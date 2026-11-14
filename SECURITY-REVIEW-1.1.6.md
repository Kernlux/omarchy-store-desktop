# Security review: Omarchy Store desktop 1.1.6 (2026-11-13)

Builds on 1.1.5 and 1.1.4 (SECURITY-REVIEW-1.1.4.md still describes everything not listed here).

## What changed
1. **No native sidebar.** The window shows the store's own page sidebar only (Luca's approved design). Updates and
   Installed are now the store's own pages (`/updates/`, `/installed/`). The header (back, forward, home, reload, the
   Updates badge, menu, minimize, maximize, close) is unchanged. Dock actions (Updates / Update all / Installed) open
   those pages.
2. **One read-only question for the page:** `storeinfo` (WebKit script message *with reply*). Accepted only from a
   committed store document (`is_store_url`), only a string of at most 64 characters, only `{"t":"info"}` or
   `{"t":"check"}`. It returns plain JSON: the app version, the time of the last check, counts, and names/versions of
   store apps and pending packages from the local package database (bounded lists). It cannot start a process.
   `check` re-runs the same read-only local check as the Check for updates button.
3. **One new action message:** `{"t":"update","what":...}` on the existing `store` handler, `what` limited to
   `all`, `store`, `system` or `app:<catalog id>` (ID_RE). It goes through the existing checks (committed store
   document + a real GTK click or Enter within 3 s) and then builds the SAME fixed chains as the 1.1.4 Updates view
   (`update_chain`: store self-update with pinned sha256, `yay -S` with validated names, `omarchy update`). The page
   never supplies a command, a package name or a URL: only which of those buttons was pressed.
4. Category labels keep "&" (from 1.1.5).

## What was checked
- Self-test: 98 checks pass (new: update message parsed; bad update messages refused).
- pytest tests/: 175 tests (174 passed, 1 skipped).
- Real window, local copy of the site: the page sidebar shows Updates and Installed (76) under Top Charts; the Updates
  page shows the local result; pressing "Update Omarchy & system" opened the terminal step with exactly
  `omarchy update && printf '\n  Restart if it asks.\n'`.

## Unchanged
Navigation policy, 3-second input gate, terminal script, NVIDIA launcher guard, package file list. No install hooks,
no background service, no timer, no root, no new network host, no evaluate_javascript in the app body.
