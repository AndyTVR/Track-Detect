"""Turn frames into images and videos: colour scale, ROI outline, timestamp."""
from __future__ import annotations

import os
import threading

import cv2
import numpy as np

from .analysis import MODES, Pipeline, clean_filters, mode_cfg

ROI_BGR = (77, 72, 229)       # red outline, as in Research Studio


# ------------------------------------------------------------------ palettes
def _stops_lut(stops):
    """256-entry BGR lookup table from (position 0-1, '#rrggbb') stops."""
    xs = np.array([p for p, _ in stops], np.float32)
    rgb = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for _, c in stops], np.float32)
    t = np.linspace(0, 1, 256, dtype=np.float32)
    lut = np.stack([np.interp(t, xs, rgb[:, k]) for k in range(3)], 1)
    return lut[:, ::-1].astype(np.uint8)          # RGB -> BGR


def _cv_lut(cmap):
    return cv2.applyColorMap(np.arange(256, dtype=np.uint8).reshape(-1, 1), cmap).reshape(256, 3)


PALETTES = {   # name: (label, BGR lookup table)
    "white": ("White hot", np.repeat(np.arange(256, dtype=np.uint8)[:, None], 3, 1)),
    "black": ("Black hot", np.repeat(np.arange(255, -1, -1, dtype=np.uint8)[:, None], 3, 1)),
    "iron": ("Iron", _stops_lut([(0, "#000000"), (0.18, "#20008C"), (0.38, "#8F0896"), (0.58, "#E0441C"),
                                 (0.78, "#F9A600"), (0.92, "#FFE861"), (1, "#FFFFFF")])),
    "rainbow": ("Rainbow", _cv_lut(cv2.COLORMAP_TURBO)),
    "lava": ("Lava", _cv_lut(cv2.COLORMAP_INFERNO)),
    "arctic": ("Arctic", _stops_lut([(0, "#000000"), (0.35, "#0B2A6F"), (0.6, "#1E88E5"), (0.8, "#7FD3F7"),
                                     (0.93, "#FFD54F"), (1, "#FFFFFF")])),
}
VIEW = {"palette": "white"}   # app-wide default palette, set by app.py


def palette_stops(name, n=17):
    lut = PALETTES.get(name, PALETTES["white"])[1]
    return ["#%02x%02x%02x" % tuple(int(v) for v in lut[int(k * 255 / (n - 1))][::-1]) for k in range(n)]


def colorize(gray: np.ndarray, palette=None) -> np.ndarray:
    lut = PALETTES.get(palette or VIEW["palette"], PALETTES["white"])[1]
    return lut[gray]


def auto_range(img: np.ndarray, scale: str):
    """Automatic visible range. 'image' = from image (subtraction modes), 'raw' = thermal."""
    if scale == "image":
        lo = float(np.median(img))
        hi = float(np.percentile(img, 99.97))
        hi = max(hi, lo + 0.5 if img.dtype != np.uint16 else lo + 20)
    else:
        lo, hi = (float(v) for v in np.percentile(img[::4, ::4], [1, 99.7]))
        hi = max(hi, lo + 1e-3)
    return lo, hi


