"use strict";
const $ = (s) => document.querySelector(s);
const S = { files: [], rec: null, mode: "raw", frame: 0, sel: null, ws: 0, we: 0,
            drawing: false, pts: [], playing: false, act: [], polling: null, lastJobs: "" };
const MODES_ORDER = ["raw", "path", "blend", "custom"];   // Default, Tracking, Detection, Custom (keys 1–4)
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
// Seconds from the first frame to a frame: from the camera's time stamp on
// each frame once the time table has loaded, otherwise frames / frame rate.
function secAt(frame) {
  const r = S.rec; if (!r) return 0;
  const t = S.times, f = Math.max(0, Math.min(r.frames - 1, Math.round(frame)));
  return t && t.length === r.frames ? t[f] : f / r.fps;
}
function spanS(f0, f1) { return Math.max(0, secAt(f1) - secAt(f0)) + 1 / S.rec.fps; }   // length of frames f0..f1
async function loadTimes(path) {
  S.times = null;
  try {
    const res = await fetch("/api/times?path=" + encodeURIComponent(path), { cache: "no-store" });
    if (res.status !== 200 || !S.rec || S.rec.path !== path) return;
    S.times = new Float64Array(await res.arrayBuffer());
    renderEvents(); drawPlot(); showFrame();   // relabel with exact times
  } catch (e) { S.times = null; }
}
function fmtZone(frame) { const r = S.rec; return r && r.start ? ukTime(new Date(r.start).getTime() + secAt(frame) * 1000).zone : ""; }
function fmtDate(frame) {   // dd/mm/yyyy, UK date
  const r = S.rec; if (!r || !r.start) return "";
  const d = ukTime(new Date(r.start).getTime() + secAt(frame) * 1000).d;
  return `${String(d.getUTCDate()).padStart(2, "0")}/${String(d.getUTCMonth() + 1).padStart(2, "0")}/${d.getUTCFullYear()}`;
}
function fmtStamp(frame) { return [fmtDate(frame), fmtTime(frame), fmtZone(frame)].filter(Boolean).join(" "); }
function fmtTime(frame) {
  const r = S.rec; if (!r) return "";
  if (r.start) return ukTime(new Date(r.start).getTime() + secAt(frame) * 1000).d.toISOString().substr(11, 8);
  const s = secAt(frame); return `+${String(Math.floor(s / 60)).padStart(2, "0")}:${(s % 60).toFixed(1).padStart(4, "0")}`;
}
function fmtDur(s) { const m = Math.floor(s / 60); return `${m}:${String(Math.round(s % 60)).padStart(2, "0")}`; }
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

// ------------------------------------------------------------ recordings list
// Recordings are organised Project > Survey > Camera. Added recordings go in
// the Unassigned box unless the Add dialog puts them in a camera; they can be
// dragged between cameras afterwards.
const ICON_PROJ = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';
const ICON_CAM = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>';
const ICON_SV = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>';
const ICON_BIN = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>';
function radio(name, value) { return document.querySelector(`[name=${name}][value=${value}]`); }
function findCam(id) {   // {project, survey, camera} for a camera id
  for (const pj of S.tree || []) for (const sv of pj.surveys) for (const c of sv.cameras) if (c.id === id) return { project: pj, survey: sv, camera: c };
  return null;
}
function fileRow(path) { return (S.files || []).find((f) => f.path === path); }
async function org(body) { const r = await api("/api/org", body); setFiles(r); return r; }

// ---- the Add dialog
function fillAddPlace(want) {   // want: {project, survey, camera} ids to preselect
  const tree = S.tree || [];
  const ps = $("#add-proj"), pv = want.project ?? ps.value;
  ps.innerHTML = tree.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("") + '<option value="__new">+ New project</option>';
  ps.value = pv === "__new" || tree.some((p) => p.id === pv) ? pv : tree.length ? tree[0].id : "__new";
  const pj = tree.find((p) => p.id === ps.value);
  $("#add-proj-name").hidden = !!pj;
  const ss = $("#add-sv"), sv0 = want.survey ?? ss.value;
  ss.innerHTML = (pj ? pj.surveys.map((s) => `<option value="${s.id}">${esc(s.label)}</option>`).join("") : "") + `<option value="__new">+ New survey${pj ? ` (Survey ${Math.max(0, ...pj.surveys.map((s) => s.no)) + 1})` : " (Survey 1)"}</option>`;
  ss.value = sv0 === "__new" || (pj && pj.surveys.some((s) => s.id === sv0)) ? (pj ? sv0 : "__new") : pj && pj.surveys.length ? pj.surveys[pj.surveys.length - 1].id : "__new";
  const sv = pj && pj.surveys.find((s) => s.id === ss.value);
  $("#add-sv-date-wrap").hidden = !!sv;
  const cs = $("#add-cam"), c0 = want.camera ?? cs.value;
  const nextNo = sv ? Math.max(0, ...sv.cameras.map((c) => c.no)) + 1 : 1;
  cs.innerHTML = (sv ? sv.cameras.map((c) => `<option value="${c.id}">${esc(c.label)}</option>`).join("") : "")
    + `<option value="__new">+ New camera (Camera ${nextNo})</option><option value="__auto">Sort automatically by file name</option>`;
  cs.value = sv && sv.cameras.some((c) => c.id === c0) ? c0 : (c0 === "__auto" || c0 === "__new" ? c0 : sv && sv.cameras.length ? sv.cameras[0].id : "__new");
  $("#add-cam-name").hidden = cs.value !== "__new";
  $("#add-auto-note").hidden = cs.value !== "__auto";
  if (typeof checkAddName === "function" && $("#add-proj-warn")) checkAddName();
  const on = radio("add-where", "camera").checked;
  $("#add-place").classList.toggle("off", !on);
  $("#add-folders-note").classList.toggle("off", !radio("add-where", "folders").checked);
  $("#add-place").querySelectorAll("select, input").forEach((el) => (el.disabled = !on));
}
// opened from the top bar or the empty viewer: Unassigned; from a camera's "+ Add files": that camera
// every saved project's name, so a new one can't repeat it
async function loadProjectNames() {
  try { S.allProj = (await api("/api/org", { action: "list_projects" })).projects; } catch (e) { S.allProj = S.allProj || []; }
}
function projClash(name) {
  const n = (name || "").trim().toLowerCase(); if (!n) return null;
  return (S.allProj || []).find((p) => p.name.toLowerCase() === n) || (S.tree || []).find((p) => p.name.toLowerCase() === n) || null;
}
function checkAddName() {
  const isNew = radio("add-where", "camera").checked && $("#add-proj").value === "__new";
  const c = isNew ? projClash($("#add-proj-name").value) : null;
  $("#add-proj-warn").hidden = !c;
  if (c) $("#add-proj-warn").textContent = `There's already a project called ${c.name}. Choose it from the Project list instead, or use another name.`;
  $("#btn-folder-ok").disabled = !!c;
}
$("#add-proj-name").addEventListener("input", checkAddName);
function sizeBox() { const t = $("#folder-input"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight + 2, 260) + "px"; }
$("#folder-input").addEventListener("input", sizeBox);
function openAdd(cameraId) {
  loadProjectNames().then(checkAddName);
  $("#folder-input").value = ""; $("#pick-msg").hidden = true; $("#add-cam-msg").hidden = true;
  $("#add-proj-name").value = ""; $("#add-cam-name").value = ""; $("#add-sv-date").value = "";
  const at = typeof cameraId === "string" ? findCam(cameraId) : null;
  radio("add-where", at ? "camera" : "none").checked = true;
  fillAddPlace(at ? { project: at.project.id, survey: at.survey.id, camera: at.camera.id } : {});
  checkAddName(); $("#dlg-folder").showModal(); sizeBox();
}
document.querySelectorAll("[name=add-where]").forEach((r) => (r.onchange = () => fillAddPlace({})));
$("#add-proj").onchange = () => fillAddPlace({ survey: "", camera: "" });
$("#add-sv").onchange = () => fillAddPlace({ camera: "" });
$("#add-cam").onchange = () => fillAddPlace({});
function addTarget() {
  if (radio("add-where", "folders").checked) return { folders: true };
  if (!radio("add-where", "camera").checked) return null;
  const p = $("#add-proj").value, sv = $("#add-sv").value, c = $("#add-cam").value;
  return {
    project: p === "__new" ? { name: $("#add-proj-name").value.trim() } : { id: p },
    survey: p === "__new" || sv === "__new" ? { date: $("#add-sv-date").value } : { id: sv },
    camera: c === "__auto" ? { auto: true } : c === "__new" || p === "__new" || sv === "__new" ? { name: $("#add-cam-name").value.trim() } : { id: c },
  };
}
// the folder button: New project, Open project, Add files
$("#btn-open").onclick = (e) => { e.stopPropagation(); closeMenus("open"); toggleMenu("#open-menu", "#btn-open"); };
$("#open-menu").addEventListener("click", (e) => e.stopPropagation());
$("#om-add").onclick = () => { toggleMenu("#open-menu", "#btn-open", false); openAdd(); };
// New project, or a new pre-survey template (a project planned on the site
// plan before the survey: where the cameras and detectors will go)
let NP_PLAN = false;
function newProject(plan) {
  NP_PLAN = !!plan;
  $("#np-title").textContent = plan ? "New pre-survey template" : "New analysis project";
  $("#np-help").textContent = plan ? "Next, the site plan opens: find the site, then place the cameras and acoustic detectors where they will go. It's saved as the template for the survey."
    : "The project starts with Survey 1 and Camera 1. Next you can add recordings to it.";
  $("#np-go").textContent = plan ? "Create and open site plan" : "Create and add files";
  $("#np-name").value = ""; $("#np-date").value = ""; $("#np-msg").hidden = true; $("#np-warn").hidden = true; $("#np-go").disabled = false;
  loadProjectNames(); $("#dlg-newproj").showModal(); $("#np-name").focus();
}
$("#om-new").onclick = () => { toggleMenu("#open-menu", "#btn-open", false); newProject(false); };
$("#om-tnew").onclick = () => { toggleMenu("#open-menu", "#btn-open", false); newProject(true); };
$("#np-name").addEventListener("input", () => {
  const c = projClash($("#np-name").value);
  $("#np-warn").hidden = !c; $("#np-go").disabled = !!c;
  if (c) $("#np-warn").textContent = `There's already a project called ${c.name}. Use Open project to open it, or choose another name.`;
});
$("#np-go").onclick = async (ev) => {
  ev.preventDefault();
  const name = $("#np-name").value.trim();
  try {
    const r = await org({ action: "new_project", name, date: $("#np-date").value, pre_survey: NP_PLAN });
    $("#dlg-newproj").close();
    const at = findCam(r.created);
    if (NP_PLAN) { if (at) openMap(at.project.id); } else openAdd(r.created);
  } catch (e) { $("#np-msg").hidden = false; $("#np-msg").textContent = e.message || String(e); }
};
$("#op-file").onclick = async () => {
  try {
    const p = await api("/api/pick", { kind: "project" }); if (!p.paths.length) return;
    const r = await api("/api/org", { action: "open_project_file", path: p.paths[0] });
    setFiles(r); $("#dlg-openproj").close();
    toast(`Project opened: ${plural(r.opened, "recording")} listed${r.missing ? `, ${r.missing} not found` : ""}.`, 7000);
  } catch (e) { err(e); }
};
// Open project (plan: open a pre-survey template's site plan instead)
async function openProjectList(plan) {
  try {
    const r = await api("/api/org", { action: "list_projects" });
    const box = $("#op-list");
    $("#op-title").textContent = plan ? "Open pre-survey template" : "Open analysis project";
    $("#op-help").textContent = plan ? "Projects with a site plan template, or made as a pre-survey template. Opening one shows its site plan."
      : "Lists every recording saved in the project. Recordings that have been moved or deleted since are skipped.";
    $("#op-file-row").hidden = $("#op-replace-row").hidden = !!plan;
    const list = plan ? r.projects.filter((p) => p.pre_survey || p.template) : r.projects;
    box.innerHTML = list.length ? "" : plan ? '<p class="small muted">No pre-survey templates yet. Use New pre-survey template, or open a project\'s Site Plan and click Save as site plan template.</p>'
      : '<p class="small muted">No projects saved yet. Use New project, or Add files and assign them to a project.</p>';
    if (plan) {
      for (const p of list) {
        const row = el("div", "op-row");
        row.innerHTML = `<div><b>${esc(p.name)}</b><br><span class="small muted">${p.template ? `Template: ${plural(p.template, "camera")}` : `${plural(p.placed, "camera")} placed`} · ${plural(p.surveys, "survey")}${p.recordings ? ` · ${plural(p.recordings, "recording")}` : ""}</span></div>`;
        row.appendChild(smallBtn("Open site plan", `Open the site plan of ${p.name}`, async () => {
          try {
            if (p.recordings && p.listed < p.recordings - p.missing) setFiles(await api("/api/org", { action: "open_project", id: p.id }));
            else await refreshFiles();
            $("#dlg-openproj").close(); openMap(p.id);
          } catch (e) { err(e); }
        }, "primary"));
        box.appendChild(row);
      }
      $("#dlg-openproj").showModal(); return;
    }
    for (const p of list) {
      const row = el("div", "op-row");
      const dates = p.dates.length ? " · " + p.dates.map((d) => d.split("-").reverse().join("/")).join(", ") : "";
      row.innerHTML = `<div><b>${esc(p.name)}</b><br><span class="small muted">${plural(p.surveys, "survey")} · ${plural(p.cameras, "camera")} · ${plural(p.recordings, "recording")}${dates}${p.missing ? ` · ${p.missing} not found` : ""}${p.listed ? ` · ${p.listed} already listed` : ""}</span></div>`;
      const already = p.recordings > 0 && p.listed >= p.recordings - p.missing;
      const b = smallBtn(already ? "Already open" : "Open", already ? `${p.name} is already open: all its recordings are listed` : `List every recording in ${p.name}`, async () => {
        try {
          const o = await api("/api/org", { action: "open_project", id: p.id, replace: $("#op-replace").checked });
          setFiles(o); $("#dlg-openproj").close();
          toast(`${p.name}: ${plural(o.opened, "recording")} listed.`);
          if (o.first) openRec(o.first);
        } catch (e) { err(e); }
      }, already ? "" : "primary");
      if (already) b.disabled = true;
      row.appendChild(b); box.appendChild(row);
    }
    $("#op-replace").checked = false; $("#dlg-openproj").showModal();
  } catch (e) { err(e); }
}
$("#om-open").onclick = () => { toggleMenu("#open-menu", "#btn-open", false); openProjectList(false); };
$("#om-topen").onclick = () => { toggleMenu("#open-menu", "#btn-open", false); openProjectList(true); };
// the start window: shown when the program opens
for (const [id, go] of [["#sd-open", () => openProjectList(false)], ["#sd-new", () => newProject(false)],
                        ["#sd-topen", () => openProjectList(true)], ["#sd-tnew", () => newProject(true)]])
  $(id).onclick = () => { $("#dlg-start").close(); go(); };
