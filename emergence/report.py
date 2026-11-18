"""PDF survey report: methodology, activity plot with the detection level,
event table and a page section per event with stills, decision and comments."""
from __future__ import annotations

import datetime as _dt
import os
from io import BytesIO

import cv2
import numpy as np
from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from .analysis import SCAN_ID
from .render import Renderer, blend_still_frame, safe_name

HERE = os.path.dirname(__file__)
LOGO = os.path.join(HERE, "tve-logo-print.png")
GREEN = colors.HexColor("#2E7D32")
AMBER = colors.HexColor("#D98A00")
BLUE = colors.HexColor("#1F6FB5")
GREY = colors.HexColor("#6B7280")
LIGHT = colors.HexColor("#F2F4F7")
STATUS = {"confirmed": ("Accepted", GREEN), "rejected": ("Rejected", colors.HexColor("#B42318")),
          "todo": ("Not reviewed", AMBER)}


def _styles():
    ss = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=ss["Normal"], fontName="Helvetica", fontSize=9.5, leading=13.5)
    return {
        "body": base,
        "small": ParagraphStyle("s", parent=base, fontSize=8, leading=10.5, textColor=GREY),
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=13, leading=17,
                             spaceBefore=10, spaceAfter=5, textColor=colors.HexColor("#1B4D1E")),
        "h3": ParagraphStyle("h3", parent=base, fontName="Helvetica-Bold", fontSize=11, leading=14, spaceAfter=3),
        "cell": ParagraphStyle("c", parent=base, fontSize=8, leading=10, alignment=TA_LEFT),
        "cellb": ParagraphStyle("cb", parent=base, fontName="Helvetica-Bold", fontSize=8, leading=10),
    }


def _esc(t) -> str:
    return (str(t or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _jpeg(img_bgr, width_mm):
    ok, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 88])
    h, w = img_bgr.shape[:2]
    return Image(BytesIO(buf.tobytes()), width=width_mm * mm, height=width_mm * mm * h / w)


