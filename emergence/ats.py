"""Reader for FLIR ATS-US (.ats) radiometric recordings.

The file is read through a memory map, so a 30 GB recording opens instantly
and only the frames you look at are read from disk.

Layout (worked out from real files, no FLIR SDK needed):
  * 16-byte magic  "FLIR ATS-US File"
  * XML <workspaceFileSettings> block (image size, units, calibration ranges)
  * binary SourceInfo record (camera model, recording start as a FILETIME)
  * frames: W*H little-endian uint16 pixels, each followed by a small
    per-frame header block. The start offset and stride are not stored in
    a documented place, so they are detected from the pixel data itself and
    cached in a small sidecar file next to the recording.
"""
from __future__ import annotations

import datetime as _dt
import json
import mmap
import os
import re
import struct
from dataclasses import dataclass, asdict

import numpy as np

MAGIC = b"FLIR ATS-US File"
LAYOUT_VERSION = 2


@dataclass
class Layout:
    width: int
    height: int
    first: int          # byte offset of frame 0's first pixel
    stride: int         # bytes from one frame to the next
    n_frames: int
    version: int = LAYOUT_VERSION


class ATSError(Exception):
    pass


def _filetime_to_datetime(v: int) -> _dt.datetime:
    return _dt.datetime(1601, 1, 1, tzinfo=_dt.timezone.utc) + _dt.timedelta(microseconds=v / 10)


def _last_sunday(year: int, month: int) -> _dt.date:
    d = _dt.date(year, month + 1, 1) - _dt.timedelta(days=1) if month < 12 else _dt.date(year, 12, 31)
    return d - _dt.timedelta(days=(d.weekday() + 1) % 7)


# Set from the Settings tab: time zone shown ("uk" or "utc"), camera clock
# correction in seconds, and temperature unit ("C" or "F").
TIME = {"zone": "uk", "offset_s": 0.0}
TEMP = {"unit": "C"}


def uk_time(t_utc: _dt.datetime):
    """UTC -> UK clock time. BST (UTC+1) runs from 01:00 UTC on the last Sunday
    in March to 01:00 UTC on the last Sunday in October; GMT otherwise."""
    if t_utc.tzinfo is None:
        t_utc = t_utc.replace(tzinfo=_dt.timezone.utc)
    y = t_utc.year
    start = _dt.datetime.combine(_last_sunday(y, 3), _dt.time(1), _dt.timezone.utc)
    end = _dt.datetime.combine(_last_sunday(y, 10), _dt.time(1), _dt.timezone.utc)
    if start <= t_utc < end:
        return t_utc.astimezone(_dt.timezone(_dt.timedelta(hours=1), "BST")), "BST"
    return t_utc.astimezone(_dt.timezone(_dt.timedelta(0), "GMT")), "GMT"


