"use strict";
const $ = (s) => document.querySelector(s);
const S = { files: [], rec: null, mode: "raw", frame: 0, sel: null, ws: 0, we: 0,
            drawing: false, pts: [], playing: false, act: [], polling: null, lastJobs: "" };
const MODE_HINT = { review: "Moving animals show as bright trails.",
                    path: "The whole route builds up across the event.",
                    raw: "The original footage, with no filters." };
const MODES_ORDER = ["raw", "review", "path", "blend"];
let CLASSES = ["Emergence", "Re-entry", "Flight through / commuting", "Passes behind structure",
               "Foraging", "Bird", "Insect / noise", "Other"];   // replaced by Settings > Classifications

async function api(url, body) {
  const r = await fetch(url, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) { const t = await r.text(); let m = t; try { m = JSON.parse(t).error || t; } catch (e) {} throw new Error(m.replace(/<[^>]+>/g, " ").trim()); }
  return r.json();
}
function toast(msg, ms = 3500) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), ms); }
function err(e) { console.error(e); toast(e.message || String(e), 6000); }
// UK clock time: BST (UTC+1) from 01:00 UTC on the last Sunday in March to
// 01:00 UTC on the last Sunday in October, GMT otherwise.
function lastSundayUTC(y, m) { const d = new Date(Date.UTC(y, m + 1, 0, 1)); d.setUTCDate(d.getUTCDate() - d.getUTCDay()); return d.getTime(); }
function ukTime(ms) {
  if (S.cfg && S.cfg.units.zone === "utc") return { d: new Date(ms), zone: "UTC" };   // Settings > Time & units
  const y = new Date(ms).getUTCFullYear(), bst = ms >= lastSundayUTC(y, 2) && ms < lastSundayUTC(y, 9);
  return { d: new Date(ms + (bst ? 3600e3 : 0)), zone: bst ? "BST" : "GMT" };
}
function fmtZone(frame) { const r = S.rec; return r && r.start ? ukTime(new Date(r.start).getTime() + frame / r.fps * 1000).zone : ""; }
function fmtDate(frame) {   // dd/mm/yyyy, UK date
  const r = S.rec; if (!r || !r.start) return "";
  const d = ukTime(new Date(r.start).getTime() + frame / r.fps * 1000).d;
  return `${String(d.getUTCDate()).padStart(2, "0")}/${String(d.getUTCMonth() + 1).padStart(2, "0")}/${d.getUTCFullYear()}`;
}
function fmtStamp(frame) { return [fmtDate(frame), fmtTime(frame), fmtZone(frame)].filter(Boolean).join(" "); }
function fmtTime(frame) {
  const r = S.rec; if (!r) return "";
  if (r.start) return ukTime(new Date(r.start).getTime() + frame / r.fps * 1000).d.toISOString().substr(11, 8);
  const s = frame / r.fps; return `+${String(Math.floor(s / 60)).padStart(2, "0")}:${(s % 60).toFixed(1).padStart(4, "0")}`;
}
function fmtDur(s) { const m = Math.floor(s / 60); return `${m}:${String(Math.round(s % 60)).padStart(2, "0")}`; }
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

// ------------------------------------------------------------ recordings list
function parentName(p) { const parts = p.split(/[\\/]/); return parts.slice(-3, -1).join(" › "); }
$("#btn-open").onclick = () => { $("#folder-input").value = ""; $("#pick-msg").hidden = true; $("#dlg-folder").showModal(); };
async function browse(kind) {
  const btns = [$("#btn-browse-files"), $("#btn-browse-folder")], msg = $("#pick-msg");
  btns.forEach((b) => (b.disabled = true));
  msg.hidden = false; msg.className = "small muted";
  msg.textContent = "Opening the Windows chooser… if you can't see it, check the taskbar.";
  try {
    const r = await api("/api/pick", { kind });
    if (!r.paths.length) { msg.textContent = "Nothing chosen."; return; }
    const box = $("#folder-input"); box.value = (box.value.trim() ? box.value.trim() + "\n" : "") + r.paths.join("\n");
    msg.textContent = `${r.paths.length} ${kind === "files" ? "file" : "folder"}${r.paths.length === 1 ? "" : "s"} added below. Click Add to list them.`;
  } catch (e) {
    msg.className = "small err"; msg.textContent = e.message || String(e);
  } finally { btns.forEach((b) => (b.disabled = false)); }
}
$("#btn-browse-files").onclick = () => browse("files");
$("#btn-browse-folder").onclick = () => browse("folder");
$("#dlg-folder").addEventListener("close", async () => {
  if ($("#dlg-folder").returnValue !== "ok") return;
  const paths = $("#folder-input").value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
  if (!paths.length) return;
  try {
    const r = await api("/api/add", { paths, replace: $("#add-replace").checked });
    S.files = r.files; renderFiles();
    if (r.problems && r.problems.length) toast(r.problems.join("; "), 7000);
    if (!S.rec && S.files.length === 1) openRec(S.files[0].path);
  } catch (e) { err(e); }
});
function renderFiles() {
  const box = $("#files"); box.innerHTML = "";
  if (!S.files.length) { box.innerHTML = '<p class="muted small">Add .ats files, or a whole folder of them.</p>'; }
  for (const f of S.files) {
    const w = document.createElement("div"); w.className = "file-wrap";
    const b = document.createElement("button");
    b.className = "file" + (S.rec && S.rec.path === f.path ? " cur" : "");
    b.title = f.path;
    const k = f.status === "Reviewed" ? "ok" : f.status === "In review" ? "todo" : "";
    b.innerHTML = `<span class="file-name">${esc(f.name)}<br><span class="small muted">${esc(parentName(f.path))} · ${f.size_gb} GB</span></span><span class="chip ${k}">${esc(f.status)}</span>`;
    b.onclick = () => openRec(f.path);
    const x = document.createElement("button"); x.className = "rm"; x.textContent = "×";
    x.setAttribute("aria-label", `Remove ${f.name} from the list`);
    x.onclick = async () => { try { const r = await api("/api/remove", { path: f.path }); S.files = r.files; if (S.rec && S.rec.path === f.path) location.reload(); renderFiles(); } catch (e) { err(e); } };
    w.append(b, x); box.appendChild(w);
  }
  $("#btn-scan-all").disabled = !S.files.length;
}
async function refreshFiles() { try { const r = await api("/api/files"); S.files = r.files; renderFiles(); } catch (e) {} }

async function openRec(path) {
  stopPlay();
  $("#empty").textContent = "Opening…";
  try {
    S.rec = await api("/api/open", { path });
    S.rng = { raw: null, review: null, path: null, blend: null }; S.track = {}; S.info = null;   // each recording starts on Auto
    S.frame = 0; S.sel = null; S.ws = 0; S.we = S.rec.frames - 1; S.pts = S.rec.roi || [];
    $("#scrub").max = S.rec.frames - 1;
    $("#crumb-folder").textContent = parentName(S.rec.path);
    $("#crumb-file").textContent = "› " + S.rec.name;
    setCrumbMeta();
    $("#fps-wrap").hidden = false; $("#fps").value = S.rec.fps;
    ["#btn-roi-draw", "#btn-roi-clear", "#btn-scan"].forEach((s) => ($(s).disabled = false));
    $("#empty").hidden = true;
    renderFiles(); updateRoiStatus(); await loadActivity(); renderEvents(); renderComments(); renderFilters(); showFrame();
  } catch (e) { $("#empty").textContent = "Could not open this file."; err(e); }
}
$("#fps").onchange = async () => { try { S.rec = await api("/api/fps", { fps: +$("#fps").value }); renderEvents(); showFrame(); } catch (e) { err(e); } };

// ------------------------------------------------------------ frames
const img = $("#view");
let pending = false, queued = false;
// visible range per viewing mode: null = automatic, otherwise [lo, hi]
S.rng = { raw: null, review: null, path: null, blend: null }; S.track = {}; S.pal = "white"; S.palettes = []; S.evDraft = {};
function frameUrl(i) {
  const r = S.mode === "review" ? null : S.rng[S.mode], q = r ? `&lo=${r[0]}&hi=${r[1]}` : "";
  const op = (S.mode === "blend" ? `&op=${$("#opacity").value}&bm=${$("#blend").value}` : "") + enhQuery();
  return `/api/frame?i=${i}&mode=${S.mode}&ws=${S.ws}&roi=${S.drawing ? 0 : 1}&pal=${S.pal}${q}${op}&t=${Date.now()}`;
}
let frameObjUrl = null;
async function loadFrame(url) {
  try {
    const r = await fetch(url);
    if (!r.ok) throw new Error(r.status);
    const h = (k) => parseFloat(r.headers.get("X-" + k));
    S.info = { lo: h("lo"), hi: h("hi"), autoLo: h("auto-lo"), autoHi: h("auto-hi"), min: h("min"), max: h("max") };
    const u = URL.createObjectURL(await r.blob());
    if (frameObjUrl) URL.revokeObjectURL(frameObjUrl);
    frameObjUrl = u; img.src = u; drawCbar();
  } catch (e) { pending = false; if (S.playing) stopPlay(); }
}
function showFrame() {
  if (!S.rec) return;
  S.frame = Math.max(0, Math.min(S.rec.frames - 1, S.frame | 0));
  if (pending) { queued = true; } else { pending = true; loadFrame(frameUrl(S.frame)); }
  $("#badge-frame").textContent = `${fmtStamp(S.frame)} · frame ${S.frame.toLocaleString()}`;
  $("#scrub").value = S.frame;
  positionCursor();
  $("#loop-wrap").hidden = !S.sel;
  updateCommentBox();
}
img.onload = () => { pending = false; drawRoi(); if (queued) { queued = false; showFrame(); } if (S.playing) S._onFrame && S._onFrame(); };
img.onerror = () => { pending = false; if (S.playing) stopPlay(); };
window.addEventListener("resize", () => { drawRoi(); drawPlot(); });

function setMode(m) {
  S.mode = m;
  document.querySelectorAll(".mode[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === m)));
  $("#btn-persist").classList.toggle("on", m === "review");
  $("#opacity-wrap").hidden = m !== "blend";
  syncEnh();
  showFrame();
}
document.querySelectorAll(".mode[data-mode]").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));
// frame persistence dropdown on the High Sensitivity Mode tab
function togglePersist(open) {
  const m = $("#persist-menu"), want = open ?? m.hidden;
  m.hidden = !want; $("#btn-persist").setAttribute("aria-expanded", String(want));
  if (want) $("#f-mfi").focus();
}
$("#btn-persist").onclick = (e) => { e.stopPropagation(); togglePersist(); };
$("#persist-menu").addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("click", () => togglePersist(false));
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#persist-menu").hidden) { togglePersist(false); $("#btn-persist").focus(); } });
$("#scrub").oninput = () => { stopPlay(); S.frame = +$("#scrub").value; showFrame(); };
$("#btn-step").onclick = () => S.rec && goFrame(S.frame + 1);
$("#btn-step-back").onclick = () => S.rec && goFrame(S.frame - 1);

