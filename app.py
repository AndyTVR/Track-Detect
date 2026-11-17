"""Track & Detect by Thermal Vision Ecology – local web app.

Run:  python app.py           (opens http://127.0.0.1:8765 in your browser)
Everything stays on this computer; nothing is uploaded anywhere.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import threading
import time
import webbrowser

import cv2
import numpy as np
from flask import Flask, jsonify, request, send_file, send_from_directory

from emergence.ats import ATSError
from emergence.session import SETTINGS, Jobs, Recording
from emergence.analysis import clean_filters
from emergence.fsutil import safe_replace

HERE = os.path.dirname(os.path.abspath(__file__))
# Packaged as a Windows program (PyInstaller): the bundled files live in a
# temporary folder, and settings and logs go to the user's AppData folder.
FROZEN = bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()   # PyInstaller or Nuitka
RES = getattr(sys, "_MEIPASS", HERE)
if FROZEN:
    DATA = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Track and Detect")
    os.makedirs(DATA, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:   # no console window: write output to a log
        _log = open(os.path.join(DATA, "program_log.txt"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or _log
        sys.stderr = sys.stderr or _log
else:
    DATA = HERE
app = Flask(__name__, static_folder=os.path.join(RES, "static"), static_url_path="/static")

from emergence import beta  # noqa: E402
beta.init(RES, DATA, FROZEN)
jobs = Jobs()
recs: dict[str, Recording] = {}
state = {"files": [], "current": None}
_lock = threading.Lock()


class UserError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


@app.errorhandler(UserError)
def _user_error(e):
    return jsonify(error=str(e)), e.code


def _note(msg):
    try:
        with open(os.path.join(DATA, "error_log.txt"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass
    print(msg, file=sys.stderr)


@app.errorhandler(Exception)
def _any_error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    import traceback
    tb = traceback.format_exc()
    try:
        with open(os.path.join(DATA, "error_log.txt"), "a", encoding="utf-8") as f:
            f.write(tb + "\n")
    except OSError:
        pass
    print(tb, file=sys.stderr)
    return jsonify(error=f"{type(e).__name__}: {e} (details in error_log.txt)"), 500


def rec(path=None) -> Recording:
    path = path or state["current"]
    if not path:
        raise UserError("No recording open")
    with _lock:
        if path not in recs:
            try:
                recs[path] = Recording(path)
            except ATSError as e:
                raise UserError(f"Could not read {os.path.basename(path)}: {e}", 422)
            except PermissionError:
                raise UserError(f"Windows refused access to {os.path.basename(path)}. If it is in Dropbox, "
                                "right-click it and choose 'Make available offline', then try again.", 422)
            except OSError as e:
                raise UserError(f"Could not open {os.path.basename(path)}: {e}", 422)
        return recs[path]


def _file_row(p):
    r = recs.get(p)
    if r is not None:
        st = r.status()
    else:
        st = "Not analysed"
        side = p + ".analysis.json"
        if os.path.exists(side):
            try:
                import json
                d = json.load(open(side))
                if d.get("scanned"):
                    st = "In review" if any(e["status"] == "todo" for e in d.get("events", [])) else "Reviewed"
            except (OSError, ValueError):
                pass
    t0, t1, timing = _file_times(p)
    return {"path": p, "name": os.path.basename(p), "status": st, "timing": timing,
            "size_gb": round(os.path.getsize(p) / 1e9, 2), **_place_row(p),
            "start": t0, "end": t1}


# ------------------------------------------------------------------ projects, surveys and cameras
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
    return os.path.join(DATA, "cameras.json")


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
        os.makedirs(DATA, exist_ok=True)
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
    cid = _org()["of"].get(p)
    n = _node(cid) if cid else None
    if not n or n[0] != "camera":
        return None
    return n[2], n[3], n[1]


def _paths_under(nid):
    """Listed recordings under a project, survey or camera ("unassigned" for those in none)."""
    if nid == "unassigned":
        return [p for p in state["files"] if _place(p) is None]
    n = _node(nid)
    if not n:
        return []
    kind, node = n[0], n[1]
    cams = ({node["id"]} if kind == "camera" else
            {c["id"] for c in node["cameras"]} if kind == "survey" else
            {c["id"] for sv in node["surveys"] for c in sv["cameras"]})
    return [p for p in state["files"] if _org()["of"].get(p) in cams]


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


_TIMES = {}


def _file_times(p):
    """A recording's start and end (UTC ISO times; None if not stored) and
    where its frame timing came from, cached."""
    try:
        key = (p, os.path.getmtime(p))
    except OSError:
        return None, None, None
    if key not in _TIMES:
        src, close = (recs[p].src, False) if p in recs else (None, True)
        try:
            if src is None:
                from emergence.ats import ATSFile
                src = ATSFile(p)
            t0 = src.time_utc(0) if src.start_time else None
            t1 = src.time_utc(src.n_frames - 1) if src.start_time else None
            _TIMES[key] = (t0.isoformat() if t0 else None, t1.isoformat() if t1 else None, src.fps_source)
        except Exception:
            _TIMES[key] = (None, None, None)
        finally:
            if close and src is not None:
                try:
                    src.close()
                except Exception:
                    pass
    return _TIMES[key]


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
                             "paths": [r["path"] for r in files], "overlaps": _overlaps(files)})
            surveys.append({"id": sv["id"], "no": sv["no"], "date": sv.get("date") or "", "label": survey_label(sv), "cameras": cams,
                            "paths": [p for c in cams for p in c["paths"]]})
        tree.append({"id": pj["id"], "name": pj["name"], "surveys": surveys,
                     "paths": [p for sv in surveys for p in sv["paths"]]})
    unassigned = sorted([r for r in rows if not r["camera_id"]], key=lambda r: (os.path.dirname(r["path"]), r["start"] or "", r["name"]))
    return tree, [r["path"] for r in unassigned if r["path"] in listed]


# ------------------------------------------------------------------ pages
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ------------------------------------------------------------------ folder & files
_PS_COMMON = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true; $owner.ShowInTaskbar = $false
$owner.StartPosition = 'CenterScreen'; $owner.Size = New-Object System.Drawing.Size(1,1)
$owner.Opacity = 0; $owner.Show(); $owner.Activate()
"""
_PS_FILES = _PS_COMMON + r"""
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Title = 'Choose .ats recordings'
$d.Filter = 'FLIR recordings (*.ats)|*.ats|All files (*.*)|*.*'
$d.Multiselect = $true
if (__START__) { $d.InitialDirectory = __START__ }
if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { $d.FileNames | ForEach-Object { [Console]::Out.WriteLine($_) } }
$owner.Close()
"""
_PS_FOLDER = _PS_COMMON + r"""
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = 'Choose a folder of .ats recordings'
$d.ShowNewFolderButton = $false
if (__START__) { $d.SelectedPath = __START__ }
if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.WriteLine($d.SelectedPath) }
$owner.Close()
"""
_last_dir = {"path": ""}


