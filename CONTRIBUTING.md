# Contributing to the Omarchy Store desktop app

<!-- SECURITY-RULES:BEGIN — keep this block at the top of every README/CONTRIBUTING in the Omarchy Store projects -->
## SECURITY RULES (read before you change anything)

**The goal, in the owner's words:** *"the SAFEST POSSIBLE APP where nobody can poke a hole in it."* This rule outranks features, speed and polish. It covers the Omarchy Store website, its backend worker and Pages Functions, the desktop app, the `/downloads` allow-list, the contact form and inbox, the nightly publish, and every deploy.

There must never be hooks or security vulnerabilities in anything we ship. The store was publicly attacked over an update hook that ran `sudo` in the background, and a paid deep security review (desktop 1.1.1: 5 real holes fixed and about 30 hardening items) can be undone by one careless change.

**Every change, no exceptions:**

1. **Think like the attacker first.** For every input, ask who can write it and what happens if it is hostile. Inputs include settings files, catalog data and app names, window titles, the clipboard, helper/AI text, voice text, anything in `~/.config` or `~/.local/state`, contact-form fields, and anything from the network. All of it is untrusted **data**. It never goes into a shell string, `eval`, `bash -c`, `innerHTML` unescaped, a URL we open without validation, or a path we haven't canonicalised.
2. **Least privilege.** Everything runs at user level. None of the following, ever:
   - `sudo`, `pkexec`, NOPASSWD, a root helper or setuid;
   - systemd/pacman/post-install hooks, remote code or auto-update;
   - a listener on `0.0.0.0` (use 127.0.0.1 or an authenticated 0600 unix socket);
   - an unverified download (it needs a signature or a pinned checksum);
   - secrets in code, logs or screenshots.

   Files are private (0600/0700), writes are atomic, and symlinks are refused.
3. **Smallest surface.** Every feature adds attack surface; do it with fewer permissions, fewer processes and no network if possible. Anything that talks to a network is **off by default**, opt-in, documented, and shows what leaves the machine. When in doubt, leave it out.
4. **Verify, don't assume.** On every change:
   - run the software-security gate;
   - fuzz the inputs and try to break it yourself;
   - record the result in `SECURITY-REVIEW-<version>.md`: PASS/FAIL per check and an honest **NOT CHECKED** list.

   Never claim "no vulnerabilities"; say what was reviewed and what was not.
5. **No last-minute additions.** Nothing is added after a build passed review without re-running the gate on the final diff. Freeze, review, tag.
6. **If a feature conflicts with safety, safety wins.** Stop, explain the risk in plain words, and propose a safer way. Cut the feature before weakening security.

**Website specifics (enforced by `v8/deploy.sh`):**
- **Content-Security-Policy:** `script-src` has no `'unsafe-inline'`, and the site ships no inline `<script>`, no `on…=` handler and no `javascript:` URL (`tools/csp_check.py`).
- **Hostile catalog data never executes** (`tools/redteam_catalog.py`).
- **`/downloads/` serves only the reviewed release** (`tools/desktop_release.py`, the Pages Function allow-list).
- **The contact endpoint** is rate-limited and size-capped, stores text only, and never echoes input or internal errors (`tools/redteam_backend.py`).
- **The desktop app** loads only the store's own hosts (82-check `--self-test`).
<!-- SECURITY-RULES:END -->