function showStart() {
  const n = (S.files || []).length;
  $("#sd-note").textContent = n ? `${plural(n, "recording")} still listed from last time. Skip to carry on with them.` : "";
  try { if (sessionStorage.getItem("td-started")) return; sessionStorage.setItem("td-started", "1"); } catch (e) {}
  $("#dlg-start").showModal();
}
$("#btn-empty-add").onclick = () => openAdd();
function setEmpty(msg, button) { $("#empty-msg").textContent = msg; $("#btn-empty-add").hidden = !button; }
async function browse(kind) {
  const btns = [$("#btn-browse-files"), $("#btn-browse-folder")], msg = $("#pick-msg");
  btns.forEach((b) => (b.disabled = true));
  msg.hidden = false; msg.className = "small muted";
  msg.textContent = "Opening the Windows chooser… if you can't see it, check the taskbar.";
  try {
    const r = await api("/api/pick", { kind });
    if (!r.paths.length) { msg.textContent = "Nothing chosen."; return; }
    const box = $("#folder-input"); box.value = (box.value.trim() ? box.value.trim() + "\n" : "") + r.paths.join("\n"); sizeBox();
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
    const t = addTarget();
    if (t && t.project && t.project.name && (S.tree || []).some((p) => p.name.toLowerCase() === t.project.name.toLowerCase()))
      return toast(`There's already a project called ${t.project.name}. Nothing was added: choose it from the Project list, or give the new project another name.`, 8000);
    const r = await api("/api/add", { paths, replace: $("#add-replace").checked, target: t });
    setFiles(r);
    if (r.problems && r.problems.length) toast(r.problems.join("; "), 7000);
    else if (r.joined) toast(`Each camera's recordings are joined into one continuous recording. To review them one by one, click Separate files on the camera.`, 7000);
    if (r.first) openRec(r.first);   // show the first recording added
  } catch (e) { err(e); }
});
function movedNote(r) {
  if (r.problems && r.problems.length) toast(r.problems.join("; "), 7000);
  else if (r.joined) toast("The camera's recordings are joined into one continuous recording. To review them one by one, click Separate files on the camera.", 7000);
}
function setFiles(r) {
  S.files = r.files || []; S.tree = r.tree || []; S.unassigned = r.unassigned || []; renderFiles();
  if (r.damaged && r.damaged.length) toast(`Couldn't read ${r.damaged.join(", ")}: it may have been damaged (for example while syncing). It's been kept as a copy ending ".damaged-…" beside it, and that information starts again. Details are in error_log.txt.`, 12000);
}
function hhmm(iso) { return iso ? ukTime(Date.parse(iso)).d.toISOString().substr(11, 5) : ""; }
function nameBox(cls, value, label, onSave, placeholder) {
  const i = document.createElement("input"); i.type = "text"; i.maxLength = 40; i.className = cls; i.value = value;
  i.setAttribute("aria-label", label); i.title = "Click to rename"; if (placeholder) i.placeholder = placeholder;
  i.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); i.blur(); } if (e.key === "Escape") { i.value = value; i.blur(); } };
  i.onchange = async () => { const v = i.value.trim(); if (v === value || (!v && !placeholder)) { i.value = value; return; } try { await onSave(v); } catch (e) { i.value = value; err(e); } };
  return i;
}
function el(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
function smallBtn(text, title, onclick, cls = "") { const b = el("button", "btn xs " + cls, text); b.type = "button"; b.title = title; b.onclick = onclick; return b; }
function binBtn(what, onYes) {
  const b = el("button", "rm bin", ICON_BIN); b.type = "button"; b.title = `Delete ${what}`; b.setAttribute("aria-label", `Delete ${what}`);
  b.onclick = () => { if (confirm(`Delete ${what}? Its recordings move to Unassigned; no files are deleted.`)) onYes(); };
  return b;
}
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
// drag a recording onto a camera box (or the Unassigned box) to move it there
function dropZone(box, cameraId) {
  box.addEventListener("dragover", (e) => { if (S.dragPath) { e.preventDefault(); e.stopPropagation(); box.classList.add("drop"); } });
  box.addEventListener("dragleave", (e) => { if (!box.contains(e.relatedTarget)) box.classList.remove("drop"); });
  box.addEventListener("drop", async (e) => {
    e.preventDefault(); e.stopPropagation(); box.classList.remove("drop");
    const p = S.dragPath; S.dragPath = null; if (!p) return;
    const f = fileRow(p); if (f && f.camera_id === cameraId) return;
    try { movedNote(await org({ action: "move", paths: [p], camera: cameraId })); } catch (er) { err(er); }
  });
}
function fileCard(f, cameraId, opt = {}) {
  const w = el("div", "file-wrap" + (opt.member ? " member" : "") + (f.joined ? " joined" : ""));
  const b = el("button", "file" + (S.rec && S.rec.path === f.path ? " cur" : ""));
  b.title = f.path + "\nDrag onto a camera to move it there"; w.draggable = true;
  const k = f.status === "Reviewed" ? "ok" : f.status === "In review" ? "todo" : "";
  const times = f.start ? `${hhmm(f.start)}–${hhmm(f.end)} · ` : "";
  b.innerHTML = `<span class="file-name">${f.joined ? '<span class="join-tag">Joined</span> ' : ""}${esc(f.name)}<br><span class="small muted">${times}${f.size_gb} GB${f.joined ? ` · ${plural(f.members.length, "recording")}` : ""}</span></span>${opt.member ? "" : `<span class="chip ${k}">${esc(f.status)}</span>`}`;
  b.onclick = () => openRec(f.path);
  if (f.joined) { b.title = "These recordings played, scanned and reviewed as one. Gaps between them show as a flat line at zero."; w.draggable = false; w.append(b); return w; }
  w.addEventListener("dragstart", (e) => { S.dragPath = f.path; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", f.name); w.classList.add("dragging"); });
  w.addEventListener("dragend", () => { S.dragPath = null; w.classList.remove("dragging"); document.querySelectorAll(".drop").forEach((x) => x.classList.remove("drop")); });
  // the same move without dragging
  const mv = el("select", "cam-move"); mv.setAttribute("aria-label", `Move ${f.name} to another camera`); mv.title = "Move to another camera";
  mv.innerHTML = `<option value="" selected disabled>Move recording to…</option>` + (cameraId ? '<option value="__none">Unassigned</option>' : "")
    + (S.tree || []).map((pj) => pj.surveys.map((sv) => `<optgroup label="${esc(pj.name)} › ${esc(sv.label)}">${sv.cameras.filter((c) => c.id !== cameraId).map((c) => `<option value="${c.id}">${esc(c.label)}</option>`).join("")}</optgroup>`).join("")).join("");
  mv.onchange = async () => { try { movedNote(await org({ action: "move", paths: [f.path], camera: mv.value === "__none" ? "" : mv.value })); } catch (e) { err(e); } };
  const x = el("button", "rm", "×"); x.type = "button";
  x.setAttribute("aria-label", `Remove ${f.name} from the list`); x.title = "Remove from the list (the file isn't deleted)";
  x.onclick = async () => { try { const r = await api("/api/remove", { path: f.path }); if (S.rec && S.rec.path === f.path) location.reload(); setFiles(r); } catch (e) { err(e); } };
  w.append(b, mv, x);
  return w;
}
// Projects, surveys and cameras fold up: the ▸/▾ beside each name. Remembered on this computer.
S.folded = (() => { try { return new Set(JSON.parse(localStorage.getItem("td-folded") || "[]")); } catch (e) { return new Set(); } })();
// Projects and surveys start open; cameras start folded (their files hidden),
// so for a camera what's remembered is that it was opened ("open:<id>").
function isFolded(id, cam) { return cam ? !S.folded.has("open:" + id) : S.folded.has(id); }
function setFolded(id, cam, f) { const k = cam ? "open:" + id : id; if (cam ? !f : f) S.folded.add(k); else S.folded.delete(k); }
function saveFolded() { try { localStorage.setItem("td-folded", JSON.stringify([...S.folded])); } catch (er) {} }
function foldBtn(id, what, box, cam = false) {
  const b = el("button", "fold", isFolded(id, cam) ? "▸" : "▾"); b.type = "button";
  const set = () => { const f = isFolded(id, cam); box.classList.toggle("folded", f); b.textContent = f ? "▸" : "▾";
    b.setAttribute("aria-expanded", String(!f)); b.title = `${f ? "Expand" : "Collapse"} ${what}`; b.setAttribute("aria-label", b.title); };
  b.onclick = (e) => { e.stopPropagation(); setFolded(id, cam, !isFolded(id, cam)); saveFolded(); set(); };
  set(); return b;
}
function renderFiles() {
  try { syncCamCycle(); } catch (e) {}
  const box = $("#files"); box.innerHTML = "";
  const tree = S.tree || [], un = S.unassigned || [];
  if (!S.files.length && !tree.length) { box.innerHTML = '<p class="muted small">Add .ats files, or a whole folder of them, with the folder button at the top.</p>'; return; }
  // Unassigned, above the projects
  if (un.length || S.files.length) {
    const ug = el("div", "un-group");
    const uh = el("div", "un-head", `<span class="lvl">Unassigned</span><span class="small muted">${plural(un.length, "recording")}</span>`);
    ug.appendChild(uh);
    if (!un.length) ug.appendChild(el("p", "small muted drop-hint", "Drag a recording here to take it out of its camera."));
    for (const p of un) { const f = fileRow(p); if (f) ug.appendChild(fileCard(f, "")); }
    if (un.length) { const us = smallBtn("Scan unassigned", "Scan every unassigned recording", () => scanGroup("unassigned", "the unassigned recordings"), "scan-btn"); uh.appendChild(us); }
    dropZone(ug, ""); box.appendChild(ug);
  }
  for (const pj of tree) {
    const pg = el("div", "proj-group");
    const lv = el("div", "lvl-row"); lv.appendChild(el("span", "lvl", "Project")); lv.appendChild(projMenu(pj)); pg.appendChild(lv);
    const ph = el("div", "proj-head", ICON_PROJ);
    ph.prepend(foldBtn(pj.id, `project ${pj.name}`, pg));
    ph.appendChild(nameBox("proj-name", pj.name, "Project name", (v) => org({ action: "rename", id: pj.id, name: v })));

    const psub = el("div", "cam-sub proj-sub", `<span class="small muted">${plural(pj.surveys.length, "survey")} · ${plural(pj.paths.length, "recording")}</span>`);
    const pb = el("span", "row-btns");
    pb.append(smallBtn("Site Plan", `Site plan of ${pj.name}: the site, where each camera and acoustic detector was and which way each camera looked`, () => openMap(pj.id), "map-btn"),
              smallBtn("+ Survey", `Add a survey (a visit or night) to ${pj.name}`, () => org({ action: "new_survey", project: pj.id }).catch(err)),
              smallBtn("Scan project", `Scan every recording in ${pj.name}`, () => scanGroup(pj.id, pj.name), "scan-btn"));
    psub.appendChild(pb); pg.append(ph, psub);
    for (const sv of pj.surveys) {
      const sg = el("div", "sv-group");
      const sh = el("div", "sv-head", ICON_SV + `<span class="sv-title">Survey ${sv.no}</span>`);
      sh.prepend(foldBtn(sv.id, `Survey ${sv.no}`, sg));
      const d = el("input", "sv-date"); d.type = "date"; d.value = sv.date || ""; d.title = "Survey date (optional)"; d.setAttribute("aria-label", `Survey ${sv.no} date`);
      d.onchange = () => org({ action: "set_date", id: sv.id, date: d.value }).catch(err);
      sh.append(d, binBtn(`Survey ${sv.no} of ${pj.name}`, () => org({ action: "delete", id: sv.id }).catch(err)));
      const ssub = el("div", "cam-sub", `<span class="small muted">${plural(sv.cameras.length, "camera")} · ${plural(sv.paths.length, "recording")}</span>`);
      const sb = el("span", "row-btns");
      sb.append(smallBtn("+ Camera", `Add a camera to Survey ${sv.no}`, () => org({ action: "new_camera", survey: sv.id }).catch(err)),
                smallBtn("Scan survey", `Scan every recording in Survey ${sv.no}`, () => scanGroup(sv.id, `Survey ${sv.no}`), "scan-btn"));
      ssub.appendChild(sb); sg.append(sh, ssub);
      if ((sv.detectors || []).length) {
        const dl = el("button", "det-line small", `<span class="det-pin-s">A</span> ${plural(sv.detectors.length, "acoustic detector")}: ${sv.detectors.map((d) => esc(d.name)).join(", ")}`);
        dl.type = "button"; dl.title = "Open the site plan"; dl.onclick = () => { MAPS.sv = sv.id; openMap(pj.id); }; sg.appendChild(dl);
      }
      for (const cam of sv.cameras) {
        const g = el("div", "cam-group"); g.dataset.cam = cam.id;
        const head = el("div", "cam-head", ICON_CAM + `<span class="cam-no">Camera ${cam.no}</span>`);
        head.prepend(foldBtn(cam.id, `Camera ${cam.no}`, g, true));
        head.appendChild(nameBox("cam-name", cam.name, `Camera ${cam.no} name`, (v) => org({ action: "rename", id: cam.id, name: v }), "Add a name"));
        const others = tree.flatMap((p) => p.surveys.filter((s) => s.id !== sv.id).map((s) => [s.id, `${p.name} › ${s.label}`]));
        head.appendChild(binBtn(`Camera ${cam.no}`, () => org({ action: "delete", id: cam.id }).catch(err)));
        let moveCam = null;
        if (others.length) {   // move the whole camera to another survey
          const mc = el("select", "cam-move"); mc.title = "Move this camera to another survey"; mc.setAttribute("aria-label", `Move Camera ${cam.no} to another survey`);
          mc.innerHTML = `<option value="" selected disabled>Move camera to survey…</option>` + others.map(([id, l]) => `<option value="${id}">${esc(l)}</option>`).join("");
          mc.onchange = () => org({ action: "move_camera", id: cam.id, survey: mc.value }).catch((e) => { err(e); mc.value = ""; });
          moveCam = mc;
        }
        const sub = el("div", "cam-sub", `<span class="small muted">${plural(cam.paths.length, "recording")}</span>`);
        const cb = el("span", "row-btns");
        cb.append(smallBtn("+ Add files", `Add recordings to Camera ${cam.no}`, () => openAdd(cam.id)));
        if (cam.paths.length) {
          const tb = smallBtn("Test ROI Scan", TEST_TIP, () => testScan(cam.id, `Camera ${cam.no}`), "test-btn");
          tb.setAttribute("aria-description", TEST_TIP); cb.append(tb);
        }
        if (cam.paths.length) cb.append(smallBtn("Scan camera", `Scan every recording from Camera ${cam.no}`, () => scanGroup(cam.id, `Camera ${cam.no}`), "cam-scan scan-btn"));
        if (moveCam) cb.append(moveCam);

        sub.appendChild(cb); g.append(head, sub);
        for (const o of cam.overlaps || []) {
          const w = el("div", "cam-warn small", `<b>⚠ Times overlap:</b> ${esc(o.a)} and ${esc(o.b)} both cover ${hhmm(o.from)}–${hhmm(o.to)}. One camera records one file at a time, so check each is under the right camera.`);
          w.setAttribute("role", "alert"); g.appendChild(w);
        }
        if (cam.paths.length >= 2) {   // read the camera's consecutive files as one recording
          const jb = smallBtn(cam.join ? "Separate files" : "Join files", cam.join ? "Go back to scanning and reviewing each recording on its own" : "Play, scan and review this camera's recordings as one continuous recording, in time order. Gaps between them show as a flat line at zero.", async () => {
            try { const r = await org({ action: "join", id: cam.id, on: !cam.join }); if (r.opened) openRec(r.opened); else if (!S.rec || !fileRow(S.rec.path)) openRec(cam.paths[0]); } catch (e) { err(e); }
          }, cam.join ? "" : "join-btn");
          cb.prepend(jb);
        }
        if (!cam.paths.length) g.appendChild(el("p", "small muted drop-hint", "Drag recordings here, or use + Add files."));
        if (cam.joined && fileRow(cam.joined)) {
          g.appendChild(fileCard(fileRow(cam.joined), cam.id));
          g.appendChild(el("p", "small muted join-note", "Made from:"));
        }
        for (const path of cam.paths) { const f = fileRow(path); if (f) g.appendChild(fileCard(f, cam.id, { member: !!cam.joined })); }
        dropZone(g, cam.id);
        // a click anywhere on the camera's box (not its buttons, boxes or recordings) shows that camera
        if (cam.paths.length) {
          g.classList.add("pickable");
          if (S.rec && (cam.paths.includes(S.rec.path) || cam.joined === S.rec.path)) g.classList.add("showing");
          g.addEventListener("click", (e) => {
            if (e.target.closest("button, input, select, textarea, a, label, .file, .file-wrap")) return;
            openCamera(cam.id);
          });
        }
        sg.appendChild(g);
      }
      pg.appendChild(sg);
    }
    box.appendChild(pg);
  }
}
$("#btn-new-project").onclick = async () => {
  try { const r = await org({ action: "new_project" }); const at = findCam(r.created);
    const inp = at && [...document.querySelectorAll(".proj-name")].find((i) => i.value === at.project.name); if (inp) { inp.focus(); inp.select(); } } catch (e) { err(e); }
};
const TEST_TIP = "A quick scan can check if ROI is affected by background movement without scanning the full recording";
async function testScan(node, what) {
  try {
    const r = await api("/api/test-scan", { node });
    S.testNode = { node, what }; (S.watch = S.watch || new Set()).add(r.job.id);   // show the result even if it finishes before the next check
    toast(`Test ROI Scan of ${what}: scanning a random minute of ${r.job.label.replace(/^Test (ROI )?scan of /, "")}…`, 4000); pollJobs();
  } catch (e) { err(e); }
}
function showTestResult(t) {
  S.lastTest = t;
  const len = t.seconds >= 59 ? "one minute, chosen at random" : `${Math.round(t.seconds)} s${t.whole ? ": the whole recording, as it's shorter than a minute" : ""}`;
  $("#ts-sub").textContent = `${S.testNode ? S.testNode.what + " · " : ""}${t.name}, ${t.date} ${t.from}–${t.to} (${len}). Nothing is saved.`;
  const fv = (v) => v == null ? "" : (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)) + (isTemp(t.units) ? " " + t.units : "");
  const word = { low: "Low", moderate: "Moderate", high: "High" };
  let h = "";
  for (const x of t.rois) {
    const rating = x.rating || "none";
    h += `<div class="noise-row ${rating}"><span class="noise-chip" ${x.rating ? "" : 'title="Too few quiet frames in this stretch to judge the background"'}>${word[rating] || "Not enough data"}</span><span class="small"><b>${esc(x.name)}</b> · ${plural(x.spikes, "spike")} above the test level of ${fv(x.level)} (0.2 °C above the background)${x.sd != null ? ` · background ${fv(x.base)}, varies ±${fv(x.sd)}, small rises ${(x.rises * 100).toFixed(1)}% of the time` : ""}</span></div>`;
  }
  const bad = t.rois.filter((x) => x.rating && x.rating !== "low");
  const none = t.rois.every((x) => !x.rating);
  const msg = none ? "There were too few quiet frames in this stretch to judge the background. Test another minute, or use a longer recording."
    : bad.length ? "The background in this ROI moves or changes more than open sky. Something in it, such as branches, cloud, water or a cooling surface, will raise the detection level and can hide faint bats. Use View this minute to see what moves, then redraw the ROI to leave it out, or test another minute."
    : "The background looks steady: the ROI isn't picking up much movement. One minute is only a sample, so test another minute if the night was windy or cloud came over.";
  h += `<p class="small ${bad.length ? "" : "muted"}">${msg}</p>`;
  $("#ts-body").innerHTML = h;
  if (!$("#dlg-test").open) $("#dlg-test").showModal();
}
$("#ts-view").onclick = async () => {
  const t = S.lastTest; if (!t) return;
  $("#dlg-test").close();
  if (!S.rec || S.rec.path !== t.path) await openRec(t.path);
  S.lim = [t.a, t.b]; $("#in-window").checked = false; S.frame = t.a; drawLimits(); showFrame();
};
$("#ts-again").onclick = () => { if (S.testNode) { $("#dlg-test").close(); testScan(S.testNode.node, S.testNode.what); } };
// The ⚙ beside PROJECT: save, rename, site plan, close, reset, delete
function projMenu(pj) {
  const wrap = el("span", "pm-wrap");
  const b = el("button", "pm-btn", '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>');
  b.type = "button"; b.title = `Project options: ${pj.name}`; b.setAttribute("aria-label", b.title); b.setAttribute("aria-haspopup", "true");
  const m = el("div", "persist-menu pm-menu"); m.hidden = true; m.setAttribute("role", "menu");
  const item = (label, fn, cls = "") => { const i = el("button", "menu-item " + cls, label); i.type = "button"; i.setAttribute("role", "menuitem");
    i.onclick = async (e) => { e.stopPropagation(); m.hidden = true; try { await fn(); } catch (er) { err(er); } }; m.appendChild(i); };
  item("Save project", async () => { const r = await api("/api/org", { action: "save_project", id: pj.id }); toast(`${pj.name} saved. Project file: ${r.file}`, 8000); });
  item("Rename…", () => { const i = [...document.querySelectorAll(".proj-name")].find((x) => x.value === pj.name); if (i) { i.focus(); i.select(); } });
  item("Site plan…", () => openMap(pj.id));
  item(pj.template ? `New survey from site plan (${plural(pj.template, "camera")})` : "New survey", async () => {
    const r = await org({ action: "new_survey", project: pj.id }); if (r.from_template) toast("New survey made from the site plan: the same cameras, positions and lenses.", 6000); });
  if (pj.template) item("Stop using the site plan template", () => org({ action: "clear_template", project: pj.id }));
  const first = pj.paths[0];
  if (first) item("Open recordings folder", () => api("/api/open-path", { path: first.replace(/[\\/][^\\/]*$/, "") }));
  item("Close project", async () => { const r = await org({ action: "close_project", id: pj.id }); if (S.rec && !fileRow(S.rec.path)) location.reload(); toast(`${pj.name} closed (${plural(r.closed, "recording")} taken off the list). Open it again from the folder button > Open project.`, 7000); });
  item("Reset all decisions…", async () => {
    if (!confirm(`Reset every Confirm, Reject and classification on all recordings in ${pj.name}? Scans and comments are kept.`)) return;
    const r = await org({ action: "reset_project", id: pj.id }); if (S.rec) { S.rec = await api("/api/recording"); renderEvents(); drawPlot(); }
    toast(`Decisions reset on ${plural(r.reset, "recording")}.`); });
  item("Delete project…", async () => { if (!confirm(`Delete project ${pj.name}? Its recordings move to Unassigned; no files are deleted.`)) return; await org({ action: "delete", id: pj.id }); }, "danger");
  b.onclick = (e) => { e.stopPropagation(); const open = m.hidden; document.querySelectorAll(".pm-menu").forEach((x) => (x.hidden = true)); m.hidden = !open; };
  m.addEventListener("click", (e) => e.stopPropagation());
  wrap.append(b, m); return wrap;
}
document.addEventListener("click", () => document.querySelectorAll(".pm-menu").forEach((x) => (x.hidden = true)));
async function scanGroup(node, what) {
  try {
    const r = await api("/api/scan", { node });
    if (!r.jobs.length) return toast(`No recording in ${what} has an ROI drawn yet. Draw one, and tick "Use for every file from this camera" to share it.`, 7000);
    toast(`Scanning ${r.jobs.length} recording${r.jobs.length === 1 ? "" : "s"} from ${what}…` + (r.skipped ? ` ${r.skipped} skipped: no ROI drawn.` : ""), 6000); pollJobs();
  } catch (e) { err(e); }
}
// Tree: Project > Survey > Camera > recording, at a glance. Click a recording to open it.
function renderTree() {
  const t = $("#tree-body"), cur = S.rec && S.rec.path;
  const leaf = (p) => { const f = fileRow(p); return f ? `<li><button type="button" class="tree-file${p === cur ? " cur" : ""}" data-path="${esc(p)}">${esc(f.name)}</button> <span class="small muted">${f.start ? hhmm(f.start) + "–" + hhmm(f.end) : ""}</span></li>` : ""; };
  let h = "";
  for (const pj of S.tree || []) {
    h += `<li><details open><summary>${ICON_PROJ} <b>${esc(pj.name)}</b></summary><ul>`;
    for (const sv of pj.surveys) {
      h += `<li><details open><summary>${ICON_SV} ${esc(sv.label)}</summary><ul>`;
      for (const c of sv.cameras) h += `<li><details open><summary>${ICON_CAM} ${esc(c.label)} <span class="small muted">(${c.paths.length})</span></summary><ul>${c.paths.map(leaf).join("") || '<li class="small muted">No recordings</li>'}</ul></details></li>`;
      h += "</ul></details></li>";
    }
    h += "</ul></details></li>";
  }
  if ((S.unassigned || []).length) h += `<li><details open><summary><b>Unassigned</b></summary><ul>${S.unassigned.map(leaf).join("")}</ul></details></li>`;
  t.innerHTML = h ? `<ul class="tree">${h}</ul>` : '<p class="small muted">Nothing listed yet.</p>';
  t.querySelectorAll(".tree-file").forEach((b) => (b.onclick = () => { $("#dlg-tree").close(); openRec(b.dataset.path); }));
}
$("#btn-tree").onclick = () => { renderTree(); $("#dlg-tree").showModal(); };
$("#btn-fold-all").onclick = () => {
  const ids = (S.tree || []).flatMap((p) => [[p.id, false], ...p.surveys.flatMap((s) => [[s.id, false], ...s.cameras.map((c) => [c.id, true])])]);
  const anyOpen = ids.some(([i, cam]) => !isFolded(i, cam));
  for (const [i, cam] of ids) setFolded(i, cam, anyOpen);
  saveFolded(); renderFiles();
};
$("#tree-expand").onclick = () => $("#tree-body").querySelectorAll("details").forEach((d) => (d.open = true));
$("#tree-collapse").onclick = () => $("#tree-body").querySelectorAll("details").forEach((d) => (d.open = false));
async function refreshFiles() { try { setFiles(await api("/api/files")); } catch (e) {} }

async function openRec(path) {
  stopPlay();
  setEmpty("Opening…", false);
  try {
    S.rec = await api("/api/open", { path });
    S.rng = { raw: null, review: null, path: null, blend: null, custom: null }; S.track = {}; S.info = null;   // each recording starts on Auto
    S.frame = 0; S.sel = null; S.ws = 0; S.we = S.rec.frames - 1; S.pts = S.rec.roi || []; S.lim = null; S.times = null;
    if (!S.linking) $("#linked-bar").hidden = true;
    $("#scrub").max = S.rec.frames - 1;
    ["#btn-roi-clear", "#btn-roi-pick"].forEach((s) => ($(s).disabled = false));
    document.querySelectorAll(".shape-btn").forEach((b) => (b.disabled = false));
    S.roiHidden = new Set(); S.roiActive = (S.rec.rois[0] || {}).id; renderRois();
    $("#empty").hidden = true;
    renderFiles(); updateRoiStatus(); await loadActivity(); renderEvents(); renderComments(); renderFilters(); showFrame();
    loadTimes(S.rec.path);   // exact frame times, in the background
  } catch (e) { setEmpty("Could not open this file.", true); err(e); }
}

// ------------------------------------------------------------ frames
const img = $("#view");
let pending = false, queued = false;
// visible range per viewing mode: null = automatic, otherwise [lo, hi]
S.rng = { raw: null, review: null, path: null, blend: null, custom: null }; S.track = {}; S.pal = "white"; S.palettes = []; S.evDraft = {};
function frameUrl(i) {
  const r = S.mode === "review" ? null : S.rng[S.mode], q = r ? `&lo=${r[0]}&hi=${r[1]}` : "";
  let op = (S.mode === "blend" ? `&op=${$("#opacity").value}&bm=${$("#blend").value}` : "") + enhQuery();
  if (S.mode === "custom") op += `&cf=${encodeURIComponent(JSON.stringify(customSpec()))}`;
  const hide = S.roiHidden && S.roiHidden.size ? `&hide=${[...S.roiHidden].join(",")}` : "";
  return `/api/frame?i=${i}&mode=${S.mode}&ws=${S.ws}&roi=${S.drawing ? 0 : 1}${hide}&pal=${S.pal}${q}${op}&t=${Date.now()}`;
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
  $("#gap-badge").hidden = !(S.rec.gaps || []).some(([a, b]) => S.frame >= a && S.frame <= b);
  $("#scrub").value = S.frame;
  positionCursor();
  syncLock(); drawLimits();
  updateCommentBox();
}
img.onload = () => { pending = false; drawRoi(); if (queued) { queued = false; showFrame(); } if (S.playing) S._onFrame && S._onFrame(); };
img.onerror = () => { pending = false; if (S.playing) stopPlay(); };
window.addEventListener("resize", () => { drawRoi(); drawPlot(); });

function setMode(m) {
  S.mode = m;
  document.querySelectorAll(".mode[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === m)));
  $("#btn-persist").classList.toggle("on", m === "blend");
  $("#custom-wrap").hidden = m !== "custom";
  if (m === "custom") renderCustomPick();
  syncEnh();
  showFrame();
}
document.querySelectorAll(".mode[data-mode]").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));
// dropdowns: trail persistence (the ▾ on Detection) and Palette & image
function toggleMenu(menu, btn, open, focus) {
  const m = $(menu), want = open ?? m.hidden;
  m.hidden = !want; $(btn).setAttribute("aria-expanded", String(want));
  if (want && focus) $(focus).focus();
}
const togglePersist = (open) => toggleMenu("#persist-menu", "#btn-persist", open, "#f-frames");
const toggleImage = (open) => toggleMenu("#image-menu", "#btn-image", open, "#palette");
// only one dropdown open at a time
function closeMenus(except) {
  for (const [k, m, b] of [["persist", "#persist-menu", "#btn-persist"], ["image", "#image-menu", "#btn-image"],
                           ["roi", "#roi-menu", "#btn-roi-pick"], ["open", "#open-menu", "#btn-open"]])
    if (k !== except && !$(m).hidden) toggleMenu(m, b, false);
}
$("#btn-persist").onclick = (e) => { e.stopPropagation(); closeMenus("persist"); togglePersist(); };
$("#btn-image").onclick = (e) => { e.stopPropagation(); closeMenus("image"); toggleImage(); };
$("#persist-menu").addEventListener("click", (e) => e.stopPropagation());
$("#image-menu").addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("click", () => closeMenus());
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); });
$("#scrub").oninput = () => { stopPlay(); S.frame = +$("#scrub").value; showFrame(); };
$("#btn-step").onclick = () => S.rec && goFrame(S.frame + 1);
$("#btn-step-back").onclick = () => S.rec && goFrame(S.frame - 1);