def _ps_str(v):
    return "'" + v.replace("'", "''") + "'"


def _dialog_windows(kind):
    import base64
    import subprocess
    start = _last_dir["path"] if os.path.isdir(_last_dir["path"]) else ""
    script = (_PS_FILES if kind == "files" else _PS_FOLDER).replace("__START__", _ps_str(start))
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", enc],
        capture_output=True, timeout=1800, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode("utf-8", "replace").strip()[-400:] or f"exit {out.returncode}")
    return out.stdout.decode("utf-8", "replace").lstrip("\ufeff")


def _dialog_tk(kind):
    import subprocess
    if kind == "files":
        ask = ("'\\n'.join(filedialog.askopenfilenames(title='Choose .ats recordings', "
               "filetypes=[('FLIR recordings', '*.ats'), ('All files', '*.*')]))")
    else:
        ask = "filedialog.askdirectory(title='Choose a folder of .ats recordings') or ''"
    code = ("import tkinter as tk; from tkinter import filedialog; r=tk.Tk(); r.withdraw(); "
            f"r.attributes('-topmost', True); r.lift(); r.focus_force(); print({ask})")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=1800)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else f"exit {out.returncode}")
    return out.stdout


def _run_dialog(kind):
    """Native file/folder picker. On Windows it uses the standard Windows
    dialog through PowerShell; elsewhere, Tk. Each runs in its own short-lived
    process, so it can't freeze the server."""
    errors = []
    tries = [_dialog_windows] if FROZEN else [_dialog_windows, _dialog_tk] if os.name == "nt" else [_dialog_tk]
    for fn in tries:
        try:
            text = fn(kind)
            paths = [os.path.normpath(p.strip()) for p in text.splitlines() if p.strip()]
            if paths:
                first = paths[0]
                _last_dir["path"] = first if os.path.isdir(first) else os.path.dirname(first)
            return paths
        except Exception as e:  # try the next method
            errors.append(f"{fn.__name__}: {e}")
            _note(f"file dialog failed ({fn.__name__}): {e}")
    raise RuntimeError("; ".join(errors))


@app.post("/api/pick")
def pick():
    kind = (request.json or {}).get("kind", "files")
    try:
        return jsonify(paths=_run_dialog(kind))
    except Exception as e:
        return jsonify(error="Couldn't open the file chooser on this computer. Paste the paths into the box instead "
                             f"(in File Explorer: select the files, then Shift + right-click > Copy as path). Details: {e}"), 500


def _expand(entry: str, deep=False):
    """A pasted line -> .ats paths. A folder gives every .ats file in it; with
    deep, also those in its subfolders (up to 3 levels down)."""
    p = os.path.normpath(os.path.expanduser(entry.strip().strip('"').strip()))
    if os.path.isdir(p):
        found = []
        for lvl in range(4 if deep else 1):
            pat = os.path.join(p, *(["*"] * lvl))
            found += glob.glob(os.path.join(pat, "*.ats")) + glob.glob(os.path.join(pat, "*.ATS"))
        return sorted(dict.fromkeys(os.path.normpath(f) for f in found)), None
    if os.path.isfile(p):
        if not p.lower().endswith(".ats"):
            return [], f"Not an .ats file: {os.path.basename(p)}"
        return [p], None
    return [], f"Not found: {p}"


@app.post("/api/add")
def add():
    """Add recordings (files and/or folders) to the list."""
    body = request.json or {}
    if body.get("replace"):
        state["files"] = []
    problems, added = [], []
    target = body.get("target")
    deep = isinstance(target, dict) and bool(target.get("folders"))
    roots = {}   # each recording -> the folder it was added from (for sorting by folder names)
    for entry in body.get("paths", []):
        if not entry.strip():
            continue
        found, err = _expand(entry, deep)
        if err:
            problems.append(err)
        top = os.path.normpath(os.path.expanduser(entry.strip().strip('"').strip()))
        for f in found:
            if f not in state["files"]:
                state["files"].append(f)
            added.append(f)
            roots[f] = top if os.path.isdir(top) else os.path.dirname(f)
    if not state["files"] and problems:
        return jsonify(error="; ".join(problems)), 404
    # where they go: left as they are (new ones unassigned), or into a project, survey and camera
    if deep:
        _file_by_folders(added, roots)
    else:
        _file_into(added, target)
    _save_org()
    first = next((f for f in added if os.path.exists(f)), None)
    return jsonify(_files_payload(problems=problems, added=added, first=first))


@app.post("/api/remove")
def remove():
    p = (request.json or {}).get("path")
    state["files"] = [f for f in state["files"] if f != p]
    if state["current"] == p:
        state["current"] = None
    return jsonify(_files_payload())


def list_files():
    return [_file_row(p) for p in state["files"] if os.path.exists(p)]


def _files_payload(**extra):
    rows = list_files()
    tree, unassigned = org_tree(rows)
    return {"files": rows, "tree": tree, "unassigned": unassigned, "current": state["current"], **extra}