def blend_still_frame(ev: dict, how: str, filters, n_frames: int) -> int:
    """Frame for a blended still. Crossfade: activity first observed plus the
    Max Frame Interval persistence, so the trail has built up. Overlay: the
    event's peak activity."""
    if how == "crossfade":
        return int(min(n_frames - 1, ev["f0"] + clean_filters(filters)["mfi"]))
    return int(ev.get("peak_frame", (ev["f0"] + ev["f1"]) // 2))


# ------------------------------------------------------------ image clean-up
# Viewing and exports only; the detection scan never uses these.
DDE_CLIP = {1: 1.5, 2: 2.5, 3: 4.0}          # detail enhancement strength (CLAHE clip limit)
TNR_WEIGHT = {1: 0.5, 2: 0.3, 3: 0.15}       # noise reduction: weight given to each new frame
TNR_PREROLL = {1: 4, 2: 8, 3: 14}            # frames needed to settle after a jump


def clean_enh(e=None) -> dict:
    e = e or {}
    return {k: int(min(3, max(0, int(e.get(k, 0) or 0)))) for k in ("dde", "tnr")}


def detail_enhance(g: np.ndarray, level: int) -> np.ndarray:
    """Local contrast enhancement (CLAHE) on the 0-255 picture: brings out roof
    edges, vegetation and animals against smooth sky, even when one hot area
    takes up most of the colour range."""
    if not level:
        return g
    return cv2.createCLAHE(clipLimit=DDE_CLIP[level], tileGridSize=(8, 8)).apply(g)


def to_u8(img: np.ndarray, scale: str, rng=None) -> np.ndarray:
    """Map values to 0-255 over the visible range (the user's, or automatic)."""
    lo, hi = rng if rng else auto_range(img, scale)
    hi = max(float(hi), float(lo) + 1e-6)
    out = (img - lo) * (255.0 / (hi - lo))
    return np.clip(out, 0, 255).astype(np.uint8)


LABEL = {"scale": 1.0}   # timestamp text size (Settings tab)


def decorate(gray: np.ndarray, roi_points=None, label: str | None = None,
             show_roi=True, show_time=True, palette=None) -> np.ndarray:
    img = colorize(gray, palette) if gray.ndim == 2 else gray
    if show_roi and roi_points and len(roi_points) >= 3:
        cv2.polylines(img, [np.asarray(roi_points, np.int32)], True, ROI_BGR, 1, cv2.LINE_AA)
    if show_time and label:
        h, w = img.shape[:2]
        fs = max(0.35, w / 1400 * LABEL["scale"])
        thick = 2 if fs >= 1.1 else 1
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, thick)
        x, y = (w - tw) // 2, h - 10
        cv2.rectangle(img, (x - 6, y - th - 6), (x + tw + 6, y + 6), (20, 16, 14), -1)
        cv2.putText(img, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, fs, (235, 232, 230), thick, cv2.LINE_AA)
    return img


class Renderer:
    """Renders frame i in a mode, reusing filter state when frames are
    requested in order (playback), and always feeding the filters enough
    earlier frames first, so a jump never shows stale trails."""

    def __init__(self, src):
        self.src = src
        self._lock = threading.Lock()
        self._key = None
        self._pipe = None
        self._last = None
        self._out = None
        self.filters = clean_filters()

    def filtered(self, i: int, mode: str, window_start: int = 0) -> np.ndarray:
        cfg = mode_cfg(mode, self.filters() if callable(self.filters) else self.filters)
        i = int(np.clip(i, 0, self.src.n_frames - 1))
        with self._lock:
            key = (mode, int(window_start) if cfg["mc"] else None, cfg["mfi"], cfg["ss"])
            if key == self._key and self._last is not None and self._last == i:
                return self._out
            if key == self._key and self._last is not None and self._last < i <= self._last + 3:
                start = self._last + 1
            else:
                self._pipe = Pipeline(**cfg)
                start = max(0, min(window_start, i)) if cfg["mc"] else max(0, i - self._pipe.preroll)
            out = None
            for k in range(start, i + 1):
                out = self._pipe.step(self.src.frame(k))
            self._key, self._last, self._out = key, i, out
            return out

    # ---- motion-adaptive temporal noise reduction for the thermal picture
    def _temporal_noise(self):
        if getattr(self, "_tn_sigma", None) is None:
            n, sig = self.src.n_frames, []
            for c in (0.2, 0.5, 0.8):
                i = int(c * (n - 2))
                d = self.src.frame(i + 1).astype(np.float32)[::2, ::2] - self.src.frame(i).astype(np.float32)[::2, ::2]
                sig.append(float(np.median(np.abs(d - np.median(d)))) * 1.4826 / np.sqrt(2))
            self._tn_sigma = max(float(np.median(sig)), 1e-3)
        return self._tn_sigma

    def thermal(self, i: int, tnr: int = 0) -> np.ndarray:
        """Frame i of the thermal picture. With noise reduction on, each pixel
        is averaged over recent frames, but only while it stays within the
        noise of its average: anything that moves or changes is shown as it
        is, so bats stay sharp while the still background gets cleaner."""
        i = int(np.clip(i, 0, self.src.n_frames - 1))
        if not tnr:
            return self.src.frame(i)
        with self._lock:
            st = getattr(self, "_tn", None)
            if st and st["level"] == tnr and st["last"] == i:
                return st["out"]
            if st and st["level"] == tnr and st["last"] < i <= st["last"] + 3:
                start, avg = st["last"] + 1, st["avg"]
            else:
                start, avg = max(0, i - TNR_PREROLL[tnr]), None
            w, thr = TNR_WEIGHT[tnr], 3.0 * self._temporal_noise()
            for k in range(start, i + 1):
                f = self.src.frame(k).astype(np.float32)
                if avg is None:
                    avg = f
                else:
                    still = np.abs(f - avg) < thr
                    avg = np.where(still, avg + w * (f - avg), f)
            out = avg.astype(np.float32)
            self._tn = {"level": tnr, "last": i, "avg": avg, "out": out}
            return out

    def blended(self, i, window_start=0, palette=None, rng=None, opacity=0.5, how="overlay", enh=None):
        """Blended mode, a mix of the thermal and High Sensitivity pictures.
        overlay:   the trails are laid over the thermal picture. Where they are
                   bright they replace it, by up to `opacity`; elsewhere the
                   thermal picture shows through untouched.
        crossfade: the two whole pictures are mixed. 0 = thermal only,
                   1 = High Sensitivity only.
        `rng` is the thermal picture's visible range."""
        i = int(np.clip(i, 0, self.src.n_frames - 1))
        enh = clean_enh(enh)
        t = self.thermal(i, enh["tnr"])
        h = self.filtered(i, "review", window_start)
        auto = auto_range(t, "raw")
        sub = t[::4, ::4]
        self.last_info = {"lo": (rng or auto)[0], "hi": (rng or auto)[1], "auto_lo": auto[0], "auto_hi": auto[1],
                          "min": float(sub.min()), "max": float(sub.max())}
        th = colorize(detail_enhance(to_u8(t, "raw", rng), enh["dde"]), palette).astype(np.float32)
        hu = to_u8(h, "image")
        hs = colorize(hu, palette).astype(np.float32)
        a = float(np.clip(opacity, 0, 1))
        if how == "crossfade":
            return (th * (1 - a) + hs * a).clip(0, 255).astype(np.uint8)
        # weak values are background noise: fade them out so only movement shows
        m = np.clip((hu.astype(np.float32) - 110.0) / 100.0, 0, 1)[..., None] * float(np.clip(opacity, 0, 1))
        return (th * (1 - m) + hs * m).clip(0, 255).astype(np.uint8)

    def image(self, i, mode, roi_points=None, window_start=0, show_roi=True, show_time=True,
              palette=None, rng=None, opacity=0.5, blend="overlay", enh=None):
        label = (self.src.date_label(i) + " " + self.src.time_label(i) + " " + self.src.zone_of(i)).strip()
        enh = clean_enh(enh)
        if mode == "blend":
            return decorate(self.blended(i, window_start, palette, rng, opacity, blend, enh), roi_points, label, show_roi, show_time)
        y = self.thermal(i, enh["tnr"]) if mode == "raw" and enh["tnr"] else self.filtered(i, mode, window_start)
        auto = auto_range(y, MODES[mode]["scale"])
        sub = y[::4, ::4]
        self.last_info = {"lo": (rng or auto)[0], "hi": (rng or auto)[1], "auto_lo": auto[0], "auto_hi": auto[1],
                          "min": float(sub.min()), "max": float(sub.max())}
        g = to_u8(y, MODES[mode]["scale"], rng)
        if mode in ("raw", "path"):
            g = detail_enhance(g, enh["dde"])
        return decorate(g, roi_points, (self.src.date_label(i) + " " + self.src.time_label(i) + " " + self.src.zone_of(i)).strip(),
                        show_roi, show_time, palette)


# --------------------------------------------------------------------- video
class VideoWriter:
    """H.264 MP4 via the ffmpeg bundled with imageio-ffmpeg (no install
    needed); falls back to OpenCV's MPEG-4 writer."""

    def __init__(self, path, size, fps, quality=75):
        self.path = path
        self._gen = None
        self._cv = None
        try:
            import imageio_ffmpeg
            crf = int(round(35 - quality * 0.2))     # 75 % -> crf 20
            self._gen = imageio_ffmpeg.write_frames(
                path, size, fps=fps, codec="libx264", pix_fmt_in="rgb24",
                pix_fmt_out="yuv420p", output_params=["-crf", str(crf), "-preset", "veryfast"],
                macro_block_size=2)
            self._gen.send(None)
        except Exception:
            self._gen = None
            self._cv = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)

    def write(self, bgr: np.ndarray):
        if self._gen is not None:
            self._gen.send(np.ascontiguousarray(bgr[:, :, ::-1]))
        else:
            self._cv.write(bgr)

    def close(self):
        if self._gen is not None:
            self._gen.close()
        if self._cv is not None:
            self._cv.release()


