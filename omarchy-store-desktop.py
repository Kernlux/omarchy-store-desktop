#!/usr/bin/env python3
"""Omarchy Store — desktop app.

A native GTK4 / libadwaita / WebKitGTK 6 window around https://omarchystore.com. One file, no build step.

SECURITY MODEL — read this before changing anything:
  * This program never installs anything and never runs as root. "Install" opens the USER'S OWN terminal
    with the command printed; nothing runs until they press Enter, and their package manager asks for
    their password in that terminal. There is no sudo, pkexec, polkit, helper, daemon, hook or auto-update.
  * It runs no code from the web page. The page can only send two typed messages over one channel:
    {t:"install", id} and {t:"open", url}. The id is looked up in OUR copy of catalog.json (fetched over
    TLS from the store origin); the command is built from the fixed allow-list METHODS below. The page
    never supplies a command, a package name, or a flag.
  * Only https pages on WEBVIEW_HOSTS (the store and its API worker) load inside the window. Everything else is
    dropped, or handed to the system browser when the user clicked it. No file:, data:, javascript: or http:
    documents, ever. The bridge, the catalog and the home page are limited further, to STORE_HOSTS.
  * The page can act (open a terminal, open the browser) only right after a real click or key press that GTK saw,
    and each press pays for one action — a page cannot open anything on its own, in a loop, or at load time. The
    click dies when a new document commits, so the page a click leads to inherits nothing (a redirect the click
    caused may still open in the browser, once).
  * WebKit may never save a file (every download is cancelled; after a click the URL goes to the browser) and may
    never show a password, prompt() or file-chooser dialog inside this window.
  * It writes only under $XDG_CONFIG_HOME/omarchy-store and $XDG_CACHE_HOME/omarchy-store (0700), plus the
    toolkit's own caches under $XDG_CACHE_HOME (GTK, WebKit, Mesa).
  * Window control on Hyprland (1.1.4): Hyprland ignores a client's own maximize request and a dock may park a window on a
    hidden "special" workspace. hypr_window() talks to the user's OWN compositor over its local socket, and only about
    THIS process's window: it reads the client list, picks the window whose pid is ours, and sends one of two fixed
    requests (maximize on/off, or bring it back to the current workspace). No free text reaches the compositor:
    the address and workspace are checked against strict patterns first. Nothing else is ever sent.
  * `--self-test` proves the allow-list, the validation and the static audit of this file without a display and is
    run by the PKGBUILD's check(); tests/ cover the packaging and the no-hook facts.
"""
import gzip, io, json, os, re, shlex, shutil, socket, subprocess, sys, tarfile, tempfile, urllib.parse, urllib.request
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("WebKit", "6.0")
from gi.repository import Gtk, Adw, WebKit, GLib, Gio, Gdk

APP_ID = "com.omarchystore.Store"
VERSION = "1.1.6"
STORE_HOSTS = ("omarchystore.com", "www.omarchystore.com")
# The store's API worker may load inside the window (it is part of the store) but it is never "the store": no bridge,
# no catalog and no home page may come from it — and it may only be the main frame, never a subframe (the message handler
# exists in every frame). Rule 5 names the store and this worker; www is the store's own alias. No preview host is ever trusted in a release.
WEBVIEW_HOSTS = STORE_HOSTS + ("omarchy-store-backend.omarchystore.workers.dev",)
DEFAULT_HOME = "https://omarchystore.com/"
MAX_URL = 2048          # longest URL we will navigate to or hand to the browser
MAX_MESSAGE = 4096      # longest page→app message we will even parse
MAX_CATALOG = 20 << 20  # 20 MiB cap on catalog.json so a bad server cannot fill the disk
FETCH_DEADLINE_US = 60_000_000  # …and the whole download must finish within 60 s, so a slow drip cannot hold the thread
MAX_PACKAGES = 20       # no listing installs more than this many packages
INPUT_WINDOW_US = 3_000_000   # a bridge action must follow a real click (or Enter) within 3 s; each press pays for ONE action
REFRESH_GAP_US = 60_000_000   # automatic catalog retries (after a page load, while it is still empty) at most once a minute
# Ids and package names: lower-case, start alphanumeric, no spaces, no shell metacharacters, and crucially
# NO leading "-" so a name can never be read as a flag by pacman/flatpak. fullmatch() is used everywhere
# (a trailing newline would slip past re.match + "$").
ID_RE = re.compile(r"[a-z0-9][a-z0-9._+-]{0,63}")
PKG_RE = re.compile(r"[a-z0-9][a-z0-9@._+-]{0,80}")           # pacman / AUR names: Arch's charset ^[a-z0-9@._+-]+$, never a leading - or .
FLATPAK_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}")  # reverse-DNS ids such as com.obsproject.Studio
ARG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9@._+-]{0,254}")    # superset: every word that may reach the terminal
TITLE_RE = re.compile(r"[^A-Za-z0-9 ._+()-]")   # anything else is stripped from text printed in the terminal
CTRL_RE = re.compile(r"[\s\x00-\x1f\x7f]")      # whitespace / control characters never belong in a URL we act on

# The ONLY command shapes this app will ever put in a terminal, keyed by install.method from the catalog,
# each with the charset its package names must match. "release" (a binary we would host ourselves),
# "store", and anything unknown are deliberately absent.
METHODS = {
    "pacman":  (PKG_RE, lambda pk: ["omarchy", "pkg", "add", *pk]),
    "omarchy": (PKG_RE, lambda pk: ["omarchy", "pkg", "add", *pk]),
    "aur":     (PKG_RE, lambda pk: ["omarchy", "pkg", "aur", "add", *pk]),
    "flatpak": (FLATPAK_RE, lambda pk: ["flatpak", "install", "flathub", *pk]),
}

# The fixed script the terminal runs. %s slots are filled with shlex.quote()d text only. Note the order:
# print → wait for Enter → run → print exit code → wait. Nothing runs before the user confirms: Ctrl+C kills the
# script and EOF (Ctrl+D) at the prompt cancels it — `read` failing must never fall through into the command.
TERMINAL_SCRIPT = (
    "[ -t 0 ] || { printf 'Omarchy Store: no terminal attached, nothing was run.\\n' >&2; exit 1; }; "
    "printf '\\n  Omarchy Store  -  %%s\\n\\n' %s; "
    "printf '  This will run:\\n\\n    %%s\\n\\n' %s; "
    "while read -r -t 0.2 _; do :; done; "                                 # drop anything typed ahead: the confirmation must be a fresh Enter
    "printf '  Press Enter to continue, or Ctrl+C to cancel.\\n'; read -r _ || { printf '\\n  Cancelled.\\n'; exit 130; }; "
    "%s; st=$?; printf '\\n  Finished (exit %%s). Press Enter to close.\\n' \"$st\"; read -r _"
)


def log(*a):
    print("[omarchy-store]", *a, file=sys.stderr, flush=True)


def _https_on(uri, hosts):
    """True only for https://<one of hosts>/… — no userinfo trick (https://omarchystore.com@evil/), no odd port, no
    other scheme, and no whitespace or control character anywhere (urlsplit would silently drop tabs and newlines)."""
    if not isinstance(uri, str) or len(uri) > MAX_URL or CTRL_RE.search(uri): return False
    try:
        u = urllib.parse.urlsplit(uri)
        return (u.scheme == "https" and u.hostname in hosts and u.username is None
                and u.password is None and u.port in (None, 443))
    except ValueError:
        return False


def is_store_url(uri):
    """The storefront itself: the only origin that may use the bridge, serve the catalog or be the home page."""
    return _https_on(uri, STORE_HOSTS)


def is_webview_url(uri):
    """What may load inside the window: the storefront and its API worker (rule 5). Nothing else ever renders here."""
    return _https_on(uri, WEBVIEW_HOSTS)


def is_https_url(uri):
    """A plain, well-formed https URL with a host — the only kind the page may ask us to hand to the browser."""
    if not isinstance(uri, str) or len(uri) > MAX_URL or CTRL_RE.search(uri) or not uri.startswith("https://"): return False
    try: u = urllib.parse.urlsplit(uri); return bool(u.hostname) and u.username is None and u.password is None
    except ValueError: return False


def inside_url(uri, main=True):
    """What may be a document inside the window. Main frame: WEBVIEW_HOSTS pages. Subframes: STORE_HOSTS pages only — the
    message handler is reachable from every frame, so no other origin may ever hold a frame here. Both: the empty/srcdoc
    frames a page creates (they inherit its origin) and blob: documents minted by such a page."""
    ok = is_webview_url if main else is_store_url
    return ok(uri) or uri in ("about:blank", "about:srcdoc") or (uri.startswith("blob:") and ok(uri[5:]))


def pick_home_url(env_value):
    """OMARCHY_STORE_URL may only name a store host over https (the same two hosts as STORE_HOSTS).
    Anything else silently falls back, so the env var can never redirect the catalog fetch elsewhere."""
    return env_value if is_store_url(env_value) else DEFAULT_HOME


HOME_URL = pick_home_url(os.environ.get("OMARCHY_STORE_URL", ""))
_o = urllib.parse.urlsplit(HOME_URL)
CATALOG_URL = f"{_o.scheme}://{_o.netloc}/catalog.json"   # origin of HOME_URL, not HOME_URL + path
CONF = os.path.join(GLib.get_user_config_dir(), "omarchy-store")
CACHE = os.path.join(GLib.get_user_cache_dir(), "omarchy-store")


def private_dir(path):
    """mkdir -p with owner-only permissions, also tightening a pre-existing directory."""
    os.makedirs(path, mode=0o700, exist_ok=True); os.chmod(path, 0o700); return path


def parse_message(raw):
    """Page→app message → ("install", id) | ("open", https-url) | None. Typed, bounded, nothing else."""
    if not isinstance(raw, str) or len(raw) > MAX_MESSAGE: return None
    try: m = json.loads(raw)
    except ValueError: return None
    if not isinstance(m, dict): return None
    if m.get("t") == "install":
        v = m.get("id")
        return ("install", v) if isinstance(v, str) and ID_RE.fullmatch(v) else None
    if m.get("t") == "open":
        v = m.get("url")
        return ("open", v) if is_https_url(v) else None
    if m.get("t") == "update":                                            # 1.1.6: the store's Updates page buttons
        v = m.get("what")
        if v in ("all", "store", "system"): return ("update", v)
        return ("update", v) if isinstance(v, str) and v.startswith("app:") and ID_RE.fullmatch(v[4:]) else None
    return None


def label_text(name, fallback):
    """Catalog text shown ONLY in a GTK label (never in a terminal): drop control characters, keep "&" and other
    punctuation (GTK labels here never parse markup, so "Terminal & CLI" shows as written)."""
    t = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", str(name))[:60].strip()
    return t or fallback


def safe_title(name, fallback):
    """Catalog text that gets printed in the terminal: strip control/escape characters so a bad catalog
    could not use ANSI sequences to hide or redraw the command the user is about to confirm."""
    t = TITLE_RE.sub("", str(name))[:60].strip()
    return t or fallback


def input_is_fresh(last_input_us, now_us):
    """True if GTK saw a real click or key press within INPUT_WINDOW_US before now. A page cannot forge GTK input, so
    this is what stops a page from opening terminals or browser windows on its own. Never trusts a clock that went back."""
    return last_input_us is not None and 0 <= now_us - last_input_us <= INPUT_WINDOW_US


VIEWS = ("updates", "update-all", "installed")   # --updates / --update-all / --installed (dock right-click menu)
UPDATE_ORIGIN = "https://omarchystore.com"   # fixed: the app update is always fetched from the store itself, never from a catalog-given URL
VER_RE = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}")
SHA_RE = re.compile(r"[0-9a-f]{64}")
UPDATE_TAG = "__update_app__"                 # cannot match ARG_RE (leading "_"), so no catalog install can ever produce it


def vtuple(v):
    return tuple(int(x) for x in v.split("."))


def app_update(latest):
    """(version, sha256) of a NEWER app published in catalog.json's desktop_latest, or None. Only these two strings are
    taken from the catalog, each checked against a strict pattern; the download URL is built by update_command."""
    if not isinstance(latest, dict): return None
    v, h = latest.get("version"), latest.get("sha256")
    if not (isinstance(v, str) and VER_RE.fullmatch(v) and isinstance(h, str) and SHA_RE.fullmatch(h)): return None
    return (v, h) if vtuple(v) > vtuple(VERSION) else None