@app.get("/api/files")
def files():
    return jsonify(_files_payload())


@app.post("/api/org")
def organise():
    """Organise recordings into projects, surveys and cameras.
    body.action:
      new_project {name} (comes with Survey 1 and Camera 1) · new_survey {project, date} (with Camera 1)
      new_camera {survey, name} · rename {id, name} (a project or camera) · set_date {id, date} (a survey)
      delete {id}: its recordings become unassigned
      move {paths, camera}: recordings into a camera ("" = unassigned)
      move_camera {id, survey}: a camera and its recordings into another survey"""
    b = request.json or {}
    org, act, out = _org(), b.get("action"), {}
    if act == "new_project":
        pj = _new_project(b.get("name", ""))
        sv = _new_survey(pj)
        out["created"] = _new_camera(sv)["id"]
    elif act == "new_survey":
        n = _node(b.get("project"))
        if not n or n[0] != "project":
            raise UserError("That project no longer exists")
        sv = _new_survey(n[1], b.get("date", ""))
        out["created"] = _new_camera(sv)["id"]
    elif act == "new_camera":
        n = _node(b.get("survey"))
        if not n or n[0] != "survey":
            raise UserError("That survey no longer exists")
        out["created"] = _new_camera(n[1], b.get("name", ""))["id"]
    elif act == "rename":
        n = _node(b.get("id"))
        if not n:
            raise UserError("That no longer exists")
        name = (b.get("name") or "").strip()[:40]
        if n[0] == "project":
            if not name:
                raise UserError("Give the project a name")
            if any(pj is not n[1] and pj["name"].lower() == name.lower() for pj in org["projects"]):
                raise UserError(f"There's already a project called {name}")
            n[1]["name"] = name
        elif n[0] == "camera":
            if name and any(c is not n[1] and (c.get("name") or "").lower() == name.lower() for c in n[3]["cameras"]):
                raise UserError(f"Survey {n[3]['no']} already has a camera called {name}")
            n[1]["name"] = name   # blank: just "Camera 2"
        else:
            raise UserError("Surveys are numbered; you can set their date")
    elif act == "set_date":
        n = _node(b.get("id"))
        if not n or n[0] != "survey":
            raise UserError("That survey no longer exists")
        n[1]["date"] = _clean_date(b.get("date", ""))
    elif act == "delete":
        n = _node(b.get("id"))
        if not n:
            raise UserError("That no longer exists")
        kind, node, pj, sv = n
        gone = ({node["id"]} if kind == "camera" else {c["id"] for c in node["cameras"]} if kind == "survey"
                else {c["id"] for s_ in node["surveys"] for c in s_["cameras"]})
        for p in [p for p, c in org["of"].items() if c in gone]:
            org["of"].pop(p)
        if kind == "camera":
            sv["cameras"].remove(node)
        elif kind == "survey":
            pj["surveys"].remove(node)
        else:
            org["projects"].remove(node)
    elif act == "move":
        cid = b.get("camera") or ""
        if cid:
            n = _node(cid)
            if not n or n[0] != "camera":
                raise UserError("That camera no longer exists")
        for p in b.get("paths") or []:
            if p not in state["files"]:
                continue
            if cid:
                org["of"][p] = cid
            else:
                org["of"].pop(p, None)
    elif act == "list_projects":   # every saved project, listed or not
        cams_of = {}
        for path, cid in org["of"].items():
            cams_of.setdefault(cid, []).append(path)
        out["projects"] = []
        for pj in org["projects"]:
            paths = [x for sv in pj["surveys"] for c in sv["cameras"] for x in cams_of.get(c["id"], [])]
            out["projects"].append({"id": pj["id"], "name": pj["name"], "surveys": len(pj["surveys"]),
                                    "cameras": sum(len(sv["cameras"]) for sv in pj["surveys"]),
                                    "recordings": len(paths), "missing": sum(1 for x in paths if not os.path.exists(x)),
                                    "listed": sum(1 for x in paths if x in state["files"]),
                                    "dates": sorted({sv["date"] for sv in pj["surveys"] if sv.get("date")})})
    elif act == "open_project":   # list every recording saved in a project
        n = _node(b.get("id"))
        if not n or n[0] != "project":
            raise UserError("That project no longer exists")
        if b.get("replace"):
            state["files"] = []
        cids = {c["id"] for sv in n[1]["surveys"] for c in sv["cameras"]}
        found = sorted((x for x, c in org["of"].items() if c in cids and os.path.exists(x)), key=lambda x: (x.lower()))
        for x in found:
            if x not in state["files"]:
                state["files"].append(x)
        out["first"] = next((x for c in [c for sv in sorted(n[1]["surveys"], key=lambda s: s["no"]) for c in sorted(sv["cameras"], key=lambda c: c["no"])]
                             for x in found if org["of"].get(x) == c["id"]), None)
        out["opened"] = len(found)
    elif act == "move_camera":
        n, t = _node(b.get("id")), _node(b.get("survey"))
        if not n or n[0] != "camera" or not t or t[0] != "survey":
            raise UserError("That camera or survey no longer exists")
        cam, src, dst = n[1], n[3], t[1]
        if src is not dst:
            if cam.get("name") and any((c.get("name") or "").lower() == cam["name"].lower() for c in dst["cameras"]):
                raise UserError(f"Survey {dst['no']} already has a camera called {cam['name']}. Rename one of them first.")
            src["cameras"].remove(cam)
            cam["no"] = max([c["no"] for c in dst["cameras"]] or [0]) + 1
            dst["cameras"].append(cam)
    else:
        raise UserError("Unknown action")
    _save_org()
    return jsonify({**_files_payload(), **out})


@app.post("/api/open")
def open_rec():
    path = (request.json or {}).get("path")
    r = rec(path)
    state["current"] = path
    return jsonify(r.summary())


@app.get("/api/recording")
def recording():
    return jsonify(rec().summary())


