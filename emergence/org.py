"""Projects, surveys and cameras: how recordings are organised.

Recordings are organised Project > Survey > Camera. A project is a site, a
survey one visit or night there (numbered, with an optional date), and each
survey has numbered cameras with optional names. Recordings not put in a
camera are "unassigned". All of it is remembered in cameras.json in the
settings folder; each recording is filed by its camera's id.

The program tells this module where the settings folder is and which
recordings are listed (configure), so it has no web code of its own.
"""
from __future__ import annotations

import os

from .errors import UserError
from .fsutil import safe_replace

_CTX = {"data": lambda: ".", "listed": lambda: []}
JOIN_CAM = {}   # joined recording's path -> camera id
CAM_JOIN = {}   # camera id -> joined recording's path


def configure(data, listed):
    """data(): the settings folder; listed(): the recordings in the list."""
    _CTX["data"], _CTX["listed"] = data, listed


# Recordings are organised Project > Survey > Camera. A project is a site, a
# survey one visit or night there (numbered, with an optional date), and each
# survey has numbered cameras with optional names. Recordings not put in a
# camera are "unassigned". All of it is remembered in cameras.json in the
# settings folder; each recording is filed by its camera's id.
_ORG = {"projects": [], "of": {}, "n": 0, "loaded": False}
_GENERIC_STEMS = {"rec", "record", "recording", "video", "file", "ats", "seq", "sequence", "clip", "capture"}


def _name_stem(p):
    """'front 2.ats' -> 'front'; '' when the name has no word stem worth using."""
    import re
    st = os.path.splitext(os.path.basename(p))[0].strip()
    st = re.sub(r"[\s_\-]*\(?\d+\)?$", "", st).strip(" _-").lower()
    if not st or len(st) > 24 or re.search(r"\d", st) or st in _GENERIC_STEMS or not re.search(r"[a-z]", st):
        return ""
    return st


def _cams_path():
    return os.path.join(_CTX["data"](), "cameras.json")


def _nid(prefix):
    _ORG["n"] += 1
    return f"{prefix}{_ORG['n']}"


def _org():
    if not _ORG["loaded"]:
        import json, re
        _ORG["loaded"] = True
        try:
            with open(_cams_path(), encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            d = {}
        if d.get("v") == 4:
            _ORG["projects"] = d.get("projects") or []
            _ORG["of"] = d.get("of") or {}
            _ORG["n"] = int(d.get("n") or 0)
        elif d.get("v") in (2, 3):   # projects and cameras of earlier versions: each project gets a Survey 1
            of, proj = d.get("of") or {}, d.get("proj") or {}
            byp = {}
            for path, cam in of.items():
                byp.setdefault(proj.get(path) or os.path.basename(os.path.dirname(path)) or "Project 1", {}).setdefault(cam, []).append(path)
            for pname, cams in byp.items():
                sv = {"id": _nid("s"), "no": 1, "date": "", "cameras": []}
                for cname in cams:
                    m = re.fullmatch(r"camera\s*(\d+)", cname.strip(), re.I)
                    used = {c["no"] for c in sv["cameras"]}
                    no = int(m.group(1)) if m and int(m.group(1)) not in used else max(used | {0}) + 1
                    c = {"id": _nid("c"), "no": no, "name": "" if m else cname}
                    sv["cameras"].append(c)
                    for path in cams[cname]:
                        _ORG["of"][path] = c["id"]
                sv["cameras"].sort(key=lambda c: c["no"])
                _ORG["projects"].append({"id": _nid("p"), "name": pname, "surveys": [sv]})
            _save_org()
    return _ORG


def _save_org():
    import json
    _org()   # never write before the saved file has been read
    try:
        os.makedirs(_CTX["data"](), exist_ok=True)
        tmp = _cams_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"v": 4, "projects": _ORG["projects"], "of": _ORG["of"], "n": _ORG["n"]}, fh, indent=1)
        safe_replace(tmp, _cams_path())
    except OSError:
        pass


