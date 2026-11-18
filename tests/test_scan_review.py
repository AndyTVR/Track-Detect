"""Scanning, events, the detection level, decisions, comments, exports and reports."""
import os

import pytest

ROI = [[100, 100], [600, 100], [600, 500], [100, 500]]


def scanned(td, name="synthetic.ats", project=True):
    """Add a recording to a camera, draw an ROI, scan the camera; returns (path, camera id)."""
    p = td.path(name)
    td.add(p, target={"project": {"name": "P"}, "survey": {}, "camera": {"name": "C"}} if project else None)
    td.post("/api/open", {"path": p})
    rid = td.get("/api/recording")["rois"][0]["id"]
    td.post("/api/roi", {"id": rid, "points": ROI})
    cid = td.files()["tree"][0]["surveys"][0]["cameras"][0]["id"] if project else None
    r = td.post("/api/scan", {"node": cid} if cid else {"node": "unassigned"})
    assert len(r["jobs"]) == 1
    td.wait_jobs()
    return p, cid


def test_scan_finds_the_pass(td):
    scanned(td)
    rec = td.get("/api/recording")
    assert rec["scanned"] and [(e["f0"], e["f1"]) for e in rec["events"]] == [(98, 115)]
    assert rec["status"] == "In review"
    act = td.get("/api/activity?points=200")
    assert len(act["values"]) > 0 and act["suggested_level"] is not None


def test_level_decisions_comments_reset(td):
    scanned(td)
    # moving the line far up loses both events; back to suggested restores them
    assert td.post("/api/level", {"level": 1e6})["events"] == []
    rec = td.post("/api/level", {"suggested": True})
    assert len(rec["events"]) == 1
    td.post("/api/event/1/decide", {"status": "rejected", "cls": "Insect / noise"})
    td.post("/api/event/1/decide", {"status": "confirmed", "cls": "Bat"})
    rec = td.post("/api/comment", {"text": "Leaves the roost", "frame": 100})
    assert rec["comments"][0]["text"] == "Leaves the roost"
    assert td.get("/api/recording")["status"] == "Reviewed"
    # decisions survive moving the line away and back
    td.post("/api/level", {"level": 1e6})
    rec = td.post("/api/level", {"suggested": True})
    assert [(e["status"], e["cls"]) for e in rec["events"]] == [("confirmed", "Bat")]
    out = td.post("/api/start-over", {"delete_comments": True})
    assert all(e["status"] == "todo" for e in out["recording"]["events"]) and out["recording"]["comments"] == []


def test_reset_project_decisions(td):
    scanned(td)
    td.post("/api/event/1/decide", {"status": "confirmed", "cls": "Bat"})
    pid = td.files()["tree"][0]["id"]
    assert td.org(action="reset_project", id=pid)["reset"] == 1
    assert td.get("/api/recording")["events"][0]["status"] == "todo"


def test_several_rois(td):
    p = td.path("synthetic.ats")
    td.add(p)
    td.post("/api/open", {"path": p})
    r1 = td.get("/api/recording")["rois"][0]["id"]
    td.post("/api/roi", {"id": r1, "points": ROI})
    r2 = td.post("/api/rois", {"action": "add", "name": "Top"})["added"]
    td.post("/api/roi", {"id": r2, "points": [[700, 50], [1200, 50], [1200, 300], [700, 300]]})
    td.post("/api/rois", {"action": "rename", "id": r2, "name": "Roof"})
    td.post("/api/scan", {"node": "unassigned"})
    td.wait_jobs()
    rec = td.get("/api/recording")
    assert {r["name"] for r in rec["rois"]} == {"ROI 1", "Roof"} and all(r["scanned"] for r in rec["rois"])
    assert {e["roi"] for e in rec["events"]} <= {r1, r2}


def test_noise_rating_and_test_scan(td):
    _, cid = scanned(td)
    rec = td.get("/api/recording")
    assert isinstance(rec["noise"], list)
    j = td.post("/api/test-scan", {"node": cid})["job"]
    jobs = td.wait_jobs()
    t = next(x for x in jobs if x["id"] == j["id"])["result"]["test"]
    assert t["name"] == "synthetic.ats" and t["rois"][0]["spikes"] >= 1
    assert t["seconds"] > 0 and t["whole"]


def test_events_csv_and_reports(td):
    p, _ = scanned(td)
    td.post("/api/event/1/decide", {"status": "confirmed", "cls": "Bat"})
    td.post("/api/comment", {"text": "One bat", "frame": 100})
    r = td.post("/api/events-csv")
    assert os.path.exists(r["path"]) and "One bat" in open(r["path"], encoding="utf-8-sig").read()
    for fmt in ("pdf", "docx"):
        td.post("/api/report", {"format": fmt, "location": "Test site", "rejected_images": False})
        job = td.wait_jobs()[-1]
        assert job["state"] == "done", job
        assert os.path.getsize(job["result"]["report"]) > 10000


def test_event_pack_and_camera_video(td):
    scanned(td)
    td.post("/api/event/1/export", {"items": ["path_still", "blend_still"], "overlays": "roi+time"})
    job = td.wait_jobs()[-1]
    assert job["state"] == "done" and len(job["result"]["files"]) == 2
    assert all(os.path.exists(f) for f in job["result"]["files"])
    r = td.post("/api/export-camera", {"mode": "raw", "overlays": "time"})
    job = td.wait_jobs()[-1]
    assert job["state"] == "done" and os.path.getsize(r["path"]) > 100000


def test_frames_and_times(td):
    p, _ = scanned(td)
    r = td.client.get("/api/frame?i=10&mode=raw&ws=0&roi=1&pal=white")
    assert r.status_code == 200 and r.data[:2] == b"\xff\xd8"   # a JPEG
    r = td.client.get("/api/frame?i=10&mode=blend&ws=0&roi=1&pal=white&op=0.8&bm=crossfade")
    assert r.status_code == 200
    r = td.client.get("/api/times?path=" + p)
    assert r.status_code in (200, 204)


def test_camera_video_of_a_joined_camera_is_named_after_the_camera(td):
    """Exporting the camera video from a joined recording names the file after
    the project, survey and camera, and the job reports time left."""
    a, b = td.path("rhino front 1.ats"), td.path("rhino front 2.ats")
    cid = td.org(action="new_project", name="Vid")["created"]
    r = td.add(a, b, target={"camera": cid})
    td.post("/api/open", {"path": r["first"]})
    out = td.post("/api/export-camera", {"mode": "raw"})
    assert out["path"].endswith("Vid_Survey1_Camera_1.mp4") and out["recordings"] == 1
    jobs = td.wait_jobs()
    assert jobs[-1]["state"] == "done" and "started" in jobs[-1]