@app.get("/api/times")
def frame_times():
    """Every frame's time (seconds from the first frame) as little-endian
    float64s, from the per-frame time stamps; 204 when there aren't any."""
    import numpy as np
    r = rec(request.args.get("path") or None)
    t = r.src.frame_times()
    if t is None:
        return ("", 204)
    from flask import Response
    return Response(np.ascontiguousarray(t, dtype="<f8").tobytes(), mimetype="application/octet-stream",
                    headers={"Cache-Control": "no-store"})


@app.post("/api/fps")
def set_fps():
    """Set the frame rate by hand (body: fps), or fps 0 to go back to the
    file's own timing."""
    r = rec()
    v = float((request.json or {}).get("fps") or 0)
    if v > 0:
        r.src.fps, r.src.fps_source, r.src.fps_user = v, "set by you", True
        r.state["fps_set"] = True
        r.save()
    else:
        r.state.pop("fps_set", None)
        r.save()
        recs.pop(r.path, None)   # reopen: the file's own timing again
        r = rec(r.path)
    for k in [k for k in _TIMES if k[0] == r.path]:
        _TIMES.pop(k)
    return jsonify(r.summary())


# ------------------------------------------------------------------ frames
@app.get("/api/frame")
def frame():
    r = rec()
    i = int(request.args.get("i", 0))
    mode = request.args.get("mode", "raw")
    ws = int(request.args.get("ws", 0))
    roi = request.args.get("roi", "1") == "1"
    pal = request.args.get("pal") or None
    rng = None
    if request.args.get("lo") not in (None, "") and request.args.get("hi") not in (None, ""):
        rng = (float(request.args["lo"]), float(request.args["hi"]))
    op = min(1.0, max(0.0, float(request.args.get("op", 0.5))))
    how = "crossfade" if request.args.get("bm") == "crossfade" else "overlay"
    enh = {"dde": request.args.get("dde", 0), "tnr": request.args.get("tnr", 0)}
    hidden = set(filter(None, request.args.get("hide", "").split(",")))   # ROIs hidden in the app
    custom = None
    if mode == "custom":
        import json
        try:
            custom = json.loads(request.args.get("cf") or "{}")
        except ValueError:
            custom = {}
    img = r.renderer.image(i, mode, r.roi_shapes(hidden) if roi else None, window_start=ws, palette=pal, rng=rng,
                           opacity=op, blend=how, enh=enh, custom=custom)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    from io import BytesIO
    resp = send_file(BytesIO(buf.tobytes()), mimetype="image/jpeg", max_age=0)
    for k, v in r.renderer.last_info.items():   # visible range and data range, for the colour bar
        resp.headers["X-" + k.replace("_", "-")] = f"{v:.4f}"
    return resp


APP_VERSION = "2026.11.17-test"   # must match static/app.js


@app.get("/api/version")
def version():
    return jsonify(version=APP_VERSION)


@app.get("/api/palettes")
def palettes():
    from emergence.render import PALETTES, VIEW, palette_stops
    return jsonify(current=VIEW["palette"], palettes=[{"id": k, "label": v[0], "stops": palette_stops(k)}
                                                      for k, v in PALETTES.items()])


@app.post("/api/palette")
def set_palette():
    import json
    from emergence.render import PALETTES, VIEW
    p = (request.json or {}).get("palette")
    if p in PALETTES:
        VIEW["palette"] = p   # this session only; Settings > Save keeps it for next time
    return jsonify(current=VIEW["palette"])


# ------------------------------------------------------------------ ROI & analysis
def _share_rois(r):
    """Same camera = same view: give the other listed recordings from this
    recording's camera these ROIs."""
    cid = _org()["of"].get(r.path)
    if not cid:
        return
    for p in _paths_under(cid):
        if p != r.path and os.path.exists(p):
            rec(p).copy_rois_from(r)


@app.post("/api/roi")
def set_roi():
    """Set an ROI's outline (body: id, points)."""
    body = request.json or {}
    r = rec()
    r.set_roi(body.get("points", []), body.get("id"))
    if body.get("restore"):   # Cancel put the old outline back: it's unchanged since the last scan
        roi = r.roi_by_id(body.get("id") or r.rois[0]["id"])
        if roi is not None and not body.get("was_changed"):
            roi.pop("changed", None)
            r.save()
    if body.get("all_files"):
        _share_rois(r)
    return jsonify(r.summary())


@app.post("/api/rois")
def edit_rois():
    """Add, rename, delete an ROI, or tick it for scanning.
    body: {action: add|rename|delete|scan, id, name, scan, all_files}"""
    body = request.json or {}
    r = rec()
    act = body.get("action")
    out = {}
    if act == "add":
        out["added"] = r.add_roi(body.get("name"))["id"]
    elif act == "rename":
        r.update_roi(body["id"], name=body.get("name"))
    elif act == "scan":
        r.update_roi(body["id"], scan=bool(body.get("scan")))
    elif act == "delete":
        r.delete_roi(body["id"])
    else:
        raise UserError("Unknown ROI action")
    if body.get("all_files"):
        _share_rois(r)
    return jsonify({**r.summary(), **out})


@app.post("/api/scan")
def start_scan():
    body = request.json or {}
    if body.get("node"):   # every recording in a project, survey or camera, or every unassigned one
        targets = [p for p in _paths_under(body["node"]) if os.path.exists(p)]
    else:
        targets = [row["path"] for row in list_files()] if body.get("all") else [state["current"]]
    # "a" and "b": scan only those frames of the current recording (the play limits)
    part = None if body.get("all") or body.get("node") or body.get("a") is None else [[int(body["a"]), int(body["b"])]]
    out = []
    for p in targets:
        r = rec(p)
        ids = [x["id"] for x in r.rois if len(x.get("points") or []) >= 3 and x.get("scan", True)]
        if not ids:
            continue
        label = f"Scan {os.path.basename(p)}" + (" (play limits)" if part else "")
        if len(r.rois) > 1:
            label += f", {len(ids)} ROI{'s' if len(ids) != 1 else ''}"
        out.append(jobs.submit(label, lambda prog, stop, r=r, ids=ids: {"ok": r.run_scan(prog, stop, ranges=part, roi_ids=ids)},
                               path=p, kind="scan"))
    return jsonify(jobs=out, skipped=len(targets) - len(out))