class ATSFile:
    """Random access to the frames of an .ats recording."""

    def __init__(self, path: str, fps: float | None = None):
        self.path = path
        self.size = os.path.getsize(path)
        self._fh = open(path, "rb")
        try:
            self._mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
        except ValueError as e:  # empty file
            raise ATSError(f"Cannot map {path}: {e}")
        if self._mm[:16] != MAGIC:
            raise ATSError("Not a FLIR ATS-US file (magic bytes missing)")
        head = self._mm[: min(self.size, 400_000)]
        self._head = head
        self.xml = self._parse_xml(head)
        self.camera = self._parse_camera(head)
        w, h = self._parse_size(head)
        self.layout = self._load_or_detect_layout(w, h)
        self.width, self.height = self.layout.width, self.layout.height
        self.n_frames = self.layout.n_frames
        self.start_time = self._parse_start_time(head)
        self.fps = float(fps) if fps else 16.0
        if self.n_frames < 1:
            raise ATSError("The file contains no complete frames")
        self._frames = np.ndarray(
            shape=(self.n_frames, self.height, self.width),
            dtype="<u2",
            buffer=self._mm,
            offset=self.layout.first,
            strides=(self.layout.stride, self.width * 2, 2),
        )
        # needs the frames, so it comes after them
        self.units, self._to_celsius = self._calibration()

    # ------------------------------------------------------------------ header
    @staticmethod
    def _parse_xml(head: bytes) -> dict:
        out: dict = {}
        m = re.search(rb"<workspaceFileSettings>(.*?)</workspaceFileSettings>", head, re.S)
        if not m:
            return out
        txt = m.group(1).decode("latin-1", "replace")
        for unit, lo, hi in re.findall(r'<segmentationValue unit="([^"]+)" min="([^"]+)" max="([^"]+)"', txt):
            out.setdefault("ranges", {})[unit] = (float(lo), float(hi))
        s = re.search(r'<source unit="([^"]+)"', txt)
        if s:
            out["source_unit"] = s.group(1)
        return out

    @staticmethod
    def _parse_camera(head: bytes) -> str:
        i = head.find(b"SourceInfo")
        if i < 0:
            return "Unknown"
        m = re.search(rb"(FLIR [A-Za-z0-9 ]{2,20}|RS\d{3,5}|A\d{2,4}sc?)\x00", head[i : i + 600])
        return m.group(1).decode("ascii", "replace") if m else "Unknown"

    @staticmethod
    def _parse_size(head: bytes) -> tuple[int, int]:
        w = re.search(rb'imageWidth="(\d+)', head)
        h = re.search(rb'imageHeight="(\d+)', head)
        if w and h:
            return int(w.group(1)), int(h.group(1))
        i = head.find(b"SourceInfo")
        if i >= 0:
            # width/height pairs appear as little-endian uint16 in the record
            for j in range(i, min(i + 800, len(head) - 4)):
                ww, hh = struct.unpack("<HH", head[j : j + 4])
                if (ww, hh) in {(640, 480), (1280, 1024), (320, 240), (640, 512), (1024, 768)}:
                    return ww, hh
        raise ATSError("Could not find the image size in the file header")

    def _parse_start_time(self, head: bytes):
        stop = min(self.layout.first, len(head) - 8)
        for i in range(0, stop):
            v = struct.unpack_from("<Q", head, i)[0]
            if 0x01D0000000000000 < v < 0x01E0000000000000:
                try:
                    return _filetime_to_datetime(v)
                except (OverflowError, ValueError):
                    continue
        return None

    def _calibration(self):
        """Return (unit label, function counts->°C or None)."""
        ranges = self.xml.get("ranges", {})
        src = self.xml.get("source_unit", "")
        if "Counts" in ranges and "TemperatureC" in ranges:
            (k0, k1), (c0, c1) = ranges["Counts"], ranges["TemperatureC"]
            if k1 != k0:
                slope = (c1 - c0) / (k1 - k0)
                return self._temp_unit(lambda a: (a.astype(np.float32) - k0) * slope + c0)
        if "Temperature" in src:
            # Radiometric cameras store temperature directly: 0.01 K per count.
            sample = self.raw(min(self.n_frames - 1, 2))[::16, ::16]
            med = float(np.median(sample))
            if 20000 < med < 40000:
                return self._temp_unit(lambda a: a.astype(np.float32) / 100.0 - 273.15)
        return "counts", None

    @staticmethod
    def _temp_unit(to_c):
        """°C, or °F when chosen on the Settings tab."""
        if TEMP["unit"] == "F":
            return "°F", lambda a: to_c(a) * 1.8 + 32.0
        return "°C", to_c

    # ------------------------------------------------------------------ layout
    def _sidecar(self) -> str:
        return self.path + ".layout.json"

    def _load_or_detect_layout(self, w: int, h: int) -> Layout:
        try:
            with open(self._sidecar()) as f:
                d = json.load(f)
            if d.get("version") == LAYOUT_VERSION and d.get("size") == self.size:
                d.pop("size")
                return Layout(**d)
        except (OSError, ValueError, TypeError):
            pass
        lay = detect_layout(self._mm, self.size, w, h)
        try:
            with open(self._sidecar(), "w") as f:
                json.dump({**asdict(lay), "size": self.size}, f)
        except OSError:
            pass  # read-only folder: just detect again next time
        return lay

    # ------------------------------------------------------------------ frames
    def raw(self, i: int) -> np.ndarray:
        return self._frames[int(i)]

    def frame(self, i: int, crop=None) -> np.ndarray:
        """Frame i as float32 (°C when calibration is known, else counts).
        crop = (x0, y0, x1, y1) converts only that part."""
        a = self.raw(i)
        if crop is not None:
            x0, y0, x1, y1 = crop
            a = a[y0:y1, x0:x1]
        return self._to_celsius(a) if self._to_celsius else a.astype(np.float32)

    def time_utc(self, i: int):
        if self.start_time is None:
            return None
        return self.start_time + _dt.timedelta(seconds=i / self.fps + TIME["offset_s"])

    def time_of(self, i: int):
        """Clock time of frame i: UK time (BST in summer, GMT in winter), or
        UTC if chosen on the Settings tab."""
        t = self.time_utc(i)
        if t is None:
            return None
        return t.replace(tzinfo=_dt.timezone.utc) if TIME["zone"] == "utc" else uk_time(t)[0]

    def zone_of(self, i: int) -> str:
        t = self.time_utc(i)
        if t is None:
            return ""
        return "UTC" if TIME["zone"] == "utc" else uk_time(t)[1]

    def date_label(self, i: int) -> str:
        """UK date of frame i as dd/mm/yyyy ('' if the file has no start time)."""
        t = self.time_of(i)
        return "" if t is None else t.strftime("%d/%m/%Y")

    def time_label(self, i: int) -> str:
        t = self.time_of(i)
        if t is None:
            s = i / self.fps
            return f"+{int(s // 60):02d}:{s % 60:06.3f}"
        return t.strftime("%H:%M:%S.") + f"{t.microsecond // 1000:03d}"

    def info(self) -> dict:
        return {
            "path": self.path,
            "name": os.path.basename(self.path),
            "camera": self.camera,
            "width": self.width,
            "height": self.height,
            "frames": self.n_frames,
            "fps": self.fps,
            "duration_s": self.n_frames / self.fps,
            "start": self.time_utc(0).isoformat() if self.start_time else None,   # includes clock correction
            "zone": self.zone_of(0),
            "units": self.units,
        }

    def close(self):
        self._frames = None
        try:
            self._mm.close()
        finally:
            self._fh.close()


