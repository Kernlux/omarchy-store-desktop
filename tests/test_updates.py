"""1.1.7 update check: never a silent "up to date" when the package lists are stale.

Luca, 14 Nov: "are you sure updates works?" — 7 updates were waiting (checkupdates), the app showed none, because it compared
the installed packages with the LOCAL sync databases (as of the last pacman -Sy, days old). These tests build a fake pacman
root whose sync database is stale (it knows no newer version) and prove the app takes the fresh answer from checkupdates,
says where the answer came from, and falls back to the local lists only when checkupdates is missing — and says so.
"""
import importlib.util, pathlib
import pytest

APP = pathlib.Path(__file__).resolve().parent.parent / "omarchy-store-desktop.py"


@pytest.fixture(scope="module")
def osd():
    spec = importlib.util.spec_from_file_location("osd_upd", APP)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def fake_root(tmp_path, installed):
    """A pacman root with the given installed packages and an EMPTY sync folder (= stale lists: nothing newer known)."""
    for name, ver in installed.items():
        d = tmp_path / "local" / f"{name}-{ver}"; d.mkdir(parents=True)
        (d / "desc").write_text(f"%NAME%\n{name}\n\n%VERSION%\n{ver}\n\n")
    (tmp_path / "sync").mkdir()
    return str(tmp_path)


def answers(mapping):
    def fake(key, timeout=90):
        return mapping.get(key)
    return fake


INSTALLED = {"yt-dlp": "2026.08.19-1", "owe": "0.2.13-1", "omarchy": "4.5.0-3", "zen-browser-bin": "1.0-1", "btop": "1.3-1"}


def test_stale_lists_do_not_hide_updates(osd, tmp_path, monkeypatch):
    root = fake_root(tmp_path, INSTALLED)
    assert osd.pending_updates(root)[1] == []                       # what 1.1.6 showed: nothing
    monkeypatch.setattr(osd, "read_only", answers({"checkupdates": (0, "yt-dlp 2026.08.19-1 -> 2026.10.26-1\nowe 0.2.13-1 -> 0.2.14-1\nomarchy 4.5.0-3 -> 4.5.1-1\n")}))
    have, pend, aur, src = osd.check_pending(root)
    assert src == "checked"
    assert [p[0] for p in pend] == ["omarchy", "owe", "yt-dlp"]
    assert aur == []


def test_checkupdates_nothing_to_do_is_a_real_zero(osd, tmp_path, monkeypatch):
    root = fake_root(tmp_path, INSTALLED)
    monkeypatch.setattr(osd, "read_only", answers({"checkupdates": (2, "")}))
    _, pend, _, src = osd.check_pending(root)
    assert (pend, src) == ([], "checked")                           # exit 2 = checked and up to date


def test_without_checkupdates_the_source_says_local(osd, tmp_path, monkeypatch):
    root = fake_root(tmp_path, INSTALLED)
    monkeypatch.setattr(osd, "read_only", answers({}))               # tool not installed
    _, pend, _, src = osd.check_pending(root)
    assert src == "local" and pend == []                            # the page shows "the lists may be old", never a bare "up to date"


def test_checkupdates_error_falls_back_to_local(osd, tmp_path, monkeypatch):
    root = fake_root(tmp_path, INSTALLED)
    monkeypatch.setattr(osd, "read_only", answers({"checkupdates": (1, "==> ERROR: Cannot fetch updates")}))
    assert osd.check_pending(root)[3] == "local"


def test_aur_updates_come_from_yay_and_only_for_installed_packages(osd, tmp_path, monkeypatch):
    root = fake_root(tmp_path, INSTALLED)
    monkeypatch.setattr(osd, "read_only", answers({"checkupdates": (2, ""), "yay": (0, "zen-browser-bin 1.0-1 -> 1.1-1\nnot-installed 1 -> 2\n")}))
    _, _, aur, _ = osd.check_pending(root)
    assert aur == [("zen-browser-bin", "1.0-1", "1.1-1")]


def test_paru_used_when_yay_is_missing(osd, tmp_path, monkeypatch):
    root = fake_root(tmp_path, INSTALLED)
    monkeypatch.setattr(osd, "read_only", answers({"checkupdates": (2, ""), "paru": (0, "zen-browser-bin 1.0-1 -> 1.2-1\n")}))
    assert osd.check_pending(root)[2] == [("zen-browser-bin", "1.0-1", "1.2-1")]


@pytest.mark.parametrize("line", ["btop;id 1 -> 2", "-x 1 -> 2", "btop 1 -> 2 extra", ":: Synchronizing package databases...", "", "BTOP 1 -> 2"])
def test_parser_ignores_anything_that_is_not_an_upgrade_line(osd, line):
    assert osd.parse_upgrades(line) == []


def test_read_only_argv_is_fixed(osd):
    assert osd.READ_ONLY == {"checkupdates": ("checkupdates", "--nocolor"), "yay": ("yay", "-Qua"), "paru": ("paru", "-Qua")}
    with pytest.raises(KeyError):
        osd.read_only("pacman")


def test_real_checkupdates_on_this_machine_runs_without_root(osd):
    """When pacman-contrib is installed, the real query returns 0 (list) or 2 (none) and every line parses."""
    r = osd.read_only("checkupdates")
    if r is None:
        pytest.skip("checkupdates not installed here")
    code, text = r
    assert code in (0, 2), code
    lines = [x for x in text.splitlines() if x.strip()]
    assert len(osd.parse_upgrades(text)) == len(lines)