@app.post("/api/start-over")
def start_over():
    """Reset every decision on the current recording; optionally delete the
    comments, go back to the suggested level, and scan it again."""
    b = request.json or {}
    r = rec()
    part = r.scanned_ranges if r.unscanned_ranges else None   # a part scan is redone over the same frames
    reset_level = bool(b.get("reset_level"))
    r.start_over(delete_comments=bool(b.get("delete_comments")), reset_level=reset_level)
    out = {"recording": r.summary(), "jobs": []}
    if b.get("rescan") and r.roi:
        out["jobs"].append(jobs.submit(f"Scan {os.path.basename(r.path)} again",
                                       lambda prog, stop, r=r: {"ok": r.run_scan(prog, stop, ranges=part, fresh=True)},
                                       path=r.path, kind="scan"))
    elif reset_level and r.acts:
        r.redetect(r.state.get("suggested_level") or 0)
        out["recording"] = r.summary()
    return jsonify(out)


@app.post("/api/level")
def set_level():
    """Move the detection line: events are re-detected at the new level."""
    r = rec()
    if r.activity is None:
        raise UserError("Scan the recording first")
    body = request.json or {}
    level = r.state.get("suggested_level") if body.get("suggested") else float(body["level"])
    r.redetect(level)
    return jsonify(r.summary())


SETTINGS_PATH = os.path.join(DATA, "settings.json")


def _apply_settings(old=None):
    """Push the saved settings into the parts of the program that use them."""
    from emergence import ats, render, settings as cfg
    c = cfg.CURRENT
    SETTINGS["filters"] = clean_filters(c["filters"])
    render.VIEW["palette"] = c["view"]["palette"]
    render.LABEL["scale"] = cfg.TEXT_SCALE[c["export"]["text_size"]]
    ats.TIME["zone"], ats.TIME["offset_s"] = c["units"]["zone"], c["units"]["clock_offset_s"]
    unit = "counts" if c["units"]["scale"] == "counts" else c["units"]["temp"]
    unit_changed = ats.TEMP["unit"] != unit
    ats.TEMP["unit"] = unit
    if unit_changed:
        with _lock:
            recs.clear()   # reopen recordings so their values convert to the new unit
    if old is not None and old.get("detect") != c["detect"]:
        for r in list(recs.values()):
            r.apply_detection_settings()


def _load_settings():
    from emergence import settings as cfg
    cfg.load(SETTINGS_PATH)
    _apply_settings()


def _save_settings():
    from emergence import settings as cfg
    try:
        cfg.save(SETTINGS_PATH)
    except OSError:
        pass


@app.get("/api/settings")
def get_settings():
    from emergence import settings as cfg
    return jsonify(settings=cfg.CURRENT, defaults=cfg.clean(cfg.DEFAULTS))


@app.post("/api/settings")
def put_settings():
    """Save settings from the Settings tab (also used by Import and Reset)."""
    import copy
    from emergence import settings as cfg
    b = request.json or {}
    old = copy.deepcopy(cfg.CURRENT)
    new = cfg.DEFAULTS if b.get("reset") else b.get("settings")
    if not isinstance(new, dict):
        raise UserError("That doesn't look like a Track & Detect settings file")
    cfg.CURRENT.clear(); cfg.CURRENT.update(cfg.clean(new))
    try:
        cfg.save(SETTINGS_PATH)
    except OSError as e:
        raise UserError(f"Couldn't save settings: {e}")
    _apply_settings(old)
    out = {"settings": cfg.CURRENT}
    if state.get("current"):
        out["recording"] = rec().summary()
    return jsonify(out)


REPORT_FIELDS = ("company", "contact", "location", "camera", "analyst")


@app.get("/api/report-defaults")
def report_defaults():
    r = rec()
    from emergence import settings as cfg
    saved = cfg.CURRENT.get("report", {})
    out = {k: saved.get(k, "") for k in ("company", "contact", "analyst", "camera")}
    out["camera"] = out["camera"] or r.src.camera or ""
    out["location"] = r.state.get("report_location") or (_place(r.path) or [{"name": os.path.basename(os.path.dirname(r.path))}])[0]["name"]   # the project name to start with
    out["folder"] = cfg.get("export", "folder") or os.path.join(os.path.dirname(r.path), "exports")
    out["reviewed"] = all(e["status"] != "todo" for e in r.state.get("events", []))
    return jsonify(out)


@app.post("/api/report")
def make_report():
    from emergence.report import build_report
    from emergence.render import safe_name
    r = rec()
    if not r.state.get("scanned"):
        raise UserError("Scan the recording first")
    b = request.json or {}
    opts = {k: (b.get(k) or "").strip() for k in REPORT_FIELDS}
    opts["rejected_images"] = bool(b.get("rejected_images", True))
    opts["blend"] = "crossfade" if b.get("blend") == "crossfade" else "overlay"
    opts["enh"] = b.get("enh") or {}
    opts["opacity"] = min(1.0, max(0.0, float(b.get("opacity", 0.8))))
    opts["palette"] = b.get("palette") or None
    rb = b.get("blend_range")
    opts["blend_range"] = (float(rb[0]), float(rb[1])) if rb and len(rb) == 2 else None
    from emergence import settings as cfg
    cfg.CURRENT["report"] = {k: opts[k] for k in ("company", "contact", "analyst", "camera")}
    _save_settings()   # report details are remembered as soon as a report is made
    r.state["report_location"] = opts["location"]
    r.save()
    folder = ((b.get("folder") or "").strip() or cfg.get("export", "folder")
              or os.path.join(os.path.dirname(r.path), "exports"))
    os.makedirs(folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(r.path))[0]
    fmt = "docx" if b.get("format") == "docx" else "pdf"
    out = os.path.join(folder, safe_name(f"{opts['location'] or 'survey'}_{stem}_report") + "." + fmt)
    j = jobs.submit(f"{'Word' if fmt == 'docx' else 'PDF'} report: {os.path.basename(r.path)}",
                    lambda prog, stop: {"files": [build_report(r, out, opts, prog)], "report": out})
    return jsonify(job=j)


