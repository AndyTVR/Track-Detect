"""Joined recordings, temperature conversion and settings."""
import datetime as dt
import os

import numpy as np
import pytest

from conftest import need, TESTDATA

ROI = [[100, 100], [600, 100], [600, 500], [100, 500]]


def test_join_scan_separate(td):
    a, b = td.path("rhino front 1.ats"), td.path("rhino rear 1.ats")
    td.add(a, b, target={"project": {"name": "P"}, "survey": {}, "camera": {"name": "C"}})
    td.post("/api/open", {"path": a})
    td.post("/api/roi", {"id": td.get("/api/recording")["rois"][0]["id"], "points": ROI})
    cam = td.files()["tree"][0]["surveys"][0]["cameras"][0]
    r = td.org(action="join", id=cam["id"], on=True)
    vp = r["opened"]
    files = {f["path"]: f for f in r["files"]}
    assert files[vp]["joined"] and len(files[vp]["members"]) == 2
    td.post("/api/open", {"path": vp})
    rec = td.get("/api/recording")
    assert rec["frames"] == 40 and len(rec["joined"]) == 2
    assert rec["rois"][0]["points"]   # ROI taken from a member
    jobs = td.post("/api/scan", {"node": cam["id"]})["jobs"]
    assert len(jobs) == 1 and jobs[0]["path"] == vp   # the camera scans its joined recording
    td.wait_jobs()
    assert td.get("/api/recording")["scanned"]
    td.org(action="join", id=cam["id"], on=False)
    assert not any(f.get("joined") for f in td.files()["files"])


def test_joined_gap_is_flat_zero(td, monkeypatch):
    """Two files 15 s apart: the gap keeps its length and its activity is zero."""
    from emergence import ats
    from emergence.session import Recording, JOINS
    a = td.path("synthetic.ats")
    b = os.path.join(td.rec_dir, "later.ats")
    os.symlink(os.path.realpath(a), b)
    orig = ats.ATSFile.__init__

    def later(self, path, fps=None):
        orig(self, path, fps)
        if path.endswith("later.ats") and self.start_time:
            self.start_time += dt.timedelta(seconds=15)
    monkeypatch.setattr(ats.ATSFile, "__init__", later)
    vp = os.path.join(td.rec_dir, "Joined recording t.ats")
    JOINS[vp] = [b, a]
    r = Recording(vp)
    assert [(k, n) for _, k, _, n, _ in r.src.blocks] == [("part", 160), ("gap", 290), ("part", 160)]
    assert r.src.time_label(0) < r.src.time_label(r.src.n_frames - 1)
    r.set_roi(ROI)
    assert r.run_scan()
    act, gap = r.activity, r.src.gap_mask
    assert float(act[gap].max()) == 0.0 and float(act[~gap].max()) > 0
    assert r.unscanned_ranges == []
    seam = act[450:460]
    assert float(seam.max()) < float(act[~gap].max()) / 2   # no false spike where the second file starts
    assert [e["f0"] for e in r.state["events"]] == [98, 548]
    JOINS.pop(vp, None)


@pytest.mark.parametrize("name, units, approx, lo, hi", [
    ("a700_0.01K.ats", "°C", False, None, None),
    ("a70_raw.ats", "°C", True, -28.31, 31.59),     # matches Research Studio exactly
    ("a700_raw.ats", "°C", True, 0.20, 44.69),      # SWT scale, A700 zero point
    ("rhino front 1.ats", "counts", False, None, None),
])
def test_temperature_formats(name, units, approx, lo, hi):
    need(name)
    from emergence.ats import ATSFile
    f = ATSFile(os.path.join(TESTDATA, name))
    assert f.units == units and bool(getattr(f, "temp_approx", False)) == approx
    if lo is not None:
        a = f.frame(0)
        assert round(float(a.min()), 2) == lo and round(float(a.max()), 2) == hi
    f.close()


def test_suggested_level_is_background_plus_0_2(td):
    need("a700_raw.ats")
    p = td.path("a700_raw.ats")
    td.add(p)
    td.post("/api/open", {"path": p})
    td.post("/api/roi", {"id": td.get("/api/recording")["rois"][0]["id"], "points": [[100, 60], [540, 60], [540, 200], [100, 200]]})
    td.post("/api/scan", {"node": "unassigned"})
    td.wait_jobs()
    rec = td.get("/api/recording")
    assert rec["temp_approx"] and abs(rec["suggested_level"] - 0.825) < 0.01


def test_settings_save_and_migrate(td):
    import json
    import app as td_app
    from emergence import settings as cfg
    s = td.get("/api/settings")["settings"]
    assert s["view"]["blend"] == "crossfade" and s["view"]["dde"] == 2
    s["detect"]["merge_s"] = 3.5
    td.post("/api/settings", {"settings": s})
    assert json.load(open(td_app.SETTINGS_PATH))["detect"]["merge_s"] == 3.5
    with open(td_app.SETTINGS_PATH, "w") as f:   # an old settings file
        json.dump({"version": 1, "view": {"blend": "overlay", "dde": 0}}, f)
    c = cfg.load(td_app.SETTINGS_PATH)
    assert c["view"]["blend"] == "crossfade" and c["view"]["dde"] == 2


def test_safe_replace_falls_back(tmp_path, monkeypatch):
    from emergence import fsutil
    a, b = tmp_path / "a.tmp", tmp_path / "b"
    a.write_text("new"); b.write_text("old")

    def locked(x, y):
        raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(fsutil.os, "replace", locked)
    fsutil.safe_replace(str(a), str(b), wait_s=0.1)
    assert b.read_text() == "new" and not a.exists()


def test_spike_at_each_join_is_left_out():
    """The hot frames a camera writes as it stops are left out at every join,
    not just at the very end, so they don't become events."""
    import types
    import numpy as np
    from emergence import session
    from emergence.analysis import detect_events
    fps, rng = 19.0, np.random.default_rng(1)
    x = (0.12 + 0.03 * rng.standard_normal(30000)).astype(np.float32)
    x[5000:5010] = 1.5                       # a bat
    x[9997:10000] = 370.0                    # end of file 1
    x[10000:10040] = 0.0                     # gap
    x[19996:20000] = 380.0                   # end of file 2
    x[29998:] = 375.0                        # end of file 3
    src = types.SimpleNamespace(fps=fps, units="°C", gap_mask=np.zeros(len(x), bool),
                                part_ranges=[[0, 9999], [10040, 19999], [20000, 29999]])
    src.gap_mask[10000:10040] = True
    rec = object.__new__(session.Recording)
    rec.src = src
    ign = rec._ignored(x)
    assert ign[9997:10000].all() and ign[19996:20000].all() and ign[29998:].all()
    assert not ign[5000:5010].any()
    evs = detect_events(np.where(ign, -np.inf, x).astype(np.float32), fps, level=0.4)
    assert [(e.f0, e.f1) for e in evs] == [(5000, 5009)]