// playback: frames are requested one after another, so the server keeps filter state
const PLAY_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5v14l11-7z"/></svg>';
const PAUSE_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>';
function playBounds() {
  return S.sel && $("#in-window").checked ? [S.ws, S.we] : [0, S.rec.frames - 1];
}
// play button on each event card: plays that event's window from its start
async function playEvent(n) {
  if (S.playing && S.dir > 0 && S.sel === n) return stopPlay();
  if (S.sel !== n) await selectEvent(n);
  if (S.playing) return;   // auto-play (Settings > Review) already started it
  $("#in-window").checked = true;
  S.frame = S.ws; startPlay(1);
}
function syncEvPlay() {
  document.querySelectorAll("[data-evplay]").forEach((b) => {
    const on = S.playing && S.dir > 0 && S.sel === +b.dataset.evplay;
    b.classList.toggle("on", on); b.innerHTML = on ? PAUSE_ICON : PLAY_ICON;
    b.setAttribute("aria-label", `${on ? "Pause" : "Play"} event ${b.dataset.evplay}`); b.title = on ? "Pause" : "Play this event";
  });
}
function stopPlay() {
  S.playing = false; S.dir = 0; syncEvPlay();
  $("#btn-play").innerHTML = PLAY_ICON; $("#btn-play").setAttribute("aria-label", "Play");
  $("#btn-rev").classList.remove("on");
}
function startPlay(dir) {
  if (!S.rec) return;
  if (S.playing && S.dir === dir) return stopPlay();
  const [lo, hi] = playBounds();
  if (S.frame < lo || S.frame > hi) S.frame = dir > 0 ? lo : hi;
  else if (dir > 0 && S.frame >= hi) S.frame = lo;      // at the end: start again
  else if (dir < 0 && S.frame <= lo) S.frame = hi;
  S.playing = true; S.dir = dir;
  $("#btn-play").innerHTML = dir > 0 ? PAUSE_ICON : PLAY_ICON;
  $("#btn-play").setAttribute("aria-label", dir > 0 ? "Pause" : "Play");
  $("#btn-rev").classList.toggle("on", dir < 0);
  syncEvPlay();
  let t0 = performance.now();
  S._onFrame = () => {
    if (!S.playing) return;
    const wait = Math.max(0, 1000 / (S.rec.fps * +$("#speed").value) - (performance.now() - t0));
    setTimeout(() => {
      if (!S.playing) return;
      const [lo2, hi2] = playBounds();
      if ((S.dir > 0 && S.frame >= hi2) || (S.dir < 0 && S.frame <= lo2)) return stopPlay();
      t0 = performance.now(); S.frame += S.dir; showFrame();
    }, wait);
  };
  showFrame();
}
function goFrame(f) { stopPlay(); S.frame = f; showFrame(); }
$("#btn-play").onclick = () => startPlay(1);
$("#btn-rev").onclick = () => startPlay(-1);
$("#btn-start").onclick = () => S.rec && goFrame(playBounds()[0]);
$("#btn-end").onclick = () => S.rec && goFrame(playBounds()[1]);
$("#in-window").onchange = () => showFrame();

// ------------------------------------------------------------ colour scheme & dark/light mode
function applyLook(scheme, theme) {
  const d = document.documentElement;
  if (scheme) d.dataset.scheme = scheme;
  if (theme) d.dataset.theme = theme;
  try { localStorage.setItem("td-look", JSON.stringify({ scheme: d.dataset.scheme, theme: d.dataset.theme })); } catch (e) {}
  if (S.rec) drawPlot();
}

// ------------------------------------------------------------ palette & visible range
function gradCss(stops, lo, hi) {   // gradient between the handles, flat colour beyond them
  const b = (lo * 100).toFixed(2), t = (hi * 100).toFixed(2), n = stops.length - 1;
  const mid = stops.map((c, k) => `${c} ${(lo + (hi - lo) * k / n) * 100}%`).join(",");
  return `linear-gradient(to top, ${stops[0]} 0%, ${stops[0]} ${b}%, ${mid}, ${stops[n]} ${t}%, ${stops[n]} 100%)`;
}
function cbFmt(v) {
  if (v == null || isNaN(v)) return "";
  const a = Math.abs(v); return a >= 1000 ? v.toFixed(0) : a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : v.toFixed(2);
}
function cbTrack() {   // the slider's full span: fixed while you set your own range, else follows the frame
  const t = S.track[S.mode], i = S.info;
  if (!i) return null;
  if (!S.rng[S.mode] || !t) {
    const pad = (i.max - i.min) * 0.2 || 1;
    S.track[S.mode] = { min: Math.min(i.min, i.lo) - pad, max: Math.max(i.max, i.hi) + pad };
  }
  return S.track[S.mode];
}
function drawCbar() {
  const bar = $("#cbar"); bar.hidden = !S.rec || !S.info;
  if (bar.hidden) return;
  const locked = S.mode === "review";   // High Sensitivity Mode: fixed contrast, nothing to adjust
  bar.classList.toggle("locked", locked);
  bar.title = locked ? "High Sensitivity Mode sets contrast automatically for each frame" : "";
  if (locked) {
    const pal = S.palettes.find((p) => p.id === S.pal);
    if (pal) $("#cb-grad").style.background = gradCss(pal.stops, 0, 1);
    $("#cb-hi").textContent = ""; $("#cb-lo").textContent = ""; $("#cb-unit").textContent = "auto";
    return;
  }
  const t = cbTrack(), i = S.info, span = (t.max - t.min) || 1;
  const fl = Math.max(0, Math.min(1, (i.lo - t.min) / span)), fh = Math.max(0, Math.min(1, (i.hi - t.min) / span));
  const pal = S.palettes.find((p) => p.id === S.pal);
  if (pal) $("#cb-grad").style.background = gradCss(pal.stops, fl, fh);
  $("#cb-top").style.top = (1 - fh) * 100 + "%"; $("#cb-bot").style.top = (1 - fl) * 100 + "%";
  $("#cb-hi").textContent = cbFmt(i.hi); $("#cb-lo").textContent = cbFmt(i.lo);
  const u = isTemp(S.rec.units) ? S.rec.units : "counts";
  $("#cb-unit").textContent = S.mode === "review" ? `change, ${u}` : u;
  $("#cb-auto").setAttribute("aria-pressed", String(!S.rng[S.mode]));
}
function cbDrag(which, e) {
  if (!S.info || S.mode === "review") return;
  e.preventDefault();
  const track = $("#cb-track"), t = cbTrack();
  const cur = S.rng[S.mode] ? [...S.rng[S.mode]] : [S.info.lo, S.info.hi];
  S.track[S.mode] = t;   // freeze the span while dragging
  const move = (ev) => {
    const b = track.getBoundingClientRect();
    const f = Math.max(0, Math.min(1, 1 - (ev.clientY - b.top) / b.height)), v = t.min + f * (t.max - t.min);
    const gap = (t.max - t.min) * 0.01;
    if (which === "top") cur[1] = Math.max(v, cur[0] + gap); else cur[0] = Math.min(v, cur[1] - gap);
    S.rng[S.mode] = [+cur[0].toFixed(4), +cur[1].toFixed(4)];
    S.info = { ...S.info, lo: cur[0], hi: cur[1] }; drawCbar(); showFrame();
  };
  const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
}
$("#cb-top").addEventListener("pointerdown", (e) => cbDrag("top", e));
$("#cb-bot").addEventListener("pointerdown", (e) => cbDrag("bot", e));
for (const [id, end] of [["#cb-top", 1], ["#cb-bot", 0]]) {   // arrow keys nudge a handle
  $(id).addEventListener("keydown", (e) => {
    if (!S.info || S.mode === "review" || !["ArrowUp", "ArrowDown"].includes(e.key)) return;
    e.preventDefault(); e.stopPropagation();
    const t = cbTrack(), step = (t.max - t.min) / 100 * (e.shiftKey ? 5 : 1) * (e.key === "ArrowUp" ? 1 : -1);
    const cur = S.rng[S.mode] ? [...S.rng[S.mode]] : [S.info.lo, S.info.hi];
    cur[end] += step; if (cur[1] <= cur[0]) return;
    S.rng[S.mode] = cur; S.info = { ...S.info, lo: cur[0], hi: cur[1] }; drawCbar(); showFrame();
  });
}
$("#cb-auto").onclick = () => { S.rng[S.mode] = null; showFrame(); };
async function loadPalettes() {
  try {
    const r = await api("/api/palettes"); S.palettes = r.palettes; S.pal = r.current;
    $("#palette").innerHTML = r.palettes.map((p) => `<option value="${p.id}" ${p.id === S.pal ? "selected" : ""}>${esc(p.label)}</option>`).join("");
  } catch (e) {}
}
// Image clean-up: detail enhancement and noise reduction (viewing and exports only)
function enhVals() {
  return { dde: $("#dde-on").checked ? +$("#dde-level").value : 0, tnr: $("#tnr-on").checked ? +$("#tnr-level").value : 0 };
}
function enhQuery() { const e = enhVals(); return `&dde=${e.dde}&tnr=${e.tnr}`; }
function syncEnh() {
  const hsm = S.mode === "review";   // neither applies to High Sensitivity Mode
  $("#enh-wrap").classList.toggle("off", hsm);
  for (const k of ["dde", "tnr"]) { $(`#${k}-on`).disabled = hsm; $(`#${k}-level`).disabled = hsm || !$(`#${k}-on`).checked; }
  $("#enh-wrap").title = hsm ? "Detail enhancement and noise reduction don't apply to High Sensitivity Mode"
    : "Image clean-up for viewing and exports. The scan is never affected.";
}
for (const id of ["#dde-on", "#dde-level", "#tnr-on", "#tnr-level"]) $(id).onchange = () => { syncEnh(); showFrame(); };
syncEnh();

// Blended mode: blend type and opacity
function opacityTitle() {
  $("#opacity-label").title = $("#blend").value === "crossfade"
    ? "0% = thermal only, 100% = High Sensitivity only"
    : "How solid the High Sensitivity trails are over the thermal picture";
}
$("#opacity").onchange = () => showFrame();
$("#blend").onchange = () => { opacityTitle(); showFrame(); };
opacityTitle();
$("#palette").onchange = async () => {
  S.pal = $("#palette").value; showFrame();
  try { await api("/api/palette", { palette: S.pal }); } catch (e) {}
};
loadPalettes();

// The page and the program must be the same version: if the black window is
// still running an older copy, say so instead of failing silently.
const APP_VERSION = "2026.11.09-startover";
(async () => {
  let v = null;
  try { const r = await fetch("/api/version"); if (r.ok) v = (await r.json()).version; } catch (e) {}
  if (v !== APP_VERSION) $("#update-banner").hidden = false;
})();

