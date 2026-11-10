# Security review — Omarchy Store desktop 1.1.0

Date: 2026-10-28 · Reviewer: Hermes (line-by-line, every file in `desktop/`) · Gate: Kernlux software security gate.
Baseline reviewed: 1.0.0 (`omarchy-store-desktop.py` 300 lines, `install.sh`, `pkg/PKGBUILD`, `data/*.desktop`).
Line numbers below refer to the **1.0.0** source unless marked (1.1.0).

Verdict: **no critical or high finding in 1.0.0 — nothing ran as root, nothing ran page-supplied text, no hook,
no listener, no telemetry.** Twenty-two medium/low hardening findings were fixed in 1.1.0; all scanner hits that
remain are prose or the self-test's own forbidden-word list (classified below). Everything marked *verified* was
exercised by real execution on this machine; the few things that were not are listed at the end.

## Findings (all fixed in 1.1.0)

| # | Sev | Where (1.0.0) | Finding | Fix (1.1.0) |
|---|---|---|---|---|
| 1 | MEDIUM | `.py:22-23` | `OMARCHY_STORE_URL` was used unvalidated: a non-store or `http://` origin would be used for the **catalog fetch**, i.e. the source of package names. | `pick_home_url()` accepts only an https URL on a `STORE_HOSTS` host, else falls back to the default. Tested. |
| 2 | MEDIUM | `.py:58-59` | Catalog fetch followed redirects anywhere (urllib allows https→http) and had no size cap. | Final URL must pass `is_store_url`; 20 MiB cap; must parse as `{"apps": [...]}`. |
| 3 | LOW | `.py:62-63` | Temp file `catalog.json.tmp` had a predictable name and was opened `O_CREAT|O_TRUNC` without `O_EXCL`/`O_NOFOLLOW`. | `tempfile.mkstemp(dir=CACHE)` (random, 0600, O_EXCL) + `os.replace`; temp unlinked on failure. |
| 4 | LOW | `.py:46,112` | `makedirs(mode=0o700, exist_ok=True)` does not tighten a pre-existing directory. | `private_dir()` also `chmod 0700`. Verified: both dirs are 700, `catalog.json` 600. |
| 5 | MEDIUM | `.py:75` | A package list with one bad name was **silently filtered** and the remaining packages installed — a partial command the user did not see in the catalog. Non-list / non-string values were coerced with `str()`. | One invalid name refuses the whole listing; `packages` must be a non-empty list of strings, ≤ 20. Tested (`mixed`, `strpk`, `many`). |
| 6 | LOW | `.py:26-27,70,75` | `re.match(... $)` accepts a trailing newline (`"btop\n"`). | `fullmatch()` everywhere. Tested. |
| 7 | MEDIUM | `.py:93,191` | The catalog's `name` was printed raw into the terminal (`printf '%s'`). A compromised catalog origin could embed ANSI escapes and redraw/hide the command line the user is asked to confirm — defeating the "read it, then press Enter" guarantee. | `safe_title()` strips everything outside `[A-Za-z0-9 ._+()-]`, caps at 60 chars. Tested with `\x1b[2J`. |
| 8 | LOW | `.py:191,196` | Same `name` went into `Adw.Toast(title=…)`, which interprets Pango markup. | `set_use_markup(False)` + sanitised name. |
| 9 | MEDIUM | `.py:181-193` | Bridge accepted any-length JSON, untyped fields (`str()` coercion), `open` of `http://` and `mailto:` URLs, and did not check that the WebView was showing a store page. | `parse_message()`: ≤ 4096 bytes, JSON object, `id` string matching `ID_RE`, `url` string ≤ 2048 starting `https://`; `on_message` drops everything unless `web.get_uri()` is a store URL. 10 tests. |
| 10 | MEDIUM | `.py:154-162` | Navigation policy let `data:` and any-origin `blob:` documents load in the window, and sent **every** non-store navigation (hidden iframes, redirects, scripted `location=`, meta refresh) to the system browser — a browser-spam/phishing-nuisance vector needing no user action. Main-frame responses were not origin-checked. | `data:` refused; `blob:` only when its origin is a store host; outside URLs open externally **only** when `nav.is_user_gesture()`, otherwise dropped (applies to subframes, so no third-party document renders); main-frame RESPONSE from a non-store URL is ignored. |
| 11 | LOW (bug) | `.py:133` | `create` handler returned `True` (`open_external(...) or None`), not a WebView/None. | `on_create()` returns `None`; store URL → load here; outside URL → browser on gesture. Verified by `--probe` run. |
| 12 | LOW | `.py:115-131` | WebKit defaults relied on: TLS errors policy not explicit, HTTP credential storage on, third-party cookies accepted, file-URL settings not pinned. | `TLSErrorsPolicy.FAIL`, credential storage off, `CookieAcceptPolicy.NO_THIRD_PARTY`, file-URL access off, top-nav to `data:` off. |
| 13 | LOW | `.py:91-102` | `bash` resolved from `PATH` without an existence check; no charset guard at the `Popen` boundary (relied on callers). | `shutil.which("bash")`; `terminal_script()` raises unless every argv word matches `ARG_RE` (no word may start with `-`). Tested with `a;b`, `-rf`, `[]`, non-str. |
| 14 | LOW | `.py:83-84` | Fallback terminals `foot` (`-e` is not its flag) and `wezterm` (needs `start --`) had wrong/unverified flags. | Removed; `xdg-terminal-exec` is now a hard dependency; remaining fallbacks use known flags. |
| 15 | MEDIUM (assurance) | `.py:248-254` | Self-test's "no shell/eval/sudo" scan was a substring heuristic (`len(v) < 40`) over text before `def self_test`; only 7 behavioural checks; no flatpak, no URL/bridge tests. | Real AST walk over the **whole file except `self_test`**: `shell=` keyword, forbidden call names (`eval/exec/compile/__import__/os.system/os.exec*/os.spawn*/subprocess.run|call|check_*/pty.spawn/socket/ctypes/GLib.spawn*/Gio.Subprocess`), `open()` only for the `"rb"` catalog read, exactly one `Popen` and it must be inside `open_in_terminal`, import allow-list, no `sudo/pkexec/doas/run0/polkit/NOPASSWD/sudoers` tokens in code strings (docstrings excluded), no `/etc /usr /var /tmp /dev /boot /opt /root /srv` constants, no `curl/wget`, no `evaluate_javascript` outside `--probe/--snapshot`. 57 checks total. **Verified: PASS.** |
| 16 | LOW | `.py:297` | `--probe` with no argument → `IndexError` traceback. | Explicit usage message, exit 2. |
| 17 | LOW | `install.sh:12` | `rm -rf "$bin"` on a path derived from `$XDG_DATA_HOME`. | Removes the four installed files by name, then `rmdir`. Verified: uninstall leaves only empty dirs (+ `mimeinfo.cache` written by `update-desktop-database`). |
| 18 | LOW | `install.sh:28` | Launcher path interpolated with `%s` inside double quotes; an unusual `$XDG_DATA_HOME` could break the launcher's quoting. | `printf %q`. |
| 19 | LOW | `install.sh` | No refusal to run as root; `xdg-terminal-exec` not checked. | `EUID==0` → exit 1; dependency list matches the PKGBUILD. |
| 20 | LOW | `pkg/PKGBUILD:10,16-19` | `xdg-terminal-exec` missing from `depends`; launcher generated at build time from a heredoc; no `check()`; no docs installed. | Launcher is a shipped file (`data/omarchy-store-desktop`), `check()` runs `--self-test` with `/usr/bin/python3`, README/SECURITY installed to `/usr/share/doc`, GitHub source URL present as a comment. Built with `makepkg -f`: **verified**. |
| 21 | LOW | `release/*.sha256` (1.0.0) | Checksum file contains `release/omarchy-store-desktop-1.0.0.tar.gz`, so `sha256sum -c` fails from the download directory. | `release.sh` writes the bare file name. 1.1.0 verified with `sha256sum -c … OK`. (1.0.0 file left untouched.) |
| 22 | LOW | `README.md` | No AUR path, no checksum-first instruction, "never" list vaguer than the code. | Rewritten; no pipe-to-shell anywhere in the tree (grep-verified). |

