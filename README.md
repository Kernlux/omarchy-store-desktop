# Omarchy Store — desktop app

<!-- SECURITY-RULES:BEGIN — keep this block at the top of every README/CONTRIBUTING in the Omarchy Store projects -->
## SECURITY RULES (read before you change anything)

**The goal, in the owner's words:** *"the SAFEST POSSIBLE APP where nobody can poke a hole in it."* This rule outranks features, speed and polish. It covers the Omarchy Store website, its backend worker and Pages Functions, the desktop app, the `/downloads` allow-list, the contact form and inbox, the nightly publish, and every deploy.

There must never be hooks or security vulnerabilities in anything we ship. The store was publicly attacked over an update hook that ran `sudo` in the background, and a paid deep security review (desktop 1.1.1: 5 real holes fixed and about 30 hardening items) can be undone by one careless change.

**Every change, no exceptions:**

1. **Think like the attacker first.** For every input, ask who can write it and what happens if it is hostile. Inputs include settings files, catalog data and app names, window titles, the clipboard, helper/AI text, voice text, anything in `~/.config` or `~/.local/state`, contact-form fields, and anything from the network. All of it is untrusted **data**. It never goes into a shell string, `eval`, `bash -c`, `innerHTML` unescaped, a URL we open without validation, or a path we haven't canonicalised.
2. **Least privilege.** Everything runs at user level. None of the following, ever:
   - `sudo`, `pkexec`, NOPASSWD, a root helper or setuid;
   - systemd/pacman/post-install hooks, remote code or auto-update;
   - a listener on `0.0.0.0` (use 127.0.0.1 or an authenticated 0600 unix socket);
   - an unverified download (it needs a signature or a pinned checksum);
   - secrets in code, logs or screenshots.

   Files are private (0600/0700), writes are atomic, and symlinks are refused.
3. **Smallest surface.** Every feature adds attack surface; do it with fewer permissions, fewer processes and no network if possible. Anything that talks to a network is **off by default**, opt-in, documented, and shows what leaves the machine. When in doubt, leave it out.
4. **Verify, don't assume.** On every change:
   - run the software-security gate;
   - fuzz the inputs and try to break it yourself;
   - record the result in `SECURITY-REVIEW-<version>.md`: PASS/FAIL per check and an honest **NOT CHECKED** list.

   Never claim "no vulnerabilities"; say what was reviewed and what was not.
5. **No last-minute additions.** Nothing is added after a build passed review without re-running the gate on the final diff. Freeze, review, tag.
6. **If a feature conflicts with safety, safety wins.** Stop, explain the risk in plain words, and propose a safer way. Cut the feature before weakening security.

**Website specifics (enforced by `v8/deploy.sh`):**
- **Content-Security-Policy:** `script-src` has no `'unsafe-inline'`, and the site ships no inline `<script>`, no `on…=` handler and no `javascript:` URL (`tools/csp_check.py`).
- **Hostile catalog data never executes** (`tools/redteam_catalog.py`).
- **`/downloads/` serves only the reviewed release** (`tools/desktop_release.py`, the Pages Function allow-list).
- **The contact endpoint** is rate-limited and size-capped, stores text only, and never echoes input or internal errors (`tools/redteam_backend.py`).
- **The desktop app** loads only the store's own hosts (83-check `--self-test`).
<!-- SECURITY-RULES:END -->