// ------------------------------------------------------------ ROI drawing
// Shapes: "poly" (click points), "rect" and "ellipse" (drag the middle to
// move, drag an edge or corner handle to resize). All are saved as outlines.
const svg = $("#roi-svg");
S.shape = "poly"; S.hover = null; S.box = null; S.drag = null;
function imgRect() { const r = img.getBoundingClientRect(), s = $("#stage").getBoundingClientRect(); return { x: r.left - s.left, y: r.top - s.top, w: r.width, h: r.height }; }
function toImg(e) {
  const b = svg.getBoundingClientRect();
  return [Math.max(0, Math.min(img.naturalWidth, (e.clientX - b.left) / b.width * img.naturalWidth)),
          Math.max(0, Math.min(img.naturalHeight, (e.clientY - b.top) / b.height * img.naturalHeight))];
}
function defaultBox() { const W = img.naturalWidth, H = img.naturalHeight; return { x0: W * 0.25, y0: H * 0.3, x1: W * 0.75, y1: H * 0.7 }; }
function shapePoints() {
  if (S.shape === "poly") return S.pts.map(([x, y]) => [Math.round(x), Math.round(y)]);
  const { x0, y0, x1, y1 } = S.box;
  if (S.shape === "rect") return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map(([x, y]) => [Math.round(x), Math.round(y)]);
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, rx = Math.abs(x1 - x0) / 2, ry = Math.abs(y1 - y0) / 2;
  return Array.from({ length: 72 }, (_, k) => { const t = k / 72 * 2 * Math.PI; return [Math.round(cx + rx * Math.cos(t)), Math.round(cy + ry * Math.sin(t))]; });
}
const HANDLES = { nw: [0, 0], n: [0.5, 0], ne: [1, 0], e: [1, 0.5], se: [1, 1], s: [0.5, 1], sw: [0, 1], w: [0, 0.5] };
function drawRoi() {
  const r = imgRect(); if (!img.naturalWidth) return;
  Object.assign(svg.style, { left: r.x + "px", top: r.y + "px", width: r.w + "px", height: r.h + "px" });
  svg.setAttribute("viewBox", `0 0 ${img.naturalWidth} ${img.naturalHeight}`);
  if (!S.drawing) { svg.innerHTML = ""; return; }
  const hr = img.naturalWidth / 110, st = 'stroke="#E5484D" stroke-width="2" vector-effect="non-scaling-stroke"';
  let h = "";
  if (S.shape === "poly") {
    const p = S.pts.map((q) => q.join(",")).join(" ");
    h += `<polygon points="${p}" fill="rgba(229,72,77,.12)" stroke="none"/>`;
    h += `<polyline points="${p}" fill="none" ${st}/>`;
    if (S.hover && S.pts.length) {   // live line from the last point to the cursor, and back to the start
      const [lx, ly] = S.pts[S.pts.length - 1], [hx, hy] = S.hover;
      h += `<line x1="${lx}" y1="${ly}" x2="${hx}" y2="${hy}" ${st}/>`;
      if (S.pts.length >= 2) h += `<line x1="${hx}" y1="${hy}" x2="${S.pts[0][0]}" y2="${S.pts[0][1]}" stroke="#E5484D" stroke-width="1.5" stroke-dasharray="6 5" opacity=".7" vector-effect="non-scaling-stroke"/>`;
    }
    h += S.pts.map((q, k) => `<circle cx="${q[0]}" cy="${q[1]}" r="${k ? hr * 0.6 : hr * 0.85}" fill="${k ? "#E5484D" : "#fff"}" stroke="#E5484D" stroke-width="2" vector-effect="non-scaling-stroke"/>`).join("");
  } else {
    const { x0, y0, x1, y1 } = S.box, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const body = S.shape === "rect"
      ? `<rect data-body="1" x="${Math.min(x0, x1)}" y="${Math.min(y0, y1)}" width="${Math.abs(x1 - x0)}" height="${Math.abs(y1 - y0)}"`
      : `<ellipse data-body="1" cx="${cx}" cy="${cy}" rx="${Math.abs(x1 - x0) / 2}" ry="${Math.abs(y1 - y0) / 2}"`;
    h += `${body} fill="rgba(229,72,77,.14)" ${st} style="cursor:move"/>`;
    if (S.shape === "ellipse") h += `<rect x="${Math.min(x0, x1)}" y="${Math.min(y0, y1)}" width="${Math.abs(x1 - x0)}" height="${Math.abs(y1 - y0)}" fill="none" stroke="#E5484D" stroke-width="1" stroke-dasharray="4 4" opacity=".5" vector-effect="non-scaling-stroke" pointer-events="none"/>`;
    const cur = { nw: "nwse", se: "nwse", ne: "nesw", sw: "nesw", n: "ns", s: "ns", e: "ew", w: "ew" };
    for (const [k, [fx, fy]] of Object.entries(HANDLES)) {
      const x = x0 + (x1 - x0) * fx, y = y0 + (y1 - y0) * fy;
      h += `<rect data-h="${k}" x="${x - hr}" y="${y - hr}" width="${hr * 2}" height="${hr * 2}" rx="${hr * 0.3}" fill="#fff" stroke="#E5484D" stroke-width="2" vector-effect="non-scaling-stroke" style="cursor:${cur[k]}-resize"/>`;
    }
  }
  svg.innerHTML = h;
}
svg.addEventListener("pointerdown", (e) => {
  if (!S.drawing || S.shape === "poly") return;
  const t = e.target, p = toImg(e);
  if (t.dataset.h) S.drag = { kind: t.dataset.h, p0: p, b0: { ...S.box } };
  else if (t.dataset.body) S.drag = { kind: "move", p0: p, b0: { ...S.box } };
  else { S.drag = { kind: "new", p0: p, b0: { x0: p[0], y0: p[1], x1: p[0], y1: p[1] } }; S.box = { ...S.drag.b0 }; }   // drag out a new shape
  svg.setPointerCapture(e.pointerId); e.preventDefault();
});
svg.addEventListener("pointermove", (e) => {
  if (!S.drawing) return;
  const p = toImg(e);
  if (S.shape === "poly") { S.hover = p; drawRoi(); return; }
  if (!S.drag) return;
  const d = S.drag, dx = p[0] - d.p0[0], dy = p[1] - d.p0[1], b = { ...d.b0 }, W = img.naturalWidth, H = img.naturalHeight;
  if (d.kind === "move") {
    const w = b.x1 - b.x0, hh = b.y1 - b.y0;
    b.x0 = Math.max(0, Math.min(W - w, b.x0 + dx)); b.y0 = Math.max(0, Math.min(H - hh, b.y0 + dy)); b.x1 = b.x0 + w; b.y1 = b.y0 + hh;
  } else if (d.kind === "new") { b.x1 = p[0]; b.y1 = p[1]; }
  else {
    if (d.kind.includes("w")) b.x0 = p[0]; if (d.kind.includes("e")) b.x1 = p[0];
    if (d.kind.includes("n")) b.y0 = p[1]; if (d.kind.includes("s")) b.y1 = p[1];
  }
  S.box = b; drawRoi();
});
svg.addEventListener("pointerup", () => {
  if (!S.drag) return;
  const b = S.box;   // keep edges in order and the shape a sensible size
  S.box = { x0: Math.min(b.x0, b.x1), y0: Math.min(b.y0, b.y1), x1: Math.max(b.x0, b.x1), y1: Math.max(b.y0, b.y1) };
  if (S.box.x1 - S.box.x0 < 8 || S.box.y1 - S.box.y0 < 8) S.box = S.drag.b0.x1 - S.drag.b0.x0 >= 8 ? S.drag.b0 : defaultBox();
  S.drag = null; drawRoi();
});
svg.addEventListener("pointerleave", () => { if (S.shape === "poly") { S.hover = null; drawRoi(); } });
svg.addEventListener("click", (e) => {
  if (!S.drawing || S.shape !== "poly") return;
  S.pts.push(toImg(e).map(Math.round)); drawRoi();
});
function setShape(sh) {
  S.shape = sh; if (sh !== "poly" && !S.box) S.box = defaultBox();
  document.querySelectorAll("[data-shape]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.shape === sh)));
  $("#btn-roi-undo").hidden = !S.drawing || sh !== "poly";
  $("#roi-hint").textContent = sh === "poly" ? "Click to add points around the roost features. Backspace removes the last one, Enter finishes."
    : "Drag the middle to move it, drag a handle to resize, or drag on the picture to draw a new one.";
  drawRoi();
}
document.querySelectorAll("[data-shape]").forEach((b) => (b.onclick = () => setShape(b.dataset.shape)));
$("#btn-roi-draw").onclick = () => {
  S.drawing = true; S.pts = []; S.box = null; S.hover = null;
  $("#stage").classList.add("drawing"); toggleRoiButtons(); setMode("raw"); setShape(S.shape);
};
$("#btn-roi-undo").onclick = () => { S.pts.pop(); drawRoi(); };
async function finishRoi() {
  const pts = shapePoints();
  if (pts.length < 3) return toast("Add at least 3 points first.");
  S.drawing = false; S.hover = null; $("#stage").classList.remove("drawing"); toggleRoiButtons();
  try { S.rec = await api("/api/roi", { points: pts, all_files: $("#roi-all").checked }); updateRoiStatus(); refreshFiles(); showFrame(); toast("ROI saved. Press Scan recording."); }
  catch (e) { err(e); }
}
$("#btn-roi-done").onclick = finishRoi;
$("#btn-roi-cancel").onclick = () => { S.drawing = false; S.hover = null; $("#stage").classList.remove("drawing"); toggleRoiButtons(); showFrame(); };
document.addEventListener("keydown", (e) => {
  if (!S.drawing || e.target.closest("input, select, textarea, dialog")) return;
  if (e.key === "Enter") { e.preventDefault(); finishRoi(); }
  else if (e.key === "Backspace" && S.shape === "poly") { e.preventDefault(); S.pts.pop(); drawRoi(); }
  else if (e.key === "Escape") $("#btn-roi-cancel").click();
}, true);
$("#btn-roi-clear").onclick = async () => { try { S.pts = []; S.rec = await api("/api/roi", { points: [] }); updateRoiStatus(); showFrame(); } catch (e) { err(e); } };
function toggleRoiButtons() {
  $("#btn-roi-done").hidden = $("#btn-roi-cancel").hidden = $("#roi-tools").hidden = !S.drawing;
  $("#btn-roi-undo").hidden = !S.drawing || S.shape !== "poly";
  $("#btn-roi-draw").hidden = $("#btn-roi-clear").hidden = S.drawing;
}
function updateRoiStatus() { const n = (S.rec && S.rec.roi || []).length; $("#roi-status").textContent = n ? `ROI set (${n} points).` : "No ROI yet: draw around the roost features."; }

// ------------------------------------------------------------ scan, jobs
$("#btn-scan").onclick = () => startScan(false);
$("#btn-scan-all").onclick = () => startScan(true);
async function startScan(all) {
  if (!S.rec && !all) return;
  try {
    const r = await api("/api/scan", { all });
    if (!r.jobs.length) return toast("Draw an ROI first. Tick 'Use this ROI for every listed file' to share it.");
    toast(`Scanning ${r.jobs.length} recording${r.jobs.length > 1 ? "s" : ""}…`); pollJobs();
  } catch (e) { err(e); }
}
$("#btn-cancel").onclick = () => api("/api/jobs/cancel", {}).catch(err);
// Start over: undo all decisions on this recording and scan it again
$("#btn-start-over").onclick = () => {
  if (!S.rec) return;
  const evs = S.rec.events || [], done = evs.filter((e) => e.status !== "todo").length, nc = (S.rec.comments || []).length;
  $("#so-name").textContent = S.rec.name;
  $("#so-count").textContent = `${done} of ${evs.length} event${evs.length === 1 ? "" : "s"} decided`;
  $("#so-ncom").textContent = `${nc} comment${nc === 1 ? "" : "s"}`;
  $("#so-comments").checked = false; $("#so-level").checked = true;
  $("#dlg-start-over").showModal();
};
$("#so-go").onclick = async () => {
  $("#so-go").disabled = true;
  try {
    stopPlay();
    const r = await api("/api/start-over", { delete_comments: $("#so-comments").checked, reset_level: $("#so-level").checked });
    S.rec = r.recording; S.sel = null;
    $("#dlg-start-over").close();
    renderEvents(); renderComments(); refreshFiles(); showFrame();
    if (r.jobs.length) { toast("Decisions cleared. Scanning again…"); pollJobs(); }
    else toast("Decisions cleared. Draw an ROI to scan again.");
  } catch (e) { err(e); } finally { $("#so-go").disabled = false; }
};
function pollJobs() {
  if (S.polling) return;
  S.polling = setInterval(async () => {
    let r; try { r = await api("/api/jobs"); } catch (e) { return; }
    const active = r.jobs.filter((j) => j.state === "queued" || j.state === "running");
    const recent = r.jobs.slice(-6).reverse();
    $("#jobs-panel").hidden = !recent.length;
    $("#jobs").innerHTML = recent.map((j) => {
      const pct = j.state === "done" ? 100 : Math.round(100 * j.done / Math.max(1, j.total));
      const st = j.state === "error" ? `Failed: ${esc(j.error)}` : j.state === "running" ? pct + "%" : j.state;
      return `<div class="job"><span>${esc(j.label)} · <span class="muted">${st}</span></span><div class="bar"><i style="width:${pct}%"></i></div></div>`;
    }).join("");
    const sig = r.jobs.map((j) => j.id + j.state).join();
    if (sig !== S.lastJobs) {
      S.lastJobs = sig; refreshFiles();
      S.watch = S.watch || new Set();   // only announce jobs this page saw running
      for (const j of r.jobs) if (j.state === "queued" || j.state === "running") S.watch.add(j.id);
      for (const j of r.jobs) {
        if (j.state !== "done" || !j.result || !S.watch.has(j.id)) continue;
        S.watch.delete(j.id);
        if (j.result.report) { toast("Report saved: " + j.result.report, 8000); api("/api/open-path", { path: j.result.report }).catch(() => {}); }
        else if (j.result.files) toast(`Saved ${j.result.files.length} files to the exports folder.`);
      }
      if (S.rec) { try { const rec = await api("/api/recording"); const sigOf = (x) => JSON.stringify([x.scanned, x.level, x.suggested_level, (x.events || []).map((e) => [e.f0, e.f1, e.status])]);
            const changed = sigOf(rec) !== sigOf(S.rec); S.rec = rec; renderFilters(); if (changed) { await loadActivity(true); renderEvents(); } } catch (e) {} }
    }
    if (!active.length) { clearInterval(S.polling); S.polling = null; }
  }, 700);
}

// ------------------------------------------------------------ activity plot
// View = frames a..b. Data for the view is fetched at screen resolution, so
// zooming in shows every frame. The blue line is the detection level.
const P = { a: 0, b: 0, data: [], level: null, suggested: null, drag: null, fetchId: 0, units: "", cap: null, yMode: "auto", range: null, capTop: null };
const plotBox = $("#plot"), plotCanvas = $("#plot-canvas");

async function loadActivity(keepView) {
  if (!S.rec) return;
  if (!keepView) { P.a = 0; P.b = S.rec.frames - 1; P.cap = null; }
  await fetchView();
  const has = P.data.length > 0;
  $("#level").disabled = !has; $("#btn-level-reset").disabled = !has; $("#level-slider").disabled = !has;
  $("#btn-start-over").disabled = !has;
}
async function fetchView() {
  if (!S.rec) return;
  const id = ++P.fetchId;
  const pts = Math.max(200, Math.round(plotBox.clientWidth * (window.devicePixelRatio || 1)));
  try {
    const r = await api(`/api/activity?a=${P.a}&b=${P.b}&points=${pts}`);
    if (id !== P.fetchId) return;
    P.data = r.values; P.units = r.units; P.range = r.range;
    if (P.drag?.kind !== "level") { P.level = r.level; P.suggested = r.suggested_level; }
  } catch (e) { P.data = []; }
  updateLevelInputs(); drawPlot();
}
let fetchTimer = null;
function fetchSoon() { clearTimeout(fetchTimer); fetchTimer = setTimeout(fetchView, 120); drawPlot(); }

// Spikes in view: every stretch that rises clearly above the noise floor, not
// only detected events, so smaller spikes below the line count too.
function endCut() { return S.rec && S.rec.end_spike != null ? S.rec.end_spike : null; }
function viewStats() {
  const cut = endCut();   // a large spike at the end that's being ignored doesn't set the scale
  let pts = cut == null ? P.data : P.data.filter((d) => d[0] < cut);
  if (!pts.length) pts = P.data;
  const vals = pts.map((d) => d[1]);
  const s = [...vals].sort((x, y) => x - y);
  const med = s[Math.floor(s.length / 2)];
  const mad = [...vals.map((v) => Math.abs(v - med))].sort((x, y) => x - y)[Math.floor(s.length / 2)] * 1.4826;
  const thr = med + Math.max(4 * mad, (s[s.length - 1] - med) * 0.02);
  const peaks = []; let cur = null;
  for (const v of vals) {
    if (v > thr) cur = Math.max(cur ?? -Infinity, v);
    else if (cur != null) { peaks.push(cur); cur = null; }
  }
  if (cur != null) peaks.push(cur);
  return { s, lo: s[Math.floor(s.length * 0.01)], max: s[s.length - 1], med, noise: mad, peaks };
}
// When one or a few spikes tower over the rest, a top that keeps the others
// clear: drop peaks more than 2x taller than the next one down (up to a
// quarter of the spikes in view) and sit just above the tallest remaining.
function autoTop(peaks, base) {
  const hs = peaks.map((p) => p - base).filter((h) => h > 0).sort((x, y) => y - x);
  if (hs.length < 2) return null;
  const maxDrop = Math.max(1, Math.floor(hs.length * 0.25));
  let k = 0;
  for (let i = 0; i < maxDrop && i < hs.length - 1; i++) if (hs[i] > 2 * hs[i + 1]) k = i + 1;
  return k ? base + hs[k] * 1.12 : null;
}
function yRange() {
  if (!P.data.length) return [0, 1];
  const st = viewStats(); P.stats = st;
  let lo = st.lo, hi = st.max;
  P.capTop = P.yMode === "manual" ? P.cap : P.yMode === "auto" ? autoTop(st.peaks, Math.min(lo, P.level ?? lo)) : null;
  P.capped = P.capTop != null && P.capTop < hi;
  if (P.capped) hi = P.capTop;
  if (P.level != null) { lo = Math.min(lo, P.level); hi = Math.max(hi, P.level); }
  if (hi <= lo) hi = lo + 1;
  return [P.yMode === "log" ? lo - (st.noise || (hi - lo) * 0.001) : lo - (hi - lo) * 0.02, hi];
}
function geom() {
  const dpr = window.devicePixelRatio || 1, W = plotBox.clientWidth, H = plotBox.clientHeight;
  const top = 34, bot = 8, [lo, hi] = yRange();
  const log = P.yMode === "log";
  // log scale measured in multiples of the noise, so the baseline is squeezed
  // and big spikes are pulled down to sit alongside small ones
  const u = Math.max((P.stats && P.stats.noise) || 0, (hi - lo) / 2000, 1e-6);
  const tf = (v) => log ? Math.log10(1 + Math.max(0, v - lo) / u) : v - lo;
  const span = tf(hi) || 1;
  return {
    dpr, W, H, lo, hi, log, u,
    x: (f) => (f - P.a) / Math.max(1, P.b - P.a) * W,
    f: (x) => P.a + x / W * (P.b - P.a),
    y: (v) => top + (H - top - bot) * (1 - tf(v) / span),
    v: (y) => { const t = (1 - (y - top) / (H - top - bot)) * span; return log ? lo + u * (Math.pow(10, t) - 1) : lo + t; },
  };
}
function niceTicks(lo, hi, n) {
  const step0 = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(step0))), r = step0 / mag;
  const step = (r < 1.5 ? 1 : r < 3.5 ? 2 : r < 7.5 ? 5 : 10) * mag, out = [];
  for (let v = Math.ceil(lo / step) * step; v < hi; v += step) out.push(v);
  return out;
}
// colours for the canvas plot come from the stylesheet, so they follow the scheme and mode
function cssv(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function drawPlot() {
  const g = geom(), c = plotCanvas, ctx = c.getContext("2d");
  c.width = g.W * g.dpr; c.height = g.H * g.dpr; ctx.setTransform(g.dpr, 0, 0, g.dpr, 0, 0);
  ctx.clearRect(0, 0, g.W, g.H); $("#markers").innerHTML = "";
  const tag = $("#level-tag");
  if (!S.rec || !P.data.length) {
    ctx.fillStyle = cssv("--muted"); ctx.font = "12px sans-serif"; ctx.fillText(S.rec ? "Not scanned yet" : "", 12, 24);
    $("#plot-axis").innerHTML = ""; $("#plot-range").textContent = ""; tag.hidden = true; return;
  }
  // ignored spike at the end of the recording: grey hatching
  const cut = endCut();
  if (cut != null && g.x(cut) < g.W) {
    const x0 = Math.max(0, g.x(cut));
    ctx.save(); ctx.fillStyle = cssv("--plot-hatch-bg"); ctx.fillRect(x0, 0, g.W - x0, g.H);
    ctx.beginPath(); ctx.rect(x0, 0, g.W - x0, g.H); ctx.clip();
    ctx.strokeStyle = cssv("--plot-hatch"); ctx.lineWidth = 1;
    for (let x = x0 - g.H; x < g.W; x += 9) { ctx.beginPath(); ctx.moveTo(x, g.H); ctx.lineTo(x + g.H, 0); ctx.stroke(); }
    ctx.restore();
    if (g.W - x0 > 150) { ctx.fillStyle = cssv("--plot-note"); ctx.font = "11px sans-serif"; ctx.fillText("Ignored: end of recording", x0 + 6, 52); }
  }
  // event windows shaded
  for (const e of S.rec.events) {
    const x0 = g.x(e.f0), x1 = Math.max(g.x(e.f1), x0 + 2);
    if (x1 < 0 || x0 > g.W) continue;
    ctx.fillStyle = S.sel === e.n ? cssv("--plot-sel") : cssv("--plot-ev");
    ctx.fillRect(x0, 0, x1 - x0, g.H);
  }
  // gridlines with values
  {
    let ticks;
    if (g.log) {   // round heights above the baseline: 1, 2, 5, 10, 20, 50 … steps
      const m = Math.pow(10, Math.floor(Math.log10(g.u))), base = P.stats ? P.stats.med : g.lo;
      ticks = []; let lastY = Infinity;
      for (let k = 0; k < 12; k++) for (const r of [1, 2, 5]) {
        const v = base + r * m * Math.pow(10, k), y = g.y(v);
        if (v >= g.hi) continue;
        if (lastY - y >= 26) { ticks.push(v); lastY = y; }
      }
    } else ticks = niceTicks(g.lo, g.hi, 4);
    ctx.font = "11px " + getComputedStyle(document.body).getPropertyValue("--mono");
    for (const v of ticks) {
      const y = g.y(v); if (y < 62 || y > g.H - 24) continue;
      ctx.strokeStyle = cssv("--plot-grid"); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(g.W, y); ctx.stroke();
      ctx.fillStyle = cssv("--plot-label"); ctx.fillText(fmtVal(v), 6, y - 3);
    }
  }
  // trace: brand green above the line, grey below
  const path = new Path2D();
  const clipped = [];
  P.data.forEach(([f, v], k) => {
    const x = g.x(f), y = g.y(Math.min(v, g.hi));
    if (v > g.hi && P.capped) clipped.push(x);
    k ? path.lineTo(x, y) : path.moveTo(x, y);
  });
  const ly = P.level != null ? g.y(P.level) : -1;
  ctx.lineWidth = 1.3;
  ctx.save(); ctx.beginPath(); ctx.rect(0, 0, g.W, Math.max(0, ly)); ctx.clip(); ctx.strokeStyle = cssv("--accent"); ctx.stroke(path); ctx.restore();
  ctx.save(); ctx.beginPath(); ctx.rect(0, Math.max(0, ly), g.W, g.H); ctx.clip(); ctx.strokeStyle = cssv("--plot-lo"); ctx.stroke(path); ctx.restore();
  // spikes cut off by the cap: small arrows at the top
  if (clipped.length) {
    ctx.fillStyle = cssv("--accent"); let last = -99;
    for (const x of clipped) {
      if (x - last < 7) continue; last = x;
      ctx.beginPath(); ctx.moveTo(x - 4, 40); ctx.lineTo(x + 4, 40); ctx.lineTo(x, 34); ctx.closePath(); ctx.fill();
    }
  }
  // detection line
  if (P.level != null) {
    ctx.strokeStyle = cssv("--blue"); ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
    ctx.beginPath(); ctx.moveTo(0, ly); ctx.lineTo(g.W, ly); ctx.stroke(); ctx.setLineDash([]);
    tag.hidden = false; tag.style.top = ly + "px";
    const n = S.rec.events.length;
    tag.textContent = `Detection level ${fmtVal(P.level)} · ${n} event${n === 1 ? "" : "s"}`;
  }
  // y labels
  ctx.fillStyle = cssv("--muted"); ctx.font = "11px " + getComputedStyle(document.body).getPropertyValue("--mono");
  ctx.fillText(fmtVal(g.hi) + (P.capped ? "  (capped)" : ""), 6, 50); ctx.fillText(fmtVal(g.lo), 6, g.H - 12);
  // markers
  for (const e of S.rec.events) {
    const x = g.x((e.f0 + e.f1) / 2); if (x < -10 || x > g.W + 10) continue;
    const m = document.createElement("button");
    m.className = "marker" + (S.sel === e.n ? " sel" : "") + (e.status === "confirmed" ? " ok" : e.status === "rejected" ? " no" : "");
    m.style.left = x + "px"; m.textContent = e.n;
    m.setAttribute("aria-label", `Event ${e.n} at ${fmtTime(e.f0)}`);
    m.onpointerdown = (ev) => ev.stopPropagation();
    m.onclick = (ev) => { ev.stopPropagation(); selectEvent(e.n); };
    $("#markers").appendChild(m);
  }
  const ticks = 5;
  $("#plot-axis").innerHTML = Array.from({ length: ticks }, (_, k) => `<span>${fmtTime(Math.round(P.a + k / (ticks - 1) * (P.b - P.a)))}</span>`).join("");
  const whole = P.a === 0 && P.b === S.rec.frames - 1;
  $("#plot-range").textContent = whole ? "whole recording" : `${fmtTime(P.a)}–${fmtTime(P.b)} · frames ${P.a.toLocaleString()}–${P.b.toLocaleString()}`;
  syncPlotSliders(g, clipped.length);
  positionCursor();
}
function isTemp(u) { return u === "°C" || u === "°F"; }
function fmtVal(v) { return v == null ? "" : (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)) + (isTemp(P.units) ? " " + P.units : ""); }
function positionCursor() {
  if (!S.rec) return;
  const g = geom(), x = g.x(S.frame);
  const cur = $("#cursor"); cur.style.display = x < 0 || x > g.W ? "none" : "block"; cur.style.left = x + "px";
}
function updateLevelInputs() {
  $("#level-unit").textContent = P.units ? `(${P.units})` : "";
  const sl = $("#level-slider");
  if (P.range) {
    const [lo, hi] = P.range, top = Math.max(hi, P.level ?? hi);
    sl.min = lo; sl.max = top; sl.step = Math.max((top - lo) / 500, 0.001);
    if (P.level != null && document.activeElement !== sl) sl.value = P.level;
  }
  if (P.level != null && document.activeElement !== $("#level")) $("#level").value = (+P.level).toFixed(2);
  $("#level-info").textContent = P.suggested != null ? `Suggested for this recording: ${fmtVal(P.suggested)}. Or drag the blue line on the plot.` : "Or drag the blue line on the plot.";
}

