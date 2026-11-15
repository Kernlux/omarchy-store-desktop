# Security review: Omarchy Store desktop 1.1.9 (2026-11-15)

Builds on 1.1.8 (SECURITY-REVIEW-1.1.8.md: plugins, screensavers and themes in one click) and earlier reviews.
1.1.8 was published on Codeberg and GitHub at 02:0x ET but never offered on omarchystore.com; 1.1.9 is the same code
plus the change below. One version, one tarball: 1.1.8 keeps its own sha256 (7565db3a…) and is superseded.

## Why
Luca, 15 Nov 01:4x: "the SECURITY CHECK must run before the install happens, every time, inside the app" — the same
live pre-install check as the GET sheet and the app page's Safety panel, before the button works; red blocks, amber
needs a second click, never skipped, never a green older than an hour, and the terminal says what was checked.
Before this, the check ran only on the app GET sheet (and its result did not gate the app's button: a check that could
not run still showed the command), and plugins, screensavers, themes and updates had no check at all, because
/api/preflight only knew catalog apps.

## What changed in the app
1. **No terminal without a finished check.** Every install, add-on and update message must carry `chk` =
   `{"v": "clear"|"caution", "at": <ISO time>, "c": ["<check>:<ok|warn>", ...]}`. `check_line()` accepts it only if the
   verdict allows installing (red "blocked" is refused here as well as on the page), the time is at most one hour old
   (and not more than 5 minutes in the future), there are 1-24 entries and every name is one of the 12 known check
   names. Otherwise `on_message` logs "no finished safety check", tells the user to wait for the check, and stops —
   before any lookup or terminal. `run_update` refuses without it too (the hidden native buttons cannot bypass it).
2. **The terminal states what was checked**, on its own line before "Press Enter": e.g. "Safety check at 01:52, all
   clear: source code ok, licence ok, store package SHA-256 ok, install scripts ok, nothing runs from the website ok".
   Built only from fixed words keyed by the check names plus the local HH:MM — no page text reaches the terminal.
3. The bridge helper passes the check along: `install(id, chk)`, `addon(kind, id, chk)`, `update(what, chk)`;
   `window.omarchyDesktop.checks = 1` tells the page this app enforces it.

## Backend and site (shipped with Site 8.19)
- `/api/preflight?plugin=<id>` and `?theme=<id>`: store packages are fetched from omarchystore.com and their SHA-256
  compared with the pinned one (small files) or their size confirmed (the 20 MB theme; the terminal checks its hash);
  marketplace plugins and GitHub themes: repository live (missing = red), archived (amber), licence, marketplace
  verdict (unverified = amber); built-in themes: nothing downloaded. Cached answers are served only under 45 minutes.
- Every install / update sheet in the app (app GET, screensaver, plugin, theme, Update all, one app's update, the
  store's own update, Omarchy & system) shows the live check; the button is disabled until it finishes; red blocks it
  with the reason; amber needs "I read the notes — continue"; an answer older than an hour is checked again first; a
  check that cannot run leaves the button disabled with "try again".

## What was checked
- Self-test: 107 checks pass (new: check accepted only when finished/non-red/under an hour/known names; 16 refused
  shapes — missing, red, stale, future, malformed time, empty, injected text, unknown name, fail status, notes on an
  all-clear, nested list, over-long, trailing newline; on_message refuses before page_update / page_addon / the
  terminal; run_update refuses; the line is printed before Enter).
- pytest tests/: 232 tests (231 passed, 1 skipped). New `tests/test_checks.py` drives the real `on_message` with a
  stand-in window: no check / red / stale / malformed -> no terminal; amber -> terminal with "notes read"; page text
  (`$(...)`, escape sequences, extra keys) never reaches the terminal line.
- Backend `test/preflight-addon.test.mjs`: 14 / 14 (hash match / mismatch, foreign URL, missing repo, archived,
  unverified, size mismatch, bad id). Live after deploy: screensaver and Omarchy Store theme "clear" with sha:ok.
- Site gate `tools/install_gate_check.py`: 50 / 50 — for each of 7 sheet types, slow / red / amber / green / error /
  stale, plus Omarchy & system.

## Unchanged
Navigation policy, 3-second input gate, update chains, read-only update check, add-on lines, NVIDIA launcher guard,
package file list. No hooks, services, timers or root.