def update_command(v, h):
    """The one chained line the user's terminal shows for an app update (the same box as /get-desktop/#update): download
    from the store, check the SHA-256, unpack, run the package's own install.sh as the user. Nothing runs until Enter."""
    if not (isinstance(v, str) and VER_RE.fullmatch(v) and isinstance(h, str) and SHA_RE.fullmatch(h)): raise ValueError("bad update")
    f = f"omarchy-store-desktop-{v}.tar.gz"
    return (f"mkdir -p ~/Downloads && cd ~/Downloads && curl -fLO {UPDATE_ORIGIN}/downloads/{f} && "
            f"echo \"{h}  {f}\" | sha256sum -c && tar xf {f} && cd omarchy-store-desktop-{v} && ./install.sh")


# ---- Updates (1.1.4): read-only, no processes, no network beyond the catalog ----
PACMAN_DB = "/var/lib/pacman"   # the package database every Arch tool reads; opened read-only ("rb"), never written, never run
MAX_DB = 64 << 20               # bound on one sync database (core/extra are a few MiB)


def _rpmvercmp(a, b):
    """libalpm rpmvercmp (lib/libalpm/version.c), ported line by line; ASCII rules like C's isalnum/isdigit/isalpha."""
    if a == b: return 0
    dig = lambda c: "0" <= c <= "9"
    alp = lambda c: "a" <= c <= "z" or "A" <= c <= "Z"
    one = p1 = 0; two = p2 = 0; la, lb = len(a), len(b)
    while one < la and two < lb:
        while one < la and not (dig(a[one]) or alp(a[one])): one += 1
        while two < lb and not (dig(b[two]) or alp(b[two])): two += 1
        if one >= la or two >= lb: break
        if (one - p1) != (two - p2): return -1 if (one - p1) < (two - p2) else 1
        p1, p2 = one, two
        isnum = dig(a[p1])
        while p1 < la and (dig(a[p1]) if isnum else alp(a[p1])): p1 += 1
        while p2 < lb and (dig(b[p2]) if isnum else alp(b[p2])): p2 += 1
        x, y = a[one:p1], b[two:p2]
        if not x: return -1
        if not y: return 1 if isnum else -1
        if isnum:
            x, y = x.lstrip("0"), y.lstrip("0")
            if len(x) != len(y): return 1 if len(x) > len(y) else -1
        if x != y: return -1 if x < y else 1
        one, two = p1, p2
    ra, rb = a[one:], b[two:]
    if not ra and not rb: return 0
    if (not ra and not (rb[:1] and alp(rb[0]))) or (ra[:1] and alp(ra[0])): return -1
    return 1


def vercmp(a, b):
    """pacman's vercmp for [epoch:]version[-release] (checked against /usr/bin/vercmp in tests/)."""
    if a == b: return 0
    def evr(v):
        i = 0
        while i < len(v) and "0" <= v[i] <= "9": i += 1
        e, rest = ((v[:i] or "0"), v[i + 1:]) if i < len(v) and v[i] == ":" else ("0", v)
        ver, sep, rel = rest.rpartition("-")
        return (e, ver, rel) if sep else (e, rest, "")
    ea, va, ra = evr(a); eb, vb, rb = evr(b)
    r = _rpmvercmp(ea, eb) or _rpmvercmp(va, vb)
    return _rpmvercmp(ra, rb) if r == 0 and ra and rb else r


def _desc(text):
    out, key = {}, None
    for line in text.splitlines():
        if line.startswith("%") and line.endswith("%"): key = line[1:-1]; out[key] = []
        elif key and line: out[key].append(line)
    return {k: v[0] for k, v in out.items() if len(v) == 1}


def installed_packages(root=PACMAN_DB):
    """{name: version} of every installed package (local/<pkg>/desc), the same data `pacman -Q` prints."""
    out, local = {}, os.path.join(root, "local")
    for d in (os.listdir(local) if os.path.isdir(local) else []):
        try:
            with open(os.path.join(local, d, "desc"), "rb") as f: m = _desc(f.read(65536).decode("utf-8", "replace"))
        except OSError: continue
        if PKG_RE.fullmatch(m.get("NAME", "")) and m.get("VERSION"): out[m["NAME"]] = m["VERSION"]
    return out


def repo_versions(root=PACMAN_DB):
    """{name: version} from the sync databases as of the user's last `pacman -Sy` (what `pacman -Qu` compares with).
    Read in memory only: tarfile.extractfile into a bytes buffer, never extract()/extractall() to disk."""
    out, sync = {}, os.path.join(root, "sync")
    for f in (sorted(os.listdir(sync)) if os.path.isdir(sync) else []):
        if not f.endswith(".db"): continue
        try:
            with open(os.path.join(sync, f), "rb") as fh: raw = fh.read(MAX_DB + 1)
            if len(raw) > MAX_DB or raw[:2] != b"\x1f\x8b": continue              # gzip (pacman's default) and bounded
            with tarfile.open(fileobj=io.BytesIO(gzip.decompress(raw)), mode="r:") as tf:
                for m in tf:
                    if m.isfile() and m.name.endswith("/desc") and m.size < 65536:
                        d = _desc(tf.extractfile(m).read().decode("utf-8", "replace"))
                        n, v = d.get("NAME", ""), d.get("VERSION", "")
                        if PKG_RE.fullmatch(n) and v and n not in out: out[n] = v      # first repo wins, as in pacman
        except (OSError, EOFError, tarfile.TarError, ValueError): continue
    return out


def pending_updates(root=PACMAN_DB):
    """(installed {name: version}, [(name, installed, newer)]) — the second part equals `pacman -Qu`."""
    have, repo = installed_packages(root), repo_versions(root)
    return have, sorted((n, v, repo[n]) for n, v in have.items() if n in repo and vercmp(repo[n], v) > 0)


CHAIN_NOTE = {"store": "Omarchy Store is updated: close it and open it again when this finishes.", "system": "Restart if it asks."}
CHAIN_RANK = {"store": 0, "apps": 1, "system": 2}   # Update all: the store app FIRST, then other store apps, Omarchy & system LAST


def update_chain(steps):
    """The one line an update shows in the user's terminal. Steps (any order in, fixed order out, each at most once):
    ("store", version, sha256) -> update_command (download, sha256sum -c, install.sh) + a note to reopen the app;
    ("apps", (pkg, ...)) -> yay -S <validated names>;  ("system",) -> omarchy update + "Restart if it asks."
    Joined with && so one failure stops everything after it. Nothing runs until the user presses Enter."""
    if not isinstance(steps, tuple) or not 0 < len(steps) <= 3: raise ValueError("bad steps")
    kinds = [st[0] if isinstance(st, tuple) and st else None for st in steps]
    if len(set(kinds)) != len(kinds) or not set(kinds) <= set(CHAIN_RANK): raise ValueError("bad steps")
    parts = []
    for st in sorted(steps, key=lambda x: CHAIN_RANK[x[0]]):
        if st[0] == "store" and len(st) == 3:
            parts += [update_command(st[1], st[2]), "printf '\\n  %s\\n\\n'" % CHAIN_NOTE["store"]]
        elif st[0] == "apps" and len(st) == 2 and isinstance(st[1], tuple) and 0 < len(st[1]) <= MAX_PACKAGES \
                and len(set(st[1])) == len(st[1]) and all(isinstance(p, str) and PKG_RE.fullmatch(p) for p in st[1]):
            parts.append("yay -S " + " ".join(st[1]))
        elif st[0] == "system" and len(st) == 1:
            parts += ["omarchy update", "printf '\\n  %s\\n'" % CHAIN_NOTE["system"]]
        else: raise ValueError("bad step")
    return " && ".join(parts)


def terminal_script(argv, title):
    """The exact bash -c text for this install. Every argv element must match ARG_RE (the allow-list words
    and validated package names do), so this is a hard stop, not a convenience check. The one exception is the app
    updates, (UPDATE_TAG, steps), whose line comes only from update_chain (every piece checked there)."""
    if isinstance(argv, tuple) and len(argv) == 2 and argv[0] == UPDATE_TAG:
        cmd = update_chain(argv[1])
        return TERMINAL_SCRIPT % (shlex.quote(title), shlex.quote(cmd), cmd)
    if not argv or not all(isinstance(a, str) and ARG_RE.fullmatch(a) for a in argv):
        raise ValueError("argv outside allow-list")
    cmd = " ".join(shlex.quote(a) for a in argv)
    return TERMINAL_SCRIPT % (shlex.quote(title), shlex.quote(cmd), cmd)


DEFAULT_CATS = [("browsers", "Browsers"), ("developer-tools", "Developer Tools"), ("terminal", "Terminal & CLI"), ("ai", "AI"),
                ("graphics", "Graphics & Design"), ("video-audio", "Video & Audio"), ("media", "Entertainment"), ("games", "Games"),
                ("communication", "Social"), ("productivity", "Productivity"), ("education", "Education & Science"),
                ("security", "Security"), ("utilities", "Utilities")]   # the website's order; the catalog's own list wins when present


def cats(v):
    """[(id, name)] from catalog.json categories: ids checked like app ids, names plain and short."""
    out = [(c["id"], label_text(c["name"], c["id"])) for c in (v if isinstance(v, list) else [])[:40]
           if isinstance(c, dict) and isinstance(c.get("id"), str) and ID_RE.fullmatch(c["id"]) and isinstance(c.get("name"), str)]
    return out


class StoreRedirectHandler(urllib.request.HTTPRedirectHandler):
    """urllib follows redirects anywhere — even https→http — and only then lets the caller see where it ended up. This
    refuses a redirect that leaves the store BEFORE the request is sent, so no other host is ever contacted."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_store_url(newurl): log("catalog redirect refused:", str(newurl)[:120]); return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Catalog:
    """Local copy of the public catalog, used ONLY to map an app id → install method + package names.
    Fetched over TLS from the store origin at start; written atomically with owner-only permissions."""
    def __init__(self):
        self.apps = {}; self.latest = None; self.categories = []; self.busy = False; self.last_try = -REFRESH_GAP_US
        try: self.path = os.path.join(private_dir(CACHE), "catalog.json"); self._load()
        except OSError as e: log("cache directory unusable, running without a catalog:", e); self.path = None

    def refresh(self, force=False):
        """Start the background fetch: from App.do_startup (primary instance only), from Reload / Home (force: the user
        asked), and after a page load while the catalog is still empty (offline first start, at most once a minute).
        Never two at once."""
        now = GLib.get_monotonic_time()
        if not self.path or self.busy or (not force and now - self.last_try < REFRESH_GAP_US): return
        self.busy, self.last_try = True, now
        GLib.Thread.new("catalog", self._refresh)

    @classmethod
    def from_apps(cls, apps):
        c = cls.__new__(cls); c.path = None; c.apps = {}; c.latest = None; c.categories = []; c._set(apps); return c

    def _set(self, apps):
        out = {}
        for a in (apps if isinstance(apps, list) else []):
            if not (isinstance(a, dict) and isinstance(a.get("id"), str)): continue
            if a["id"] in out: log("duplicate catalog id ignored:", a["id"][:64]); continue   # first wins, loudly
            out[a["id"]] = a
        self.apps = out

    def _load(self):
        try:
            with open(self.path, "rb") as f: j = json.load(f)
            self._set(j.get("apps", [])); self.latest = j.get("desktop_latest"); self.categories = cats(j.get("categories"))
        except Exception: self.apps = {}                                 # it is a cache: anything unreadable means "no catalog"

    def _refresh(self):
        tmp = None
        try:
            req = urllib.request.Request(CATALOG_URL, headers={"User-Agent": f"OmarchyStore-desktop/{VERSION}"})
            opener = urllib.request.build_opener(StoreRedirectHandler)   # default context: TLS + hostname verified
            with opener.open(req, timeout=20) as r:
                if not is_store_url(r.geturl()): raise ValueError("redirected off the store")
                data, t0 = b"", GLib.get_monotonic_time()
                while len(data) <= MAX_CATALOG:                              # bounded size AND bounded time
                    chunk = r.read1(1 << 16)                                 # read1: returns after ONE socket read, so a drip cannot stall the deadline check
                    if not chunk: break
                    data += chunk
                    if GLib.get_monotonic_time() - t0 > FETCH_DEADLINE_US: raise ValueError("catalog fetch too slow")
            if len(data) > MAX_CATALOG: raise ValueError("catalog too large")
            j = json.loads(data)
            if not isinstance(j, dict) or not isinstance(j.get("apps"), list): raise ValueError("not a catalog")
            fd, tmp = tempfile.mkstemp(dir=CACHE, prefix=".catalog-")  # random name, 0600, O_EXCL: no symlink games
            with os.fdopen(fd, "wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, self.path); tmp = None
            self._set(j["apps"]); self.latest = j.get("desktop_latest"); self.categories = cats(j.get("categories")); log("catalog refreshed:", len(self.apps), "apps")   # the tree we validated, parsed once
        except Exception as e:                                           # offline is normal; the app still works
            log("catalog refresh skipped:", e)
            if tmp:
                try: os.unlink(tmp)
                except OSError: pass
        finally:
            self.busy = False

    def command(self, app_id):
        """argv for the install, or None. None means refused — never a 'best effort' partial command."""
        if not isinstance(app_id, str) or not ID_RE.fullmatch(app_id): return None
        return self.command_for(self.apps.get(app_id))

    def command_for(self, a):
        """The same, for one catalog entry already in hand — so the name shown and the command run come from one read."""
        if not isinstance(a, dict): return None
        inst = a.get("install")
        if not isinstance(inst, dict): return None
        m = inst.get("method"); method = METHODS.get(m) if isinstance(m, str) else None
        pk = inst.get("packages")
        if not method or not isinstance(pk, list) or not 0 < len(pk) <= MAX_PACKAGES: return None
        name_re, build = method
        if not all(isinstance(p, str) and name_re.fullmatch(p) for p in pk): return None   # one bad name (or a non-string) → refuse all, BEFORE anything hashes it
        if len(set(pk)) != len(pk): return None                            # a repeated name is a malformed listing, like any other
        return build(pk)


def find_terminal():
    """The user's own terminal. xdg-terminal-exec (a dependency) honours their default; the fallbacks are
    for systems that removed it. Only terminals whose 'run this command' flag is known are listed."""
    if shutil.which("xdg-terminal-exec"): return ["xdg-terminal-exec"]
    for t, flags in (("ghostty", ["-e"]), ("alacritty", ["-e"]), ("kitty", []), ("gnome-terminal", ["--"]),
                     ("konsole", ["-e"]), ("xterm", ["-e"])):
        if shutil.which(t): return [t, *flags]
    return None


def open_in_terminal(argv, title):
    """Open a terminal that SHOWS the command and waits for Enter. This is the only process the app body ever
    starts (--self-test additionally runs `bash -n` on the generated script). No shell=True: the terminal gets a fixed
    argv; bash gets a fixed script with quoted data.
    Returns the terminal's process handle (so a terminal that exits at once can be reported), or None."""
    term, bash = find_terminal(), shutil.which("bash", path=os.defpath)   # /bin:/usr/bin only, never a PATH-shadowed bash
    if not term or not bash: return None
    try:
        return subprocess.Popen([*term, bash, "-c", terminal_script(argv, title)], start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)   # stderr inherited: a failing launcher says why in our log
    except (OSError, ValueError) as e:
        log("terminal failed to start:", e); return False


