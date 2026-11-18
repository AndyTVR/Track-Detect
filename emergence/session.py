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

from .analysis import SCAN_ID, Pipeline, clean_filters, end_spike, frozen_mask, detect_events, mode_cfg, roi_mask, scan, scan_multi, suggest, suggested_level, track_window, Event
from .ats import ATSFile
from .render import Renderer, export_event
from . import settings as cfg
from .fsutil import read_json, safe_replace, write_json


# Filter persistence is one setting for the whole app (saved by app.py), so
# every recording is viewed and scanned the same way.
SETTINGS = {"filters": clean_filters()}


def _sidecar(path, ext):
    """A recording's own file: in its project's folder (see fsutil.side_path)."""
    from .fsutil import side_path
    return side_path(path, ext)


def _merge_ranges(rs):
    """Sorted, non-overlapping [first, last] frame ranges."""
    out = []
    for a, b in sorted([int(a), int(b)] for a, b in rs):
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _range_mask(rs, n):
    m = np.zeros(n, bool)
    for a, b in rs:
        m[a:b + 1] = True
    return m


ROI_COLOURS = ["#E5484D", "#3E9BFF", "#F5A524", "#A26CF5", "#2EC4B6", "#FF7AB6", "#9BE15D", "#FF8A3D"]


# Joined recordings: virtual path -> the recordings joined into it (set by the app)
JOINS: dict = {}


