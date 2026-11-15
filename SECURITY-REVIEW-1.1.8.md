# Security review: Omarchy Store desktop 1.1.8 (2026-11-15)

Builds on 1.1.7 (SECURITY-REVIEW-1.1.7.md and earlier reviews still describe everything not listed here).

## Why
Luca, 15 Nov: inside the app, the "Add Omarchy Store Screensaver" sheet showed the website flow (a Download button and
"paste this into a terminal"); Download ends in "This app never saves files", and the floating helper covered the button.
"What's the use of the desktop app if you can't install in one click?" Plugins, screensavers and themes now install the
way apps always have: one button opens the user's own terminal with the exact command; he presses Enter.

## What changed
1. **One new bridge message:** `{"t":"addon","kind":"plugin"|"theme","id":<ID_RE>}`. Nothing else is read from it (extra
   keys are ignored); a wrong kind, a non-string or a bad id is dropped by `parse_message`. Like every bridge message it
   needs a committed store document and a real click / Enter within 3 s (the input gate); one press pays for one terminal.
2. **The command comes only from the app's own copy of the store's lists** (`addon_line`): `themes` from catalog.json and,
   new, `plugins` from `https://<store origin>/plugins.json` (same fetch, same store-only redirect refusal, 20 MiB cap,
   60 s deadline; kept in memory, never written). Shapes, each piece matched against a strict pattern, else refused:
   - store package: `cd /tmp && curl -fLO https://omarchystore.com/theme-packages/<f>.tar.gz && echo "<sha256>  <f>.tar.gz" | sha256sum -c - && mkdir -p ~/.config/omarchy/<plugins|themes> && tar -xzf <f>.tar.gz -C <folder> && omarchy plugin enable <dir>` (or `omarchy-theme-set <name>`)
     — origin fixed in the code (not from the list), path `/theme-packages/[a-z0-9][a-z0-9._-]{0,100}.tar.gz` without `..`,
     hash 64 lower-case hex; the hash is checked before anything is unpacked, and a mismatch stops the chain (`&&`).
   - marketplace plugin: `omarchy plugin add https://github.com/<owner>/<repo>.git --enable` (listed as installable only).
   - theme: `omarchy-theme-set <name>` (built in) or `omarchy-theme-install https://github.com/<owner>/<repo>`.
   Owner / repo: `[A-Za-z0-9][A-Za-z0-9_.-]{0,99}`, exactly two parts, no `..`; dir / name / builtin: `ID_RE`.
   The result is exactly the line the store page shows (its lines joined with `&&`).
3. **Same terminal path as apps:** `terminal_script((ADDON_TAG, (kind, entry)))` prints the line, drops typed-ahead input,
   waits for Enter (Ctrl+C / Ctrl+D cancel), then runs it. `ADDON_TAG` cannot match `ARG_RE`, so no catalog app install
   can produce it, and a list (rather than the tuple the code builds) never takes this branch.
4. The app still never downloads or saves a file itself; the user's own shell does, after Enter. No root, no sudo in any
   line, no pipe into a shell, no hooks, no services, no timers.

## What was checked
- Self-test: 103 checks pass. New: add-on lines equal the store page's lines for all five shapes and are valid bash;
  crafted entries are refused (other host, `//host`, `/downloads/`, `..`, `;`, `$()`, newline, bad or upper-case hash,
  hash with quotes appended, dir with space / `;` / leading `-` / `../`, three-part or non-GitHub repo, theme name with
  `;` or `--help`, wrong kind); the network rule now allows exactly one request site that fetches CATALOG_URL then
  PLUGINS_URL; the only `curl` strings are the app-update line and the store-package line.
- pytest tests/: 218 tests (217 passed, 1 skipped). New `tests/test_addons.py`: every installable plugin (4,387) and
  theme (286) in the current store build gives exactly the page's command; 20 injection payloads x 8 fields refused, and
  `terminal_script` raises for each; 4,000 random entries never produce a character outside the safe alphabet; only the
  store origin and `/theme-packages/` paths; bridge message shapes; the tag cannot come from a catalog install.
- Real window (headless output, test app id, local copy of the site, terminal launcher stubbed to record the script):
  the screensaver, Omarchy Store theme and Gruvbox sheets each opened exactly one terminal script with the expected
  line; a page call without a real click was ignored ("no recent click or key press"); crafted calls with the gate
  armed (`x;id`, kind `app`, an unknown id) opened nothing.
- Site gate `tools/addon_sheet_check.py`: 36 / 36 (Glass, Terminal, White x 1440 / 390 x screensaver, store theme,
  built-in theme, with 1.1.8 and with an older app): one button, the command visible, no Download, no "paste this",
  the helper hidden while a sheet is open.

## Unchanged
Navigation policy, 3-second input gate, terminal script, update chains, read-only update check, NVIDIA launcher guard,
package file list (no install script hooks). Themes' "Apply to Omarchy Store" is a site-only button and is unchanged.