def _walk():
    """(project, survey, camera) for every camera."""
    for pj in _org()["projects"]:
        for sv in pj["surveys"]:
            for c in sv["cameras"]:
                yield pj, sv, c


def _node(nid):
    """('project'|'survey'|'camera', node, project, survey) for an id, or None."""
    for pj in _org()["projects"]:
        if pj["id"] == nid:
            return "project", pj, pj, None
        for sv in pj["surveys"]:
            if sv["id"] == nid:
                return "survey", sv, pj, sv
            for c in sv["cameras"]:
                if c["id"] == nid:
                    return "camera", c, pj, sv
    return None


def camera_label(c):
    """'Camera 2' or 'Camera 2: Front elevation'."""
    base = f"Camera {c['no']}"
    nm = (c.get("name") or "").strip()
    return f"{base}: {nm}" if nm and nm.lower() != base.lower() else base


def survey_label(sv):
    lab = f"Survey {sv['no']}"
    if sv.get("date"):
        try:
            import datetime as _d
            lab += " · " + _d.date.fromisoformat(sv["date"]).strftime("%-d %b %Y" if os.name != "nt" else "%#d %b %Y")
        except ValueError:
            lab += " · " + sv["date"]
    return lab


def _place(p):
    """Where a recording is filed: (project, survey, camera), or None if unassigned."""
    cid = _org()["of"].get(p) or JOIN_CAM.get(p)
    n = _node(cid) if cid else None
    if not n or n[0] != "camera":
        return None
    return n[2], n[3], n[1]


def _paths_under(nid):
    """Listed recordings under a project, survey or camera ("unassigned" for those in none)."""
    if nid == "unassigned":
        return [p for p in _CTX["listed"]() if _place(p) is None]
    n = _node(nid)
    if not n:
        return []
    kind, node = n[0], n[1]
    cams = ({node["id"]} if kind == "camera" else
            {c["id"] for c in node["cameras"]} if kind == "survey" else
            {c["id"] for sv in node["surveys"] for c in sv["cameras"]})
    return [p for p in _CTX["listed"]() if _org()["of"].get(p) in cams]


def _new_project(name=""):
    used = {pj["name"].lower() for pj in _org()["projects"]}
    name = (name or "").strip()[:40]
    if name and name.lower() in used:
        raise UserError(f"There's already a project called {name}")
    if not name:
        k = 1
        while f"project {k}" in used:
            k += 1
        name = f"Project {k}"
    pj = {"id": _nid("p"), "name": name, "surveys": []}
    _org()["projects"].append(pj)
    return pj


def _new_survey(pj, date=""):
    sv = {"id": _nid("s"), "no": max([s["no"] for s in pj["surveys"]] or [0]) + 1, "date": _clean_date(date), "cameras": []}
    pj["surveys"].append(sv)
    return sv


def _new_camera(sv, name=""):
    name = (name or "").strip()[:40]
    if name and name.lower() in {(c.get("name") or "").lower() for c in sv["cameras"]}:
        raise UserError(f"Survey {sv['no']} already has a camera called {name}")
    c = {"id": _nid("c"), "no": max([c["no"] for c in sv["cameras"]] or [0]) + 1, "name": name}
    sv["cameras"].append(c)
    return c


def _clean_date(d):
    import datetime as _d
    d = (d or "").strip()[:10]
    if not d:
        return ""
    try:
        return _d.date.fromisoformat(d).isoformat()
    except ValueError:
        raise UserError("Give the survey date as a date, for example 2026-08-10")




def _folder_date(name):
    """A survey date in a folder name ('10.8.26', '19-10-2026', '2026-08-10'),
    as (ISO date, the name with the date taken out); ("", name) if none."""
    import re, datetime as _d
    for pat, order in ((r"(?<!\d)(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})(?!\d)", "ymd"),
                       (r"(?<!\d)(\d{1,2})[-_.](\d{1,2})[-_.](\d{2}|\d{4})(?!\d)", "dmy")):
        m = re.search(pat, name)
        if not m:
            continue
        a, b, c = (int(x) for x in m.groups())
        y, mo, d = (a, b, c) if order == "ymd" else (c + 2000 if c < 100 else c, b, a)
        try:
            iso = _d.date(y, mo, d).isoformat()
        except ValueError:
            continue
        rest = (name[:m.start()] + " " + name[m.end():]).strip(" _-.,")
        return iso, " ".join(rest.split())
    return "", name