HYPR_SIG_RE = re.compile(r"[A-Za-z0-9_]{1,128}")
HYPR_ADDR_RE = re.compile(r"0x[0-9a-f]{1,16}")
HYPR_WS_RE = re.compile(r"[0-9]{1,6}")
HYPR_REQUESTS = {   # the ONLY requests this app ever sends to the compositor; %s slots take a checked address / workspace number
    "maximize": 'dispatch hl.dsp.window.fullscreen({ mode = "maximized", window = "address:%s" })',
    "bring_back": 'dispatch hl.dsp.window.move({ workspace = "%s", follow = false, window = "address:%s" })',
    "focus": 'dispatch hl.dsp.focus({ window = "address:%s" })',
    "minimize": 'dispatch hl.dsp.window.move({ workspace = "special:sd4-minimized", follow = false, window = "address:%s" })',   # SnapDock's own place; a relaunch or the dock brings it back
}


def hypr_ask(req):
    """One request to the user's own Hyprland over its local socket; returns the reply text, or None (not Hyprland, or no answer)."""
    sig, run = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", ""), os.environ.get("XDG_RUNTIME_DIR", "")
    if not HYPR_SIG_RE.fullmatch(sig) or not os.path.isabs(run) or not (req in ("j/clients", "j/activeworkspace") or req.startswith("dispatch hl.dsp.")):
        return None
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(1.0); s.connect(os.path.join(run, "hypr", sig, ".socket.sock")); s.sendall(req.encode())
        out = b""
        while len(out) < (4 << 20):
            b = s.recv(65536)
            if not b: break
            out += b
        return out.decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        s.close()


def hypr_window(action):
    """'maximize' toggles the maximized state of OUR window; 'bring_back' moves it from a hidden special workspace to the
    current one and focuses it. Returns True when the compositor took the request, False when this is not Hyprland."""
    try:
        clients = json.loads(hypr_ask("j/clients") or "null")
        mine = [c for c in clients if isinstance(c, dict) and c.get("pid") == os.getpid()] if isinstance(clients, list) else []
    except ValueError:
        return False
    if len(mine) != 1: return False
    addr = str(mine[0].get("address", ""))
    if not HYPR_ADDR_RE.fullmatch(addr): return False
    if action in ("maximize", "minimize"):
        return hypr_ask(HYPR_REQUESTS[action] % addr) is not None
    if action == "bring_back":
        if not str((mine[0].get("workspace") or {}).get("name", "")).startswith("special:"): return True   # nothing to do
        try: ws = str(json.loads(hypr_ask("j/activeworkspace") or "null").get("id", ""))
        except (ValueError, AttributeError): return False
        if not HYPR_WS_RE.fullmatch(ws): return False
        return hypr_ask(HYPR_REQUESTS["bring_back"] % (ws, addr)) is not None and hypr_ask(HYPR_REQUESTS["focus"] % addr) is not None
    return False


