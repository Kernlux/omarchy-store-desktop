"""Security regression tests for omarchy-store-desktop.py.

Run with the system interpreter that has PyGObject (the app imports gi at module level):
    python3 -m pytest tests/
Nothing here stubs the app: the real module is imported and its real functions are exercised. The terminal
script is even executed once with bash (with a harmless command) to prove the "print, wait, run" order.
"""
import importlib.util, json, os, pathlib, re, shlex, subprocess, sys, urllib.request
import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
APP = ROOT / "omarchy-store-desktop.py"


@pytest.fixture(scope="session")
def osd():
    spec = importlib.util.spec_from_file_location("osd", APP)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ command builder ------------------------------------------------------------------
NAME_RULE = re.compile(r"^[a-z0-9@._+-]+$")   # the owner's required charset for package names


def catalog(osd, *entries):
    return osd.Catalog.from_apps([{"id": i, "name": i, "install": inst} for i, inst in entries])


@pytest.mark.parametrize("method, pk, expected", [
    ("pacman",  ["btop"],                    ["omarchy", "pkg", "add", "btop"]),
    ("omarchy", ["omarchy-thing"],           ["omarchy", "pkg", "add", "omarchy-thing"]),
    ("aur",     ["bottles"],                 ["omarchy", "pkg", "aur", "add", "bottles"]),
    ("flatpak", ["com.obsproject.Studio"],   ["flatpak", "install", "flathub", "com.obsproject.Studio"]),
    ("pacman",  ["a", "b-c", "d_e", "f.g", "h+i"], ["omarchy", "pkg", "add", "a", "b-c", "d_e", "f.g", "h+i"]),
    ("pacman",  ["foo@bar"],                 ["omarchy", "pkg", "add", "foo@bar"]),      # '@' is a legal Arch pkgname character
])
def test_command_allow_list(osd, method, pk, expected):
    assert catalog(osd, ("x", {"method": method, "packages": pk})).command("x") == expected


@pytest.mark.parametrize("method, pk", [
    ("pacman", ["btop; rm -rf ~"]), ("pacman", ["btop", "x$(id)"]), ("pacman", ["--noconfirm"]), ("pacman", ["-Syu"]),
    ("pacman", [".hidden"]), ("pacman", ["Btop"]), ("pacman", ["b top"]), ("pacman", [""]), ("pacman", ["btop\n"]),
    ("pacman", ["../x"]), ("pacman", ["a/b"]), ("pacman", ["a=b"]), ("pacman", ["btöp"]), ("pacman", ["a" * 82]),
    ("pacman", "btop"), ("pacman", []), ("pacman", None), ("pacman", [1]), ("pacman", ["p%d" % i for i in range(21)]), ("pacman", ["btop", "btop"]),
    ("flatpak", ["--user"]), ("flatpak", ["com.x.Y;id"]), ("flatpak", ["com.x.Y", "-v"]), ("flatpak", [".com.x"]),
    ("release", ["btop"]), ("store", ["btop"]), ("yay", ["btop"]), ("", ["btop"]), (None, ["btop"]), ("PACMAN", ["btop"]),
])
def test_command_refusals(osd, method, pk):
    assert catalog(osd, ("x", {"method": method, "packages": pk})).command("x") is None


def test_command_refuses_broken_listings(osd):
    c = osd.Catalog.from_apps([{"id": "a"}, {"id": "b", "install": "pacman"}, {"id": "c", "install": {"method": "pacman"}},
                               {"id": 7, "install": {"method": "pacman", "packages": ["btop"]}}, "junk", None,
                               {"id": "d", "install": {"method": "pacman", "packages": ["btop"], "url": "https://x/y.sh"}}])
    for bad in ("a", "b", "c", 7, "junk", None, "nope", "../../etc", "Btop", "btop\n", "a" * 65, ""):
        assert c.command(bad) is None
    assert c.command("d") == ["omarchy", "pkg", "add", "btop"]      # extra keys are ignored, never used