// zoom & pan
function zoom(factor, centreFrame) {
  if (!S.rec) return;
  const n = S.rec.frames, span = P.b - P.a;
  const c = centreFrame ?? (P.a + P.b) / 2;
  let ns = Math.max(48, Math.min(n - 1, Math.round(span * factor)));
  let a = Math.round(c - (c - P.a) / span * ns);
  a = Math.max(0, Math.min(n - 1 - ns, a));
  P.a = a; P.b = a + ns; fetchSoon();
}
plotBox.addEventListener("wheel", (e) => {
  if (!S.rec) return; e.preventDefault();
  const b = plotBox.getBoundingClientRect();
  zoom(e.deltaY > 0 ? 1.3 : 1 / 1.3, geom().f(e.clientX - b.left));
}, { passive: false });
$("#btn-zoom-in").onclick = () => zoom(1 / 1.6, S.frame >= P.a && S.frame <= P.b ? S.frame : undefined);
$("#btn-zoom-out").onclick = () => zoom(1.6);
$("#btn-zoom-fit").onclick = () => { if (!S.rec) return; P.a = 0; P.b = S.rec.frames - 1; fetchSoon(); };
function setYMode(m) { P.yMode = m; if (m !== "manual") P.cap = null; drawPlot(); }
document.querySelectorAll("[data-y]").forEach((b) => (b.onclick = () => setYMode(b.dataset.y)));
$("#btn-enlarge").onclick = () => {
  const big = $("#plot-panel").classList.toggle("big");
  $("#btn-enlarge").setAttribute("aria-pressed", String(big)); $("#btn-enlarge").textContent = big ? "Smaller" : "Enlarge";
  setTimeout(fetchView, 50);
};

