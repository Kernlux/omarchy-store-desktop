"""1.1.17 (Luca, 17 Nov): never show a version the user cannot install, never mention mirrors. A fake LAGGING mirror
(catalog/Arch has Telegram 7.4.4-1, the user's package list offers nothing) must produce NO update row, badge or count."""
import importlib.util
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "omarchy-store-desktop.py")
spec = importlib.util.spec_from_file_location("osd_nc", SRC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

TG = {"id": "telegram", "name": "Telegram", "install": {"method": "pacman", "packages": ["telegram-desktop"]},
      "package": {"name": "telegram-desktop", "repo": "extra", "version": "7.4.4-1"}}
YT = {"id": "yt-dlp", "name": "yt-dlp", "install": {"method": "pacman", "packages": ["yt-dlp"]},
      "package": {"name": "yt-dlp", "repo": "extra", "version": "2026.11.01-1"}}


class FakeWin:
    upd_total = m.Window.upd_total; upd_apps = m.Window.upd_apps
    store_apps = m.Window.store_apps; repo_names = m.Window.repo_names; info = m.Window.info

    def __init__(self, have, pending):
        self.catalog = m.Catalog.from_apps([TG, YT])
        self.upd = {"have": have, "pending": list(pending), "aur": [], "source": "checked", "store": None, "busy": False, "when": "02:30"}


HAVE = {"telegram-desktop": "7.3.2-1", "yt-dlp": "2026.10.26-1"}


def test_lagging_mirror_shows_no_row():
    w = FakeWin(HAVE, [])                      # the mirror offers nothing; the catalog/Arch is newer
    i = w.info()
    assert w.upd_total() == 0 and i["total"] == 0
    assert "coming" not in i and i["apps"] == [] and i["system"]["count"] == 0
    assert "7.4.4" not in repr(i)


def test_only_what_the_mirror_offers_is_shown():
    w = FakeWin(HAVE, [("yt-dlp", "2026.10.26-1", "2026.11.01-1")])
    i = w.info()
    assert w.upd_total() == 1 and [a["id"] for a in i["apps"]] == ["yt-dlp"] and "7.4.4" not in repr(i)


def test_no_such_wording_in_the_app():
    src = open(SRC).read()
    assert not re.search(r"not on your mirror|more out|\+ \{len\(coming\)\}|coming with a later|COMING_WHY|upd_coming|coming_updates", src)