def test_every_emitted_word_is_allow_listed(osd):
    """No word that reaches the terminal may come from anywhere but the fixed prefixes or a validated name."""
    prefixes = {("omarchy", "pkg", "add"), ("omarchy", "pkg", "aur", "add"), ("flatpak", "install", "flathub")}
    for method in osd.METHODS:
        argv = catalog(osd, ("x", {"method": method, "packages": ["btop", "com.a.B" if method == "flatpak" else "b+c"]})).command("x")
        assert argv and tuple(argv[:len(argv) - 2]) in prefixes
        assert all(osd.ARG_RE.fullmatch(w) for w in argv)
        assert all(NAME_RULE.match(w) or method == "flatpak" for w in argv[-2:])
        assert all(not w.startswith(("-", ".")) for w in argv)


def test_package_name_rule_matches_owner_spec_and_forbids_flag_shapes(osd):
    for ok in ("btop", "foo@bar", "a.b", "a_b", "a+b", "a-b", "0ad"):
        assert osd.PKG_RE.fullmatch(ok) and NAME_RULE.match(ok)
    for bad in ("-x", "--x", ".x", "..", "A", "a b", "a;b", "a$b", "a@b/c", "", "a\n"):
        assert osd.PKG_RE.fullmatch(bad) is None


# ------------------------------------------------------------------ terminal script ------------------------------------------------------------------
def test_terminal_script_prints_then_waits_then_runs(osd):
    sc = osd.terminal_script(["omarchy", "pkg", "add", "btop"], "Install btop")
    assert sc.index("read -r _") < sc.index("; omarchy pkg add btop; st=$?")
    assert sc.count("omarchy pkg add btop") == 2            # shown once, run once, identical
    assert shlex.quote("Install btop") in sc


@pytest.mark.parametrize("argv", [["omarchy", "pkg", "add", "a;b"], ["-rf"], ["--"], [""], [], ["x", 1], [None], "omarchy pkg add btop",
                                  ["omarchy", "pkg", "add", "a b"], ["omarchy", "pkg", "add", "$(id)"], ["omarchy", "pkg", "add", "a\n"], ["é"]])
def test_terminal_script_refuses_unlisted_words(osd, argv):
    with pytest.raises((ValueError, TypeError)):
        osd.terminal_script(argv, "t")


@pytest.mark.parametrize("title", ["it's $(id) `uname` \x1b[2J; rm -rf ~", "%s%n", "\"; id; \"", "\\", "a" * 500, ""])
def test_terminal_script_title_cannot_escape_quoting(osd, title):
    sc = osd.terminal_script(["omarchy", "pkg", "add", "btop"], osd.safe_title(title, "Install"))
    # Everything the catalog contributed is inside single quotes; bash -n must accept the script as ONE well-formed command list.
    subprocess.run(["bash", "-n", "-c", sc], check=True)
    assert "\x1b" not in sc and "$(" not in sc.split("%")[0]


def run_in_terminal(script, keys, timeout=20):
    """Run the script in a real pseudo-terminal (as a terminal emulator would) and type `keys` at each prompt."""
    import pty, select, time
    master, slave = pty.openpty()
    p = subprocess.Popen(["bash", "-c", script], stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave); out = b""; deadline = time.time() + timeout; sent = 0; quiet_since = time.time()
    while time.time() < deadline and p.poll() is None:
        r, _, _ = select.select([master], [], [], 0.2)
        if master in r:
            try: out += os.read(master, 4096); quiet_since = time.time()
            except OSError: break
        if sent < len(keys) and out.count(b"Press Enter to") > sent:      # one key per prompt, after the prompt is shown
            time.sleep(0.2); os.write(master, keys[sent]); sent += 1; quiet_since = time.time()
        elif sent and time.time() - quiet_since > 1.5:                     # the key was swallowed by the typeahead drain: send it again
            os.write(master, keys[sent - 1]); quiet_since = time.time()
    try: p.wait(timeout=5)
    except subprocess.TimeoutExpired: p.kill()
    try:
        while True:                                                       # drain what the script printed after the last key
            r, _, _ = select.select([master], [], [], 0.2)
            if master not in r: break
            out += os.read(master, 4096)
    except OSError: pass
    os.close(master)
    return out.decode("utf-8", "replace"), p.returncode