// time-window and cap sliders
function syncPlotSliders(g, nClipped) {
  const n = S.rec.frames, ta = $("#t-a"), tb = $("#t-b");
  ta.max = tb.max = n - 1;
  ta.value = P.a; tb.value = P.b;
  const fill = $("#t-fill"), fa = P.a / Math.max(1, n - 1), fb = P.b / Math.max(1, n - 1);  // thumbs are 16px wide
  fill.style.left = `calc(8px + (100% - 16px) * ${fa})`; fill.style.width = `calc((100% - 16px) * ${fb - fa})`;
  $("#t-label").textContent = `${fmtTime(P.a)} → ${fmtTime(P.b)} (${fmtDur((P.b - P.a) / S.rec.fps)})`;
  const c = $("#plot-cap");
  if (P.range) {
    const [lo, hi] = P.range;
    const cmin = Math.min(hi, Math.max(lo, P.level ?? lo));   // never cap below the detection line
    if (P.yMode === "manual" && P.cap < cmin) P.cap = cmin;
    c.min = cmin; c.max = hi; c.step = Math.max((hi - lo) / 500, 0.001); c.disabled = false;
    c.value = P.capped ? P.capTop : hi;  // far right = full height
  }
  const nTall = P.capped && P.stats ? P.stats.peaks.filter((p) => p > P.capTop).length : 0;
  $("#cap-label").textContent =
    P.yMode === "auto" ? (P.capped ? `${nTall} very tall spike${nTall === 1 ? "" : "s"} cut off (▲) so the rest are clear` : "No spike dwarfs the others here, so nothing is cut off. Try Log.")
    : P.yMode === "full" ? "Everything shown at full height."
    : P.yMode === "log" ? "Log scale: tall spikes are squeezed down so small ones stay visible."
    : `Capped at ${fmtVal(P.cap)}${nClipped ? " · taller spikes cut off (▲)" : ""}`;
  document.querySelectorAll("[data-y]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.y === P.yMode)));
}
function timeSlider(which) {
  const n = S.rec.frames, minSpan = Math.min(48, n - 1);
  let a = +$("#t-a").value, b = +$("#t-b").value;
  if (which === "a") a = Math.min(a, b - minSpan); else b = Math.max(b, a + minSpan);
  a = Math.max(0, a); b = Math.min(n - 1, b);
  $("#t-a").value = a; $("#t-b").value = b; P.a = a; P.b = b; fetchSoon();
}
$("#t-a").oninput = () => S.rec && timeSlider("a");
$("#t-b").oninput = () => S.rec && timeSlider("b");
$("#t-fill").addEventListener("pointerdown", (e) => {   // drag the shaded middle to slide the window
  if (!S.rec) return; e.preventDefault();
  const track = $("#t-track").getBoundingClientRect(), x0 = e.clientX, a0 = P.a, span = P.b - P.a, n = S.rec.frames;
  const move = (ev) => { const df = Math.round((ev.clientX - x0) / track.width * (n - 1)); P.a = Math.max(0, Math.min(n - 1 - span, a0 + df)); P.b = P.a + span; fetchSoon(); };
  const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
});
$("#plot-cap").oninput = () => {
  if (!P.range) return;
  const v = +$("#plot-cap").value;
  if (v >= P.range[1] - 1e-9) setYMode("full"); else { P.cap = v; setYMode("manual"); }
};

// pointer: drag the line, drag to pan, click to jump
plotBox.addEventListener("pointermove", (e) => {
  if (!S.rec || !P.data.length) return;
  const b = plotBox.getBoundingClientRect(), g = geom(), y = e.clientY - b.top, x = e.clientX - b.left;
  if (!P.drag) { plotBox.classList.toggle("on-line", P.level != null && Math.abs(y - g.y(P.level)) < 8); return; }
  if (P.drag.kind === "level") { P.level = Math.max(g.lo, g.v(y)); $("#level").value = P.level.toFixed(2); $("#level-slider").value = P.level; drawPlot(); }
  else {
    const dx = x - P.drag.x;
    if (Math.abs(dx) > 4) P.drag.moved = true;
    if (P.drag.moved) {
      const span = P.drag.b - P.drag.a, df = Math.round(-dx / g.W * span), n = S.rec.frames;
      P.a = Math.max(0, Math.min(n - 1 - span, P.drag.a + df)); P.b = P.a + span;
      plotBox.classList.add("grab"); fetchSoon();
    }
  }
});
plotBox.addEventListener("pointerdown", (e) => {
  if (!S.rec || !P.data.length) return;
  const b = plotBox.getBoundingClientRect(), g = geom(), y = e.clientY - b.top, x = e.clientX - b.left;
  plotBox.setPointerCapture(e.pointerId);
  P.drag = P.level != null && Math.abs(y - g.y(P.level)) < 8 ? { kind: "level" } : { kind: "pan", x, a: P.a, b: P.b, moved: false };
});
plotBox.addEventListener("pointerup", async (e) => {
  const d = P.drag; P.drag = null; plotBox.classList.remove("grab");
  if (!d) return;
  if (d.kind === "level") return setLevel(P.level);
  if (!d.moved) { const b = plotBox.getBoundingClientRect(); stopPlay(); S.frame = Math.round(geom().f(e.clientX - b.left)); showFrame(); }
});
async function setLevel(level, suggested) {
  try {
    S.rec = await api("/api/level", suggested ? { suggested: true } : { level: +level });
    if (S.sel && !S.rec.events.some((e) => e.n === S.sel)) S.sel = null;
    await fetchView(); renderEvents(); renderComments(); refreshFiles();
  } catch (e) { err(e); }
}
$("#level").onchange = () => setLevel($("#level").value);
$("#level-slider").oninput = () => { P.level = +$("#level-slider").value; $("#level").value = P.level.toFixed(2); drawPlot(); };
$("#level-slider").onchange = () => setLevel($("#level-slider").value);
$("#btn-level-reset").onclick = () => setLevel(null, true);

// ------------------------------------------------------------ events
function evById(n) { return S.rec.events.find((e) => e.n === n); }
async function selectEvent(n) {
  stopPlay(); S.sel = n; const e = evById(n);
  const pad = winPad();
  S.ws = Math.max(0, e.f0 - pad); S.we = Math.min(S.rec.frames - 1, e.f1 + pad);
  S.frame = e.f0;
  renderEvents(); drawPlot(); showFrame(); renderComments();
  const card = document.querySelector(`[data-ev="${n}"]`); card && card.scrollIntoView({ block: "nearest" });
  if (S.cfg && S.cfg.review.auto_play) { $("#in-window").checked = true; S.frame = S.ws; startPlay(1); }
}
async function decide(n, body) {
  try {
    Object.assign(evById(n), await api(`/api/event/${n}/decide`, body)); renderEvents(); drawPlot(); refreshFiles();
    // Settings > Review: after Confirm or Reject, move on to the next event still to review
    if (S.cfg && S.cfg.review.auto_advance && (body.status === "confirmed" || body.status === "rejected")) {
      const evs = S.rec.events, i = evs.findIndex((e) => e.n === n);
      const next = [...evs.slice(i + 1), ...evs.slice(0, i)].find((e) => e.status === "todo");
      if (next) selectEvent(next.n); else toast("All events reviewed.");
    }
  } catch (e) { err(e); }
}
function renderEvents() {
  const box = $("#events"), evs = (S.rec && S.rec.events) || [];
  $("#btn-export").disabled = !S.sel; $("#btn-csv").disabled = !evs.length; $("#btn-report").disabled = !(S.rec && S.rec.scanned);
  $("#btn-export-confirmed").disabled = !evs.some((e) => e.status === "confirmed");
  $("#reviewed").textContent = evs.length ? `${evs.filter((e) => e.status !== "todo").length} of ${evs.length} reviewed` : "";
  if (!S.rec) return;
  if (!S.rec.scanned) { box.innerHTML = '<p class="muted small">Draw an ROI, then Scan recording.</p>'; return; }
  if (!evs.length) { box.innerHTML = '<p class="muted small">No spikes reach the detection level. Drag the blue line lower on the plot.</p>'; return; }
  box.innerHTML = "";
  for (const e of evs) {
    const d = document.createElement("div"); d.className = "ev" + (S.sel === e.n ? " sel" : ""); d.dataset.ev = e.n;
    const chipK = e.status === "confirmed" ? "ok" : e.status === "rejected" ? "no" : "todo";
    const chipT = e.status === "confirmed" ? (e.cls || "Confirmed") : e.status === "rejected" ? "Rejected" : "Not reviewed";
    const nC = commentsFor(e).length;
    const playingThis = S.playing && S.dir > 0 && S.sel === e.n;
    d.innerHTML = `<div class="ev-row"><button class="ev-play${playingThis ? " on" : ""}" data-evplay="${e.n}" aria-label="${playingThis ? "Pause" : "Play"} event ${e.n}" title="${playingThis ? "Pause" : "Play this event"}">${playingThis ? PAUSE_ICON : PLAY_ICON}</button><button class="ev-head"><span class="ev-top"><b>Event ${e.n}</b><span class="mono small">${fmtTime(e.f0)}–${fmtTime(e.f1)}</span></span>
      <span class="mono small muted">${fmtDate(e.f0) ? `${fmtDate(e.f0)} ${fmtZone(e.f0)} · ` : ""}frames ${e.f0.toLocaleString()}–${e.f1.toLocaleString()} · ${fmtDur((e.f1 - e.f0 + 1) / S.rec.fps)} · peak ${e.peak.toFixed(1)}${isTemp(S.rec.units) ? " " + S.rec.units : ""}</span>
      <span class="row wrap"><span class="chip ${chipK}">${esc(chipT)}</span></span></button></div>`;
    d.querySelector(".ev-head").onclick = () => selectEvent(e.n);
    d.querySelector(".ev-play").onclick = () => playEvent(e.n);
    if (S.sel === e.n) {
      const x = document.createElement("div");
      x.innerHTML = `<label class="small" style="display:block;margin-top:10px">Classification<select data-cls>${["", ...CLASSES, ...(e.cls && !CLASSES.includes(e.cls) ? [e.cls] : [])].map((c) => `<option ${c === (e.cls || "") ? "selected" : ""}>${c}</option>`).join("")}</select></label>
         <div class="ev-actions"><button class="btn sm ok" data-act="confirmed">Confirm</button><button class="btn sm" data-act="rejected">Reject</button>${e.status !== "todo" ? '<button class="btn sm" data-act="todo">Undo</button>' : ""}</div>`;
      x.querySelector("[data-cls]").onchange = (ev) => decide(e.n, { cls: ev.target.value });
      x.querySelectorAll("[data-act]").forEach((b) => (b.onclick = () => {
        const act = b.dataset.act, cls = x.querySelector("[data-cls]").value;
        decide(e.n, { status: act, cls: act === "rejected" && !cls ? "Insect / noise" : act === "todo" ? "" : cls });
      }));
      d.appendChild(x);
    }
    // this event's comments, listed below it; the selected event also gets a box to add one
    const cms = commentsFor(e);
    if (cms.length || S.sel === e.n) {
      const c = document.createElement("div"); c.className = "ev-comments";
      c.innerHTML = `<div class="ev-c-head small strong">Comments${cms.length ? ` (${cms.length})` : ""}</div>`;
      for (const cm of cms) c.appendChild(commentItem(cm, false));
      if (S.sel === e.n) {
        const at = S.frame >= S.ws && S.frame <= S.we ? S.frame : e.f0;
        const f = document.createElement("div"); f.className = "ev-c-add";
        f.innerHTML = `<textarea rows="2" placeholder="Add a comment at ${fmtTime(at)} (frame ${at.toLocaleString()})…">${esc(S.evDraft[e.n] || "")}</textarea>
          <div class="row between"><span class="small muted">Ctrl + Enter to add</span><button class="btn sm primary" type="button">Add comment</button></div>`;
        const ta = f.querySelector("textarea");
        ta.oninput = () => { S.evDraft[e.n] = ta.value; };
        const add = async () => {
          const t = ta.value.trim(); if (!t) return;
          const frame = S.frame >= S.ws && S.frame <= S.we ? S.frame : e.f0;
          stopPlay();
          try { S.rec = await api("/api/comment", { text: t, frame }); S.evDraft[e.n] = ""; renderComments(); renderEvents(); } catch (er) { err(er); }
        };
        f.querySelector("button").onclick = add;
        ta.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); add(); } });
        c.appendChild(f);
      }
      d.appendChild(c);
    }
    box.appendChild(d);
  }
}
$("#btn-prev").onclick = () => stepEvent(-1);
$("#btn-next").onclick = () => stepEvent(1);
function stepEvent(d) { const evs = (S.rec && S.rec.events) || []; if (!evs.length) return; const i = evs.findIndex((e) => e.n === S.sel); const k = i < 0 ? 0 : Math.max(0, Math.min(evs.length - 1, i + d)); selectEvent(evs[k].n); }

