"""1.1.13: a download link clicked in the app goes to the browser; the app itself never saves a file."""
import importlib.util
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("osd_dl", os.path.join(HERE, "omarchy-store-desktop.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Dl:
    def __init__(self, uri): self.uri, self.cancelled = uri, False
    def get_request(self): u = self.uri; return type("R", (), {"get_uri": lambda s: u})()
    def cancel(self): self.cancelled = True


class W:
    def __init__(self, clicked): self.clicked, self.opened, self.notes = clicked, [], []
    def take_input(self): return self.clicked
    def open_external(self, uri): self.opened.append(uri); return True
    def note(self, t): self.notes.append(t)


def test_clicked_store_file_goes_to_the_browser_and_is_never_saved_here():
    w, d = W(True), Dl("https://omarchystore.com/downloads/omarchy-store-desktop-1.1.13.tar.gz")
    m.Window.on_download(w, None, d)
    assert d.cancelled and w.opened == [d.uri] and "browser" in w.notes[0] and "never saves" not in w.notes[0]


def test_download_without_a_click_is_only_cancelled():
    w, d = W(False), Dl("https://omarchystore.com/downloads/x.tar.gz")
    m.Window.on_download(w, None, d)
    assert d.cancelled and w.opened == []


def test_non_https_is_never_handed_on():
    for u in ("http://omarchystore.com/x.tar.gz", "file:///etc/passwd", "data:text/plain,hi", ""):
        w, d = W(True), Dl(u)
        m.Window.on_download(w, None, d)
        assert d.cancelled and w.opened == []