def test_terminal_script_really_runs_in_order(osd):
    """In a real pty: the command must be shown, then Enter awaited, then run, then the exit code shown."""
    sc = osd.terminal_script(["echo", "hello-from-test"], "Install demo")
    out, rc = run_in_terminal(sc, [b"\r", b"\r"])
    assert out.index("This will run:") < out.index("echo hello-from-test") < out.index("Press Enter to continue") < out.rindex("hello-from-test") < out.index("Finished (exit 0)")
    assert rc == 0


def test_terminal_script_eof_at_the_prompt_cancels(osd):
    """Ctrl+D (EOF) at 'Press Enter' must cancel: the command is shown but never run."""
    sc = osd.terminal_script(["echo", "hello-from-test"], "Install demo")
    out, rc = run_in_terminal(sc, [b"\x04"])
    assert "Cancelled." in out and out.count("hello-from-test") == 1 and "Finished" not in out and rc == 130


def test_terminal_script_refuses_to_run_without_a_terminal(osd):
    """stdin that is not a tty (a pipe, a wrapper without a pty) means nothing runs — not even with newlines queued."""
    sc = osd.terminal_script(["echo", "hello-from-test"], "Install demo")
    r = subprocess.run(["bash", "-c", sc], input="\n\n", capture_output=True, text=True, timeout=20)
    assert r.returncode == 1 and "no terminal attached" in r.stderr and "hello-from-test" not in r.stdout


def test_inside_url_document_shapes(osd):
    for ok in ("https://omarchystore.com/x", "https://omarchy-store-backend.omarchystore.workers.dev/api", "about:blank", "about:srcdoc", "blob:https://omarchystore.com/uuid"):
        assert osd.inside_url(ok)
    for bad in ("https://evil.test/", "blob:https://evil.test/uuid", "data:text/html,x", "about:config", "javascript:alert(1)", "file:///etc/passwd", "http://omarchystore.com/"):
        assert not osd.inside_url(bad)


def test_terminal_script_reports_failure_exit_code(osd):
    sc = osd.terminal_script(["false"], "Install demo")
    out, rc = run_in_terminal(sc, [b"\r", b"\r"])
    assert "Finished (exit 1)" in out


def test_safe_title(osd):
    assert "\x1b" not in osd.safe_title("btop\x1b[2J; rm -rf ~", "x") and ";" not in osd.safe_title("a;b", "x")
    assert osd.safe_title("\x1b\x07", "btop") == "btop" and len(osd.safe_title("a" * 200, "x")) == 60
    assert osd.safe_title(None, "fb") == "None" or osd.safe_title(None, "fb") == "fb"   # never raises
    for ch in "'\"`$%\\\n\r\t<>|&;":
        assert ch not in osd.safe_title("a" + ch + "b", "x")


# ------------------------------------------------------------------ URL allow-list ------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "https://omarchystore.com/", "https://www.omarchystore.com/app/btop/",
    "https://omarchystore.com:443/x", "HTTPS://OMARCHYSTORE.COM/", "https://omarchystore.com/#frag@evil", "https://omarchystore.com/?u=https://evil.com",
])
def test_store_urls_accepted(osd, url):
    assert osd.is_store_url(url)


@pytest.mark.parametrize("url", [
    "http://omarchystore.com/", "https://evil.com/", "https://omarchystore.com.evil.com/", "https://evil.omarchystore.com/",
    "https://omarchystore.com@evil.com/", "https://omarchystore.com:8443/", "https://omarchystore.com:0/", "https://omarchystore.com./",
    "https://omarchystore.com\t/", "https://omarchystore.com\n/", "https://omarchystore.com /", "https://omarchystore%2ecom/",
    "https://xn--omarchystore-com/", "https://[::1]/", "https://127.0.0.1/", "https:///omarchystore.com/", "https:omarchystore.com/",
    "file:///etc/passwd", "javascript:alert(1)", "data:text/html,x", "about:blank", "blob:https://omarchystore.com/x",
    "https://omarchystore.com/" + "a" * 2048, "", None, b"https://omarchystore.com/", 7,
    "https://omarchy-store-backend.omarchystore.workers.dev/",      # the API worker is NOT the storefront: no bridge, no catalog
])
def test_store_urls_refused(osd, url):
    assert not osd.is_store_url(url)


