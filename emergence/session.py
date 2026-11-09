"""Per-recording state saved beside the recording, plus a background job queue."""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import traceback
from dataclasses import asdict

import numpy as np

from .analysis import SCAN_ID, clean_filters, end_spike, detect_events, roi_mask, scan, suggest, suggested_level, track_window, Event
from .ats import ATSFile
from .render import Renderer, export_event
from . import settings as cfg


# Filter persistence is one setting for the whole app (saved by app.py), so
# every recording is viewed and scanned the same way.
SETTINGS = {"filters": clean_filters()}


def _sidecar(path, ext):
    return path + ext


class Recording:
    """One .ats file with its ROI, activity trace and reviewed events."""

    def __init__(self, path: str, fps: float | None = None):
        self.path = path
        self.state = self._load_state()
        self.src = ATSFile(path, fps=fps or self.state.get("fps"))
        self.renderer = Renderer(self.src)
        self.renderer.filters = lambda: self.filters
        self.activity = self._load_activity()
        self._notes_to_comments()
        self._sync_units()

    def _sync_units(self):
        """If this recording was scanned in °C and the Settings tab now says °F
        (or the other way round), convert the stored scan, level and peaks
        instead of asking for a rescan. Scan values are temperature
        differences, so only the scale changes."""
        was, now = self.state.get("units"), self.src.units
        if was is None:
            if self.state.get("scanned"):
                self.state["units"] = "°C" if now in ("°C", "°F") else now   # older files were always °C
                was = self.state["units"]
            else:
                return
        if was == now or {was, now} != {"°C", "°F"}:
            return
        k = 1.8 if now == "°F" else 1 / 1.8
        if self.activity is not None:
            self.activity = (self.activity * k).astype(np.float32)
            np.save(_sidecar(self.path, ".activity.npy"), self.activity)
        for key in ("level", "suggested_level"):
            if self.state.get(key) is not None:
                self.state[key] = round(float(self.state[key]) * k, 4)
        for e in self.state.get("events", []):
            e["peak"] = float(e["peak"]) * k
        self.state["units"] = now
        self.save()

    @property
    def window(self) -> int:
        """Review window either side of an event, in frames (Settings tab)."""
        return int(round(cfg.get("detect", "window_s") * self.src.fps))

    def _notes_to_comments(self):
        cs = self.state.setdefault("comments", [])
        moved = False
        for e in self.state.get("events", []):
            if e.get("note"):
                cs.append({"id": max([c["id"] for c in cs], default=0) + 1, "frame": e["peak_frame"],
                           "text": e.pop("note"), "added": ""})
                moved = True
        if moved:
            self.save()

    # ---------------------------------------------------------- persistence
    def _load_state(self) -> dict:
        try:
            with open(_sidecar(self.path, ".analysis.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"roi": [], "events": [], "scanned": False}

    def save(self):
        self.state["fps"] = self.src.fps
        tmp = _sidecar(self.path, ".analysis.json.tmp")
        with open(tmp, "w") as f:
            json.dump(self.state, f, indent=1)
        os.replace(tmp, _sidecar(self.path, ".analysis.json"))

    def _load_activity(self):
        try:
            a = np.load(_sidecar(self.path, ".activity.npy"))
            return a if len(a) == self.src.n_frames else None
        except (OSError, ValueError):
            return None

    # ---------------------------------------------------------- analysis
    @property
    def roi(self):
        return self.state.get("roi") or []

    def set_roi(self, pts):
        self.state["roi"] = [[float(x), float(y)] for x, y in pts]
        self.save()

    @property
    def filters(self) -> dict:
        return clean_filters(SETTINGS["filters"])

    def run_scan(self, progress=None, should_stop=None):
        mask = roi_mask(self.roi, (self.src.height, self.src.width))
        if self.state.get("scan_id") != SCAN_ID:
            self.state.pop("level", None)   # an old level doesn't fit the new scan's values
        act = scan(self.src, mask, progress, should_stop)
        if len(act) < self.src.n_frames:
            return False  # cancelled
        self.activity = act
        np.save(_sidecar(self.path, ".activity.npy"), act)
        cut = self.end_cut
        self.state["suggested_level"] = self._suggest(act[:cut] if cut else act)
        self.state["units"] = self.src.units
        self.state["scanned"] = True
        self.state["scan_id"] = SCAN_ID
        self.redetect(self.state.get("level") or self.state["suggested_level"])
        return True

    _KEEP = ("status", "cls", "note", "tracks", "suggestion", "notes", "exports")

    def redetect(self, level: float):
        """Events = every rise above the detection level. Work already done on
        an event (decision, note, tracks) is archived, so it comes back if the
        same event reappears after the line is moved."""
        arch = self.state.setdefault("archive", {})
        for e in self.state.get("events", []):
            if e.get("status") != "todo" or e.get("note") or e.get("tracks"):
                arch[f"{e['f0']}-{e['f1']}"] = {k: e[k] for k in self._KEEP if k in e}
        cut = self.end_cut
        act = self.activity[:cut] if cut else self.activity
        evs = [asdict(e) for e in detect_events(act, self.src.fps, level=level, units=self.src.units,
                                                merge_s=cfg.get("detect", "merge_s"),
                                                min_frames=cfg.get("detect", "min_frames"))]
        for e in evs:
            prev = arch.get(f"{e['f0']}-{e['f1']}")
            if prev is None:  # same spike, slightly different edges at a new level
                for key, val in arch.items():
                    a, b = map(int, key.split("-"))
                    if a <= e["peak_frame"] <= b:
                        prev = {k: v for k, v in val.items() if k in ("status", "cls", "note")}
                        break
            if prev:
                e.update(prev)
        self.state["events"], self.state["level"] = evs, float(level)
        self.save()

    def _suggest(self, act):
        return suggested_level(act, sensitivity=cfg.SENSITIVITY[cfg.get("detect", "sensitivity")], units=self.src.units)

    def apply_detection_settings(self):
        """Sensitivity, merge gap or minimum length changed on the Settings
        tab: recompute the suggested level and the events. A level the user set
        themselves is kept; one that was just the old suggestion follows the
        new suggestion."""
        if self.activity is None:
            return
        old_sugg, level = self.state.get("suggested_level"), self.state.get("level")
        cut = self.end_cut
        self.state["suggested_level"] = self._suggest(self.activity[:cut] if cut else self.activity)
        if level is None or (old_sugg is not None and abs(level - old_sugg) < 1e-6):
            level = self.state["suggested_level"]
        self.redetect(level)

    @property
    def end_spike_frame(self):
        """Start of a very large spike at the end of the recording, if any."""
        if self.activity is None:
            return None
        return end_spike(self.activity, self.src.fps, self.src.units)

    @property
    def end_cut(self):
        """Where analysis stops. A very large spike at the end is always left
        out, and the final frame is never used (it's often a glitch as the
        recording stops)."""
        if self.activity is None:
            return None
        s = self.end_spike_frame
        return s if s is not None else max(1, len(self.activity) - 1)

    def activity_range(self, a: int, b: int, points: int):
        """Max-pooled activity between frames a and b, for the zoomable plot."""
        act = self.activity
        if act is None:
            return []
        a, b = max(0, int(a)), min(len(act) - 1, int(b))
        seg = act[a : b + 1]
        if len(seg) <= points:
            return [[a + k, round(float(v), 3)] for k, v in enumerate(seg)]
        edges = np.linspace(0, len(seg), points + 1).astype(int)
        out = []
        for k in range(points):
            s, e = int(edges[k]), max(int(edges[k]) + 1, int(edges[k + 1]))
            j = int(np.argmax(seg[s:e]))
            out.append([int(a + s + j), round(float(seg[s + j]), 3)])
        return out

    def track_event(self, n: int):
        ev = self.event(n)
        pad = self.window
        tr = track_window(self.src, max(0, ev["f0"] - pad),
                          min(self.src.n_frames - 1, ev["f1"] + pad), self.roi, filters=self.filters)
        head, notes = suggest(tr, self.src.fps)
        ev["tracks"], ev["suggestion"], ev["notes"] = tr, head, notes
        self.save()
        return ev

    def event(self, n: int) -> dict:
        for e in self.state.get("events", []):
            if e["n"] == n:
                return e
        raise KeyError(n)

    def decide(self, n, status=None, cls=None, note=None):
        e = self.event(n)
        if status is not None:
            e["status"] = status
        if cls is not None:
            e["cls"] = cls
        if note is not None:
            e["note"] = note
        self.save()
        return e

    # ---------------------------------------------------------- comments
    def add_comment(self, text: str, frame: int):
        cs = self.state.setdefault("comments", [])
        nid = max([c["id"] for c in cs], default=0) + 1
        frame = max(0, min(self.src.n_frames - 1, int(frame)))
        cs.append({"id": nid, "frame": frame, "text": text, "added": time.strftime("%d/%m/%Y %H:%M")})
        self.save()
        return self.summary()

    def delete_comment(self, cid):
        self.state["comments"] = [c for c in self.state.get("comments", []) if c["id"] != cid]
        self.save()
        return self.summary()

    def start_over(self, delete_comments=False, reset_level=True):
        """Undo every decision on this recording: all events go back to
        'to review', with no classification, tracks or archived decisions.
        Exported files on disk are left alone."""
        self.state["archive"] = {}
        for e in self.state.get("events", []):
            e["status"], e["cls"] = "todo", ""
            for k in ("tracks", "suggestion", "notes", "exports", "note"):
                e.pop(k, None)
        if delete_comments:
            self.state["comments"] = []
        if reset_level:
            self.state.pop("level", None)   # the rescan sets the suggested level
        self.save()

    def status(self) -> str:
        if not self.state.get("scanned"):
            return "Not analysed"
        evs = self.state.get("events", [])
        if evs and any(e["status"] == "todo" for e in evs):
            return "In review"
        return "Reviewed"

    def activity_preview(self, points=1200):
        a = self.activity
        if a is None:
            return []
        n = len(a)
        if n <= points:
            return [round(float(v), 3) for v in a]
        edges = np.linspace(0, n, points + 1).astype(int)
        return [round(float(a[edges[k]:edges[k + 1]].max()), 3) for k in range(points)]

    def export(self, n, opts, progress=None):
        ev = self.event(n)
        if not ev.get("tracks") and "entry_frames" in opts.get("items", []):
            ev = self.track_event(n)
        folder = (opts.get("folder") or cfg.get("export", "folder")
                  or os.path.join(os.path.dirname(self.path), "exports"))
        stem = os.path.splitext(os.path.basename(self.path))[0]
        site = os.path.basename(os.path.dirname(self.path))
        opts = {"naming": cfg.get("export", "naming"), "slowmo": cfg.get("export", "slowmo"),
                **opts, "filters": self.filters, "site": site, "recording": stem}
        files = export_event(self.src, ev, self.roi if opts.get("overlays", "roi+time") == "roi+time" else None,
                             folder, f"{site}_{stem}", opts, progress)
        ev.setdefault("exports", [])
        ev["exports"] = sorted(set(ev["exports"]) | set(files))
        self.save()
        return files

    def summary(self) -> dict:
        return {**self.src.info(), "status": self.status(), "roi": self.roi,
                "events": self.state.get("events", []), "scanned": bool(self.state.get("scanned")),
                "level": self.state.get("level"), "suggested_level": self.state.get("suggested_level"),
                "filters": self.filters,
                "scan_outdated": bool(self.state.get("scanned")) and self.state.get("scan_id") != SCAN_ID,
                "end_spike": self.end_spike_frame,
                "comments": sorted(self.state.get("comments", []), key=lambda c: c["frame"])}


class Jobs:
    """One worker thread; long jobs (scans, exports) report progress here."""

    def __init__(self):
        self.q = queue.Queue()
        self.current = None
        self.history = []
        self._cancel = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, label, fn):
        job = {"id": f"{time.time():.6f}", "label": label, "done": 0, "total": 1,
               "state": "queued", "result": None, "error": None}
        self.history.append(job)
        self.history = self.history[-50:]
        self.q.put((job, fn))
        return job

    def cancel(self):
        self._cancel.set()

    def _run(self):
        while True:
            job, fn = self.q.get()
            self._cancel.clear()
            self.current = job
            job["state"] = "running"

            def progress(d, t):
                job["done"], job["total"] = d, t

            try:
                job["result"] = fn(progress, self._cancel.is_set)
                job["state"] = "cancelled" if self._cancel.is_set() else "done"
            except Exception as e:  # report, keep the worker alive
                job["state"], job["error"] = "error", f"{e}"
                traceback.print_exc()
            self.current = None

    def snapshot(self):
        return [dict(j, result=None if isinstance(j["result"], (bytes,)) else j["result"]) for j in self.history]
