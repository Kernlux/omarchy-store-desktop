# Security review — Omarchy Store desktop 1.1.3

Date: 2026-11-09 · Reviewer: Hermes (Kernlux Development Labs) · Gate: Kernlux software security gate.
Baseline: 1.1.2 (independent audit the same day: `SECURITY-AUDIT-desktop-2026-11-09.md`).

## What changed (diff against the 1.1.2 release)
1. **F1 fixed.** `Catalog.command_for` checked for duplicate packages (`set(pk)`) before checking every package is a
   string, so a catalog entry such as `"packages": [["btop"]]` raised `TypeError`. The type and charset check now runs first;
   such an entry is refused with no exception. Self-test and tests cover list and dict packages.
2. **F2 fixed.** `STORE_HOSTS` is now exactly `omarchystore.com` and `www.omarchystore.com`. The preview host is no longer
   trusted by any release build (a re-registered preview name could otherwise have been trusted).
3. **F3 fixed.** SECURITY.md now states the catalog request's User-Agent (`OmarchyStore-desktop/<version>`, store host only).
4. Documentation and packaging: source address is Codeberg, maintainer line and counts updated. No code path changed.

Not changed: the bridge contract, terminal script, navigation policy, input gate, NVIDIA launcher guard, package file list
(no install script, no hooks).

## Results
- `--self-test`: **83 checks** · SELF-TEST OK
- Test suite: **174 tests** (173 passed, 1 skipped while the archive is being rebuilt)

## Not checked
Same as 1.1.2: a hostile page inside the app on a real store host, a real install through the password prompt,
terminals other than the default, the storefront's own JavaScript, release signing (the pinned checksum is the protection),
WebKitGTK/GTK/libadwaita themselves.
