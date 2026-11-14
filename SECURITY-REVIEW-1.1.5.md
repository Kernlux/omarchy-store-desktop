# Security review: Omarchy Store desktop 1.1.5 (2026-11-13)

1.1.5 is a one-change release on top of 1.1.4 (see SECURITY-REVIEW-1.1.4.md for the full review, still valid).

## What changed
- Category names in the app's own sidebar keep "&" ("Terminal & CLI", "Graphics & Design", "Video & Audio",
  "Education & Science"). They were passed through `safe_title()`, the filter for text that is printed in a
  terminal, which removes "&". They now go through `label_text()`: it removes control characters (0x00-0x1f,
  0x7f-0x9f) and caps the length at 60. These names are only shown in GTK labels that never parse markup.
- `safe_title()` is unchanged and still used for every name that reaches a terminal command line.

## What was checked
- Self-test: 96 checks pass (new check: category labels keep "&" and drop escape sequences).
- pytest tests/: 175 tests (174 passed, 1 skipped).
- Every sidebar entry (Discover, Top Charts, Updates, Installed, New Apps, Themes, Plugins, Screensavers, the 16
  categories, Settings & About) was activated in a real window: each web entry loaded its store page, Updates and
  Installed opened their views, Settings & About opened the About dialog.

## Unchanged
Bridge contract, terminal script, navigation policy, 3-second input gate, NVIDIA launcher guard, package file list.
No install script hooks, no background service, no timer, no root, no new network host.