@app.get("/api/filters")
def get_filters():
    return jsonify(filters=SETTINGS["filters"])


@app.post("/api/filters")
def set_filters():
    """Frame persistence for Max Frame Interval and Sliding Subtraction,
    used by the Detection view's trails, exports and the next scan."""
    import json
    b = request.json or {}
    SETTINGS["filters"] = clean_filters({**SETTINGS["filters"], **{k: b[k] for k in ("mfi", "ss") if k in b}})
    # this session only; Settings > Save keeps it for next time
    return jsonify(rec().summary() if state.get("current") else {"filters": SETTINGS["filters"]})


@app.get("/api/activity")
def activity():
    r = rec()
    n = r.src.n_frames
    a = int(request.args.get("a", 0))
    b = int(request.args.get("b", n - 1))
    pts = max(50, min(4000, int(request.args.get("points", 1200))))
    act = r.activity
    rng = [float(np.percentile(act, 1)), float(act.max())] if act is not None and len(act) else None
    return jsonify(values=r.activity_range(a, b, pts), series=r.activity_series(a, b, pts), frames=n, units=r.src.units, range=rng,
                   level=r.state.get("level"), suggested_level=r.state.get("suggested_level"))


@app.get("/api/scan-live")
def scan_live():
    """The current recording's scan so far, while it runs."""
    r = rec()
    n = r.src.n_frames
    a = int(request.args.get("a", 0))
    b = int(request.args.get("b", n - 1))
    pts = max(50, min(4000, int(request.args.get("points", 1200))))
    lv = r.live_range(a, b, pts)
    return jsonify(live=lv is not None, units=r.src.units, frames=n, **(lv or {}))


