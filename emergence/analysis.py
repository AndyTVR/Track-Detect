"""Filters, activity scan, event detection and bat tracking.

The filters reproduce the FLIR Research Studio ones used in the TVE manual:
  Window Average (3x3), Max - Frame Interval (depth N),
  Sliding Subtraction (delay N, relative) and Max - Continuous,
applied in that order (Window Average -> Max Interval -> Sliding Subtraction).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np

# ---------------------------------------------------------------- modes
MODES = {
    # name: (window_average, max_interval_depth, sliding_sub_delay, max_continuous, scale)
    # detection scan: Window Average 3x3 + Sliding Subtraction 5 (fixed)
    "scan":   dict(wa=True,  mfi=0, ss=5, mc=False, scale="image"),
    "review": dict(wa=False, mfi=5, ss=5, mc=False, scale="image"),
    "path":   dict(wa=False, mfi=0, ss=0, mc=True,  scale="raw"),
    "raw":    dict(wa=False, mfi=0, ss=0, mc=False, scale="raw"),
}


DEFAULT_FILTERS = {"mfi": 5, "ss": 5}
SCAN_ID = "wa3+ss5"   # changes whenever the scan filters change, so old scans can be flagged


def clean_filters(f=None) -> dict:
    """Frame persistence for Max Frame Interval and Sliding Subtraction (1-60)."""
    f = {**DEFAULT_FILTERS, **(f or {})}
    return {k: int(min(60, max(1, round(float(f[k]))))) for k in DEFAULT_FILTERS}


def mode_cfg(mode: str, filters=None) -> dict:
    """A view's filter settings, with the user's persistence values applied to
    the High Sensitivity view and to the detection scan."""
    cfg = dict(MODES[mode])
    if mode == "review":
        cfg.update(clean_filters(filters))
    return cfg


class Pipeline:
    """Stateful filter chain fed one frame at a time, in order."""

    def __init__(self, wa=False, mfi=0, ss=0, mc=False, **_):
        self.wa, self.mfi, self.ss, self.mc = wa, int(mfi), int(ss), mc
        self.reset()

    @property
    def preroll(self) -> int:
        """Frames needed before the output is fully formed."""
        return max(0, self.mfi - 1) + self.ss

    def reset(self):
        self._mfi_buf = deque(maxlen=max(self.mfi, 1))
        self._ss_buf = deque(maxlen=self.ss + 1)
        self._mc = None

    def step(self, frame: np.ndarray) -> np.ndarray:
        x = frame
        if self.wa:
            x = cv2.blur(x, (3, 3))
        if self.mfi > 1:
            self._mfi_buf.append(x)
            x = np.maximum.reduce(list(self._mfi_buf)) if len(self._mfi_buf) > 1 else x
        if self.ss > 0:
            self._ss_buf.append(x)
            x = x - self._ss_buf[0] if len(self._ss_buf) > self.ss else np.zeros_like(x)
        if self.mc:
            self._mc = x.copy() if self._mc is None else np.maximum(self._mc, x)
            x = self._mc
        return x


# ---------------------------------------------------------------- ROI
def roi_mask(points, shape) -> np.ndarray | None:
    if not points or len(points) < 3:
        return None
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [np.asarray(points, np.int32)], 1)
    return m.astype(bool)


def roi_bbox(mask: np.ndarray | None, shape):
    if mask is None:
        return 0, 0, shape[1], shape[0]
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


# ---------------------------------------------------------------- scan
def scan(src, mask, progress=None, should_stop=None, mode="scan", filters=None) -> np.ndarray:
    """Max value inside the ROI for every frame, through the Scan filters.

    This is the Temporal Plot (All ROIs without image, Maximum) from the
    manual, computed in one pass."""
    n = src.n_frames
    x0, y0, x1, y1 = roi_bbox(mask, (src.height, src.width))
    sub = mask[y0:y1, x0:x1] if mask is not None else None
    pipe = Pipeline(**mode_cfg(mode, filters))
    out = np.zeros(n, np.float32)
    for i in range(n):
        if should_stop and should_stop():
            return out[:i]
        try:
            f = src.frame(i, crop=(x0, y0, x1, y1))
        except TypeError:  # sources without crop support
            f = src.frame(i)[y0:y1, x0:x1]
        y = pipe.step(f)
        out[i] = float(y[sub].max()) if sub is not None else float(y.max())
        if progress and (i % 200 == 0 or i == n - 1):
            progress(i + 1, n)
    out[: pipe.preroll] = np.median(out[pipe.preroll : pipe.preroll + 50]) if n > pipe.preroll + 1 else 0
    return out


def _rolling_stat(a: np.ndarray, block: int, fn):
    """Cheap rolling statistic: fn over blocks, linearly interpolated."""
    n = len(a)
    if n == 0:
        return a
    centres, vals = [], []
    for s in range(0, n, block):
        seg = a[s : s + block]
        centres.append(s + len(seg) / 2)
        vals.append(fn(seg))
    return np.interp(np.arange(n), centres, vals).astype(np.float32)


@dataclass
class Event:
    n: int
    f0: int
    f1: int
    peak: float
    peak_frame: int
    status: str = "todo"          # todo | confirmed | rejected
    cls: str = ""                 # analyst's classification (or suggestion)
    suggestion: str = ""
    tracks: list = field(default_factory=list)
    note: str = ""


TEMP_UNITS = ("°C", "°F")


def temp_scale(units: str) -> float:
    """Size of one °C in the recording's units (1.8 for °F), for the fixed
    minimum differences below."""
    return 1.8 if units == "°F" else 1.0


def suggested_level(activity: np.ndarray, sensitivity: float = 6.0, units: str = "°C") -> float:
    """A starting detection level: the noise floor plus a safety margin.
    The analyst can then drag it up or down on the plot."""
    if len(activity) == 0:
        return 0.0
    base = float(np.median(activity))
    mad = float(np.median(np.abs(activity - base))) * 1.4826
    if units in TEMP_UNITS:
        floor = 0.6 * temp_scale(units)
    else:
        lo, hi = np.percentile(activity, [5, 99.9])
        floor = max(1.0, 0.02 * (hi - lo))
    return round(base + max(sensitivity * mad, floor), 3)


def end_spike(activity: np.ndarray, fps: float, units: str = "°C") -> int | None:
    """A very large spike right at the end of a recording (someone walking up to
    the camera, the camera being moved or switched off) is not survey activity.
    Returns the frame where that final spike starts, or None if there isn't one.

    It must be the last rise above the noise, run to within 2 s of the end, and
    be at least 3x taller than any other spike in the recording."""
    n = len(activity)
    if n < fps * 10:
        return None
    base = float(np.median(activity))
    mad = float(np.median(np.abs(activity - base))) * 1.4826
    floor = 0.6 * temp_scale(units) if units in TEMP_UNITS else max(1.0, 0.02 * float(np.percentile(activity, 99.9) - np.percentile(activity, 5)))
    thr = base + max(6 * mad, floor)
    hot = activity > thr
    if not hot[-int(2 * fps):].any():
        return None                       # nothing high near the very end
    b = n - 1 - int(np.argmax(hot[::-1]))  # last hot frame
    if n - 1 - b > 2 * fps:
        return None
    gap = int(2 * fps)                    # walk back to where the final spike started
    a = b
    while a > 0 and hot[max(0, a - gap):a].any():
        a = max(0, a - gap) + int(np.flatnonzero(hot[max(0, a - gap):a])[0])
    tail_h = float(activity[a:].max()) - base
    rest = activity[: max(0, a - int(fps))]
    other_h = float(rest.max()) - base if len(rest) else 0.0
    if tail_h < 3 * max(other_h, thr - base) or a < n * 0.5:
        return None
    return max(0, a - int(fps))           # a second of margin before it


def detect_events(activity: np.ndarray, fps: float, level: float | None = None,
                  merge_s: float = 2.0, units: str = "°C", sensitivity: float = 6.0,
                  min_frames: int = 1) -> list[Event]:
    """Every stretch where the activity rises above the detection level.

    level: the horizontal line on the plot, in the recording's units. If not
    given, the suggested level is used. Spikes below it are ignored."""
    if len(activity) == 0:
        return []
    if level is None:
        level = suggested_level(activity, sensitivity, units)
    hot = np.flatnonzero(activity > level)
    events: list[Event] = []
    if hot.size == 0:
        return events
    gap = int(merge_s * fps)
    start = prev = int(hot[0])
    for i in hot[1:]:
        i = int(i)
        if i - prev > gap:
            events.append((start, prev))
            start = i
        prev = i
    events.append((start, prev))
    out = []
    for a, b in events:
        if b - a + 1 < max(1, int(min_frames)):
            continue   # too short: usually an insect or a flicker
        seg = activity[a : b + 1]
        p = int(np.argmax(seg))
        out.append(Event(n=len(out) + 1, f0=a, f1=b, peak=float(seg[p]), peak_frame=a + p))
    return out


# ---------------------------------------------------------------- tracking
def _blobs(img: np.ndarray, units: str):
    med = float(np.median(img))
    mad = float(np.median(np.abs(img - med))) * 1.4826 + 1e-6
    thr = med + 10 * mad
    if units in TEMP_UNITS:
        thr = max(thr, med + 0.8 * temp_scale(units))
    m = (img > thr).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, _, st, c = cv2.connectedComponentsWithStats(m)
    out = []
    for k in range(1, n):
        area = int(st[k, cv2.CC_STAT_AREA])
        if 3 <= area <= img.size * 0.01:
            out.append((float(c[k][0]), float(c[k][1]), area))
    return out


def track_window(src, f0: int, f1: int, roi_points=None, link_px=None, filters=None):
    """Follow warm moving objects through frames f0..f1 (Review filters)."""
    W, H = src.width, src.height
    link_px = link_px or max(12.0, W / 25)
    # Sliding subtraction alone: one warm blob per bat per frame (Max Interval
    # would leave several copies of the bat in each frame).
    pipe = Pipeline(wa=False, mfi=0, ss=clean_filters(filters)["ss"])
    start = max(0, f0 - pipe.preroll)
    dets = []
    for i in range(start, f1 + 1):
        y = pipe.step(src.frame(i))
        if i < f0:
            continue
        for x, yy, a in _blobs(y, src.units):
            dets.append((i, x, yy, a))
    tracks: list[list] = []
    for fr, x, y, a in sorted(dets):
        best, bd = None, None
        for t in tracks:
            lf, lx, ly, _ = t[-1]
            if 0 < fr - lf <= 3:
                d = (x - lx) ** 2 + (y - ly) ** 2
                if d < link_px ** 2 and (bd is None or d < bd):
                    best, bd = t, d
        (best.append((fr, x, y, a)) if best is not None else tracks.append([(fr, x, y, a)]))
    poly = np.asarray(roi_points, np.float32) if roi_points and len(roi_points) >= 3 else None
    min_move = max(10.0, W / 40)
    res = []
    for t in tracks:
        if len(t) < 4:
            continue
        (fa, xa, ya, _), (fb, xb, yb, _) = t[0], t[-1]
        if np.hypot(xb - xa, yb - ya) < min_move:
            continue  # flicker that does not travel (foliage, noise)
        res.append(_describe_track(t, W, H, poly))
    res = _dedupe(res, link_px)
    res.sort(key=lambda r: r["first_frame"])
    for k, r in enumerate(res, 1):
        r["id"] = chr(64 + k) if k <= 26 else str(k)
    return res


def _dedupe(tracks, link_px):
    """Drop tracks that shadow a longer one (same place, same frames)."""
    tracks = sorted(tracks, key=lambda t: -len(t["points"]))
    keep = []
    for t in tracks:
        pts = {p[0]: p for p in t["points"]}
        dup = False
        for k in keep:
            kp = {p[0]: p for p in k["points"]}
            common = [f for f in pts if f in kp]
            if len(common) >= 0.6 * len(pts):
                close = sum(1 for f in common
                            if np.hypot(pts[f][1] - kp[f][1], pts[f][2] - kp[f][2]) < link_px)
                if close >= 0.8 * len(common):
                    dup = True
                    break
        if not dup:
            keep.append(t)
    return keep


def _edge(x, y, W, H, m=0.04):
    sides = []
    if x < W * m: sides.append("left")
    if x > W * (1 - m): sides.append("right")
    if y < H * m: sides.append("top")
    if y > H * (1 - m): sides.append("bottom")
    return sides[0] if sides else None


def _in_poly(poly, x, y):
    return poly is not None and cv2.pointPolygonTest(poly, (float(x), float(y)), False) >= 0


def _describe_track(t, W, H, poly):
    (fa, xa, ya, _), (fb, xb, yb, _) = t[0], t[-1]
    e0, e1 = _edge(xa, ya, W, H), _edge(xb, yb, W, H)
    return {
        "first_frame": fa, "last_frame": fb,
        "first_xy": [round(xa, 1), round(ya, 1)], "last_xy": [round(xb, 1), round(yb, 1)],
        "start_edge": e0, "end_edge": e1,
        "start_in_roi": _in_poly(poly, xa, ya), "end_in_roi": _in_poly(poly, xb, yb),
        "points": [[int(f), round(x, 1), round(y, 1)] for f, x, y, _ in t],
    }


def suggest(tracks: list, fps: float) -> tuple[str, list[str]]:
    """A plain-language suggestion for the analyst. Never a final call."""
    if not tracks:
        return "No moving bat found – likely noise", []
    notes = []
    gap = 4 * fps
    paired_start, paired_end = set(), set()
    for a in tracks:
        for b in tracks:
            if a is b:
                continue
            dt = b["first_frame"] - a["last_frame"]
            if 0 < dt <= gap and not a["end_edge"] and not b["start_edge"]:
                paired_end.add(a["id"]); paired_start.add(b["id"])
                notes.append(f"{a['id']}→{b['id']}: lost at frame {a['last_frame']}, reappears "
                             f"{dt / fps:.1f} s later – probably the same bat passing behind the structure")
    emerg, reentry = [], []
    for t in tracks:
        where0 = f"entered view at {t['start_edge']} edge" if t["start_edge"] else (
            "first seen inside ROI" if t["start_in_roi"] else "first seen in open view")
        where1 = f"left view at {t['end_edge']} edge" if t["end_edge"] else (
            "last seen inside ROI" if t["end_in_roi"] else "lost in open view")
        notes.append(f"Bat {t['id']}: frames {t['first_frame']}–{t['last_frame']}, {where0}, {where1}")
        if t["start_in_roi"] and not t["start_edge"] and t["id"] not in paired_start:
            emerg.append(t["id"])
        if t["end_in_roi"] and not t["end_edge"] and t["id"] not in paired_end:
            reentry.append(t["id"])
    if emerg:
        head = "Possible emergence – check bat " + ", ".join(emerg)
    elif reentry:
        head = "Possible re-entry – check bat " + ", ".join(reentry)
    elif paired_start:
        head = "Flight past roost features – passes behind structure"
    else:
        head = "Flight through view (commuting/foraging)"
    return head, notes
