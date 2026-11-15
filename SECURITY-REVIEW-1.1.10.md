# Security review: Omarchy Store desktop 1.1.10 (2026-11-15)

Builds on 1.1.9 (SECURITY-REVIEW-1.1.9.md) and earlier reviews.

## Why
Luca, 15 Nov 10:1x: every time he opened the app, a blank tab
`https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile/...` opened in his browser and stayed (ten tabs).

## Root cause (reproduced)
The site's "I'm human" widget (newsletter on the home page, contact, submit) loads a Cloudflare iframe. The app drops every
non-store document, but 1.1.1-1.1.9 handed any non-store navigation to the browser when WebKit flagged it as user-initiated
and a real click had happened in the last 3 s. Right after a click, WebKit flags the widget's iframe load that way.
Reproduced in a real 1.1.9 window against the live site (open_external recorded, not launched): 3 browser launches, all
`challenges.cloudflare.com/...turnstile...`, from simply clicking through home, contact, submit and a plugin page.

## What changed
1. **Only a link the user clicked may leave the app** (`link_click` / `external_allowed`): navigation type LINK_CLICKED,
   a user gesture, not a redirect, aimed at the window or a new window (frame name empty/_blank/_self/_top/_parent).
   Everything else — a frame loading (type OTHER), a redirect, a script-started navigation, a form, a reload, a link aimed at
   a named frame — is dropped silently. Same rule in `on_policy` and `on_create`. WebKitGTK gives navigation actions no
   main-frame flag; a subframe's own load is never LINK_CLICKED, and third-party documents still never render here.
2. Nothing else changed: no host was added to any allow-list, the bridge is still reachable only from committed store
   documents, the 3-second input gate and the safety check are unchanged.

## Site side (Site 8.20)
- Inside the app no Turnstile widget is loaded at all; every form that needs it (newsletter, contact, developer submit,
  support, review) shows one "Open in your browser" link to the same page on omarchystore.com (a clicked link: allowed).
- In browsers the widget loads only when the visitor starts using a form (focus / press), so pages make no request to
  challenges.cloudflare.com until then.

## What was checked
- Self-test: 109 checks pass (new: the link-click rule, refusing OTHER / redirect / no gesture / form / reload / named
  frame; both outside-navigation paths use it and no `is_user_gesture() and take_input()` path remains).
- pytest tests/: 245 tests (244 passed, 1 skipped). New `tests/test_external.py`: the Turnstile iframe after a click opens
  nothing through the real `on_policy`; a clicked outside link opens once; `on_create` follows the same rule.
- Real window, `v8/tools/app_external_gate.sh` (now a deploy gate): 1.1.10 against the LIVE (old) site: 0 launches;
  1.1.10 against the new site: 0 launches, 0 Cloudflare frames or scripts over 60+ s of home / contact / submit / plugin
  page with clicks and focused forms, and the "Open in your browser" button opened exactly https://omarchystore.com/contact/
  once. The same gate run with 1.1.9 against the live site FAILS (3 launches, 6 Cloudflare frames/scripts), so it can fail.

## Unchanged
Navigation allow-lists, bridge, input gate, safety-check requirement, terminal script, add-on lines, update chains,
read-only update check, NVIDIA launcher guard, package file list. No hooks, services, timers or root.
