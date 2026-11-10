// Build step: copy static/ to build/static/ with the JavaScript compressed and
// its names scrambled, and the CSS and HTML minified, so the shipped program
// doesn't contain readable source. Run from the project folder:
//   npm install terser@5 csso@5 html-minifier-terser@7
//   node tools/minify.mjs
import { minify as terser } from "terser";
import { minify as csso } from "csso";
import { minify as html } from "html-minifier-terser";
import fs from "node:fs";
import path from "node:path";

const SRC = "static", OUT = path.join("build", "static");
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

for (const name of fs.readdirSync(SRC)) {
  const from = path.join(SRC, name), to = path.join(OUT, name);
  const text = () => fs.readFileSync(from, "utf8");
  if (name.endsWith(".js")) {
    // wrapped in its own function so its scrambled names can't clash with
    // any other script on the page
    const r = await terser("(() => {\n" + text() + "\n})();", {
      compress: { passes: 2, drop_debugger: true },
      mangle: { toplevel: true },          // rename functions and variables
      format: { comments: false },
    });
    fs.writeFileSync(to, r.code);
  } else if (name.endsWith(".css")) {
    fs.writeFileSync(to, csso(text()).css);
  } else if (name.endsWith(".html")) {
    fs.writeFileSync(to, await html(text(), {
      collapseWhitespace: true, removeComments: true, minifyCSS: true, minifyJS: true,
    }));
  } else {
    fs.copyFileSync(from, to);
  }
  console.log("  " + name);
}
