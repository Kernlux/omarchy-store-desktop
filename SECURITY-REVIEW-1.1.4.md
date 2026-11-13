# Security review — Omarchy Store desktop 1.1.4

Date: 2026-11-13 · Reviewer: Hermes (Kernlux Development Labs) · Gate: Kernlux software security gate.
Baseline: 1.1.3 (published release, sha256 d76d12d4…6860e).

## What changed (diff against the 1.1.3 release)
1. **Window control on Hyprland (`hypr_ask`, `hypr_window`).** Hyprland ignores a client's own maximize request, and a dock may
   park a window on a hidden special workspace (a second launch could not bring it back). The app opens ONE local AF_UNIX stream
   to the user's own compositor (`$XDG_RUNTIME_DIR/hypr/<signature>/.socket.sock`; signature checked against `[A-Za-z0-9_]{1,128}`;
   1 s timeout; reply capped at 4 MiB), reads the client list, keeps only the window whose pid is this process, checks the address
   (`0x[0-9a-f]{1,16}`) and workspace (`[0-9]{1,6}`), and sends one of four fixed requests: maximize toggle, minimize (to SnapDock's
   `special:sd4-minimized`), bring back to the current workspace, focus. Nothing from the page or the catalog reaches the compositor.
   Triggers: header buttons, a double-click on the header, a second launch. Not Hyprland: nothing is sent.
2. **Updates and Installed (read-only).** The app reads the pacman database the way `pacman -Q` / `pacman -Qu` do:
   `/var/lib/pacman/local/*/desc` and the gzip sync databases (bounded to 64 MiB each, parsed in memory with
   `tarfile.extractfile`, never extracted to disk), compares versions with a line-by-line port of libalpm's `vercmp`
   (tests compare it with `/usr/bin/vercmp`), and shows: the Omarchy Store app itself (from the catalog's `desktop_latest`,
   version `N.N.N` and 64-hex sha256 only; a catalog URL is ignored), store apps with a newer package, and "Omarchy & system".
   No process is started to check, no network beyond the usual catalog fetch from the store, no timer: it checks when the window
   opens and when the user presses Check for updates.
3. **Update commands.** Every update opens the user's own terminal through the same confirm-with-Enter script as installs. The
   line is built only by `update_chain` from fixed pieces and validated data, in a fixed order joined with `&&` (one failure stops
   the rest): store app (`mkdir -p ~/Downloads && cd ~/Downloads && curl -fLO https://omarchystore.com/downloads/<file> &&
   echo "<sha256>  <file>" | sha256sum -c && tar xf <file> && cd <dir> && ./install.sh`, then a note to reopen the app), store apps
   (`yay -S <names matching the pacman charset>`), Omarchy & system (`omarchy update`, then "Restart if it asks."). The checksum is
   verified before anything is unpacked; nothing runs as root from the app; nothing runs until Enter.
4. **App sidebar, dock actions.** A native sidebar (official lockup PNG shipped next to the program; all store categories, ids
   checked like app ids) loads store pages in the window. `com.omarchystore.Store.desktop` gains three Desktop Actions
   (`--updates`, `--update-all`, `--installed`); they only OPEN a view in the running app (a GApplication action with a fixed
   allow-list); nothing is run. StartupNotify, icons at 48/64/128/256/512.
5. **Robustness.** If the web process dies the window shows a plain "The page stopped" page with Reload instead of going blank.
6. **install.sh.** Prints "Updated X -> Y" (reads the installed VERSION line as text, never runs it), "Then run ./install.sh
   again." after the missing-packages line, installs the lockup and the extra icon sizes; uninstall removes exactly those files.

Not changed: the bridge contract, the terminal script, the navigation policy, the input gate, the catalog fetch, the NVIDIA
launcher guard (`WEBKIT_DISABLE_DMABUF_RENDERER=1`; an alternative, `WEBKIT_DISABLE_COMPOSITING_MODE=1`, scrolled faster but
blacked out the window on the test PC and was rejected). No install scriptlet, no hooks, no services, no timers, never root.

## Self-test changes
`socket` only inside `hypr_ask` (AF_UNIX stream); compositor requests only the two reads and the four fixed templates; the only
`curl` in the program is inside `update_command`, whose exact output is pinned; `update_chain` output pinned, malformed input
refused; `open()` only for the catalog cache and the two read-only pacman database paths; `gzip`/`io`/`tarfile` only inside
`repo_versions`, no `extract`/`extractall`; the one system path is `/var/lib/pacman`, used only as the readers' default.

## Results
- `--self-test`: **95 checks** · SELF-TEST OK
- Test suite: **175 tests** (174 passed, 1 skipped while the archive is being rebuilt)
- Real window on the test PC (RTX 5060 Ti, Hyprland, webkitgtk-6.0 2.54.1): installed from a clean HOME with the published box,
  10 minutes open, 0 new WebKitWebProcess core dumps; maximize, minimize and bring-back tested through the compositor.