def test_worker_may_load_in_webview_but_is_not_the_store(osd):
    """Rule 5: the backend worker may load in the view; it must never gain bridge or catalog trust."""
    w = "https://omarchy-store-backend.omarchystore.workers.dev/api/x"
    assert osd.is_webview_url(w) and not osd.is_store_url(w)
    assert not osd.inside_url(w, main=False) and osd.inside_url("https://omarchystore.com/x", main=False)   # never a subframe
    assert osd.is_webview_url("https://omarchystore.com/") and not osd.is_webview_url("https://evil.test/")
    assert not osd.is_webview_url("http://omarchy-store-backend.omarchystore.workers.dev/")
    assert osd.pick_home_url(w) == osd.DEFAULT_HOME                 # the catalog can never come from the worker


def test_home_url_env_validation(osd):
    for bad in ("http://evil.example/", "", "https://evil.com/", "https://omarchystore.com@evil.com/", "file:///x", None):
        assert osd.pick_home_url(bad) == osd.DEFAULT_HOME
    assert osd.pick_home_url("https://v8.omarchy-store-preview.pages.dev/app/btop/") == osd.DEFAULT_HOME
    assert osd.CATALOG_URL.endswith("/catalog.json") and osd.CATALOG_URL.count("/") == 3


def test_catalog_redirects_off_store_are_refused_before_being_followed(osd):
    h = osd.StoreRedirectHandler()
    req = urllib.request.Request(osd.CATALOG_URL)
    for off in ("https://evil.test/catalog.json", "http://omarchystore.com/catalog.json", "file:///etc/passwd", "https://omarchy-store-backend.omarchystore.workers.dev/c.json"):
        assert h.redirect_request(req, None, 302, "Found", {}, off) is None
    r = h.redirect_request(req, None, 302, "Found", {}, "https://www.omarchystore.com/catalog-moved.json")
    assert isinstance(r, urllib.request.Request) and r.full_url == "https://www.omarchystore.com/catalog-moved.json"


# ------------------------------------------------------------------ bridge message validation ------------------------------------------------------------------
@pytest.mark.parametrize("raw, expected", [
    ('{"t":"install","id":"btop"}', ("install", "btop")),
    ('{"t":"install","id":"btop","x":1}', ("install", "btop")),
    ('{"t":"open","url":"https://github.com/x"}', ("open", "https://github.com/x")),
])
def test_bridge_messages_accepted(osd, raw, expected):
    assert osd.parse_message(raw) == expected


@pytest.mark.parametrize("raw", [
    '{"t":"open","url":"http://github.com/x"}', '{"t":"open","url":"javascript:alert(1)"}', '{"t":"open","url":"file:///etc/passwd"}',
    '{"t":"open","url":"https://"}', '{"t":"open","url":"https:///x"}', '{"t":"open","url":"https://a b"}', '{"t":"open","url":"https://a\\nb"}',
    '{"t":"open","url":"https://%s"}' % ("a" * 2048), '{"t":"open","url":123}', '{"t":"open"}', '{"t":"open","url":"HTTPS://x"}',
    '{"t":"open","url":"https://omarchystore.com@evil.test/"}', '{"t":"open","url":"https://user:pw@evil.test/"}',
    '{"t":"install","id":123}', '{"t":"install","id":"btop\\n"}', '{"t":"install","id":"Btop"}', '{"t":"install","id":"../etc"}',
    '{"t":"install","id":"-x"}', '{"t":"install","id":""}', '{"t":"install"}', '{"t":"install","id":"%s"}' % ("a" * 65),
    '{"t":"exec","cmd":"ls"}', '{"t":"install","id":"btop","t2":"x"}'[:-1], '[1]', 'nope', '', '{"t":["install"],"id":"btop"}',
    '{"t":"install","id":"' + "a" * 4096 + '"}', None, 5, b'{"t":"install","id":"btop"}', ['install', 'btop'],
])
def test_bridge_messages_refused(osd, raw):
    assert osd.parse_message(raw) is None