class Window(Adw.ApplicationWindow):
    def __init__(self, app, catalog):
        super().__init__(application=app, title="Omarchy Store", default_width=1380, default_height=900)
        self.catalog = catalog
        try: private_dir(CONF)
        except OSError as e: log("config directory unusable:", e)

        # --- WebKit, locked down ---
        ns = WebKit.NetworkSession.new(os.path.join(CONF, "web"), os.path.join(CACHE, "web"))   # (data dir, cache dir)
        ns.set_tls_errors_policy(WebKit.TLSErrorsPolicy.FAIL)            # a bad certificate is an error, never a prompt
        ns.set_persistent_credential_storage_enabled(False)              # never store HTTP auth credentials
        ns.connect("download-started", lambda _s, d: (d.cancel(), self.note("This app never saves files. Open the link in your browser instead.")))   # hard stop, said out loud
        cm = ns.get_cookie_manager()
        cm.set_persistent_storage(os.path.join(CONF, "cookies.sqlite"), WebKit.CookiePersistentStorage.SQLITE)
        cm.set_accept_policy(WebKit.CookieAcceptPolicy.NO_THIRD_PARTY)
        ucm = WebKit.UserContentManager()
        ucm.register_script_message_handler("store", None)
        ucm.connect("script-message-received::store", self.on_message)
        # 1.1.6: ONE read-only question the page may ask (numbers and names from the local package lists, for the store's own
        # Updates / Installed pages). It returns data only; nothing here can start a process.
        ucm.register_script_message_handler_with_reply("storeinfo", None)
        ucm.connect("script-message-with-reply-received::storeinfo", self.on_info)
        # Tell the page it is inside the desktop app and give it ONE narrow bridge (top frame only).
        ucm.add_script(WebKit.UserScript.new(
            "window.__OMARCHY_DESKTOP__={version:'%s'};document.documentElement.classList.add('desktop-app');"
            "window.omarchyDesktop={install:(id)=>window.webkit.messageHandlers.store.postMessage(JSON.stringify({t:'install',id:String(id)})),"
            "open:(u)=>window.webkit.messageHandlers.store.postMessage(JSON.stringify({t:'open',url:String(u)})),"
            "update:(w)=>window.webkit.messageHandlers.store.postMessage(JSON.stringify({t:'update',what:String(w)})),"
            "info:()=>window.webkit.messageHandlers.storeinfo.postMessage(JSON.stringify({t:'info'})).then(JSON.parse),"
            "check:()=>window.webkit.messageHandlers.storeinfo.postMessage(JSON.stringify({t:'check'})).then(JSON.parse)};" % VERSION,
            WebKit.UserContentInjectedFrames.TOP_FRAME, WebKit.UserScriptInjectionTime.START,
            [f"https://{h}/*" for h in STORE_HOSTS], None))                  # injected on store pages only, never on the worker
        self.web = WebKit.WebView(network_session=ns, user_content_manager=ucm)
        s = self.web.get_settings()
        s.set_enable_javascript(True); s.set_enable_developer_extras(False)
        s.set_javascript_can_open_windows_automatically(False); s.set_enable_media_stream(False)
        s.set_allow_file_access_from_file_urls(False); s.set_allow_universal_access_from_file_urls(False)
        s.set_allow_top_navigation_to_data_urls(False)
        s.set_enable_fullscreen(False); s.set_enable_webgl(False); s.set_enable_webrtc(False)   # no spoofable fullscreen, no GPU/RTC surface
        s.set_media_playback_requires_user_gesture(True)                                        # no autoplay
        s.set_user_agent(f"{s.get_user_agent()} OmarchyStore")           # a vendor token only: the version goes to store pages via __OMARCHY_DESKTOP__, not to every host
        self.web.connect("decide-policy", self.on_policy)
        self.web.connect("create", self.on_create)
        self.web.connect("load-failed", self.on_load_failed)
        self.web.connect("web-process-terminated", self.on_web_crash)         # 1.1.4: the window never goes blank; a plain page with Reload instead
        self.web.connect("load-changed", self.on_load_changed)
        self.web.connect("authenticate", lambda _w, req: (req.cancel(), True)[1])      # never a password prompt — not even WebKit's own
        self.web.connect("run-file-chooser", lambda _w, req: (req.cancel(), True)[1])  # the store never needs a file from your disk
        self.web.connect("script-dialog", self.on_script_dialog)                       # prompt(): no text field a page could label "password"
        self.web.set_background_color(Gdk.RGBA(red=0.03, green=0.04, blue=0.09, alpha=1))
        # Real input only: the page may open a terminal or the browser only right after a click/tap or key press that
        # GTK itself delivered — observed here in the capture phase, before WebKit or the page sees it. A page cannot
        # forge that. Among keys only Enter counts (it activates links and buttons), so typing in the page never arms it.
        # (GestureClick + EventControllerKey, not EventControllerLegacy: PyGObject hands the latter a None event.)
        self.last_input = None
        self.doc_uri = None                                                 # URL of the COMMITTED document: nothing may use the bridge before the first commit
        self.clicked = None                                                 # the one request URI whose user-started navigation still awaits its first response
        click = Gtk.GestureClick(propagation_phase=Gtk.PropagationPhase.CAPTURE, button=0)   # any button, mouse or touch
        click.connect("pressed", self.on_input); self.web.add_controller(click)
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key); self.web.add_controller(keys)

        # --- chrome ---
        tv = Adw.ToolbarView(); hb = Adw.HeaderBar()
        hb.set_decoration_layout(":close")                                  # the toolkit's own maximize/minimize requests are ignored on Hyprland
        mx = Gtk.Button(icon_name="window-maximize-symbolic", tooltip_text="Maximize / restore (double-click the title too)")
        mx.connect("clicked", lambda *_: self.toggle_max()); hb.pack_end(mx)
        mn = Gtk.Button(icon_name="window-minimize-symbolic", tooltip_text="Minimize (open Omarchy Store again, or click it in the dock, to bring it back)")
        mn.connect("clicked", lambda *_: hypr_window("minimize") or self.minimize()); hb.pack_end(mn)
        dbl = Gtk.GestureClick(button=1); dbl.connect("pressed", lambda _g, n, _x, _y: n == 2 and self.toggle_max()); hb.add_controller(dbl)
        for icon, tip, cb in (("go-previous-symbolic", "Back", lambda *_: self.web.go_back()),
                              ("go-next-symbolic", "Forward", lambda *_: self.web.go_forward()),
                              ("go-home-symbolic", "Store home", lambda *_: (self.catalog.refresh(force=True), self.web.load_uri(HOME_URL))),
                              ("view-refresh-symbolic", "Reload", lambda *_: (self.catalog.refresh(force=True), self.web.reload()))):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip); b.connect("clicked", cb); hb.pack_start(b)
        self.upd_btn = Gtk.Button(visible=False, css_classes=["suggested-action", "pill"], tooltip_text="Open Updates")
        self.upd_btn.connect("clicked", lambda *_: self.show_view("updates")); hb.pack_end(self.upd_btn)
        menu = Gio.Menu()
        for label, action in (("Check for updates", "win.check-update"), ("About Omarchy Store", "app.about"), ("Security model", "app.security"), ("Quit", "app.quit")):
            menu.append(label, action)
        hb.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))
        self.title_w = Adw.WindowTitle(title="Omarchy Store", subtitle="installs run in your terminal · nothing runs in the background")
        hb.set_title_widget(self.title_w); tv.add_top_bar(hb)
        self.stack = Gtk.Stack(hexpand=True, vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self.web, "web")
        self.upd_box, self.inst_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14), Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for name, box in (("updates", self.upd_box), ("installed", self.inst_box)):
            box.set_margin_top(24); box.set_margin_bottom(24); box.set_margin_start(24); box.set_margin_end(24)
            sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER); sc.set_child(Adw.Clamp(maximum_size=900, child=box)); self.stack.add_named(sc, name)
        self.nav_badges, self.nav_targets, self.sidebar_list = {}, {}, None   # 1.1.6: no native sidebar; the store page's own sidebar has Updates + Installed
        body = Gtk.Box(); body.append(self.stack)
        self.toast = Adw.ToastOverlay(); self.toast.set_child(body); tv.set_content(self.toast)
        self.set_content(tv)
        self.web.connect("notify::title", lambda *_: self.stack.get_visible_child_name() == "web" and self.title_w.set_title(self.web.get_title() or "Omarchy Store"))
        self.web.load_uri(HOME_URL)
        self.upd = {"have": {}, "pending": [], "store": None, "busy": False, "when": ""}
        a = Gio.SimpleAction.new("check-update", None); a.connect("activate", lambda *_: (self.show_view("updates"), self.check_updates(asked=True))); self.add_action(a)
        self.check_updates()                                                # once, when the window opens: local package lists + the catalog copy

    def toggle_max(self):
        if not hypr_window("maximize"):                                    # other desktops honour the toolkit's request
            (self.unmaximize if self.is_maximized() else self.maximize)()

    def on_script_dialog(self, web, dialog):
        return dialog.get_dialog_type() == WebKit.ScriptDialogType.PROMPT  # True = swallowed; alert/confirm keep WebKit's plain dialog

    def on_input(self, *_):
        self.last_input = GLib.get_monotonic_time()
        return False                                                        # observe only; the page still gets the event

    def on_key(self, controller, keyval, keycode, state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter): self.on_input()
        return False

    def on_load_changed(self, web, event):
        if event == WebKit.LoadEvent.COMMITTED:
            self.last_input = None                                          # a new document never inherits the click that led to it
            self.doc_uri = web.get_uri()                                    # the document actually showing (get_uri() alone may already name a pending load)
        elif event == WebKit.LoadEvent.FINISHED and not self.catalog.apps: self.catalog.refresh()   # back online after an offline start

    def take_input(self):
        """Spend the most recent real input: True once per click/key press (unless a new document committed since), False
        for anything a page does on its own."""
        fresh = input_is_fresh(self.last_input, GLib.get_monotonic_time()); self.last_input = None; return fresh

    # ---- navigation policy: only the store inside; outside links to the browser, only on a user click ----
    def on_policy(self, web, decision, dtype):
        if dtype in (WebKit.PolicyDecisionType.NAVIGATION_ACTION, WebKit.PolicyDecisionType.NEW_WINDOW_ACTION):
            nav = decision.get_navigation_action(); uri = nav.get_request().get_uri() or ""
            if inside_url(uri):
                if nav.is_user_gesture(): self.clicked = uri                # a download this turns into may go to the browser
                if dtype == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION:   # target=_blank / window.open: never a second window
                    decision.ignore()
                    if is_webview_url(uri): self.web.load_uri(uri)         # a store page opens here; a blank popup opens nowhere
                    return True
                return False                                                # default handler: load it
            decision.ignore()
            # Clicked by the user → their browser, ONE window per click (every navigation a click handler starts carries
            # the gesture). Not clicked (hidden iframe, redirect, script, meta refresh) → dropped. Applies to subframes too,
            # so no third-party document ever renders in this WebView.
            if nav.is_user_gesture() and self.take_input(): self.open_external(uri)
            return True
        if dtype == WebKit.PolicyDecisionType.RESPONSE:
            resp = decision.get_response(); uri = resp.get_uri() or ""; headers = resp.get_http_headers()
            clicked = uri == self.clicked                                   # a click vouches for the first response after it, never a later one
            if clicked or decision.is_main_frame_main_resource(): self.clicked = None
            if not inside_url(uri, main=decision.is_main_frame_main_resource()):   # worker documents: main frame only
                decision.ignore(); log("refused document:", uri[:120]); return True
            attachment = bool(headers) and (headers.get_one("Content-Disposition") or "").strip().lower().startswith("attachment")
            if attachment or not decision.is_mime_type_supported():        # a download (e.g. the tarball), however it is labelled
                decision.ignore()                                            # we never write files; the browser may, if the user clicked
                if clicked and self.take_input(): self.open_external(uri)   # and it spends the click, like every other action
                return True
        return False

    def on_create(self, web, nav):
        """window.open / target=_blank. We never create a second WebView: store URLs load here, outside
        URLs go to the browser if the user clicked, and the page gets no window handle either way."""
        uri = nav.get_request().get_uri() or ""
        if is_store_url(uri): self.web.load_uri(uri)
        elif nav.is_user_gesture() and self.take_input(): self.open_external(uri)
        return None

    def open_external(self, uri):
        """Hand a link to the system browser / mail client. https, http and mailto only — never file:,
        javascript:, or any custom scheme that could reach another application's handler."""
        if isinstance(uri, str) and len(uri) <= MAX_URL and not CTRL_RE.search(uri) and uri.startswith(("https://", "http://", "mailto:")):
            Gtk.UriLauncher.new(uri).launch(self, None, None, None); return True
        return False

    def on_load_failed(self, web, event, uri, err):
        # Our own policy decisions — an outside link handed to the browser, a download — surface here as "cancelled" or
        # "interrupted by policy change". Those are not failures and must not replace the page the user is looking at.
        if err.matches(WebKit.network_error_quark(), WebKit.NetworkError.CANCELLED) or \
           err.matches(WebKit.policy_error_quark(), WebKit.PolicyError.FRAME_LOAD_INTERRUPTED_BY_POLICY_CHANGE): return False
        html = f"""<html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#070b16;color:#e6ecff;font-family:Inter,system-ui">
        <div style="text-align:center;max-width:460px"><div style="font-size:44px">⌁</div><h2>Can't reach the store</h2>
        <p style="color:#9aa6c4">The app loads omarchystore.com live so you always see the current catalog. Check your connection and press Reload.</p>
        <p style="font-size:12px;color:#5b6a8c">{GLib.markup_escape_text(str(err))}</p></div></body></html>"""
        # load_alternate_html keeps the failed URL as the page's address, so Reload retries the store — not this HTML.
        self.web.load_alternate_html(html, uri if is_webview_url(uri or "") else HOME_URL, HOME_URL)
        return True

    def on_web_crash(self, web, reason):
        log("page engine stopped:", reason.value_nick if hasattr(reason, "value_nick") else reason)
        html = """<html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#070b16;color:#e6ecff;font-family:Inter,system-ui">
        <div style="text-align:center;max-width:460px"><h2>The page stopped</h2>
        <p style="color:#9aa6c4">The page engine stopped responding. Press Reload at the top to open the store again.</p></div></body></html>"""
        self.web.load_alternate_html(html, HOME_URL, HOME_URL)              # Reload then loads the store, not this text

    # ---- the one bridge from the page ----
    def on_message(self, ucm, value):
        if not is_store_url(self.doc_uri or ""): return                    # only a committed store document may talk to us — never one still loading in
        if not value.is_string(): return                                    # a string or nothing, decided before any conversion
        msg = parse_message(value.to_string())
        if not msg: return
        if not self.take_input(): log("bridge message ignored: no recent click or key press"); return
        kind, v = msg
        if kind == "open": self.open_external(v); return
        if kind == "update": self.page_update(v); return
        entry = self.catalog.apps.get(v)                                    # one read: the refresh thread may swap the dict under us
        argv = self.catalog.command_for(entry)
        if not argv:
            self.note("The catalog could not be fetched yet — press Reload, or use the command shown on its page." if not self.catalog.apps
                      else "That listing can't be installed from here. Use the command shown on its page."); return
        name = safe_title(entry.get("name") or v, v)
        proc = open_in_terminal(argv, f"Install {name}")
        if proc is None: self.note("No terminal emulator found. Copy the command from the app page instead."); return
        if proc is False: self.note("Your terminal could not be started (see the log). Copy the command from the app page instead."); return
        self.note(f"Opened your terminal. Read the command shown there: Enter runs it, Ctrl+C cancels.")
        t0 = GLib.get_monotonic_time()
        def watch():                                                        # reap the terminal when it exits (no zombie); one that dies at once never showed the command
            if proc.poll() is None: return True
            if proc.returncode and GLib.get_monotonic_time() - t0 < 2_000_000:
                self.note(f"Your terminal closed right away (exit {proc.returncode}). Copy the command from the app page instead.")
            return False
        GLib.timeout_add(500, watch)

    # ---- sidebar, Updates and Installed (1.1.4) ----
    NAV = (("Discover", "starred-symbolic", "/"), ("Top Charts", "view-list-ordered-symbolic", "/charts/"),
           ("Updates", "software-update-available-symbolic", "updates"), ("Installed", "object-select-symbolic", "installed"),
           ("New Apps", "starred-symbolic", "/new/"))
    BROWSE = (("Themes", "/themes/"), ("Plugins", "/plugins/"), ("Screensavers", "/screensavers/"))

    def build_sidebar(self):
        lb = Gtk.ListBox(css_classes=["navigation-sidebar"], selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav_badges, self.nav_targets = {}, {}
        def row(label, icon, target, badge=False):
            r = Gtk.ListBoxRow(); bx = Gtk.Box(spacing=10, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
            if icon: bx.append(Gtk.Image(icon_name=icon))
            bx.append(Gtk.Label(label=label, xalign=0, hexpand=True))
            if badge:
                bl = Gtk.Label(visible=False, css_classes=["os-badge"]); bx.append(bl); self.nav_badges[target] = bl
            r.set_child(bx); self.nav_targets[r] = target; lb.append(r); return r
        for label, icon, target in self.NAV: row(label, icon, target, badge=target in ("updates", "installed"))
        head = Gtk.Label(label="Browse", xalign=0, css_classes=["dim-label", "caption-heading"], margin_top=12, margin_start=12)
        r = Gtk.ListBoxRow(selectable=False, activatable=False); r.set_child(head); lb.append(r)
        for label, path in self.BROWSE: row(label, None, path)
        for cid, name in (self.catalog.categories or DEFAULT_CATS): row(name, None, f"/category/{cid}/")
        r = Gtk.ListBoxRow(selectable=False, activatable=False); r.set_child(Gtk.Separator(margin_top=8, margin_bottom=8)); lb.append(r)
        row("Settings & About", "help-about-symbolic", "about")
        lb.connect("row-activated", lambda _lb, r: self.nav(self.nav_targets.get(r, "")))
        self.sidebar_list = lb
        logo = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True, height_request=29, margin_top=14, margin_bottom=10, margin_start=14, margin_end=14,
                           alternative_text="Omarchy Store")
        lockup = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lockup.png")   # the official lockup PNG installed next to this file
        if os.path.isfile(lockup): logo.set_filename(lockup)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); col.append(logo); col.append(lb)
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, width_request=232, vexpand=True); sc.set_child(col)
        css = Gtk.CssProvider()
        css.load_from_string(".os-badge{background:#2F6BFF;color:#fff;border-radius:999px;padding:0 8px;font-weight:700;font-size:12px}"
                             ".os-badge.muted{background:alpha(currentColor,.15);color:inherit}.os-hl{background:alpha(#2F6BFF,.16);border-radius:12px}")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        return sc

    def select_nav(self, target):
        if self.sidebar_list is None: return
        r = next((r for r, t in self.nav_targets.items() if t == target), None)
        if r: self.sidebar_list.select_row(r)

    def nav(self, target):
        if target == "about": self.get_application().about(); return
        if target in ("updates", "installed"): self.show_view(target); return
        if isinstance(target, str) and target.startswith("/"):
            self.stack.set_visible_child_name("web"); self.select_nav(target); self.web.load_uri(urllib.parse.urljoin(HOME_URL, target))

    def show_view(self, name, focus_all=False):
        """1.1.6: Updates and Installed are the store's own pages (same blue sidebar), filled from on_info()."""
        if name not in ("updates", "installed"): return
        self.stack.set_visible_child_name("web"); self.web.load_uri(urllib.parse.urljoin(HOME_URL, f"/{name}/"))
        self.render_updates()

    def check_updates(self, asked=False):
        """User-triggered (button / menu / dock action) or once when the window opens. Reads the local package database and
        the catalog copy; the only network contact is the usual catalog fetch from the store when the user asks."""
        if self.upd["busy"]: return
        self.upd["busy"] = True; self.render_updates()
        if asked: self.catalog.refresh(force=True)
        res = {}
        def work():
            try: res["have"], res["pending"] = pending_updates()
            except Exception as e: log("package database unreadable:", e); res["have"], res["pending"] = {}, []
        th = GLib.Thread.new("updates", work)
        tries = [0]
        def finish():
            tries[0] += 1
            if ("pending" not in res or self.catalog.busy) and tries[0] < 60: return True
            th.join()
            self.upd.update(have=res.get("have", {}), pending=res.get("pending", []), store=app_update(self.catalog.latest), busy=False,
                            when=GLib.DateTime.new_now_local().format("%H:%M"))
            self.render_updates(); self.render_installed()
            if asked: self.note(f"{self.upd_total()} update(s) found." if self.upd_total() else "Everything is up to date.")
            return False
        GLib.timeout_add(500, finish)

    def store_apps(self):
        """[(entry, packages, method)] for catalog apps whose packages are all installed (pacman/omarchy/AUR listings)."""
        have, out = self.upd["have"], []
        for a in list(self.catalog.apps.values()):
            inst = a.get("install") if isinstance(a.get("install"), dict) else {}
            pk, m = inst.get("packages"), inst.get("method")
            if m in ("pacman", "omarchy", "aur") and self.catalog.command_for(a) and all(p in have for p in pk): out.append((a, tuple(pk), m))
        return sorted(out, key=lambda x: safe_title(x[0].get("name") or x[0]["id"], x[0]["id"]).lower())

    def upd_apps(self):
        newer = {n: (v, w) for n, v, w in self.upd["pending"]}
        return [(a, pk, newer) for a, pk, m in self.store_apps() if m != "aur" and any(p in newer for p in pk)]

    def upd_total(self):
        return len(self.upd["pending"]) + (1 if self.upd["store"] else 0)

    def info(self):
        """Read-only snapshot for the store's Updates / Installed pages: bounded, plain values only."""
        u = self.upd; apps = self.upd_apps(); st = u["store"]
        return {"v": 1, "version": VERSION, "busy": bool(u["busy"]), "when": u["when"], "total": self.upd_total(),
                "store": {"latest": st[0]} if st else None,
                "apps": [{"id": a["id"], "name": safe_title(a.get("name") or a["id"], a["id"]),
                          "from": nw[next(p for p in pk if p in nw)][0], "to": nw[next(p for p in pk if p in nw)][1]} for a, pk, nw in apps][:200],
                "system": {"count": len(u["pending"]), "list": [[n, v, w] for n, v, w in u["pending"]][:9]},
                "installed": [{"id": a["id"], "name": safe_title(a.get("name") or a["id"], a["id"]), "version": u["have"].get(pk[0], ""),
                               "aur": m == "aur"} for a, pk, m in self.store_apps()][:2000]}

    def on_info(self, ucm, value, reply):
        try:
            if not is_store_url(self.doc_uri or "") or not value.is_string() or len(value.to_string()) > 64: reply.return_error_message("refused"); return True
            t = (json.loads(value.to_string()) or {}).get("t")
            if t == "check": self.check_updates(asked=True)
            elif t != "info": reply.return_error_message("refused"); return True
            reply.return_value(type(value).new_string(value.get_context(), json.dumps(self.info())))   # the JSC value type, without a 7th gi import
        except Exception as e:
            log("info request failed:", e); reply.return_error_message("unavailable")
        return True

    def page_update(self, what):
        """A button on the store's Updates page (already input-checked in on_message): the SAME chains the native view used."""
        u = self.upd; apps = self.upd_apps(); st = u["store"]
        if what == "store":
            if st: self.run_update((("store", st[0], st[1]),), f"Update Omarchy Store to {st[0]}")
            return
        if what == "system": self.run_update((("system",),), "Update Omarchy & system"); return
        if what == "all":
            steps = (((("store", st[0], st[1]),) if st else ()) + ((("apps", tuple(sorted({p for _, pk, nw in apps for p in pk if p in nw}))),) if apps else ())
                     + (("system",),))
            self.run_update(steps, "Update all"); return
        hit = next(((a, pk, nw) for a, pk, nw in apps if a["id"] == what[4:]), None)
        if not hit: self.note("That app has no update in your last package list. Press Check for updates."); return
        a, pk, nw = hit
        self.run_update((("apps", tuple(p for p in pk if p in nw)),), f"Update {safe_title(a.get('name') or a['id'], a['id'])}")

    def run_update(self, steps, title):
        proc = open_in_terminal((UPDATE_TAG, steps), title)
        if not proc: self.note("No terminal could be opened. Run the command yourself: omarchy update"); return
        self.note("Opened your terminal. Read the command shown there: Enter runs it, Ctrl+C cancels.")
        GLib.timeout_add(500, lambda: proc.poll() is None)                 # reap the terminal when it exits

    def _clear(self, box):
        while (c := box.get_first_child()): box.remove(c)

    def _row(self, title, sub, btn=None, cb=None, hl=False):
        r = Gtk.Box(spacing=12, margin_top=4, margin_bottom=4, css_classes=["os-hl"] if hl else [])
        if hl: r.set_margin_start(0)
        t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, margin_start=10 if hl else 0, margin_top=6 if hl else 0, margin_bottom=6 if hl else 0)
        t.append(Gtk.Label(label=title, xalign=0, css_classes=["heading"], wrap=True)); t.append(Gtk.Label(label=sub, xalign=0, css_classes=["dim-label"], wrap=True))
        r.append(t)
        if btn:
            b = Gtk.Button(label=btn, valign=Gtk.Align.CENTER, css_classes=["pill", "suggested-action"] if hl else ["pill"], margin_end=10 if hl else 0)
            b.connect("clicked", lambda *_: cb()); r.append(b)
        return r

    def _group(self, box, title, count, desc, btn=None, cb=None):
        g = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card"])
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=14, margin_bottom=14, margin_start=16, margin_end=16); g.append(inner)
        h = Gtk.Box(spacing=10); h.append(Gtk.Label(label=title, xalign=0, css_classes=["title-3"]))
        if count is not None: h.append(Gtk.Label(label=str(count), css_classes=["os-badge"] if count else ["os-badge", "muted"], valign=Gtk.Align.CENTER))
        h.append(Gtk.Box(hexpand=True))
        if btn:
            b = Gtk.Button(label=btn, css_classes=["pill"]); b.connect("clicked", lambda *_: cb()); h.append(b)
        inner.append(h)
        if desc: inner.append(Gtk.Label(label=desc, xalign=0, wrap=True, css_classes=["dim-label"]))
        box.append(g); return inner

    def render_updates(self):
        u, box = self.upd, self.upd_box; self._clear(box)
        total, apps, store = self.upd_total(), self.upd_apps(), u["store"]
        for key, n in (("updates", total), ("installed", len(self.store_apps()))):
            bl = self.nav_badges.get(key)
            if bl: bl.set_label(str(n)); bl.set_visible(n > 0); bl.set_css_classes(["os-badge"] if key == "updates" else ["os-badge", "muted"])
        self.upd_btn.set_label(f"Updates  {total}"); self.upd_btn.set_visible(total > 0)
        head = Gtk.Box(spacing=12); tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        tb.append(Gtk.Label(label="Updates", xalign=0, css_classes=["title-1"]))
        tb.append(Gtk.Label(label="Checking…" if u["busy"] else (f"Checked at {u['when']}" if u["when"] else "Not checked yet"), xalign=0, css_classes=["dim-label"]))
        head.append(tb)
        chk = Gtk.Button(label="Check for updates", css_classes=["pill"], valign=Gtk.Align.CENTER, sensitive=not u["busy"])
        chk.connect("clicked", lambda *_: self.check_updates(asked=True)); head.append(chk)
        steps = (((("store", store[0], store[1]),) if store else ()) + ((("apps", tuple(sorted({p for _, pk, nw in apps for p in pk if p in nw}))),) if apps else ())
                 + (("system",),))
        self.all_btn = Gtk.Button(label="Update all", css_classes=["pill", "suggested-action"], valign=Gtk.Align.CENTER, sensitive=not u["busy"])
        self.all_btn.connect("clicked", lambda *_: self.run_update(steps, "Update all"))
        head.append(self.all_btn); box.append(head)
        box.append(Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"], label=(
            "Nothing here runs by itself: an update starts only when you press a button here and then Enter in your own terminal. "
            "No background checks, no timers, no hooks, and this app never runs anything as root.")))
        g = self._group(box, "Apps", len(apps) + (1 if store else 0), "Apps you installed from the store. Each button opens your terminal with the exact command.")
        if store:
            g.append(self._row(f"Omarchy Store {store[0]} available", f"You have {VERSION}. Close and reopen the app after it updates.", "Update",
                               lambda st=store: self.run_update((("store", st[0], st[1]),), f"Update Omarchy Store to {st[0]}"), hl=True))
        for a, pk, nw in apps:
            name = safe_title(a.get("name") or a["id"], a["id"]); p0 = next(p for p in pk if p in nw)
            todo = tuple(p for p in pk if p in nw)
            g.append(self._row(name, f"{nw[p0][0]}  →  {nw[p0][1]}", "Update", lambda t=todo, n=name: self.run_update((("apps", t),), f"Update {n}")))
        if not apps and not store: g.append(Gtk.Label(label="Your store apps are up to date.", xalign=0))
        g.append(Gtk.Label(label="Apps from the AUR are updated by Omarchy & system below.", xalign=0, wrap=True, css_classes=["dim-label", "caption"]))
        pend = u["pending"]; om = next(((v, w) for n, v, w in pend if n == "omarchy"), None)
        g2 = self._group(box, "Omarchy & system", len(pend), "Omarchy, Linux, the desktop and every system package, plus AUR apps and Omarchy's own "
                         "migrations, in one go: the same as Omarchy menu › Update. It may ask you to restart, so Update all runs it last.",
                         "Update Omarchy & system", lambda: self.run_update((("system",),), "Update Omarchy & system"))
        if om: g2.append(self._row(f"Omarchy {om[0]}  →  {om[1]}", "Omarchy itself"))
        for n, v, w in [x for x in pend if x[0] != "omarchy"][:8]: g2.append(self._row(n, f"{v}  →  {w}"))
        if len(pend) > 9: g2.append(Gtk.Label(label=f"+{len(pend) - 9 if om else len(pend) - 8} more", xalign=0, css_classes=["dim-label"]))
        if not pend: g2.append(Gtk.Label(label="No newer packages in your last package list. The button still runs Omarchy's own update check.", xalign=0, wrap=True))

    def render_installed(self):
        box = self.inst_box; self._clear(box); items = self.store_apps()
        box.append(Gtk.Label(label="Installed", xalign=0, css_classes=["title-1"]))
        box.append(Gtk.Label(label=f"{len(items)} apps from the store are installed on this computer." if items else "No apps from the store found on this computer yet.",
                             xalign=0, css_classes=["dim-label"]))
        for a, pk, m in items:
            name = safe_title(a.get("name") or a["id"], a["id"]); aid = a["id"]
            box.append(self._row(name, f"{self.upd['have'].get(pk[0], '')} · {'AUR' if m == 'aur' else 'Arch / Omarchy package'}", "Open page",
                                 lambda i=aid: self.nav(f"/app/{i}/")))

    def note(self, text):
        t = Adw.Toast(title=text, timeout=5); t.set_use_markup(False); self.toast.add_toast(t)


