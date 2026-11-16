# Security model — Omarchy Store desktop 1.1.1

Reviewed line by line against the Kernlux software security gate on 2026-10-30 (1.1.0 baseline, 1.1.1 fixes). Full
findings with severities, fixes and the exact commands that were run: `SECURITY-REVIEW-1.1.1.md` (repository and
release tarball). This file is the short, honest summary.

## Runs as root: nothing
No sudo, pkexec, doas, polkit, setuid, sudoers, helper daemon, systemd unit, pacman hook or `.install` scriptlet
anywhere in the tree. `--self-test` audits the program's own syntax tree and compiled constants and fails if any of the
tokens `sudo pkexec doas run0 polkit NOPASSWD sudoers systemd systemctl setuid setgid` appears in a code string, bytes or
f-string of the app body; if any `shell=` keyword, `eval`/`exec`/`compile`/`getattr`/`__import__`, `os.system`/`exec*`/
`spawn*`/`fork`/`set*id`, `GLib.spawn_*`, `Gio.Subprocess`/`AppInfo`, ctypes or pty is referenced; if `socket` is used
anywhere but `hypr_ask` (1.1.4: one AF_UNIX stream to the user's own Hyprland, see below); if there is
more than one process launcher or more than one network request; if an import is aliased or outside the allow-list; or
if a fixed system path (`/bin /etc /usr /tmp /proc /home …`) appears. The no-hook / no-unit / no-scriptlet facts about
the *tree* are asserted by `tests/`. WebKit's own HTTP-authentication dialog is refused too (`authenticate` → cancel): a
401 from the store or a 407 from a proxy ends as a failed load, never as a password field inside this window.

## Executes
Two `subprocess.Popen` sites, both asserted word for word by the self-test.

**Read-only update check (1.1.7), in `read_only`:** one of three FIXED argument lists, nothing from the page or the
catalog: `checkupdates --nocolor` (pacman-contrib: downloads fresh package lists into its own temporary copy, never
writes the system's package database, needs no root), `yay -Qua` or `paru -Qua` (newer AUR versions of installed AUR
packages). No shell, no environment change, stdin closed, stderr dropped, output capped at 1 MiB and parsed line by line
against the package-name pattern; a tool that is missing or does not answer within 90 s is skipped. It runs when the
user presses Check for updates and once when the window opens (the same moment the 1.1.4 local check ran); there is no
timer, service or hook. It installs nothing: updates still start only from a button and Enter in the user's terminal.
Without checkupdates the app falls back to the local package lists and the Updates page says they may be old.

**Terminal, in `open_in_terminal`:** the user's terminal (`xdg-terminal-exec`, a hard dependency;
fallbacks ghostty/alacritty/kitty/gnome-terminal/konsole/xterm) running `bash -c` of a **fixed** script that prints
the command, waits for Enter, runs it, prints the exit code, waits again. Ctrl+C kills the script; EOF (Ctrl+D) at
the prompt prints "Cancelled." and exits 130 — a failing `read` can never fall through into the command (it could in
1.1.0). The command is built from the allow-list below, every word must match
`[A-Za-z0-9][A-Za-z0-9@._+-]{0,254}` (so no word can start with `-` and be read as a flag), and every word is
`shlex.quote`d. The title printed above it is stripped of control/escape characters so a bad catalog cannot redraw
the terminal to hide the command. If no terminal emulator is found, or the one found fails to start, the app says
which of the two happened and points at the command on the page; the launcher's own stderr reaches the app's log.

| catalog `install.method` | command | package-name rule |
|---|---|---|
| `pacman`, `omarchy` | `omarchy pkg add <pk…>` | `[a-z0-9][a-z0-9@._+-]{0,80}` — Arch's charset `^[a-z0-9@._+-]+$`, never a leading `-` or `.` |
| `aur` | `omarchy pkg aur add <pk…>` | same |
| `flatpak` | `flatpak install flathub <id…>` | `[A-Za-z0-9][A-Za-z0-9._-]{0,254}` |
| `release`, `store`, anything else | **refused** | — |

