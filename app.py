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
    return {"path": p, "name": os.path.basename(p), "status": st,
            "size_gb": round(os.path.getsize(p) / 1e9, 2)}


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


def _expand(entry: str):
    """A pasted line -> .ats paths. A folder gives every .ats file in it."""
    p = os.path.normpath(os.path.expanduser(entry.strip().strip('"').strip()))
    if os.path.isdir(p):
        found = glob.glob(os.path.join(p, "*.ats")) + glob.glob(os.path.join(p, "*.ATS"))
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
    problems = []
    for entry in body.get("paths", []):
        if not entry.strip():
            continue
        found, err = _expand(entry)
        if err:
            problems.append(err)
        for f in found:
            if f not in state["files"]:
                state["files"].append(f)
    if not state["files"] and problems:
        return jsonify(error="; ".join(problems)), 404
    return jsonify(files=list_files(), problems=problems)


@app.post("/api/remove")
def remove():
    p = (request.json or {}).get("path")
    state["files"] = [f for f in state["files"] if f != p]
    if state["current"] == p:
        state["current"] = None
    return jsonify(files=list_files())


def list_files():
    return [_file_row(p) for p in state["files"] if os.path.exists(p)]


@app.get("/api/files")
def files():
    return jsonify(files=list_files(), current=state["current"])


@app.post("/api/open")
def open_rec():
    path = (request.json or {}).get("path")
    r = rec(path)
    state["current"] = path
    return jsonify(r.summary())


@app.get("/api/recording")
def recording():
    return jsonify(rec().summary())


@app.post("/api/fps")
def set_fps():
    r = rec()
    r.src.fps = float(request.json["fps"])
    r.save()
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
    img = r.renderer.image(i, mode, r.roi if roi else None, window_start=ws, palette=pal, rng=rng, opacity=op,
                           blend=how, enh=enh)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    from io import BytesIO
    resp = send_file(BytesIO(buf.tobytes()), mimetype="image/jpeg", max_age=0)
    for k, v in r.renderer.last_info.items():   # visible range and data range, for the colour bar
        resp.headers["X-" + k.replace("_", "-")] = f"{v:.4f}"
    return resp


APP_VERSION = "2026.11.09-startover"   # must match static/app.js


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
@app.post("/api/roi")
def set_roi():
    body = request.json or {}
    r = rec()
    r.set_roi(body.get("points", []))
    if body.get("all_files"):  # same camera position = same folder
        here = os.path.dirname(r.path)
        for row in list_files():
            if row["path"] != r.path and os.path.dirname(row["path"]) == here:
                rec(row["path"]).set_roi(r.roi)
    return jsonify(r.summary())


@app.post("/api/scan")
def start_scan():
    body = request.json or {}
    targets = [row["path"] for row in list_files()] if body.get("all") else [state["current"]]
    out = []
    for p in targets:
        r = rec(p)
        if not r.roi:
            continue
        out.append(jobs.submit(f"Scan {os.path.basename(p)}",
                               lambda prog, stop, r=r: {"ok": r.run_scan(prog, stop)}))
    return jsonify(jobs=out)


@app.post("/api/start-over")
def start_over():
    """Undo all decisions on the current recording, then scan it again."""
    b = request.json or {}
    r = rec()
    r.start_over(delete_comments=bool(b.get("delete_comments")), reset_level=bool(b.get("reset_level", True)))
    out = {"recording": r.summary(), "jobs": []}
    if r.roi:
        out["jobs"].append(jobs.submit(f"Scan {os.path.basename(r.path)} again",
                                       lambda prog, stop, r=r: {"ok": r.run_scan(prog, stop)}))
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
    unit_changed = ats.TEMP["unit"] != c["units"]["temp"]
    ats.TEMP["unit"] = c["units"]["temp"]
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
    out["location"] = r.state.get("report_location") or os.path.basename(os.path.dirname(r.path))
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
    out = os.path.join(folder, safe_name(f"{opts['location'] or 'survey'}_{stem}_report") + ".pdf")
    j = jobs.submit(f"PDF report: {os.path.basename(r.path)}",
                    lambda prog, stop: {"files": [build_report(r, out, opts, prog)], "report": out})
    return jsonify(job=j)


@app.get("/api/filters")
def get_filters():
    return jsonify(filters=SETTINGS["filters"])


@app.post("/api/filters")
def set_filters():
    """Frame persistence for Max Frame Interval and Sliding Subtraction,
    used by the High Sensitivity view, exports and the next scan."""
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
    return jsonify(values=r.activity_range(a, b, pts), frames=n, units=r.src.units, range=rng,
                   level=r.state.get("level"), suggested_level=r.state.get("suggested_level"))


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
        w.writerow(["event", "date", f"start_time ({zone})", f"end_time ({zone})", "first_frame", "last_frame", "peak", "units",
                    "status", "classification", "comments"])
        for e in evs:
            mine = [c["text"] for c in comments if event_of(c["frame"]) == e["n"]]
            w.writerow([e["n"], r.src.date_label(e["f0"]), r.src.time_label(e["f0"]), r.src.time_label(e["f1"]), e["f0"], e["f1"],
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
_BETA_OPEN = ("/api/beta", "/api/feedback", "/api/about", "/api/version", "/api/quit", "/api/settings",
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


def _watchdog(idle_s=180):
    """Without a console window there's nothing to close, so the program stops
    itself once no Track & Detect page has been open for a few minutes and
    nothing is being scanned or exported."""
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
