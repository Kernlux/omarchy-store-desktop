"""1.1.15: an update that is out upstream but not on the user's (lagging) mirror yet is shown as "coming", never twice,
never with a button. Luca's real case: Telegram 7.3.2-1 installed, Arch 7.4.4-1, Omarchy stable mirror still 7.3.2-1."""
import importlib.util
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("osd_coming", os.path.join(HERE, "omarchy-store-desktop.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

TG = {"id": "telegram", "name": "Telegram", "install": {"method": "pacman", "packages": ["telegram-desktop"]},
      "package": {"name": "telegram-desktop", "repo": "extra", "version": "7.4.4-1"}}
YT = {"id": "yt-dlp", "name": "yt-dlp", "install": {"method": "pacman", "packages": ["yt-dlp"]},
      "package": {"name": "yt-dlp", "repo": "extra", "version": "2026.11.01-1"}}
OWE = {"id": "owe", "name": "Owe", "install": {"method": "aur", "packages": ["owe"]}, "package": {"name": "owe", "repo": "aur", "version": "9.9-1"}}


class FakeWin:
    """Just enough of Window for upd_coming / info / upd_total (no display)."""
    upd_coming = m.Window.upd_coming; upd_total = m.Window.upd_total; upd_apps = m.Window.upd_apps
    store_apps = m.Window.store_apps; repo_names = m.Window.repo_names; info = m.Window.info

    def __init__(self, have, pending, aur=(), source="checked"):
        self.catalog = m.Catalog.from_apps([TG, YT, OWE])
        self.upd = {"have": have, "pending": list(pending), "aur": list(aur), "source": source, "store": None, "busy": False, "when": "02:30"}


HAVE = {"telegram-desktop": "7.3.2-1", "yt-dlp": "2026.10.26-1", "owe": "1.0-1", "omarchy": "3.2.0-1"}


def test_lagging_mirror_shows_telegram_as_coming_with_the_reason():
    w = FakeWin(HAVE, pending=[("yt-dlp", "2026.10.26-1", "2026.11.01-1")])       # checkupdates: the mirror has yt-dlp, not Telegram
    i = w.info()
    assert i["total"] == 1 and [a["id"] for a in i["apps"]] == ["yt-dlp"]
    assert i["coming"]["count"] == 1
    assert i["coming"]["list"] == [{"id": "telegram", "name": "Telegram", "pkg": "telegram-desktop", "from": "7.3.2-1", "to": "7.4.4-1"}]
    assert "stable mirror gets it later" in i["coming"]["why"] and "mirror" in i["coming"]["why"]


def test_when_the_mirror_catches_up_it_is_ready_not_coming():
    w = FakeWin(HAVE, pending=[("telegram-desktop", "7.3.2-1", "7.4.4-1"), ("yt-dlp", "2026.10.26-1", "2026.11.01-1")])
    i = w.info()
    assert i["coming"]["count"] == 0 and sorted(a["id"] for a in i["apps"]) == ["telegram", "yt-dlp"] and i["total"] == 2


def test_up_to_date_is_neither():
    w = FakeWin(dict(HAVE, **{"telegram-desktop": "7.4.4-1", "yt-dlp": "2026.11.01-1"}), pending=[])
    assert w.info()["coming"]["count"] == 0 and w.info()["total"] == 0


def test_installed_newer_than_the_catalog_is_not_coming():
    w = FakeWin(dict(HAVE, **{"telegram-desktop": "7.5.0-1"}), pending=[])
    assert all(c["id"] != "telegram" for c in w.info()["coming"]["list"])


def test_aur_apps_are_never_coming():                                                  # AUR = the helper's -Qua, as before
    w = FakeWin(HAVE, pending=[])
    assert "owe" not in [c["id"] for c in w.info()["coming"]["list"]]


def test_no_coming_while_checking_or_after_a_failed_check():
    w = FakeWin(HAVE, pending=[]); w.upd["busy"] = True
    assert w.upd_coming() == []
    w = FakeWin(HAVE, pending=[], source="failed")
    assert w.upd_coming() == []


def test_malformed_catalog_version_is_ignored():
    bad = dict(TG, package={"name": "telegram-desktop", "repo": "extra", "version": "7.9-1 && curl x"})
    assert m.coming_updates([(bad, ("telegram-desktop",), "pacman")], HAVE, []) == []
    other = dict(TG, package={"name": "something-else", "repo": "extra", "version": "9.9-1"})
    assert m.coming_updates([(other, ("telegram-desktop",), "pacman")], HAVE, []) == []


def test_epoch_versions_compare_with_pacman_rules():
    a = dict(TG, package={"name": "telegram-desktop", "repo": "extra", "version": "1:7.0-1"})
    assert len(m.coming_updates([(a, ("telegram-desktop",), "pacman")], HAVE, [])) == 1


FF = {"id": "firefox", "name": "Firefox", "install": {"method": "omarchy", "command": "omarchy install browser firefox"},
      "package": {"name": "firefox", "repo": "extra", "version": "160.0-1"}}


def test_omarchy_install_listings_without_a_package_list_are_tracked_too():
    # 1.1.16: Firefox / Brave / Chrome / 1Password are listed as `omarchy install …` (no package list) and were never in Updates
    w = FakeWin(dict(HAVE, firefox="158.0.1-1"), pending=[]); w.catalog = m.Catalog.from_apps([TG, YT, OWE, FF])
    assert "firefox" in [c["id"] for c in w.info()["coming"]["list"]]
    w = FakeWin(dict(HAVE, firefox="158.0.1-1"), pending=[("firefox", "158.0.1-1", "160.0-1")]); w.catalog = m.Catalog.from_apps([TG, YT, OWE, FF])
    i = w.info()
    assert "firefox" in [a["id"] for a in i["apps"]] and next(a for a in i["apps"] if a["id"] == "firefox")["repo"] is True
    assert "firefox" in [a["id"] for a in i["installed"]]


def test_a_bad_package_name_in_such_a_listing_is_ignored():
    bad = dict(FF, id="bad", package={"name": "-rf", "repo": "extra", "version": "9-1"})
    w = FakeWin(dict(HAVE, **{"-rf": "1-1"}), pending=[]); w.catalog = m.Catalog.from_apps([bad])
    assert w.store_apps() == []
