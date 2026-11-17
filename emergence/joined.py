"""Several consecutive recordings from one camera, read as one.

A JoinedSource looks like an ATSFile to the rest of the program: frames are
numbered straight through, and frame times come from each file's own clock.
Where the camera wasn't recording between two files, gap frames are added at
the first file's frame rate, so the time line stays true. A gap frame shows
the first picture of the file after it (so the scan filters see no change
there) and its activity is held at zero.
"""
from __future__ import annotations

import bisect
import os

import numpy as np

from .ats import ATSFile, ATSError

MAX_GAP_S = 6 * 3600   # longer gaps than this aren't filled (not one night's recording)


class JoinedSource:
    def __init__(self, path: str, members: list[str]):
        if len(members) < 2:
            raise ATSError("Joining needs at least two recordings")
        parts = [ATSFile(p) for p in members]
        w, h = parts[0].width, parts[0].height
        if any((p.width, p.height) != (w, h) for p in parts):
            for p in parts:
                p.close()
            raise ATSError("These recordings have different picture sizes, so they can't be joined")
        parts.sort(key=lambda p: (p.start_time is None, p.start_time or 0, os.path.basename(p.path).lower()))
        self.parts = parts
        self.path = path
        first = parts[0]
        self.width, self.height, self.camera = w, h, first.camera
        self.units, self.count_slope = first.units, first.count_slope
        self.temp_approx = bool(getattr(first, "temp_approx", False))
        self.fps, self.fps_source, self.fps_user = first.fps, first.fps_source, False
        self.start_time = first.start_time
        self.xml = first.xml
        # lay the files out on one frame line: [gap][part][gap][part]...
        self.blocks = []          # (first frame, kind "part"/"gap", part index, frames, seconds at first frame)
        at, t = 0, 0.0
        for k, p in enumerate(parts):
            if k:
                prev = parts[k - 1]
                end = t_prev + prev.seconds_at(prev.n_frames - 1) + 1 / prev.fps
                if p.start_time is not None and self.start_time is not None:
                    begin = (p.start_time - self.start_time).total_seconds()
                else:
                    begin = end
                gap_s = begin - end
                t = max(end, begin)
                n_gap = int(round(gap_s * self.fps)) if 0 < gap_s <= MAX_GAP_S else 0
                if n_gap > 0:
                    self.blocks.append((at, "gap", k, n_gap, end))
                    at += n_gap
            self.blocks.append((at, "part", k, p.n_frames, t))
            t_prev = t
            at += p.n_frames
            t = t_prev + p.seconds_at(p.n_frames - 1) + 1 / p.fps
        self.n_frames = at
        self._starts = [b[0] for b in self.blocks]
        self._times = None

    # ------------------------------------------------------------ frames
    def _block(self, i: int):
        i = int(max(0, min(self.n_frames - 1, i)))
        b = self.blocks[bisect.bisect_right(self._starts, i) - 1]
        return b, i - b[0]

    @property
    def gap_mask(self) -> np.ndarray:
        m = np.zeros(self.n_frames, bool)
        for s, kind, _, n, _ in self.blocks:
            if kind == "gap":
                m[s:s + n] = True
        return m

    @property
    def gap_ranges(self) -> list:
        return [[s, s + n - 1] for s, kind, _, n, _ in self.blocks if kind == "gap"]

    @property
    def part_ranges(self) -> list:
        return [[s, s + n - 1] for s, kind, _, n, _ in self.blocks if kind == "part"]

    def raw(self, i: int) -> np.ndarray:
        (s, kind, k, n, _), j = self._block(i)
        return self.parts[k].raw(0 if kind == "gap" else j)

    def frame(self, i: int, crop=None) -> np.ndarray:
        (s, kind, k, n, _), j = self._block(i)
        return self.parts[k].frame(0 if kind == "gap" else j, crop)

    # ------------------------------------------------------------ time
    def frame_times(self):
        if self._times is not None:
            return self._times
        out = np.zeros(self.n_frames, np.float64)
        for s, kind, k, n, t0 in self.blocks:
            if kind == "gap":
                out[s:s + n] = t0 + np.arange(n) / self.fps
            else:
                p = self.parts[k]
                pt = p.frame_times()
                out[s:s + n] = t0 + (pt if pt is not None else np.arange(n) / p.fps)
        self._times = out
        return out

    def seconds_at(self, i: int) -> float:
        return float(self.frame_times()[int(max(0, min(self.n_frames - 1, i)))])

    # the same clock-time labels as a single file
    span_s = ATSFile.span_s
    time_utc = ATSFile.time_utc
    time_of = ATSFile.time_of
    zone_of = ATSFile.zone_of
    date_label = ATSFile.date_label

    def time_label(self, i: int) -> str:
        return ATSFile.time_label(self, i)

    def info(self) -> dict:
        d = ATSFile.info(self)
        names = [os.path.basename(p.path) for p in self.parts]
        d["name"] = " + ".join(os.path.splitext(n)[0] for n in names) + " (joined)"
        d["joined"] = [{"name": os.path.basename(self.parts[k].path), "path": self.parts[k].path, "from": s, "to": s + n - 1}
                       for s, kind, k, n, _ in self.blocks if kind == "part"]
        d["gaps"] = self.gap_ranges
        return d

    def close(self):
        for p in self.parts:
            try:
                p.close()
            except Exception:
                pass
