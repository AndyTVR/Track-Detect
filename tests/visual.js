// Screenshots of the main screens, to compare before and after a tidy-up
// that shouldn't change how anything looks. Usage: node tests/visual.js <url> <recordings folder> <out folder>
const { chromium } = require("playwright");
const [URL, DIR, OUT] = process.argv.slice(2);
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1500, height: 1100 } });
  p.on("dialog", (d) => d.accept());
  await p.addInitScript(() => { try { localStorage.clear(); } catch (e) {} });
  await p.goto(URL); await p.waitForTimeout(800);
  await p.screenshot({ path: OUT + "/0-empty.png" });
  await p.click("#btn-open"); await p.click("#om-new"); await p.fill("#np-name", "Visual"); await p.click("#np-go"); await p.waitForTimeout(400);
  await p.fill("#folder-input", ["rhino front 1.ats", "rhino rear 1.ats", "synthetic.ats"].map((n) => DIR + "/" + n).join("\n"));
  await p.selectOption("#add-cam", "__auto"); await p.waitForTimeout(200);
  await p.locator("#dlg-folder").screenshot({ path: OUT + "/1-add.png" });
  await Promise.all([p.waitForResponse((r) => r.url().includes("/api/add")), p.click("#btn-folder-ok")]); await p.waitForTimeout(1500);
  await p.locator(".file", { hasText: "synthetic" }).click(); await p.waitForTimeout(1500);
  await p.evaluate(() => { const t = document.querySelector("#toast"); t.classList.remove("show"); });
  await p.screenshot({ path: OUT + "/2-main.png" });
  await p.click(".mode[data-mode=blend]"); await p.click("#btn-persist"); await p.waitForTimeout(300);
  await p.screenshot({ path: OUT + "/3-detection.png" });
  await p.keyboard.press("Escape"); await p.click("body", { position: { x: 5, y: 700 } });
  await p.locator(".pm-btn").first().click(); await p.waitForTimeout(200);
  await p.screenshot({ path: OUT + "/4-projmenu.png", clip: { x: 0, y: 60, width: 420, height: 700 } });
  await p.click("body", { position: { x: 5, y: 700 } });
  await p.click("#btn-settings"); await p.waitForTimeout(400);
  await p.screenshot({ path: OUT + "/5-settings.png" });
  await p.keyboard.press("Escape");
  await p.getByRole("button", { name: "Site Plan", exact: true }).click(); await p.waitForTimeout(600);
  await p.locator("#map-cams .mc").nth(1).getByRole("button", { name: "Place on map" }).click(); await p.waitForTimeout(400);
  await p.screenshot({ path: OUT + "/6-siteplan.png" });
  await b.close();
})();
