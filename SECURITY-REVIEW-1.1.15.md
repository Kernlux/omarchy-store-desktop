# Security review: Omarchy Store desktop 1.1.15 (2026-11-17)

Builds on 1.1.14 (SECURITY-REVIEW-1.1.14.md).

## Why
Luca, 17 Nov 02:xx: "still not showing the Telegram update". On his PC telegram-desktop 7.3.2-1 is installed; Arch has
7.4.4-1 (extra, 14 Nov); his pacman mirror is Omarchy's STABLE mirror, which still had 7.3.2-1, so `checkupdates` (fresh,
read-only) rightly listed nothing and the Updates view stayed silent. His decision: "what good is an update if you can't be
notified of them": show every update that exists, with what can and cannot be installed now made plain.

## What changed
1. **"Coming" updates (`coming_updates`, `Window.upd_coming`).** For each store app from the repositories (pacman / omarchy
   listings) the app compares three things it already has: the installed version (local package database), the fresh mirror
   list (`checkupdates`, unchanged) and the app's current upstream version from the catalog it already downloads from the
   store (`package.version`, now refreshed nightly for every app). Upstream newer than installed AND not offered by the
   mirror = "New version out, not on your mirror yet", shown with its version arrow and one plain reason ("Omarchy's stable
   mirror gets it later; the Omarchy & system update will install it when it arrives").
   - **No button, nothing to run**: no install path exists for a coming row (self-test: the function builds no button and
     no command); never a mirror switch, never `pacman -S` of a single repository package (no partial upgrade).
   - **No new network contact**: the catalog is the copy the app already fetches from omarchystore.com; no Arch or AUR
     request is added.
   - **Untrusted data**: the catalog version must match a strict pacman version pattern (`UPSTREAM_RE`) and the catalog's
     package name must equal the app's first package; anything else is ignored. Compared with pacman's own vercmp rules
     (`vercmp`, already checked against /usr/bin/vercmp in tests/). Only plain strings reach the page (bounded to 200 rows).
   - **Never twice**: a package the mirror offers is a normal "ready" row, never also "coming"; AUR apps keep the helper's
     `-Qua` result (never "coming"); nothing is shown while a check runs or after a failed check.
2. **Counts**: "total" (the ready count, the red badge) is unchanged; the coming count travels separately (`coming.count`)
   and is shown as an outlined "+N" next to it and in the header button ("Updates 7 + 2 coming").
3. **No background notifier** (security rule): the count is shown when the window opens and after "Check for updates"
   (dock action or menu). The Updates page says so in one line.

## What was checked
- Self-test: 114 checks pass (new: a newer upstream version the mirror does not offer is coming, never for AUR, never when
  the mirror lists it, never from a malformed version; no button in coming_updates).
- pytest tests/: 289 tests (288 passed, 1 skipped). New `tests/test_coming.py` (8): Luca's case with a fake lagging mirror
  (Telegram 7.3.2-1 installed, catalog 7.4.4-1, mirror offers only yt-dlp -> 1 ready + 1 coming), the mirror catching up
  (ready, not coming), up to date, installed newer than the catalog, AUR never coming, busy / failed check, malformed or
  mismatched catalog data ignored, epoch versions.
- Site gate `v8/tools/updates_coming_check.py` (deploy.sh RC 49): the same fake lagging mirror for desktop 1.1.15 and 1.1.14
  (the page works the list out itself for 1.1.14), the outlined count, no button, header "1 ready + 1 coming", and the
  page's vercmp equal to /usr/bin/vercmp on 304 pairs. It fails against the previous live site.
- Real window on Luca's PC (real checkupdates against his Omarchy stable mirror): see the release report.

## Unchanged
Everything in SECURITY-REVIEW-1.1.14.md (Pin to dock), 1.1.13 (downloads), navigation, bridge, input gate, safety check,
terminal script, update chains, Restart, NVIDIA guard, package file list. No hooks, services, timers or root.