// playback: frames are requested one after another, so the server keeps filter state
const PLAY_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5v14l11-7z"/></svg>';
const PAUSE_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>';
// Play limits: playback runs between the start and end handles on the
// progress bar. "Lock Play Limits to Current Event" makes them follow the
// selected event's window; otherwise they stay where the user put them.
function locked() { return !!(S.sel && $("#in-window").checked); }
function playBounds() {
  if (!S.rec) return [0, 0];
  if (locked()) return [S.ws, S.we];
  return S.lim ? [...S.lim] : [0, S.rec.frames - 1];
}
function isWhole(b) { return !S.rec || (b[0] <= 0 && b[1] >= S.rec.frames - 1); }
function syncLock() {
  const on = !!S.sel;
  $("#in-window").disabled = !on;
  $("#loop-wrap").classList.toggle("off", !on);
  $("#loop-wrap").title = on ? "Keep the play limits on the selected event's window" : "Select an event to use this";
}
function limPos(f) { const n = Math.max(1, S.rec.frames - 1); return `calc(8px + (100% - 16px) * ${f / n})`; }
function drawLimits() {
  const has = !!S.rec;
  for (const id of ["#lim-a", "#lim-b", "#lim-fill"]) $(id).hidden = !has;
  if (!has) { $("#lim-label").textContent = ""; $("#btn-lim-reset").hidden = true; return; }
  const [a, b] = playBounds(), n = Math.max(1, S.rec.frames - 1);
  $("#lim-a").style.left = limPos(a); $("#lim-b").style.left = limPos(b);
  $("#lim-fill").style.left = limPos(a); $("#lim-fill").style.width = `calc((100% - 16px) * ${(b - a) / n})`;
  const whole = isWhole([a, b]);
  $("#lim-label").textContent = whole ? "Play limits: whole recording. Drag the blue markers to set your own."
    : `Play limits: ${fmtTime(a)} → ${fmtTime(b)} (${fmtDur(spanS(a, b))})${locked() ? " · locked to event " + S.sel : ""}`;
  $("#btn-lim-reset").hidden = whole || locked();
}
function limDrag(which, e) {
  if (!S.rec) return;
  e.preventDefault(); e.stopPropagation();
  if (locked()) { S.lim = playBounds(); $("#in-window").checked = false; }   // moving a marker unlocks it from the event
  if (!S.lim) S.lim = [0, S.rec.frames - 1];
  const wrap = $("#scrub-wrap"), n = S.rec.frames - 1;
  const move = (ev) => {
    const r = wrap.getBoundingClientRect(), f = Math.round(Math.max(0, Math.min(1, (ev.clientX - r.left - 8) / (r.width - 16))) * n);
    if (which === "a") S.lim[0] = Math.min(f, S.lim[1] - 1); else S.lim[1] = Math.max(f, S.lim[0] + 1);
    drawLimits();
  };
  const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); drawLimits(); };
  window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
}
$("#lim-a").addEventListener("pointerdown", (e) => limDrag("a", e));
$("#lim-b").addEventListener("pointerdown", (e) => limDrag("b", e));
for (const [id, k] of [["#lim-a", 0], ["#lim-b", 1]]) {   // arrow keys nudge a marker (Shift = 1 s)
  $(id).addEventListener("keydown", (e) => {
    if (!S.rec || !["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    e.preventDefault(); e.stopPropagation();
    if (locked()) { S.lim = playBounds(); $("#in-window").checked = false; }
    if (!S.lim) S.lim = [0, S.rec.frames - 1];
    const step = (e.shiftKey ? Math.round(S.rec.fps) : 1) * (e.key === "ArrowRight" ? 1 : -1), n = S.rec.frames - 1;
    const v = Math.max(0, Math.min(n, S.lim[k] + step));
    if (k === 0 && v < S.lim[1]) S.lim[0] = v; if (k === 1 && v > S.lim[0]) S.lim[1] = v;
    drawLimits();
  });
}
$("#btn-lim-reset").onclick = () => { S.lim = null; drawLimits(); };
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
$("#in-window").onchange = () => { if (!$("#in-window").checked && S.sel && !S.lim) S.lim = [S.ws, S.we]; showFrame(); };

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
    ? "0% = thermal only, 100% = trails only"
    : "How solid the trails are over the thermal picture";
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
const APP_VERSION = "2026.11.18-autojoin";
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
    } else if (S.pts.length >= 3) {   // the line that will close the shape when it's finished
      const [lx, ly] = S.pts[S.pts.length - 1];
      h += `<line x1="${lx}" y1="${ly}" x2="${S.pts[0][0]}" y2="${S.pts[0][1]}" stroke="#E5484D" stroke-width="1.5" stroke-dasharray="6 5" opacity=".7" vector-effect="non-scaling-stroke"/>`;
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
  if (!S.drawing || S.shape === "poly" || e.button !== 0) return;   // right-click finishes instead
  const t = e.target, p = toImg(e);
  if (t.dataset.h) S.drag = { kind: t.dataset.h, p0: p, b0: { ...S.box } };
  else if (t.dataset.body) S.drag = { kind: "move", p0: p, b0: { ...S.box } };
  else { S.drag = { kind: "new", p0: p, b0: { x0: p[0], y0: p[1], x1: p[0], y1: p[1] }, prev: S.box && { ...S.box } }; S.box = { ...S.drag.b0 }; }   // drag out a new shape
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
svg.addEventListener("pointerup", (e) => {
  if (!S.drag) return;
  {   // a click (no drag) once the shape has been drawn sets the ROI
    const b0 = svg.getBoundingClientRect(), sc = b0.width / img.naturalWidth, p = toImg(e);
    const moved = Math.hypot(p[0] - S.drag.p0[0], p[1] - S.drag.p0[1]) * sc;
    if (moved < 4 && S.shapeDragged) { S.box = S.drag.kind === "new" ? S.drag.prev : S.drag.b0; S.drag = null; drawRoi(); finishRoi(); return; }
    if (moved >= 4) S.shapeDragged = true;
  }
  const b = S.box;   // keep edges in order and the shape a sensible size
  S.box = { x0: Math.min(b.x0, b.x1), y0: Math.min(b.y0, b.y1), x1: Math.max(b.x0, b.x1), y1: Math.max(b.y0, b.y1) };
  if (S.box.x1 - S.box.x0 < 8 || S.box.y1 - S.box.y0 < 8) S.box = S.drag.b0.x1 - S.drag.b0.x0 >= 8 ? S.drag.b0 : defaultBox();
  S.drag = null; drawRoi();
  if (S.drawing && S.shape !== "poly") saveShape();   // saved each time you let go; keep adjusting until Done

});
svg.addEventListener("pointerleave", () => { if (S.shape === "poly") { S.hover = null; drawRoi(); } });
svg.addEventListener("click", (e) => {
  if (!S.drawing || S.shape !== "poly") return;
  S.pts.push(toImg(e).map(Math.round)); drawRoi();
});
function setShape(sh) {
  S.shape = sh; if (sh !== "poly" && !S.box) S.box = defaultBox();
  document.querySelectorAll("[data-shape]").forEach((b) => b.setAttribute("aria-pressed", String(S.drawing && b.dataset.shape === sh)));
  toggleRoiButtons();
  updateRoiStatus();
  drawRoi();
}
// picking a shape from the ROI toolbar starts drawing it; picking another while drawing switches shape
function startRoi(sh) {
  if (!S.rec) return;
  if (!S.drawing) {
    S.drawing = true; S.pts = []; S.box = null; S.hover = null; S.roiSaved = false; S.shapeDragged = false;
    S.roiOrig = (activeRoi().points || []).map((q) => q.slice()); S.roiOrigChanged = !!activeRoi().changed;
    $("#stage").classList.add("drawing"); setMode("raw");
    const p = activeRoi().points || [];   // a rectangle or circle starts on the ROI's current outline
    if (sh !== "poly" && p.length >= 3) {
      const xs = p.map((q) => q[0]), ys = p.map((q) => q[1]);
      S.box = { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
    }
  }
  setShape(sh);
}
document.querySelectorAll("[data-shape]").forEach((b) => (b.onclick = () => startRoi(b.dataset.shape)));
// right-click on the picture finishes the ROI; an open polygon is closed back to its first point
$("#stage").addEventListener("contextmenu", (e) => { if (!S.drawing) return; e.preventDefault(); finishRoi(); });
$("#btn-roi-undo").onclick = () => { S.pts.pop(); drawRoi(); };
// a rectangle or circle is saved every time you let go, without leaving drawing,
// so it can be moved and resized as often as needed. Cancel puts back the outline it had.
async function saveShape() {
  try { S.rec = await api("/api/roi", { id: S.roiActive, points: shapePoints(), all_files: $("#roi-all").checked }); S.roiSaved = true; renderRois(); }
  catch (e) { err(e); }
}
async function finishRoi() {
  const pts = shapePoints();
  if (pts.length < 3) return toast("Add at least 3 points first, then right-click to finish.");
  S.drawing = false; S.hover = null; $("#stage").classList.remove("drawing"); setShape(S.shape);
  try { S.rec = await api("/api/roi", { id: S.roiActive, points: pts, all_files: $("#roi-all").checked }); renderRois(); refreshFiles(); showFrame(); toast(`${activeRoi().name} saved. Scan it from the recordings list: Scan camera, Scan project or Scan unassigned.`, 5000); }
  catch (e) { err(e); }
}
$("#btn-roi-done").onclick = finishRoi;
$("#btn-roi-cancel").onclick = async () => {
  S.drawing = false; S.hover = null; $("#stage").classList.remove("drawing"); setShape(S.shape);
  if (S.roiSaved) { S.roiSaved = false; try { S.rec = await api("/api/roi", { id: S.roiActive, points: S.roiOrig || [], all_files: $("#roi-all").checked, restore: true, was_changed: S.roiOrigChanged }); renderRois(); } catch (e) { err(e); } }
  showFrame();
};
document.addEventListener("keydown", (e) => {
  if (!S.drawing || e.target.closest("input, select, textarea, dialog")) return;
  if (e.key === "Enter") { e.preventDefault(); finishRoi(); }
  else if (e.key === "Backspace" && S.shape === "poly") { e.preventDefault(); S.pts.pop(); drawRoi(); }
  else if (e.key === "Escape") $("#btn-roi-cancel").click();
}, true);
$("#btn-roi-clear").onclick = async () => { try { S.pts = []; S.rec = await api("/api/roi", { id: S.roiActive, points: [], all_files: $("#roi-all").checked }); renderRois(); showFrame(); } catch (e) { err(e); } };
function toggleRoiButtons() {
  $("#btn-roi-done").hidden = $("#btn-roi-cancel").hidden = !S.drawing;
  $("#btn-roi-undo").hidden = !S.drawing || S.shape !== "poly";
  $("#btn-roi-clear").hidden = S.drawing;
  $("#btn-roi-clear").disabled = !(S.rec && (activeRoi().points || []).length);
}
function updateRoiStatus() {
  const el = $("#roi-status");
  if (S.drawing) {
    el.textContent = S.shape === "poly"
      ? "Click round the roost to add points. Right-click (or Enter) to finish: the last point joins back to the first. Backspace removes a point."
      : "Drag on the picture to draw it, drag the middle to move it, or drag a handle to resize, as often as you like. Then click once anywhere on the picture to set it.";
    return;
  }
  if (!S.rec) { el.textContent = "Open a recording, then pick a shape to draw round the roost."; return; }
  const r = activeRoi(), n = (r.points || []).length;
  el.textContent = n ? `${r.name} is drawn. Pick a shape to redraw it, or + Add ROI from the ▾ menu for another.` : `${r.name}: pick a shape, then draw round the roost.`;
  toggleRoiButtons();
}

// ------------------------------------------------------------ several ROIs
// Each ROI has a name and a colour. The selected one is what the shape
// buttons draw. Hidden ROIs are left off the picture and the Event Log.
const EYE = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';
const EYE_OFF = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M17.9 17.9A10.5 10.5 0 0 1 12 19c-7 0-11-7-11-7a19 19 0 0 1 5-5.9M9.9 4.2A9.6 9.6 0 0 1 12 4c7 0 11 7 11 7a19 19 0 0 1-2.2 3.2M1 1l22 22"/></svg>';
function rois() { return (S.rec && S.rec.rois) || []; }
function activeRoi() { return rois().find((r) => r.id === S.roiActive) || rois()[0] || { id: "r1", name: "ROI 1", points: [], colour: "#E5484D" }; }
function roiById(id) { return rois().find((r) => r.id === id); }
function roiVisible(id) { return !(S.roiHidden && S.roiHidden.has(id)); }
function roiShare() { return $("#roi-all").checked; }
async function roiAction(body) {
  try { const r = await api("/api/rois", { ...body, all_files: roiShare() }); S.rec = r; return r; } catch (e) { err(e); return null; }
}
function renderRois() {
  if (!S.rec) return;
  if (!roiById(S.roiActive)) S.roiActive = (rois()[0] || {}).id;
  const a = activeRoi();
  $("#roi-cur-name").textContent = a.name; $("#roi-cur-dot").style.background = a.colour;
  // the ROI manager
  const list = $("#roi-list"); list.innerHTML = "";
  for (const r of rois()) {
    const row = document.createElement("div"); row.className = "roi-row" + (r.id === S.roiActive ? " active" : "");
    const vis = roiVisible(r.id), n = (r.points || []).length;
    row.innerHTML = `<input type="radio" name="roi-active" aria-label="Draw ${esc(r.name)}" ${r.id === S.roiActive ? "checked" : ""}>
      <i class="roi-dot" style="background:${r.colour}"></i>
      <input type="text" value="${esc(r.name)}" maxlength="40" aria-label="Name of ${esc(r.name)}">
      <span class="roi-pts">${n ? "drawn" : "not drawn"}</span>
      <label class="roi-scan" title="${n >= 3 ? "Include this ROI when scanning" : "Draw it first"}"><input type="checkbox" ${r.scan && n >= 3 ? "checked" : ""} ${n >= 3 ? "" : "disabled"}> Scan</label>
      <button type="button" class="ib eye${vis ? "" : " off"}" aria-pressed="${vis}" title="${vis ? "Hide" : "Show"} ${esc(r.name)}">${vis ? EYE : EYE_OFF}</button>
      <button type="button" class="ib del" title="Delete ${esc(r.name)}" ${rois().length < 2 ? "disabled" : ""}>×</button>`;
    row.querySelector("[type=radio]").onchange = () => { S.roiActive = r.id; renderRois(); };
    const nm = row.querySelector("[type=text]");
    nm.onfocus = () => { if (S.roiActive !== r.id) { S.roiActive = r.id; row.classList.add("active"); $("#roi-cur-name").textContent = r.name; $("#roi-cur-dot").style.background = r.colour; } };
    nm.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); nm.blur(); } };
    nm.onchange = async () => { const v = nm.value.trim(); if (!v) { nm.value = r.name; return; } if (await roiAction({ action: "rename", id: r.id, name: v })) { renderRois(); renderEvents(); drawPlot(); showFrame(); } };
    row.querySelector(".eye").onclick = () => toggleRoiVisible(r.id);
    row.querySelector(".roi-scan input").onchange = async (e) => { if (await roiAction({ action: "scan", id: r.id, scan: e.target.checked })) renderRois(); };
    row.querySelector(".del").onclick = async () => {
      if (!confirmTwice(row.querySelector(".del"), `Click again to delete ${r.name} and its events`)) return;
      if (await roiAction({ action: "delete", id: r.id })) { S.roiHidden.delete(r.id); afterRoiChange(); toast(`${r.name} deleted.`); }
    };
    list.appendChild(row);
  }
  renderLegend(); updateRoiStatus();
}
// a delete button asks for a second click instead of a pop-up
function confirmTwice(btn, msg) {
  if (btn.dataset.armed && Date.now() - +btn.dataset.armed < 4000) { delete btn.dataset.armed; return true; }
  btn.dataset.armed = Date.now(); btn.title = msg; toast(msg, 4000); return false;
}
function renderLegend() {
  const box = $("#roi-legend"); box.innerHTML = "";
  const scanned = rois().filter((r) => r.scanned);
  if (scanned.length < 2) return;   // one ROI: nothing to tell apart
  for (const r of scanned) {
    const b = document.createElement("button"); b.type = "button"; b.className = "roi-chip";
    b.setAttribute("aria-pressed", String(roiVisible(r.id))); b.title = `${roiVisible(r.id) ? "Hide" : "Show"} ${r.name} on the plot and picture`;
    b.innerHTML = `<i class="roi-dot" style="background:${r.colour}"></i><span class="roi-name">${esc(r.name)}</span>`;
    b.onclick = () => toggleRoiVisible(r.id);
    box.appendChild(b);
  }
}
function toggleRoiVisible(id) {
  if (S.roiHidden.has(id)) S.roiHidden.delete(id); else S.roiHidden.add(id);
  renderRois(); drawPlot(); showFrame();
}
function afterRoiChange() { renderRois(); renderEvents(); renderComments(); loadActivity(true); refreshFiles(); showFrame(); }
$("#btn-roi-add").onclick = async (e) => {
  e.stopPropagation();
  const r = await roiAction({ action: "add" });
  if (!r) return;
  S.roiActive = r.added; renderRois(); toggleRoiMenu(false);
  toast(`${activeRoi().name} added. Pick a shape to draw it.`, 5000);
};
const toggleRoiMenu = (open) => toggleMenu("#roi-menu", "#btn-roi-pick", open);
$("#btn-roi-pick").onclick = (e) => { e.stopPropagation(); closeMenus("roi"); toggleRoiMenu(); };
$("#roi-menu").addEventListener("click", (e) => e.stopPropagation());

