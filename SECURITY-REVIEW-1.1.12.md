# Security review: Omarchy Store desktop 1.1.12 (2026-11-16)

Builds on 1.1.11 (SECURITY-REVIEW-1.1.11.md) and earlier reviews.

## Why
Luca, 15 Nov 23:5x: he and a friend updated to 1.1.11, but the store kept saying "you have 1.1.9". The app is a
single-instance GApplication: the installer replaced the file, but the app that was already open (started at 10:00) kept
running the old code, and opening it again from the launcher only brought that old window back. The installer's "close it and
open it again" line was easy to miss.

## What changed
1. **The app notices its own update.** `installed_version()` reads the `VERSION = "x.y.z"` line of its own file on disk
   (`SELF_FILE`, the path it was started from; `open(path, "rb")`, first 64 KiB, strict pattern, "" on any error).
   `restart_pending()` is true only when that version is newer than the running code. Checked when the window opens and on
   every activation (a second launch, a dock action). Nothing runs in the background; no timer.
2. **One Restart bar.** `Adw.Banner` "Omarchy Store was updated to x.y.z. Restart to use it." with one button. The button
   only sets a flag and quits the app normally; after `app.run()` returns and the instance is disposed (its single-instance
   name released), `run_app` starts the same file once: `subprocess.Popen([sys.executable, '-I', SELF_FILE], start_new_session=True,
   stdin/stdout/stderr DEVNULL)` (`relaunch()`). Fixed argv, no shell, no env change, nothing from the page or the network.
3. **`omarchy-store-desktop --restart`** (the command install.sh prints): asks the running instance to quit through its own
   `quit` action (every version has it), waits up to 10 s until its D-Bus name is free (NameHasOwner), then `relaunch()`.
   Nothing is killed; if the app does not close, it says so and changes nothing.
4. **install.sh only looks:** `pgrep -u <uid> -f 'omarchy-store-desktop\.py'` (read-only process list). If an instance is
   open, it prints "Omarchy Store is still open and running the old version. Restart it now with: <launcher> --restart (or close
   it with Ctrl+Q and open it again)". It never stops a process (a test asserts there is no kill/pkill/killall).
5. **Bridge info** adds `installed` (the file's version) so the store page can say "restart" instead of "update" (Site 8.23).

The self-test's process rule now allows exactly three Popen sites, each word for word (terminal, read-only update query,
relaunch); relaunch may be called only from `run_app` (after Restart) and from `restart_running` (after the old instance
has quit). `os.exec*`, `os.kill` style calls and `Gio.Subprocess` stay forbidden.

## What was checked
- Self-test: 111 checks pass.
- pytest tests/: 257 tests (256 passed, 1 skipped). New `tests/test_restart.py`: version line read; missing / odd / injected
  version lines never offer a restart; newer file offers it, same or older does not; the bar text; Restart only flags and
  quits; the installer only looks and prints.
- Real run (test app id, GTK Broadway display, never the user's app): an instance started as 1.1.11, its file then changed to
  1.1.12, a second launch activated it, the `restart` action quit it and a NEW process started from the file (new pid);
  `--restart` against a running instance: "Omarchy Store restarted.", new pid. Both left no stray process after quit.

## Unchanged
Navigation rule, bridge contract (one read-only field added to info), input gate, safety check, terminal script, add-on
lines, update chains, read-only update check, NVIDIA launcher guard, package file list. No hooks, services, timers or root.