def test_bridge_actions_need_fresh_user_input(osd):
    """A page may not open terminals or browsers on its own: each real click/key pays for at most one action."""
    assert osd.input_is_fresh(None, 0) is False
    assert osd.input_is_fresh(0, osd.INPUT_WINDOW_US) is True
    assert osd.input_is_fresh(0, osd.INPUT_WINDOW_US + 1) is False
    assert osd.input_is_fresh(100, 50) is False                     # clock went backwards → not fresh


# ------------------------------------------------------------------ the static audit must catch evasions ------------------------------------------------------------------
EVASIONS = {   # each is inserted at module level (after the imports) of a COPY of the app; --self-test must then FAIL
    "getattr-run": 'getattr(subprocess, "run")',
    "import-alias": 'import subprocess as _sp',
    "from-import-run": 'from subprocess import run as _r',
    "from-os-system": 'from os import system as _s',
    "gio-subprocess-ctor": '_g = Gio.Subprocess',
    "gio-appinfo": '_a = Gio.AppInfo',
    "glib-spawn": '_x = GLib.spawn_async',
    "second-popen-ref": '_p = subprocess.Popen',
    "duplicate-self-test": 'def self_test():\n    return 0',
    "bytes-sudo": '_b = b"sudo -n true"',
    "folded-concat-sudo": '_c = "su" + "do"',
    "fstring-system-path": '_f = f"/{\'etc\'}/passwd"',
    "bin-sh-string": '_sh = "/bin/sh"',
    "second-build-opener": '_o = urllib.request.build_opener',
    "urlretrieve": '_u = urllib.request.urlretrieve',
    "os-open": '_w = os.open',
    "shutil-copy": '_s2 = shutil.copyfile',
    "named-tempfile": '_t = tempfile.NamedTemporaryFile',
    "open-with-opener-kw": '_fh = open(__file__, "rb", opener=None)',
    "environ-write": 'os.environ["LD_PRELOAD"] = "x"',
    "putenv": '_pe = os.putenv',
    "sys-modules": '_m = sys.modules',
    "dunder-dict": '_d = os.__dict__',
    "extra-gi-namespace": 'from gi.repository import Soup',
    "eval-name": '_e = eval',
    "pathlib": 'import pathlib',
    "socket": 'import socket',
    "docstring-readback": 'def _h():\n    "sudo -n true"\n_s3 = _h.__doc__',
    "nested-self-test-method": 'class _K:\n    def self_test(self):\n        return "su" + "do"',
    "open-other-path": '_fh2 = open(__file__, "rb")',
    "second-userscript": '_us = WebKit.UserScript.new',
    "second-urilauncher": '_ul = Gtk.UriLauncher.new',
    "load-html": '_lh = WebKit.WebView.load_html',
}