# ---------------------------------------------------------------------- detection
def _u16(buf, off: int, n: int) -> np.ndarray:
    return np.frombuffer(buf[off : off + 2 * n], dtype="<u2").astype(np.int32)


def detect_layout(buf, size: int, w: int, h: int) -> Layout:
    """Find where frame 0 starts and the byte distance between frames."""
    pix = w * h * 2
    si = buf.find(b"SourceInfo")
    if si < 0:
        si = 0
    row = w * 2

    # 1. first offset (either byte parity) where values change smoothly,
    #    i.e. look like neighbouring pixels rather than header fields.
    def rough(o):
        a = _u16(buf, o, 512)
        if a.size < 512 or a.max() == a.min():
            return None
        return np.abs(np.diff(a)).mean()

    def parity_ok(o):
        """0 or 1 if data from o onwards is clearly pixels at that parity."""
        d0, d1 = rough(o), rough(o + 1)
        if d0 is None or d1 is None:
            return None
        if min(d0, d1) < 0.25 * max(d0, d1):
            return 0 if d0 < d1 else 1
        return None

    rough_start = None
    for o in range(si, min(si + 400_000, size - pix), 64):
        p = parity_ok(o)
        # pixel data read at the right byte parity is far smoother than at the
        # wrong one; insist it stays that way for several rows
        if p is not None and all(parity_ok(o + k) == p for k in (2 * row, 4 * row, 8 * row)):
            rough_start = o + p
            break
    if rough_start is None:
        raise ATSError("Could not find image data in the file")

    def frame_at(s, rows=h):
        return _u16(buf, s, rows * w).reshape(rows, w)

    # 2. column phase: read at the wrong phase, every row "wraps" at the same
    #    column, which shows up as the strongest column-to-column jump.
    a = frame_at(rough_start + 4 * row, min(h - 8, 400))
    jump = np.abs(np.diff(a, axis=1)).mean(axis=0)          # jump between col c and c+1
    wrap = np.abs(a[1:, 0] - a[:-1, -1]).mean()             # last col of a row -> first col of next
    c = int(np.argmax(jump)) + 1
    if jump[c - 1] > 2.0 * max(wrap, 1e-6) and jump[c - 1] > 3.0 * np.median(jump):
        s0 = rough_start + c * 2
    else:
        s0 = rough_start

    # 3. stride: slide a probe from the middle of frame 0 along the data that
    #    follows and take the offset where it matches best.
    L = 2048
    probe_off = s0 + (h // 2) * row
    probe = _u16(buf, probe_off, L)
    max_extra = int(min(16 * row + 16384, max(0, size - s0 - pix - L * 2 - 2)))
    region = _u16(buf, probe_off + pix, max_extra // 2 + L)
    if region.size >= L + 1:
        win = np.lib.stride_tricks.sliding_window_view(region, L)[:, ::4]
        mad = np.abs(win - probe[::4]).mean(axis=1)
        stride = pix + 2 * int(np.argmin(mad))
    else:
        stride = pix

    # 4. row phase: shift by whole rows so per-frame header rows fall outside
    #    the image (they show up as a hard edge at the top or bottom).
    def edge_cost(s):
        # judge on the 2nd frame: the file header before frame 0 can be blank
        s1 = s + stride if s + stride + pix <= size else s
        a = frame_at(s1)
        # row-to-row change down the whole frame: header rows inside the
        # image show up as the biggest jumps, wherever they land
        d = np.abs(np.diff(a, axis=0)).mean(axis=1)
        jumps = np.sort(d)[-4:].mean() / (np.median(d) + 1)
        blank = sum(1 for r in range(a.shape[0]) if a[r].std() == 0)
        return jumps + 100 * blank

    extra_rows = max(0, (stride - pix) // row)
    shifts = range(-4 - extra_rows, 5 + extra_rows)
    s0 = min((s0 + r * row for r in shifts if s0 + r * row >= si), key=edge_cost)

    n = 1 + (size - (s0 + pix)) // stride
    return Layout(width=w, height=h, first=int(s0), stride=int(stride), n_frames=int(n))
