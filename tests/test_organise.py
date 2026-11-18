"""Projects, surveys, cameras, unassigned recordings, project files, site plans."""
import json
import os

from conftest import need


def tree(td):
    return td.files()["tree"]


def labels(td):
    """{project: {survey label: {camera label: [file names]}}} for easy checks."""
    out = {}
    for pj in tree(td):
        out[pj["name"]] = {sv["label"]: {c["label"]: [os.path.basename(p) for p in c["paths"]] for c in sv["cameras"]}
                           for sv in pj["surveys"]}
    return out


def test_add_unassigned_opens_first(td):
    a, b = td.path("rhino front 1.ats"), td.path("rhino rear 1.ats")
    r = td.add(a, b)
    assert set(r["unassigned"]) == {a, b}
    assert r["first"] == a
    assert r["tree"] == []


def test_new_project_survey_camera_and_existing(td):
    a = td.path("rhino front 1.ats")
    td.add(a, target={"project": {"name": "St Fagans"}, "survey": {"date": "2026-08-10"}, "camera": {"name": "Front"}})
    assert labels(td) == {"St Fagans": {"Survey 1 · 10 Aug 2026": {"Camera 1: Front": ["rhino front 1.ats"]}}}
    pj = tree(td)[0]
    sv, cam = pj["surveys"][0], pj["surveys"][0]["cameras"][0]
    b = td.path("rhino front 2.ats")
    td.add(b, target={"camera": cam["id"]})
    assert labels(td)["St Fagans"]["Survey 1 · 10 Aug 2026"]["Camera 1: Front"] == ["rhino front 1.ats", "rhino front 2.ats"]
    c = td.path("rhino rear 1.ats")
    td.add(c, target={"project": {"id": pj["id"]}, "survey": {"id": sv["id"]}, "camera": {"name": "Rear"}})
    assert "Camera 2: Rear" in labels(td)["St Fagans"]["Survey 1 · 10 Aug 2026"]


def test_duplicate_project_names_refused(td):
    td.org(action="new_project", name="Site A")
    td.post("/api/org", {"action": "new_project", "name": "site a"}, status=400)
    a = td.path("rhino front 1.ats")
    td.post("/api/add", {"paths": [a], "target": {"project": {"name": "SITE A"}, "survey": {}, "camera": {}}}, status=400)


def test_sort_by_file_name(td):
    paths = [td.path(n) for n in ("rhino front 1.ats", "rhino front 2.ats", "rhino rear 1.ats")]
    td.add(*paths, target={"project": {"name": "P"}, "survey": {}, "camera": {"auto": True}})
    cams = labels(td)["P"]["Survey 1"]
    assert cams == {"Camera 1: Rhino front": ["rhino front 1.ats", "rhino front 2.ats"], "Camera 2: Rhino rear": ["rhino rear 1.ats"]}


def test_auto_assign_from_folders(td):
    a = td.path("rhino front 1.ats", "St Fagans 10.8.26")
    b = td.path("rhino rear 1.ats", "St Fagans 10.8.26")
    c = td.path("rhino front 2.ats", os.path.join("Barn", "24.8.26", "Roof"))
    root = td.rec_dir
    td.post("/api/add", {"paths": [os.path.join(root, "St Fagans 10.8.26"), os.path.join(root, "Barn")], "target": {"folders": True}})
    got = labels(td)
    assert got["St Fagans"] == {"Survey 1 · 10 Aug 2026": {"Camera 1: Rhino front": ["rhino front 1.ats"], "Camera 2: Rhino rear": ["rhino rear 1.ats"]}}
    assert got["Barn"] == {"Survey 1 · 24 Aug 2026": {"Camera 1: Roof": ["rhino front 2.ats"]}}
    # adding again reuses everything
    td.post("/api/add", {"paths": [os.path.join(root, "Barn")], "target": {"folders": True}})
    assert labels(td)["Barn"] == got["Barn"]


