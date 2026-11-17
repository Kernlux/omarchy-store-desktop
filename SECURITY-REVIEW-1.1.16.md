# Security review: Omarchy Store desktop 1.1.16 (2026-11-17)

Builds on 1.1.15 (SECURITY-REVIEW-1.1.15.md).

## Why
Luca, 17 Nov 02:xx: "this is about EVERY app in the store". The catalog audit found a class of apps the Updates view never
saw at all: the 17 listings installed with an Omarchy command (`omarchy install browser firefox`, Brave, Chrome,
1Password, Dropbox, LM Studio …) have no package list in the catalog, so `store_apps()` skipped them: no ready row, no
"coming" row, not in Installed.

## What changed
- `Window.store_apps()`: for an `omarchy` listing WITHOUT a package list, the package named in the listing's package record
  (`package.name`) is used when it is a valid pacman name (`PKG_RE`, the same pattern every install name must pass) and is
  installed. This only feeds the read-only Updates / Installed lists. Installing still requires `command_for` (unchanged),
  and an update of such an app is a repository package, so it goes through the full Omarchy & system update (no partial
  upgrade), exactly like every other repository app.
- Nothing else: no new command, network contact, file write or permission.

## What was checked
- Self-test: 114 checks pass.
- pytest tests/: 291 tests (290 passed, 1 skipped). New in `tests/test_coming.py`: Firefox (an `omarchy install` listing)
  appears as coming when the mirror lags, as a ready repository app ("Update with system") when the mirror has it, and in
  Installed; a listing whose package name is not a valid package name ("-rf") is ignored.

## Unchanged
Everything in SECURITY-REVIEW-1.1.15.md and earlier reviews.
