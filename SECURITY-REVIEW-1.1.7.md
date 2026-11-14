# Security review: Omarchy Store desktop 1.1.7 (2026-11-14)

Builds on 1.1.6 (SECURITY-REVIEW-1.1.6.md and SECURITY-REVIEW-1.1.4.md still describe everything not listed here).

## Why
Luca, 14 Nov: "are you sure updates works?" Seven updates were waiting (`checkupdates`), the Updates page showed none.
1.1.4-1.1.6 compared the installed packages with the LOCAL sync databases, which are only as new as the user's last
`pacman -Sy` (on Omarchy usually days old), so the answer was a silent "up to date".

## What changed
1. **A read-only update query (`read_only`).** Exactly three fixed argument lists, chosen by a literal key, nothing from
   the page, the catalog or the network:
   - `checkupdates --nocolor` (pacman-contrib) — downloads fresh package lists into its own temporary database copy,
     never writes `/var/lib/pacman`, needs no root. Exit 0 = list, 2 = nothing to update, anything else = not used.
   - `yay -Qua`, else `paru -Qua` — newer AUR versions of installed AUR packages (a read-only query of the AUR).
   `subprocess.Popen` with the absolute path from `shutil.which`, no shell, no `env=`, no `preexec_fn`, stdin
   `/dev/null`, stderr dropped, `start_new_session=True`, 90 s timeout (the process is killed after it), output capped
   at 1 MiB and parsed line by line: only `name old -> new` lines whose name matches the package-name pattern are kept.
   AUR lines are kept only for packages installed on the computer.
2. **When it runs:** when the user presses Check for updates (button, page, dock action) and once when the window opens,
   the same moments the local check ran before. No timer, service, hook or background loop. It installs nothing:
   updates still start only from a button and Enter in the user's own terminal (unchanged chains).
3. **Honest fallback:** without checkupdates (or when it fails) the local lists are read as before and the page is told
   `source: "local"`; the Updates page then says the lists may be old instead of "up to date".
4. **`storeinfo` reply** gains `source`, `aur` (count + bounded list), `omarchy` (installed version and pending
   upgrade) and a longer bounded system list (60). Still plain JSON, still unable to start anything.
5. The sidebar count is the same number the page shows (system + AUR + the store's own update).

## What was checked
- Self-test: 99 checks pass. The Popen rule now requires exactly two sites, each word for word: the terminal one in
  `open_in_terminal` and the read-only one in `read_only`; `READ_ONLY` must equal the three fixed lists; every
  `read_only(...)` call passes a literal key; the parser refuses injected names (`btop;id`, `-x`).
- pytest tests/: 189 tests (188 passed, 1 skipped). New `tests/test_updates.py`: a fake pacman root with STALE sync
  lists proves 1.1.6's answer was empty and 1.1.7 takes checkupdates' fresh answer; exit 2 is a real zero; missing or
  failing checkupdates is reported as "local"; AUR via yay, then paru; parser refusals; the real checkupdates on this
  machine runs without root and every line parses.
- Real window on this PC (headless output, test app id, local copy of the site): sidebar "Updates 7", the page lists
  the 7 pending packages (cliamp, gliff, herdr, mise-bin, owe, voxtype-bin, yt-dlp; six of them are store apps), "Checked
  at" time shown, Spanish fully translated after switching the language. No update was run.
- No new import, no new network code in the app body, no root, no writes outside the app's own cache.

## Unchanged
Navigation policy, 3-second input gate, terminal script, update chains, NVIDIA launcher guard, package file list. No
install hooks, no services, no timers, nothing runs as root.