// ------------------------------------------------------------ scan, jobs
$("#btn-cancel").onclick = () => api("/api/jobs/cancel", {}).catch(err);
$("#btn-export-camera").onclick = () => {
  if (!S.rec) return;
  const f = fileRow(S.rec.path), at = f && f.camera_id && findCam(f.camera_id);
  const rows = at ? at.camera.paths.map(fileRow).filter(Boolean) : [f || { name: S.rec.name }];
  $("#cv-sub").textContent = at ? `${at.project.name} › ${at.survey.label} › ${at.camera.label}: ${plural(rows.length, "recording")}${rows.length > 1 ? ", joined in time order" : ""}, as one MP4.`
    : `${S.rec.name} isn't in a camera, so just this recording, as one MP4.`;
  $("#cv-blend").textContent = `(${$("#blend").value === "crossfade" ? "crossfade" : "overlay"} at ${Math.round(+$("#opacity").value * 100)}%)`;
  $("#dlg-camvid").showModal();
};
$("#cv-go").onclick = async (ev) => {
  ev.preventDefault(); $("#dlg-camvid").close();
  const mode = (document.querySelector("[name=cv-mode]:checked") || {}).value || "raw";
  const overlays = $("#cv-roi").checked ? "roi+time" : $("#cv-time").checked ? "time" : "none";
  try {
    const r = await api("/api/export-camera", { mode, overlays, palette: S.pal, blend: $("#blend").value, opacity: +$("#opacity").value, enh: enhVals() });
    (S.watch = S.watch || new Set()).add(r.job.id);
    toast(`Exporting ${plural(r.recordings, "recording")} to ${r.path}…`, 6000); pollJobs();
  } catch (e) { err(e); }
};
$("#cv-roi").onchange = () => { if ($("#cv-roi").checked) $("#cv-time").checked = true; };
// Start over: undo all decisions on this recording and scan it again
$("#btn-start-over").onclick = () => {
  if (!S.rec) return;
  const evs = S.rec.events || [], done = evs.filter((e) => e.status !== "todo").length, nc = (S.rec.comments || []).length;
  $("#so-name").textContent = S.rec.name;
  $("#so-count").textContent = `${done} of ${evs.length} event${evs.length === 1 ? "" : "s"} decided`;
  $("#so-ncom").textContent = `${nc} comment${nc === 1 ? "" : "s"}`;
  $("#so-comments").checked = false; $("#so-level").checked = false; $("#so-rescan").checked = false;
  $("#dlg-start-over").showModal();
};
$("#so-go").onclick = async () => {
  $("#so-go").disabled = true;
  try {
    stopPlay();
    const rescan = $("#so-rescan").checked;
    const r = await api("/api/start-over", { delete_comments: $("#so-comments").checked, reset_level: $("#so-level").checked, rescan });
    S.rec = r.recording; S.sel = null;
    $("#dlg-start-over").close();
    renderEvents(); renderComments(); refreshFiles(); await loadActivity(true); showFrame();
    if (r.jobs.length) { toast("Decisions reset. Scanning again…"); pollJobs(); }
    else toast(rescan ? "Decisions reset. Draw an ROI to scan again." : "All decisions reset.");
  } catch (e) { err(e); } finally { $("#so-go").disabled = false; }
};
// Progress shows over the Event Log plot: a percentage, what's running and
// what's queued. While the open recording is being scanned, its plot fills in
// as the scan goes (read every second; it doesn't slow the scan).
function showJobProgress(all, active) {
  const ov = $("#job-overlay");
  const fails = all.filter((j) => j.state === "error" && !(S.seenErr || (S.seenErr = new Set())).has(j.id));
  for (const j of fails) { S.seenErr.add(j.id); if (S.watch && S.watch.has(j.id)) toast(`${j.label} failed: ${j.error}`, 9000); }
  const run = active.find((j) => j.state === "running") || active[0];
  if (!run) { ov.hidden = true; S.liveScan = false; return; }
  const pct = Math.round(100 * run.done / Math.max(1, run.total));
  ov.hidden = false;
  $("#job-pct").textContent = run.state === "queued" ? "…" : pct + "%";
  $("#job-label").textContent = run.label;
  $("#job-more").textContent = active.length > 1 ? `${active.length - 1} more waiting` : "";
  $("#job-bar").style.width = pct + "%";
  const mine = run.kind === "scan" && S.rec && run.path === S.rec.path && run.state === "running";
  ov.classList.toggle("live", mine);
  if (mine) liveScanPlot();
}
async function liveScanPlot() {
  if (S.liveBusy || Date.now() - (S.liveAt || 0) < 900) return;
  S.liveBusy = true; S.liveAt = Date.now();
  try {
    const pts = Math.max(200, Math.round(plotBox.clientWidth * (window.devicePixelRatio || 1)));
    const r = await api(`/api/scan-live?a=${P.a}&b=${P.b}&points=${pts}`);
    if (r.live && r.values.length && S.rec) { S.liveScan = true; P.data = r.values; P.series = {}; P.units = r.units; drawPlot(); }
  } catch (e) {} finally { S.liveBusy = false; }
}
function pollJobs() {
  if (S.polling) return;
  S.polling = setInterval(async () => {
    let r; try { r = await api("/api/jobs"); } catch (e) { return; }
    const active = r.jobs.filter((j) => j.state === "queued" || j.state === "running");
    showJobProgress(r.jobs, active);
    const sig = r.jobs.map((j) => j.id + j.state).join();
    if (sig !== S.lastJobs) {
      S.lastJobs = sig; refreshFiles();
      S.watch = S.watch || new Set();   // only announce jobs this page saw running
      for (const j of r.jobs) if (j.state === "queued" || j.state === "running") S.watch.add(j.id);
      for (const j of r.jobs) {
        if (j.state !== "done" || !j.result || !S.watch.has(j.id)) continue;
        S.watch.delete(j.id);
        if (j.result.test) showTestResult(j.result.test);
        else if (j.result.report) { toast("Report saved: " + j.result.report, 8000); api("/api/open-path", { path: j.result.report }).catch(() => {}); }
        else if (j.result.files) toast(j.kind === "export" && j.result.files.length === 1 ? `Saved ${j.result.files[0]}` : `Saved ${j.result.files.length} files to the exports folder.`, 7000);
      }
      if (S.rec) { try { const rec = await api("/api/recording"); const sigOf = (x) => JSON.stringify([x.scanned, x.level, x.suggested_level, (x.events || []).map((e) => [e.f0, e.f1, e.status])]);
            const changed = sigOf(rec) !== sigOf(S.rec) || JSON.stringify(rec.rois) !== JSON.stringify(S.rec.rois); S.rec = rec; renderFilters(); if (changed) { renderRois(); await loadActivity(true); renderEvents(); } } catch (e) {} }
    }
    if (!active.length) { clearInterval(S.polling); S.polling = null; }
  }, 700);
}

