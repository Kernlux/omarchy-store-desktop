"""1.1.11: no partial upgrades and no double listing. An app from the Arch / Omarchy repositories is never updated on its own
(yay -S / pacman -S of one repository package after newer package lists is a partial upgrade, which can break programs):
its button runs the full Omarchy & system update and the terminal says why first. AUR apps keep yay -S <pkg>. Update all:
the store app first, then AUR apps with yay -S, then Omarchy & system last. Nothing ever runs -Sy."""
import importlib.util
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("osd_partial", os.path.join(HERE, "omarchy-store-desktop.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# Luca's 15 Nov screen: six store apps with updates (yt-dlp from extra, the rest AUR) and mise-bin (AUR, not a store app)
PENDING = [("yt-dlp", "2025.10.22-1", "2025.11.12-1")]
AUR = [("cliamp", "1.0-1", "1.1-1"), ("gliff", "0.3-1", "0.4-1"), ("herdr", "2.0-1", "2.1-1"), ("owe", "0.1-1", "0.2-1"),
       ("voxtype-bin", "1.1.1-2", "1.2.1-2"), ("mise-bin", "2025.10-1", "2025.11-1")]
APPS = ["yt-dlp", "cliamp", "gliff", "herdr", "owe", "voxtype-bin"]


class Win:
    upd_apps = m.Window.upd_apps
    repo_names = m.Window.repo_names
    upd_total = m.Window.upd_total
    page_update = m.Window.page_update

    def __init__(self):
        self.upd = {"pending": PENDING, "aur": AUR, "store": None, "have": {}}
        self.runs, self.notes = [], []

    def store_apps(self):
        return [({"id": p.replace("-bin", ""), "name": p}, (p,), "aur") for p in APPS]

    def run_update(self, steps, title, checked=None): self.runs.append((steps, title, m.update_chain(steps)))
    def note(self, t): self.notes.append(t)


def test_repo_app_runs_the_full_system_update_with_the_reason_first():
    w = Win(); w.page_update("app:yt-dlp", "chk")
    steps, title, line = w.runs[0]
    assert steps == (("system", "repo"),) and "with Omarchy & system" in title
    assert line.index("partial upgrade") < line.index("omarchy update") and "yay" not in line and "pacman" not in line


def test_aur_app_keeps_its_own_yay_line():
    w = Win(); w.page_update("app:cliamp", "chk")
    assert w.runs[0][0] == (("apps", ("cliamp",)),) and w.runs[0][2] == "yay -S cliamp"


def test_update_all_never_gives_yay_a_repository_package_and_runs_the_system_last():
    w = Win(); w.page_update("all", "chk")
    steps, _, line = w.runs[0]
    assert steps[-1] == ("system",)
    yay = next(s for s in steps if s[0] == "apps")[1]
    assert "yt-dlp" not in yay and set(yay) == {"cliamp", "gliff", "herdr", "owe", "voxtype-bin"}
    assert line.index("yay -S") < line.index("omarchy update")


def test_no_command_ever_contains_a_bare_refresh():
    for what in ["all", "system"] + ["app:" + p.replace("-bin", "") for p in APPS]:
        w = Win(); w.page_update(what, "chk")
        for _, _, line in w.runs:
            assert "-Sy" not in line and "--refresh" not in line and "-Syy" not in line


def test_info_marks_repo_apps_and_lists_their_packages():
    w = Win(); w.upd.update(busy=False, when="10:02", source="checked")
    info = m.Window.info(w)
    by = {a["id"]: a for a in info["apps"]}
    assert by["yt-dlp"]["repo"] is True and by["yt-dlp"]["pkgs"] == ["yt-dlp"]
    assert by["voxtype"]["repo"] is False and by["voxtype"]["pkgs"] == ["voxtype-bin"]
    assert info["total"] == 7          # the badge: distinct packages