class App(Adw.Application):
    def __init__(self, fetch=True):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.fetch = fetch; self.catalog = Catalog()                     # the cached copy now; the network refresh waits for do_startup
        for name, cb in (("quit", lambda *_: self.quit()), ("about", self.about), ("security", self.security)):
            a = Gio.SimpleAction.new(name, None); a.connect("activate", cb); self.add_action(a)
        self.start_view = None
        v = Gio.SimpleAction.new("show-view", GLib.VariantType.new("s")); v.connect("activate", lambda _a, p: self.open_view(p.get_string())); self.add_action(v)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

    def do_startup(self):
        """Runs in the primary instance only (GApplication uniqueness): a second launch never refetches the catalog."""
        Adw.Application.do_startup(self)
        if self.fetch: self.catalog.refresh()

    def do_activate(self):
        win = self.props.active_window
        if win is None: win = Window(self, self.catalog)
        else: hypr_window("bring_back")                                    # a second launch brings a window a dock had hidden back to this workspace
        win.present()
        if self.start_view: v, self.start_view = self.start_view, None; self.open_view(v)

    def open_view(self, view):
        """Dock / launcher actions (Desktop Actions in the .desktop file): they only OPEN a view; nothing is run."""
        if view not in VIEWS: return
        if self.props.active_window is None: self.start_view = view; self.activate(); return
        w = self.props.active_window; hypr_window("bring_back"); w.present()
        w.show_view("installed" if view == "installed" else "updates", focus_all=view == "update-all")
        if view in ("updates", "update-all"): w.check_updates(asked=view == "updates")

    def about(self, *_):
        d = Adw.AboutDialog(application_name="Omarchy Store", application_icon=APP_ID, version=VERSION,
                            developer_name="Kernlux Development Labs", website="https://omarchystore.com",
                            issue_url="https://omarchystore.com/contact/", license_type=Gtk.License.MIT_X11,
                            comments="The community app store for Omarchy Linux. Independent project, not affiliated with Omarchy or 37signals.\n\n"
                                     "Pin it: right-click its icon in your dock and choose Pin / Keep in dock.")
        d.present(self.props.active_window)

    def security(self, *_):
        d = Adw.AlertDialog(heading="How installs work", body=(
            "• Clicking Install opens YOUR terminal with the command shown. Nothing runs until you press Enter, and your "
            "package manager asks for your password there — this app never sees it.\n"
            "• The app never runs as root, has no background service, no update hook, and never runs code from the web page.\n"
            "• Only the store (omarchystore.com and www, its API worker) loads inside this window. Links you click that "
            "lead elsewhere open in your browser; nothing a page starts on its own goes anywhere.\n"
            "• The page can only ask for an install or open a link right after you click or press a key — never on its own.\n"
            "• It writes only to ~/.config/omarchy-store and ~/.cache/omarchy-store (plus GTK's and WebKit's own caches under ~/.cache).\n\n"
            "Source: the whole app is one readable Python file, omarchy-store-desktop.py. "
            "Run it with --self-test to check these claims yourself."))
        d.add_response("ok", "Got it"); d.present(self.props.active_window)