def safe_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)


def export_event(src, ev, roi_points, outdir, stem, opts=None, progress=None) -> list[str]:
    """The event pack: flight-path still and clip, review clip, entry frames."""
    opts = opts or {}
    pad = int(opts.get("pad_s", 3) * src.fps)
    ws = max(0, ev["f0"] - pad)
    we = min(src.n_frames - 1, ev["f1"] + pad)
    show_roi = opts.get("overlays", "roi+time") in ("roi+time",)
    show_time = opts.get("overlays", "roi+time") != "none"
    os.makedirs(outdir, exist_ok=True)
    t = src.time_of(ev["f0"])
    tlabel = t.strftime("%H-%M-%S") if t else f"f{ev['f0']}"
    from .settings import NAMING
    name = NAMING.get(opts.get("naming"), NAMING["site_recording"]).format(
        site=opts.get("site", ""), recording=opts.get("recording", stem), n=ev["n"], time=tlabel,
        date=t.strftime("%d-%m-%Y") if t else "nodate")
    base = os.path.join(outdir, safe_name(name.strip("_")))
    vfps = src.fps * float(opts.get("slowmo", 1.0) or 1.0)   # slow-motion export
    want = opts.get("items", ["path_still", "path_clip", "review_clip", "entry_frames"])
    files = []
    total = (we - ws + 1) * (("path_clip" in want or "path_still" in want) + ("review_clip" in want)
                             + ("blend_clip" in want)) + 1
    done = [0]

    def tick():
        done[0] += 1
        if progress and done[0] % 25 == 0:
            progress(done[0], total)

    pal = opts.get("palette")
    rngs = opts.get("ranges") or {}
    enh = clean_enh(opts.get("enh"))

    def rng(mode):
        v = rngs.get(mode)
        return (float(v[0]), float(v[1])) if v and len(v) == 2 else None

    def label(i):
        return (src.date_label(i) + " " + src.time_label(i) + " " + src.zone_of(i)).strip()

    if "path_clip" in want or "path_still" in want:
        pipe = Pipeline(**MODES["path"])
        vw = VideoWriter(base + "_flightpath.mp4", (src.width, src.height), vfps,
                         opts.get("quality", 75)) if "path_clip" in want else None
        last = None
        for i in range(ws, we + 1):
            y = pipe.step(src.frame(i))
            if vw:
                vw.write(decorate(detail_enhance(to_u8(y, "raw", rng("path")), enh["dde"]), roi_points, label(i), show_roi, show_time, pal))
            last = (y, i)
            tick()
        if vw:
            vw.close(); files.append(vw.path)
        if "path_still" in want and last is not None:
            p = base + "_flightpath.jpg"
            cv2.imwrite(p, decorate(detail_enhance(to_u8(last[0], "raw", rng("path")), enh["dde"]), roi_points, label(last[1]), show_roi, show_time, pal),
                        [cv2.IMWRITE_JPEG_QUALITY, 95])
            files.append(p)

    if "review_clip" in want:
        rngs = {**rngs, "review": None}   # High Sensitivity Mode always uses automatic contrast
        pipe = Pipeline(**mode_cfg("review", opts.get("filters")))
        for k in range(max(0, ws - pipe.preroll), ws):
            pipe.step(src.frame(k))
        vw = VideoWriter(base + "_high-sensitivity.mp4", (src.width, src.height), vfps, opts.get("quality", 75))
        for i in range(ws, we + 1):
            vw.write(decorate(to_u8(pipe.step(src.frame(i)), "image", rng("review")), roi_points, label(i), show_roi, show_time, pal))
            tick()
        vw.close(); files.append(vw.path)

    if "blend_clip" in want:   # Blended mode, with the blend type and opacity set in the app
        br = Renderer(src)
        br.filters = clean_filters(opts.get("filters"))
        how = "crossfade" if opts.get("blend") == "crossfade" else "overlay"
        op = float(opts.get("opacity", 0.8))
        vw = VideoWriter(base + f"_blended-{how}.mp4", (src.width, src.height), vfps, opts.get("quality", 75))
        for i in range(ws, we + 1):
            vw.write(br.image(i, "blend", roi_points, show_roi=show_roi, show_time=show_time,
                              palette=pal, rng=rng("blend"), opacity=op, blend=how, enh=enh))
            tick()
        vw.close(); files.append(vw.path)

    if "blend_still" in want:   # crossfade: first activity + persistence; overlay: peak
        br = Renderer(src)
        br.filters = clean_filters(opts.get("filters"))
        how = "crossfade" if opts.get("blend") == "crossfade" else "overlay"
        f = blend_still_frame(ev, how, opts.get("filters"), src.n_frames)
        p = f"{base}_blended-{how}_frame{f}.jpg"
        cv2.imwrite(p, br.image(f, "blend", roi_points, window_start=ws, show_roi=show_roi, show_time=show_time,
                                palette=pal, rng=rng("blend"), opacity=float(opts.get("opacity", 0.8)), blend=how, enh=enh),
                    [cv2.IMWRITE_JPEG_QUALITY, 95])
        files.append(p)

    if "entry_frames" in want:
        r = Renderer(src)
        r.filters = clean_filters(opts.get("filters"))
        done = set()
        for tr in ev.get("tracks", []):
            f = min(tr["first_frame"] + 2, src.n_frames - 1)
            if f in done:
                continue
            done.add(f)
            p = f"{base}_frame{f}.jpg"
            cv2.imwrite(p, r.image(f, "review", roi_points, show_roi=show_roi, show_time=show_time,
                                   palette=pal, rng=rng("review")),
                        [cv2.IMWRITE_JPEG_QUALITY, 95])
            files.append(p)
    if progress:
        progress(total, total)
    return files