class Recording:
    """One .ats file with its ROIs, an activity trace for each ROI, and the
    reviewed events (each found in one ROI)."""

    def __init__(self, path: str, fps: float | None = None):
        self.path = path
        self.state = self._load_state()
        # only a frame rate the user typed in overrides the file's own timing
        # (older versions saved an assumed 16 fps here for every file)
        if path in JOINS:
            from .joined import JoinedSource
            self.src = JoinedSource(path, JOINS[path])
            names = [os.path.basename(x.path) for x in self.src.parts]
            if self.state.get("members") not in (None, names):   # the files joined have changed: earlier work doesn't line up
                for k in ("events", "level", "suggested_level", "scanned", "roi_scans", "archive"):
                    self.state.pop(k, None)
                for e in (".activity.npz",):
                    try:
                        os.remove(_sidecar(path, e))
                    except OSError:
                        pass
            self.state["members"] = names
        else:
            self.src = ATSFile(path, fps=fps or (self.state.get("fps") if self.state.get("fps_set") else None))
        self.renderer = Renderer(self.src)
        self.renderer.filters = lambda: self.filters
        self.acts = self._load_activity()       # ROI id -> activity trace
        self._notes_to_comments()
        self._sync_units()
        if self.acts and self.state.get("scanned"):   # the suggestion follows the current rule (0.2 °C above the background)
            try:
                old_sugg = self.state.get("suggested_level")
                self.state["suggested_level"] = self._suggest_scanned()
                lv = self.state.get("level")
                if lv is None or (old_sugg is not None and abs(lv - old_sugg) < 1e-6):
                    lv = self.state["suggested_level"]
                # events follow the current rules (camera freezes and end spikes
                # left out); decisions already made carry over
                self.redetect(lv)
            except Exception:
                pass

    # ---------------------------------------------------------- activity traces
    @property
    def activity(self):
        """The combined trace (the highest of the ROIs at each frame), or None
        before any scan."""
        arrs = [a for rid, a in self.acts.items() if self.roi_by_id(rid)]
        if not arrs:
            return None
        return np.max(np.vstack(arrs), axis=0) if len(arrs) > 1 else arrs[0]

    def _save_activity(self):
        p = _sidecar(self.path, ".activity.npz")
        tmp = p + ".tmp.npz"
        np.savez(tmp, **{rid: a for rid, a in self.acts.items()})
        safe_replace(tmp, p)

    def _load_activity(self) -> dict:
        n = self.src.n_frames
        try:
            with np.load(_sidecar(self.path, ".activity.npz")) as z:
                return {k: z[k] for k in z.files if len(z[k]) == n}
        except (OSError, ValueError):
            pass
        try:   # a scan from before ROIs had names: it belongs to the first ROI
            a = np.load(_sidecar(self.path, ".activity.npy"))
            if len(a) == n and self.state.get("scanned") and self.rois:
                return {self.rois[0]["id"]: a}
        except (OSError, ValueError):
            pass
        return {}

    def _sync_units(self):
        """If this recording was scanned in one unit (°C, °F or raw counts) and
        the Settings tab now says another, convert the stored scan, level and
        peaks instead of asking for a rescan."""
        was, now = self.state.get("units"), self.src.units
        if was is None:
            if self.state.get("scanned"):
                self.state["units"] = "°C" if now in ("°C", "°F") else now   # older files were always °C
                was = self.state["units"]
            else:
                return
        if was == now:
            return
        # scan values are differences, so only the scale changes: work out
        # the factor through °C (counts need the file's calibration)
        slope = getattr(self.src, "count_slope", None)
        to_c = {"°C": 1.0, "°F": 1 / 1.8, "counts": slope}
        from_c = {"°C": 1.0, "°F": 1.8, "counts": (1 / slope) if slope else None}
        if to_c.get(was) is None or from_c.get(now) is None:
            return
        k = to_c[was] * from_c[now]
        if self.acts:
            self.acts = {rid: (a * k).astype(np.float32) for rid, a in self.acts.items()}
            self._save_activity()
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
        st = read_json(_sidecar(self.path, ".analysis.json"))   # a damaged file is kept as a copy, not overwritten
        if not isinstance(st, dict):
            st = {"events": [], "scanned": False}
        if not isinstance(st.get("rois"), list):   # files from before multiple ROIs
            pts = st.pop("roi", None) or []
            st["rois"] = [{"id": "r1", "name": "ROI 1", "points": pts, "scan": True}]
            if st.get("scanned"):
                st["roi_scans"] = {"r1": st.pop("scanned_ranges", None) or None}
                if st.pop("roi_changed", False):
                    st["rois"][0]["changed"] = True
                for e in st.get("events", []):
                    e.setdefault("roi", "r1")
                st["archive"] = {(k if ":" in k else f"r1:{k}"): v for k, v in st.get("archive", {}).items()}
        st.setdefault("roi_scans", {})
        return st

    def save(self):
        self.state["fps"] = self.src.fps
        self.state["roi"] = self.roi        # kept for older versions of the program
        write_json(_sidecar(self.path, ".analysis.json"), self.state)

    # ---------------------------------------------------------- ROIs
    @property
    def rois(self) -> list:
        return self.state.setdefault("rois", [])

    def roi_by_id(self, rid):
        return next((r for r in self.rois if r["id"] == rid), None)

    def roi_name(self, rid) -> str:
        r = self.roi_by_id(rid)
        return r["name"] if r else "ROI"

    def roi_colour(self, rid) -> str:
        ids = [r["id"] for r in self.rois]
        return ROI_COLOURS[(ids.index(rid) if rid in ids else 0) % len(ROI_COLOURS)]

    @property
    def roi(self):
        """The first drawn ROI's outline (older single-ROI callers)."""
        return next((r["points"] for r in self.rois if len(r.get("points") or []) >= 3), [])

    def roi_shapes(self, hidden=(), only=None):
        """Drawn ROIs for the picture overlay: outline, colour and name."""
        return [{"points": r["points"], "colour": self.roi_colour(r["id"]), "name": r["name"]}
                for r in self.rois if len(r.get("points") or []) >= 3 and r["id"] not in hidden
                and (only is None or r["id"] == only)]

    def add_roi(self, name=None) -> dict:
        nums = [int(r["id"][1:]) for r in self.rois if r["id"][1:].isdigit()]
        k = max(nums, default=0) + 1
        r = {"id": f"r{k}", "name": (name or f"ROI {k}").strip()[:40] or f"ROI {k}", "points": [], "scan": True}
        self.rois.append(r)
        self.save()
        return r

    def update_roi(self, rid, name=None, points=None, scan=None):
        r = self.roi_by_id(rid)
        if r is None:
            raise KeyError(rid)
        if name is not None and str(name).strip():
            r["name"] = str(name).strip()[:40]
        if scan is not None:
            r["scan"] = bool(scan)
        if points is not None:
            new = [[float(x), float(y)] for x, y in points]
            if rid in self.acts and new != r.get("points"):
                r["changed"] = True   # the next part scan of this ROI starts afresh
            r["points"] = new
        self.save()
        return r

    def delete_roi(self, rid):
        """Remove an ROI with its trace and its events (decisions on them are
        kept in the archive in case it's drawn again)."""
        if len(self.rois) <= 1:
            return self.update_roi(rid, points=[])
        self.state["rois"] = [r for r in self.rois if r["id"] != rid]
        self.acts.pop(rid, None)
        self.state.get("roi_scans", {}).pop(rid, None)
        if self.acts:
            self._save_activity()
            self.redetect(self.state.get("level") or self.state.get("suggested_level") or 0)
        else:
            self.state["events"], self.state["scanned"] = [], False
            self.save()

    def set_roi(self, pts, rid=None):
        rid = rid or self.rois[0]["id"]
        self.update_roi(rid, points=pts)

    def copy_rois_from(self, other: "Recording"):
        """Use another recording's ROIs (same names, outlines and scan ticks)."""
        old = {r["id"]: r for r in self.rois}
        out = []
        for r in other.rois:
            mine = old.get(r["id"])
            changed = bool(mine and r["id"] in self.acts and mine.get("points") != r.get("points"))
            out.append({"id": r["id"], "name": r["name"], "points": [list(p) for p in r.get("points") or []],
                        "scan": r.get("scan", True), **({"changed": True} if changed or (mine or {}).get("changed") else {})})
        for rid in list(self.acts):
            if rid not in {r["id"] for r in out}:
                self.acts.pop(rid)
                self.state.get("roi_scans", {}).pop(rid, None)
        self.state["rois"] = out
        self.save()

    @property
    def filters(self) -> dict:
        return clean_filters(SETTINGS["filters"])

    # ---------------------------------------------------------- scanning
    def run_scan(self, progress=None, should_stop=None, ranges=None, fresh=False, roi_ids=None):
        """Scan the whole recording, or only the given [first, last] frame
        ranges (the play limits), for the chosen ROIs (default: every drawn
        ROI ticked for scanning), in one pass. A part scan updates those
        frames of an ROI's earlier scan and keeps the rest; frames never
        scanned hold a flat baseline, so no events are found there.
        fresh=True drops the earlier scans first (Start over)."""
        n = self.src.n_frames
        ids = [r["id"] for r in self.rois if len(r.get("points") or []) >= 3
               and (r["id"] in roi_ids if roi_ids is not None else r.get("scan", True))]
        if not ids:
            return False
        if self.state.get("scan_id") != SCAN_ID:
            self.state.pop("level", None)   # an old level doesn't fit the new scan's values
            self.acts, self.state["roi_scans"] = {}, {}
            fresh = True
        whole = not ranges
        if whole:
            ranges = [[0, n - 1]]
        ranges = _merge_ranges([[max(0, int(a)), min(n - 1, int(b))] for a, b in ranges if int(b) >= int(a)])
        gaps = getattr(self.src, "gap_ranges", None) or []
        if gaps:   # a joined recording: scan each file's frames, not the gaps between them
            parts = self.src.part_ranges
            ranges = [[max(a, pa), min(b, pb)] for a, b in ranges for pa, pb in parts if min(b, pb) >= max(a, pa)]
        if not ranges:
            return False
        shape = (self.src.height, self.src.width)
        masks = [roi_mask(self.roi_by_id(rid)["points"], shape) for rid in ids]
        total = sum(b - a + 1 for a, b in ranges)
        segs, offset = [], 0
        self.live = {"ids": ids, "segs": []}   # what's been scanned so far, for the plot to fill in as it goes
        try:
            for a, b in ranges:
                lv = {"start": a, "k": 0}
                self.live["segs"].append(lv)
                seg = scan_multi(self.src, masks, (lambda d, t, o=offset: progress(o + d, total)) if progress else None,
                                 should_stop, start=a, stop=b, live=lv)
                if seg.shape[1] < b - a + 1:
                    return False  # cancelled
                segs.append((a, b, seg))
                offset += b - a + 1
        finally:
            self.live = None
        scans = self.state.setdefault("roi_scans", {})
        for j, rid in enumerate(ids):
            r = self.roi_by_id(rid)
            restart = whole or fresh or r.get("changed") or rid not in self.acts
            act = np.zeros(n, np.float32) if restart else self.acts[rid].copy()
            done = [] if restart else self.scanned_ranges_of(rid)
            for a, b, seg in segs:
                act[a:b + 1] = seg[j]
            done = _merge_ranges(done + ranges + gaps)
            for ga, gb in gaps:
                act[ga:gb + 1] = 0.0   # the camera wasn't recording: a flat line at zero
            real = _range_mask(done, n)
            if not real.all():   # never-scanned frames: a flat line at the quiet baseline of the scanned part
                data = real & ~self.src.gap_mask if gaps else real
                act[~real] = float(np.percentile(act[data if data.any() else real], 5))
            self.acts[rid] = act
            scans[rid] = done
            r.pop("changed", None)
        self._save_activity()
        self.state["suggested_level"] = self._suggest_scanned()
        self.state["units"] = self.src.units
        self.state["scanned"] = True
        self.state["scan_id"] = SCAN_ID
        self.redetect(self.state.get("level") or self.state["suggested_level"])
        return True

    def scanned_ranges_of(self, rid):
        """Frame ranges really scanned for one ROI ([[0, n-1]] for a whole scan)."""
        if rid not in self.acts:
            return []
        return self.state.get("roi_scans", {}).get(rid) or [[0, self.src.n_frames - 1]]

    def _unscanned(self, done):
        out, at = [], 0
        for a, b in done:
            if a > at:
                out.append([at, a - 1])
            at = b + 1
        if at <= self.src.n_frames - 1:
            out.append([at, self.src.n_frames - 1])
        return out

    @property
    def scanned_ranges(self):
        """Frames scanned for at least one ROI."""
        return _merge_ranges([rg for rid in self.acts for rg in self.scanned_ranges_of(rid)])

    @property
    def unscanned_ranges(self):
        if not self.acts:
            return []
        return self._unscanned(self.scanned_ranges)

    def _cut(self, act):
        """Where analysis of a trace stops: a very large spike at the end is
        left out, and the final frame is never used."""
        s = end_spike(act, self.src.fps, self.src.units)
        return s if s is not None else max(1, len(act) - 1)

    def _ignored(self, act):
        """Frames left out of events and statistics, because they come from the
        camera rather than the survey:
          - every time the picture froze while the camera recalibrated, and the
            few frames after, when the scan filters see it jump (frozen_mask);
          - the end: a very large spike (cameras often write a few very hot
            frames as they stop), and the final frame (_cut);
          - in a joined recording, the same end spike at the end of every file,
            and the gaps between files.
        Each rule only takes what is certainly the camera: a false event is
        better than a missed bat."""
        n = len(act)
        fps, units = self.src.fps, self.src.units
        pre = Pipeline(**mode_cfg("scan")).preroll
        ign = frozen_mask(act, pre)
        ign[self._cut(act):] = True
        if hasattr(self.src, "gap_mask"):
            ign |= self.src.gap_mask[:n]
            for a, b in self.src.part_ranges:
                if a >= n:
                    continue
                b = min(b, n - 1)
                seg = act[a:b + 1]
                s = end_spike(seg, fps, units)
                ign[(a + s) if s is not None else b:b + 1] = True
        return ign

    def shown(self, act):
        """A trace as plotted and reported: frames left out because the camera
        was starting or stopping are drawn at the background level instead of
        as huge spikes (gaps stay at zero)."""
        if act is None or not len(act):
            return act
        ign = self._ignored(act)
        if hasattr(self.src, "gap_mask"):
            ign &= ~self.src.gap_mask[:len(act)]
        if not ign.any():
            return act
        keep = act[~self._ignored(act)]
        out = act.copy()
        out[ign] = float(np.median(keep)) if len(keep) else 0.0
        return out

    def _suggest_scanned(self):
        """Suggested level from every ROI's scanned frames, before its end cut."""
        vals = []
        for rid, act in self.acts.items():
            real = _range_mask(self.scanned_ranges_of(rid), len(act))
            real &= ~self._ignored(act)
            vals.append(act[real])
        allv = np.concatenate(vals) if vals else np.zeros(0, np.float32)
        return self._suggest(allv if len(allv) else (self.activity if self.activity is not None else allv))

    _KEEP = ("status", "cls", "note", "tracks", "suggestion", "notes", "exports")

    def redetect(self, level: float):
        """Events = every rise above the detection level, in each ROI. Work
        already done on an event (decision, tracks) is archived, so it comes
        back if the same event reappears after the line is moved."""
        arch = self.state.setdefault("archive", {})
        for e in self.state.get("events", []):
            if e.get("status") != "todo" or e.get("note") or e.get("tracks"):
                arch[f"{e.get('roi', 'r1')}:{e['f0']}-{e['f1']}"] = {k: e[k] for k in self._KEEP if k in e}
        evs = []
        for r in self.rois:
            act = self.acts.get(r["id"])
            if act is None:
                continue
            ign = self._ignored(act)
            for ev in detect_events(np.where(ign, -np.inf, act).astype(np.float32), self.src.fps, level=level, units=self.src.units,
                                    merge_s=cfg.get("detect", "merge_s"), min_frames=cfg.get("detect", "min_frames")):
                e = asdict(ev)
                e["roi"] = r["id"]
                evs.append(e)
        evs.sort(key=lambda e: (e["f0"], e["roi"]))
        for k, e in enumerate(evs, 1):
            e["n"] = k
            prev = arch.get(f"{e['roi']}:{e['f0']}-{e['f1']}")
            if prev is None:  # same spike, slightly different edges at a new level
                for key, val in arch.items():
                    rid, rng = key.split(":", 1) if ":" in key else ("r1", key)
                    a, b = map(int, rng.split("-"))
                    if rid == e["roi"] and a <= e["peak_frame"] <= b:
                        prev = {k2: v for k2, v in val.items() if k2 in ("status", "cls", "note")}
                        break
            if prev:
                e.update(prev)
        self.state["events"], self.state["level"] = evs, float(level)
        self.save()

    def _suggest(self, act):
        return suggested_level(act, sensitivity=cfg.SENSITIVITY[cfg.get("detect", "sensitivity")], units=self.src.units,
                               count_slope=getattr(self.src, "count_slope", None))

    def apply_detection_settings(self):
        """Sensitivity, merge gap or minimum length changed on the Settings
        tab: recompute the suggested level and the events. A level the user set
        themselves is kept; one that was just the old suggestion follows the
        new suggestion."""
        if not self.acts:
            return
        old_sugg, level = self.state.get("suggested_level"), self.state.get("level")
        self.state["suggested_level"] = self._suggest_scanned()
        if level is None or (old_sugg is not None and abs(level - old_sugg) < 1e-6):
            level = self.state["suggested_level"]
        self.redetect(level)

    @property
    def end_spike_frame(self):
        """Start of a very large spike at the end of the combined trace, if any."""
        act = self.activity
        if act is None:
            return None
        return end_spike(act, self.src.fps, self.src.units)

    @staticmethod
    def _pool(act, a, b, points):
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

    def live_range(self, a: int, b: int, points: int):
        """While this recording is being scanned: the activity so far (all ROIs
        combined), as plot points; None when no scan is running."""
        lv = getattr(self, "live", None)
        if not lv:
            return None
        out = []
        for s in list(lv["segs"]):
            arr, k = s.get("out"), int(s.get("k", 0))
            if arr is None or k <= 0:
                continue
            comb = arr[:, :k].max(axis=0)
            lo, hi = max(a, s["start"]), min(b, s["start"] + k - 1)
            if hi < lo:
                continue
            seg = np.zeros(self.src.n_frames, np.float32)   # pooled over just the scanned part
            seg[lo:hi + 1] = comb[lo - s["start"]:hi - s["start"] + 1]
            share = max(10, int(points * (hi - lo + 1) / max(1, b - a + 1)))
            out += self._pool(seg, lo, hi, share)
        done = sum(int(s.get("k", 0)) for s in lv["segs"])
        return {"values": sorted(out), "done": done}

    def activity_range(self, a: int, b: int, points: int):
        """Max-pooled combined activity between frames a and b, for the zoomable plot."""
        act = self.shown(self.activity)
        if act is None:
            return []
        a, b = max(0, int(a)), min(len(act) - 1, int(b))
        return self._pool(act, a, b, points)

    def activity_series(self, a: int, b: int, points: int) -> dict:
        """The same, for each scanned ROI."""
        n = self.src.n_frames
        a, b = max(0, int(a)), min(n - 1, int(b))
        return {r["id"]: self._pool(self.shown(self.acts[r["id"]]), a, b, points) for r in self.rois if r["id"] in self.acts}

    def event_roi_points(self, ev):
        r = self.roi_by_id(ev.get("roi"))
        return (r or {}).get("points") or self.roi

    def track_event(self, n: int):
        ev = self.event(n)
        pad = self.window
        tr = track_window(self.src, max(0, ev["f0"] - pad),
                          min(self.src.n_frames - 1, ev["f1"] + pad), self.event_roi_points(ev), filters=self.filters)
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

    def export(self, n, opts, progress=None):
        ev = self.event(n)
        if not ev.get("tracks") and "entry_frames" in opts.get("items", []):
            ev = self.track_event(n)
        if not opts.get("folder"):
            from .org import project_subfolder
        folder = opts.get("folder") or project_subfolder(self.path, "Exports")
        stem = os.path.splitext(os.path.basename(self.path))[0]
        site = os.path.basename(os.path.dirname(self.path))
        opts = {"naming": cfg.get("export", "naming"), "slowmo": cfg.get("export", "slowmo"),
                **opts, "filters": self.filters, "site": site, "recording": stem}
        files = export_event(self.src, ev, self.event_roi_points(ev) if opts.get("overlays", "roi+time") == "roi+time" else None,
                             folder, f"{site}_{stem}", opts, progress)
        ev.setdefault("exports", [])
        ev["exports"] = sorted(set(ev["exports"]) | set(files))
        self.save()
        return files

    def noise(self) -> list:
        """Background noise between spikes, for each scanned ROI (cached)."""
        from .analysis import noise_stats
        level = self.state.get("level")
        evs = self.state.get("events", [])
        key = (level, len(evs), tuple((rid, len(a), float(a[:64].sum()) if len(a) else 0.0) for rid, a in self.acts.items()),
               json.dumps(self.state.get("roi_scans", {}), sort_keys=True))
        if getattr(self, "_noise_key", None) == key:
            return self._noise_val
        out = []
        pad = int(self.src.fps)
        for r in self.rois:
            act = self.acts.get(r["id"])
            if act is None or not len(act):
                continue
            quiet = _range_mask(self.scanned_ranges_of(r["id"]), len(act))
            quiet &= ~self._ignored(act)
            for e in evs:
                if e.get("roi", "r1") == r["id"]:
                    quiet[max(0, e["f0"] - pad):e["f1"] + pad + 1] = False
            if level is not None:
                quiet &= act <= level
            st = noise_stats(act, quiet, self.src.fps, level, self.src.units)
            if st:
                out.append({"roi": r["id"], "name": r["name"], **st})
        self._noise_key, self._noise_val = key, out
        return out

    def summary(self) -> dict:
        rois = [{"id": r["id"], "name": r["name"], "points": r.get("points") or [], "scan": r.get("scan", True),
                 "colour": self.roi_colour(r["id"]), "scanned": r["id"] in self.acts,
                 "unscanned": self._unscanned(self.scanned_ranges_of(r["id"])) if r["id"] in self.acts else []}
                for r in self.rois]
        return {**self.src.info(), "status": self.status(), "roi": self.roi, "rois": rois,
                "events": self.state.get("events", []), "scanned": bool(self.state.get("scanned")),
                "level": self.state.get("level"), "suggested_level": self.state.get("suggested_level"),
                "filters": self.filters,
                "scan_outdated": bool(self.state.get("scanned")) and self.state.get("scan_id") != SCAN_ID,
                "end_spike": self.end_spike_frame,
                "unscanned": self.unscanned_ranges,
                "noise": self.noise(),
                "comments": sorted(self.state.get("comments", []), key=lambda c: c["frame"]),
                "exports_folder": self._exports_folder()}

    def _exports_folder(self):
        try:
            from .org import project_subfolder
            return project_subfolder(self.path, "Exports")
        except Exception:
            return os.path.join(os.path.dirname(self.path), "exports")


