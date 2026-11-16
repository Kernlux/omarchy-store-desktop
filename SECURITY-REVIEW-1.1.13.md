# Security review: Omarchy Store desktop 1.1.13 (2026-11-16)

Builds on 1.1.12 (SECURITY-REVIEW-1.1.12.md) and earlier reviews.

## Why
Luca, 16 Nov 18:3x (app 1.1.11, /get-desktop/ "Already have it? Update"): the page's Download button ended in the app's
"This app never saves files. Open the link in your browser instead." Same class as the plugin/theme sheet (15 Nov) on another
page. The site now never offers a file inside the app (Site 8.23: one "Update in terminal" button, file links handed to the
browser through the existing `open` message); 1.1.13 closes the class in the app as well, for any page or older site copy.

## What changed
1. **Downloads go to the browser on a real click (`on_download`).** A download is still cancelled at once: the app never
   writes a downloaded file (no destination is ever set; the self-test checks that `set_destination` / `set_allow_overwrite`
   are never used). Then, only if the address is `https://` AND the user really clicked or pressed a key within 3 s (the same
   input gate as installs), the address is handed to the user's browser (`open_external`, https/http/mailto only). A
   download a script or redirect starts is only cancelled.
2. **`info()` key `installed_version`.** 1.1.12 sent the file's version as `installed`, which the installed-apps list right
   below it in the same dict overwrote, so the store page never saw it (its own Restart bar was not affected). 1.1.13 uses its
   own key, so the site can say "restart" instead of "update" (tested).

## What was checked
- Self-test: 112 checks pass (new: the download handler cancels first and hands on only https after the input gate).
- pytest tests/: 261 tests (260 passed, 1 skipped). New `tests/test_download.py`: a clicked store file goes to the browser
  and is never saved; without a click it is only cancelled; http/file/data/empty are never handed on. `test_restart.py`:
  `installed_version` present and the app list intact.
- Real window, `v8/tools/app_download_gate.sh` (a deploy gate): every visible file link on get-desktop, ignite,
  get-omarchy, the store theme and the store plugin page clicked like a user: 0 "never saves files", every file handed to the
  browser, /get-desktop/ shows no file link and one "Update in terminal" when an update exists. The same gate against the
  previous live site fails (1 "never saves files"), so it can fail.

## Unchanged
Navigation rule, bridge contract, input gate, safety check, terminal script, add-on lines, update chains (the store update is
still `update_command`: download from omarchystore.com, pinned sha256 check, install.sh), read-only update check, Restart,
NVIDIA launcher guard, package file list. No hooks, services, timers or root.