def self_test():
    """No display, no network, no files written. Proves the allow-list, the input validation, and — by walking
    the AST of this very file — that the app body contains no shell, eval, privilege or system-path shape."""
    import ast
    c = Catalog.from_apps([
        {"id": "btop", "name": "btop", "install": {"method": "pacman", "packages": ["btop"]}},
        {"id": "omt", "install": {"method": "omarchy", "packages": ["omarchy-thing"]}},
        {"id": "bottles", "install": {"method": "aur", "packages": ["bottles"]}},
        {"id": "obs", "install": {"method": "flatpak", "packages": ["com.obsproject.Studio"]}},
        {"id": "fpbad", "install": {"method": "flatpak", "packages": ["com.x.Y;id"]}},
        {"id": "fpflag", "install": {"method": "flatpak", "packages": ["--user"]}},
        {"id": "evil", "install": {"method": "pacman", "packages": ["btop; rm -rf ~"]}},
        {"id": "mixed", "install": {"method": "pacman", "packages": ["btop", "x$(id)"]}},
        {"id": "flag", "install": {"method": "pacman", "packages": ["--noconfirm"]}},
        {"id": "caps", "install": {"method": "pacman", "packages": ["Btop"]}},
        {"id": "at", "install": {"method": "pacman", "packages": ["foo@bar"]}},
        {"id": "dot", "install": {"method": "pacman", "packages": [".hidden"]}},
        {"id": "dup", "install": {"method": "pacman", "packages": ["btop", "btop"]}},
        {"id": "rel", "install": {"method": "release", "url": "https://x/y.pkg.tar.zst"}},
        {"id": "sto", "install": {"method": "store", "packages": ["btop"]}},
        {"id": "nopk", "install": {"method": "pacman"}},
        {"id": "strpk", "install": {"method": "pacman", "packages": "btop"}},
        {"id": "many", "install": {"method": "pacman", "packages": ["p%d" % i for i in range(MAX_PACKAGES + 1)]}},
        {"id": "lstpk", "install": {"method": "pacman", "packages": [["btop"]]}}, {"id": "dctpk", "install": {"method": "aur", "packages": [{"x": 1}]}},
        {"id": "noinst", "name": "x"}, {"id": 7, "install": {"method": "pacman", "packages": ["btop"]}},
    ])
    S = "https://omarchystore.com/"; W = "https://omarchy-store-backend.omarchystore.workers.dev/api"
    checks = [
        (c.command("btop") == ["omarchy", "pkg", "add", "btop"], "pacman → omarchy pkg add"),
        (c.command("omt") == ["omarchy", "pkg", "add", "omarchy-thing"], "omarchy → omarchy pkg add"),
        (c.command("bottles") == ["omarchy", "pkg", "aur", "add", "bottles"], "aur → omarchy pkg aur add"),
        (c.command("obs") == ["flatpak", "install", "flathub", "com.obsproject.Studio"], "flatpak → flatpak install flathub"),
        (c.command("evil") is None, "shell metacharacters in package name refused"),
        (c.command("mixed") is None, "one bad package name refuses the whole listing"),
        (c.command("flag") is None, "package name starting with '-' (flag injection) refused"),
        (c.command("caps") is None, "upper-case pacman package name refused"),
        (c.command("at") == ["omarchy", "pkg", "add", "foo@bar"] and c.command("dot") is None, "'@' accepted in a package name, leading '.' refused"),
        (c.command("dup") is None, "a repeated package name refuses the listing"),
        (c.command("fpbad") is None and c.command("fpflag") is None, "flatpak id with metacharacters / leading '-' refused"),
        (c.command("rel") is None, "'release' (self-hosted binary) method refused"),
        (c.command("sto") is None, "'store' method refused"),
        (c.command("nopk") is None and c.command("strpk") is None, "missing / non-list packages refused"),
        (c.command("many") is None, f"more than {MAX_PACKAGES} packages refused"),
        (c.command("noinst") is None and c.command(7) is None, "listing without install block / non-string id refused"),
        (c.command("lstpk") is None and c.command("dctpk") is None, "non-string package (list / dict) refused without raising"),
        (c.command("nope") is None, "unknown id refused"),
        (c.command("../../etc") is None and c.command("Btop") is None, "bad id refused"),
        (c.command("a" * 65) is None and c.command("a" * 64) is None, "over-long id refused"),
        (c.command("btop\n") is None and ID_RE.fullmatch("btop\n") is None, "trailing newline in id refused"),
        (parse_message('{"t":"install","id":"btop"}') == ("install", "btop"), "install message parsed"),
        (parse_message('{"t":"open","url":"https://github.com/x"}') == ("open", "https://github.com/x"), "https open parsed"),
        (parse_message('{"t":"open","url":"http://github.com/x"}') is None, "non-https open refused"),
        (parse_message('{"t":"open","url":"javascript:alert(1)"}') is None, "javascript: open refused"),
        (parse_message('{"t":"open","url":"file:///etc/passwd"}') is None, "file: open refused"),
        (parse_message('{"t":"open","url":"https://%s"}' % ("a" * MAX_URL)) is None, "over-long open url refused"),
        (parse_message('{"t":"open","url":"https://"}') is None and parse_message('{"t":"open","url":"https://a b"}') is None
         and parse_message('{"t":"open","url":"https://a\\tb.com/"}') is None, "hostless / whitespace open url refused"),
        (parse_message('{"t":"install","id":123}') is None and parse_message('{"t":"install","id":"btop\\n"}') is None, "non-string / newline id refused"),
        (parse_message('{"t":"exec","cmd":"ls"}') is None and parse_message('[1]') is None and parse_message('nope') is None, "unknown type / non-object / non-JSON refused"),
        (parse_message('{"t":"install","id":"' + "a" * MAX_MESSAGE + '"}') is None, "oversize message refused"),
        (parse_message(None) is None, "non-string message refused"),
        (parse_message('{"t":"update","what":"all"}') == ("update", "all") and parse_message('{"t":"update","what":"app:btop"}') == ("update", "app:btop"), "update message parsed"),
        (parse_message('{"t":"update","what":"app:btop;rm"}') is None and parse_message('{"t":"update","what":"root"}') is None and parse_message('{"t":"update","what":1}') is None, "bad update message refused"),
        (is_store_url(S) and is_store_url("https://www.omarchystore.com/app/btop/") and not is_store_url("https://v8.omarchy-store-preview.pages.dev/"), "store hosts accepted; the preview host is not trusted"),
        (is_store_url("https://omarchystore.com:443/x"), "explicit :443 accepted"),
        (not is_store_url("http://omarchystore.com/"), "http:// store refused for in-window nav"),
        (not is_store_url("https://evil.com/") and not is_store_url("https://omarchystore.com.evil.com/"), "non-store host refused"),
        (not is_store_url("https://evil.omarchystore.com/"), "unknown subdomain refused"),
        (not is_store_url("https://omarchystore.com@evil.com/"), "userinfo trick refused"),
        (not is_store_url("https://omarchystore.com:8443/"), "odd port refused"),
        (not is_store_url("file:///etc/passwd") and not is_store_url("javascript:alert(1)") and not is_store_url("data:text/html,x"), "file:/javascript:/data: refused"),
        (not is_store_url("https://omarchystore.com/" + "a" * MAX_URL) and not is_store_url(None), "over-long / non-string url refused"),
        (not is_store_url("https://omarchystore.com\t/") and not is_store_url("https://omarchystore.com\n/"), "tab / newline inside url refused"),
        (not is_store_url(" https://omarchystore.com/") and not is_store_url("https://@omarchystore.com/") and not is_store_url("https://omarchystore.com:443@evil.com/"), "leading space / empty userinfo / userinfo+port refused"),
        (is_store_url("HTTPS://OMARCHYSTORE.COM/") and not is_store_url("https://omarchystore.com./") and not is_store_url("https://[omarchystore.com]/"), "scheme/host case folded; trailing-dot and bracketed hosts refused"),
        (all(shlex.quote(w) == w for w in ("omarchy", "pkg", "aur", "add", "flatpak", "install", "flathub", "a0.z_9+@-", "com.obsproject.Studio")), "every allow-list word and valid name is shell-safe unquoted (printed text == executed text)"),
        (inside_url("about:blank") and inside_url("about:srcdoc") and inside_url("blob:" + S + "x") and inside_url(W) and not inside_url("blob:https://evil.com/x")
         and not inside_url("data:text/html,x") and not inside_url("about:config") and not inside_url("https://evil.com/"), "in-window document shapes: store/worker, about:blank/srcdoc, store blob only"),
        (parse_message('{"t":"open","url":"https://omarchystore.com@evil.com/"}') is None, "open url with userinfo refused"),
        (is_webview_url(W) and not is_store_url(W) and not is_webview_url("https://evil.com/") and not is_webview_url("http" + W[5:]), "worker host may load in the view but is not the store"),
        (not inside_url(W, main=False) and inside_url(S + "x", main=False) and not inside_url("blob:" + W, main=False) and inside_url("about:blank", main=False), "worker documents may be the main frame only, never a subframe"),
        (pick_home_url(W) == DEFAULT_HOME, "worker host refused as home / catalog origin"),
        (input_is_fresh(None, 0) is False and input_is_fresh(0, INPUT_WINDOW_US) and not input_is_fresh(0, INPUT_WINDOW_US + 1) and not input_is_fresh(5, 1), "bridge actions need a fresh real input"),
        (StoreRedirectHandler().redirect_request(urllib.request.Request(S), None, 302, "Found", {}, "https://evil.com/c.json") is None
         and StoreRedirectHandler().redirect_request(urllib.request.Request(S), None, 302, "Found", {}, "http://omarchystore.com/c.json") is None
         and StoreRedirectHandler().redirect_request(urllib.request.Request(S), None, 302, "Found", {}, "https://www.omarchystore.com/c.json") is not None,
         "catalog redirect off the store refused before it is followed"),
        (pick_home_url("http://evil.example/") == DEFAULT_HOME and pick_home_url("") == DEFAULT_HOME, "bad OMARCHY_STORE_URL falls back"),
        (pick_home_url("https://www.omarchystore.com/app/btop/") == "https://www.omarchystore.com/app/btop/" and pick_home_url("https://v8.omarchy-store-preview.pages.dev/") == DEFAULT_HOME, "store OMARCHY_STORE_URL kept, preview host refused"),
        (CATALOG_URL.endswith("/catalog.json") and CATALOG_URL.count("/") == 3, "catalog URL built from origin only"),
        ("\x1b" not in safe_title("btop\x1b[2J; rm -rf ~", "x") and ";" not in safe_title("a;b", "x"), "control/escape chars stripped from terminal title"),
        (safe_title("\x1b\x07", "btop") == "btop" and len(safe_title("a" * 200, "x")) == 60, "empty title falls back, length capped"),
        (cats([{"id": "terminal", "name": "Terminal & CLI"}, {"id": "x", "name": "A\x1b[2J&B"}]) == [("terminal", "Terminal & CLI"), ("x", "A[2J&B")], "category labels keep '&', drop control chars"),
        (shlex.quote("a b;c") == "'a b;c'", "shell quoting present"),
    ]
    sc = terminal_script(["omarchy", "pkg", "add", "btop"], "Install btop")
    checks += [
        (sc.index("read -r _") < sc.index("; omarchy pkg add btop; st=$?"), "terminal script waits for Enter BEFORE running"),
        (sc.count("omarchy pkg add btop") == 2, "terminal script prints exactly the command it runs"),
    ]
    sc2 = terminal_script(["flatpak", "install", "flathub", "com.obsproject.Studio"], "Install OBS Studio (1.2)")
    checks += [
        ("read -r _ ||" in sc and "exit 130" in sc, "terminal script cancels, never runs, on EOF (Ctrl+D) at the prompt"),
        (not shutil.which("bash") or all(subprocess.run([shutil.which("bash"), "-n", "-c", x], capture_output=True).returncode == 0 for x in (sc, sc2)),
         "generated terminal scripts are valid bash (bash -n, pacman and flatpak shapes)"),
    ]
    for bad in (["omarchy", "pkg", "add", "a;b"], ["-rf"], [], ["x", 1]):
        try: terminal_script(bad, "t"); checks.append((False, f"terminal_script refuses {bad!r}"))
        except (ValueError, TypeError): checks.append((True, f"terminal_script refuses {bad!r}"))

    # ---- static audit of this file: everything except this function ----
    src = open(__file__, encoding="utf-8").read(); tree = ast.parse(src)
    selftests = [fn for fn in tree.body if isinstance(fn, ast.FunctionDef) and fn.name == "self_test"]
    skip = {id(n) for fn in selftests for n in ast.walk(fn)}
    nodes = [n for n in ast.walk(tree) if id(n) not in skip]
    main_block = next((n for n in reversed(tree.body) if isinstance(n, ast.If) and "__name__" in ast.unparse(n.test)), None)
    main_ids = {id(n) for n in ast.walk(main_block)} if main_block else set()
    docs = {ast.get_docstring(n, clean=False) for n in nodes if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))}

    def dotted(n):
        if isinstance(n, ast.Name): return n.id
        if isinstance(n, ast.Attribute): return dotted(n.value) + "." + n.attr
        return "?"
    refs = [(dotted(n), n) for n in nodes if isinstance(n, (ast.Name, ast.Attribute))]   # every name, not only call sites
    calls = [(dotted(n.func), n) for n in nodes if isinstance(n, ast.Call)]
    FORBIDDEN = {"eval", "exec", "compile", "__import__", "getattr", "setattr", "delattr", "globals", "locals", "vars", "breakpoint",
                 "importlib", "sys.modules", "sys.path", "os.system", "os.popen", "os.putenv", "os.unsetenv", "os.open", "os.write",
                 "os.truncate", "os.rename", "os.link", "os.symlink", "os.mkdir", "os.remove", "os.chown", "os.utime", "pty",
                 "ctypes", "pathlib", "subprocess.call", "subprocess.check_call", "subprocess.check_output", "subprocess.run",
                 "subprocess.getoutput", "subprocess.getstatusoutput", "urllib.request.urlopen", "urllib.request.urlretrieve"}
    FORBIDDEN_PREFIXES = ("os.exec", "os.spawn", "os.posix_spawn", "os.fork", "os.set", "GLib.spawn", "Gio.Subprocess", "Gio.AppInfo",
                          "Gio.DesktopAppInfo", "Gio.File", "shutil.", "tempfile.")
    ALLOWED_PREFIXED = {"shutil.which", "tempfile.mkstemp"}
    DUNDERS = ("__dict__", "__getattribute__", "__class__", "__subclasses__", "__globals__", "__builtins__", "__code__", "__doc__")
    forbidden_hits = sorted({f for f, _ in refs if f in FORBIDDEN or (f.startswith(FORBIDDEN_PREFIXES) and f not in ALLOWED_PREFIXED) or f.endswith(DUNDERS)})
    # open() only as the audited `open(path, "rb")` read of the catalog cache — two positional arguments, no keywords
    # 1.1.4: plus exactly two read-only opens of the pacman database, inside installed_packages / repo_versions
    db_ids = {id(n) for fn in tree.body if isinstance(fn, ast.FunctionDef) and fn.name in ("installed_packages", "repo_versions") for n in ast.walk(fn)}
    DB_OPENS = {"open(os.path.join(local, d, 'desc'), 'rb')", "open(os.path.join(sync, f), 'rb')"}
    bad_open = [ast.unparse(n)[:50] for f, n in calls if f == "open" and not (len(n.args) == 2 and ast.unparse(n.args[0]) == "self.path" and getattr(n.args[1], "value", "") == "rb" and not n.keywords)
                and not (id(n) in db_ids and ast.unparse(n) in DB_OPENS)]
    tar_refs = [(f, n) for f, n in refs if f.split(".")[0] in ("tarfile", "gzip", "io") or f.endswith((".extract", ".extractall"))]
    tar_ok = all(id(n) in db_ids for _, n in tar_refs) and not any(f.endswith((".extract", ".extractall")) for f, _ in tar_refs) \
        and sorted({f for f, _ in tar_refs}) == ["gzip", "gzip.decompress", "io", "io.BytesIO", "tarfile", "tarfile.TarError", "tarfile.open"]
    db_refs = [n for f, n in refs if f == "PACMAN_DB"]
    db_ok = PACMAN_DB == "/var/lib/pacman" and len(db_refs) == 4   # the constant + three default arguments, nothing else
    singletons = {f: [n for g, n in refs if g == f] for f in ("WebKit.UserScript.new", "Gtk.UriLauncher.new", "ucm.register_script_message_handler")}
    load_html = [f for f, _ in refs if f.endswith(("load_html", "load_plain_text", "load_bytes"))]
    popen_sites = [n for f, n in calls if f.endswith("Popen")]
    POPEN = "subprocess.Popen([*term, bash, '-c', terminal_script(argv, title)], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)"
    oit = next(fn for fn in tree.body if isinstance(fn, ast.FunctionDef) and fn.name == "open_in_terminal")
    popen_refs = [f for f, _ in refs if f.endswith("Popen")]
    net_opens = [n for f, n in calls if f == "opener.open"]; net_reqs = [n for f, n in calls if f == "urllib.request.Request"]
    refresh_ids = {id(n) for fn in nodes if isinstance(fn, ast.FunctionDef) and fn.name == "_refresh" for n in ast.walk(fn)}
    net_refs = [(f, n) for f, n in refs if f in ("urllib.request.build_opener", "urllib.request.Request", "opener.open", "opener")]
    net_pinned = sorted(f for f, _ in net_refs) == ["opener", "opener", "opener.open", "urllib.request.Request", "urllib.request.build_opener"] and all(id(n) in refresh_ids for _, n in net_refs)
    ALLOWED_IMPORTS = {"gzip", "io", "json", "os", "re", "shlex", "shutil", "socket", "subprocess", "sys", "tarfile", "tempfile", "urllib.parse", "urllib.request", "gi", "gi.repository"}
    ask_ids = {id(n) for fn in tree.body if isinstance(fn, ast.FunctionDef) and fn.name == "hypr_ask" for n in ast.walk(fn)}
    sock_refs = [(f, n) for f, n in refs if f.startswith("socket")]
    sock_ok = bool(sock_refs) and all(id(n) in ask_ids for _, n in sock_refs) and sorted({f for f, _ in sock_refs}) == ["socket", "socket.AF_UNIX", "socket.SOCK_STREAM", "socket.socket"]
    ask_sites = [n for f, n in calls if f == "hypr_ask"]
    ask_args_ok = all(ast.unparse(n.args[0]) in ("'j/clients'", "'j/activeworkspace'") or ast.unparse(n.args[0]).startswith("HYPR_REQUESTS[") for n in ask_sites)
    imports = {a.name for n in nodes if isinstance(n, ast.Import) for a in n.names} | {n.module or "" for n in nodes if isinstance(n, ast.ImportFrom)}
    aliased = [a.name for n in nodes if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names if a.asname]
    from_names = {a.name for n in nodes if isinstance(n, ast.ImportFrom) for a in n.names}
    env_writes = [ast.unparse(n)[:60] for n in nodes if isinstance(n, (ast.Assign, ast.AugAssign, ast.Delete, ast.AnnAssign))
                  for t in (n.targets if isinstance(n, (ast.Assign, ast.Delete)) else [n.target]) if isinstance(t, ast.Subscript) and dotted(t.value) == "os.environ"] + \
                 [f for f, _ in calls if f.startswith("os.environ.") and f.rsplit(".", 1)[-1] not in ("get",)]
    # Strings: the compiled constants (so "su" + "do" is seen folded as "sudo"), bytes included, plus every f-string's literal
    # parts joined — everything except the docstrings, which describe the rules and therefore name the forbidden words.
    def consts(code, acc):
        for c in code.co_consts:
            if isinstance(c, (str, bytes)): acc.append(c if isinstance(c, str) else c.decode("latin1"))
            elif hasattr(c, "co_consts") and not (c.co_name == "self_test" and c.co_firstlineno == selftests[0].lineno): consts(c, acc)
        return acc
    strs = [c for c in consts(compile(src, __file__, "exec"), []) if c not in docs]
    strs += ["".join(v.value if isinstance(v, ast.Constant) else (v.value.value if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Constant) and isinstance(v.value.value, str) else "")
                     for v in n.values) for n in nodes if isinstance(n, ast.JoinedStr)]
    priv = [x for x in strs if re.search(r"\b(sudo|pkexec|doas|run0|polkit|NOPASSWD|sudoers|systemd|systemctl|setuid|setgid)\b", x)]
    syspath = [x for x in strs if re.match(r"/(bin|sbin|lib|lib32|lib64|etc|usr|var|tmp|dev|boot|opt|root|srv|proc|sys|run|home|mnt|media)(/|$)", x) and x != "/var/lib/pacman"]
    # 1.1.4: the ONE allowed fetch word is the curl inside update_command (the line the user's terminal shows for an app update)
    upd_fn = next(fn for fn in tree.body if isinstance(fn, ast.FunctionDef) and fn.name == "update_command")
    upd_strs = set(consts(update_command.__code__, [])) | {"".join(v.value if isinstance(v, ast.Constant) else "" for v in n.values) for n in ast.walk(upd_fn) if isinstance(n, ast.JoinedStr)}
    fetchers = [x for x in strs if re.search(r"\b(curl|wget)\b", x) and x not in upd_strs]
    H0 = "0" * 64; ul = update_command("9.9.9", H0)
    upd_ok = (ul == f'mkdir -p ~/Downloads && cd ~/Downloads && curl -fLO https://omarchystore.com/downloads/omarchy-store-desktop-9.9.9.tar.gz && echo "{H0}  omarchy-store-desktop-9.9.9.tar.gz" | sha256sum -c && tar xf omarchy-store-desktop-9.9.9.tar.gz && cd omarchy-store-desktop-9.9.9 && ./install.sh'
              and UPDATE_ORIGIN == "https://omarchystore.com")
    upd_refuse = True
    for bad in (("1.2", H0), ("1.2.3;rm", H0), ("1.2.3\n", H0), ("1.2.3", "z" * 64), ("1.2.3", H0 + "\n"), ("1.2.3", H0[:63]), (None, H0), ("1.2.3", None)):
        try: update_command(*bad); upd_refuse = False
        except ValueError: pass
    upd_newer = (app_update({"version": "999.0.0", "sha256": H0}) == ("999.0.0", H0) and app_update({"version": VERSION, "sha256": H0}) is None
                 and app_update({"version": "0.0.1", "sha256": H0}) is None and app_update({"version": "999.0.0", "sha256": "x"}) is None
                 and app_update({"version": "999.0.0", "sha256": H0, "url": "https://evil.example/x.tar.gz"}) == ("999.0.0", H0) and app_update(None) is None)
    sc_chain = update_chain((("system",), ("apps", ("btop", "zen-browser-bin")), ("store", "9.9.9", H0)))
    chain_ok = sc_chain == (ul + " && printf '\\n  Omarchy Store is updated: close it and open it again when this finishes.\\n\\n' && yay -S btop zen-browser-bin"
                            " && omarchy update && printf '\\n  Restart if it asks.\\n'") and "sudo" not in sc_chain
    chain_refuse = True
    for bad in ((), (("apps", ("btop;id",)),), (("apps", ("-x",)),), (("apps", ("a", "a")),), (("system",), ("system",)), (("rm",),), (("apps", []),), [("system",)]):
        try: update_chain(bad); chain_refuse = False
        except (ValueError, TypeError, KeyError): pass
    vc_ok = all(vercmp(a, b) == w for a, b, w in (("1.0", "1.0", 0), ("1:1.0", "2.0", 1), ("1.0-2", "1.0-1", 1), ("1.0rc1", "1.0", -1), ("1.0a", "1.0", -1),
                                                    ("1.01", "1.1", 0), ("1.0.1", "1.0", 1), ("2.0", "10.0", -1), ("1..0", "1.0", 1), ("1.0-1", "1.0", 0)))
    try: terminal_script([UPDATE_TAG, "9.9.9", H0], "t"); tag_list_refused = False      # a list (what a catalog build makes) never takes the update branch
    except ValueError: tag_list_refused = True
    qa = {id(n) for fn in tree.body if isinstance(fn, ast.FunctionDef) and fn.name in ("probe", "snapshot") for n in ast.walk(fn)}
    eval_js = [f for f, n in calls if id(n) not in qa and f.endswith(("evaluate_javascript", "run_javascript", "call_async_javascript_function"))]
    def calls_in(name):
        fn = next((f for f in nodes if isinstance(f, ast.FunctionDef) and f.name == name), None)
        return {dotted(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)} if fn else set()
    writers = sorted(f for f, _ in refs if f in ("tempfile.mkstemp", "os.replace", "os.makedirs", "os.chmod", "os.fdopen", "os.unlink", "os.fsync"))
    assigns = {t.id: ast.unparse(n.value) for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    private_args = sorted(ast.unparse(n.args[0]) for f, n in calls if f == "private_dir")
    mkstemp_in_cache = all(any(k.arg == "dir" and getattr(k.value, "id", "") == "CACHE" for k in n.keywords) for f, n in calls if f == "tempfile.mkstemp")
    checks += [
        (len(selftests) == 1 and all(id(n) in main_ids for f, n in refs if f == "self_test"), "exactly one self_test, called only from the __main__ block"),
        (not forbidden_hits, f"no eval/exec/getattr/import tricks, os.system/exec/spawn/fork/setuid, Gio.Subprocess/AppInfo, GLib.spawn, socket/ctypes/pty, raw os writes, shutil/tempfile beyond which/mkstemp, urlopen/urlretrieve {forbidden_hits}"),
        (not bad_open, f"open() only as the two-argument 'rb' read of the catalog cache {bad_open}"),
        (len(popen_sites) == 1 and popen_sites[0] in list(ast.walk(oit)) and ast.unparse(popen_sites[0]) == POPEN and len(popen_refs) == 1,
         "exactly one subprocess.Popen, inside open_in_terminal, with exactly the audited arguments (no shell=, no env=, no preexec_fn=)"),
        (net_pinned and len(net_opens) == 1 and getattr(net_opens[0].args[0], "id", "") == "req" and len(net_reqs) == 1
         and getattr(net_reqs[0].args[0], "id", "") == "CATALOG_URL", "exactly one network request, of CATALOG_URL, through the store-only redirect handler, all inside Catalog._refresh"),
        (imports <= ALLOWED_IMPORTS and not aliased and from_names <= {"Gtk", "Adw", "WebKit", "GLib", "Gio", "Gdk"},
         f"imports limited to {sorted(ALLOWED_IMPORTS)}, no aliases, only the six gi namespaces (got {sorted(imports - ALLOWED_IMPORTS)} {aliased} {sorted(from_names - {'Gtk', 'Adw', 'WebKit', 'GLib', 'Gio', 'Gdk'})})"),
        (sock_ok, "socket is used only inside hypr_ask, AF_UNIX stream only (the user's own compositor socket)"),
        (ask_args_ok and len(HYPR_REQUESTS) == 4 and all(v.startswith("dispatch hl.dsp.") for v in HYPR_REQUESTS.values()),
         "compositor requests are only the client list, the active workspace, and the four fixed HYPR_REQUESTS"),
        (not HYPR_ADDR_RE.fullmatch('0x1" }) hl.exec_cmd("x') and not HYPR_WS_RE.fullmatch("1\") ") and HYPR_ADDR_RE.fullmatch("0x55a4fbb251c0"),
         "compositor address/workspace patterns refuse anything that could close a quote"),
        (not env_writes, f"the environment is never modified (no os.putenv / os.environ writes) {env_writes}"),
        (writers == ["os.chmod", "os.fdopen", "os.fsync", "os.makedirs", "os.replace", "os.unlink", "tempfile.mkstemp"] and {"os.makedirs", "os.chmod"} <= calls_in("private_dir")
         and {"tempfile.mkstemp", "os.fdopen", "os.replace", "os.unlink", "os.fsync"} <= calls_in("_refresh"), f"file-writing calls exist only in private_dir and Catalog._refresh {writers}"),
        (mkstemp_in_cache, "the catalog temp file is always created inside CACHE"),
        (assigns.get("CONF") == "os.path.join(GLib.get_user_config_dir(), 'omarchy-store')" and assigns.get("CACHE") == "os.path.join(GLib.get_user_cache_dir(), 'omarchy-store')"
         and private_args == ["CACHE", "CONF"], "the only directories ever created are the XDG config/cache dirs + 'omarchy-store'"),
        (assigns.get("STORE_HOSTS") == "('omarchystore.com', 'www.omarchystore.com')"
         and assigns.get("WEBVIEW_HOSTS") == "STORE_HOSTS + ('omarchy-store-backend.omarchystore.workers.dev',)" and assigns.get("DEFAULT_HOME") == "'https://omarchystore.com/'",
         "the host allow-lists and the default home are exactly the three named hosts"),
        (all(len(v) == 1 for v in singletons.values()) and not load_html, f"one injected script, one message handler, one browser hand-off, no load_html {load_html}"),
        (sc.startswith("[ -t 0 ] ||") and "while read -r -t 0.2 _; do :; done; " in sc, "terminal script needs a terminal on stdin and drops typed-ahead input before asking"),
        (not priv, f"no sudo/pkexec/doas/polkit/systemd/setuid tokens in code strings, bytes or f-strings {priv}"),
        (not syspath, f"no fixed system paths (/bin /etc /usr /tmp /proc /home …) in code strings {syspath}"),
        (not fetchers, "no curl/wget in code except the app-update line in update_command"),
        (tar_ok, "pacman sync databases are read in memory only (gzip/io/tarfile used only inside repo_versions; no extract/extractall)"),
        (db_ok, "the one system path is /var/lib/pacman, used only as the read-only default of the three package readers"),
        (chain_ok, "Update all line: store app first (then a reopen note), other store apps (yay -S), Omarchy & system last (omarchy update, then 'Restart if it asks'), joined with &&"),
        (chain_refuse, "update line refuses bad package names, repeated or unknown steps, and empty input"),
        (vc_ok, "vercmp agrees with pacman on epochs, releases, pre-releases and separators"),
        (upd_ok, "app-update line is exactly: download from https://omarchystore.com/downloads/, sha256sum -c, tar, ./install.sh (no root, no pipe to a shell)"),
        (upd_refuse, "app-update refuses a malformed version or sha256"),
        (upd_newer, "app update offered only for a strictly newer valid version; a catalog-given URL is ignored"),
        (tag_list_refused and not ARG_RE.fullmatch(UPDATE_TAG), "the app-update tag cannot come from a catalog install command"),
        (not eval_js, f"no evaluate_javascript in the app body — only --probe below the audit line uses it {eval_js}"),
    ]
    ok = all(x for x, _ in checks)
    for x, name in checks: print(("PASS " if x else "FAIL ") + name)
    print(f"{len(checks)} checks · SELF-TEST", "OK" if ok else "FAILED"); return 0 if ok else 1


# ---------------------------------------------------------------------------------------------------------
# Everything below is QA tooling, excluded from the self-test's "app body" audit. It drives the page with
# evaluate_javascript from OUR side — the page never gains the ability to run anything in the app.
# ---------------------------------------------------------------------------------------------------------
def snapshot(path, url):
    """Render the store in a WebView and save a PNG — for release notes and QA."""
    app = App()
    def on_activate(a):
        win = Window(a, a.catalog); win.web.load_uri(url)
        def shoot():
            def cb(view, res):
                try: view.get_snapshot_finish(res).save_to_png(path); print("saved", path)
                finally: a.quit()
            win.web.get_snapshot(WebKit.SnapshotRegion.VISIBLE, WebKit.SnapshotOptions.NONE, None, cb); return False
        win.present(); GLib.timeout_add(7000, shoot)
    app.connect("activate", on_activate); return app.run([])


def probe(url):
    """End-to-end test of the bridge against the live page: GET → panel → Install → the argv that WOULD have
    gone to the terminal (open_in_terminal is stubbed; no terminal opens)."""
    if not is_store_url(url): print("probe: not a store URL"); return 2
    global open_in_terminal
    res: dict = {"terminal": False}
    class Opened:                                                        # stands in for the Popen handle the real function returns
        returncode = 0
        def poll(self): return None
    def fake(argv, title): res.update({"terminal": True, "argv": argv, "title": title, "script": terminal_script(argv, title)}); return Opened()
    open_in_terminal = fake
    app = App()
    def on_activate(a):
        win = Window(a, a.catalog); win.web.load_uri(url); win.present()
        def step1(): win.web.evaluate_javascript("document.querySelector('.actions [data-get]').click(); 'clicked'", -1, None, None, None); GLib.timeout_add(9000, step2); return False
        def step2():
            def cb(view, r):
                try: res["button"] = view.evaluate_javascript_finish(r).to_string()
                except GLib.Error as e: res["button"] = "ERR " + str(e)
                GLib.timeout_add(1500, finish)
            win.last_input = GLib.get_monotonic_time()                   # the probe's scripted click is not real input; arm the gate
            win.web.evaluate_javascript("(()=>{const b=document.querySelector('[data-desktop-install]'); if(!b) return 'NO BUTTON'; b.click(); return b.innerText})()", -1, None, None, None, cb); return False
        def finish(): print(json.dumps(res)); a.quit(); return False
        GLib.timeout_add(7000, step1)
    app.connect("activate", on_activate); app.run([]); return 0 if res["terminal"] else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--self-test"]: sys.exit(self_test())
    if args[:1] == ["--probe"] and len(args) == 2: sys.exit(probe(args[1]))
    if args[:1] == ["--snapshot"] and len(args) == 2: sys.exit(snapshot(args[1], HOME_URL))
    if len(args) == 1 and args[0][2:] in VIEWS and args[0][:2] == "--":     # dock menu: open a view in the running app, or start with it
        app = App(); app.register(None)
        if app.get_is_remote(): app.activate_action("show-view", GLib.Variant("s", args[0][2:])); sys.exit(0)
        app.start_view = args[0][2:]; sys.exit(app.run([sys.argv[0]]))
    if args: print(f"omarchy-store-desktop {VERSION}\nusage: omarchy-store-desktop [--updates | --update-all | --installed | --self-test | --probe <store app url> | --snapshot out.png]"); sys.exit(2)
    sys.exit(App().run([sys.argv[0]]))
