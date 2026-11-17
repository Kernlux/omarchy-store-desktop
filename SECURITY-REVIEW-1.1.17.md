# Security review: Omarchy Store desktop 1.1.17 (2026-11-17)

Builds on 1.1.16 (SECURITY-REVIEW-1.1.16.md).

## Why
Luca, 17 Nov: the store must never show a version the user cannot install, and the app must never talk about mirrors.
The "coming" rows added in 1.1.15 (a newer version that is out upstream but not on the user's mirror yet), the
"+ N coming" badge text and the matching note after Check for updates are removed.

## What changed
- Removed `coming_updates`, `UPSTREAM_RE`, `COMING_WHY`, `Window.upd_coming`, the "coming" group in Updates, the
  "+ N coming" text on the Updates button and the "coming" key in the read-only `info` snapshot the page reads.
- Updates lists only what the user's own package lists offer: checkupdates (fresh, read-only), the AUR helper's list
  and the store's own release. Unchanged from 1.1.14 and earlier.
- Self-test: the old "coming" check is replaced by one that fails if any such code or wording is in the app.
- This is a removal only: no new command, network contact, file write or permission.

## What was checked
- Self-test: 114 checks pass.
- pytest tests/: 284 tests (283 passed, 1 skipped). New `tests/test_no_coming.py`: a fake lagging mirror (catalog says
  Telegram 7.4.4-1, the user has 7.3.2-1, the package list offers nothing) gives no row, no count and no 7.4.4 anywhere
  in the snapshot; an update the package list offers (yt-dlp) is still listed; no removed wording in the source.

## Unchanged
Everything in SECURITY-REVIEW-1.1.16.md and earlier reviews: the bridge contract, terminal script, navigation policy,
3-second input gate, NVIDIA launcher guard, package file list (no install script, no hooks).