// ------------------------------------------------------------ exports
$("#btn-export").onclick = () => {
  const e = evById(S.sel); $("#exp-title").textContent = `Export event pack – event ${e.n}`;
  $("#exp-sub").textContent = `${fmtTime(e.f0)} · ${S.rec.name}`;
  exportDefaults();
  $("#dlg-export").dataset.all = ""; $("#exp-blend-note").textContent = `(MP4, ${$("#blend").value === "crossfade" ? "crossfade" : "overlay"} at ${Math.round(+$("#opacity").value * 100)}%)`; document.querySelector(".exp-blend-jpg").textContent = $("#blend").value === "crossfade" ? `(JPEG, crossfade at ${Math.round(+$("#opacity").value * 100)}%, ${(S.filters || {}).mfi || 5} frames after activity is first seen)` : `(JPEG, overlay at ${Math.round(+$("#opacity").value * 100)}%, at the event's peak)`; $("#dlg-export").showModal();
};
$("#btn-export-confirmed").onclick = () => { $("#exp-title").textContent = "Export all confirmed events"; $("#exp-sub").textContent = S.rec.name; $("#dlg-export").dataset.all = "1"; exportDefaults(); $("#exp-blend-note").textContent = `(MP4, ${$("#blend").value === "crossfade" ? "crossfade" : "overlay"} at ${Math.round(+$("#opacity").value * 100)}%)`; document.querySelector(".exp-blend-jpg").textContent = $("#blend").value === "crossfade" ? `(JPEG, crossfade at ${Math.round(+$("#opacity").value * 100)}%, ${(S.filters || {}).mfi || 5} frames after activity is first seen)` : `(JPEG, overlay at ${Math.round(+$("#opacity").value * 100)}%, at the event's peak)`; $("#dlg-export").showModal(); };
$("#dlg-export").addEventListener("close", async () => {
  if ($("#dlg-export").returnValue !== "ok") return;
  const opts = { palette: S.pal, ranges: { review: S.rng.review, path: S.rng.path, blend: S.rng.blend },
                 blend: $("#blend").value, opacity: +$("#opacity").value, enh: enhVals(),
                 items: [...document.querySelectorAll("[name=items]:checked")].map((i) => i.value), pad_s: +$("#exp-pad").value,
                 overlays: $("#exp-overlays").value, quality: +$("#exp-quality").value, folder: $("#exp-folder").value };
  try { await api($("#dlg-export").dataset.all ? "/api/export-confirmed" : `/api/event/${S.sel}/export`, opts); toast("Exporting…"); pollJobs(); } catch (e) { err(e); }
});
$("#btn-csv").onclick = async () => { try { const r = await api("/api/events-csv", {}); toast("Saved " + r.files.join(" and "), 7000); } catch (e) { err(e); } };

// ------------------------------------------------------------ frame persistence
function renderFilters() {
  const f = (S.rec && S.rec.filters) || S.filters; if (!f) return;
  S.filters = f;
  if (document.activeElement !== $("#f-mfi")) $("#f-mfi").value = f.mfi;
  if (document.activeElement !== $("#f-ss")) $("#f-ss").value = f.ss;
  $("#btn-f-reset").disabled = f.mfi === 5 && f.ss === 5;
  const note = $("#scan-note"), old = !!(S.rec && S.rec.scan_outdated);
  note.hidden = !old;
  if (old) note.textContent = "This recording was scanned with an earlier version of the scan filters. Scan again so its events use Window Average + Sliding Subtraction 5.";
}
async function setFilters(body) {
  try {
    const r = await api("/api/filters", body);
    if (r.path) S.rec = r; else S.filters = r.filters;
    renderFilters(); showFrame();
  } catch (e) { err(e); }
}
$("#f-mfi").onchange = () => setFilters({ mfi: +$("#f-mfi").value });
$("#f-ss").onchange = () => setFilters({ ss: +$("#f-ss").value });
$("#btn-f-reset").onclick = () => setFilters({ mfi: 5, ss: 5 });
api("/api/filters").then((r) => { S.filters = r.filters; renderFilters(); }).catch(() => {});

// ------------------------------------------------------------ PDF report
const RP = ["company", "contact", "location", "camera", "analyst", "folder"];
$("#btn-report").onclick = async () => {
  try {
    const d = await api("/api/report-defaults");
    RP.forEach((k) => ($("#rp-" + k).value = d[k] || ""));
    $("#rp-warn").hidden = d.reviewed;
    $("#dlg-report").showModal();
  } catch (e) { err(e); }
};
$("#dlg-report").addEventListener("close", async () => {
  if ($("#dlg-report").returnValue !== "ok") return;
  const body = { rejected_images: $("#rp-rejected").checked, blend: $("#blend").value, opacity: +$("#opacity").value,
                 palette: S.pal, blend_range: S.rng.blend, enh: enhVals() };
  RP.forEach((k) => (body[k] = $("#rp-" + k).value));
  try { await api("/api/report", body); toast("Creating the PDF report…"); pollJobs(); } catch (e) { err(e); }
});