Checklist items with **no finding**: (1) nothing runs as root — true in 1.0.0 and 1.1.0; `.desktop` `Exec=` has no field codes; MIT licence present; no hooks, no `.install`, no systemd units, no listeners, no secrets, no telemetry anywhere in the tree.

## Scanner results (final run, 1.1.0) — every hit classified

`sec_audit.py` (run over `desktop/` with the `pkg/` skip removed so the PKGBUILD is scanned too):

| Hit | Classification |
|---|---|
| ROOT-SILENT `README.md:16,30`, `SECURITY.md:7`, `.py:9` | **False positive** — prose stating that sudo/pkexec are absent. |
| ROOT-SILENT `.py:452,462` | **False positive** — the self-test's own regex of forbidden words and its PASS/FAIL label. |
| REMOTE-CODE `README.md:21` | **Was** a prose mention of a pipe-to-shell; reworded so no such string exists in the tree. |
| SHELL-TRUE `SECURITY.md:9`, `.py:191` | **False positive** — prose: "no shell=True". `grep -n 'shell=True' *.py` → only inside that docstring. |
| CHMOD-WIDE `install.sh:51`, `release.sh:20-21` | **False positive** — `0755` on an executable launcher and on directories, the normal mode. |
| Every hit inside `SECURITY-REVIEW-1.1.0.md` (this file) | **False positive** — it quotes the rules and the forbidden words it classifies. |
| LOW HTTP-PLAIN ×4 | Not printed by the tool; the only `http://` strings in the tree are the `startswith(("https://","http://","mailto:"))` allow-list for *link clicks to the browser* and self-test negative cases. |