One invalid or repeated package name refuses the whole listing (no partial installs); more than 20 packages is refused; ids must
match `[a-z0-9][a-z0-9._+-]{0,63}` (`fullmatch`, so a trailing newline is refused too). Verified against Omarchy's
own source (basecamp/omarchy, master, 2026-10-30): `omarchy pkg add` routes to `omarchy-pkg-add`, which runs
`sudo pacman -S --noconfirm --needed -- "$@"`; `omarchy pkg aur add` routes to `omarchy-pkg-aur-add`, which runs
`yay -S --noconfirm --needed -- "$@"`. Both pass `--`, so even a flag-shaped name (which this app refuses anyway)
could not become an option. `sudo` asks for the user's password in the user's own terminal; this app never sees it.
The `omarchy` dispatcher (`bin/omarchy`) exists from **Omarchy v3.7.0**; v3.6.0 and earlier ship only `omarchy-pkg-add` /
`omarchy-pkg-aur-add` (checked against the upstream repository's history during this review) — there the printed
command fails with "command not found" and nothing is installed. Switching to the leaf scripts is a product decision
left to the owner.

## Network — every host, every purpose
- `STORE_HOSTS` = `omarchystore.com`, `www.omarchystore.com`: the only
  origins that may be the home page (`$OMARCHY_STORE_URL` is accepted only if it is an https URL on one of them),
  serve `catalog.json`, or talk to the app over the bridge.
- `WEBVIEW_HOSTS` = `STORE_HOSTS` + `omarchy-store-backend.omarchystore.workers.dev` (the store's API worker): what
  may load as a *document* in the **main frame**. Subframes may hold `STORE_HOSTS` documents only — the message handler
  is reachable from every frame, so the worker (which gets no bridge, no catalog and no home-page trust, and no injected
  helper script) is never allowed to be a frame inside a store page.
- `https://<store origin>/plugins.json` (1.1.8), right after catalog.json with the same rules (store-only redirects, 20 MiB,
  60 s), kept in memory only (never written), used only to look up a plugin or screensaver for `addon_line`.
- `https://<store origin>/catalog.json` once at start: TLS and hostname verified by Python's default context, 20 s
  timeout, **a redirect that leaves the store over https is refused before it is followed** (no other host is ever
  contacted), 20 MiB cap and a 60 s deadline for the whole download (read in single socket reads, so a slow drip
  cannot stall the clock), must parse as `{"apps": [...]}`, duplicate ids keep the first and are logged, written via `mkstemp` (random name, 0600) + atomic
  `os.replace`. Fetch failure is logged and the app keeps working with the previous copy (or none — then every
  Install is refused with "the catalog could not be fetched yet — press Reload"); Reload and Home retry the fetch
  (one at a time); a page load while the catalog is still empty retries automatically, at most once a minute. The catalog request's User-Agent is `OmarchyStore-desktop/<version>` and goes to the store host only; the WebView's
  User-Agent carries only the token `OmarchyStore` (the version reaches store pages via `__OMARCHY_DESKTOP__`).
- Subresources — images, fonts, scripts, and `fetch()`/XHR calls the storefront's own code makes to its API worker or
  elsewhere — are governed by WebKit and the storefront's CSP, not by this app's navigation policy, which decides
  which *documents* may render. `<a ping>` hyperlink auditing cannot be switched off in WebKitGTK API 6.0 (the setting
  is a deprecated no-op; 1.1.1 no longer calls it): such pings are click-initiated subresource requests, like any image
  the page loads. No telemetry: this program itself contacts only the store origin, for `catalog.json` and `plugins.json`.
- App updates (1.1.4): no automatic download and no background check. When the window opens, or when the user picks
  "Check for app update", the app reads `desktop_latest` from the catalog it already fetched; only `version`
  (`N.N.N`) and `sha256` (64 hex) are used, a catalog-given URL is ignored. If the version is newer, the header shows
  "Update to N.N.N". Pressing it opens the user's own terminal through the same confirm-with-Enter script as installs,
  showing one line: `mkdir -p ~/Downloads && cd ~/Downloads && curl -fLO https://omarchystore.com/downloads/<file> &&
  echo "<sha256>  <file>" | sha256sum -c && tar xf <file> && cd <dir> && ./install.sh`. The checksum is checked before
  anything is unpacked; install.sh runs as the user and never uses root. Nothing happens until the user presses Enter.
- Window control on Hyprland (1.1.4): `hypr_ask` talks to `$XDG_RUNTIME_DIR/hypr/<signature>/.socket.sock` (the
  user's own compositor), reads the client list, and sends only four fixed requests about the window whose pid is this
  process (maximize toggle, minimize to SnapDock's hidden workspace, bring back, focus); address and workspace are
  pattern-checked first. Nothing from the page or the catalog reaches the compositor.
- Proxies: Python and WebKit honour the session's proxy environment; an authenticating proxy (407) is a failed load,
  never a password prompt.

## Page → app surface
One `webkit.messageHandlers.store` channel. The helper `window.omarchyDesktop` is injected only on `STORE_HOSTS`
pages (user-script allow-list), top frame only. A message is dropped unless **all** of: the **committed** document's URL
is a `STORE_HOSTS` URL (not the view's active URL, which already names a pending navigation while the previous document
still runs — nothing may use the bridge before the first commit); the value is a string of ≤ 4096 chars that parses as a JSON object; it is
`{"t":"install","id":<id matching ID_RE>}`, `{"t":"addon","kind":"plugin"|"theme","id":<id matching ID_RE>}` (1.1.8), `{"t":"update",…}` (1.1.6) or `{"t":"open","url":<plain https URL with a host, no userinfo, no
whitespace or control characters, ≤ 2048 chars>}`; **and GTK itself saw a click/tap, or an Enter key press, on the
view within the last 3 s — each press pays for exactly one action (one terminal, or one browser window, also for
ordinary outside links), and the press dies the moment a new document commits in the window**, so the page a click
leads to inherits nothing (a redirect the click caused may still open in the browser, once). Typing never arms the
bridge (only Enter counts among keys; a held key repeats into one token, not many), and the terminal script discards
any typed-ahead input before it asks for Enter, so a terminal that appears while you type cannot be confirmed by
accident. Residual, accepted: Enter pressed in a store search box arms one action for 3 s. A page therefore cannot open a terminal or the browser on
its own, in a loop, or at load time (the review's attack page: 3 terminals + 5 browser windows in 1.1.0, nothing in
1.1.1). The page never supplies a command, package name or flag.

**Downloads (1.1.13).** The app never saves a file: every download is cancelled at once. On a real click, an https file
address is handed to your browser instead, which downloads it there. See SECURITY-REVIEW-1.1.13.md.

**Restart after an update (1.1.12).** The app reads the VERSION line of its own file (read-only, 64 KiB); when the file is
newer than the running code it shows one Restart button, which quits the app and starts the same file once (fixed argv).
`--restart` asks a running instance to quit through its own quit action, then starts it again; install.sh only looks
(pgrep) and prints that command. Nothing is killed. See SECURITY-REVIEW-1.1.12.md.

**No partial upgrades (1.1.11).** A store app from the Arch / Omarchy repositories is never updated on its own: its button
runs the full Omarchy & system update (`omarchy update`) after a line saying why. `yay -S` only ever gets AUR packages.
No command contains `-Sy`. See SECURITY-REVIEW-1.1.11.md.

**Outside links (1.1.10).** Only a link the user clicked (navigation type LINK_CLICKED, a user gesture, not a redirect,
not aimed at a named frame) is handed to the browser. A frame loading — e.g. the Cloudflare "I'm human" iframe right after
a click, which 1.1.9 opened as a blank browser tab —, a redirect, a script or a form is dropped silently. See
SECURITY-REVIEW-1.1.10.md.

**The safety check first (1.1.9).** Every install, add-on and update message must carry the result of the store's
live check (`chk`: verdict clear or caution, its time, the check names). The app refuses red, anything older than an
hour, unknown check names or no check at all, before any lookup or terminal; the terminal prints what was checked
(fixed words only) on its own line before it asks for Enter. See SECURITY-REVIEW-1.1.9.md.

**Plugins, screensavers and themes (1.1.8).** `addon` carries only a kind and an id. The id is looked up in the app's own
copy of the store's lists (`themes` in catalog.json, `plugins` in plugins.json) and `addon_line` builds the one line from
that entry, every piece against a strict pattern, else refuses: a store-hosted package is `cd /tmp && curl -fLO
https://omarchystore.com/theme-packages/<name>.tar.gz && echo "<pinned sha256>  <name>.tar.gz" | sha256sum -c - &&
mkdir -p ~/.config/omarchy/<plugins|themes> && tar -xzf <name>.tar.gz -C <that folder> && omarchy plugin enable <dir>` /
`omarchy-theme-set <name>` (fixed origin, path `/theme-packages/[a-z0-9][a-z0-9._-]*.tar.gz`, 64 lower-case hex, the hash
is checked BEFORE anything is unpacked); a marketplace plugin is `omarchy plugin add https://github.com/<owner>/<repo>.git
--enable`; a theme is `omarchy-theme-set <name>` (built in) or `omarchy-theme-install https://github.com/<owner>/<repo>`.
Owner/repo/name/dir must be plain names (no `/`, `..`, spaces, quotes, `$`, `;`, leading `-`). It is the same line the
store page shows, and it goes through the same terminal script, input gate and Enter confirmation as an app install. The
app itself never downloads or saves the package; the user's own shell does, after Enter.

## WebKit hardening
- Navigation policy: documents only from `WEBVIEW_HOSTS` over https (no userinfo, port 443 only), plus
  `about:blank` / `about:srcdoc` frames and `blob:` documents of those origins — in the main frame **and** in
  subframes, so no third-party document ever renders here. Other URLs: opened in the system browser if the user
  clicked (`is_user_gesture`), otherwise dropped (hidden iframes, redirects, scripts, meta refresh, `form.submit()`).
  A main-frame response from elsewhere is refused even if it slipped past.
- Downloads: **every** WebKit download is cancelled (`download-started` → cancel, with a toast saying so) — this app never writes a
  downloaded file (1.1.0 relied on WebKit's default, which saves `Content-Disposition: attachment` responses under
  `~/Downloads`, or into `$HOME` itself when that folder does not exist — reproduced). A response that is not
  displayable, or is served as an attachment, is handed to the browser only when it is the first response after a
  navigation the user started (`is_user_gesture`) and that click has not been spent on anything else; one a page starts
  by itself is simply dropped.
- `window.open`/`target=_blank`: never creates a second WebView; store URLs load in place; a blank popup opens
  nowhere (in 1.1.0 it replaced the page with `about:blank`); outside URLs go to the browser on a click.
  `javascript-can-open-windows-automatically` off.
- No password dialog (`authenticate` → cancel), no `prompt()` (swallowed; `alert`/`confirm` keep WebKit's plain
  dialogs), no file chooser (`run-file-chooser` → cancel), no fullscreen, no WebGL, no WebRTC, no autoplay; developer
  extras off, media stream off, file-URL access off, top navigation to `data:` off,
  TLS errors policy FAIL (never a "continue anyway" prompt), HTTP credential storage off, third-party cookies refused.
  Active mixed content is blocked by WebKit (passive `http:` images could still load if the storefront referenced any).
- The app's own policy decisions (a link handed to the browser, a download) are recognised by error domain and code
  and never replace the page with the error page (1.1.0 matched the text "cancel" and showed "Can't reach the store"
  after every download or off-site redirect). The error page is loaded with `load_alternate_html`, so Reload retries
  the real URL.
- The web and network processes run in WebKitGTK's bubblewrap sandbox (always on in API 6.0; the app never calls
  `add_path_to_sandbox`).
- Toasts render catalog text with markup disabled; terminal titles are stripped to `[A-Za-z0-9 ._+()-]`, ≤ 60 chars.

## Files written (all under `$HOME`)
`~/.config/omarchy-store/` (0700): `web/` (site data: localStorage, IndexedDB, HSTS, media keys) and
`cookies.sqlite`. `~/.cache/omarchy-store/` (0700): `catalog.json` (0600) and `web/` (HTTP cache). 1.1.0 had the two
`web/` directories swapped (site data in the cache, HTTP cache in the config). WebKitGTK, GStreamer, Mesa and GTK keep
their own caches under `~/.cache` and GTK keeps dconf's runtime file under `$XDG_RUNTIME_DIR`; on a headless box without
`XDG_RUNTIME_DIR`, GLib itself creates `~/.cache` — that is the only thing `--self-test` touches. A full `strace` of a
session is summarised in the review (§5.7). `install.sh`: `~/.local/share/omarchy-store/omarchy-store-desktop.py`,
`~/.local/bin/omarchy-store-desktop`, the `.desktop` entry (its `Exec=` points at that launcher by absolute path, so
the menu entry works even when `~/.local/bin` is not on the session's `PATH`) and the 512 px icon under
`~/.local/share`; `--uninstall` removes those four files by name, plus `mimeinfo.cache` when ours was the only menu
entry (never `rm -rf` of a directory derived from an environment variable). Rule 4 as worded governs the running app; the installer's launcher, menu entry, icon and the
two desktop caches are the only additions, all under `~/.local`. The `--snapshot <file>` QA flag (command line only,
never reachable from the menu entry or from web content) writes the PNG you name. `private_dir` follows a symlink
placed at the state directory by the user themselves (accepted: it is their home). The package: files under
`/usr/bin` and `/usr/share/{omarchy-store-desktop,applications,icons,licenses,doc}` only.

## Packaging
`install.sh`: refuses to run as root, checks dependencies with `pacman -T` (providers accepted) and prints the install
command instead of running it, no network; `--uninstall` also removes the `mimeinfo.cache` it caused when ours was the
only menu entry. Installing the package makes pacman run the distribution's generic desktop-database and icon-cache
hooks (owned by desktop-file-utils / gtk-update-icon-cache), as for any app with a menu entry; this package ships none. `pkg/PKGBUILD`: `depends` from the official repos only, `check()` runs `--self-test`,
`package()` is six `install` lines, no `install=` scriptlet, no hooks. Built in this review with makepkg 7.1 on Arch
and makepkg 6.0.2 on Ubuntu (identical file lists); `pacman -Qi` reports `Install Script : No`; `pacman -R` leaves
nothing behind.

## Verify it yourself
`python3 -I omarchy-store-desktop.py --self-test` (112 checks, no display, no network: the command allow-list,
the URL and message validation, the terminal script, and a static audit of this file — every name, call, import,
string, bytes and f-string in the app body) and `python3 -m pytest tests/` (261 tests, `python-pytest` is a
development tool, not a runtime dependency; they include negative tests that plant known audit evasions in a copy of
the file and require the self-test to fail). The packaging and no-hook facts are asserted by the tests, not by the
self-test.

## Not checked / known limits — say so plainly
- The live hosts were unreachable from the review sandbox (network policy), so every WebKit behaviour above was
  exercised against a local HTTPS fixture that mimics the storefront's bridge contract
  (`.actions [data-get]` → `[data-desktop-install]` → `omarchyDesktop.install(id)`); the storefront's own JavaScript
  was not re-reviewed here. If the website were compromised, the attacker still could not run a command through this
  app, but could show a wrong app name next to a legitimate install command — which is why the terminal prints the
  real command and waits.
- In the review VM the web-process sandbox could not start while a D-Bus session bus was set (`xdg-dbus-proxy`); the
  app was run with the sandbox on and no session bus. A real desktop has both.
- The storefront's `omarchy` install method is treated as a plain repo install (its schema was not readable from the
  review sandbox). A real `omarchy pkg add` run was not possible here (not an Omarchy system).
- Terminals: xterm was exercised end to end through `xdg-terminal-exec`; `xterm -e`, `kitty` and `alacritty -e` were
  started through the fallback list and ran the script; ghostty, gnome-terminal and konsole were not run. Flatpak
  listings: self-test and unit tests only (the catalog has none).
- The 4096-byte message cap is a parse bound: the string has already crossed IPC into the UI process; the
  one-action-per-input rule is what bounds abuse. URLs longer than 2048 characters are treated as outside URLs.
- Upstream WebKitGTK, GTK and libadwaita vulnerabilities; the `omarchy pkg` / `flatpak` tools themselves; `namcap`
  (no Arch mirror was reachable to install it).
