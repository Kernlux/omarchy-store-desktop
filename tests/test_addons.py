"""1.1.8: plugins, screensavers and themes install in one click, the same rule as apps.

The terminal line comes only from addon_line(), built from the app's own copy of the store's lists: a store package is
downloaded from the store origin with its pinned SHA-256 checked before unpacking; marketplace plugins and GitHub themes
use Omarchy's own commands. A crafted list entry must never put anything else into the terminal."""
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("osd", os.path.join(HERE, "omarchy-store-desktop.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SITE = os.path.expanduser("~/omarchy-store-relaunch/v8/dist")
SH = "0123456789abcdef" * 4
SAFE = re.compile(r'[A-Za-z0-9 ._/:~@"&|+-]+')   # every character an add-on line may contain


def site_plugin_cmd(x, host="https://omarchystore.com"):
    """The store page's plugCmd (app.js), lines joined with ' && ' — what the sheet shows inside the app."""
    if not x.get("pkg"):
        return f"omarchy plugin add {x['r']}.git --enable"
    p = x["pkg"]; f = p["url"].split("/")[-1]
    return (f"cd /tmp && curl -fLO {host}{p['url']}\necho \"{p['sha256']}  {f}\" | sha256sum -c - && mkdir -p ~/.config/omarchy/plugins && "
            f"tar -xzf {f} -C ~/.config/omarchy/plugins\nomarchy plugin enable {p['dir']}").replace("\n", " && ")


def site_theme_cmd(t, host="https://omarchystore.com"):
    if t.get("builtin"):
        return f"omarchy-theme-set {t['builtin']}"
    if t.get("download"):
        d = t["download"]; f = d["url"].split("/")[-1]
        return (f"cd /tmp && curl -fLO {host}{d['url']}\necho \"{d['sha256']}  {f}\" | sha256sum -c - && mkdir -p ~/.config/omarchy/themes && "
                f"tar -xzf {f} -C ~/.config/omarchy/themes\nomarchy-theme-set {t['install_name']}").replace("\n", " && ")
    return f"omarchy-theme-install https://github.com/{t['repo']}"


@pytest.mark.skipif(not os.path.exists(os.path.join(SITE, "plugins.json")), reason="no local site build")
def test_every_installable_plugin_matches_the_store_page():
    plugins = json.load(open(os.path.join(SITE, "plugins.json")))["plugins"]
    n = 0
    for x in plugins:
        if not (x.get("i") or x.get("pkg")):
            assert m.addon_line("plugin", x) is None
            continue
        assert m.addon_line("plugin", x) == site_plugin_cmd(x), x["id"]
        n += 1
    assert n > 1000


@pytest.mark.skipif(not os.path.exists(os.path.join(SITE, "catalog.json")), reason="no local site build")
def test_every_installable_theme_matches_the_store_page():
    themes = json.load(open(os.path.join(SITE, "catalog.json")))["themes"]
    n = 0
    for t in themes:
        if not (t.get("builtin") or t.get("download") or t.get("repo")):
            assert m.addon_line("theme", t) is None
            continue
        assert m.addon_line("theme", t) == site_theme_cmd(t), t["id"]
        n += 1
    assert n > 200


def test_store_package_line_checks_the_hash_before_unpacking():
    e = {"id": "s", "i": 1, "pkg": {"url": "/theme-packages/s-1.tar.gz", "sha256": SH, "dir": "s"}}
    line = m.addon_line("plugin", e)
    assert line.index("sha256sum -c -") < line.index("tar -xzf")
    assert line.startswith("cd /tmp && curl -fLO https://omarchystore.com/theme-packages/")
    assert "sudo" not in line and not re.search(r"\|\s*(sh|bash)\b", line)


def test_terminal_waits_for_enter_and_is_valid_bash():
    e = {"id": "gruvbox", "builtin": "gruvbox"}
    sc = m.terminal_script((m.ADDON_TAG, ("theme", e)), "Add Gruvbox")
    assert sc.index("read -r _") < sc.index("; omarchy-theme-set gruvbox; st=$?")
    assert sc.count("omarchy-theme-set gruvbox") == 2          # printed, then run: the same text
    if shutil.which("bash"):
        assert subprocess.run([shutil.which("bash"), "-n", "-c", sc]).returncode == 0


EVIL = ["; id", "$(id)", "`id`", "' ; id ; '", '" ; id ; "', "\n id", "a b", "../x", "-x", "--help", "a|b", "a&&b", "a>b", "~root", "\x1b[2J",
        "%2e%2e", "a\\b", "a\tb", "A" * 300]


@pytest.mark.parametrize("bad", EVIL)
def test_crafted_entries_cannot_inject(bad):
    entries = [
        ("plugin", {"id": "p", "i": 1, "pkg": {"url": f"/theme-packages/{bad}.tar.gz", "sha256": SH, "dir": "p"}}),
        ("plugin", {"id": "p", "i": 1, "pkg": {"url": "/theme-packages/p.tar.gz", "sha256": SH + bad, "dir": "p"}}),
        ("plugin", {"id": "p", "i": 1, "pkg": {"url": "/theme-packages/p.tar.gz", "sha256": SH, "dir": bad}}),
        ("plugin", {"id": "p", "i": 1, "r": f"https://github.com/a/{bad}"}),
        ("plugin", {"id": "p", "i": 1, "r": f"https://github.com/{bad}/b"}),
        ("theme", {"id": "t", "builtin": bad}),
        ("theme", {"id": "t", "repo": f"a/{bad}"}),
        ("theme", {"id": "t", "install_name": bad, "download": {"url": "/theme-packages/t.tar.gz", "sha256": SH}}),
    ]
    for kind, e in entries:
        line = m.addon_line(kind, e)
        assert line is None, (kind, e, line)
        with pytest.raises(ValueError):
            m.terminal_script((m.ADDON_TAG, (kind, e)), "Add x")


def test_empty_fields_refused():
    assert m.addon_line("plugin", {"i": 1, "pkg": {"url": "/theme-packages/p.tar.gz", "sha256": SH, "dir": ""}}) is None
    assert m.addon_line("plugin", {"i": 1, "pkg": {"url": "", "sha256": SH, "dir": "p"}}) is None
    assert m.addon_line("plugin", {"i": 1, "r": ""}) is None and m.addon_line("theme", {"repo": ""}) is None


def test_random_entries_never_leave_the_safe_alphabet():
    rnd = random.Random(1108)
    alphabet = "abcAZ09._-/:;$`'\"|&<> \n\t()~*?!#%=+@\\"
    for _ in range(4000):
        w = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 24)))
        for kind, e in (("plugin", {"i": 1, "r": "https://github.com/" + w}), ("theme", {"repo": w}), ("theme", {"builtin": w}),
                        ("plugin", {"pkg": {"url": "/theme-packages/" + w, "sha256": SH, "dir": "p"}})):
            line = m.addon_line(kind, e)
            assert line is None or SAFE.fullmatch(line), line


