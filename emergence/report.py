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
    act, src = rec.activity, rec.src
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
    d.add(PolyLine(line, strokeColor=colors.HexColor("#9AA1AC"), strokeWidth=0.6))
    # highlight the parts above the line
    if level is not None:
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


def build_report(rec, out_path, opts=None, progress=None):
    opts = opts or {}
    src = rec.src
    st = _styles()
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

    story = []
    # ------------------------------------------------------------------ cover
    if os.path.exists(LOGO):
        story += [Image(LOGO, width=55 * mm, height=55 * mm * 180 / 665, hAlign="LEFT"), Spacer(1, 6 * mm)]
    story += [Paragraph("Thermal emergence survey: analysis report", st["h1"]),
              Paragraph(f"{_esc(opts.get('location') or site)} · {_esc(title_file)}", st["h3"])]
    if opts.get("company"):
        story.append(Paragraph(f"Prepared for {_esc(opts['company'])}", st["body"]))
    story.append(Spacer(1, 3 * mm))
    t0, t1 = src.time_of(0), src.time_of(src.n_frames - 1)
    info = [
        ["Company", opts.get("company") or "–"],
        ["Company contact", opts.get("contact") or "–"],
        ["Survey location", opts.get("location") or site],
        ["Recording", title_file],
        ["Camera and lens", opts.get("camera") or src.camera or "unknown"],
        ["Date", t0.strftime("%A %d/%m/%Y") if t0 else "not stored in file"],
        [f"Start – end ({zone})", f"{src.time_label(0)[:8]} – {src.time_label(src.n_frames - 1)[:8]}" if t0 else "–"],
        ["Duration", _fmt_dur(src.n_frames / src.fps)],
        ["Image size", f"{src.width} × {src.height} pixels"],
        ["Analyst", opts.get("analyst") or "–"],
        ["Report created", _dt.datetime.now().strftime("%d/%m/%Y, %H:%M")],
    ]
    story.append(_kv_table(info, st))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Summary", st["h2"]))
    cls_count = {}
    for e in evs:
        if e["status"] == "confirmed":
            cls_count[e.get("cls") or "Unclassified"] = cls_count.get(e.get("cls") or "Unclassified", 0) + 1
    ok_times = [e for e in evs if e["status"] == "confirmed"]
    summ = [
        ["Events detected", str(len(evs))],
        ["Accepted", str(n_ok)],
        ["Rejected", str(n_no)],
        ["Not reviewed", str(n_todo)],
    ]
    if ok_times:
        summ += [["First accepted event", f"{src.time_label(ok_times[0]['f0'])[:8]} {src.zone_of(ok_times[0]['f0'])}"],
                 ["Last accepted event", f"{src.time_label(ok_times[-1]['f0'])[:8]} {src.zone_of(ok_times[-1]['f0'])}"]]
    for c, k in sorted(cls_count.items(), key=lambda kv: -kv[1]):
        summ.append([f"Accepted as: {c}", str(k)])
    story.append(_kv_table(summ, st))
    if n_todo:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(f"<b>Note:</b> {n_todo} event{'s' if n_todo != 1 else ''} had not been reviewed when "
                               "this report was created.", st["body"]))

    # ------------------------------------------------------------------ methodology
    story.append(PageBreak())
    story.append(Paragraph("Introduction and methodology", st["h2"]))
    level = rec.state.get("level")
    sugg = rec.state.get("suggested_level")
    paras = [
        f"This report presents the analysis of a thermal imaging recording" + (f" (recorded with {_esc(cam_txt)})" if cam_txt else "") + f" made to survey bat emergence and "
        f"re-entry at <b>{_esc(opts.get('location') or site)}</b>. The recording was analysed with Track &amp; Detect by Thermal Vision "
        "Ecology, which reads the FLIR .ats radiometric recording directly and follows the TVE thermal analysis "
        "method: an automated scan finds moments of movement, and an analyst reviews every one of them.",
        "<b>1. Region of interest (ROI).</b> The analyst drew a region of interest around the roost features "
        "(roofline, eaves, openings and nearby flight lines), excluding open sky where possible. Only this "
        "region is used for detection.",
        "<b>2. Activity scan.</b> Every frame of the recording was processed with a Window Average filter "
        "(3 × 3 pixels, to suppress single-pixel noise) followed by Sliding Subtraction (each frame minus the "
        "frame 5 frames earlier). This removes the stationary scene (buildings, vegetation, sky) so that only "
        "change remains, and a warm, moving animal stands out. The highest value inside the ROI was recorded "
        "for each frame, giving the activity trace shown below.",
        f"<b>3. Detection level.</b> A detection level was set on the activity trace: every rise above it "
        f"becomes an event, and rises within 2 seconds of each other are merged into one event. The level used "
        f"was <b>{level:.2f} {_unit(src.units)}</b>" + (f" (suggested starting level {sugg:.2f}, based on the "
        "recording's background noise)" if sugg is not None else "") + ". Spikes below the level were "
        "not reviewed." if level is not None else "<b>3. Detection level.</b> The recording had not been scanned.",
        f"<b>4. Review.</b> Each event was reviewed by the analyst in a window from 3 seconds before to 3 seconds "
        f"after it, in the plain thermal view and in High Sensitivity Mode (Max Frame Interval {filters['mfi']} "
        f"frames with Sliding Subtraction {filters['ss']} frames, which shows moving animals as bright trails). "
        "Each event was then accepted with a classification, or rejected (for example as an insect, "
        "vegetation movement or noise). Comments record what the analyst observed.",
        "<b>5. Images.</b> For each event this report shows a <i>flight path</i> image (the hottest value of "
        "every pixel across the event window, building up the whole route) and a <i>blended</i> "
        "frame (taken at the event's peak activity for an overlay, or a Max Frame Interval's worth of frames "
        "after activity was first seen for a crossfade): the thermal picture with the High Sensitivity Mode trails "
        "combined with it, so the moving animal can be seen in its setting.",
    ]
    for p in paras:
        story += [Paragraph(p, st["body"]), Spacer(1, 2.2 * mm)]
    story.append(Paragraph("Activity plot", st["h2"]))
    drawing, capped = activity_drawing(rec)
    story.append(drawing)
    cap_note = (" The vertical axis is capped so that one very tall spike does not hide the others; spikes "
                "above the cap are cut off.") if capped else ""
    story.append(Paragraph("Figure 1. Highest value inside the ROI in each frame. The dashed blue line is the "
                           "detection level; rises above it (amber) became events. Shaded bands mark events: "
                           "green accepted, red rejected, amber not reviewed." + cap_note, st["small"]))
    if progress:
        progress(1, len(evs) + 3)

    # ROI overview
    r = Renderer(src)
    r.filters = filters
    mid = evs[0]["f0"] if evs else 0
    story.append(KeepTogether([Paragraph("Region of interest", st["h2"]),
                               _jpeg(r.image(mid, "raw", rec.roi, show_time=True), 120),
                               Paragraph("Figure 2. The region of interest (red outline) used for detection.",
                                         st["small"])]))

    # ------------------------------------------------------------------ event table
    story.append(PageBreak())
    story.append(Paragraph("Events", st["h2"]))
    head = ["#", f"Start ({zone})", "End", "Length", "Peak", "Decision", "Classification", "Comments"]
    rows = [[Paragraph(h, st["cellb"]) for h in head]]
    for e in evs:
        lab, col = STATUS.get(e["status"], STATUS["todo"])
        cm = "; ".join(c["text"] for c in ev_comments(e))
        rows.append([Paragraph(str(e["n"]), st["cell"]), Paragraph(src.time_label(e["f0"])[:8], st["cell"]),
                     Paragraph(src.time_label(e["f1"])[:8], st["cell"]),
                     Paragraph(f"{(e['f1'] - e['f0'] + 1) / src.fps:.1f} s", st["cell"]),
                     Paragraph(f"{e['peak']:.1f}", st["cell"]),
                     Paragraph(f'<font color="{col.hexval().replace("0x", "#")}"><b>{lab}</b></font>', st["cell"]),
                     Paragraph(_esc(e.get("cls") or "–"), st["cell"]), Paragraph(_esc(cm) or "–", st["cell"])])
    if len(rows) == 1:
        rows.append([Paragraph("No events were detected at this level.", st["cell"])] + [""] * 7)
    tbl = Table(rows, colWidths=[8 * mm, 19 * mm, 17 * mm, 14 * mm, 13 * mm, 22 * mm, 34 * mm, 47 * mm],
                repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#D0D5DD")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tbl)

    # ------------------------------------------------------------------ per event
    img_dir = None
    if opts.get("save_images", True):
        img_dir = os.path.splitext(out_path)[0] + "_images"
        os.makedirs(img_dir, exist_ok=True)
    for k, e in enumerate(evs):
        if progress:
            progress(k + 2, len(evs) + 3)
        lab, col = STATUS.get(e["status"], STATUS["todo"])
        block = [Paragraph(f'Event {e["n"]} <font color="{col.hexval().replace("0x", "#")}">· {lab}</font>', st["h2"])]
        details = [
            ["Time", f"{src.time_label(e['f0'])} – {src.time_label(e['f1'])} {src.zone_of(e['f0'])}"],
            ["Frames", f"{e['f0']:,} – {e['f1']:,} ({(e['f1'] - e['f0'] + 1) / src.fps:.1f} s)"],
            ["Peak activity", f"{e['peak']:.2f} {_unit(src.units)} at frame {e['peak_frame']:,}"],
            ["Decision", lab],
            ["Classification", e.get("cls") or "–"],
        ]
        block.append(_kv_table(details, st, widths=(32 * mm, 140 * mm)))
        show_imgs = e["status"] != "rejected" or include_rejected
        if show_imgs:
            ws, we = max(0, e["f0"] - pad), min(src.n_frames - 1, e["f1"] + pad)
            path_img = r.image(we, "path", rec.roi, window_start=ws, palette=opts.get("palette"), enh=opts.get("enh"))
            how, op = opts.get("blend", "overlay"), float(opts.get("opacity", 0.8))
            bf = blend_still_frame(e, how, filters, src.n_frames)
            bf_note = f"first activity + {filters['mfi']} frames" if how == "crossfade" else "peak"
            hs_img = r.image(bf, "blend", rec.roi, window_start=ws, palette=opts.get("palette"),
                             rng=opts.get("blend_range"), opacity=op, blend=how, enh=opts.get("enh"))
            if img_dir:
                base = os.path.join(img_dir, safe_name(f"event{e['n']}_{src.time_label(e['f0'])[:8].replace(':', '-')}"))
                cv2.imwrite(base + "_flightpath.jpg", path_img, [cv2.IMWRITE_JPEG_QUALITY, 92])
                cv2.imwrite(base + f"_blended-{how}_frame{bf}.jpg", hs_img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            imgs = Table([[_jpeg(path_img, 84), _jpeg(hs_img, 84)],
                          [Paragraph(f"Flight path, {src.time_label(ws)[:8]}–{src.time_label(we)[:8]}", st["small"]),
                           Paragraph(f"Blended ({how} {round(op * 100)}%), frame {bf:,} ({bf_note})", st["small"])]],
                         colWidths=[87 * mm, 87 * mm])
            imgs.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            block += [Spacer(1, 2 * mm), imgs]
        cms = ev_comments(e)
        if cms:
            block.append(Spacer(1, 2 * mm))
            block.append(Paragraph("<b>Comments</b>", st["body"]))
            for c in cms:
                block.append(Paragraph(f"{src.time_label(c['frame'])[:8]} (frame {c['frame']:,}): {_esc(c['text'])}",
                                       st["body"]))
        block.append(Spacer(1, 5 * mm))
        story.append(KeepTogether(block))

    other = [c for c in comments if c["id"] not in linked]
    if other:
        story.append(Paragraph("Other comments", st["h2"]))
        story.append(Paragraph("Comments made outside any event window.", st["small"]))
        for c in other:
            story.append(Paragraph(f"{src.time_label(c['frame'])[:8]} {src.zone_of(c['frame'])} (frame "
                                   f"{c['frame']:,}): {_esc(c['text'])}", st["body"]))

    # ------------------------------------------------------------------ appendix
    story.append(Paragraph("Appendix: analysis settings", st["h2"]))
    app_rows = [
        ["Recording file", rec.path],
        ["Scan filters", "Window Average 3 × 3, Sliding Subtraction 5 frames (" + SCAN_ID + ")"],
        ["Activity measure", "Maximum inside ROI per frame"],
        ["Detection level", f"{level:.3f} {_unit(src.units)}" if level is not None else "–"],
        ["End of recording", (f"A very large spike from {src.time_label(rec.end_spike_frame)[:8]} {src.zone_of(rec.end_spike_frame)} to the end "
                              "was left out of the analysis (typically the camera being approached or moved)")
                             if rec.end_spike_frame is not None else "Final frame not used"],
        ["Suggested level", f"{sugg:.3f} {_unit(src.units)}" if sugg is not None else "–"],
        ["Event merge gap", "2 s"],
        ["Review window", "3 s either side of each event"],
        ["High Sensitivity Mode", f"Max Frame Interval {filters['mfi']} frames + Sliding Subtraction {filters['ss']} frames"],
        ["Blended images", ("Crossfade" if opts.get("blend") == "crossfade" else "Overlay")
                           + f" at {round(float(opts.get('opacity', 0.8)) * 100)}% opacity"],
        ["Software", f"Track & Detect {_version_label()}"],
        ["Image clean-up", _enh_text(opts.get("enh"))],
        ["ROI", f"{len(rec.roi)} outline points" if rec.roi else "whole image"],
        ["Times", "UK time (BST in summer, GMT in winter), from the UTC start time stored in the recording"],
        ["Temperature data", "°C" if src.units == "°C" else f"raw {src.units}"],
    ]
    if rec.state.get("scan_id") not in (None, SCAN_ID):
        app_rows.append(["Warning", "This recording was scanned with an earlier version of the scan filters."])
    story.append(_kv_table(app_rows, st, widths=(40 * mm, 132 * mm)))
    if img_dir:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(f"Full-resolution copies of the images are saved in {_esc(img_dir)}.", st["small"]))

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
    if progress:
        progress(len(evs) + 3, len(evs) + 3)
    return out_path


def _kv_table(rows, st, widths=(45 * mm, 127 * mm)):
    data = [[Paragraph(f"<b>{_esc(k)}</b>", st["cell"]), Paragraph(_esc(v), st["cell"])] for k, v in rows]
    t = Table(data, colWidths=list(widths), hAlign="LEFT")
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#E4E7EC")),
                           ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
    return t