// ------------------------------------------------------------ comments
function commentsFor(e) {
  const pad = winPad();
  return (S.rec.comments || []).filter((c) => c.frame >= e.f0 - pad && c.frame <= e.f1 + pad);
}
function eventAt(frame) {
  const pad = winPad();
  const e = (S.rec.events || []).find((e) => frame >= e.f0 - pad && frame <= e.f1 + pad);
  return e ? e.n : null;
}
function updateCommentBox() {
  const on = !!S.rec;
  $("#c-text").disabled = !on; $("#btn-c-add").disabled = !on;
  $("#c-at").textContent = on ? `${fmtStamp(S.frame)} · frame ${S.frame.toLocaleString()}` : "";
  document.querySelectorAll(".c-item").forEach((el) => el.classList.toggle("here", +el.dataset.frame === S.frame));
  const ta = document.querySelector(".ev-c-add textarea");
  if (ta && S.sel) { const e = evById(S.sel), at = S.frame >= S.ws && S.frame <= S.we ? S.frame : e.f0; ta.placeholder = `Add a comment at ${fmtTime(at)} (frame ${at.toLocaleString()})…`; }
}
function commentItem(c, showEvent) {
  const ev = eventAt(c.frame), d = document.createElement("div");
  d.className = "c-item" + (c.frame === S.frame ? " here" : ""); d.dataset.frame = c.frame;
  d.innerHTML = `<button class="c-body" title="Jump to this moment"><span class="c-meta">${fmtStamp(c.frame)} · frame ${c.frame.toLocaleString()}${showEvent && ev ? ` · event ${ev}` : ""}</span><span class="c-text">${esc(c.text)}</span></button>
    <button class="rm" aria-label="Delete comment" title="Delete comment">×</button>`;
  d.querySelector(".c-body").onclick = () => goFrame(c.frame);
  d.querySelector(".rm").onclick = async () => { try { S.rec = await api("/api/comment/delete", { id: c.id }); renderComments(); renderEvents(); } catch (e) { err(e); } };
  return d;
}
// The side panel holds comments that fall outside every event; event comments sit under their event.
function renderComments() {
  const box = $("#c-list"); box.innerHTML = "";
  const cs = ((S.rec && S.rec.comments) || []).filter((c) => eventAt(c.frame) == null);
  $("#c-count").textContent = cs.length ? `${cs.length}` : "";
  if (!S.rec) return;
  if (!cs.length) { box.innerHTML = '<p class="small muted">Comments made inside an event appear under that event. Comments at other times appear here.</p>'; updateCommentBox(); return; }
  for (const c of cs) box.appendChild(commentItem(c, false));
  updateCommentBox();
}
async function addComment() {
  const t = $("#c-text").value.trim(); if (!t || !S.rec) return;
  stopPlay();
  try { S.rec = await api("/api/comment", { text: t, frame: S.frame }); $("#c-text").value = ""; renderComments(); renderEvents(); } catch (e) { err(e); }
}
$("#btn-c-add").onclick = addComment;
$("#c-text").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); addComment(); } });

// ------------------------------------------------------------ keyboard
document.addEventListener("keydown", (e) => {
  if (e.target.closest("input, select, textarea, dialog")) return;
  const k = e.key;
  if (k >= "1" && k <= "4") setMode(MODES_ORDER[+k - 1]);
  else if (k === "ArrowRight") { stopPlay(); S.frame += e.shiftKey ? Math.round(S.rec ? S.rec.fps : 16) : 1; showFrame(); }
  else if (k === "ArrowLeft") { stopPlay(); S.frame -= e.shiftKey ? Math.round(S.rec ? S.rec.fps : 16) : 1; showFrame(); }
  else if (k === " ") { e.preventDefault(); startPlay(1); }
  else if (k === "Home") { e.preventDefault(); $("#btn-start").click(); }
  else if (k === "End") { e.preventDefault(); $("#btn-end").click(); }
  else if (k === "n") stepEvent(1); else if (k === "p") stepEvent(-1);
  else return;
});

// ------------------------------------------------------------ customer beta
async function checkBeta() {
  let b; try { b = await api("/api/beta"); } catch (e) { return; }
  S.beta = b;
  const badge = $("#beta-badge");
  badge.hidden = !b.active;
  badge.title = `${b.product} ${b.version} (beta)` + (b.ends ? ` · trial ends ${b.ends.split("-").reverse().join("/")}` : "");
  $("#beta-days").hidden = !(b.active && !b.expired && b.days_left <= 14);
  $("#beta-days").textContent = `${b.days_left} day${b.days_left === 1 ? "" : "s"} left in this beta`;
  if (!b.active) return;
  const gate = $("#beta-gate"), acts = $("#bg-actions");
  if (b.expired) {
    $("#bg-title").textContent = "This beta has ended";
    $("#bg-intro").textContent = `Thank you for testing ${b.product}. This beta version (${b.version}) has reached the end of its trial period. Please contact Thermal Vision Ecology for the latest version. You can still send us feedback.`;
    $("#bg-licence").hidden = true;
    acts.innerHTML = '<button class="btn" id="bg-fb">Send feedback</button><button class="btn primary" id="bg-quit">Close</button>';
    gate.hidden = false;
    $("#bg-fb").onclick = () => openFeedback();
    $("#bg-quit").onclick = () => $("#btn-quit").click();
  } else if (!b.licence_accepted) {
    $("#bg-title").textContent = `Welcome to the ${b.product} beta`;
    $("#bg-intro").textContent = `Version ${b.version}. Please read and accept the beta licence to continue. The trial runs for ${b.days_left} days, until ${b.ends.split("-").reverse().join("/")}.`;
    $("#bg-licence").hidden = false; $("#bg-licence").textContent = b.licence_text || "";
    acts.innerHTML = '<button class="btn" id="bg-decline">Decline and close</button><button class="btn primary" id="bg-accept">I accept</button>';
    gate.hidden = false;
    $("#bg-decline").onclick = () => $("#btn-quit").click();
    $("#bg-accept").onclick = async () => {
      try { await api("/api/beta/accept", {}); gate.hidden = true; refreshFiles(); } catch (e) { err(e); }
    };
  } else gate.hidden = true;
}

// ------------------------------------------------------------ feedback
function openFeedback() {
  $("#fb-entry").hidden = false; $("#fb-done").hidden = true; $("#fb-err").hidden = true;
  if (S.cfg && S.cfg.report) { if (!$("#fb-name").value) $("#fb-name").value = S.cfg.report.analyst || ""; }
  if (S.rec && !$("#fb-where").value) $("#fb-where").value = S.sel ? `Event ${S.sel}, ${S.rec.camera} recording` : `${S.rec.camera} recording`;
  fbType(); $("#dlg-feedback").showModal(); $("#fb-summary").focus();
}
function fbType() {
  const t = (document.querySelector("[name=fb-type]:checked") || {}).value;
  $("#fb-steps-wrap").hidden = !(t === "bug" || t === "broken");
}
document.querySelectorAll("[name=fb-type]").forEach((r) => (r.onchange = fbType));
$("#btn-feedback").onclick = openFeedback;
$("#fb-cancel").onclick = () => $("#dlg-feedback").close();
$("#fb-close").onclick = () => {
  $("#dlg-feedback").close();
  for (const id of ["#fb-summary", "#fb-details", "#fb-steps", "#fb-where"]) $(id).value = "";
};
$("#fb-send").onclick = async () => {
  const body = { type: (document.querySelector("[name=fb-type]:checked") || {}).value, summary: $("#fb-summary").value,
                 details: $("#fb-details").value, steps: $("#fb-steps").value, where: $("#fb-where").value,
                 name: $("#fb-name").value, email: $("#fb-email").value, diagnostics: $("#fb-diag").checked };
  if (!body.summary.trim()) { $("#fb-err").textContent = "Please add a one-line summary."; $("#fb-err").hidden = false; $("#fb-summary").focus(); return; }
  $("#fb-send").disabled = true;
  try {
    const r = await api("/api/feedback", body);
    $("#fb-zip").textContent = r.zip; $("#fb-mailto").href = r.mailto;
    $("#fb-noemail").hidden = !!r.email;
    $("#fb-noemail").textContent = "No feedback address is set in this build, so please add Thermal Vision Ecology's email address yourself.";
    $("#fb-copy").onclick = async () => { try { await navigator.clipboard.writeText(`${r.subject}\n\n${r.text}`); toast("Message copied."); } catch (e) { toast("Couldn't copy. Select the text in the email instead."); } };
    $("#fb-entry").hidden = true; $("#fb-done").hidden = false;
  } catch (e) { $("#fb-err").textContent = e.message || String(e); $("#fb-err").hidden = false; }
  finally { $("#fb-send").disabled = false; }
};

// ------------------------------------------------------------ quit
let quitArmed = 0;
$("#btn-quit").onclick = async () => {
  let busy = false;
  try { busy = (await api("/api/jobs")).jobs.some((j) => j.state === "queued" || j.state === "running"); } catch (e) {}
  if (busy && Date.now() - quitArmed > 5000) {   // ask once more if a scan or export is still going
    quitArmed = Date.now(); $("#btn-quit").lastChild.textContent = " Quit anyway?";
    toast("A scan or export is still running. Click Quit anyway? to stop it and close.", 5000);
    setTimeout(() => { $("#btn-quit").lastChild.textContent = " Quit"; }, 5000);
    return;
  }
  try { await api("/api/quit", {}); } catch (e) {}
  document.body.innerHTML = `<div class="closed"><img src="/static/tve-logo.png" alt="" class="logo-dark"><img src="/static/tve-logo-dark.png" alt="" class="logo-light">
    <h1>Track &amp; Detect has closed</h1><p>You can close this window. Open Track &amp; Detect again from its desktop shortcut.</p></div>`;
  setTimeout(() => { try { window.close(); } catch (e) {} }, 1200);   // closes the app window where Windows allows it
};

// ------------------------------------------------------------ settings
function setCrumbMeta() {
  $("#crumb-meta").textContent = `· ${S.rec.camera} · ${S.rec.start ? "starts " + fmtStamp(0) + " · " : ""}${fmtDur(S.rec.duration_s)} · ${S.rec.frames.toLocaleString()} frames · ${S.rec.units}`;
}
function winPad() { return Math.round(((S.cfg && S.cfg.detect.window_s) ?? 3) * (S.rec ? S.rec.fps : 16)); }
function exportDefaults() {   // the export dialog opens with the defaults from Settings > Exports
  const ex = (S.cfg || {}).export || {};
  document.querySelectorAll("[name=items]").forEach((i) => (i.checked = (ex.items || []).includes(i.value)));
  if (ex.overlays) $("#exp-overlays").value = ex.overlays;
  if (ex.quality) $("#exp-quality").value = ex.quality;
  $("#exp-pad").value = (S.cfg && S.cfg.detect.window_s) ?? 3;
  const sep = S.rec.path.includes("\\") ? "\\" : "/";
  $("#exp-folder").value = ex.folder || S.rec.path.replace(/[\\/][^\\/]+$/, "") + sep + "exports";
}
function applyViewDefaults(v) {   // start the Viewing Mode bar from the saved defaults
  if ([...$("#palette").options].some((o) => o.value === v.palette)) $("#palette").value = v.palette;
  S.pal = v.palette;
  $("#dde-on").checked = v.dde > 0; if (v.dde > 0) $("#dde-level").value = String(v.dde);
  $("#tnr-on").checked = v.tnr > 0; if (v.tnr > 0) $("#tnr-level").value = String(v.tnr);
  $("#blend").value = v.blend; $("#opacity").value = String(v.opacity);
  $("#speed").value = String(v.speed);
  syncEnh(); opacityTitle();
}
function applySettings(c, first) {
  const old = S.cfg; S.cfg = c;
  CLASSES = c.classes;
  applyLook(c.appearance.scheme, c.appearance.theme);
  if (first || JSON.stringify(old.view) !== JSON.stringify(c.view)) applyViewDefaults(c.view);
}