def test_only_store_origin_and_store_paths():
    for url in ("https://evil.com/theme-packages/a.tar.gz", "//evil.com/theme-packages/a.tar.gz", "/downloads/a.tar.gz",
                "/theme-packages/sub/a.tar.gz", "/theme-packages/a.zip", "/theme-packages/.a.tar.gz"):
        assert m.addon_line("plugin", {"pkg": {"url": url, "sha256": SH, "dir": "a"}}) is None, url


def test_bridge_message_shape():
    assert m.parse_message('{"t":"addon","kind":"plugin","id":"omarchy-store-screensaver"}') == ("addon", ("plugin", "omarchy-store-screensaver"))
    for raw in ('{"t":"addon","kind":"app","id":"x"}', '{"t":"addon","kind":"plugin"}', '{"t":"addon","kind":"theme","id":"X"}',
                '{"t":"addon","kind":"theme","id":"a/b"}', '{"t":"addon","kind":{"a":1},"id":"x"}', '{"t":"addon","id":"x"}'):
        assert m.parse_message(raw) is None, raw


def test_addon_tag_cannot_come_from_a_catalog_install():
    assert not m.ARG_RE.fullmatch(m.ADDON_TAG)
    c = m.Catalog.from_apps([{"id": "x", "install": {"method": "pacman", "packages": [m.ADDON_TAG]}}])
    assert c.command("x") is None


def test_catalog_keeps_themes_and_plugins_by_id():
    c = m.Catalog.from_apps([])
    assert c.plugins == {} and c.themes == {}
    assert m.Catalog.by_id([{"id": "a", "n": 1}, {"id": "a", "n": 2}, {"x": 1}, 3]) == {"a": {"id": "a", "n": 1}}