`vet.py`: HIGH 1 — `sudoers-write .py:452` = the self-test's forbidden-word regex (**false positive**). MED: `sudo install.sh:43` = the printed hint `sudo pacman -S …` the user is told to run themselves (**by design, nothing executes**); `pkexec` ×6 = prose/self-test text; `env-read .py:83` = `OMARCHY_STORE_URL`, now validated (finding 1); `browser-cookie .py:213` + SECURITY.md ×2 = WebKit cookie jar for the store origin only, under 0700 (**by design**); `sudo README.md:58` = the `sudo pacman -R` uninstall instruction (**by design**).

## Proofs (real output, this machine)

```
$ /usr/bin/python3 omarchy-store-desktop.py --self-test | tail -1
57 checks · SELF-TEST OK

$ makepkg -f   (scratch copy; deps already present, -s deliberately not used)
==> Starting check()...  …  57 checks · SELF-TEST OK
==> Finished making: omarchy-store-desktop 1.1.0-1
$ tar tf omarchy-store-desktop-1.1.0-1-any.pkg.tar.zst | grep -c '^\.INSTALL$'   → 0
  files: usr/bin/omarchy-store-desktop, usr/share/{applications,doc,icons,licenses,omarchy-store-desktop}/… only

$ HOME=<scratch> ./install.sh && <scratch>/.local/bin/omarchy-store-desktop --self-test && ./install.sh --uninstall
  installed: launcher, .desktop, icon, .py · self-test OK via launcher · after uninstall: only empty dirs + mimeinfo.cache

$ timeout 90 env WAYLAND_DISPLAY=wayland-1 OMARCHY_STORE_URL=https://v8.omarchy-store-preview.pages.dev/ \
    /usr/bin/python3 omarchy-store-desktop.py --probe https://v8.omarchy-store-preview.pages.dev/app/btop/
[omarchy-store] catalog refreshed: 1134 apps
{"terminal": true, "argv": ["omarchy", "pkg", "add", "btop"], "title": "Install btop", "button": " Install btop — opens your terminal"}
```

## Not checked (honest list)
- `namcap` — not installed on this machine and installing it needs root; package inspected by hand instead.
- WebKitGTK/GTK/libadwaita upstream security; the `omarchy pkg` / `flatpak` tools; the storefront's JavaScript.
- A real terminal opening on the desktop (`--probe` stubs `open_in_terminal`); the fallback terminals.
- Flatpak listings end to end (the catalog has none today).
- `v8/catalog.json` still carries `desktop_version: "1.8.19"` (the old app's number) which `app.js:393` displays — outside this review's scope; flagged to the storefront owner.
- `v8/app.js` lines 45, 2680, 2881-2882 still *generate* pipe-to-shell one-liners (curl piped into bash) for the website's own "release"/bundle flows. The desktop app refuses the `release` method, so none of that reaches the terminal through the app — but the storefront text fails the gate's pipe-to-shell rule and is flagged to the storefront owner.