def _auto_top(peaks, base):
    """Same rule as the app's Auto y-axis: cut off spikes more than twice the
    height of the next one down (up to a quarter of them)."""
    hs = sorted([p - base for p in peaks if p > base], reverse=True)
    if len(hs) < 2:
        return None
    k = 0
    for i in range(min(max(1, len(hs) // 4), len(hs) - 1)):
        if hs[i] > 2 * hs[i + 1]:
            k = i + 1
    return base + hs[k] * 1.12 if k else None


def activity_drawing(rec, width_mm=174, height_mm=70):
    """The activity trace with the detection level and the events, as vectors."""
    act, src = rec.shown(rec.activity), rec.src
    level = rec.state.get("level")
    evs = rec.state.get("events", [])
    W, H = width_mm * mm, height_mm * mm
    L, R, T, B = 14 * mm, 4 * mm, 9 * mm, 9 * mm
    d = Drawing(W, H)
    d.add(Rect(L, B, W - L - R, H - T - B, strokeColor=colors.HexColor("#C9CED6"), fillColor=None, strokeWidth=0.5))
    if act is None or not len(act):
        d.add(String(L + 4, H / 2, "Not scanned", fontName="Helvetica", fontSize=8, fillColor=GREY))
        return d, False
    n = len(act)
    pts = 900
    edges = np.linspace(0, n, min(pts, n) + 1).astype(int)
    xs, ys = [], []
    for k in range(len(edges) - 1):
        a, b = edges[k], max(edges[k] + 1, edges[k + 1])
        j = a + int(np.argmax(act[a:b]))
        xs.append(j); ys.append(float(act[j]))
    lo = float(np.percentile(act, 1))
    hi = float(act.max())
    top = _auto_top([e["peak"] for e in evs], min(lo, level if level is not None else lo))
    capped = top is not None and top < hi
    if capped:
        hi = top
    if level is not None:
        lo, hi = min(lo, level), max(hi, level)
    hi = hi if hi > lo else lo + 1
    lo -= (hi - lo) * 0.03
    pw, ph = W - L - R, H - T - B
    fx = lambda f: L + f / max(1, n - 1) * pw
    fy = lambda v: B + (min(v, hi) - lo) / (hi - lo) * ph
    for e in evs:  # event windows, coloured by decision
        col = STATUS.get(e["status"], STATUS["todo"])[1]
        x0, x1 = fx(e["f0"]), max(fx(e["f1"]), fx(e["f0"]) + 1.2)
        d.add(Rect(x0, B, x1 - x0, ph, fillColor=colors.Color(col.red, col.green, col.blue, 0.13), strokeColor=None))
        d.add(String((x0 + x1) / 2, H - T + 2.2 * mm, str(e["n"]), fontName="Helvetica-Bold", fontSize=6.5,
                     fillColor=col, textAnchor="middle"))
    above, below = [], []
    line = []
    for x, v in zip(xs, ys):
        line += [fx(x), fy(v)]
    traces = [(rec.shown(rec.acts[r["id"]]), rec.roi_colour(r["id"])) for r in rec.rois if r["id"] in getattr(rec, "acts", {})]
    multi = len(traces) > 1
    if multi:   # several ROIs: each trace in its ROI's colour
        for a, hexc in traces:
            pl = []
            for k in range(len(edges) - 1):
                s0, e0 = edges[k], max(edges[k] + 1, edges[k + 1])
                j = s0 + int(np.argmax(a[s0:e0]))
                pl += [fx(j), fy(float(a[j]))]
            d.add(PolyLine(pl, strokeColor=colors.HexColor(hexc), strokeWidth=0.7))
    else:
        d.add(PolyLine(line, strokeColor=colors.HexColor("#9AA1AC"), strokeWidth=0.6))
    # highlight the parts above the line
    if level is not None and not multi:
        seg = []
        for x, v in zip(xs, ys):
            if v > level:
                seg += [fx(x), fy(v)]
            elif seg:
                if len(seg) >= 4:
                    d.add(PolyLine(seg, strokeColor=AMBER, strokeWidth=0.8))
                seg = []
        if len(seg) >= 4:
            d.add(PolyLine(seg, strokeColor=AMBER, strokeWidth=0.8))
    if level is not None:
        ly = fy(level)
        d.add(Line(L, ly, W - R, ly, strokeColor=BLUE, strokeWidth=1, strokeDashArray=[3, 2]))
        d.add(String(W - R - 1 * mm, ly + 1.2 * mm, f"Detection level {level:.2f} {_unit(src.units)}",
                     fontName="Helvetica-Bold", fontSize=7, fillColor=BLUE, textAnchor="end"))
    # axes labels
    for v in (lo + (hi - lo) * 0.03, hi):
        d.add(String(L - 1.2 * mm, fy(v) - 1, f"{v:.1f}", fontName="Helvetica", fontSize=6.5, fillColor=GREY,
                     textAnchor="end"))
    for k in range(5):
        f = int(k / 4 * (n - 1))
        d.add(String(fx(f), B - 3.6 * mm, src.time_label(f)[:8], fontName="Helvetica", fontSize=6.5,
                     fillColor=GREY, textAnchor="middle"))
    d.add(String(L, H - 3 * mm, f"Maximum in ROI ({_unit(src.units)}) against time ({src.zone_of(0) or 'elapsed'})",
                 fontName="Helvetica", fontSize=7, fillColor=GREY))
    return d, capped


def _unit(u):
    return "°C" if u == "°C" else u


def _fmt_dur(s):
    s = int(round(s))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _version_label() -> str:
    from . import beta
    v, ch = beta.INFO.get("version", "dev"), beta.INFO.get("channel", "dev")
    return f"{v} ({ch})" if ch in ("beta", "dev") else v


def _enh_text(e) -> str:
    lv = {0: "", 1: "low", 2: "medium", 3: "high"}
    e = e or {}
    parts = []
    if int(e.get("dde") or 0):
        parts.append(f"detail enhancement ({lv[int(e['dde'])]})")
    if int(e.get("tnr") or 0):
        parts.append(f"noise reduction ({lv[int(e['tnr'])]})")
    return ("Images use " + " and ".join(parts) + "; detection is not affected") if parts else "None"


def _content(rec, opts, out_path, progress=None):
    """The report as a list of blocks, written out as PDF or Word by the
    functions below. Block kinds:
      ("logo",) ("h1", t) ("h2", t) ("h3", t) ("p", html) ("small", html)
      ("kv", rows, widths_mm) ("table", head, rows, widths_mm) ("plot",)
      ("image", bgr, width_mm, caption) ("pair", [(bgr, caption), (bgr, caption)])
      ("keep", [blocks]) ("space", mm) ("pagebreak",)
    html is plain text with <b>, <i> and <font color="#rrggbb"> only."""
    src = rec.src
    evs = rec.state.get("events", [])
    comments = sorted(rec.state.get("comments", []), key=lambda c: c["frame"])
    pad = rec.window
    filters = rec.filters
    include_rejected = opts.get("rejected_images", True)
    zone = src.zone_of(0) or "elapsed time"

    def ev_comments(e):
        return [c for c in comments if e["f0"] - pad <= c["frame"] <= e["f1"] + pad]

    linked = {c["id"] for e in evs for c in ev_comments(e)}
    n_ok = sum(e["status"] == "confirmed" for e in evs)
    n_no = sum(e["status"] == "rejected" for e in evs)
    n_todo = len(evs) - n_ok - n_no
    site = os.path.basename(os.path.dirname(rec.path))
    cam_txt = opts.get("camera") or src.camera
    title_file = os.path.basename(rec.path)
    B = []
    # ------------------------------------------------------------------ cover
    B += [("logo",), ("h1", "Thermal emergence survey: analysis report"),
          ("h3", f"{opts.get('location') or site} · {title_file}")]
    if opts.get("company"):
        B.append(("p", f"Prepared for {_esc(opts['company'])}"))
    B.append(("space", 3))
    t0 = src.time_of(0)
    info = [
        ["Company", opts.get("company") or "–"],
        ["Company contact", opts.get("contact") or "–"],
        ["Survey location", opts.get("location") or site],
        ["Recording", title_file],
        ["Camera and lens", opts.get("camera") or src.camera or "unknown"],
        ["Date", t0.strftime("%A %d/%m/%Y") if t0 else "not stored in file"],
        [f"Start – end ({zone})", f"{src.time_label(0)[:8]} – {src.time_label(src.n_frames - 1)[:8]}" if t0 else "–"],
        ["Duration", _fmt_dur(src.span_s(0, src.n_frames - 1))],
        ["Image size", f"{src.width} × {src.height} pixels"],
        ["Analyst", opts.get("analyst") or "–"],
        ["Report created", _dt.datetime.now().strftime("%d/%m/%Y, %H:%M")],
    ]
    B += [("kv", info, (45, 127)), ("space", 5), ("h2", "Summary")]
    cls_count = {}
    for e in evs:
        if e["status"] == "confirmed":
            cls_count[e.get("cls") or "Unclassified"] = cls_count.get(e.get("cls") or "Unclassified", 0) + 1
    ok_times = [e for e in evs if e["status"] == "confirmed"]
    summ = [["Events detected", str(len(evs))], ["Accepted", str(n_ok)], ["Rejected", str(n_no)],
            ["Not reviewed", str(n_todo)]]
    if ok_times:
        summ += [["First accepted event", f"{src.time_label(ok_times[0]['f0'])[:8]} {src.zone_of(ok_times[0]['f0'])}"],
                 ["Last accepted event", f"{src.time_label(ok_times[-1]['f0'])[:8]} {src.zone_of(ok_times[-1]['f0'])}"]]
    for c, k in sorted(cls_count.items(), key=lambda kv: -kv[1]):
        summ.append([f"Accepted as: {c}", str(k)])
    B.append(("kv", summ, (45, 127)))
    if n_todo:
        B += [("space", 2), ("p", f"<b>Note:</b> {n_todo} event{'s' if n_todo != 1 else ''} had not been reviewed when "
                                  "this report was created.")]

    # ------------------------------------------------------------------ methodology
    B += [("pagebreak",), ("h2", "Introduction and methodology")]
    level = rec.state.get("level")
    sugg = rec.state.get("suggested_level")
    roi_names = [x["name"] for x in rec.rois if len(x.get("points") or []) >= 3]
    paras = [
        f"This report presents the analysis of a thermal imaging recording" + (f" (recorded with {_esc(cam_txt)})" if cam_txt else "") + f" made to survey bat emergence and "
        f"re-entry at <b>{_esc(opts.get('location') or site)}</b>. The recording was analysed with Track &amp; Detect by Thermal Vision "
        "Ecology, which reads the FLIR .ats radiometric recording directly and follows the TVE thermal analysis "
        "method: an automated scan finds moments of movement, and an analyst reviews every one of them.",
        ("<b>1. Regions of interest (ROIs).</b> The analyst drew " + (f"{len(roi_names)} regions of interest ({_esc(', '.join(roi_names))})" if len(roi_names) > 1 else "a region of interest")
         + " around the roost features (roofline, eaves, openings and nearby flight lines), excluding open sky where possible. "
         "Only these regions are used for detection" + (", and each event is reported with the ROI it was found in." if len(roi_names) > 1 else ".")),
        "<b>2. Activity scan.</b> Every frame of the recording was processed with a Window Average filter "
        "(3 × 3 pixels, to suppress single-pixel noise) followed by Sliding Subtraction (each frame minus the "
        "frame 5 frames earlier). This removes the stationary scene (buildings, vegetation, sky) so that only "
        "change remains, and a warm, moving animal stands out. The highest value inside each ROI was recorded "
        "for each frame, giving the activity trace shown below.",
        f"<b>3. Detection level.</b> A detection level was set on the activity trace: every rise above it "
        f"becomes an event, and rises within 2 seconds of each other are merged into one event. The level used "
        f"was <b>{level:.2f} {_unit(src.units)}</b>" + (f" (suggested starting level {sugg:.2f}, based on the "
        "recording's background noise)" if sugg is not None else "") + ". Spikes below the level were "
        "not reviewed." if level is not None else "<b>3. Detection level.</b> The recording had not been scanned.",
        f"<b>4. Review.</b> Each event was reviewed by the analyst in a window from 3 seconds before to 3 seconds "
        f"after it, in the Default (plain thermal) view, the Tracking view and the Detection view, whose trails use "
        f"Max Frame Interval {filters['mfi']} frames with Sliding Subtraction {filters['ss']} frames to show moving animals brightly. "
        "Each event was then accepted with a classification, or rejected (for example as an insect, "
        "vegetation movement or noise). Comments record what the analyst observed.",
        "<b>5. Images.</b> For each event this report shows a <i>tracking</i> image (the hottest value of "
        "every pixel across the event window, building up the whole route) and a <i>detection</i> "
        "frame (taken at the event's peak activity for an overlay, or a Max Frame Interval's worth of frames "
        "after activity was first seen for a crossfade): the thermal picture with the moving-animal trails "
        "combined with it, so the moving animal can be seen in its setting.",
    ]
    for p in paras:
        B += [("p", p), ("space", 2.2)]
    B += [("h2", "Activity plot"), ("plot",)]
    if progress:
        progress(1, len(evs) + 3)

    r = Renderer(src)
    r.filters = filters
    mid = evs[0]["f0"] if evs else 0
    B.append(("keep", [("h2", "Regions of interest" if len(roi_names) > 1 else "Region of interest"),
                       ("image", r.image(mid, "raw", rec.roi_shapes(), show_time=True), 120,
                        "Figure 2. The region" + ("s" if len(roi_names) > 1 else "") + " of interest used for detection.")]))

    # ------------------------------------------------------------------ event table
    B += [("pagebreak",), ("h2", "Events")]
    multi = len(roi_names) > 1
    head = ["#", f"Start ({zone})", "End", "Length"] + (["ROI"] if multi else ["Peak"]) + ["Decision", "Classification", "Comments"]
    rows = []
    for e in evs:
        lab, col = STATUS.get(e["status"], STATUS["todo"])
        cm = "; ".join(c["text"] for c in ev_comments(e))
        rows.append([str(e["n"]), src.time_label(e["f0"])[:8], src.time_label(e["f1"])[:8],
                     f"{src.span_s(e['f0'], e['f1']):.1f} s", rec.roi_name(e.get("roi")) if multi else f"{e['peak']:.1f}",
                     f'<font color="{_hex(col)}"><b>{lab}</b></font>', _esc(e.get("cls") or "–"), _esc(cm) or "–"])
    if not rows:
        rows.append(["No events were detected at this level."] + [""] * 7)
    B.append(("table", head, rows, (8, 19, 17, 14, 13 if not multi else 20, 22, 32 if not multi else 28, 47 if not multi else 44)))

    # ------------------------------------------------------------------ per event
    img_dir = None
    if opts.get("save_images", True):
        img_dir = os.path.splitext(out_path)[0] + "_images"
        os.makedirs(img_dir, exist_ok=True)
    for k, e in enumerate(evs):
        if progress:
            progress(k + 2, len(evs) + 3)
        lab, col = STATUS.get(e["status"], STATUS["todo"])
        block = [("h2", f'Event {e["n"]} <font color="{_hex(col)}">· {lab}</font>')]
        details = [
            ["Time", f"{src.time_label(e['f0'])} – {src.time_label(e['f1'])} {src.zone_of(e['f0'])}"],
            ["Frames", f"{e['f0']:,} – {e['f1']:,} ({src.span_s(e['f0'], e['f1']):.1f} s)"],
            ["ROI", rec.roi_name(e.get("roi"))],
            ["Peak activity", f"{e['peak']:.2f} {_unit(src.units)} at frame {e['peak_frame']:,}"],
            ["Decision", lab],
            ["Classification", e.get("cls") or "–"],
        ]
        block.append(("kv", details, (32, 140)))
        if e["status"] != "rejected" or include_rejected:
            ws, we = max(0, e["f0"] - pad), min(src.n_frames - 1, e["f1"] + pad)
            path_img = r.image(we, "path", rec.event_roi_points(e), window_start=ws, palette=opts.get("palette"), enh=opts.get("enh"))
            how, op = opts.get("blend", "overlay"), float(opts.get("opacity", 0.8))
            bf = blend_still_frame(e, how, filters, src.n_frames)
            bf_note = f"first activity + {filters['mfi']} frames" if how == "crossfade" else "peak"
            hs_img = r.image(bf, "blend", rec.event_roi_points(e), window_start=ws, palette=opts.get("palette"),
                             rng=opts.get("blend_range"), opacity=op, blend=how, enh=opts.get("enh"))
            if img_dir:
                base = os.path.join(img_dir, safe_name(f"event{e['n']}_{src.time_label(e['f0'])[:8].replace(':', '-')}"))
                cv2.imwrite(base + "_tracking.jpg", path_img, [cv2.IMWRITE_JPEG_QUALITY, 92])
                cv2.imwrite(base + f"_detection-{how}_frame{bf}.jpg", hs_img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            block += [("space", 2), ("pair", [(path_img, f"Tracking, {src.time_label(ws)[:8]}–{src.time_label(we)[:8]}"),
                                              (hs_img, f"Detection ({how} {round(op * 100)}%), frame {bf:,} ({bf_note})")])]
        cms = ev_comments(e)
        if cms:
            block += [("space", 2), ("p", "<b>Comments</b>")]
            for c in cms:
                block.append(("p", f"{src.time_label(c['frame'])[:8]} (frame {c['frame']:,}): {_esc(c['text'])}"))
        block.append(("space", 5))
        B.append(("keep", block))

    other = [c for c in comments if c["id"] not in linked]
    if other:
        B += [("h2", "Other comments"), ("small", "Comments made outside any event window.")]
        for c in other:
            B.append(("p", f"{src.time_label(c['frame'])[:8]} {src.zone_of(c['frame'])} (frame {c['frame']:,}): {_esc(c['text'])}"))

    # ------------------------------------------------------------------ appendix
    B.append(("h2", "Appendix: analysis settings"))
    app_rows = [
        ["Recording file", rec.path],
        ["Scan filters", "Window Average 3 × 3, Sliding Subtraction 5 frames (" + SCAN_ID + ")"],
        ["Activity measure", "Maximum inside each ROI per frame"],
        ["Detection level", f"{level:.3f} {_unit(src.units)}" if level is not None else "–"],
        ["End of recording", (f"A very large spike from {src.time_label(rec.end_spike_frame)[:8]} {src.zone_of(rec.end_spike_frame)} to the end "
                              "was left out of the analysis (typically the camera being approached or moved)")
                             if rec.end_spike_frame is not None else "Final frame not used"],
        ["Suggested level", f"{sugg:.3f} {_unit(src.units)}" if sugg is not None else "–"],
        ["Event merge gap", "2 s"],
        ["Review window", "3 s either side of each event"],
        ["Detection trails", f"Max Frame Interval {filters['mfi']} frames + Sliding Subtraction {filters['ss']} frames"],
        ["Detection images", ("Crossfade" if opts.get("blend") == "crossfade" else "Overlay")
                             + f" at {round(float(opts.get('opacity', 0.8)) * 100)}% opacity"],
        ["Software", f"Track & Detect {_version_label()}"],
        ["Image clean-up", _enh_text(opts.get("enh"))],
        ["ROIs", ", ".join(roi_names) or "whole image"],
        ["Times", "UK time (BST in summer, GMT in winter), from the UTC start time stored in the recording"],
        ["Pixel values", _unit(src.units) if src.units in ("°C", "°F") else f"raw {src.units}"],
    ]
    if rec.state.get("scan_id") not in (None, SCAN_ID):
        app_rows.append(["Warning", "This recording was scanned with an earlier version of the scan filters."])
    B.append(("kv", app_rows, (40, 132)))
    if img_dir:
        B += [("space", 2), ("small", f"Full-resolution copies of the images are saved in {_esc(img_dir)}.")]
    return B


def _hex(col) -> str:
    return col.hexval().replace("0x", "#")


def build_report(rec, out_path, opts=None, progress=None):
    """Write the report as a PDF, or as a Word document when out_path ends
    in .docx."""
    opts = opts or {}
    blocks = _content(rec, opts, out_path, progress)
    n = len(rec.state.get("events", []))
    if out_path.lower().endswith(".docx"):
        _write_docx(rec, blocks, out_path, opts)
    else:
        _write_pdf(rec, blocks, out_path, opts)
    if progress:
        progress(n + 3, n + 3)
    return out_path


# ---------------------------------------------------------------------- PDF
def _write_pdf(rec, blocks, out_path, opts):
    st = _styles()
    title_file = os.path.basename(rec.path)

    def conv(b):
        k = b[0]
        if k == "logo":
            return [Image(LOGO, width=55 * mm, height=55 * mm * 180 / 665, hAlign="LEFT"), Spacer(1, 6 * mm)] if os.path.exists(LOGO) else []
        if k in ("h1", "h2", "h3"):
            return [Paragraph(b[1] if k == "h2" else _esc(b[1]), st[k])]
        if k == "p":
            return [Paragraph(b[1], st["body"])]
        if k == "small":
            return [Paragraph(b[1], st["small"])]
        if k == "kv":
            return [_kv_table(b[1], st, widths=tuple(w * mm for w in b[2]))]
        if k == "table":
            head, rows, widths = b[1], b[2], b[3]
            data = [[Paragraph(h, st["cellb"]) for h in head]] + [[Paragraph(c, st["cell"]) for c in row] for row in rows]
            t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#D0D5DD")),
                                   ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            return [t]
        if k == "plot":
            drawing, capped = activity_drawing(rec)
            return [drawing, Paragraph(_plot_caption(rec, capped), st["small"])]
        if k == "image":
            return [_jpeg(b[1], b[2]), Paragraph(_esc(b[3]), st["small"])]
        if k == "pair":
            (a, ca), (c, cc) = b[1]
            t = Table([[_jpeg(a, 84), _jpeg(c, 84)], [Paragraph(_esc(ca), st["small"]), Paragraph(_esc(cc), st["small"])]],
                      colWidths=[87 * mm, 87 * mm])
            t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            return [t]
        if k == "keep":
            inner = []
            for x in b[1]:
                inner += conv(x)
            return [KeepTogether(inner)]
        if k == "space":
            return [Spacer(1, b[1] * mm)]
        if k == "pagebreak":
            return [PageBreak()]
        return []

    story = []
    for b in blocks:
        story += conv(b)
    doc = SimpleDocTemplate(out_path, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"Track & Detect report – {title_file}",
                            author=opts.get("analyst") or "Thermal Vision Ecology")

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(18 * mm, 9 * mm, f"Track & Detect {_version_label()} by Thermal Vision Ecology · {title_file}")
        canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def _plot_caption(rec, capped):
    cap_note = (" The vertical axis is capped so that one very tall spike does not hide the others; spikes "
                "above the cap are cut off.") if capped else ""
    roi_note = " Each ROI's trace is drawn in its own colour." if len([r for r in rec.rois if r["id"] in rec.acts]) > 1 else ""
    return ("Figure 1. Highest value inside the ROI in each frame. The dashed blue line is the detection level; "
            "rises above it became events. Shaded bands mark events: green accepted, red rejected, amber not "
            "reviewed." + roi_note + cap_note)


def _kv_table(rows, st, widths=(45 * mm, 127 * mm)):
    data = [[Paragraph(f"<b>{_esc(k)}</b>", st["cell"]), Paragraph(_esc(v), st["cell"])] for k, v in rows]
    t = Table(data, colWidths=list(widths), hAlign="LEFT")
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#E4E7EC")),
                           ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
    return t


# ---------------------------------------------------------------------- Word
def _runs(par, html, size=None, color=None, bold=False):
    """Add simple marked-up text (<b>, <i>, <font color>, &amp;) to a Word paragraph."""
    import re
    from docx.shared import Pt, RGBColor
    state = {"b": bold, "i": False, "c": color}
    stack = []
    for tok in re.split(r"(<[^>]+>)", html or ""):
        if not tok:
            continue
        m = re.match(r"<(/?)(b|i|font)([^>]*)>", tok)
        if m:
            close, tag, attrs = m.groups()
            if tag == "font":
                if close:
                    state["c"] = stack.pop() if stack else color
                else:
                    stack.append(state["c"])
                    cm = re.search(r'color="#?([0-9A-Fa-f]{6})"', attrs)
                    state["c"] = cm.group(1) if cm else state["c"]
            else:
                state[tag] = not close if not close else (bold if tag == "b" else False)
            continue
        text = tok.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        r = par.add_run(text)
        r.bold, r.italic = state["b"], state["i"]
        if size:
            r.font.size = Pt(size)
        if state["c"]:
            r.font.color.rgb = RGBColor.from_string(state["c"].upper())
    return par


def _write_docx(rec, blocks, out_path, opts):
    from docx import Document
    from docx.enum.section import WD_ORIENT  # noqa: F401  (kept for clarity: A4 portrait)
    from docx.enum.text import WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = Mm(18)
    sec.top_margin = sec.bottom_margin = Mm(16)
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10)
    title_file = os.path.basename(rec.path)
    doc.core_properties.title = f"Track & Detect report – {title_file}"
    doc.core_properties.author = opts.get("analyst") or "Thermal Vision Ecology"

    # footer: product line and page number
    fp = sec.footer.paragraphs[0]
    _runs(fp, f"Track &amp; Detect {_version_label()} by Thermal Vision Ecology · {_esc(title_file)} · Page ", size=7.5, color="6B7280")
    run = fp.add_run()
    run.font.size = Pt(7.5)
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar"); el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText"); el.set(qn("xml:space"), "preserve"); el.text = text
        run._r.append(el)

    def shade(cell, hex_fill):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_fill)
        tcPr.append(shd)

    def set_width(cell, w_mm):
        cell.width = Mm(w_mm)

    def picture(container, bgr, width_mm):
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 88])
        container.add_run().add_picture(BytesIO(buf.tobytes()), width=Mm(width_mm))

    def heading(text, size, color="1B4D1E", before=10):
        p = doc.add_paragraph()
        p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(before), Pt(4)
        p.paragraph_format.keep_with_next = True
        _runs(p, text, size=size, color=color, bold=True)
        return p

    def para(html, size=10, color=None):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(3)
        _runs(p, html, size=size, color=color)
        return p

    def table(rows, widths, head=None):
        t = doc.add_table(rows=0, cols=len(widths))
        t.style = "Table Grid"
        t.autofit = False
        if head:
            cells = t.add_row().cells
            for c, h, w in zip(cells, head, widths):
                set_width(c, w); shade(c, "F2F4F7")
                _runs(c.paragraphs[0], h, size=8, bold=True)
        for row in rows:
            cells = t.add_row().cells
            for j, (c, v, w) in enumerate(zip(cells, row, widths)):
                set_width(c, w)
                _runs(c.paragraphs[0], v, size=8.5, bold=(head is None and j == 0))
        for j, w in enumerate(widths):   # Word and LibreOffice both honour column widths set here
            t.columns[j].width = Mm(w)
        doc.add_paragraph().paragraph_format.space_after = Pt(2)
        return t

    def emit(b):
        k = b[0]
        if k == "logo":
            if os.path.exists(LOGO):
                doc.add_paragraph().add_run().add_picture(LOGO, width=Mm(55))
        elif k == "h1":
            heading(_esc(b[1]), 20, color="111111", before=0)
        elif k == "h2":
            heading(b[1], 13)
        elif k == "h3":
            heading(_esc(b[1]), 11, color="111111", before=2)
        elif k == "p":
            para(b[1])
        elif k == "small":
            para(b[1], size=8, color="6B7280")
        elif k == "kv":
            table([[_esc(a), _esc(v)] for a, v in b[1]], b[2])
        elif k == "table":
            table(b[2], b[3], head=b[1])
        elif k == "plot":
            png, capped = activity_png(rec)
            doc.add_paragraph().add_run().add_picture(BytesIO(png), width=Mm(174))
            para(_plot_caption(rec, capped), size=8, color="6B7280")
        elif k == "image":
            picture(doc.add_paragraph(), b[1], b[2])
            para(_esc(b[3]), size=8, color="6B7280")
        elif k == "pair":
            t = doc.add_table(rows=2, cols=2)
            t.autofit = False
            for j, (img, cap) in enumerate(b[1]):
                set_width(t.cell(0, j), 87); set_width(t.cell(1, j), 87)
                picture(t.cell(0, j).paragraphs[0], img, 84)
                _runs(t.cell(1, j).paragraphs[0], _esc(cap), size=8, color="6B7280")
        elif k == "keep":
            for x in b[1]:
                emit(x)
        elif k == "space":
            doc.add_paragraph().paragraph_format.space_after = Pt(b[1] * 1.2)
        elif k == "pagebreak":
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    for b in blocks:
        emit(b)
    doc.save(out_path)


