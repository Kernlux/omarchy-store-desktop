# Security review — Omarchy Store desktop 1.1.1

Date: 2026-10-30 · Reviewer: Claude (Anthropic), running as an automated multi-agent audit (seven independent review
lenses, each finding re-verified by a skeptical second pass) plus **live execution** of the real app under Xvfb with real
input events · Gate: Kernlux software security gate + the owner's six non-negotiable rules.
Baseline reviewed: 1.1.0 as uploaded (`omarchy-store-desktop.py` sha256 `fcbae355bb77e0c9d90c12795400516752300e730f9a032db104c247522ec7d4`,
519 lines, `install.sh`, `pkg/PKGBUILD`, `release.sh`, `data/*`, `SECURITY.md`, `SECURITY-REVIEW-1.1.0.md`, `README.md`).
Line numbers below refer to the **1.1.0** file unless marked (1.1.1). Everything marked *verified* was exercised by real
execution in the review environment described in §4; the things that were not are listed in §6.

## 1. Verdict

**1.1.0 kept its central promises** — nothing ran as root, no page-supplied text was ever executed, no hook, no unit, no
scriptlet, no listener, no telemetry — **but it broke rule 4 and weakened rule 2 in ways the 1.1.0 review missed**, and
a store page could act without the user:

- A store-origin response served as `Content-Disposition: attachment` was **saved to disk by WebKit's default download
  handler** (reproduced: the file landed in `$HOME` because the test home had no `~/Downloads`). The app never asked.
- **Ctrl+D at "Press Enter to continue" ran the install** (`read -r _;` ignores EOF), so the "nothing runs until you press
  Enter" guarantee had a hole.
- WebKit's **built-in password dialog** appeared inside the window on a `401`/`407` (reproduced:
  `WebKitAuthenticationDialog` in the widget tree).
- The bridge needed **no user gesture**: the review's attack page opened **3 terminals and 5 browser windows** at load,
  with no click.
- The catalog fetch **followed redirects to other hosts (and to plain http) before checking** where it ended up
  (reproduced: four requests to `evil.test`).
- The WebKit **data and cache directories were swapped** (site data in `~/.cache`, HTTP cache in `~/.config`).

No CRITICAL or HIGH finding: none of the above gave a page or the catalog origin command execution, root, or a silent
install. All of it is fixed in 1.1.1 (§2), along with 30-odd LOW/INFO hardening items and every false claim found in the
1.1.0 documents (§3). 1.1.1 was then re-run through the same live harness: the attack page gets nothing, no file is ever
saved, Ctrl+D cancels, no dialog appears, redirects are refused before they are followed.

## 2. Findings

Severity: MEDIUM = a stated guarantee is false or an attack needs no user action; LOW = hardening gap / bug / false
documentation; INFO = accepted limit, documented. "Verified" names the evidence in §5.