def test_rename_move_delete(td):
    a, b = td.path("rhino front 1.ats"), td.path("rhino rear 1.ats")
    r = td.add(a, b)
    r = td.org(action="new_project", name="P")
    pj = r["tree"][0]
    cam1 = pj["surveys"][0]["cameras"][0]
    td.org(action="rename", id=pj["id"], name="Q")
    td.org(action="rename", id=cam1["id"], name="Front")
    td.org(action="move", paths=[a], camera=cam1["id"])
    r = td.org(action="new_camera", survey=pj["surveys"][0]["id"])
    cam2 = r["tree"][0]["surveys"][0]["cameras"][1]
    td.org(action="move", paths=[b], camera=cam2["id"])
    assert labels(td) == {"Q": {"Survey 1": {"Camera 1: Front": ["rhino front 1.ats"], "Camera 2": ["rhino rear 1.ats"]}}}
    r = td.org(action="new_survey", project=pj["id"])
    sv2 = r["tree"][0]["surveys"][1]
    td.org(action="move_camera", id=cam2["id"], survey=sv2["id"])
    assert labels(td)["Q"]["Survey 2"] == {"Camera 1": [], "Camera 2": ["rhino rear 1.ats"]}
    td.org(action="delete", id=cam1["id"])
    assert td.files()["unassigned"] == [a]
    td.org(action="move", paths=[b], camera="")
    assert set(td.files()["unassigned"]) == {a, b}


def test_overlap_warning(td):
    a, b = td.path("rhino front 1.ats"), td.path("rhino front 2.ats")   # overlap 0.6 s: allowed (2 s)
    td.add(a, b, target={"project": {"name": "P"}, "survey": {}, "camera": {"name": "C"}})
    assert tree(td)[0]["surveys"][0]["cameras"][0]["overlaps"] == []
    s1 = td.path("a700_raw.ats")
    s2 = os.path.join(td.rec_dir, "a700_raw copy.ats")   # the same 11 s again (frame clock): overlaps
    os.symlink(os.path.realpath(s1), s2)
    cam = tree(td)[0]["surveys"][0]["cameras"][0]
    td.add(s1, s2, target={"camera": cam["id"]})
    cam = tree(td)[0]["surveys"][0]["cameras"][0]
    assert {cam["overlaps"][0]["a"], cam["overlaps"][0]["b"]} == {"a700_raw.ats", "a700_raw copy.ats"}


def test_site_plan_template_detectors_and_project_file(td):
    a = td.path("rhino front 1.ats")
    td.add(a, target={"project": {"name": "Longfield"}, "survey": {}, "camera": {"name": "Front"}})
    pj = tree(td)[0]
    sv, cam = pj["surveys"][0], pj["surveys"][0]["cameras"][0]
    td.org(action="set_site", id=pj["id"], site={"lat": 51.7248, "lon": 0.678, "zoom": 18})
    td.org(action="set_camera_map", id=cam["id"], map={"lat": 51.72477, "lon": 0.67798, "bearing": 111, "range": 16,
                                                         "fov": 95, "model": "FLIR A70", "lens": "95"})
    td.org(action="set_info", id=sv["id"], surveyor="A. Milner")
    td.org(action="set_info", id=cam["id"], surveyor="J. Smith")
    r = td.org(action="add_detector", survey=sv["id"])
    td.org(action="set_detector", id=r["created"], fields={"name": "Front SM4", "model": "SM4BAT FS", "map": {"lat": 51.7247, "lon": 0.6781}, "range": 25})
    t = td.org(action="save_template", survey=sv["id"])
    assert t["template"] == 1
    r = td.org(action="new_survey", project=pj["id"])
    assert r["from_template"]
    sv2 = r["tree"][0]["surveys"][1]
    assert sv2["cameras"][0]["name"] == "Front" and sv2["cameras"][0]["map"]["bearing"] == 111
    assert sv2["cameras"][0]["surveyor"] == "J. Smith"
    assert sv2["detectors"][0]["name"] == "Front SM4" and sv2["detectors"][0]["map"]
    f = td.org(action="save_project", id=pj["id"])["file"]
    assert os.path.exists(f) and json.load(open(f))["project"]["name"] == "Longfield"
    # open it on a "fresh computer"
    td.post("/api/org", {"action": "open_project_file", "path": f}, status=400)   # same name exists here
    import app as td_app
    td_app._ORG.update(projects=[], of={}, n=0, loaded=True)
    td_app.state.update(files=[], current=None)
    r = td.org(action="open_project_file", path=f)
    assert r["opened"] == 1 and r["missing"] == 0
    got = r["tree"][0]
    assert got["name"] == "Longfield" and got["site"]["lat"] == 51.7248 and got["template"] == 1
    assert got["surveys"][0]["surveyor"] == "A. Milner"


