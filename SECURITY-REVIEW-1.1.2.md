# Security review — Omarchy Store desktop 1.1.2

Date: 2026-11-01 · Reviewer: Hermes (Omarchy Store) · Gate: Kernlux software security gate.
Baseline: 1.1.1 (reviewed by a Claude Code cloud session on 30 Oct, `SECURITY-REVIEW-1.1.1.md`; re-run on Arch
on 1 Nov: 82 checks · SELF-TEST OK, 175 tests passed).

## What changed

Exactly two things, and nothing else (verified with `diff` against the 1.1.1 release tarball):

1. `VERSION = "1.1.2"` in `omarchy-store-desktop.py`. No other line of the app changed.
2. The launcher (`/usr/bin/omarchy-store-desktop`, and the per-user launcher written by `install.sh`) gained three lines:

       if [[ -e /proc/driver/nvidia/version && -z "${WEBKIT_DISABLE_DMABUF_RENDERER+x}" ]]; then
         export WEBKIT_DISABLE_DMABUF_RENDERER=1
       fi

Why: on NVIDIA's proprietary driver (tested: RTX 5060 Ti, driver 615.78.08, WebKitGTK 2.54.1, Hyprland) WebKitGTK's
DMA-BUF renderer painted only part of the window — half the width and the top of the page — with stale content
under the rest, so a click landed on a control the user could not see. With the renderer off the full window paints.

## Review of the change

- **Input read:** one fixed kernel path (`/proc/driver/nvidia/version`), tested for existence only. Its contents are
  never read. No user-writable file, argument or environment variable feeds a decision.
- **Respects the user:** if `WEBKIT_DISABLE_DMABUF_RENDERER` is already set (to anything, including empty), it is kept.
- **Effect:** one well-known WebKitGTK variable that selects a rendering path. It does not relax any web security
  setting, sandbox, TLS policy or navigation rule — those are set in code and are unchanged (82 self-test checks).
- **No new privilege, hook, network call, file write, daemon, autostart or update path.** The package still ships the
  same 7 files with no install script.
- `tests/test_security.py` now asserts the launcher's code lines are exactly those four lines (the `if`, the
  `export`, the `fi`, the `exec`), so any further change to the launcher fails the suite.

## Results

- `--self-test` on the shipped file: **82 checks** · SELF-TEST OK
- Test suite: **175 tests** (174 passed, 1 skipped while the archive is being rebuilt — the release-consistency test)
- Live: launched against the preview store on the affected machine; the whole window paints.

## Not checked

Same as 1.1.1: the live storefront's own JavaScript, and release signing (the PKGBUILD checksum pin is the only
protection against a look-alike tarball until the GitHub organisation exists). Non-NVIDIA machines: the launcher
change is a no-op there (the kernel path does not exist), so 1.1.1 behaviour is unchanged.
