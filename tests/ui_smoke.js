// A quick check of the page in a real browser: everything main still works
// and nothing throws. Run with tests/run_all.sh (or see tests/README.md).
// Usage: node tests/ui_smoke.js <url> <folder of test recordings> [screenshot folder]
const { chromium } = require("playwright");
const [URL, DIR, SHOTS] = [process.argv[2] || "http://127.0.0.1:8897", process.argv[3], process.argv[4]];
const ok = [], bad = [];
const check = (name, cond, info = "") => (cond ? ok : bad).push(name + (cond ? "" : ` (${info})`));
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1500, height: 1100 } });
  const errs = [];
  p.on("pageerror", (e) => errs.push("page error: " + e.message));
  p.on("response", (r) => { if (r.status() >= 400 && r.url().startsWith(URL)) errs.push(`HTTP ${r.status()} ${r.url().slice(URL.length, URL.length + 60)}`); });
  p.on("dialog", (d) => d.accept());
  await p.goto(URL); await p.waitForTimeout(1000);
  check("start window shows on opening", await p.isVisible("#dlg-start"));
  // new pre-survey template: opens the site plan; closing saves the template once a camera is placed
  await p.click("#sd-tnew"); await p.fill("#np-name", "Plan A"); await p.click("#np-go"); await p.waitForTimeout(800);
  check("pre-survey template opens the site plan", await p.isVisible("#dlg-map"));
  await p.click("#map-close"); await p.waitForTimeout(500);
  await p.click("#btn-open"); await p.click("#om-topen"); await p.waitForTimeout(500);
  check("template listed under Open pre-survey template", /Plan A/.test(await p.textContent("#op-list")));
  await p.keyboard.press("Escape"); await p.waitForTimeout(200);
  check("top bar has four buttons", (await p.$$(".actions > button, .actions .open-wrap > button")).length === 4);
  // new project, add files sorted by name
  await p.click("#btn-open"); await p.click("#om-new"); await p.fill("#np-name", "Smoke"); await p.click("#np-go"); await p.waitForTimeout(500);
  await p.fill("#folder-input", ["rhino front 1.ats", "rhino front 2.ats", "rhino rear 1.ats", "synthetic.ats"].map((n) => DIR + "/" + n).join("\n"));
  await p.selectOption("#add-cam", "__auto");
  await Promise.all([p.waitForResponse((r) => r.url().includes("/api/add")), p.click("#btn-folder-ok")]); await p.waitForTimeout(1500);
  const cams = await p.$$eval(".cam-group", (g) => g.map((x) => x.querySelector(".cam-no").textContent));
  check("cameras made from file names", cams.length >= 3, cams.join(","));
  check("first recording opened", !!(await p.evaluate(() => S.rec && S.rec.name)));
  check("Event Log names the camera", /Camera/.test(await p.textContent("#log-cam")));
  const opts = await p.$$eval("#log-cam-pick option", (o) => o.map((x) => x.value));
  const before = await p.evaluate(() => S.rec.path);
  await p.selectOption("#log-cam-pick", opts.find((v) => v && v !== opts[0]) || opts[1]); await p.waitForTimeout(1500);
  check("camera chosen from the Event Log chip", (await p.evaluate(() => S.rec.path)) !== before, opts.join(","));
  check("camera boxes start folded", (await p.locator(".cam-group:not(.folded)").count()) === 0);
  check("a camera given several recordings joins them", await p.evaluate(() => S.tree.some((pj) => pj.surveys.some((s) => s.cameras.some((c) => c.join && c.joined)))));
  {  // click a folded camera's box that isn't showing: that camera shows
    const other = p.locator(".cam-group.pickable:not(.showing)").first();
    const cid = await other.getAttribute("data-cam");
    await other.locator(".cam-no").click(); await p.waitForTimeout(1500);
    const on = await p.evaluate((id) => { const at = findCam(id); return !!(S.rec && at && (at.camera.paths.includes(S.rec.path) || at.camera.joined === S.rec.path)); }, cid);
    check("clicking a folded camera's box shows that camera", on);
    check("the camera showing is highlighted", await p.locator(`.cam-group.showing[data-cam="${cid}"]`).count() === 1);
  }
  await p.click("#btn-fold-all"); await p.waitForTimeout(150); await p.click("#btn-fold-all"); await p.waitForTimeout(300);   // fold all, then open all
  check("open all shows the camera files", (await p.locator(".cam-group.folded").count()) === 0);
  // open synthetic, draw a rectangle, set it with a click
  await p.locator(".file", { hasText: "synthetic" }).click(); await p.waitForTimeout(1200);
  await p.click("[data-shape=rect]"); await p.waitForTimeout(200);
  const box = await p.locator("#roi-svg").boundingBox();
  await p.mouse.move(box.x + box.width * 0.06, box.y + box.height * 0.08); await p.mouse.down(); await p.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5, { steps: 6 }); await p.mouse.up(); await p.waitForTimeout(400);
  await p.mouse.click(box.x + box.width * 0.8, box.y + box.height * 0.85); await p.waitForTimeout(500);
  check("rectangle set with a click", !(await p.evaluate(() => S.drawing)));
  const pts = await p.evaluate(() => S.rec.rois[0].points);
  const w = Math.max(...pts.map((q) => q[0])) - Math.min(...pts.map((q) => q[0]));
  check("the click keeps the rectangle that was drawn", w > 300, JSON.stringify(pts));
  // scan its camera, watch the progress, see the event
  const cam = p.locator(".cam-group").filter({ has: p.locator(".file-name", { hasText: "synthetic.ats" }) });
  await cam.locator(".cam-scan").click(); await p.waitForTimeout(400);
  await p.waitForTimeout(300); const tst = await p.$eval(".toast", (t) => t.textContent).catch(() => "");
  await p.waitForFunction(() => S.rec && S.rec.scanned && !S.polling, null, { timeout: 120000 }).catch(() => {});
  await p.waitForTimeout(800);
  const evs = await p.$$(".ev");
  check("scan found events", evs.length >= 1, evs.length + " · " + tst + " · rois " + JSON.stringify(await p.evaluate(() => S.rec.rois.map((r) => [r.points.length, r.scan]))));
  if (evs.length) {
    await p.locator(".ev-head").first().click(); await p.waitForTimeout(300);
    await p.locator("[data-act=confirmed]").click(); await p.waitForTimeout(400);
    check("event confirmed", /Bat|Confirmed/.test(await p.locator(".ev").first().textContent()));
  }
  // a longer job: progress shows over the plot, then goes
  await p.click("#btn-export-camera"); await p.waitForTimeout(200); await p.click("#cv-go");
  check("progress shows over the plot", await p.waitForSelector("#job-overlay", { state: "visible", timeout: 8000 }).then(() => true, () => false));
  check("progress goes when done", await p.waitForSelector("#job-overlay", { state: "hidden", timeout: 120000 }).then(() => true, () => false));
  // viewing modes and the Detection menu
  for (const m of ["path", "blend", "custom", "raw"]) { await p.click(`.mode[data-mode=${m}]`); await p.waitForTimeout(250); }
  await p.click(".mode[data-mode=blend]"); await p.click("#btn-persist"); await p.waitForTimeout(200);
  check("Detection menu has trail length, blend, opacity", await p.isVisible("#f-frames") && await p.isVisible("#blend") && await p.isVisible("#opacity"));
  await p.keyboard.press("Escape"); await p.click("body", { position: { x: 5, y: 600 } });
  // y-axis buttons
  for (const y of ["linear", "log", "default"]) { await p.click(`[data-y=${y}]`); await p.waitForTimeout(150); }
  check("y-axis back to Default", (await p.evaluate(() => P.yMode)) === "default");
  // tree, fold, site plan, project menu
  await p.click("#btn-tree"); await p.waitForTimeout(300); check("tree lists recordings", (await p.$$(".tree-file")).length >= 4); await p.keyboard.press("Escape");
  await p.click("#btn-fold-all"); await p.waitForTimeout(150); await p.click("#btn-fold-all"); await p.waitForTimeout(150);
  await p.locator(".map-btn[title*=\"of Smoke\"]").click(); await p.waitForTimeout(600);
  await p.locator("#map-cams .mc").first().getByRole("button", { name: "Place on map" }).click(); await p.waitForTimeout(400);
  await p.click("#map-add-det"); await p.waitForTimeout(400);
  check("site plan has a camera and a detector", (await p.$$(".cam-pin")).length === 1 && (await p.$$("#map-dets .mc")).length === 1);
  await p.click("#map-close"); await p.waitForTimeout(400);
  await p.locator(".pm-btn").first().click(); await p.waitForTimeout(150);
  check("project menu has Save project", (await p.$$eval(".pm-menu:not([hidden]) .menu-item", (i) => i.map((x) => x.textContent))).includes("Save project"));
  await p.keyboard.press("Escape"); await p.click("body", { position: { x: 5, y: 600 } });
  // settings open and save
  await p.click("#btn-settings"); await p.waitForTimeout(400);
  await p.getByRole("button", { name: /Save settings/ }).click().catch(() => {}); await p.waitForTimeout(500);
  if (SHOTS) await p.screenshot({ path: SHOTS + "/ui_smoke.png" });
  check("no page errors", errs.length === 0, errs.join("; "));
  console.log(`${ok.length} passed, ${bad.length} failed`);
  for (const x of bad) console.log("FAILED: " + x);
  await b.close();
  process.exit(bad.length ? 1 : 0);
})();