def test_close_and_reopen_project(td):
    a = td.path("rhino front 1.ats")
    td.add(a, target={"project": {"name": "P"}, "survey": {}, "camera": {}})
    pid = tree(td)[0]["id"]
    assert td.org(action="close_project", id=pid)["closed"] == 1
    assert td.files()["files"] == [] and tree(td) == []
    lst = td.org(action="list_projects")["projects"]
    assert lst[0]["name"] == "P" and lst[0]["recordings"] == 1 and lst[0]["listed"] == 0
    r = td.org(action="open_project", id=pid)
    assert r["opened"] == 1 and r["first"] == a


def test_old_cameras_file_migrates(td):
    import app as td_app
    a, b = td.path("rhino front 1.ats"), td.path("rhino rear 1.ats")
    with open(os.path.join(td_app.DATA, "cameras.json"), "w") as f:
        json.dump({"v": 3, "of": {a: "Front", b: "Camera 2"}, "proj": {a: "stf", b: "stf"}, "manual": []}, f)
    td_app._ORG.update(projects=[], of={}, n=0, loaded=False)
    td.add(a, b)
    assert labels(td) == {"stf": {"Survey 1": {"Camera 1: Front": ["rhino front 1.ats"], "Camera 2": ["rhino rear 1.ats"]}}}


def test_remaining_actions(td):
    r = td.org(action="new_project", name="P")
    pj = r["tree"][0]
    sv = pj["surveys"][0]
    td.org(action="set_date", id=sv["id"], date="2026-08-24")
    assert tree(td)[0]["surveys"][0]["label"] == "Survey 1 · 24 Aug 2026"
    td.post("/api/org", {"action": "set_date", "id": sv["id"], "date": "24th August"}, status=400)
    td.post("/api/org", {"action": "rename", "id": sv["id"], "name": "x"}, status=400)   # surveys are numbered
    td.post("/api/org", {"action": "nonsense"}, status=400)
    td.org(action="rename", id=sv["cameras"][0]["id"], name="Front")
    r = td.org(action="new_survey", project=pj["id"])
    sv2 = r["tree"][0]["surveys"][1]
    td.org(action="rename", id=sv2["cameras"][0]["id"], name="Front")
    td.post("/api/org", {"action": "move_camera", "id": sv2["cameras"][0]["id"], "survey": sv["id"]}, status=400)   # name clash
    td.org(action="save_template", survey=sv["id"])
    td.org(action="clear_template", project=pj["id"])
    assert tree(td)[0]["template"] == 0
    td.org(action="delete", id=sv2["id"])
    assert len(tree(td)[0]["surveys"]) == 1
    td.org(action="delete", id=pj["id"])
    assert tree(td) == []


def test_adding_several_files_to_one_camera_joins_them(td):
    """Recordings added to one camera are joined automatically, unless the
    camera's files were separated by hand."""
    a, b = td.path("rhino front 1.ats"), td.path("rhino front 2.ats")
    cid = td.org(action="new_project", name="AutoJoin")["created"]
    cam = lambda r: [c for pj in r["tree"] for sv in pj["surveys"] for c in sv["cameras"] if c["id"] == cid][0]
    r = td.add(a, b, target={"camera": cid})
    assert cam(r)["join"] and cam(r)["joined"] and r["joined"] == 1
    assert r["first"] == cam(r)["joined"]
    td.org(action="join", id=cid, on=False)          # separated by hand
    r = td.add(a, target={"camera": cid})
    assert not cam(r)["join"]


def test_dragging_a_second_file_onto_a_camera_joins_them(td):
    a, b = td.path("rhino front 1.ats"), td.path("rhino front 2.ats")
    cid = td.org(action="new_project", name="DragJoin")["created"]
    td.add(a, target={"camera": cid})
    td.add(b)                                           # unassigned
    r = td.org(action="move", paths=[b], camera=cid)
    c = [c for pj in r["tree"] for sv in pj["surveys"] for c in sv["cameras"] if c["id"] == cid][0]
    assert r.get("joined") == 1 and c["join"] and c["joined"]
