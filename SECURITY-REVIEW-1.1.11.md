# Security review: Omarchy Store desktop 1.1.11 (2026-11-15)

Builds on 1.1.10 (SECURITY-REVIEW-1.1.10.md) and earlier reviews.

## Why
Luca, 15 Nov 13:3x (screenshot, 1.1.9): Updates badge 7, Apps 6, "Omarchy & system" 7 — the six store apps were listed in
both groups. Review of the update buttons for the same screen found a stability problem: a store app from the Arch
repositories (yt-dlp, from extra) got `yay -S yt-dlp`. Updating one repository package on its own is a partial upgrade:
with package lists newer than the rest of the system it can pull a library other programs were not built against; with old
lists it changes nothing. Arch's rule is the full upgrade.

## What changed
1. **A repository app is never updated on its own.** Its button runs the same chain as "Update Omarchy & system"
   (`omarchy update`, which is Omarchy's full update), preceded by a fixed line in the terminal: "This app comes from the
   Arch / Omarchy repositories. Updating it on its own can break other programs (a partial upgrade), so the full Omarchy &
   system update runs; it updates this app too." New step shape `("system", "repo")` in `update_chain`; any other second
   element is refused.
2. **Update all:** store app first (unchanged), then `yay -S` with the store apps' **AUR** packages only, then Omarchy &
   system last (unchanged). A repository package is never given to yay -S.
3. **AUR apps** keep `yay -S <their packages>` (the AUR helper builds the package against the current system).
4. Which is which comes from the read-only update check: packages in the `checkupdates` answer are repository packages,
   those in `yay/paru -Qua` are AUR. Nothing from the page decides it; the page still sends only `app:<catalog id>`.
5. `info()` (the read-only answer for the store's Updates page) adds, per app, `pkgs` (its packages with an update) and
   `repo` (true when any is a repository package), so the page lists each package once and labels the button.
6. No command ever contains `-Sy` (refresh without upgrade) or a refresh flag; checked by the self-test and tests.

Not touched: the user's own systemd units or drop-ins (e.g. Voxtype's); the app never starts, stops or edits services.

## Site side (Site 8.20)
Apps lists the store apps (6); "Omarchy & system" lists every other package (here mise-bin, 1), so 6 + 1 = the badge 7.
A repository app's button reads "Update with system" and says why; the system group says "Also updates the 6 apps listed
above". For apps older than 1.1.11 the page itself sends `system` for a repository app's button, so they get no partial
upgrade either. Gate `v8/tools/updates_groups_check.py` (Luca's exact list, as 1.1.9 and as 1.1.11 send it, desktop + phone).

## What was checked
- Self-test: 110 checks pass (new: the repository chain shows the reason before `omarchy update`, contains no yay;
  `page_update` gives yay only AUR packages and sends a repository app to the system chain; no `-Sy` anywhere).
- pytest tests/: 250 tests (249 passed, 1 skipped). New `tests/test_partial.py` drives the real `page_update` / `info`
  with Luca's list: yt-dlp -> full system update with the reason first; cliamp -> `yay -S cliamp`; Update all -> yay gets the
  five AUR apps only, system last; no command contains a refresh; badge 7, yt-dlp marked repo.

## Unchanged
Navigation rule, bridge, input gate, safety check, terminal script, add-on lines, read-only update check, NVIDIA launcher
guard, package file list. No hooks, services, timers or root.