| # | Sev | Where (1.1.0) | Finding | Fix (1.1.1) | Verified |
|---|---|---|---|---|---|
| 1 | MEDIUM | `.py:56` (`TERMINAL_SCRIPT`) | `read -r _;` — on EOF (Ctrl+D, or stdin that is not a terminal) `read` fails, `;` ignores it and the install **runs without Enter**. | `read -r _ \|\| { printf 'Cancelled'; exit 130; }` and a leading `[ -t 0 ] \|\| exit 1` (a pipe is not a terminal). | §5.3 xterm Ctrl+D → "Cancelled.", nothing run; pytest in a real pty (Enter runs, EOF cancels, pipe refused). |
| 2 | MEDIUM | `.py:300-313` (`on_message`) | Bridge `install`/`open` needed **no user gesture and had no limit**: page script could open terminals and browser windows in a loop, at load. | A real-input token: `Gtk.GestureClick` + `Gtk.EventControllerKey` in the capture phase record the last click/key; a bridge action needs one within 10 s and **spends** it; a click that starts a navigation is spent by the navigation. | §5.3 attack page: 1.1.0 → 3 terminals + 5 browsers; 1.1.1 → 0 + 0; real clicks still open the terminal. |
| 3 | MEDIUM | `.py:272-274` (`on_policy` RESPONSE) | Only non-displayable MIME types were intercepted; a displayable response with `Content-Disposition: attachment` fell through to **WebKit's default handler, which saves it to disk** (rule 4). The hand-off to the browser also needed no gesture and fired for hidden subframes. | `download-started → cancel()` on the NetworkSession (hard stop: this app never writes a downloaded file); attachment responses treated as downloads; the hand-off to the browser only when the navigation that produced it was user-started. | §5.3: 1.1.0 wrote `omarchy-attachment-test.txt` into `$HOME`; 1.1.1 wrote nothing and handed the URL to the browser; hidden-iframe attachment dropped. |
| 4 | MEDIUM | `.py:292` (`on_load_failed`) | Errors classified by the text "cancel". Every download and every click→302→off-site redirect produced `WebKitPolicyError 102 Frame load interrupted` and **replaced the page with "Can't reach the store"**. | Match by domain/code (`NetworkError.CANCELLED`, `PolicyError.FRAME_LOAD_INTERRUPTED_BY_POLICY_CHANGE`); error page via `load_alternate_html` so Reload retries the real URL. (`GLib.Error.matches` needs the integer quark — a string domain silently never matches.) | §5.3 download/redirect clicks: error page in 1.1.0, none in 1.1.1. |
| 5 | MEDIUM | `.py:231-233` (no `authenticate` handler) | WebKit's default shows a **username/password dialog inside the app** on `401 WWW-Authenticate` or a `407` proxy. Rule 2 says nothing asks for a password. | `authenticate → request.cancel()`. | §5.3: `WebKitAuthenticationDialog` present in 1.1.0's widget tree, absent in 1.1.1. |
| 6 | LOW | `.py:150-151` (`_refresh`) | `urlopen` followed redirects **anywhere, including https→http**, and only then was the final URL checked — other hosts were contacted first. | `StoreRedirectHandler`: a redirect off the store is refused before the request is sent; one fetch site, proven by the self-test. | §5.4: 1.1.0 → 4 × `GET evil.test/catalog.json` and an attempt on `http://evil.test`; 1.1.1 → store request only, "catalog redirect refused". |
| 7 | LOW | `.py:209` | `WebKit.NetworkSession.new(CACHE/web, CONF/web)` — the signature is `(data_directory, cache_directory)`: **site data lived in `~/.cache`, the HTTP cache in `~/.config`**. | Arguments swapped back. | §5.3 directory listings before/after. |
| 8 | LOW | `.py:26, 258, 270` | Rule 5 names the API worker `omarchy-store-backend.omarchystore.workers.dev`; it was in no allow-list, so a navigation, form post or frame to it was dropped or sent to the browser. | `WEBVIEW_HOSTS = STORE_HOSTS + worker`, used **only** to decide what may render; bridge, catalog and home stay on `STORE_HOSTS`; the bridge helper is not injected on the worker. | §5.3 worker link/form/iframe load in-window; its page's bridge attempts are ignored; `__OMARCHY_DESKTOP__` is `null` there. |
| 9 | LOW | `.py:36, 38` | `PKG_RE`/`ARG_RE` lacked `@`, which Arch's pkgname charset (`^[a-z0-9@._+-]+$`, the owner's rule) allows. | `@` added to both; the first character stays `[a-z0-9]` (a leading `-` would be a flag, a leading `.` is invalid in Arch). | §5.3 `foo@bar` listing: refused in 1.1.0, terminal in 1.1.1; self-test + pytest. |
| 10 | LOW | `.py:104-106, 287` | Bridge `open` accepted any string starting `https://`: empty host, whitespace, control characters, userinfo (`https://omarchystore.com@evil/`). | `is_https_url`: scheme, host present, no userinfo, no whitespace/control character, ≤ 2048. | pytest, self-test. |
| 11 | LOW | `.py:65-74` | `urlsplit` silently strips tabs/newlines/CR, so `https://omarchystore.com\t/` passed `is_store_url`. | `CTRL_RE` rejects any whitespace/control character before parsing. | pytest, self-test. |
| 12 | LOW | `.py:258-261` | `window.open()` / `target=_blank` to `about:blank` was treated as "inside" and **`load_uri("about:blank")` replaced the store page**. | A blank popup opens nowhere; only `WEBVIEW_HOSTS` URLs load in place. | §5.3: 1.1.0 ended on `about:blank`; 1.1.1 page intact. |
| 13 | LOW | `.py:258 vs 270` | `blob:` documents allowed at navigation but refused at the main-frame response check → error page. | One predicate `inside_url()` for navigations and responses (store/worker, `about:blank`, `about:srcdoc`, store `blob:`). | pytest, self-test (live blob check: §6). |
| 14 | LOW | `.py:306-309` | `command(v)` then `apps[v]`: two reads across the refresh thread's dict swap → `KeyError`. | Single read of the entry. | code review; thread swap unchanged otherwise. |
| 15 | LOW | `.py:225-233` | `script-dialog`, `run-file-chooser`, `enter-fullscreen` left to WebKit's defaults: `prompt()` could show a GTK text field labelled "password", a page could open a file picker or go fullscreen. | `prompt()` swallowed (alert/confirm keep WebKit's plain dialog), file chooser cancelled, fullscreen off. | §5.3 `/attack2/`: `prompt()` returned null in 3 ms, not fullscreen; 1.1.0's prompt blocked the page until the test timed out. |
| 16 | LOW | `.py:225-230` | Risky defaults unpinned: WebGL, WebRTC, media autoplay (and `<a ping>` hyperlink auditing, which turned out not to be controllable in API 6.0 — see 51). | WebGL, WebRTC off; playback needs a gesture. | code + §5.1. |
| 17 | LOW | `.py:219-223` | The bridge helper (`window.omarchyDesktop`) was injected into **every** top-frame document (allow_list `None`), including the error page and anything else the view ever shows. | `UserScript` allow-list `https://<store host>/*` derived from `STORE_HOSTS`. | §5.3 worker page: `desktop flag: null`. |
| 18 | LOW | `.py:302` | `value.to_string()` before any type check. | `value.is_string()` first. | code. |
| 19 | LOW | `.py:195-199, 310-313` | "Opened your terminal" toast even when `xdg-terminal-exec` exits at once; the child was never reaped (one zombie per install until the next). | `open_in_terminal` returns the handle; a 0.5 s poll reaps it and, if it died within 2 s with a non-zero status, says so. | code; §5.3 terminals close cleanly. |
| 20 | LOW | `.py:129-132, 322` | `Catalog(fetch)` in `App.__init__` runs **before GApplication uniqueness**: every second launch re-downloads the catalog. | Fetch moved to `do_startup` (primary instance only). | code. |
| 21 | LOW | `.py:90-92, 130, 206` | `private_dir()` failures (a file where the dir should be, unwritable XDG dir) were uncaught tracebacks at startup. | Caught and logged; the app runs without a catalog / without persistence instead of not at all. | code. |
| 22 | LOW | `.py:141-144, 156-162` | `_load` missed `TypeError`/`RecursionError` (`{"apps": 5}`, deep nesting); `os.unlink` in the `except` could itself raise; no `fsync`; the 20 MiB body was parsed twice. | `except Exception`, non-list guard, guarded unlink, `fsync`, the validated tree is used directly. | code; §5.4 big/not-JSON/list modes refused with no cache written. |
| 23 | LOW | `data/omarchy-store-desktop:1,4`, `install.sh:50`, `PKGBUILD:22` | Launchers ran `python3` without `-I` (PYTHONPATH, user site-packages and `.pth` files could inject code into the process that opens the terminal) and resolved `bash` through `env`/`PATH`. | `#!/usr/bin/bash` + `exec /usr/bin/python3 -I …` everywhere; the app resolves `bash` from `os.defpath` (`/bin:/usr/bin`) only. | §5.5 package launcher and installer launcher content; self-test passes under `-I`. |
| 24 | LOW | `install.sh:52, 58` | The menu entry kept `Exec=omarchy-store-desktop`, which needs `~/.local/bin` on the *session's* PATH; the script said "the launcher entry still works". | `Exec="<absolute launcher path>"` (quoted per the Desktop Entry spec), with an honest note for the rare unquotable path. | §5.5 `Exec=` line after install. |
| 25 | LOW | `install.sh:13` | A relative `XDG_DATA_HOME` (invalid per the XDG spec; GLib ignores it) was honoured — broken launcher, uninstall missing every file. | Ignored unless absolute. | code. |
| 26 | LOW | `install.sh:50` | `printf > "$launcher"` followed a pre-existing symlink and overwrote its target. | Written to a temp file, placed with `install(1)` (replaces, never follows). | code. |
| 27 | LOW | `install.sh:38-44` | `pacman -Q <name>` refused providers (`provides=('xdg-terminal-exec')`); no check that pacman exists. | `command -v pacman` first; `pacman -T` (accepts providers). | §5.5 missing-dep run. |
| 28 | LOW | `install.sh:25-32` | `--uninstall` re-ran `update-desktop-database` and left `mimeinfo.cache` behind. | Removed when ours was the only entry. | §5.5 uninstall listing. |
| 29 | LOW | `pkg/PKGBUILD:13` | Icons under `/usr/share/icons/hicolor` without depending on `hicolor-icon-theme` (Arch guideline; namcap error). | Added. | §5.5 `.PKGINFO`. |
| 30 | LOW | `pkg/PKGBUILD:14-18`, README | Not yet AUR-packagable as committed: local-file `source=`, no `.SRCINFO`, README build steps that cannot work. | `pkg/.SRCINFO` generated with `makepkg --printsrcinfo`; README documents the interim local-tarball flow; the AUR `source=` URL stays as a comment until the organisation is live. | §5.5. |
| 31 | LOW | `release.sh:25-29` | Tarball mtime = "now" (not reproducible), no clean-tree check, no tests, hash pinned without a recorded epoch. | `SOURCE_DATE_EPOCH` defaults to the newest source mtime (or the last commit) and is printed; git tree must be clean; `--self-test` and `pytest` (if installed) must pass; the review document must exist; `tests/` and the review ship in the tarball. | §5.6. |
| 32 | LOW | `SECURITY.md`, `README.md`, module docstring, in-app dialog | False or stale claims: subresources "go through the navigation policy"; "the only hosts it ever contacts"; bridge "injected into the top frame only"; `--self-test` "no files written" (GLib creates `~/.cache` when `XDG_RUNTIME_DIR` is unset); word/package charsets without `@`; "57 checks"; mixed content "blocked"; the token scan described as broader than it is; files "all owner-only" (the parent dirs are 0700, not every file); `--snapshot` path. | Both documents rewritten; numbers come from real runs. | this document, `SECURITY.md`. |
| 33 | INFO | `.py:258` | `about:srcdoc` frames were dropped (fail-closed; the storefront does not use them). | Allowed: they inherit the parent's origin. | pytest. |
| 34 | INFO | owner's rule | `^[a-z0-9@._+-]+$` taken literally would accept `--noconfirm`, `-`, `.`; the code's first-character anchor is the real protection and is kept. | Documented. | — |
| 35 | INFO | `.py:44-49` | `omarchy pkg add` / `omarchy pkg aur add` verified against basecamp/omarchy master (`bin/omarchy` → `omarchy-pkg-add` → `sudo pacman -S --noconfirm --needed -- "$@"`; `omarchy-pkg-aur-add` → `yay -S --noconfirm --needed -- "$@"`). Older Omarchy releases may only ship the leaf scripts; the storefront's `omarchy` method is mapped to a plain repo install. | Documented; unchanged (product decision). | raw source fetched 2026-10-30. |
| 36 | INFO | `.py:28` | `MAX_URL = 2048` also caps in-window store URLs (a longer store link opens in the browser). | Documented. | — |
| 37 | INFO | `.py:216` | `register_script_message_handler` has no frame filter in API 6.0: any frame that renders can post; only store-origin frames can render, and the origin check is on the main frame. | Documented; mitigated by the policy. | — |
| 38 | INFO | `.py:219-223` | Third-party scripts the storefront embeds run with the store origin and can call the bridge like first-party code. A content filter was considered and not added (it could break the storefront). | Documented. | — |
| 39 | INFO | `release/` | Only `.sha256` files for 1.0.0/1.1.0 were in the upload; the 1.1.0 PKGBUILD hash could not be re-verified here. | 1.1.1 built, hashed and pinned by `release.sh`. | §5.6 |
| 40 | INFO | `.py:349-469` | Self-test blind spots (EOF gate, `bash -n`, flatpak script, URL parser differentials, file-writing call sites, fetch sites, worker, input gate). | +25 checks: **57 → 82**, including `bash -n` of generated scripts, "file-writing calls exist only in `private_dir` and `_refresh`", and "the only directories ever created are the XDG config/cache dirs + omarchy-store" (see also 44). | §5.1 |
| 41 | INFO | — | Releases are checksum-only (no signature); a signed release (minisign/GPG, `validpgpkeys=`) is recommended once there is a key to publish. | Recommended. | — |
| 42 | MEDIUM (1.1.1 draft) | `.py` (1.1.1 draft) `inside_url`, RESPONSE branch | My first 1.1.1 draft let the API worker render in **subframes** too; the message handler exists in every frame, so a worker-origin frame inside a store page could post to the bridge while the main-frame origin check passed. | `inside_url(uri, main=…)`: worker documents in the main frame only; subframes hold `STORE_HOSTS` documents only (plus `about:blank`/`srcdoc`/store `blob:`). | §5.3 worker iframe now refused ("refused document:"), worker link/POST still load in the main frame. |
| 43 | LOW (1.1.1 draft) | `.py` (1.1.1 draft) `on_policy` | Click-token leaks in the first draft of the gate: `clicked` URIs never expired (a later script-started response for a once-clicked URI went to the browser); every gesture-carrying navigation opened the browser (one click → N windows via N iframes/`window.open`); any key press armed the bridge. | A click vouches for the first response of its navigation only; every external open spends the token (one browser window per click); only Enter/Space count as key input; the terminal script drops typed-ahead input before asking. | §5.3 final run; pytest. |
| 44 | LOW | `.py:349-469` (self-test) | The static audit could be evaded: `getattr(subprocess,"run")`, `import subprocess as sp`, `from os import system`, `Gio.Subprocess()`/`Gio.AppInfo` constructors, `GLib.spawn_*`, bytes/f-string/folded-concatenation strings, `os.open`/`shutil`/`NamedTemporaryFile`, `open(…, opener=)`, `os.environ[…] =`, a second `def self_test`, `/bin/sh`. | The audit now inspects every name reference (not only calls), forbids aliased/extra imports, pins the one `Popen` and the one network request by exact text and location, scans compiled constants (bytes, folded strings) and joined f-strings, extends the system-path roots, forbids environment writes, and requires exactly one `self_test`. `tests/` plants 33 known evasions in a copy and requires the self-test to **fail** for each. | §5.1: 82 checks; 33 negative tests pass. |
| 45 | LOW | `pkg/PKGBUILD`, docs | During the review the PKGBUILD briefly pinned a tarball older than the tree (the normal failure mode of a manual release step), and documents quoted stale counts. | `release.sh` deletes the stale archive first, requires the review to be final (not a draft), and refuses to release unless README/SECURITY.md quote the real check/test counts; a test asserts the pinned hash equals the tarball and the tarball's `.py` equals the tree's. | §5.6; pytest. |
| 46 | INFO | `.py:26` | `www.omarchystore.com` carries full store trust although rule 5 does not list it. | Kept (it is the store's own alias); stated in the code comment and `SECURITY.md`. Owner to confirm. | — |
| 47 | INFO | `install.sh` vs rule 4 | The user-space installer necessarily writes a launcher (`~/.local/bin`), a menu entry and an icon (`~/.local/share/{applications,icons}`) and two desktop caches — outside rule 4's three roots as worded. | Documented in README/SECURITY.md; rule 4's wording should name them. | — |
| 48 | MEDIUM (1.1.1 draft) | `on_message` origin check | The check used the view's *active* URL (`get_uri()`), which already names a pending navigation while the previous document — e.g. the worker page after the user pressed Home — still runs its scripts; a message posted in that window passed the check. | The bridge checks the **committed** document's URL (`doc_uri`, set on `load-changed COMMITTED`); nothing may use the bridge before the first commit. | two independent verifiers; §5.3 unchanged for real pages. |
| 49 | LOW (1.1.1 draft) | download hand-off | `clicked` kept up to 32 URIs (a later script-started response for a once-clicked URI could be handed off) and the hand-off did not spend the click (one click → a browser window **and** a terminal). | One pending clicked navigation, consumed by its first main-frame response; the hand-off spends the click like every other action. | §5.3 download/attachment clicks still reach the browser, once. |
| 50 | LOW | `.py:152` | The catalog read had only a per-`recv` timeout: a slow drip could hold the fetch thread indefinitely while buffering up to 20 MiB. | 64 KiB chunks with a 60 s deadline for the whole body. | §5.4 big-catalog mode still refused. |
| 51 | LOW (1.1.1 draft) | WebKit settings | `set_enable_hyperlink_auditing(False)` (added in the draft) is a deprecated **no-op** in API 6.0 that logs a WARNING at every launch; the docs claimed pings were off. | Call removed; docs state that `<a ping>` cannot be disabled and is a click-initiated subresource request. | final runs' stderr: no WebKit warning. |
| 52 | LOW | `install.sh:61` (1.1.1 draft) | The generated `.desktop` was written through a plain redirect (follows a symlink) — the launcher had been fixed the same way, the menu entry not. | Temp file + `install(1)`. | §5.5. |
| 53 | INFO | `.py:44-49` | The 1.1.0 review left open whether older Omarchy releases ship the `omarchy` dispatcher. Verified against the upstream repository's history: present from **v3.7.0**, absent in ≤ 3.6.0. | Documented; switching to the leaf scripts is the owner's call. | upstream clone by a review agent. |
| 54 | INFO | `.py:196` | The terminal launcher's stderr was discarded, hiding `xdg-terminal-exec`'s own diagnostics when it fails. | stderr inherited (reaches the app's log). | §5.3. |
| 55 | LOW (1.1.1 draft) | `_refresh` read loop | `r.read(65536)` blocks until 64 KiB arrive, so the 60 s deadline was only checked between full chunks — a one-byte drip could hold the thread for hours per chunk. | `read1()` (one socket read per iteration), deadline checked each time. | code; §5.4 big-catalog mode. |
| 56 | LOW | `release.sh:27` (1.1.1 draft) | The default `SOURCE_DATE_EPOCH` included `pkg/PKGBUILD`'s mtime, which the script itself rewrites — two runs on one tree gave two hashes. | `pkg/PKGBUILD` dropped from the epoch sources; `RELEASE-INFO` (version + epoch) shipped inside the archive; a warning when not run from git. | §5.6. |
| 57 | LOW | `.py:129-132` | The catalog was fetched exactly once per process: after an offline first start, Install stayed refused until a restart, although the error page says "press Reload". | Reload and Home re-run the fetch while the catalog is empty (one at a time, at most once a minute); the refusal toast says what to do. | §5.3 offline → Reload → catalog present. |
| 58 | LOW (1.1.1 draft) | input gate | Space armed the bridge while typing in a search box; the 10 s window was generous. | Enter only; 3 s window. | code; live runs unchanged. |
| 59 | LOW | self-test (1.1.1 draft) | Six more audit evasions: `__doc__` read-back of a docstring payload, a nested method named `self_test`, `open()` of any path, unpinned host constants, a second `UserScript`/`UriLauncher`, `load_html`. | All closed and covered by six more negative tests (33 in total). | §5.1. |
| 60 | INFO | `.py:230` | The User-Agent token carried the exact app version to every host the page loads from. | Token without version. | code. |
| 61 | INFO | `command()` | Duplicate package names in one listing were passed through (`… add btop btop`). | Refused like any malformed listing; duplicate catalog ids keep the first and are logged. | self-test, pytest. |
| 62 | INFO | `download-started` | Cancelled downloads gave no feedback; "No terminal emulator found" also covered a terminal that failed to start; the toast primed "press Enter". | Toast on cancelled downloads; distinct messages; toast now says "read the command — Enter runs it, Ctrl+C cancels". | code. |
| 63 | INFO | README/PKGBUILD/docs | README claimed the dependencies are "present on every Omarchy install" (webkitgtk-6.0 is not; flatpak only for Flatpak listings); launcher comments overclaimed what `-I` protects against; the GitHub organisation named in README/PKGBUILD is not yet controlled by the project. | README reworded; `optdepends=('flatpak: …')`; comments reworded; organisation registration is an owner action (handoff). | — |

## 2a. How the findings were produced and checked
Six independent review lenses (command construction; bridge and navigation policy; URL allow-list; files, fetch and
concurrency; packaging and installer; runtime/API correctness) each read the whole tree and returned structured findings
(99 raw, deduplicated to 90). A seventh lens (specification compliance / assurance soundness) was started and dropped
after it stalled; its ground is covered by the runtime lens's assurance findings (44) and this document's own checks.
Every deduplicated finding was then handed to a **skeptical verifier** with the instruction to refute it from the actual
file and API facts: 43 were confirmed, 47 refuted (mostly: already fixed in the tree by then, or not reproducible).
Of the 43 confirmed: 25 were already fixed in the 1.1.1 draft under review (the verifier said so explicitly), 8 led to
further code changes (rows 48–54 and the single-slot click token), 10 were documentation alignments or accepted limits
now stated in `SECURITY.md`. Several verifiers ran their own experiments (pure-function extractions, a clone of
basecamp/omarchy to date the `omarchy` dispatcher, live `install.sh` runs as an unprivileged user). The author of the
changes (the same automated reviewer) then re-ran the live harness after every patch; §5 shows the final state. A final
**completeness critic** read the whole tree against the confirmed list and returned 17 more items (rows 55–63 plus
documentation corrections); each was acted on or recorded above before the release was cut.

## 3. What changed in 1.1.1 (by file)

- `omarchy-store-desktop.py` (519 → ~700 lines): `WEBVIEW_HOSTS`, `CTRL_RE`, `INPUT_WINDOW_US`; `PKG_RE`/`ARG_RE` with `@`; `_https_on`/`is_store_url`/`is_webview_url`/`is_https_url`/`inside_url(main=)`; `input_is_fresh`; `StoreRedirectHandler`; `Catalog.refresh()` (started from `App.do_startup`), `command_for`, robust `_load`/`_set`/`_refresh`; terminal script with `[ -t 0 ]`, typeahead drain and `read … || exit 130`; `bash` from `os.defpath`; `open_in_terminal` returns the handle; WebKit: data/cache dirs fixed, `download-started → cancel`, user-script allow-list, `authenticate`/`run-file-chooser`/`script-dialog` handlers, settings pinned, real-input observers (clicks; Enter/Space), `on_policy` with `inside_url`, spent clicks, one browser window per click, attachment detection, blank-popup fix, `on_load_failed` by error code + `load_alternate_html`, `on_message` type/token/one-read/terminal watch; hardened self-test (82 checks); `--probe` arms the gate for its scripted click.
- `install.sh`: `#!/usr/bin/bash`, relative `XDG_DATA_HOME` ignored, `pacman -T` + `command -v pacman`, launcher with `-I` via temp file + `install(1)`, absolute quoted `Exec=`, uninstall removes `mimeinfo.cache` when ours was the only entry.
- `data/omarchy-store-desktop`: `#!/usr/bin/bash`, `python3 -I`.
- `pkg/PKGBUILD`: `pkgver=1.1.1`, `hicolor-icon-theme`, `check()` with `-I`, pinned sha256 of the 1.1.1 tarball; `pkg/.SRCINFO` added.
- `release.sh`: reproducible epoch, clean-tree check, tests, review document required and shipped, `tests/` shipped.
- `tests/test_security.py` (new): 175 tests — command builder, terminal script (in a real pty), URL allow-list, bridge validation, input gate, redirect handler, self-test, 33 audit-evasion negatives, release consistency (every file in the archive), tree-level no-hook assertions.
- `SECURITY.md`, `README.md`, `.gitignore`, this document.

## 4. Environment the proofs were produced in — and its limits

- **Host**: the review sandbox is Ubuntu 24.04 (x86_64). Arch is the target; no Arch mirror was reachable from the
  sandbox (network policy), so the *runtime* stack came from Ubuntu's official packages: python 3.12.3, PyGObject 3.48.2,
  GTK 4.14.5, libadwaita 1.5.0, **WebKitGTK 2.52.6 (API 6.0)**, Xvfb 21.1.12 (1600×1000), xterm 390, xdg-terminal-exec
  0~20230318, xdotool (real XTEST clicks and key presses), bubblewrap 0.9.0. The app's code paths are identical on Arch;
  library versions differ (Arch ships newer GTK/libadwaita/WebKitGTK — see §6).
- **Arch (packaging only)**: the official `archlinux:base-devel` image (pacman 7.1.0, makepkg 7.1.0, fakeroot 1.37.2,
  python 3.14.8) pulled layer by layer from Docker Hub (digests verified) into a chroot entered with `unshare -m -p`.
  Because no mirror was reachable, the runtime dependencies were installed as **empty placeholder packages** so that
  pacman's dependency resolution and `install.sh`'s `pacman -T` check could run for real; the app itself did not run there.
- **Store hosts**: `omarchystore.com`, `www.omarchystore.com`, `v8.omarchy-store-preview.pages.dev` and the worker were
  all blocked by the sandbox's network policy. Every WebKit behaviour was therefore exercised against a **local HTTPS
  fixture** (Python `http.server` + TLS, a locally generated CA trusted only inside the sandbox, `/etc/hosts` pointing the
  four hostnames and `evil.test` at 127.0.0.1) that mimics the storefront's bridge contract documented by the 1.1.0
  `--probe` (`.actions [data-get]` → `[data-desktop-install]` → `omarchyDesktop.install(id)`) and serves a 10-app catalog
  with good and hostile listings. The real storefront's JavaScript was **not** re-reviewed.
- **WebKit sandbox**: on this VM WebKit's bubblewrap sandbox started only when no D-Bus session bus was set
  (`xdg-dbus-proxy` could not bind its socket here); all runs used the sandbox **on** and no session bus, in a fresh test
  `$HOME`, with the proxy and CA environment variables of the sandbox removed (as on a real desktop).
- The QA harness (fixture, pages, driver, chain scripts, packaging verifier) is delivered next to the source tree as
  `qa/` with its own README so the next reviewer can reproduce every run; its TLS key material is not included.

## 5. Proofs — commands run and their real output

### 5.1 Self-test and unit tests (final 1.1.1 file)
```
$ /usr/bin/python3 -I omarchy-store-desktop.py --self-test | tail -1
82 checks · SELF-TEST OK
$ /usr/bin/python3 -m pytest -q tests/
175 passed
```
(33 of the 175 are negative tests: each plants one known evasion of the static audit into a copy of the file and
asserts that `--self-test` then fails. One test asserts the pinned release hash matches the tarball and `.SRCINFO`, and
that every file inside the tarball is byte-identical to the tree; it skips while no archive exists.)
Against the untouched 1.1.0 file the same suite failed 12 tests (the ones encoding the fixes: `@`, tab/newline URLs,
worker scope, redirect handler, open-URL validation, input gate) and the 1.1.0 self-test reported `57 checks · SELF-TEST OK`.

### 5.2 Live run — what the window does (driver = the real module, real `Window`, real catalog thread, real terminal launcher; input = xdotool XTEST)
Window opens at 1380×900 with the header bar (back / forward / home / reload, menu); the store (fixture) loads over TLS;
`[omarchy-store] catalog refreshed: 10 apps`; `~/.cache/omarchy-store/catalog.json` is 0600 inside 0700 directories.

### 5.3 Behaviour table — 1.1.0 vs 1.1.1 (same fixture, same real clicks)

| Action (real click unless stated) | 1.1.0 | 1.1.1 |
|---|---|---|
| store link | loads in window | loads in window |
| external https / http / mailto link, external `target=_blank` | browser log gets the URL; page unchanged | same |
| store `target=_blank` | loads in place | loads in place |
| `target=_blank` to `about:blank` | **page replaced by `about:blank`** | page intact |
| download link (`application/x-tar`) | browser gets URL **and "Can't reach the store" error page** (`WebKitPolicyError 102`) | browser gets URL, page intact |
| `text/html` served `Content-Disposition: attachment` | **file saved by WebKit into `$HOME`** (`omarchy-attachment-test.txt`), no browser, error page | nothing saved, browser gets URL, page intact |
| `data:` link | refused, page intact | refused, page intact |
| store link → 302 → `evil.test` | browser gets the final URL (gesture carried) **+ error page**; `evil.test` never requested by the view | browser gets URL, no error page, no request |
| link / form POST to the API worker | sent to the browser (rule 5 not met) | load in the main frame; the worker page's bridge attempts are ignored; `__OMARCHY_DESKTOP__` null there |
| iframe to the API worker inside a store page | dropped | dropped ("refused document:") — subframes hold store documents only |
| hidden iframe to `evil.test` | never requested | never requested |
| store URL answering `401 WWW-Authenticate` | **`WebKitAuthenticationDialog` in the window** | no dialog |
| `/attack/` page (its own script at load: 3 × `install`, 5 × `open`, junk, `window.open`, evil iframe, `form.submit()`, `location=` evil, `location=` data:, hidden attachment iframe) | **3 terminals, 5 browser launches**; navigations dropped; no file saved | 0 terminals, 0 browser launches (the click that opened the page was spent by that navigation); "bridge message ignored: no recent click or key press" × 9; no file saved |
| `/attack2/` page: `prompt('Enter your password')`, `requestFullscreen()` | prompt dialog **blocked the page** (test timed out) | `prompt() returned null after 3 ms`; not fullscreen |
| GET → Install on `btop` | xterm via `xdg-terminal-exec` with `bash -c '<fixed script>'`; printed `omarchy pkg add btop`; Enter → ran (`command not found`, exit 127 on this non-Omarchy host); Enter → closed | same (the one `--` difference: the script now starts with `[ -t 0 ] ||`) |
| Install on `bottles` (aur), `obs` (flatpak) | terminal with `omarchy pkg aur add bottles` / `flatpak install flathub com.obsproject.Studio` | same |
| Install on `foo@bar` listing | refused | terminal with `omarchy pkg add foo@bar` |
| Install on `evil` (`btop; rm -rf ~`), `flag` (`--noconfirm`), `dot` (`.hidden`), `rel`, `many` (21), unknown id | refused with toast | refused with toast |
| listing whose name is `\x1b[2J\x1b[H  HIDDEN btop` | title printed as `Install 2JH  HIDDEN btop` (escapes stripped) | same |
| Ctrl+D at "Press Enter to continue" | *(not exercised — see finding 1; pty test shows the install runs)* | `Cancelled.` printed, nothing run, terminal closed |
| offline first start | error page with the g-io error; `catalog refresh skipped: Connection refused`; header Reload after reconnecting → store loads | same |

Site data after a run: 1.1.0 `~/.config/omarchy-store/web/{CacheStorage,HSTS,WebKitCache}` + `~/.cache/omarchy-store/web/{mediakeys,storage}`;
1.1.1 `~/.config/omarchy-store/web/{mediakeys,storage}` + `~/.cache/omarchy-store/web/{CacheStorage,HSTS,WebKitCache}`. Nothing else
appeared under the test `$HOME` except GTK/dbus housekeeping (`.dbus/session-bus` from the autolaunch, because no session bus was set).

### 5.4 Catalog fetch under hostile servers (fixture `catalog.mode`)

| `/catalog.json` behaviour | 1.1.0 | 1.1.1 |
|---|---|---|
| 302 → `https://evil.test/catalog.json` | **4 × `GET evil.test/catalog.json`** then "redirect error that would lead to an infinite loop" | "catalog redirect refused: https://evil.test/catalog.json", 1 store request only |
| 302 → `http://evil.test/catalog.json` | **connected to evil.test:80** (refused by the fixture) | refused before the request |
| 302 → `https://www.omarchystore.com/…` (store host) | followed, 10 apps | followed, 10 apps |
| 21 MiB body | "catalog too large", no cache | same |
| not JSON / top-level list | refused, no cache | same |

### 5.5 Packaging (task D)
```
# Arch chroot (archlinux:base-devel, pacman 7.1.0, makepkg 7.1.0), non-root user "builder"
==> Finished making: omarchy-store-desktop 1.1.1-1
file list: .BUILDINFO .MTREE .PKGINFO usr/bin/omarchy-store-desktop usr/share/applications/com.omarchystore.Store.desktop
  usr/share/doc/omarchy-store-desktop/{README.md,SECURITY.md} usr/share/icons/hicolor/512x512/apps/com.omarchystore.Store.png
  usr/share/licenses/omarchy-store-desktop/LICENSE usr/share/omarchy-store-desktop/omarchy-store-desktop.py
.INSTALL scriptlet present: 0  hooks: 0  systemd: 0  autostart: 0   files outside /usr/bin,/usr/share: 0
pacman -U …  Install Script : No     pacman -R … left behind: (nothing)   hooks/units mentioning omarchy: (none)
install.sh as builder: 4 files under ~/.local, launcher "exec /usr/bin/python3 -I <abs path> "$@"", Exec="<abs launcher>"
install.sh --uninstall: only empty directories remain   install.sh as root: refused (rc=1)
install.sh with gtk4 missing: "Missing packages: gtk4 … sudo pacman -S gtk4" (rc=1), nothing installed
# Ubuntu host, makepkg 6.0.2 as user "ubuntu" (--nodeps: deps are apt packages here), check() RUNS:
==> Starting check()...   82 checks · SELF-TEST OK   ==> Finished making: omarchy-store-desktop 1.1.1-1
file lists identical to the Arch-built package; pacman -U into an isolated db, launcher runs --self-test, pacman -R leaves nothing
```
The run was repeated on the final 1.1.1 tarball; the full logs are `qa/evidence/d-verify-final.log` and `qa/evidence/d2-verify-final.log`.

### 5.6 Release
`./release.sh` refuses to build unless `--self-test` and `pytest` pass and this document exists; it writes
`release/omarchy-store-desktop-1.1.1.tar.gz`, its `.sha256` sidecar (bare file name, so `sha256sum -c` works from the
download directory), pins the sum into `pkg/PKGBUILD`, and prints the `SOURCE_DATE_EPOCH` it used so the archive can be
rebuilt byte for byte. The hash itself is deliberately **not** written here: this document travels inside the archive
it would be hashing (the same reason the PKGBUILD copy inside the tarball says `SKIP`). Read it from the sidecar and from
`pkg/PKGBUILD` in the repository; the handoff report and `qa/evidence/release-final.log` record the values of this build.

### 5.7 File-system footprint (strace -f over the whole `home` scenario, final code, every child process)
Successful write-class syscalls (`openat` with write flags, `mkdir`, `rename`, `unlink`, `chmod`) targeted only:
`~/.config/omarchy-store/…` and `~/.cache/omarchy-store/…` (the app and WebKit), `~/.cache/mesa_shader_cache/…` (Mesa),
`$XDG_RUNTIME_DIR/dconf/user` (GTK), and bwrap's private `/newroot` mount-namespace setup for the WebKit sandbox. Nothing
under `~/Downloads`, `~/.local`, `/tmp` or anywhere else (the harness's own browser log and screenshots excepted).

## 6. Not checked — say so plainly
- The live storefront and its JavaScript (hosts blocked from the sandbox); the fixture mimics the documented bridge contract.
- Arch's current GTK/libadwaita/WebKitGTK builds: the app ran on Ubuntu 24.04's GTK 4.14 / libadwaita 1.5 / WebKitGTK 2.52.6.
  Every API used exists in WebKitGTK API 6.0 since 2.40; nothing version-specific was relied on.
- A real `omarchy pkg add` run (not an Omarchy system; the command printed and the exit-code path were verified).
- Terminal fallbacks: with a PATH holding only the emulator, the real `open_in_terminal` started `xterm -e`, bare `kitty` and
  `alacritty -e`, each with a `bash -c '<fixed script>'` child carrying the script (process tree inspected); only the
  xterm path (through `xdg-terminal-exec`) was driven to completion. ghostty, gnome-terminal and konsole were not run.
- `blob:` documents: verified by direct navigation — 1.1.1 renders the store page's own blob document at its `blob:` URI;
  1.1.0 logged `refused non-store main resource blob:…` and showed the error page. The fixture's button variant of the
  same test did not navigate in either version (fixture quirk, not investigated further).
- Flatpak listings end to end (none in the catalog); `namcap`; signatures; WebKitGTK/GTK/libadwaita upstream security.
- The WebKit sandbox with a D-Bus session bus present (could not start in this VM; on a real desktop both are present).

## 7. Handoff notes for the next reviewer
- Re-run everything with `qa/README.md` (fixture + driver + chains + packaging verifier). The driver imports the real
  module and drives the real window with XTEST input; nothing in the app is stubbed.
- Decisions deliberately **not** taken (product calls): `omarchy pkg add` vs the leaf scripts `omarchy-pkg-add`; mapping
  of the storefront's `omarchy` install method; a WebKit content filter for third-party scripts; release signing.
- Known accepted limits are in `SECURITY.md` → "Not checked / known limits".