class Jobs:
    """One worker thread; long jobs (scans, exports) report progress here."""

    def __init__(self):
        self.q = queue.Queue()
        self.current = None
        self.history = []
        self._cancel = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, label, fn, path=None, kind=None):
        job = {"id": f"{time.time():.6f}", "label": label, "done": 0, "total": 1,
               "state": "queued", "result": None, "error": None, "path": path, "kind": kind}
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
            job["state"], job["started"] = "running", time.time()

            def progress(d, t):
                job["done"], job["total"] = d, t

            try:
                job["result"] = fn(progress, self._cancel.is_set)
                job["state"] = "cancelled" if self._cancel.is_set() else "done"
            except Exception as e:  # report, keep the worker alive
                job["state"], job["error"] = "error", f"{e}"
                traceback.print_exc()
            job["finished"] = time.time()
            self.current = None

    def snapshot(self):
        out = []
        now = time.time()
        for j in self.history:
            d = dict(j, result=None if isinstance(j["result"], (bytes,)) else j["result"])
            if j["state"] == "running" and j.get("started") and j["done"] > 0:   # time left, from the pace so far
                el = now - j["started"]
                d["eta_s"] = round(el * (j["total"] - j["done"]) / j["done"]) if el > 3 else None
            out.append(d)
        return out