@app.post("/api/test-scan")
def test_scan():
    """A quick look at background noise: scan one randomly chosen minute of a
    recording from a camera (or the current recording) with its ROIs, without
    saving anything, and rate the noise between spikes."""
    import random
    b = request.json or {}
    paths = [p for p in (_paths_under(b["node"]) if b.get("node") else [state["current"]]) if p and os.path.exists(p)]
    cands = [p for p in paths if any(len(x.get("points") or []) >= 3 for x in rec(p).rois)]
    if not cands:
        raise UserError("Draw an ROI on a recording from this camera first (tick 'Use for every file from this camera' to share it)")
    p = random.choice(cands)
    r = rec(p)
    n, fps = r.src.n_frames, r.src.fps
    length = int(min(n, max(fps * 60, 30)))   # one minute
    edge = int(min(fps * 10, max(0, n - length) // 4))
    a = random.randint(edge, max(edge, n - length - edge))
    bb = min(n - 1, a + length - 1)
    rois = [x for x in r.rois if len(x.get("points") or []) >= 3]

    def work(prog, stop):
        from emergence.analysis import roi_mask, scan_multi, suggested_level, noise_stats
        shape = (r.src.height, r.src.width)
        seg = scan_multi(r.src, [roi_mask(x["points"], shape) for x in rois], prog, stop, start=a, stop=bb)
        if seg.shape[1] < bb - a + 1:
            return {"cancelled": True}
        sens = cfg_mod().SENSITIVITY[cfg_mod().get("detect", "sensitivity")]
        out = []
        for j, x in enumerate(rois):
            act = seg[j]
            lvl = suggested_level(act, sens, r.src.units)
            quiet = act <= lvl
            hot = np.flatnonzero(~quiet)
            pad = int(fps)
            for i in hot:
                quiet[max(0, i - pad):i + pad + 1] = False
            st = noise_stats(act, quiet, fps, lvl, r.src.units) or {}
            spikes = int(((act[1:] > lvl) & (act[:-1] <= lvl)).sum() + (act[0] > lvl))
            out.append({"roi": x["id"], "name": x["name"], "level": float(lvl), "spikes": spikes, **st})
        return {"test": {"path": p, "name": os.path.basename(p), "a": a, "b": bb, "seconds": (bb - a + 1) / fps, "whole": bb - a + 1 >= n,
                         "from": r.src.time_label(a), "to": r.src.time_label(bb), "date": r.src.date_label(a),
                         "units": r.src.units, "rois": out}}

    j = jobs.submit(f"Test scan of {os.path.basename(p)}", work, path=p, kind="test")
    return jsonify(job=j)


def cfg_mod():
    from emergence import settings as cfg
    return cfg


@app.post("/api/export-camera")
def export_camera():
    """Every recording from a camera, in time order, as one MP4 (or just this
    recording if it isn't in a camera)."""
    from emergence.render import export_recordings_video, safe_name
    b = request.json or {}
    cur = state["current"]
    cid = _org()["of"].get(cur) if cur else None
    if cid:
        pj, sv, c = _place(cur)
        rows = sorted([_file_row(p) for p in _paths_under(cid) if os.path.exists(p)], key=lambda x: (x["start"] or "", x["name"]))
        paths = [x["path"] for x in rows]
        name = f"{pj['name']}_Survey{sv['no']}{('_' + sv['date']) if sv.get('date') else ''}_{camera_label(c).replace(': ', '_')}"
    else:
        if not cur:
            raise UserError("Open a recording first")
        paths, name = [cur], os.path.splitext(os.path.basename(cur))[0]
    folder = (b.get("folder") or cfg_mod().get("export", "folder") or os.path.join(os.path.dirname(paths[0]), "exports"))
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, safe_name(name) + ("_detection" if b.get("mode") == "blend" else "") + ".mp4")
    recs_ = [rec(p) for p in paths]
    opts = {k: b.get(k) for k in ("mode", "palette", "blend", "opacity", "enh", "overlays", "quality")}
    j = jobs.submit(f"Camera video: {os.path.basename(out)}",
                    lambda prog, stop: {"files": export_recordings_video(recs_, out, opts, prog, stop)}, kind="export")
    return jsonify(job=j, path=out, recordings=len(paths))


@app.post("/api/event/<int:n>/track")
def track(n):
    return jsonify(rec().track_event(n))


@app.post("/api/event/<int:n>/decide")
def decide(n):
    b = request.json or {}
    return jsonify(rec().decide(n, b.get("status"), b.get("cls"), b.get("note")))


@app.post("/api/event/<int:n>/export")
def export(n):
    r = rec()
    opts = request.json or {}
    j = jobs.submit(f"Export event {n}", lambda prog, stop: {"files": r.export(n, opts, prog)})
    return jsonify(job=j)


@app.post("/api/export-confirmed")
def export_confirmed():
    r = rec()
    opts = request.json or {}
    out = [jobs.submit(f"Export event {e['n']}", lambda prog, stop, n=e["n"]: {"files": r.export(n, opts, prog)})
           for e in r.state.get("events", []) if e["status"] == "confirmed"]
    return jsonify(jobs=out)


@app.post("/api/comment")
def add_comment():
    b = request.json or {}
    text = (b.get("text") or "").strip()
    if not text:
        raise UserError("Type a comment first")
    return jsonify(rec().add_comment(text, int(b.get("frame", 0))))


@app.post("/api/comment/delete")
def delete_comment():
    return jsonify(rec().delete_comment((request.json or {}).get("id")))


@app.post("/api/events-csv")
def events_csv():
    import csv
    r = rec()
    stem = os.path.splitext(r.path)[0]
    pad = r.window
    evs = r.state.get("events", [])
    comments = sorted(r.state.get("comments", []), key=lambda c: c["frame"])

    def event_of(frame):
        for e in evs:
            if e["f0"] - pad <= frame <= e["f1"] + pad:
                return e["n"]
        return ""

    p = stem + "_events.csv"
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        zone = r.src.zone_of(0) or "elapsed"
        w.writerow(["event", "roi", "date", f"start_time ({zone})", f"end_time ({zone})", "first_frame", "last_frame", "peak", "units",
                    "status", "classification", "comments"])
        for e in evs:
            mine = [c["text"] for c in comments if event_of(c["frame"]) == e["n"]]
            w.writerow([e["n"], r.roi_name(e.get("roi")), r.src.date_label(e["f0"]), r.src.time_label(e["f0"]), r.src.time_label(e["f1"]), e["f0"], e["f1"],
                        round(e["peak"], 2), r.src.units, e["status"], e.get("cls", ""), " | ".join(mine)])
    files = [p]
    if comments:
        pc = stem + "_comments.csv"
        with open(pc, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["date", f"time ({r.src.zone_of(0) or 'elapsed'})", "frame", "event", "comment", "added"])
            for c in comments:
                w.writerow([r.src.date_label(c["frame"]), r.src.time_label(c["frame"]), c["frame"], event_of(c["frame"]), c["text"], c.get("added", "")])
        files.append(pc)
    return jsonify(path=p, files=files)


@app.get("/api/jobs")
def job_list():
    return jsonify(jobs=jobs.snapshot())


@app.post("/api/jobs/cancel")
def job_cancel():
    jobs.cancel()
    return jsonify(ok=True)


@app.post("/api/open-path")
def open_path():
    p = (request.json or {}).get("path")
    if p and os.path.exists(p) and sys.platform.startswith("win"):
        os.startfile(p)  # noqa: opens Explorer / default viewer on Windows
    return jsonify(ok=True)


# ---------------------------------------------------------------- running as a program
_last_seen = {"t": time.time()}


@app.before_request
def _seen():
    _last_seen["t"] = time.time()


# ---------------------------------------------------------------- customer beta
_BETA_OPEN = ("/api/ping", "/api/beta", "/api/feedback", "/api/about", "/api/version", "/api/quit", "/api/settings",
              "/api/palettes", "/api/filters")


@app.before_request
def _beta_gate():
    """While the licence hasn't been accepted, or after the beta has ended,
    nothing can be opened or analysed."""
    why = beta.blocked()
    if why and request.path.startswith("/api/") and not request.path.startswith(_BETA_OPEN):
        msg = ("This beta has ended. Please contact Thermal Vision Ecology for the latest version."
               if why == "expired" else "Please accept the beta licence first.")
        return jsonify(error=msg, beta=why), 403


@app.get("/api/beta")
def beta_status():
    s = beta.status()
    if s["active"]:
        try:
            with open(os.path.join(RES, "LICENCE-BETA.txt"), encoding="utf-8") as fh:
                s["licence_text"] = fh.read()
        except OSError:
            s["licence_text"] = ""
    return jsonify(s)


@app.post("/api/beta/accept")
def beta_accept():
    return jsonify(beta.accept_licence())


# ---------------------------------------------------------------- feedback
FEEDBACK_TYPES = {"bug": "Bug", "broken": "Something isn't working", "idea": "Feature idea", "other": "Other"}


def _desktop():
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and os.path.isdir(buf.value):
                return buf.value
        except Exception:
            pass
    d = os.path.join(os.path.expanduser("~"), "Desktop")
    return d if os.path.isdir(d) else DATA


def _tail(path, n=200_000):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2); size = fh.tell(); fh.seek(max(0, size - n))
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return None