def activity_png(rec, width_px=1740, height_px=700):
    """The activity plot as a picture, for the Word report (same content as
    activity_drawing)."""
    act, src = rec.shown(rec.activity), rec.src
    level = rec.state.get("level")
    evs = rec.state.get("events", [])
    W, H = width_px, height_px
    L, R, T, Bm = 120, 30, 70, 70
    img = np.full((H, W, 3), 255, np.uint8)
    grey, blue = (172, 161, 154), (181, 111, 31)
    cv2.rectangle(img, (L, T), (W - R, H - Bm), (214, 206, 201), 2)
    font = cv2.FONT_HERSHEY_SIMPLEX
    if act is None or not len(act):
        cv2.putText(img, "Not scanned", (L + 20, H // 2), font, 1.0, grey, 2, cv2.LINE_AA)
        ok, buf = cv2.imencode(".png", img)
        return buf.tobytes(), False
    n = len(act)
    lo = float(np.percentile(act, 1))
    hi = float(act.max())
    top = _auto_top([e["peak"] for e in evs], min(lo, level if level is not None else lo))
    capped = top is not None and top < hi
    if capped:
        hi = top
    if level is not None:
        lo, hi = min(lo, level), max(hi, level)
    hi = hi if hi > lo else lo + 1
    lo -= (hi - lo) * 0.03
    pw, ph = W - L - R, H - T - Bm
    fx = lambda f: int(L + f / max(1, n - 1) * pw)
    fy = lambda v: int(H - Bm - (min(v, hi) - lo) / (hi - lo) * ph)
    over = img.copy()
    for e in evs:
        col = STATUS.get(e["status"], STATUS["todo"])[1]
        bgr = (int(col.blue * 255), int(col.green * 255), int(col.red * 255))
        x0, x1 = fx(e["f0"]), max(fx(e["f1"]), fx(e["f0"]) + 3)
        cv2.rectangle(over, (x0, T), (x1, H - Bm), bgr, -1)
        cv2.putText(img, str(e["n"]), ((x0 + x1) // 2 - 8, T - 12), font, 0.7, bgr, 2, cv2.LINE_AA)
    img = cv2.addWeighted(over, 0.15, img, 0.85, 0)
    traces = [(rec.shown(rec.acts[r["id"]]), rec.roi_colour(r["id"])) for r in rec.rois if r["id"] in rec.acts]
    if len(traces) <= 1:
        traces = [(act, "#9AA1AC")]
    for a, hexc in traces:
        h = hexc.lstrip("#")
        bgr = (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))
        edges = np.linspace(0, n, min(pw, n) + 1).astype(int)
        pts = []
        for k in range(len(edges) - 1):
            s, e2 = edges[k], max(edges[k] + 1, edges[k + 1])
            j = s + int(np.argmax(a[s:e2]))
            pts.append((fx(j), fy(float(a[j]))))
        cv2.polylines(img, [np.array(pts, np.int32)], False, bgr, 2, cv2.LINE_AA)
    if level is not None:
        ly = fy(level)
        for x in range(L, W - R, 18):
            cv2.line(img, (x, ly), (min(x + 10, W - R), ly), blue, 3, cv2.LINE_AA)
        txt = f"Detection level {level:.2f} {_unit(src.units).replace('°', '')}"
        (tw, _), _ = cv2.getTextSize(txt, font, 0.7, 2)
        cv2.putText(img, txt, (W - R - tw - 6, ly - 10), font, 0.7, blue, 2, cv2.LINE_AA)
    for v in (lo + (hi - lo) * 0.03, hi):
        cv2.putText(img, f"{v:.1f}", (8, fy(v) + 8), font, 0.6, grey, 1, cv2.LINE_AA)
    for k in range(5):
        f = int(k / 4 * (n - 1))
        cv2.putText(img, src.time_label(f)[:8], (fx(f) - 45, H - Bm + 34), font, 0.6, grey, 1, cv2.LINE_AA)
    cv2.putText(img, f"Maximum in ROI ({_unit(src.units).replace('°', 'deg ')}) against time ({src.zone_of(0) or 'elapsed'})",
                (L, 36), font, 0.7, grey, 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes(), capped
