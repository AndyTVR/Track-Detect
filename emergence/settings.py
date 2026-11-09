"""Track & Detect settings: one place for every option on the Settings tab.

Saved to settings.json beside the program, so they're kept for next time.
`CURRENT` is the live copy the rest of the program reads.
"""
from __future__ import annotations

import copy
import json
import os

DEFAULT_CLASSES = ["Emergence", "Re-entry", "Flight through / commuting", "Passes behind structure",
                   "Foraging", "Bird", "Insect / noise", "Other"]

EXPORT_ITEMS = ("path_still", "path_clip", "review_clip", "blend_still", "blend_clip", "entry_frames")

DEFAULTS = {
    "version": 1,
    "appearance": {"scheme": "forest", "theme": "dark", "window": "app"},
    "view": {"palette": "white", "dde": 0, "tnr": 0, "blend": "overlay", "opacity": 0.8, "speed": 1.0},
    "filters": {"mfi": 5, "ss": 5},
    "detect": {"sensitivity": "normal", "merge_s": 2.0, "min_frames": 1, "window_s": 3.0},
    "export": {"folder": "", "items": list(EXPORT_ITEMS), "overlays": "roi+time", "text_size": "medium",
               "naming": "site_recording", "quality": 75, "slowmo": 1.0},
    "units": {"temp": "C", "zone": "uk", "clock_offset_s": 0.0},
    "classes": DEFAULT_CLASSES,
    "review": {"auto_advance": True, "auto_play": False},
    "report": {"company": "", "contact": "", "analyst": "", "camera": ""},
}

# how far above the background noise the suggested detection level sits (x noise)
SENSITIVITY = {"low": 9.0, "normal": 6.0, "high": 4.0}
TEXT_SCALE = {"small": 0.75, "medium": 1.0, "large": 1.4}
NAMING = {   # how exported files are named
    "site_recording": "{site}_{recording}_event{n}_{time}",
    "date_site": "{date}_{site}_{recording}_event{n}",
    "recording_event": "{recording}_event{n}_{time}",
}

CURRENT: dict = copy.deepcopy(DEFAULTS)


def _num(v, lo, hi, default, cast=float):
    try:
        return cast(min(hi, max(lo, cast(v))))
    except (TypeError, ValueError):
        return default


def _pick(v, choices, default):
    return v if v in choices else default


def clean(d: dict | None) -> dict:
    """Fill in anything missing and keep every value in range, so a settings
    file from an older version (or edited by hand) can't break the program."""
    d = d or {}
    D = DEFAULTS
    g = lambda sec: d.get(sec) if isinstance(d.get(sec), dict) else {}
    a, v, f, de, ex, u, rv, rp = (g(k) for k in ("appearance", "view", "filters", "detect", "export", "units",
                                                 "review", "report"))
    from .render import PALETTES   # late import: render imports settings
    classes = [str(c).strip()[:60] for c in (d.get("classes") or []) if str(c).strip()]
    items = [i for i in (ex.get("items") if isinstance(ex.get("items"), list) else D["export"]["items"])
             if i in EXPORT_ITEMS]
    return {
        "version": 1,
        "appearance": {"scheme": _pick(a.get("scheme"), ("forest", "ocean", "teal", "heather", "slate"), "forest"),
                       "theme": _pick(a.get("theme"), ("dark", "light"), "dark"),
                       "window": _pick(a.get("window"), ("app", "browser"), "app")},
        "view": {"palette": _pick(v.get("palette"), PALETTES, "white"),
                 "dde": _num(v.get("dde"), 0, 3, 0, int), "tnr": _num(v.get("tnr"), 0, 3, 0, int),
                 "blend": _pick(v.get("blend"), ("overlay", "crossfade"), "overlay"),
                 "opacity": round(_num(v.get("opacity"), 0, 1, 0.8), 2),
                 "speed": _pick(_num(v.get("speed"), 0.25, 4, 1.0), (0.25, 0.5, 1.0, 2.0, 4.0), 1.0)},
        "filters": {"mfi": _num(f.get("mfi"), 1, 60, 5, int), "ss": _num(f.get("ss"), 1, 60, 5, int)},
        "detect": {"sensitivity": _pick(de.get("sensitivity"), SENSITIVITY, "normal"),
                   "merge_s": round(_num(de.get("merge_s"), 0, 30, 2.0), 2),
                   "min_frames": _num(de.get("min_frames"), 1, 100, 1, int),
                   "window_s": round(_num(de.get("window_s"), 0, 60, 3.0), 2)},
        "export": {"folder": str(ex.get("folder") or "").strip(), "items": items,
                   "overlays": _pick(ex.get("overlays"), ("roi+time", "time", "none"), "roi+time"),
                   "text_size": _pick(ex.get("text_size"), TEXT_SCALE, "medium"),
                   "naming": _pick(ex.get("naming"), NAMING, "site_recording"),
                   "quality": _num(ex.get("quality"), 10, 100, 75, int),
                   "slowmo": _pick(_num(ex.get("slowmo"), 0.25, 1, 1.0), (0.25, 0.5, 1.0), 1.0)},
        "units": {"temp": _pick(u.get("temp"), ("C", "F"), "C"), "zone": _pick(u.get("zone"), ("uk", "utc"), "uk"),
                  "clock_offset_s": round(_num(u.get("clock_offset_s"), -86400 * 7, 86400 * 7, 0.0), 3)},
        "classes": classes or list(DEFAULT_CLASSES),
        "review": {"auto_advance": bool(rv.get("auto_advance", True)), "auto_play": bool(rv.get("auto_play", False))},
        "report": {k: str(rp.get(k) or "").strip()[:200] for k in D["report"]},
    }


def load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        raw = {}
    # settings files from before the Settings tab kept a few keys at the top level
    if "palette" in raw and not isinstance(raw.get("view"), dict):
        raw["view"] = {"palette": raw["palette"]}
    CURRENT.clear()
    CURRENT.update(clean(raw))
    return CURRENT


def save(path: str, d: dict | None = None) -> dict:
    if d is not None:
        CURRENT.clear()
        CURRENT.update(clean(d))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(CURRENT, fh, indent=1)
    os.replace(tmp, path)
    return CURRENT


def get(section: str, key: str | None = None):
    sec = CURRENT.get(section, DEFAULTS.get(section))
    return sec if key is None else sec.get(key, DEFAULTS[section][key])