// ------------------------------------------------------------ activity plot
// View = frames a..b. Data for the view is fetched at screen resolution, so
// zooming in shows every frame. The blue line is the detection level.
const P = { a: 0, b: 0, data: [], level: null, suggested: null, drag: null, fetchId: 0, units: "", cap: null, yMode: "default", range: null, capTop: null };
const plotBox = $("#plot"), plotCanvas = $("#plot-canvas");

async function loadActivity(keepView) {
  if (!S.rec) return;
  if (!keepView) { P.a = 0; P.b = S.rec.frames - 1; P.cap = null; }
  await fetchView();
  const has = P.data.length > 0;
  $("#level").disabled = !has; $("#btn-level-reset").disabled = !has;
  $("#btn-start-over").disabled = !has;
}
async function fetchView() {
  if (!S.rec) return;
  const id = ++P.fetchId;
  const pts = Math.max(200, Math.round(plotBox.clientWidth * (window.devicePixelRatio || 1)));
  try {
    const r = await api(`/api/activity?a=${P.a}&b=${P.b}&points=${pts}`);
    if (id !== P.fetchId) return;
    P.data = r.values; P.series = r.series || {}; P.units = r.units; P.range = r.range;
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
// Default: the height comes from the suggested detection level, which sits a
// quarter of the way up, so the background noise and small spikes are clear.
function defaultTop(lo) {
  const s = P.suggested ?? P.level; if (s == null || !(s > lo)) return null;
  return lo + 4 * (s - lo);
}
function yRange() {
  if (!P.data.length) return [0, 1];
  const st = viewStats(); P.stats = st;
  let lo = st.lo, hi = st.max;
  P.capTop = P.yMode === "manual" ? P.cap : P.yMode === "auto" ? autoTop(st.peaks, Math.min(lo, P.level ?? lo))
    : P.yMode === "default" ? defaultTop(lo) : null;
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
function multiRoi() { return rois().filter((r) => r.scanned).length > 1; }
function roiName(id) { return (roiById(id) || {}).name || "ROI"; }
function roiColour(id) { return (roiById(id) || {}).colour || "#E5484D"; }
// frames that no visible, scanned ROI has scanned (hatched "Not scanned")
function unscannedVisible() {
  const vis = rois().filter((r) => r.scanned && roiVisible(r.id));
  if (!vis.length) return S.rec.unscanned || [];
  let acc = vis[0].unscanned || [];
  for (const r of vis.slice(1)) {
    const out = [];
    for (const [a, b] of acc) for (const [c, d] of r.unscanned || []) { const lo = Math.max(a, c), hi = Math.min(b, d); if (lo <= hi) out.push([lo, hi]); }
    acc = out;
  }
  return acc;
}
function cssv(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function drawPlot() {
  const g = geom(), c = plotCanvas, ctx = c.getContext("2d");
  c.width = g.W * g.dpr; c.height = g.H * g.dpr; ctx.setTransform(g.dpr, 0, 0, g.dpr, 0, 0);
  ctx.clearRect(0, 0, g.W, g.H); $("#markers").innerHTML = "";
  const tag = $("#level-tag");
  if (!S.rec || !P.data.length) {
    ctx.fillStyle = cssv("--muted"); ctx.font = "12px sans-serif"; ctx.fillText(S.rec ? "Not scanned yet: use Scan camera (or Scan project) in the recordings list" : "", 12, 24);
    $("#plot-axis").innerHTML = ""; tag.hidden = true; syncCapBar(); return;
  }
  // grey hatching: stretches not scanned (a play-limits scan), and an ignored spike at the end
  const hatch = (f0, f1, note) => {
    const x0 = Math.max(0, g.x(f0)), x1 = Math.min(g.W, g.x(f1 + 1));
    if (x1 <= 0 || x0 >= g.W || x1 - x0 < 1) return;
    ctx.save(); ctx.fillStyle = cssv("--plot-hatch-bg"); ctx.fillRect(x0, 0, x1 - x0, g.H);
    ctx.beginPath(); ctx.rect(x0, 0, x1 - x0, g.H); ctx.clip();
    ctx.strokeStyle = cssv("--plot-hatch"); ctx.lineWidth = 1;
    for (let x = x0 - g.H; x < x1; x += 9) { ctx.beginPath(); ctx.moveTo(x, g.H); ctx.lineTo(x + g.H, 0); ctx.stroke(); }
    ctx.restore();
    if (x1 - x0 > 110) { ctx.fillStyle = cssv("--plot-note"); ctx.font = "11px sans-serif"; ctx.textAlign = "center"; ctx.fillText(note, (x0 + x1) / 2, 52); ctx.textAlign = "start"; }
  };
  for (const [a, b] of unscannedVisible()) hatch(a, b, "Not scanned");
  const cut = endCut();
  if (cut != null && g.x(cut) < g.W) hatch(cut, P.b, "Ignored: end of recording");
  // event windows shaded
  for (const e of S.rec.events) {
    if (!roiVisible(e.roi)) continue;
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
  // trace: one ROI = brand green above the line, grey below; several ROIs =
  // each in its own colour, faded below the line
  const clipped = [];
  const ly = P.level != null ? g.y(P.level) : -1;
  const traces = multiRoi()
    ? rois().filter((r) => r.scanned && roiVisible(r.id) && P.series[r.id]).map((r) => [P.series[r.id], r.colour, r.colour])
    : [[P.data, cssv("--accent"), cssv("--plot-lo")]];
  ctx.lineWidth = 1.3;
  for (const [data, hiCol, loCol] of traces) {
    const path = new Path2D();
    data.forEach(([f, v], k) => {
      const x = g.x(f), y = g.y(Math.min(v, g.hi));
      if (v > g.hi && P.capped) clipped.push(x);
      k ? path.lineTo(x, y) : path.moveTo(x, y);
    });
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, g.W, Math.max(0, ly)); ctx.clip(); ctx.strokeStyle = hiCol; ctx.stroke(path); ctx.restore();
    ctx.save(); ctx.beginPath(); ctx.rect(0, Math.max(0, ly), g.W, g.H); ctx.clip(); ctx.strokeStyle = loCol;
    if (multiRoi()) ctx.globalAlpha = 0.45; ctx.stroke(path); ctx.restore();
  }
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
    const n = S.rec.events.filter((e) => roiVisible(e.roi)).length;
    tag.textContent = `Detection level ${fmtVal(P.level)} · ${n} event${n === 1 ? "" : "s"}${S.roiHidden && S.roiHidden.size ? " shown" : ""}`;
  }
  // y labels
  ctx.fillStyle = cssv("--muted"); ctx.font = "11px " + getComputedStyle(document.body).getPropertyValue("--mono");
  ctx.fillText(fmtVal(g.hi) + (P.capped ? "  (capped)" : ""), 6, 50); ctx.fillText(fmtVal(g.lo), 6, g.H - 12);
  // markers
  for (const e of S.rec.events) {
    if (!roiVisible(e.roi)) continue;
    const x = g.x((e.f0 + e.f1) / 2); if (x < -10 || x > g.W + 10) continue;
    const m = document.createElement("button");
    m.className = "marker" + (S.sel === e.n ? " sel" : "") + (e.status === "confirmed" ? " ok" : e.status === "rejected" ? " no" : "");
    m.style.left = x + "px"; m.textContent = e.n;
    m.setAttribute("aria-label", `Event ${e.n} at ${fmtTime(e.f0)}, ${roiName(e.roi)}`);
    if (multiRoi()) { m.style.borderColor = roiColour(e.roi); m.style.borderWidth = "2px"; }
    m.onpointerdown = (ev) => ev.stopPropagation();
    m.onclick = (ev) => { ev.stopPropagation(); selectEvent(e.n); };
    $("#markers").appendChild(m);
  }
  const ticks = 5;
  $("#plot-axis").innerHTML = Array.from({ length: ticks }, (_, k) => `<span>${fmtTime(Math.round(P.a + k / (ticks - 1) * (P.b - P.a)))}</span>`).join("");
  const whole = P.a === 0 && P.b === S.rec.frames - 1;
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
  const approx = S.rec && S.rec.temp_approx && isTemp(P.units);
  $("#level-unit").textContent = P.units ? `(${P.units}${approx ? ", approx." : ""})` : "";
  $("#level-unit").title = approx ? "This file stores raw sensor values. They're converted to temperature from the range Research Studio showed when recording started: right for temperature differences, but the absolute values are approximate." : "";
  if (P.level != null && document.activeElement !== $("#level")) $("#level").value = (+P.level).toFixed(2);
  $("#level-info").textContent = P.suggested != null ? `Suggested: ${fmtVal(P.suggested)}. Or drag the blue line on the plot.` : "Or drag the blue line on the plot.";
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
document.querySelectorAll("[data-y]").forEach((b) => (b.onclick = () => setYMode(b.dataset.y === "log" ? "log" : b.dataset.y === "default" ? "default" : "auto")));
// The bar left of the plot sets the y-axis height in Linear mode: it starts
// where the automatic cut-off puts it; drag down to cut off more, up to the
// top for full height.
function capSpan() {
  if (!P.stats) return null;
  const vmax = P.stats.max, vmin = Math.min(vmax, Math.max(P.stats.lo, P.level ?? P.stats.lo));   // never below the detection line
  return vmax > vmin ? [vmin, vmax] : null;
}
function capGeom() { const b = $("#cap-bar").getBoundingClientRect(); return { top: b.top + 34, h: Math.max(1, b.height - 34 - 8) }; }
function syncCapBar() {
  const h = $("#cap-h"), sp = capSpan(), log = P.yMode === "log";
  const on = !!(S.rec && P.data.length && sp && !log);
  h.disabled = !on; $("#cap-bar").classList.toggle("off", !on);
  if (!on) { h.style.top = "34px"; $("#cap-fill").style.top = "34px"; return; }
  const cur = P.capped ? P.capTop : sp[1], f = Math.max(0, Math.min(1, (cur - sp[0]) / (sp[1] - sp[0])));
  const y = 34 + (1 - f) * ($("#cap-bar").clientHeight - 42);
  h.style.top = y + "px"; $("#cap-fill").style.top = y + "px";
  h.setAttribute("aria-valuetext", P.capped ? `Cut off at ${fmtVal(cur)}` : "Full height");
}
function capSet(f) {
  const sp = capSpan(); if (!sp) return;
  P.cap = sp[0] + Math.max(0, Math.min(1, f)) * (sp[1] - sp[0]);
  if (f >= 0.995) P.cap = sp[1] * 1.0001;   // the top = full height
  P.yMode = "manual"; drawPlot();
}
$("#cap-h").addEventListener("pointerdown", (e) => {
  if ($("#cap-h").disabled) return;
  e.preventDefault();
  const move = (ev) => { const g = capGeom(); capSet(1 - (ev.clientY - g.top) / g.h); };
  const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
});
$("#cap-bar").addEventListener("pointerdown", (e) => {   // click on the bar to jump the handle there
  if (e.target.id === "cap-h" || $("#cap-h").disabled) return;
  const g = capGeom(); capSet(1 - (e.clientY - g.top) / g.h);
});
$("#cap-h").addEventListener("keydown", (e) => {
  if (!["ArrowUp", "ArrowDown"].includes(e.key) || $("#cap-h").disabled) return;
  e.preventDefault(); e.stopPropagation();
  const sp = capSpan(); if (!sp) return;
  const cur = P.capped ? P.capTop : sp[1], f = (cur - sp[0]) / (sp[1] - sp[0]);
  capSet(f + (e.key === "ArrowUp" ? 1 : -1) * (e.shiftKey ? 0.1 : 0.02));
});
$("#cap-auto").onclick = () => setYMode("default");
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
  $("#t-label").textContent = `${fmtTime(P.a)} → ${fmtTime(P.b)} (${fmtDur(spanS(P.a, P.b))})`;
  const nTall = P.capped && P.stats ? P.stats.peaks.filter((p) => p > P.capTop).length : 0;
  $("#cap-label").textContent =
    P.yMode === "default" ? (P.capped ? `Default: height set from the suggested level (${fmtVal(P.suggested ?? P.level)}); ${nTall} taller spike${nTall === 1 ? "" : "s"} marked ▲.` : "Default: height set from the suggested level; every spike fits.")
    : P.yMode === "auto" ? (P.capped ? `Automatic: ${nTall} very tall spike${nTall === 1 ? "" : "s"} cut off (▲) so the rest are clear. Drag the bar's handle to change it.` : "Automatic: no spike dwarfs the others here, so nothing is cut off. Drag the bar's handle to cut off tall spikes.")
    : P.yMode === "log" ? "Log scale: tall spikes are squeezed down so small ones stay visible."
    : P.capped ? `Cut off at ${fmtVal(P.capTop)}${nClipped ? " · taller spikes marked ▲" : ""}` : "Full height: nothing cut off.";
  $("#cap-auto").hidden = P.yMode !== "manual";
  document.querySelectorAll("[data-y]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.y === "log" ? P.yMode === "log" : b.dataset.y === "default" ? P.yMode === "default" : P.yMode === "auto" || P.yMode === "manual")));
  syncCapBar();
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

// pointer: drag the line, drag to pan, click to jump
plotBox.addEventListener("pointermove", (e) => {
  if (!S.rec || !P.data.length) return;
  const b = plotBox.getBoundingClientRect(), g = geom(), y = e.clientY - b.top, x = e.clientX - b.left;
  if (!P.drag) { plotBox.classList.toggle("on-line", P.level != null && Math.abs(y - g.y(P.level)) < 8); return; }
  if (P.drag.kind === "level") { P.level = Math.max(g.lo, g.v(y)); $("#level").value = P.level.toFixed(2); drawPlot(); }
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
// ---- the same moment on another camera from the same survey (night)
function sameSurveyCams() {
  const f = S.rec && fileRow(S.rec.path), at = f && f.camera_id && findCam(f.camera_id);
  if (!at) return [];
  const out = at.survey.cameras.filter((c) => c.id !== at.camera.id && c.paths.length);
  out.here = at.camera; return out;
}
function frameAtSec(sec) {   // the first frame at or after this many seconds into the recording
  let lo = 0, hi = S.rec.frames - 1;
  while (lo < hi) { const m = (lo + hi) >> 1; if (secAt(m) < sec) lo = m + 1; else hi = m; }
  return lo;
}
const clockAt = (ms) => ukTime(ms).d.toISOString().substr(11, 8);
async function viewOnCamera(camId, n) {
  const e = evById(n), f = fileRow(S.rec.path), at = findCam(camId), here = sameSurveyCams().here;
  if (!f || !f.start) return toast("This recording has no start time, so it can't be matched to another camera.", 6000);
  const t0 = Date.parse(f.start) + secAt(e.f0) * 1000, t1 = Date.parse(f.start) + secAt(e.f1) * 1000;
  const hit = (at.camera.joined ? [at.camera.joined] : at.camera.paths).map(fileRow).find((r) => r && r.start && r.end && Date.parse(r.start) <= t1 && Date.parse(r.end) >= t0);
  if (!hit) { renderEvents(); return toast(`${at.camera.label} wasn't recording at ${clockAt(t0)} (none of its recordings cover that time).`, 7000); }
  const back = { path: S.rec.path, n, label: here.label };
  S.linking = true;
  try { await openRec(hit.path); } finally { S.linking = false; }
  if (!S.rec || S.rec.path !== hit.path) return;
  await loadTimes(hit.path);
  const s0 = Date.parse(hit.start), a = frameAtSec((t0 - s0) / 1000), b = Math.max(a, frameAtSec((t1 - s0) / 1000)), pad = winPad();
  S.lim = [Math.max(0, a - pad), Math.min(S.rec.frames - 1, b + pad)]; $("#in-window").checked = false;
  S.frame = a; drawLimits(); showFrame(); drawPlot();
  const bar = $("#linked-bar");
  bar.innerHTML = `<span><b>${esc(at.camera.label)}</b> at ${clockAt(t0)}–${clockAt(t1)}: the same time as Event ${n} on ${esc(back.label)}. The play limits are set to it.</span>`;
  const bb = document.createElement("button"); bb.type = "button"; bb.className = "btn sm"; bb.textContent = `Back to Event ${n}`;
  bb.onclick = async () => { bar.hidden = true; await openRec(back.path); if (S.rec && S.rec.path === back.path && evById(back.n)) selectEvent(back.n); };
  bar.appendChild(bb); bar.hidden = false;
}
// ---- step through the cameras of this survey, at the same moment
function surveyCams() {
  const f = S.rec && fileRow(S.rec.path), at = f && f.camera_id && findCam(f.camera_id);
  return at ? { at, cams: at.survey.cameras.filter((c) => c.paths.length) } : null;
}
function syncCamCycle() {
  const sc = surveyCams(), n = sc ? sc.cams.length : 0;
  const lc = $("#log-cam");
  $("#log-cam-wrap").hidden = !S.rec;
  if (S.rec) {
    fillCamPick(sc);
    lc.innerHTML = sc ? `${ICON_CAM}<b>${esc(sc.at.camera.label)}</b><span class="muted"> · ${esc(sc.at.survey.label)} · ${esc(sc.at.project.name)}</span>`
      : `${ICON_CAM}<b>Unassigned</b><span class="muted"> · ${esc(S.rec.name)}</span>`;
    lc.title = sc ? `This Event Log is for ${sc.at.project.name} › ${sc.at.survey.label} › ${sc.at.camera.label}: ${S.rec.name}` : S.rec.name;
  }
  $("#btn-cam-prev").disabled = $("#btn-cam-next").disabled = n < 2;
  const i = sc ? sc.cams.findIndex((c) => c.id === sc.at.camera.id) : -1;
  $("#cam-now").textContent = sc ? `${sc.at.camera.label}${n > 1 ? ` · ${i + 1} of ${n}` : ""}` : "";
  const t = n < 2 ? (sc ? "This survey has no other camera with recordings" : "Put this recording in a camera to step between cameras") : "";
  $("#btn-cam-prev").title = t || "The same moment on the previous camera of this survey";
  $("#btn-cam-next").title = t || "The same moment on the next camera of this survey";
}
// the moment showing now (clock ms) and the play limits, to match on another camera
function nowMoment() {
  const f = S.rec && fileRow(S.rec.path);
  if (!f || !f.start) return null;
  const s0 = Date.parse(f.start);
  return { t: s0 + secAt(S.frame) * 1000, lim: S.lim ? S.lim.map((x) => s0 + secAt(x) * 1000) : null };
}
function camHit(c, t) {   // this camera's recording that covers clock time t
  return (c.joined ? [c.joined] : c.paths).map(fileRow).find((r) => r && r.start && r.end && Date.parse(r.start) <= t && Date.parse(r.end) >= t);
}
async function openAtMoment(hit, m) {   // open a recording at the same moment (and play limits)
  try { await openRec(hit.path); } catch (e) { err(e); return false; }
  if (!S.rec || S.rec.path !== hit.path) return false;
  await loadTimes(hit.path);
  const h0 = Date.parse(hit.start);
  if (m.lim) { S.lim = [frameAtSec((m.lim[0] - h0) / 1000), frameAtSec((m.lim[1] - h0) / 1000)]; $("#in-window").checked = false; }
  S.frame = frameAtSec((m.t - h0) / 1000); drawLimits(); showFrame(); drawPlot();
  return true;
}
async function cycleCamera(dir) {
  const sc = surveyCams(); if (!sc || sc.cams.length < 2) return;
  const m = nowMoment();
  if (!m) return toast("This recording has no start time, so it can't be matched to another camera.", 6000);
  const n = sc.cams.length, i = sc.cams.findIndex((c) => c.id === sc.at.camera.id);
  for (let k = 1; k < n; k++) {
    const hit = camHit(sc.cams[(((i + dir * k) % n) + n) % n], m.t);
    if (!hit) continue;
    if (await openAtMoment(hit, m) && k > 1) toast(`Skipped ${plural(k - 1, "camera")} with no recording at ${clockAt(m.t)}.`, 5000);
    return;
  }
  toast(`No other camera in ${sc.at.survey.label} was recording at ${clockAt(m.t)}.`, 6000);
}
// ---- the camera chip at the top of the Event Log: choose any camera to show
function fillCamPick(sc) {
  fillCamSelect($("#log-cam-pick"), sc);
  fillCamSelect($("#cam-now-pick"), sc);
  $("#cam-now-pick").disabled = !sc;
}
function fillCamSelect(sel, sc) {
  const here = sc ? sc.at.camera.id : "";
  let h = sc ? "" : `<option value="" selected>Unassigned · ${esc(S.rec.name)}</option>`;
  for (const pj of S.tree || []) for (const sv of pj.surveys) {
    const cams = sv.cameras.filter((c) => c.paths.length);
    if (cams.length) h += `<optgroup label="${esc(pj.name)} › ${esc(sv.label)}">${cams.map((c) => `<option value="${c.id}"${c.id === here ? " selected" : ""}>${esc(c.label)}</option>`).join("")}</optgroup>`;
  }
  sel.innerHTML = h;
}
$("#log-cam-pick").onchange = $("#cam-now-pick").onchange = (e) => openCamera(e.target.value);
async function openCamera(id) {
  const at = findCam(id); if (!at || !at.camera.paths.length) return;
  const sc = surveyCams(); if (sc && sc.at.camera.id === at.camera.id) return;
  const c = at.camera, m = nowMoment(), hit = m && camHit(c, m.t);
  if (hit && await openAtMoment(hit, m)) return;
  try { await openRec(c.joined || c.paths[0]); } catch (er) { err(er); }
  if (m && S.rec) toast(`${c.label} wasn't recording at ${clockAt(m.t)}, so it opens at the start.`, 5000);
}
$("#btn-cam-prev").onclick = () => cycleCamera(-1);
$("#btn-cam-next").onclick = () => cycleCamera(1);
// ---- background noise between spikes, for each ROI
function renderNoise() {
  const box = $("#noise-box"), ns = (S.rec && S.rec.noise) || [];
  box.hidden = !ns.length; if (!ns.length) { box.innerHTML = ""; return; }
  const word = { low: "Low", moderate: "Moderate", high: "High" };
  let h = `<div class="noise-head"><span class="small strong">Background noise between spikes</span><span class="small muted">how busy each ROI is when no bat is passing</span></div>`;
  for (const x of ns) {
    const pct = (x.rises * 100).toFixed(x.rises < 0.1 ? 1 : 0);
    h += `<div class="noise-row ${x.rating}"><span class="noise-chip">${word[x.rating]}</span>
      <span class="small">${ns.length > 1 ? `<b>${esc(x.name)}</b> · ` : ""}average ${fmtVal(x.mean)}, varies ±${fmtVal(x.sd)}, small rises ${pct}% of the time${x.headroom != null ? ` · line ${fmtVal(x.headroom)} above the background` : ""}</span>
      ${x.worst ? `<button type="button" class="btn xs" data-noisy="${x.worst[0]}">Noisiest: ${fmtTime(x.worst[0])}–${fmtTime(x.worst[1])}</button>` : ""}</div>`;
  }
  const bad = ns.filter((x) => x.rating !== "low");
  if (bad.length) h += `<p class="small muted noise-tip">${bad.some((x) => x.rating === "high") ? "This ROI's background keeps rising and falling" : "This ROI's background is busier than open sky"}: something in it may move or change, such as swaying branches, passing cloud, water or a warm surface cooling. That raises the detection level and can hide faint bats. Check the noisiest stretch, and if something there moves, redraw the ROI to leave it out.</p>`;
  box.innerHTML = h;
  box.querySelectorAll("[data-noisy]").forEach((b) => (b.onclick = () => { stopPlay(); S.frame = +b.dataset.noisy; S.lim = null; drawLimits(); showFrame(); }));
}
function renderEvents() {
  const box = $("#events"), evs = (S.rec && S.rec.events) || [];
  $("#btn-export").disabled = !S.sel; $("#btn-csv").disabled = !evs.length; $("#btn-report").disabled = !(S.rec && S.rec.scanned);
  $("#btn-export-confirmed").disabled = !evs.some((e) => e.status === "confirmed");
  $("#btn-export-camera").disabled = !S.rec;
  $("#reviewed").textContent = evs.length ? `${evs.filter((e) => e.status !== "todo").length} of ${evs.length} reviewed` : "";
  if (!S.rec) return;
  renderNoise();
  if (!S.rec.scanned) { box.innerHTML = '<p class="muted small">Draw an ROI, then use Scan camera or Scan project in the recordings list.</p>'; return; }
  if (!evs.length) { box.innerHTML = '<p class="muted small">No spikes reach the detection level. Drag the blue line lower on the plot.</p>'; return; }
  box.innerHTML = "";
  for (const e of evs) {
    const d = document.createElement("div"); d.className = "ev" + (S.sel === e.n ? " sel" : ""); d.dataset.ev = e.n;
    const chipK = e.status === "confirmed" ? "ok" : e.status === "rejected" ? "no" : "todo";
    const chipT = e.status === "confirmed" ? (e.cls || "Confirmed") : e.status === "rejected" ? "Rejected" : "Not reviewed";
    const nC = commentsFor(e).length;
    const playingThis = S.playing && S.dir > 0 && S.sel === e.n;
    const when = [fmtDate(e.f0), `${fmtTime(e.f0)}–${fmtTime(e.f1)}`, fmtZone(e.f0)].filter(Boolean).join(" ");
    const roiTag = rois().length > 1 ? `<span class="roi-tag"><i class="roi-dot" style="background:${roiColour(e.roi)}"></i>${esc(roiName(e.roi))}</span>` : "";
    d.innerHTML = `<div class="ev-row"><button class="ev-play${playingThis ? " on" : ""}" data-evplay="${e.n}" aria-label="${playingThis ? "Pause" : "Play"} event ${e.n}" title="${playingThis ? "Pause" : "Play this event"}">${playingThis ? PAUSE_ICON : PLAY_ICON}</button><button class="ev-head"><span class="ev-top"><b>Event ${e.n}</b>${roiTag}</span>
      <span class="mono ev-when">${when}</span>
      <span class="mono small muted">frames ${e.f0.toLocaleString()}–${e.f1.toLocaleString()} · ${fmtDur(spanS(e.f0, e.f1))}</span>
      <span class="row wrap"><span class="chip ${chipK}">${esc(chipT)}</span></span></button></div>`;
    d.querySelector(".ev-head").onclick = () => selectEvent(e.n);
    d.querySelector(".ev-play").onclick = () => playEvent(e.n);
    if (S.sel === e.n) {
      const x = document.createElement("div");
      x.innerHTML = `<label class="small" style="display:block;margin-top:10px">Classification<select data-cls>${["", ...CLASSES, ...(e.cls && !CLASSES.includes(e.cls) ? [e.cls] : [])].map((c) => `<option ${c === (e.cls || "") ? "selected" : ""}>${c}</option>`).join("")}</select></label>
         <div class="ev-actions"><button class="btn sm ok" data-act="confirmed">Confirm</button><button class="btn sm" data-act="rejected">Reject</button>${e.status !== "todo" ? '<button class="btn sm" data-act="todo">Undo</button>' : ""}</div>`;
      const others = sameSurveyCams();
      if (others.length) {   // the same time on another camera from this survey
        const v = document.createElement("label"); v.className = "small ev-view";
        v.innerHTML = `View this time on <select data-view><option value="" selected>${esc(others.here.label)} (this camera)</option>${others.map((c) => `<option value="${c.id}">${esc(c.label)}</option>`).join("")}</select>`;
        v.querySelector("select").onchange = (ev) => { if (ev.target.value) viewOnCamera(ev.target.value, e.n); };
        x.appendChild(v);
      }
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
  if (document.activeElement !== $("#f-frames")) $("#f-frames").value = f.mfi;
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
// one number sets Max Frame Interval and Sliding Subtraction together
$("#f-frames").onchange = () => { const n = Math.max(1, Math.min(60, Math.round(+$("#f-frames").value) || 5)); setFilters({ mfi: n, ss: n }); };
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
  const body = { format: (document.querySelector("[name=rp-format]:checked") || {}).value || "pdf", rejected_images: $("#rp-rejected").checked, blend: $("#blend").value, opacity: +$("#opacity").value,
                 palette: S.pal, blend_range: S.rng.blend, enh: enhVals() };
  RP.forEach((k) => (body[k] = $("#rp-" + k).value));
  try { await api("/api/report", body); toast(`Creating the ${body.format === "docx" ? "Word" : "PDF"} report…`); pollJobs(); } catch (e) { err(e); }
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
// Comments are added and listed under each event.
function renderComments() { updateCommentBox(); }

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

// ------------------------------------------------------------ Custom viewing mode
// The Custom mode shows one of the saved custom filters (Settings > Custom
// filters). "Edit filters…" is a shortcut to that part of Settings.
S.customIdx = 0;
function customList() { return (S.cfg && S.cfg.custom_filters) || []; }
function customSpec() { return customList()[S.customIdx] || { name: "Custom", mfi: 0, ss: 0, mc: false, blend: "none", opacity: 0.8 }; }
function renderCustomPick() {
  const l = customList(), sel = $("#custom-pick");
  if (S.customIdx >= l.length) S.customIdx = 0;
  sel.innerHTML = l.length ? l.map((c, k) => `<option value="${k}" ${k === S.customIdx ? "selected" : ""}>${esc(c.name)}</option>`).join("")
    : '<option value="">No filters yet: click Edit filters…</option>';
  sel.disabled = !l.length;
}
$("#custom-pick").onchange = () => { S.customIdx = +$("#custom-pick").value || 0; S.rng.custom = null; showFrame(); };
$("#btn-custom-edit").onclick = () => openSettings("custom", S.customIdx);

// Settings > Custom filters: the editor
const CF = { list: [], idx: 0 };
const CF_BLANK = { name: "New filter", mfi: 0, ss: 0, mc: false, blend: "none", opacity: 0.8 };   // a blank start: nothing ticked
$("#cf-opacity").innerHTML = Array.from({ length: 11 }, (_, k) => `<option value="${k / 10}">${k * 10}%</option>`).join("");
function cfWarnings(c) {
  const w = [], any = c.mfi || c.ss || c.mc;
  if (!any) w.push(c.blend === "none" ? "No filters are ticked, so this looks the same as Default." : "No filters are ticked: blending the thermal picture with itself changes nothing.");
  if (c.mc && c.ss) w.push("Max Continuous with Sliding Subtraction: the subtraction removes most of the built-up route, so the picture may be almost blank.");
  if (c.mc && c.mfi) w.push("Max Continuous already keeps the brightest value of every frame, so Max Frame Interval adds nothing.");
  if (c.blend === "overlay" && any && !c.ss) w.push("Overlay without Sliding Subtraction lays the whole bright scene over the thermal picture, not just moving animals, so it can look washed out.");
  if (c.ss && c.ss >= 30) w.push("A long Sliding Subtraction delay can leave ghost copies of animals where they were earlier.");
  if (c.mfi && c.mfi >= 30) w.push("A long Max Frame Interval smears trails into wide bands and hides detail.");
  if (c.blend === "crossfade" && c.opacity >= 0.95) w.push("Crossfade at 100% shows only the filter, as if it weren't blended.");
  return w;
}
function cfRead() {
  return { name: $("#cf-name").value.trim() || "Custom",
           mfi: $("#cf-mfi-on").checked ? Math.max(2, Math.min(60, +$("#cf-mfi").value || 5)) : 0,
           ss: $("#cf-ss-on").checked ? Math.max(1, Math.min(60, +$("#cf-ss").value || 5)) : 0,
           mc: $("#cf-mc").checked, blend: $("#cf-blend-on").checked ? (CF.blendKind || "overlay") : "none", opacity: +$("#cf-opacity").value };
}
function cfShowWarnings() {
  const c = cfRead();
  $("#cf-warn-list").innerHTML = cfWarnings(c).map((t) => `<li>${esc(t)}</li>`).join("");
  $("#cf-opacity").disabled = c.blend === "none";
  $("#cf-mfi").disabled = !$("#cf-mfi-on").checked; $("#cf-ss").disabled = !$("#cf-ss-on").checked;
}
function cfRender(idx) {
  CF.idx = Math.max(0, idx);
  const l = $("#cf-list");
  l.innerHTML = CF.list.map((c, k) => `<option value="${k}">${esc(c.name)}</option>`).join("");
  const has = CF.list.length > 0;
  $("#cf-edit").hidden = !has; $("#cf-dup").disabled = $("#cf-del").disabled = !has;
  if (!has) { $("#cf-msg").hidden = false; $("#cf-msg").textContent = "No custom filters yet. Click New to make one."; return; }
  l.value = String(CF.idx);
  const c = CF.list[CF.idx];
  $("#cf-name").value = c.name;
  $("#cf-mfi-on").checked = c.mfi > 0; $("#cf-mfi").value = c.mfi || 5;
  $("#cf-ss-on").checked = c.ss > 0; $("#cf-ss").value = c.ss || 5;
  $("#cf-mc").checked = c.mc; $("#cf-blend-on").checked = c.blend !== "none"; CF.blendKind = c.blend === "crossfade" ? "crossfade" : "overlay"; $("#cf-opacity").value = String(c.opacity);
  $("#cf-msg").hidden = true; cfShowWarnings();
}
// edits update the filter being edited straight away (saved with Save filter or Save settings)
for (const id of ["#cf-name", "#cf-mfi-on", "#cf-mfi", "#cf-ss-on", "#cf-ss", "#cf-mc", "#cf-blend-on", "#cf-opacity"]) {
  $(id).addEventListener("input", () => { if (!CF.list.length) return; CF.list[CF.idx] = cfRead(); cfShowWarnings();
    if (id === "#cf-name") $("#cf-list").options[CF.idx].textContent = CF.list[CF.idx].name; });
  $(id).addEventListener("change", () => { if (!CF.list.length) return; CF.list[CF.idx] = cfRead(); cfShowWarnings(); });
}
$("#cf-list").onchange = () => cfRender(+$("#cf-list").value);
function cfUniqueName(base) { let n = base, k = 2; while (CF.list.some((c) => c.name.toLowerCase() === n.toLowerCase())) n = `${base} ${k++}`; return n; }
$("#cf-new").onclick = () => { CF.list.push({ ...CF_BLANK, name: cfUniqueName("New filter") }); cfRender(CF.list.length - 1); stDirty(); $("#cf-name").select(); };
$("#cf-dup").onclick = () => { const c = CF.list[CF.idx]; CF.list.push({ ...c, name: cfUniqueName(c.name + " copy") }); cfRender(CF.list.length - 1); stDirty(); };
$("#cf-del").onclick = () => { if (!confirmTwice($("#cf-del"), `Click Delete again to remove ${CF.list[CF.idx].name}`)) return; CF.list.splice(CF.idx, 1); cfRender(Math.min(CF.idx, CF.list.length - 1)); cfSave(false); };
async function cfSave(close) {
  const names = CF.list.map((c) => c.name.toLowerCase());
  const dup = names.find((n, k) => names.indexOf(n) !== k);
  const msg = $("#cf-msg");
  if (dup) { msg.hidden = false; msg.className = "small err"; msg.textContent = `Two filters are called "${dup}". Give each one a different name.`; return false; }
  try {
    const r = await api("/api/settings", { settings: { ...ST.saved, custom_filters: CF.list } });
    ST.saved = r.settings; applySettings(r.settings, false);
    CF.list = JSON.parse(JSON.stringify(r.settings.custom_filters));
    if (!close) { cfRender(Math.min(CF.idx, CF.list.length - 1)); msg.hidden = false; msg.className = "small ok"; msg.textContent = "Saved. It's in the Custom mode's Filter list."; stDirty(); }
    renderCustomPick(); if (S.mode === "custom") showFrame();
    return true;
  } catch (e) { err(e); return false; }
}
$("#cf-save").onclick = () => cfSave(false);
$("#cf-view").onclick = async () => {
  const idx = CF.idx;
  if (!(await cfSave(true))) return;
  $("#dlg-settings").close(); S.customIdx = idx; S.rng.custom = null; setMode("custom");
};

// ------------------------------------------------------------ settings
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
  renderCustomPick();
}

const ST = { saved: null, draft: null };   // saved settings, and the copy being edited
const SECTIONS = ["appearance", "viewing", "custom", "detection", "exports", "time", "classes", "review", "report", "shortcuts"];
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
  $("#st-frames").value = c.filters.mfi;
  $("#st-sens").value = c.detect.sensitivity; $("#st-merge").value = c.detect.merge_s;
  $("#st-minf").value = c.detect.min_frames; $("#st-window").value = c.detect.window_s;
  $("#st-folder").value = c.export.folder;
  document.querySelectorAll("[name=st-items]").forEach((i) => (i.checked = c.export.items.includes(i.value)));
  $("#st-overlays").value = c.export.overlays; $("#st-textsize").value = c.export.text_size;
  $("#st-naming").value = c.export.naming; $("#st-quality").value = c.export.quality; $("#st-slowmo").value = String(c.export.slowmo);
  $("#st-scale").value = c.units.scale || "temperature"; $("#st-temp").disabled = $("#st-scale").value === "counts";
  $("#st-temp").value = c.units.temp; $("#st-zone").value = c.units.zone; $("#st-offset").value = c.units.clock_offset_s;

  $("#st-classes").value = c.classes.join("\n");
  $("#st-autoadv").checked = c.review.auto_advance; $("#st-autoplay").checked = c.review.auto_play;
  for (const k of ["company", "contact", "analyst", "camera"]) $("#st-" + k).value = c.report[k] || "";
  CF.list = JSON.parse(JSON.stringify(c.custom_filters || [])); cfRender(Math.min(CF.idx, CF.list.length - 1));
  stExamples();
}
function stRead() {
  const v = (id) => $(id).value;
  return {
    appearance: { scheme: v("#st-scheme"), theme: (document.querySelector("[name=st-theme]:checked") || {}).value || "dark",
                  window: (document.querySelector("[name=st-window]:checked") || {}).value || "app" },
    view: { palette: v("#st-palette"), speed: +v("#st-speed"), dde: +v("#st-dde"), tnr: +v("#st-tnr"), blend: v("#st-blend"), opacity: +v("#st-opacity") },
    filters: { mfi: +v("#st-frames"), ss: +v("#st-frames") },
    detect: { sensitivity: v("#st-sens"), merge_s: +v("#st-merge"), min_frames: +v("#st-minf"), window_s: +v("#st-window") },
    export: { folder: v("#st-folder").trim(), items: [...document.querySelectorAll("[name=st-items]:checked")].map((i) => i.value),
              overlays: v("#st-overlays"), text_size: v("#st-textsize"), naming: v("#st-naming"), quality: +v("#st-quality"), slowmo: +v("#st-slowmo") },
    units: { scale: v("#st-scale"), temp: v("#st-temp"), zone: v("#st-zone"), clock_offset_s: +v("#st-offset") || 0 },
    classes: v("#st-classes").split("\n").map((x) => x.trim()).filter(Boolean),
    review: { auto_advance: $("#st-autoadv").checked, auto_play: $("#st-autoplay").checked },
    report: Object.fromEntries(["company", "contact", "analyst", "camera"].map((k) => [k, v("#st-" + k).trim()])),
    custom_filters: CF.list,
  };
}
function stExamples() {
  const site = S.rec ? S.rec.path.split(/[\\/]/).slice(-2, -1)[0] : "St Fagans", recn = S.rec ? S.rec.name.replace(/\.ats$/i, "") : "front 2";
  const eg = { site_recording: `${site}_${recn}_event1_21-14-05`, date_site: `${(S.rec && fmtDate(0) ? fmtDate(0) : "10/08/2026").replace(/\//g, "-")}_${site}_${recn}_event1`, recording_event: `${recn}_event1_21-14-05` };
  $("#st-naming-eg").textContent = (eg[$("#st-naming").value] || "").replace(/[^A-Za-z0-9_.-]+/g, "_") + "_tracking.mp4";
  const o = +$("#st-offset").value || 0, a = Math.abs(o);
  $("#st-offset-eg").textContent = o ? `Times will move ${o > 0 ? "later" : "earlier"} by ${a >= 3600 ? Math.floor(a / 3600) + " h " : ""}${a % 3600 >= 60 ? Math.floor((a % 3600) / 60) + " min " : ""}${a % 60 ? (a % 60) + " s" : ""}.` : "";
}
function stDirty() {   // compare what's on screen with what's saved, section by section
  const a = stRead(), c = ST.saved, norm = (o) => JSON.stringify(o, Object.keys(o || {}).sort());
  const same = Object.keys(a).every((k) => Array.isArray(a[k]) ? JSON.stringify(a[k]) === JSON.stringify(c[k]) : norm(a[k]) === norm(c[k]));
  $("#st-dirty").hidden = same;
}
$("#st-form").addEventListener("input", () => { stExamples(); stDirty(); });
$("#st-form").addEventListener("change", () => { stExamples(); stDirty(); $("#st-temp").disabled = $("#st-scale").value === "counts"; });
// appearance previews straight away; Cancel puts it back
$("#st-scheme").addEventListener("change", () => applyLook($("#st-scheme").value, null));
document.querySelectorAll("[name=st-theme]").forEach((r) => r.addEventListener("change", () => applyLook(null, r.value)));
$("#st-from-view").onclick = () => {
  const e = enhVals();
  $("#st-palette").value = S.pal; $("#st-speed").value = $("#speed").value;
  $("#st-dde").value = String(e.dde); $("#st-tnr").value = String(e.tnr);
  $("#st-blend").value = $("#blend").value; $("#st-opacity").value = $("#opacity").value;
  if (S.filters) $("#st-frames").value = S.filters.mfi;
  stDirty(); toast("Copied the current view. Click Save settings to keep it.");
};
$("#st-detect-reset").onclick = () => { $("#st-sens").value = "normal"; $("#st-merge").value = 2; $("#st-minf").value = 1; $("#st-window").value = 3; stDirty(); };
$("#st-folder-pick").onclick = async () => {
  try { const r = await api("/api/pick", { kind: "folder" }); if (r.paths.length) { $("#st-folder").value = r.paths[0]; stDirty(); } } catch (e) { err(e); }
};
async function openSettings(sec, cfIdx) {
  try { const r = await api("/api/settings"); ST.saved = r.settings; ST.defaults = r.defaults; } catch (e) { return err(e); }
  if (cfIdx != null) CF.idx = cfIdx;
  stFill(ST.saved); stShow(typeof sec === "string" ? sec : "appearance"); $("#st-dirty").hidden = true; $("#dlg-settings").showModal();
}
function closeSettings() {   // undo any appearance preview that wasn't saved
  applyLook(S.cfg.appearance.scheme, S.cfg.appearance.theme);
  $("#dlg-settings").close();
}
$("#btn-settings").onclick = () => openSettings();
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
      if (unitsChanged) { S.rng = { raw: null, review: null, path: null, blend: null, custom: null }; S.track = {}; }
      if (S.sel && !S.rec.events.some((e) => e.n === S.sel)) S.sel = null;
      if (S.sel) { const e = evById(S.sel), pad = winPad(); S.ws = Math.max(0, e.f0 - pad); S.we = Math.min(S.rec.frames - 1, e.f1 + pad); }
      if (S.rec.scanned) await loadActivity(true);
      renderEvents(); renderComments(); updateLevelInputs(); refreshFiles(); showFrame();
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
  refreshFiles().then(() => api("/api/files").then((r) => { if (r.current) openRec(r.current); })).catch(() => {}).finally(showStart);
})();
syncLock(); drawLimits();
pollJobs();

// Heartbeat: tells the program this window is still open, so it never shuts
// itself down while you're working. If the program has stopped, say so
// instead of leaving buttons that do nothing.
let missedPings = 0;
setInterval(async () => {
  try { const r = await fetch("/api/ping", { cache: "no-store" }); if (!r.ok) throw new Error(); missedPings = 0; $("#stopped-banner").hidden = true; }
  catch (e) { if (++missedPings >= 2) $("#stopped-banner").hidden = false; }
}, 20000);

// ------------------------------------------------------------ project map
// A satellite map of the project's site (Leaflet, with Esri imagery or
// OpenStreetMap), with each camera of a survey placed where it stood and a
// cone showing which way it looked, how wide its lens sees and how far.
const LENSES = { "FLIR A70": [29, 51, 95], "FLIR A700": [14, 24, 42, 80] };
const SENSOR_PX = 640;   // both cameras are 640 × 480
const MAPS = {};
function geoDest(lat, lon, brg, dist) {   // the point dist metres from lat/lon on bearing brg
  const R = 6371000, d = dist / R, t = brg * Math.PI / 180, p1 = lat * Math.PI / 180, l1 = lon * Math.PI / 180;
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(t));
  const l2 = l1 + Math.atan2(Math.sin(t) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return [p2 * 180 / Math.PI, l2 * 180 / Math.PI];
}
function geoBearing(a, b) {
  const p1 = a.lat * Math.PI / 180, p2 = b.lat * Math.PI / 180, dl = (b.lng - a.lng) * Math.PI / 180;
  const t = Math.atan2(Math.sin(dl) * Math.cos(p2), Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl));
  return (t * 180 / Math.PI + 360) % 360;
}
function conePoints(m) {
  const pts = [[m.lat, m.lon]], n = 24;
  for (let k = 0; k <= n; k++) pts.push(geoDest(m.lat, m.lon, m.bearing - m.fov / 2 + m.fov * k / n, m.range));
  return pts;
}
// Pixel size at the range: the lens sees 2 × range × tan(angle ÷ 2) across, shared
// between 640 pixels (480 down). The vertical angle comes from FLIR's lens figures.
const LENS_V = { 29: 22, 51: 39, 95: 74, 14: 10, 24: 18, 42: 32, 80: 63 };
const SENSOR_PY = 480;
function vfov(m) { return LENS_V[m.fov] ?? 2 * Math.atan(Math.tan(m.fov * Math.PI / 360) * SENSOR_PY / SENSOR_PX) * 180 / Math.PI; }
function viewW(m) { return 2 * m.range * Math.tan(m.fov * Math.PI / 360); }       // metres across at the range
function viewH(m) { return 2 * m.range * Math.tan(vfov(m) * Math.PI / 360); }     // metres high at the range
function pixW(m) { return viewW(m) / SENSOR_PX * 1000; }                           // mm
function pixH(m) { return viewH(m) / SENSOR_PY * 1000; }
function targetPx(m, size = 0.1) { return Math.PI / 4 * (size * 1000 / pixW(m)) * (size * 1000 / pixH(m)); }   // pixels on a round target
const camIcon = (no, sel) => L.divIcon({ className: "cam-pin" + (sel ? " sel" : ""), html: `<span>${no}</span>`, iconSize: [26, 30], iconAnchor: [13, 30] });
const tipIcon = L.divIcon({ className: "cone-tip", iconSize: [14, 14], iconAnchor: [7, 7] });

function openMap(projectId) {
  const pj = (S.tree || []).find((p) => p.id === projectId); if (!pj) return;
  MAPS.pj = pj.id; MAPS.sel = null;
  $("#map-title").textContent = `Site plan: ${pj.name}`;
  $("#map-survey").innerHTML = pj.surveys.map((s) => `<option value="${s.id}">${esc(s.label)}</option>`).join("");
  $("#map-survey").value = MAPS.sv && pj.surveys.some((s) => s.id === MAPS.sv) ? MAPS.sv : (pj.surveys[pj.surveys.length - 1] || {}).id || "";
  MAPS.sv = $("#map-survey").value;
  $("#map-results").hidden = true; $("#map-q").value = "";
  $("#dlg-map").showModal();
  if (!MAPS.map) {
    L.Icon.Default.imagePath = "/static/leaflet/images/";
    const sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 21, maxNativeZoom: 19, attribution: "Imagery © Esri, Maxar, Earthstar Geographics" });
    const labels = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 21, maxNativeZoom: 19 });
    const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 21, maxNativeZoom: 19, attribution: "© OpenStreetMap contributors" });
    MAPS.map = L.map("map", { layers: [sat, labels], zoomControl: true, attributionControl: true }).setView([54, -2.5], 6);
    L.control.layers({ "Satellite": sat, "Map": osm }, { "Place names": labels }, { position: "topright" }).addTo(MAPS.map);
    L.control.scale({ imperial: false }).addTo(MAPS.map);
    MAPS.layer = L.layerGroup().addTo(MAPS.map);
  }
  setTimeout(() => {
    MAPS.map.invalidateSize();
    if (pj.site) MAPS.map.setView([pj.site.lat, pj.site.lon], pj.site.zoom || 18);
    else {
      const placed = pj.surveys.flatMap((s) => s.cameras).map((c) => c.map).filter(Boolean);
      if (placed.length) MAPS.map.setView([placed[0].lat, placed[0].lon], 19);
    }
    drawMap(); templateNote();
  }, 60);
}
function mapProject() { return (S.tree || []).find((p) => p.id === MAPS.pj); }
function mapSurvey() { const pj = mapProject(); return pj && pj.surveys.find((s) => s.id === MAPS.sv); }
function camDefaults(cam) {
  const f = cam.paths.map(fileRow).find(Boolean);
  const model = S.rec && S.rec.camera && LENSES[S.rec.camera] && f && fileRow(S.rec.path) && fileRow(S.rec.path).camera_id === cam.id ? S.rec.camera : "FLIR A70";
  const c = MAPS.map.getCenter(), at = geoDest(c.lat, c.lng, 90, 6 * (cam.no - 1));   // a few metres apart, so they don't stack
  return { lat: at[0], lon: at[1], bearing: 0, range: 15, model, lens: String(LENSES[model].includes(95) ? 95 : LENSES[model][0]), fov: LENSES[model].includes(95) ? 95 : LENSES[model][0] };
}
function saveCamMap(cam, m) {
  cam.map = m;
  clearTimeout(MAPS.t && MAPS.t[cam.id]); MAPS.t = MAPS.t || {};
  MAPS.t[cam.id] = setTimeout(async () => {
    try { await api("/api/org", { action: "set_camera_map", id: cam.id, map: m }); } catch (e) { err(e); }
  }, 350);
}
function drawMap() {
  const sv = mapSurvey(), pj = mapProject(); if (!MAPS.map || !pj) return;
  MAPS.layer.clearLayers();
  if (pj.site) {
    const sm = L.marker([pj.site.lat, pj.site.lon], { draggable: true, title: "Site" }).addTo(MAPS.layer).bindTooltip(pj.name);
    sm.on("dragend", () => setSite(sm.getLatLng()));
    $("#map-site-note").textContent = `Site: ${pj.site.lat.toFixed(5)}, ${pj.site.lon.toFixed(5)}`;
  } else $("#map-site-note").textContent = "No site pin yet.";
  for (const d of (sv ? sv.detectors || [] : [])) {
    if (!d.map) continue;
    const sel = MAPS.sel === d.id;
    if (d.range > 0) L.circle([d.map.lat, d.map.lon], { radius: d.range, color: "#f0a020", weight: 1.5, dashArray: "5 5", fillColor: "#f0a020", fillOpacity: sel ? 0.18 : 0.08, interactive: false }).addTo(MAPS.layer);
    const mk = L.marker([d.map.lat, d.map.lon], { draggable: true, icon: L.divIcon({ className: "det-pin" + (sel ? " sel" : ""), html: `<span>A${d.no}</span>`, iconSize: [30, 30], iconAnchor: [15, 15] }), title: d.name, zIndexOffset: 1100 }).addTo(MAPS.layer);
    mk.on("click", () => { MAPS.sel = d.id; drawMap(); });
    mk.on("dragend", () => { const p = mk.getLatLng(); d.map = { lat: p.lat, lon: p.lng }; saveDet(d, { map: d.map }); drawMap(); });
  }
  for (const cam of (sv ? sv.cameras : [])) {
    const m = cam.map; if (!m) continue;
    const sel = MAPS.sel === cam.id;
    const cone = L.polygon(conePoints(m), { color: "#2bb7c8", weight: 1.5, fillColor: "#2bb7c8", fillOpacity: sel ? 0.42 : 0.28, interactive: true }).addTo(MAPS.layer);
    cone.on("click", () => { MAPS.sel = cam.id; drawMap(); });
    const pin = L.marker([m.lat, m.lon], { draggable: true, icon: camIcon(cam.no, sel), title: cam.label, zIndexOffset: 1000 }).addTo(MAPS.layer);
    const tipAt = geoDest(m.lat, m.lon, m.bearing, m.range);
    const tip = L.marker(tipAt, { draggable: true, icon: tipIcon, title: `Turn ${cam.label} or change how far it reaches`, zIndexOffset: 900 }).addTo(MAPS.layer);
    pin.on("click", () => { MAPS.sel = cam.id; drawMap(); });
    pin.on("drag", () => { const p = pin.getLatLng(); m.lat = p.lat; m.lon = p.lng; cone.setLatLngs(conePoints(m)); tip.setLatLng(geoDest(m.lat, m.lon, m.bearing, m.range)); });
    pin.on("dragend", () => { saveCamMap(cam, m); renderMapCams(); });
    tip.on("drag", () => {
      const p = tip.getLatLng(), c = L.latLng(m.lat, m.lon);
      m.bearing = Math.round(geoBearing(c, p)); m.range = Math.max(1, Math.round(c.distanceTo(p)));
      cone.setLatLngs(conePoints(m)); renderMapCams(true);
    });
    tip.on("dragend", () => { saveCamMap(cam, m); renderMapCams(); });
  }
  renderMapCams();
}
function renderMapCams(quiet) {
  const sv = mapSurvey(), box = $("#map-cams");
  if (!quiet) { if (document.activeElement !== $("#map-surveyor")) $("#map-surveyor").value = sv ? sv.surveyor || "" : ""; renderDets(); }
  if (!sv) { box.innerHTML = '<p class="small muted">This project has no surveys yet.</p>'; return; }
  if (quiet) {   // while dragging: just refresh the numbers
    for (const cam of sv.cameras) { const r = box.querySelector(`[data-mc="${cam.id}"]`); if (!r || !cam.map) continue;
      r.querySelector("[data-k=bearing]").value = cam.map.bearing; r.querySelector("[data-k=range]").value = cam.map.range;
      r.querySelector(".mc-stats").innerHTML = camStats(cam.map); }
    return;
  }
  box.innerHTML = "";
  for (const cam of sv.cameras) {
    const m = cam.map, row = el("div", "mc" + (MAPS.sel === cam.id ? " sel" : "")); row.dataset.mc = cam.id;
    row.innerHTML = `<div class="mc-head"><span class="cam-pin-s">${cam.no}</span><b>${esc(cam.label)}</b></div>`;
    if (!m) {
      row.appendChild(smallBtn("Place on map", `Put ${cam.label} in the middle of the map`, () => { const d = camDefaults(cam); MAPS.sel = cam.id; saveCamMap(cam, d); drawMap(); }, "primary"));
    } else {
      const lenses = LENSES[m.model] || [];
      row.insertAdjacentHTML("beforeend", `<div class="mc-grid">
        <label>Camera <select data-k="model">${Object.keys(LENSES).map((k) => `<option ${k === m.model ? "selected" : ""}>${k}</option>`).join("")}</select></label>
        <label>Lens <select data-k="lens">${lenses.map((a) => `<option value="${a}" ${String(a) === m.lens ? "selected" : ""}>${a}°</option>`).join("")}<option value="custom" ${m.lens === "custom" ? "selected" : ""}>Other…</option></select></label>
        <label ${m.lens === "custom" ? "" : "hidden"}>Angle ° <input data-k="fov" type="number" min="1" max="180" step="1" value="${m.fov}"></label>
        <label>Facing ° <input data-k="bearing" type="number" min="0" max="359" step="1" value="${Math.round(m.bearing)}"></label>
        <label>Range m <input data-k="range" type="number" min="1" max="2000" step="1" value="${Math.round(m.range)}"></label>
        <label class="span2">Surveyor <input data-s="1" type="text" maxlength="80" value="${esc(cam.surveyor || "")}" placeholder="Who set up this camera"></label>
      </div><div class="mc-stats small muted">${camStats(m)}</div>`);
      row.querySelector("[data-s]").onchange = async (e) => { cam.surveyor = e.target.value.trim(); try { await api("/api/org", { action: "set_info", id: cam.id, surveyor: cam.surveyor }); } catch (er) { err(er); } };
      row.querySelectorAll("[data-k]").forEach((i) => (i.onchange = () => {
        const k = i.dataset.k;
        if (k === "model") { m.model = i.value; const l = LENSES[m.model]; m.fov = l.includes(m.fov) ? m.fov : (l.includes(95) ? 95 : l[l.length - 1]); m.lens = String(m.fov); }
        else if (k === "lens") { m.lens = i.value; if (i.value !== "custom") m.fov = +i.value; }
        else m[k] = Math.max(+i.min || 0, Math.min(+i.max, +i.value || 0));
        saveCamMap(cam, m); drawMap();
      }));
      const acts = el("div", "row wrap");
      acts.append(smallBtn("Show", `Centre the map on ${cam.label}`, () => { MAPS.sel = cam.id; MAPS.map.setView([m.lat, m.lon], Math.max(MAPS.map.getZoom(), 18)); drawMap(); }),
                  smallBtn("Remove from map", `Take ${cam.label} off the map`, async () => { cam.map = null; try { await api("/api/org", { action: "set_camera_map", id: cam.id, map: null }); } catch (e) { err(e); } drawMap(); }));
      row.appendChild(acts);
    }
    row.addEventListener("click", (e) => { if (e.target.closest("input, select, button")) return; if (MAPS.sel !== cam.id) { MAPS.sel = cam.id; drawMap(); } });
    box.appendChild(row);
  }
}
// acoustic detectors: placed like cameras, with a dashed circle for their range
const DET_FIELDS = [["name", "Acoustic detector name"], ["surveyor", "Surveyor"], ["model", "Model"], ["serial", "Serial no."]];
function saveDet(d, fields) {   // edits close together go in one save, none lost
  MAPS.dt = MAPS.dt || {}; MAPS.dp = MAPS.dp || {};
  clearTimeout(MAPS.dt[d.id]); MAPS.dp[d.id] = { ...(MAPS.dp[d.id] || {}), ...fields };
  MAPS.dt[d.id] = setTimeout(async () => { const f = MAPS.dp[d.id]; delete MAPS.dp[d.id];
    try { await api("/api/org", { action: "set_detector", id: d.id, fields: f }); } catch (e) { err(e); } }, 250);
}
function renderDets() {
  const sv = mapSurvey(), box = $("#map-dets"); box.innerHTML = "";
  if (!sv) return;
  const ds = sv.detectors || (sv.detectors = []);
  if (!ds.length) box.innerHTML = '<p class="small muted">No acoustic detectors in this survey.</p>';
  for (const d of ds) {
    const row = el("div", "mc det" + (MAPS.sel === d.id ? " sel" : ""));
    row.innerHTML = `<div class="mc-head"><span class="det-pin-s">A${d.no}</span><b>${esc(d.name)}</b></div>
      <div class="mc-grid">${DET_FIELDS.map(([k, l]) => `<label class="${k === "name" || k === "model" ? "span2" : ""}">${l} <input data-d="${k}" type="text" maxlength="80" ${k === "model" ? 'list="det-models"' : ""} value="${esc(d[k] || "")}"></label>`).join("")}
        <label>Range m <input data-d="range" type="number" min="0" max="500" step="1" value="${Math.round(d.range ?? 20)}" title="Rough detection range, drawn as a dashed circle (0 for none)"></label>
        <label class="span2">Other info <textarea data-d="notes" rows="2" maxlength="200" placeholder="Settings, height, mounting…">${esc(d.notes || "")}</textarea></label>
      </div>${d.map ? `<div class="mc-stats small muted">${d.map.lat.toFixed(6)}, ${d.map.lon.toFixed(6)}</div>` : ""}`;
    row.querySelectorAll("[data-d]").forEach((i) => (i.onchange = () => {
      const k = i.dataset.d; d[k] = k === "range" ? Math.max(0, +i.value || 0) : i.value.trim();
      saveDet(d, { [k]: d[k] }); if (k === "name" || k === "range") drawMap();
    }));
    const acts = el("div", "row wrap");
    if (!d.map) acts.append(smallBtn("Place on map", `Put ${d.name} in the middle of the map`, () => {
      const c = MAPS.map.getCenter(), at = geoDest(c.lat, c.lng, 180, 6 * d.no); d.map = { lat: at[0], lon: at[1] }; MAPS.sel = d.id; saveDet(d, { map: d.map }); drawMap(); }, "primary"));
    else acts.append(smallBtn("Show", `Centre the map on ${d.name}`, () => { MAPS.sel = d.id; MAPS.map.setView([d.map.lat, d.map.lon], Math.max(MAPS.map.getZoom(), 18)); drawMap(); }),
                     smallBtn("Remove from map", "Take it off the map (keeps its details)", () => { d.map = null; saveDet(d, { map: null }); drawMap(); }));
    acts.append(smallBtn("Delete", `Delete ${d.name}`, async () => {
      if (!confirm(`Delete ${d.name} from this survey?`)) return;
      try { await api("/api/org", { action: "delete_detector", id: d.id }); sv.detectors = sv.detectors.filter((x) => x !== d); drawMap(); } catch (e) { err(e); } }));
    row.appendChild(acts);
    row.addEventListener("click", (e) => { if (e.target.closest("input, select, button, textarea")) return; if (MAPS.sel !== d.id) { MAPS.sel = d.id; drawMap(); } });
    box.appendChild(row);
  }
}
$("#map-add-det").onclick = async () => {
  const sv = mapSurvey(); if (!sv) return;
  try { const r = await api("/api/org", { action: "add_detector", survey: sv.id });
    const d = (r.tree || []).flatMap((p) => p.surveys).find((s) => s.id === sv.id).detectors.find((x) => x.id === r.created);
    (sv.detectors = sv.detectors || []).push(d); MAPS.sel = d.id; drawMap(); } catch (e) { err(e); }
};
function camStats(m) {
  return `<b>Pixel size ${pixW(m).toFixed(1)} × ${pixH(m).toFixed(1)} mm</b> at ${Math.round(m.range)} m · view ${viewW(m).toFixed(1)} × ${viewH(m).toFixed(1)} m · ${targetPx(m).toFixed(1)} px on a 0.1 m target · ${m.lat.toFixed(6)}, ${m.lon.toFixed(6)}`;
}
async function setSite(ll) {
  try {
    const site = { lat: ll.lat, lon: ll.lng, zoom: MAPS.map.getZoom() };
    await api("/api/org", { action: "set_site", id: MAPS.pj, site }); mapProject().site = site; drawMap();
  } catch (e) { err(e); }
}
$("#map-site").onclick = () => setSite(MAPS.map.getCenter());
function templateNote() {
  const pj = mapProject();
  $("#map-template-note").textContent = pj && pj.template ? `Site plan template: ${plural(pj.template, "camera")}. New surveys start with them.` : "No site plan template yet.";
}
$("#map-template").onclick = async () => {
  const sv = mapSurvey(); if (!sv) return;
  try { const r = await api("/api/org", { action: "save_template", survey: sv.id }); mapProject().template = r.template; templateNote();
    toast(`${sv.label} saved as the site plan: new surveys of this project start with its ${plural(r.template, "camera")}.`, 7000); } catch (e) { err(e); }
};
$("#map-print").onclick = () => {
  const pj = mapProject(), sv = mapSurvey(); if (!pj) return;
  const cams = (sv ? sv.cameras : []).filter((c) => c.map);
  const rows = cams.map((c) => { const m = c.map; return `<tr><td>${c.no}</td><td>${esc(c.label)}</td><td>${esc(m.model)} ${m.fov}°</td><td>${Math.round(m.bearing)}°</td><td>${Math.round(m.range)} m</td><td>${pixW(m).toFixed(1)} × ${pixH(m).toFixed(1)} mm</td><td>${targetPx(m).toFixed(2)} px</td><td>${esc(c.surveyor || "")}</td><td>${m.lat.toFixed(6)}, ${m.lon.toFixed(6)}</td></tr>`; }).join("");
  const dets = (sv ? sv.detectors || [] : []);
  const drows = dets.map((d) => `<tr><td>A${d.no}</td><td>${esc(d.name)}</td><td>${esc(d.model)}</td><td>${esc(d.serial)}</td><td>${esc(d.surveyor)}</td><td>${d.range ? Math.round(d.range) + " m" : ""}</td><td>${esc(d.notes)}</td><td>${d.map ? d.map.lat.toFixed(6) + ", " + d.map.lon.toFixed(6) : "not placed"}</td></tr>`).join("");
  const d = new Date();
  $("#plan-print").innerHTML = `<h1>${esc(pj.name)}: site plan</h1>
    <p>${sv ? esc(sv.label) + " · " : ""}${sv && sv.surveyor ? "Surveyor(s): " + esc(sv.surveyor) + " · " : ""}Printed ${d.toLocaleDateString("en-GB")}${pj.site ? ` · Site ${pj.site.lat.toFixed(6)}, ${pj.site.lon.toFixed(6)}` : ""}</p>
    <table><thead><tr><th>No.</th><th>Camera</th><th>Model and lens</th><th>Facing</th><th>Range</th><th>Pixel size</th><th>Pixels on 0.1 m target</th><th>Surveyor</th><th>GPS</th></tr></thead><tbody>${rows || '<tr><td colspan="9">No cameras placed yet.</td></tr>'}</tbody></table>
    ${dets.length ? `<h2>Acoustic detectors</h2><table><thead><tr><th>No.</th><th>Name</th><th>Model</th><th>Serial no.</th><th>Surveyor</th><th>Range</th><th>Other info</th><th>GPS</th></tr></thead><tbody>${drows}</tbody></table>` : ""}`;
  const dpts = (sv ? sv.detectors || [] : []).filter((x) => x.map).map((x) => [x.map.lat, x.map.lon]);
  if (cams.length || dpts.length) {
    const pts = cams.flatMap((c) => conePoints(c.map)).concat(dpts);
    MAPS.map.fitBounds(L.latLngBounds(pts), { padding: [30, 30] });
  }
  document.body.classList.add("printing-plan");
  setTimeout(() => { MAPS.map.invalidateSize(); setTimeout(() => { window.print(); }, 900); }, 200);
};
window.addEventListener("afterprint", () => { document.body.classList.remove("printing-plan"); if (MAPS.map) MAPS.map.invalidateSize(); });
$("#map-survey").onchange = () => { MAPS.sv = $("#map-survey").value; MAPS.sel = null; drawMap(); };
$("#map-surveyor").onchange = async () => { const sv = mapSurvey(); if (!sv) return; sv.surveyor = $("#map-surveyor").value.trim();
  try { await api("/api/org", { action: "set_info", id: sv.id, surveyor: sv.surveyor }); } catch (e) { err(e); } };