@app.post("/api/feedback")
def feedback():
    """Feedback form: write a small zip (never recordings, images or file
    names) and open a ready-to-send email to Thermal Vision Ecology."""
    import json
    import platform
    import urllib.parse
    import zipfile
    from emergence import settings as cfg
    b = request.json or {}
    kind = FEEDBACK_TYPES.get(b.get("type"), "Other")
    summary = (b.get("summary") or "").strip()[:200]
    if not summary:
        raise UserError("Please add a one-line summary")
    fields = [("Type", kind), ("Summary", summary), ("Details", (b.get("details") or "").strip()[:20000]),
              ("Steps to reproduce", (b.get("steps") or "").strip()[:10000]),
              ("Which recording / event", (b.get("where") or "").strip()[:500]),
              ("Name", (b.get("name") or "").strip()[:200]), ("Email for replies", (b.get("email") or "").strip()[:200])]
    st = beta.status()
    tech = {"product": st.get("product"), "version": st.get("version"), "channel": st.get("channel"),
            "app_build": APP_VERSION, "windows": platform.platform(), "python": platform.python_version(),
            "days_left": st.get("days_left"), "time": time.strftime("%d/%m/%Y %H:%M")}
    text = "\n\n".join(f"{k}:\n{v}" for k, v in fields if v) + "\n\n---\n" + "\n".join(f"{k}: {v}" for k, v in tech.items())
    stamp = time.strftime("%Y-%m-%d %H%M")
    zpath = os.path.join(_desktop(), f"Track and Detect feedback {stamp}.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("feedback.txt", text)
        if b.get("diagnostics", True):
            z.writestr("technical.json", json.dumps(tech, indent=1))
            z.writestr("settings.json", json.dumps(cfg.CURRENT, indent=1))
            if state.get("current"):   # what kind of recording, but not its name or location
                r = rec()
                z.writestr("recording.json", json.dumps({k: r.summary().get(k) for k in (
                    "camera", "width", "height", "fps", "frames", "duration_s", "units", "scanned", "level",
                    "suggested_level")} | {"events": len(r.state.get("events", []))}, indent=1, default=str))
            for name in ("error_log.txt", "program_log.txt"):
                t = _tail(os.path.join(DATA, name))
                if t:
                    z.writestr(name, t)
    to = beta.INFO.get("feedback_email", "")
    subject = f"Track & Detect {tech['version']} – {kind}: {summary}"
    body = text if len(text) < 1500 else text[:1500] + "\n\n[…the rest is in feedback.txt in the attached zip]"
    body += f"\n\nPlease attach: {os.path.basename(zpath)} (saved on your desktop)"
    mailto = f"mailto:{urllib.parse.quote(to)}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
    if os.name == "nt":
        try:
            os.startfile(mailto)   # the customer's own email program
            import subprocess
            subprocess.Popen(["explorer", "/select,", zpath])
        except OSError:
            pass
    return jsonify(zip=zpath, mailto=mailto, email=to, text=text, subject=subject)


@app.post("/api/quit")
def quit_app():
    """The Quit button: stop the program (after this reply has gone)."""
    threading.Timer(0.4, lambda: os._exit(0)).start()
    return jsonify(ok=True)


@app.get("/api/about")
def about():
    return jsonify(version=APP_VERSION, frozen=FROZEN, data=DATA, product_version=beta.INFO.get("version", "dev"))


@app.get("/api/ping")
def ping():
    """The page's heartbeat: keeps the program running while its window is open."""
    return jsonify(ok=True)


def _watchdog(idle_s=900):
    """Without a console window there's nothing to close, so the program stops
    itself once no Track & Detect page has been open for 15 minutes and nothing
    is being scanned or exported. An open page checks in every 20 seconds
    (/api/ping), even while it's sitting idle, so this never stops a program
    that's still on screen."""
    while True:
        time.sleep(15)
        busy = jobs.current is not None or not jobs.q.empty()
        if not busy and time.time() - _last_seen["t"] > idle_s:
            os._exit(0)


def _already_running(port):
    """Is Track & Detect already running on this port? (Double-clicking the
    program again should just open another window onto it.)"""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/about", timeout=1.5) as r:
            return "version" in json.loads(r.read().decode())
    except Exception:
        return False


def _port_free(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _find_app_browser():
    """Microsoft Edge (part of Windows 10 and 11), or Chrome, which can show
    Track & Detect as its own app window. TD_APP_BROWSER overrides, for testing."""
    if os.environ.get("TD_APP_BROWSER"):
        return os.environ["TD_APP_BROWSER"]
    if os.name != "nt":
        return None
    roots = [os.environ.get(k) for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
    for root in filter(None, roots):
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            p = os.path.join(root, rel)
            if os.path.isfile(p):
                return p
    return None


def _open_window(url, watch=False):
    """Open Track & Detect in its own window (Settings > Appearance), falling
    back to a normal browser tab. With watch=True, closing that window closes
    the program too, once any scan or export has finished."""
    from emergence import settings as cfg
    exe = _find_app_browser() if cfg.get("appearance", "window") == "app" else None
    if not exe:
        webbrowser.open(url)
        return
    import subprocess
    # its own browser profile, so it gets its own window and taskbar button
    profile = os.path.join(os.environ.get("LOCALAPPDATA") or DATA, "Track and Detect", "window")
    args = [exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1500,960",
            "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]
    args += os.environ.get("TD_APP_BROWSER_ARGS", "").split()
    try:
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        webbrowser.open(url)
        return
    if not watch:
        return
    def wait():
        t0 = time.time()
        proc.wait()
        if time.time() - t0 < 5:      # handed over to a window that was already open
            return
        while jobs.current is not None or not jobs.q.empty():
            time.sleep(2)             # let a running scan or export finish first
        os._exit(0)
    threading.Thread(target=wait, daemon=True).start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("paths", nargs="*", help=".ats files or folders to list")
    a = ap.parse_args()
    port = a.port
    if _already_running(port):
        _load_settings()
        _open_window(f"http://127.0.0.1:{port}")
        return
    while not _port_free(port) and port < a.port + 20:   # something else has the port
        port += 1
    _load_settings()
    for p in a.paths:
        for f in _expand(p)[0]:
            if f not in state["files"]:
                state["files"].append(f)
    url = f"http://127.0.0.1:{port}"
    if not a.no_browser:
        threading.Timer(1.0, lambda: _open_window(url, watch=True)).start()
    if FROZEN:
        threading.Thread(target=_watchdog, daemon=True).start()
    print(f"Track & Detect running at {url}  (close this window to stop)")
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
