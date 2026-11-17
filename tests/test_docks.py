"""1.1.14 Pin to dock: each adapter against a fake dock config in a throwaway HOME — the exact diff, the backup, unpin,
and every refusal (symlink, outside home, foreign file, dock's own lock held, file changed a moment ago / while we worked)."""
import fcntl
import importlib.util
import json
import os
import time

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("osd_docks", os.path.join(HERE, "omarchy-store-desktop.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
SNAP, OMA, NWG = m.DOCKS
OLD = time.time() - 60          # "now" far enough after the fake file's mtime


def env_for(home, **extra):
    return {"HOME": str(home), **extra}


def old(path):
    os.utime(path, (OLD - 60, OLD - 60))


SNAP_FILE = '{\n  "version": 2,\n  "pins": [\n    "org.gnome.nautilus",\n    "foot"\n  ],\n  "iconSize": 48\n}\n'


def snap_home(tmp_path):
    d = tmp_path / ".config" / "snapdock"; d.mkdir(parents=True); f = d / "settings.json"
    f.write_text(SNAP_FILE); os.chmod(f, 0o600); old(f)
    return f


def test_snapdock_pin_exact_diff_backup_and_unpin(tmp_path):
    f = snap_home(tmp_path)
    ok, msg = m.dock_change(SNAP, True, str(tmp_path), env_for(tmp_path), now=OLD)
    assert ok and msg == "Pinned to SnapDock."
    assert f.read_text() == SNAP_FILE.replace('"foot"\n', '"foot",\n    "com.omarchystore.store"\n')     # only the one entry added
    assert (tmp_path / ".config/snapdock/settings.json.omarchy-store.bak").read_text() == SNAP_FILE
    assert oct(os.stat(f).st_mode & 0o777) == "0o600"
    assert [p.name for p in f.parent.iterdir() if p.name.endswith(".tmp")] == []
    assert m.dock_state(SNAP, str(tmp_path), env_for(tmp_path))["pinned"] is True
    ok, msg = m.dock_change(SNAP, True, str(tmp_path), env_for(tmp_path), now=time.time() + 60)
    assert ok and msg == "Already pinned to SnapDock."
    old(f)
    ok, msg = m.dock_change(SNAP, False, str(tmp_path), env_for(tmp_path), now=OLD)
    assert ok and msg == "Unpinned from SnapDock." and f.read_text() == SNAP_FILE


def test_snapdock_refuses_while_its_own_lock_is_held(tmp_path):
    f = snap_home(tmp_path)
    with open(f.parent / ".lock", "ab") as lk:
        fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
        ok, msg = m.dock_change(SNAP, True, str(tmp_path), env_for(tmp_path), now=OLD)
    assert not ok and "saving its settings right now" in msg and f.read_text() == SNAP_FILE


def test_snapdock_never_creates_a_settings_file(tmp_path):
    (tmp_path / ".config" / "snapdock").mkdir(parents=True)
    ok, msg = m.dock_change(SNAP, True, str(tmp_path), env_for(tmp_path), now=OLD)
    assert not ok and "open it once" in msg and not (tmp_path / ".config/snapdock/settings.json").exists()


OMA_DEFAULTS = '{"dock": {"position": "bottom", "pinned": ["org.gnome.Nautilus", "chromium"]}, "bar": {"layout": {}}}'


def oma_root(tmp_path):
    r = tmp_path / "omarchy" / "config" / "omarchy"; r.mkdir(parents=True); (r / "shell.json").write_text(OMA_DEFAULTS)
    (tmp_path / ".config" / "omarchy").mkdir(parents=True)
    return env_for(tmp_path, OMARCHY_PATH=str(tmp_path / "omarchy"))


def test_omarchy_dock_user_file_without_pins_starts_from_the_defaults(tmp_path):
    env = oma_root(tmp_path)
    f = tmp_path / ".config/omarchy/shell.json"
    user = {"bar": {"background": "glassy", "layout": {"center": []}}, "plugins": [], "version": 1}
    f.write_text(json.dumps(user, indent=2, sort_keys=True) + "\n"); os.chmod(f, 0o600); old(f)
    before = f.read_text()
    ok, _ = m.dock_change(OMA, True, str(tmp_path), env, now=OLD)
    assert ok
    after = json.loads(f.read_text())
    assert after["dock"] == {"pinned": ["org.gnome.Nautilus", "chromium", "com.omarchystore.Store"]}
    assert {k: v for k, v in after.items() if k != "dock"} == user                                  # nothing else changed
    assert (tmp_path / ".config/omarchy/shell.json.omarchy-store.bak").read_text() == before
    old(f)
    ok, _ = m.dock_change(OMA, False, str(tmp_path), env, now=OLD)
    assert ok and json.loads(f.read_text())["dock"]["pinned"] == ["org.gnome.Nautilus", "chromium"]


def test_omarchy_dock_without_a_user_file_writes_the_defaults_plus_the_pin(tmp_path):
    env = oma_root(tmp_path)
    ok, _ = m.dock_change(OMA, True, str(tmp_path), env, now=OLD)
    f = tmp_path / ".config/omarchy/shell.json"
    assert ok and json.loads(f.read_text()) == {"bar": {"layout": {}}, "dock": {"pinned": ["org.gnome.Nautilus", "chromium", "com.omarchystore.Store"], "position": "bottom"}}
    assert oct(os.stat(f).st_mode & 0o777) == "0o600" and not (tmp_path / ".config/omarchy/shell.json.omarchy-store.bak").exists()


def test_nwg_dock_one_id_per_line(tmp_path):
    (tmp_path / ".cache").mkdir(); f = tmp_path / ".cache" / "nwg-dock-pinned"; f.write_text("firefox\nfoot\n"); old(f)
    ok, _ = m.dock_change(NWG, True, str(tmp_path), env_for(tmp_path), now=OLD)
    assert ok and f.read_text() == "firefox\nfoot\ncom.omarchystore.Store\n"
    old(f)
    assert m.dock_change(NWG, False, str(tmp_path), env_for(tmp_path), now=OLD)[0] and f.read_text() == "firefox\nfoot\n"


def test_xdg_cache_home_is_followed_only_when_absolute(tmp_path):
    c = tmp_path / "c"; c.mkdir()
    assert m.dock_path(NWG, str(tmp_path), {"XDG_CACHE_HOME": str(c)}) == str(c / "nwg-dock-pinned")
    assert m.dock_path(NWG, str(tmp_path), {"XDG_CACHE_HOME": "relative/../x"}) == str(tmp_path / ".cache" / "nwg-dock-pinned")


def test_refuses_a_symlinked_pin_list(tmp_path):
    d = tmp_path / ".config" / "snapdock"; d.mkdir(parents=True)
    real = tmp_path / "dotfiles.json"; real.write_text(SNAP_FILE); old(real)
    (d / "settings.json").symlink_to(real)
    ok, msg = m.dock_change(SNAP, True, str(tmp_path), env_for(tmp_path), now=OLD)
    assert not ok and "link" in msg and real.read_text() == SNAP_FILE


def test_refuses_a_pin_list_outside_home(tmp_path):
    home = tmp_path / "home"; home.mkdir(); out = tmp_path / "elsewhere"; out.mkdir()
    f = out / "nwg-dock-pinned"; f.write_text("foot\n"); old(f)
    ok, msg = m.dock_change(NWG, True, str(home), {"XDG_CACHE_HOME": str(out)}, now=OLD)
    assert not ok and "outside your home folder" in msg and f.read_text() == "foot\n"


def test_refuses_a_folder_that_is_a_link_out_of_home(tmp_path):
    home = tmp_path / "home"; home.mkdir(); out = tmp_path / "elsewhere"; out.mkdir()
    (home / ".cache").symlink_to(out); f = out / "nwg-dock-pinned"; f.write_text("foot\n"); old(f)
    ok, msg = m.dock_change(NWG, True, str(home), env_for(home), now=OLD)
    assert not ok and "outside your home folder" in msg and f.read_text() == "foot\n"


def test_refuses_a_file_the_dock_changed_a_moment_ago(tmp_path):
    f = snap_home(tmp_path)
    ok, msg = m.dock_change(SNAP, True, str(tmp_path), env_for(tmp_path), now=os.stat(f).st_mtime + 0.2)
    assert not ok and "a moment ago" in msg and f.read_text() == SNAP_FILE


def test_refuses_when_the_dock_writes_while_we_work(tmp_path, monkeypatch):
    f = snap_home(tmp_path)
    real_write = m.dock_write

    def racing(path, data, mode):                    # the dock rewrites its file between our read and our write
        real_write(path, data, mode)
        if path.endswith(m.DOCK_BAK): f.write_text(SNAP_FILE.replace("48", "52"))
    monkeypatch.setattr(m, "dock_write", racing)
    ok, msg = m.dock_change(SNAP, True, str(tmp_path), env_for(tmp_path), now=OLD)
    assert not ok and "while we worked" in msg and f.read_text() == SNAP_FILE.replace("48", "52")


def test_refuses_garbage_and_never_writes(tmp_path):
    d = tmp_path / ".config" / "snapdock"; d.mkdir(parents=True); f = d / "settings.json"
    f.write_text('{"pins": "not a list"}'); old(f)
    ok, msg = m.dock_change(SNAP, True, str(tmp_path), env_for(tmp_path), now=OLD)
    assert not ok and "ValueError" in msg and f.read_text() == '{"pins": "not a list"}'


def test_find_running_docks_from_fake_proc(tmp_path):
    uid = os.getuid()
    for pid, argv in ((10, ["quickshell", "-n", "-p", "/usr/share/snapdock/shell"]), (11, ["quickshell", "-n", "-p", "/usr/share/omarchy/shell"]),
                      (12, ["/usr/bin/nwg-dock-hyprland", "-d"]), (13, ["plank"]), (14, ["bash"])):
        p = tmp_path / str(pid); p.mkdir(); (p / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
    (tmp_path / "self").mkdir()
    procs = m.dock_procs(str(tmp_path))
    assert os.stat(tmp_path / "10").st_uid == uid and len(procs) == 5
    found, unsup = m.dock_find(procs)
    assert [a["key"] for a in found] == ["snapdock", "omarchy", "nwg"] and unsup == ["Plank"]


def test_legal_desk_is_named_not_supported_and_never_written():
    found, unsup = m.dock_find([["legal-desk"]])
    assert found == [] and unsup == ["Legal Desk"]


def test_no_adapter_points_at_the_compositor_config(tmp_path):
    for a in m.DOCKS:
        p = m.dock_path(a, str(tmp_path), {})
        assert "/hypr" not in p and p.startswith(str(tmp_path) + "/")
    d = tmp_path / ".config" / "hypr"; d.mkdir(parents=True)
    assert "compositor" in m.dock_check_path(str(d / "x.lua"), str(tmp_path))


def test_launcher_info_is_the_desktop_id():
    i, path = m.launcher_info()
    assert i == "com.omarchystore.Store" and path.endswith("/applications/com.omarchystore.Store.desktop")


@pytest.mark.parametrize("a", m.DOCKS, ids=lambda a: a["key"])
def test_each_adapter_round_trips(a):
    sample = {"snapdock": SNAP_FILE, "omarchy": OMA_DEFAULTS, "nwg": "foot\n"}[a["key"]]
    pins = a["get"](sample, OMA_DEFAULTS) + [a["id"]]
    assert a["get"](a["put"](sample, pins, OMA_DEFAULTS), OMA_DEFAULTS) == pins