A native window for [omarchystore.com](https://omarchystore.com) on Omarchy Linux. GTK 4 + libadwaita +
WebKitGTK 6, **one readable Python file** (`omarchy-store-desktop.py`), no build step, no bundled browser
engine, no npm. MIT.

Source: <https://codeberg.org/kernlux/omarchy-store-desktop> (mirror: <https://github.com/Kernlux/omarchy-store-desktop>)

## What it does
- Shows the live store — the same catalog and safety checks as the website. The install command comes from the
  app's own copy of the catalog, fetched when it starts (and on Reload while it is still empty).
- **Install** on an app's safety panel opens **your own terminal** with the exact command printed. Nothing
  runs until you press Enter; your package manager asks for your password there, in your terminal.
- Links that leave the store open in your normal browser.

## What it never does — the no-hook promise, in plain words
- **Never runs as root, never asks for a password.** No `sudo`, no `pkexec`, no polkit rule, no helper service, no
  setuid anything — and WebKit's own password dialog is switched off. The app cannot install software; it can only
  ask *you* to, in a terminal you can read first. Enter runs the command; Ctrl+C or Ctrl+D cancels it.
- **No hooks of any kind.** No pacman hook, no `.install` scriptlet, no systemd unit, no timer, no
  autostart entry, no background process. When the window is closed, nothing of it is running.
- **No auto-update, no remote code.** It fetches `catalog.json` (data, over TLS, from the store origin)
  and nothing else. It never downloads a script or a package, and never pipes a download into a shell.
- **The web page cannot run commands.** It can only say *install `<id>`* or *open `<https url>`*, and only right
  after you clicked or pressed a key — never on its own, in a loop, or at load time. The app looks the id up in
  **its own** copy of the catalog and builds the command from a fixed allow-list (`omarchy pkg add`,
  `omarchy pkg aur add`, `flatpak install flathub`). Anything else — a self-hosted binary, an unknown method, a
  package name with a stray character — is refused with a message.
- **Never saves a file.** Every download WebKit might start is cancelled; a download link you click is handed to
  your browser.
- **Writes only to `~/.config/omarchy-store` and `~/.cache/omarchy-store`** (plus GTK's and WebKit's own caches under
  `~/.cache`). Nothing outside your home; the user-space installer adds a launcher, a menu entry and an icon under `~/.local`.
- **No telemetry.** The program itself contacts only the store origin (for `catalog.json`); only the store and its API worker may ever load inside the window.

The command allow-list, the URL and message validation and the terminal script are asserted by `--self-test`, which
also audits the program's own syntax tree and fails if a shell, `eval`, `getattr`, `sudo`, `pkexec`, a second process
launcher or a fixed system path ever appears in the app body; the no-hook and packaging facts are asserted by `tests/`.

## Install

### From the package (makepkg)
Until the GitHub organisation is live again, `pkg/PKGBUILD` builds from the release tarball placed next to it
(the `source=` URL for the AUR is in the file, commented out; `pkg/.SRCINFO` is generated from it):
```bash
sha256sum -c omarchy-store-desktop-1.1.2.tar.gz.sha256      # verify the download first
cp omarchy-store-desktop-1.1.2.tar.gz pkg/ && cd pkg
makepkg -si          # builds the package (running --self-test in check()), then pacman installs it
```
`makepkg -si` is pacman asking for *your* password in *your* terminal to install a package you just built
from source you can read. The package contains files only — no install scriptlet, no hooks of its own (pacman will
run the distribution's generic desktop-database and icon-cache hooks, as for any app with a menu entry).

### From the release tarball (user space, no root at all)
```bash
sha256sum -c omarchy-store-desktop-1.1.2.tar.gz.sha256      # verify the download first
tar xf omarchy-store-desktop-1.1.2.tar.gz && cd omarchy-store-desktop-1.1.1
./install.sh                                               # copies to ~/.local, adds a launcher entry
```
Needs `gtk4 libadwaita webkitgtk-6.0 python-gobject xdg-terminal-exec hicolor-icon-theme` — all in the official
Arch repos (`webkitgtk-6.0` is not part of a stock Omarchy and `flatpak` is only needed for Flatpak listings). The
script only *checks* for them (`pacman -T`): if one is missing it prints the pacman command and stops. It never runs it for you. It writes four files under `~/.local` (the app,
a launcher in `~/.local/bin`, the menu entry — pointing at that launcher by absolute path — and the icon).

The `pkg/PKGBUILD` inside the tarball carries `sha256sums=('SKIP')` because a file cannot contain the hash
of the archive it travels in; the PKGBUILD in the repository and on the AUR pins the real sum.

## Uninstall
```bash
./install.sh --uninstall       # tarball install: removes exactly the files it installed
sudo pacman -R omarchy-store-desktop   # package install
```
Both leave `~/.config/omarchy-store` and `~/.cache/omarchy-store` for you to delete if you like.

## Verify it yourself
```bash
python3 -I omarchy-store-desktop.py --self-test              # 98 checks, no display, no network
python3 -m pytest tests/                                     # 175 tests (needs python-pytest; development only)
python3 omarchy-store-desktop.py --snapshot out.png          # QA: renders the store to the PNG you name (the one write outside the app dirs)
python3 omarchy-store-desktop.py --probe https://omarchystore.com/app/btop/   # prints the argv the terminal WOULD get
```
`OMARCHY_STORE_URL` is accepted only for the two store hosts over https; anything else falls back to the default. The
preview site is deliberately not trusted by release builds; QA against it is done on a throwaway copy, never shipped.

The security model, every host contacted, every file written and what was *not* reviewed are in
`SECURITY.md`; the full 1.1.1 review with the commands that were run is `SECURITY-REVIEW-1.1.1.md`. The harness that
produced its proofs (local HTTPS store stand-in, driver with real X input, packaging checks) is in `qa/` — development
only, never installed. Auditors: the app body is everything above `def self_test`; `--probe` and `--snapshot`
below it are QA tooling and are still covered by the forbidden-call audit.

## Keyboard
`Ctrl+Q` quit · header bar: back, forward, home, reload · menu: About, Security model.

Kernlux Development Labs · MIT · info@omarchystore.com
