"""Edge cases: damaged save files, saves at the same moment, files that
disappear, joined cameras changing, and actions on things that have gone."""
import glob
import json
import os
import threading

ROI = [[100, 100], [600, 100], [600, 500], [100, 500]]


def test_damaged_analysis_file_is_kept_not_overwritten(td):
    p = td.path("rhino front 1.ats")
    side = p + ".analysis.json"
    with open(side, "w") as f:
        f.write('{"events": [{"n": 1, "status": "confir')   # cut off half-way
    td.add(p)
    td.post("/api/open", {"path": p})
    td.post("/api/roi", {"id": td.get("/api/recording")["rois"][0]["id"], "points": ROI})   # saves
    kept = glob.glob(side + ".damaged-*")
    assert len(kept) == 1 and open(kept[0]).read().startswith('{"events"')
    assert json.load(open(side))["rois"][0]["points"]   # the new save is good
    assert "rhino front 1.ats.analysis.json" in td.files()["damaged"]


def test_damaged_projects_file_is_kept(td):
    import app as td_app
    path = os.path.join(td_app.DATA, "cameras.json")
    with open(path, "w") as f:
        f.write("{not json")
    td_app._ORG.update(projects=[], of={}, n=0, loaded=False)
    td.org(action="new_project", name="P")
    assert glob.glob(path + ".damaged-*") and json.load(open(path))["projects"][0]["name"] == "P"


def test_saves_at_the_same_moment(td):
    p = td.path("rhino front 1.ats")
    td.add(p)
    import app as td_app
    r = td_app.rec(p)
    errors = []

    def hammer(k):
        try:
            for i in range(30):
                r.add_comment(f"comment {k}-{i}", i)
        except Exception as e:   # noqa: BLE001
            errors.append(e)
    ts = [threading.Thread(target=hammer, args=(k,)) for k in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    saved = json.load(open(p + ".analysis.json"))
    assert len(saved["comments"]) == 120
    assert not glob.glob(p + ".analysis.json.*tmp")


def test_recording_that_disappears(td):
    a, b = td.path("rhino front 1.ats"), td.path("rhino rear 1.ats")
    td.add(a, b)
    os.remove(b)   # moved or deleted outside the program
    f = td.files()
    assert [x["path"] for x in f["files"]] == [a]
    td.post("/api/open", {"path": b}, status=422)


def test_joined_camera_changes(td):
    a, b, c = td.path("rhino front 1.ats"), td.path("rhino front 2.ats"), td.path("rhino rear 1.ats")
    td.add(a, b, target={"project": {"name": "P"}, "survey": {}, "camera": {"name": "C"}})
    cam = td.files()["tree"][0]["surveys"][0]["cameras"][0]
    vp = td.org(action="join", id=cam["id"], on=True)["opened"]
    td.post("/api/open", {"path": vp})
    td.post("/api/roi", {"id": td.get("/api/recording")["rois"][0]["id"], "points": ROI})
    td.post("/api/scan", {"node": cam["id"]})
    td.wait_jobs()
    assert td.get("/api/recording")["scanned"]
    # a third file joins the camera: the joined recording changes and its scan starts afresh
    td.add(c, target={"camera": cam["id"]})
    rows = {f["path"]: f for f in td.files()["files"]}
    new_vp = next(p for p, f in rows.items() if f.get("joined"))
    assert len(rows[new_vp]["members"]) == 3
    td.post("/api/open", {"path": new_vp})
    assert not td.get("/api/recording")["scanned"]
    # taking a file out leaves two again; removing one from the list leaves a single file: no joined recording
    td.org(action="move", paths=[c], camera="")
    td.post("/api/remove", {"path": b})
    f = td.files()
    assert not any(x.get("joined") for x in f["files"]) and f["current"] in (None, a)


def test_acting_on_things_that_have_gone(td):
    r = td.org(action="new_project", name="P")
    pj = r["tree"][0]
    cam = pj["surveys"][0]["cameras"][0]
    td.org(action="delete", id=pj["id"])
    for body in ({"action": "rename", "id": cam["id"], "name": "x"},
                 {"action": "new_camera", "survey": pj["surveys"][0]["id"]},
                 {"action": "set_camera_map", "id": cam["id"], "map": None},
                 {"action": "join", "id": cam["id"], "on": True},
                 {"action": "set_detector", "id": "d999", "fields": {}},
                 {"action": "open_project", "id": pj["id"]}):
        td.post("/api/org", body, status=400)
    td.post("/api/add", {"paths": [td.path("rhino front 1.ats")], "target": {"camera": cam["id"]}}, status=400)
    td.post("/api/org", {"action": "set_camera_map", "id": "c1", "map": {"lat": 999, "lon": 0}}, status=400)


def test_names_and_paths_with_odd_characters(td):
    p = td.path("rhino front 1.ats", "Café – survey (1) & co")
    r = td.add(p, target={"project": {"name": "Ty’n-y-Coed «test»"}, "survey": {"date": "2026-08-10"}, "camera": {"name": "Fenêtre"}})
    assert r["tree"][0]["name"] == "Ty’n-y-Coed «test»"
    td.post("/api/open", {"path": p})
    rec = td.post("/api/comment", {"text": "Pipistrelle – 2 × passes, café wall", "frame": 3})
    assert rec["comments"][0]["text"].startswith("Pipistrelle")
    f = td.org(action="save_project", id=r["tree"][0]["id"])["file"]
    assert os.path.exists(f)
