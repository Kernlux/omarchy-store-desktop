"""1.1.8: the store's safety check runs before EVERY terminal, inside the app.

The page sends what /api/preflight found with each install / add-on / update. on_message refuses the action unless that
check finished, is not red, is under an hour old and uses known check names; the terminal then prints what was checked."""
import importlib.util
import json
import os

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("osd_chk", os.path.join(HERE, "omarchy-store-desktop.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
GLib = m.GLib


def iso(seconds_ago):
    return GLib.DateTime.new_now_utc().add_seconds(-seconds_ago).format_iso8601().replace("+00", "Z")[:19] + "Z"


class Val:
    def __init__(self, s): self.s = s
    def is_string(self): return True
    def to_string(self): return self.s


class FakeWin:
    """Just enough of Window for on_message: a committed store document, a real click, our catalog copy."""
    doc_uri = "https://omarchystore.com/app/btop/"
    def __init__(self):
        self.notes, self.updates = [], []
        self.catalog = m.Catalog.from_apps([{"id": "btop", "name": "btop", "install": {"method": "pacman", "packages": ["btop"]}}])
        self.catalog.themes = {"gruvbox": {"id": "gruvbox", "name": "Gruvbox", "builtin": "gruvbox"}}
        self.catalog.plugins = {}
    def take_input(self): return True
    def note(self, t): self.notes.append(t)
    def open_external(self, u): pass
    def page_update(self, what, checked): self.updates.append((what, checked))
    page_addon = m.Window.page_addon
    run_terminal = m.Window.run_terminal


@pytest.fixture
def opened(monkeypatch):
    calls = []
    class P:
        returncode = 0
        def poll(self): return 0
    monkeypatch.setattr(m, "open_in_terminal", lambda argv, title, checked="": (calls.append((argv, title, checked)), P())[1])
    monkeypatch.setattr(m.GLib, "timeout_add", lambda *a, **k: 0)
    return calls


def send(win, msg):
    m.Window.on_message(win, None, Val(json.dumps(msg)))


GOOD = lambda: {"v": "clear", "at": iso(60), "c": ["upstream:ok", "license:ok", "source:ok", "hooks:ok", "store:ok"]}


def test_install_with_a_finished_check_opens_the_terminal_and_says_what_was_checked(opened):
    w = FakeWin(); send(w, {"t": "install", "id": "btop", "chk": GOOD()})
    assert len(opened) == 1
    argv, title, checked = opened[0]
    assert argv == ["omarchy", "pkg", "add", "btop"] and checked.startswith("Safety check at ") and "all clear" in checked
    sc = m.terminal_script(argv, title, checked)
    assert sc.index("Safety check at") < sc.index("Press Enter")


@pytest.mark.parametrize("chk", [None, {}, {"v": "blocked", "at": "X", "c": ["source:fail"]}, "clear", 1,
                                 {"v": "clear", "c": ["source:ok"]}, {"v": "clear", "at": None, "c": ["source:ok"]}])
def test_no_terminal_without_a_usable_check(opened, chk):
    w = FakeWin()
    msg = {"t": "install", "id": "btop"}
    if chk is not None: msg["chk"] = chk
    send(w, msg)
    assert opened == [] and w.notes and "safety check" in w.notes[-1].lower()


def test_red_verdict_is_refused_even_if_the_page_tried(opened):
    w = FakeWin(); send(w, {"t": "install", "id": "btop", "chk": {"v": "blocked", "at": iso(10), "c": ["source:fail", "store:ok"]}})
    assert opened == []


def test_a_check_older_than_an_hour_is_refused(opened):
    w = FakeWin(); c = GOOD(); c["at"] = iso(3601)
    send(w, {"t": "install", "id": "btop", "chk": c})
    assert opened == []
    c["at"] = iso(3500); send(w, {"t": "install", "id": "btop", "chk": c})
    assert len(opened) == 1


def test_amber_needs_notes_and_says_so(opened):
    w = FakeWin(); send(w, {"t": "addon", "kind": "theme", "id": "gruvbox", "chk": {"v": "caution", "at": iso(5), "c": ["upstream:warn", "store:ok"]}})
    assert len(opened) == 1 and "notes read" in opened[0][2] and "(read the note)" in opened[0][2]


def test_addon_and_update_need_the_check_too(opened):
    w = FakeWin()
    send(w, {"t": "addon", "kind": "theme", "id": "gruvbox"})
    send(w, {"t": "update", "what": "all"})
    assert opened == [] and w.updates == []
    send(w, {"t": "update", "what": "system", "chk": {"v": "clear", "at": iso(1), "c": ["system:ok"]}})
    assert w.updates and w.updates[0][0] == "system" and "Omarchy's own updater ok" in w.updates[0][1]


def test_page_text_never_reaches_the_terminal(opened):
    w = FakeWin(); c = GOOD(); c["c"] = ["source:ok", "x$(id):ok"]
    send(w, {"t": "install", "id": "btop", "chk": c})
    c2 = GOOD(); c2["note"] = "$(rm -rf ~)"; c2["summary"] = "\x1b[2J"
    send(w, {"t": "install", "id": "btop", "chk": c2})
    assert len(opened) == 1 and "$(" not in opened[0][2] and "\x1b" not in opened[0][2]


def test_run_update_refuses_without_a_check():
    w = FakeWin(); notes = []
    w.note = notes.append
    m.Window.run_update(w, (("system",),), "Update Omarchy & system")
    assert notes and "safety check" in notes[0].lower()