$("#map-close").onclick = () => $("#dlg-map").close();
$("#dlg-map").addEventListener("close", async () => {
  // a pre-survey template: the plan is saved as the template each time it's closed
  const pj = mapProject(), sv = mapSurvey();
  if (pj && pj.pre_survey && sv && sv.cameras.some((c) => c.map)) {
    try { await api("/api/org", { action: "save_template", survey: sv.id }); toast(`${pj.name}: pre-survey template saved (${plural(sv.cameras.length, "camera")}).`, 5000); } catch (e) { err(e); }
  }
  refreshFiles();
});
$("#map-search").onsubmit = async (e) => {
  e.preventDefault();
  const q = $("#map-q").value.trim(); if (!q) return;
  const ll = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (ll) { MAPS.map.setView([+ll[1], +ll[2]], 18); return; }
  const box = $("#map-results"); box.hidden = false; box.textContent = "Searching…";
  try {
    const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=6&q=${encodeURIComponent(q)}`, { headers: { "Accept-Language": "en-GB" } });
    const hits = await res.json();
    if (!hits.length) { box.textContent = "Nothing found. Try a postcode, or type the latitude and longitude."; return; }
    box.innerHTML = "";
    for (const h of hits) {
      const b = el("button", "map-hit", esc(h.display_name)); b.type = "button";
      b.onclick = () => { MAPS.map.setView([+h.lat, +h.lon], 18); box.hidden = true; };
      box.appendChild(b);
    }
  } catch (er) { box.textContent = "Couldn't search: the map needs an internet connection."; }
};