def _file_by_folders(paths, roots):
    """Sort recordings into projects, surveys and cameras from their folders.
    Below the folder they were added from (root):
      root/file          project = root's name, cameras by file name (front 1 -> Front)
      root/A/file        A is a date: survey A, cameras by file name; otherwise camera A
      root/A/B/file      survey A, camera B
    A date in a folder name becomes the survey's date ("St Fagans 10.8.26" ->
    project St Fagans, survey dated 10/08/2026). A root named only by a date
    takes its project name from the folder above. Existing projects, surveys
    (same date) and cameras (same name) with matching names are reused."""
    of = _org()["of"]
    made = {}   # (project id, survey key) -> survey made in this add
    for p in paths:
        root = roots.get(p) or os.path.dirname(p)
        rel = os.path.relpath(os.path.dirname(p), root)
        parts = [] if rel in (".", "") else rel.split(os.sep)
        rdate, rname = _folder_date(os.path.basename(root))
        if not rname:   # the root is just a date: the project is the folder above
            rname = _folder_date(os.path.basename(os.path.dirname(root)))[1] or "Project"
        sv_name, cam_name = "", None
        if len(parts) == 1:
            d1, n1 = _folder_date(parts[0])
            if d1:
                sv_name = parts[0]
            else:
                cam_name = parts[0]
        elif len(parts) >= 2:
            sv_name, cam_name = parts[-2], parts[-1]
        sdate = _folder_date(sv_name)[0] if sv_name else rdate
        pj = next((x for x in _org()["projects"] if x["name"].lower() == rname[:40].lower()), None) or _new_project(rname)
        key = (pj["id"], sdate or sv_name or "")
        sv = made.get(key) or next((x for x in pj["surveys"] if sdate and x.get("date") == sdate), None)
        if sv is None:
            sv = _new_survey(pj, sdate)
        made[key] = sv
        if cam_name is None:   # cameras by file name
            stem = _name_stem(p)
            cam_name = stem[:1].upper() + stem[1:] if stem else ""
        c = next((x for x in sv["cameras"] if (x.get("name") or "").lower() == cam_name[:40].lower()), None) or _new_camera(sv, cam_name)
        of[p] = c["id"]


def _file_into(paths, target):
    """File recordings as the Add dialog asked. target: None/"" = leave as they are
    (new ones stay unassigned); {"camera": id}; or {"project": {id|new}, "survey":
    {id|new, date}, "camera": {id|new|auto}}."""
    if not target or not paths:
        return
    of = _org()["of"]
    if isinstance(target, dict) and target.get("camera") and isinstance(target["camera"], str):
        n = _node(target["camera"])
        if not n or n[0] != "camera":
            raise UserError("That camera no longer exists")
        for p in paths:
            of[p] = n[1]["id"]
        return
    pj_t, sv_t, cam_t = target.get("project") or {}, target.get("survey") or {}, target.get("camera") or {}
    if pj_t.get("id"):
        n = _node(pj_t["id"])
        if not n or n[0] != "project":
            raise UserError("That project no longer exists")
        pj = n[1]
    else:
        pj = _new_project(pj_t.get("name", ""))
    if sv_t.get("id"):
        sv = next((s for s in pj["surveys"] if s["id"] == sv_t["id"]), None)
        if sv is None:
            raise UserError("That survey isn't in the chosen project")
    else:
        sv = _new_survey(pj, sv_t.get("date", ""))
    if cam_t.get("id"):
        c = next((c for c in sv["cameras"] if c["id"] == cam_t["id"]), None)
        if c is None:
            raise UserError("That camera isn't in the chosen survey")
        for p in paths:
            of[p] = c["id"]
    elif cam_t.get("auto"):
        # files from one folder with the same name stem share a camera ("front 1",
        # "front 2" -> Front); files with numbered names group by folder
        groups = {}
        for p in paths:
            groups.setdefault((os.path.dirname(p), _name_stem(p)), []).append(p)
        for (_, stem), ps in groups.items():
            nm = stem[:1].upper() + stem[1:] if stem else ""
            c = next((c for c in sv["cameras"] if nm and (c.get("name") or "").lower() == nm.lower()), None) or _new_camera(sv, nm)
            for p in ps:
                of[p] = c["id"]
    else:
        c = _new_camera(sv, cam_t.get("name", ""))
        for p in paths:
            of[p] = c["id"]



