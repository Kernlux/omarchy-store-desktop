# Security review: Omarchy Store desktop 1.1.14 (2026-11-16)

1.1.14 = 1.1.13 (downloads, see SECURITY-REVIEW-1.1.13.md) + **Pin to dock**. 1.1.13 was published on Codeberg/GitHub
before Luca approved Pin to dock for the same release; one version has one tarball, so the combined release is 1.1.14
and 1.1.13 never reaches omarchystore.com.

## Why
Luca, 16 Nov 18:4x–18:5x: a "Pin to dock…" action, user-triggered only, for SnapDock, the Omarchy dock and
nwg-dock-hyprland; several docks = a picker with Both; unknown docks (his friend's "Legal Desk") named "not supported yet"
with a copy-the-launcher-id fallback; a backup and Unpin; never the Hyprland config; adapters tested in a throwaway HOME.

## Design
- **Adapters (`DOCKS`)**: one entry per dock = how it runs (an argv element or program name), where its OWN pin list lives
  (XDG variable + default under the home folder + a fixed relative file), its own lock file if it has one, the id it stores
  for this app, and two pure functions (read the list, rewrite the list). A new dock (Legal Desk, once we know its file) is
  one entry plus a test. `DOCKS_UNSUPPORTED` names recognised docks we do not write.

  | Dock | Pin list | Id written | Format (verified against) |
  |---|---|---|---|
  | SnapDock | `~/.config/snapdock/settings.json` → `pins` | `com.omarchystore.store` | `json.dumps(indent=2)`; holds SnapDock's own `.lock` (flock), as its `sd-settings` does |
  | Omarchy dock | `~/.config/omarchy/shell.json` → `dock.pinned` (no own pins = Omarchy's defaults) | `com.omarchystore.Store` | `jq -S` layout, as `omarchy-dock pin` writes it |
  | nwg-dock-hyprland | `$XDG_CACHE_HOME/nwg-dock-pinned` (default `~/.cache`) | `com.omarchystore.Store` | one id per line, as its `savePinned()` (tools.go) writes it |

  Byte-for-byte check on this PC: the same starting files pinned by the docks' own tools (`omarchy-dock pin`,
  `sd-settings pin`, run with a throwaway HOME) and by 1.1.14 are identical (`cmp`).
- **Detection (read-only)**: `/proc/<pid>/cmdline` of the user's own processes only (uid match), at most 8192 processes and
  4 KB each, when the window opens and on every activation. Nothing is executed, nothing is watched.
- **Menu**: "Pin to dock…" exists only when a dock is found. One dock = one confirm line naming the dock and its file;
  two = "Which dock do you want to pin it to? [A] [B] [Both]" (a dock that already has it is greyed); three or more =
  checkboxes + All. Unpin from the same dialog. "Copy launcher id" puts `com.omarchystore.Store` and the .desktop path on the
  clipboard. About keeps the manual tip. First run: one toast tip if a supported dock runs without the pin (remembered by
  an empty file in ~/.config/omarchy-store).

## Write path (`dock_change` → `dock_write`)
1. **Path checks** (`dock_check_path`): the folder must exist, resolve (realpath) inside the home folder, belong to the user
   and not be the compositor config (`~/.config/hypr` is refused outright, and no adapter can point there: self-test); the
   pin list must not be a symlink (dotfiles setups are told to change it by hand), must be a regular file owned by the user
   and at most 1 MB. A relative or `..` XDG variable is ignored (default path used).
2. **The dock's own lock** (SnapDock): flock on its `.lock`, non-blocking, retried for 2 s; if the dock holds it, nothing
   is written ("saving its settings right now"). A symlinked lock is refused.
3. **Mid-write guard**: a pin list changed in the last second is refused (nwg-dock writes in place, without a temp file).
4. Read, parse with the adapter, compute the new list (only this app's entry added or removed; everything else in the
   file kept as parsed), render, and **parse the result back**: it must equal the intended list.
5. **Backup** of the original bytes next to it: `<file>.omarchy-store.bak` (same permissions).
6. **Concurrent edit guard**: the file's (mtime_ns, size, inode) are compared with step 3; if the dock wrote meanwhile,
   nothing is written.
7. **Atomic write**: temp file in the same folder, fsync, the original permissions (0600 when created), one rename.
   No root, no `sudo`, no subprocess, no compositor request, no new hook/service/timer/watcher.

## What was checked
- Self-test: 113 checks pass. New audit: writes only through `dock_write` (called only from `dock_change` and the tip
  marker); `fcntl` only in `dock_change`; four audited opens (cmdline, Omarchy defaults, the pin list, the lock for flock);
  no adapter path near `.config/hypr`; every adapter round-trips its own format; Legal Desk named, never written.
- pytest tests/: 281 (280 passed, 1 skipped). New `tests/test_docks.py` (20): exact diffs for each dock, backup content,
  0600 kept, no temp files left, unpin restores the original bytes, Omarchy defaults rule (user file with and without own
  pins), SnapDock never creates its settings, refusals: symlinked pin list, folder link out of home, XDG path outside home,
  SnapDock lock held, changed a moment ago, changed while we worked, garbage JSON; fake /proc detection; Legal Desk.
- Real window on Luca's PC (SnapDock + Omarchy dock running): menu shows "Pin to dock…"; the dialog is the picker with
  [SnapDock] (greyed: already pinned) [Omarchy dock] [Both]; with no dock the item is hidden; one dock = "Pin Omarchy Store
  to Omarchy dock?" + "Not supported yet: Legal Desk."; three docks = checkboxes + All. The probe replaced the writer, so
  nothing on Luca's PC was pinned or changed.

## Not done / limits
- Legal Desk: unknown file and format; only named when its process is called legal-desk/legaldesk/legal_desk. One entry
  once the friend sends (a) the pin file path, (b) a sample with one pinned app, (c) whether it reads ~/.local/share/applications.
- nwg-dock-hyprland reloads its pin list when it redraws (a window opens or closes); it is not installed here, so its
  adapter is tested on files only.

## Unchanged
Everything listed in SECURITY-REVIEW-1.1.13.md (navigation, bridge, input gate, safety check, terminal script, update
chains, Restart, NVIDIA guard, package file list).