const ST = { saved: null, draft: null };   // saved settings, and the copy being edited
const SECTIONS = ["appearance", "viewing", "detection", "exports", "time", "classes", "review", "report", "shortcuts"];
function stShow(sec) {
  document.querySelectorAll(".st-nav [data-sec]").forEach((b) => b.setAttribute("aria-current", String(b.dataset.sec === sec)));
  document.querySelectorAll(".st-panes [data-pane]").forEach((p) => (p.hidden = p.dataset.pane !== sec));
}
document.querySelectorAll(".st-nav [data-sec]").forEach((b) => (b.onclick = () => stShow(b.dataset.sec)));
function stFill(c) {
  $("#st-scheme").value = c.appearance.scheme;
  document.querySelectorAll("[name=st-theme]").forEach((r) => (r.checked = r.value === c.appearance.theme));
  document.querySelectorAll("[name=st-window]").forEach((r) => (r.checked = r.value === (c.appearance.window || "app")));
  $("#st-palette").innerHTML = S.palettes.map((p) => `<option value="${p.id}">${esc(p.label)}</option>`).join("");
  $("#st-palette").value = c.view.palette; $("#st-speed").value = String(c.view.speed);
  $("#st-dde").value = String(c.view.dde); $("#st-tnr").value = String(c.view.tnr);
  $("#st-blend").value = c.view.blend; $("#st-opacity").value = String(c.view.opacity);
  $("#st-mfi").value = c.filters.mfi; $("#st-ss").value = c.filters.ss;
  $("#st-sens").value = c.detect.sensitivity; $("#st-merge").value = c.detect.merge_s;
  $("#st-minf").value = c.detect.min_frames; $("#st-window").value = c.detect.window_s;
  $("#st-folder").value = c.export.folder;
  document.querySelectorAll("[name=st-items]").forEach((i) => (i.checked = c.export.items.includes(i.value)));
  $("#st-overlays").value = c.export.overlays; $("#st-textsize").value = c.export.text_size;
  $("#st-naming").value = c.export.naming; $("#st-quality").value = c.export.quality; $("#st-slowmo").value = String(c.export.slowmo);
  $("#st-temp").value = c.units.temp; $("#st-zone").value = c.units.zone; $("#st-offset").value = c.units.clock_offset_s;
  $("#st-classes").value = c.classes.join("\n");
  $("#st-autoadv").checked = c.review.auto_advance; $("#st-autoplay").checked = c.review.auto_play;
  for (const k of ["company", "contact", "analyst", "camera"]) $("#st-" + k).value = c.report[k] || "";
  stExamples();
}
function stRead() {
  const v = (id) => $(id).value;
  return {
    appearance: { scheme: v("#st-scheme"), theme: (document.querySelector("[name=st-theme]:checked") || {}).value || "dark",
                  window: (document.querySelector("[name=st-window]:checked") || {}).value || "app" },
    view: { palette: v("#st-palette"), speed: +v("#st-speed"), dde: +v("#st-dde"), tnr: +v("#st-tnr"), blend: v("#st-blend"), opacity: +v("#st-opacity") },
    filters: { mfi: +v("#st-mfi"), ss: +v("#st-ss") },
    detect: { sensitivity: v("#st-sens"), merge_s: +v("#st-merge"), min_frames: +v("#st-minf"), window_s: +v("#st-window") },
    export: { folder: v("#st-folder").trim(), items: [...document.querySelectorAll("[name=st-items]:checked")].map((i) => i.value),
              overlays: v("#st-overlays"), text_size: v("#st-textsize"), naming: v("#st-naming"), quality: +v("#st-quality"), slowmo: +v("#st-slowmo") },
    units: { temp: v("#st-temp"), zone: v("#st-zone"), clock_offset_s: +v("#st-offset") || 0 },
    classes: v("#st-classes").split("\n").map((x) => x.trim()).filter(Boolean),
    review: { auto_advance: $("#st-autoadv").checked, auto_play: $("#st-autoplay").checked },
    report: Object.fromEntries(["company", "contact", "analyst", "camera"].map((k) => [k, v("#st-" + k).trim()])),
  };
}
function stExamples() {
  const site = S.rec ? S.rec.path.split(/[\\/]/).slice(-2, -1)[0] : "St Fagans", recn = S.rec ? S.rec.name.replace(/\.ats$/i, "") : "front 2";
  const eg = { site_recording: `${site}_${recn}_event1_21-14-05`, date_site: `${(S.rec && fmtDate(0) ? fmtDate(0) : "10/08/2026").replace(/\//g, "-")}_${site}_${recn}_event1`, recording_event: `${recn}_event1_21-14-05` };
  $("#st-naming-eg").textContent = (eg[$("#st-naming").value] || "").replace(/[^A-Za-z0-9_.-]+/g, "_") + "_flightpath.mp4";
  const o = +$("#st-offset").value || 0, a = Math.abs(o);
  $("#st-offset-eg").textContent = o ? `Times will move ${o > 0 ? "later" : "earlier"} by ${a >= 3600 ? Math.floor(a / 3600) + " h " : ""}${a % 3600 >= 60 ? Math.floor((a % 3600) / 60) + " min " : ""}${a % 60 ? (a % 60) + " s" : ""}.` : "";
}
function stDirty() {   // compare what's on screen with what's saved, section by section
  const a = stRead(), c = ST.saved, norm = (o) => JSON.stringify(o, Object.keys(o || {}).sort());
  const same = Object.keys(a).every((k) => Array.isArray(a[k]) ? JSON.stringify(a[k]) === JSON.stringify(c[k]) : norm(a[k]) === norm(c[k]));
  $("#st-dirty").hidden = same;
}
$("#st-form").addEventListener("input", () => { stExamples(); stDirty(); });
$("#st-form").addEventListener("change", () => { stExamples(); stDirty(); });
// appearance previews straight away; Cancel puts it back
$("#st-scheme").addEventListener("change", () => applyLook($("#st-scheme").value, null));
document.querySelectorAll("[name=st-theme]").forEach((r) => r.addEventListener("change", () => applyLook(null, r.value)));
$("#st-from-view").onclick = () => {
  const e = enhVals();
  $("#st-palette").value = S.pal; $("#st-speed").value = $("#speed").value;
  $("#st-dde").value = String(e.dde); $("#st-tnr").value = String(e.tnr);
  $("#st-blend").value = $("#blend").value; $("#st-opacity").value = $("#opacity").value;
  if (S.filters) { $("#st-mfi").value = S.filters.mfi; $("#st-ss").value = S.filters.ss; }
  stDirty(); toast("Copied the current view. Click Save settings to keep it.");
};
$("#st-detect-reset").onclick = () => { $("#st-sens").value = "normal"; $("#st-merge").value = 2; $("#st-minf").value = 1; $("#st-window").value = 3; stDirty(); };
$("#st-folder-pick").onclick = async () => {
  try { const r = await api("/api/pick", { kind: "folder" }); if (r.paths.length) { $("#st-folder").value = r.paths[0]; stDirty(); } } catch (e) { err(e); }
};
async function openSettings() {
  try { const r = await api("/api/settings"); ST.saved = r.settings; ST.defaults = r.defaults; } catch (e) { return err(e); }
  stFill(ST.saved); stShow("appearance"); $("#st-dirty").hidden = true; $("#dlg-settings").showModal();
}
function closeSettings() {   // undo any appearance preview that wasn't saved
  applyLook(S.cfg.appearance.scheme, S.cfg.appearance.theme);
  $("#dlg-settings").close();
}
$("#btn-settings").onclick = openSettings;
$("#st-cancel").onclick = closeSettings;
$("#dlg-settings").addEventListener("cancel", (e) => { e.preventDefault(); closeSettings(); });
async function saveSettings(body, msg) {
  const btn = $("#st-save"); btn.disabled = true;
  try {
    const before = S.cfg, r = await api("/api/settings", body);
    applySettings(r.settings, false);
    if (r.recording) {
      const unitsChanged = !S.rec || r.recording.units !== S.rec.units;
      S.rec = r.recording;
      if (unitsChanged) { S.rng = { raw: null, review: null, path: null, blend: null }; S.track = {}; }
      if (S.sel && !S.rec.events.some((e) => e.n === S.sel)) S.sel = null;
      if (S.sel) { const e = evById(S.sel), pad = winPad(); S.ws = Math.max(0, e.f0 - pad); S.we = Math.min(S.rec.frames - 1, e.f1 + pad); }
      if (S.rec.scanned) await loadActivity(true);
      renderEvents(); renderComments(); updateLevelInputs(); refreshFiles(); showFrame();
      setCrumbMeta();
    }
    api("/api/filters").then((f) => { S.filters = f.filters; renderFilters(); }).catch(() => {});
    $("#dlg-settings").close(); toast(msg || "Settings saved. They'll be used next time too.", 5000);
  } catch (e) { err(e); } finally { btn.disabled = false; }
}
$("#st-save").onclick = () => saveSettings({ settings: stRead() });
$("#st-reset").onclick = () => { if (ST.defaults) { stFill(ST.defaults); applyLook(ST.defaults.appearance.scheme, ST.defaults.appearance.theme); stDirty(); toast("Defaults filled in. Click Save settings to use them."); } };
$("#st-export").onclick = () => {
  const blob = new Blob([JSON.stringify({ app: "Track & Detect", ...stRead() }, null, 1)], { type: "application/json" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "TrackAndDetect-settings.json";
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
};
$("#st-import").onclick = () => $("#st-import-file").click();
$("#st-import-file").onchange = async () => {
  const f = $("#st-import-file").files[0]; $("#st-import-file").value = ""; if (!f) return;
  try {
    const d = JSON.parse(await f.text());
    if (!d || typeof d !== "object" || !d.view && !d.detect && !d.appearance) throw new Error("That file doesn't contain Track & Detect settings.");
    const merged = { ...stRead(), ...d };
    stFill({ ...ST.saved, ...merged, appearance: { ...ST.saved.appearance, ...(d.appearance || {}) }, view: { ...ST.saved.view, ...(d.view || {}) },
             filters: { ...ST.saved.filters, ...(d.filters || {}) }, detect: { ...ST.saved.detect, ...(d.detect || {}) },
             export: { ...ST.saved.export, ...(d.export || {}) }, units: { ...ST.saved.units, ...(d.units || {}) },
             review: { ...ST.saved.review, ...(d.review || {}) }, report: { ...ST.saved.report, ...(d.report || {}) },
             classes: Array.isArray(d.classes) && d.classes.length ? d.classes : ST.saved.classes });
    applyLook($("#st-scheme").value, (document.querySelector("[name=st-theme]:checked") || {}).value);
    stDirty(); toast(`Loaded ${f.name}. Check it over, then click Save settings.`, 6000);
  } catch (e) { err(e.message ? e : new Error("Couldn't read that settings file.")); }
};

(async () => {
  try { const r = await api("/api/settings"); ST.saved = r.settings; await loadPalettes(); applySettings(r.settings, true); } catch (e) {}
  await checkBeta();
  setInterval(checkBeta, 3600e3);   // the trial can end while the program is open
  refreshFiles().then(() => api("/api/files").then((r) => { if (r.current) openRec(r.current); })).catch(() => {});
})();
pollJobs();