def _place_row(p):
    pl = _place(p)
    if pl is None:
        return {"camera_id": "", "survey_id": "", "project_id": "", "place": "Unassigned"}
    pj, sv, c = pl
    return {"camera_id": c["id"], "survey_id": sv["id"], "project_id": pj["id"],
            "place": f"{pj['name']} › {survey_label(sv)} › {camera_label(c)}"}


def _overlaps(files):
    import datetime as _d
    out = []
    for i, a in enumerate(files):
        for b in files[i + 1:]:
            if not (a["start"] and a["end"] and b["start"] and b["end"]) or "assumed" in (a["timing"], b["timing"]):
                continue
            lo, hi = max(a["start"], b["start"]), min(a["end"], b["end"])
            if (_d.datetime.fromisoformat(hi) - _d.datetime.fromisoformat(lo)).total_seconds() > 2:
                out.append({"a": a["name"], "b": b["name"], "from": lo, "to": hi})
    return out


def org_tree(rows):
    """Projects > surveys > cameras > recordings (in time order), with any
    recordings from one camera that overlap in time (they shouldn't: one camera
    records one file at a time). Files whose frame rate had to be assumed are
    left out of that check, and 2 s of overlap is allowed for. A project is
    shown if a listed recording is in it, or if nothing has been put in it yet."""
    listed = {r["path"] for r in rows}
    byc = {}
    for r in rows:
        byc.setdefault(r["camera_id"], []).append(r)
    used = {}
    for p, cid in _org()["of"].items():
        used.setdefault(cid, set()).add(p)
    tree = []
    for pj in _org()["projects"]:
        cids = [c["id"] for sv in pj["surveys"] for c in sv["cameras"]]
        shown = any(byc.get(c) for c in cids) or not any(used.get(c) for c in cids)
        if not shown:
            continue
        surveys = []
        for sv in sorted(pj["surveys"], key=lambda s: s["no"]):
            cams = []
            for c in sorted(sv["cameras"], key=lambda c: c["no"]):
                files = sorted(byc.get(c["id"], []), key=lambda r: (r["start"] or "", r["name"]))
                cams.append({"id": c["id"], "no": c["no"], "name": c.get("name") or "", "label": camera_label(c),
                             "paths": [r["path"] for r in files], "overlaps": _overlaps(files),
                             "join": bool(c.get("joined")), "joined": CAM_JOIN.get(c["id"], ""), "map": c.get("map"),
                             "surveyor": c.get("surveyor") or ""})
            surveys.append({"id": sv["id"], "no": sv["no"], "date": sv.get("date") or "", "label": survey_label(sv), "cameras": cams,
                            "surveyor": sv.get("surveyor") or "", "detectors": sv.get("detectors") or [],
                            "paths": [p for c in cams for p in c["paths"]]})
        tree.append({"id": pj["id"], "name": pj["name"], "surveys": surveys, "site": pj.get("site"), "template": len(pj.get("template") or []),
                     "paths": [p for sv in surveys for p in sv["paths"]]})
    unassigned = sorted([r for r in rows if not r["camera_id"]], key=lambda r: (os.path.dirname(r["path"]), r["start"] or "", r["name"]))
    return tree, [r["path"] for r in unassigned if r["path"] in listed]
