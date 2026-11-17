"""1.1.12: after an update the running (old) instance notices that its own file on disk is newer and offers ONE Restart.
install.sh only looks for a running instance and prints the restart command; it never stops anything."""
import importlib.util
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("osd_restart", os.path.join(HERE, "omarchy-store-desktop.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def _file(tmp_path, body):
    p = tmp_path / "app.py"; p.write_text(body); return str(p)


def test_installed_version_reads_the_version_line(tmp_path):
    assert m.installed_version(_file(tmp_path, '#!/usr/bin/python3\nVERSION = "9.8.7"\n')) == "9.8.7"


def test_unreadable_or_odd_files_never_offer_a_restart(tmp_path):
    assert m.restart_pending(str(tmp_path / "missing.py")) == ""
    assert m.restart_pending(_file(tmp_path, 'VERSION = "1.1.x"\n')) == ""
    assert m.restart_pending(_file(tmp_path, 'VERSION = "1.1.2"; rm -rf ~\n')) == ""
    assert m.restart_pending(os.devnull) == ""


def test_newer_file_offers_restart_same_or_older_does_not(tmp_path):
    assert m.restart_pending(_file(tmp_path, 'VERSION = "99.0.0"\n')) == "99.0.0"
    assert m.restart_pending(_file(tmp_path, f'VERSION = "{m.VERSION}"\n')) == ""
    assert m.restart_pending(_file(tmp_path, 'VERSION = "1.0.0"\n')) == ""


def test_the_running_file_is_this_file_and_matches():
    assert m.SELF_FILE == os.path.abspath(os.path.join(HERE, "omarchy-store-desktop.py"))
    assert m.installed_version() == m.VERSION and m.restart_pending() == ""


def test_window_bar_text():
    class W:
        def __init__(self): self.restart_bar = type("B", (), {"set_title": lambda s, t: setattr(s, "t", t), "set_revealed": lambda s, v: setattr(s, "r", v)})()
    w = W(); m.Window.show_restart(w, "1.1.13")
    assert w.restart_bar.t == "Omarchy Store was updated to 1.1.13. Restart to use it." and w.restart_bar.r is True


def test_restart_flag_quits_only():
    class A:
        restart = False; quitted = False
        def quit(self): self.quitted = True
    a = A(); m.App.restart_now(a)
    assert a.restart and a.quitted


def test_installer_only_looks_and_prints():
    src = open(os.path.join(HERE, "install.sh")).read()
    assert "pgrep -u" in src and "--restart" in src
    assert not re.search(r"\b(pkill|killall|kill)\b", src.replace("pgrep", ""))


def test_info_carries_the_installed_file_version_without_clobbering_the_app_list():
    # 1.1.12 shipped with the key "installed", which the installed-apps list right below it overwrote in the same dict
    # literal, so the page never saw the file's version; 1.1.13 uses its own key.
    class W:
        upd = {"pending": [], "aur": [], "store": None, "have": {}, "busy": False, "when": "", "source": "checked"}
        upd_apps = lambda s: []; upd_total = lambda s: 0; store_apps = lambda s: []; repo_names = lambda s: set(); upd_coming = lambda s: []
    info = m.Window.info(W())
    assert info["installed_version"] == m.VERSION and isinstance(info["installed"], list)