def _self_test_on_copy(tmp_path, snippet):
    src = APP.read_text()
    marker = "\nAPP_ID = "
    assert marker in src
    copy = tmp_path / "omarchy-store-desktop.py"
    copy.write_text(src.replace(marker, "\n" + snippet + "\n" + marker.lstrip("\n"), 1) if snippet else src)
    r = subprocess.run([sys.executable, "-I", str(copy), "--self-test"], capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout


def test_self_test_passes_on_an_untouched_copy(tmp_path):
    rc, out = _self_test_on_copy(tmp_path, "")
    assert rc == 0 and "SELF-TEST OK" in out


@pytest.mark.parametrize("name", sorted(EVASIONS))
def test_self_test_catches_evasion(tmp_path, name):
    rc, out = _self_test_on_copy(tmp_path, EVASIONS[name])
    assert rc != 0 and ("FAIL" in out or "SELF-TEST OK" not in out), f"{name} slipped past the static audit:\n{out}"


# ------------------------------------------------------------------ release artefacts stay consistent with the tree ------------------------------------------------------------------
def test_release_tarball_matches_tree_and_pkgbuild_pin(osd):
    """If a release tarball for this VERSION exists, its sha256 must be the one pinned in pkg/PKGBUILD and its .py must be this .py."""
    import hashlib, tarfile
    tb = ROOT / "release" / f"omarchy-store-desktop-{osd.VERSION}.tar.gz"
    if not tb.exists(): pytest.skip("no release tarball built yet")
    digest = hashlib.sha256(tb.read_bytes()).hexdigest()
    assert f"sha256sums=('{digest}')" in (ROOT / "pkg" / "PKGBUILD").read_text(), "pkg/PKGBUILD pins a different tarball — run ./release.sh"
    assert (ROOT / "release" / f"omarchy-store-desktop-{osd.VERSION}.tar.gz.sha256").read_text().split()[0] == digest
    assert f"sha256sums = {digest}" in (ROOT / "pkg" / ".SRCINFO").read_text()
    with tarfile.open(tb) as t:                                         # every shipped file must be the tree's file
        for m in t.getmembers():
            if not m.isfile(): continue
            rel = m.name.split("/", 1)[1]
            if rel == "RELEASE-INFO": continue                               # generated by release.sh: version + SOURCE_DATE_EPOCH
            inner = t.extractfile(m).read(); tree = (ROOT / rel).read_bytes()
            if rel == "pkg/PKGBUILD":                                     # the only sanctioned difference: the in-archive copy says SKIP
                inner = re.sub(rb"^sha256sums=.*$", b"", inner, flags=re.M); tree = re.sub(rb"^sha256sums=.*$", b"", tree, flags=re.M)
            assert inner == tree, f"{rel} inside the tarball differs from the tree — run ./release.sh"


# ------------------------------------------------------------------ the shipped self-test and the tree ------------------------------------------------------------------
def test_self_test_passes(osd, capsys):
    assert osd.self_test() == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out and "SELF-TEST OK" in out


def test_no_hooks_or_privilege_anywhere_in_the_tree():
    pkgbuild = re.sub(r"#[^\n]*", "", (ROOT / "pkg" / "PKGBUILD").read_text())      # comments may *mention* hooks; code may not
    assert not re.search(r"^\s*install=", pkgbuild, re.M), "PKGBUILD must not ship an .install scriptlet"
    assert "systemd" not in pkgbuild and "hooks" not in pkgbuild and "sudo" not in pkgbuild
    for line in re.findall(r'install -D[^\n]*"\$pkgdir(/[^"]*)"', pkgbuild) + re.findall(r'-t "\$pkgdir(/[^"]*)"', pkgbuild):
        assert re.match(r"/usr/(bin|share|lib/omarchy-store)(/|$)", line), line
    desktop = (ROOT / "data" / "com.omarchystore.Store.desktop").read_text()
    assert "Exec=omarchy-store-desktop\n" in desktop and "%" not in desktop and "DBusActivatable" not in desktop and "autostart" not in desktop.lower()
    launcher = (ROOT / "data" / "omarchy-store-desktop").read_text()
    assert launcher.startswith("#!/usr/bin/bash\n") and 'exec /usr/bin/python3 -I /usr/share/omarchy-store-desktop/omarchy-store-desktop.py "$@"' in launcher
    # 1.1.2 NVIDIA workaround: the ONLY other code is one fixed-path test and one fixed export; nothing user-supplied is read
    code = [l for l in launcher.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    assert code == ['if [[ -e /proc/driver/nvidia/version && -z "${WEBKIT_DISABLE_DMABUF_RENDERER+x}" ]]; then',
                    '  export WEBKIT_DISABLE_DMABUF_RENDERER=1', 'fi',
                    'exec /usr/bin/python3 -I /usr/share/omarchy-store-desktop/omarchy-store-desktop.py "$@"'], code
    assert re.search(r"/usr/bin/python3 -I omarchy-store-desktop.py --self-test", (ROOT / "pkg" / "PKGBUILD").read_text())
    inst = (ROOT / "install.sh").read_text()
    assert "systemd" not in inst and "/etc/" not in inst and "autostart" not in inst and "pacman -S" not in inst.replace("sudo pacman -S ${missing[*]}\"", "")
    assert not list(ROOT.glob("**/*.hook")) and not list(ROOT.glob("**/*.service")) and not list(ROOT.glob("**/*.timer")) and not list(ROOT.glob("**/*.install"))
