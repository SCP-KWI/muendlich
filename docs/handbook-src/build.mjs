// Builds the standalone handbook: inlines fonts, screenshots and the numbered
// arrow overlays into a single HTML file.
import { readFileSync, writeFileSync } from "node:fs";

const SP = new URL("./", import.meta.url).pathname;   // docs/handbook-src/
const REPO = new URL("../../", import.meta.url).pathname;
const SHOTS = `${SP}shots/`;
const FONTS = `${REPO}frontend/node_modules/@fontsource/`;
const rects = JSON.parse(readFileSync(`${SHOTS}rects.json`, "utf8"));

// ---- figures ---------------------------------------------------------------
// crop: [y0, y1] in page CSS px. only: subset of mark numbers to draw.
const FIGURES = {
  login: { shot: "01-login", crop: [24, 400] },
  klassen: { shot: "02-klassen-verwalten", crop: [66, 1010] },
  sus: { shot: "03-sus-verwalten", crop: [150, 726], only: [3, 4, 5, 6] },
  "sus-neu": { shot: "03-sus-verwalten", crop: [1540, 2295], only: [1, 2] },
  klassenwahl: { shot: "07-klasse-waehlen", crop: [70, 420] },
  aufnahme: { shot: "08-aufnahme", crop: [150, 840] },
  cloud: { shot: "10-an-die-cloud", crop: [270, 620] },
  pruefen: { shot: "09-pruefen", crop: [196, 620], only: [1, 2, 3, 4, 5] },
  "pruefen-neu": { shot: "09-pruefen", crop: [1190, 1610], only: [6, 7] },
  gespeichert: { shot: "11-gespeichert", crop: [200, 522] },
  uebersicht: { shot: "05-klassenuebersicht", crop: [198, 750] },
  detail: { shot: "06-schueler-detail", crop: [230, 622] },
};

const b64 = (p) => readFileSync(p).toString("base64");

function figure(key) {
  const cfg = FIGURES[key];
  if (!cfg) throw new Error(`unknown figure ${key}`);
  const m = rects[cfg.shot];
  if (!m) throw new Error(`no rects for ${cfg.shot}`);
  const marks = m.marks.filter(
    (r) => !r.missing && (!cfg.only || cfg.only.includes(r.n))
  );
  const [y0, y1] = cfg.crop ?? [0, m.pageH];

  const contentL = Math.min(...marks.map((r) => r.x));
  const contentR = Math.max(...marks.map((r) => r.x + r.w));
  const bxL = contentL - 46;
  const bxR = contentR + 46;
  const minX = Math.min(0, bxL - 22);
  const maxX = Math.max(m.pageW, bxR + 22);

  const R = 14;
  const parts = [];
  for (const r of marks) {
    // dy nudges the BADGE only, so marks sharing a row don't collide. The arrow
    // still has to land on the element: when the badge is offset, the line runs
    // horizontally out of it and then bends onto the element's true centre. A
    // straight line from an offset badge points at empty space beside the mark.
    const cyTarget = Math.round(r.y + r.h / 2);
    const cyBadge = cyTarget + (r.dy || 0);
    const left = r.side === "l";
    const bx = left ? bxL : bxR;
    const x1 = left ? bx + R + 2 : bx - R - 2;
    const x2 = left ? r.x - 7 : r.x + r.w + 7;
    if (Math.abs(x2 - x1) > 8) {
      const bend = left ? Math.max(x1, x2 - 26) : Math.min(x1, x2 + 26);
      const d =
        cyBadge === cyTarget
          ? `M${x1} ${cyTarget} H${x2}`
          : `M${x1} ${cyBadge} H${bend} L${x2} ${cyTarget}`;
      parts.push(
        `<path class="hal" d="${d}"/>`,
        `<path class="arw" d="${d}" marker-end="url(#ah-${key})"/>`
      );
    }
    parts.push(
      `<circle class="bdg" cx="${bx}" cy="${cyBadge}" r="${R}"/>`,
      `<text class="bdgt" x="${bx}" y="${cyBadge + 1}">${r.n}</text>`
    );
  }

  const img = b64(`${SHOTS}web/${cfg.shot}.webp`);
  return `<svg class="fig fig--${m.device}" viewBox="${minX} ${y0} ${maxX - minX} ${y1 - y0}" role="img">
<defs><marker id="ah-${key}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="currentColor"/></marker></defs>
<image href="data:image/webp;base64,${img}" x="0" y="0" width="${m.pageW}" height="${m.pageH}"/>
${parts.join("\n")}
</svg>`;
}

// ---- fonts -----------------------------------------------------------------
const face = (fam, file, weight, range) =>
  `@font-face{font-family:"${fam}";font-style:normal;font-weight:${weight};font-display:swap;` +
  `src:url(data:font/woff2;base64,${b64(FONTS + file)}) format("woff2");` +
  (range ? `unicode-range:${range};` : "") +
  `}`;

const LATIN =
  "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD";
const LATIN_EXT =
  "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF";

const fonts = [
  face("Source Sans 3", "source-sans-3/files/source-sans-3-latin-400-normal.woff2", 400, LATIN),
  face("Source Sans 3", "source-sans-3/files/source-sans-3-latin-ext-400-normal.woff2", 400, LATIN_EXT),
  face("Source Sans 3", "source-sans-3/files/source-sans-3-latin-600-normal.woff2", 600, LATIN),
  face("Source Sans 3", "source-sans-3/files/source-sans-3-latin-ext-600-normal.woff2", 600, LATIN_EXT),
  face("Source Sans 3", "source-sans-3/files/source-sans-3-latin-700-normal.woff2", 700, LATIN),
  face("IBM Plex Mono", "ibm-plex-mono/files/ibm-plex-mono-latin-400-normal.woff2", 400, LATIN),
  face("IBM Plex Mono", "ibm-plex-mono/files/ibm-plex-mono-latin-600-normal.woff2", 600, LATIN),
].join("\n");

// ---- assemble --------------------------------------------------------------
let html = readFileSync(`${SP}handbuch.src.html`, "utf8");
html = html.replace(/\{\{FONTS\}\}/g, fonts);
html = html.replace(/\{\{FIG:([a-z0-9-]+)\}\}/g, (_, k) => figure(k));

// The served copy lives in the PWA's public dir: that is the only location the
// frontend Docker build (context: frontend/) can see, and Vite serves it in dev
// and copies it into dist/ on build — one file, same path everywhere.
// docs/handbuch.html is a symlink to it, so the documented path still resolves.
const out = `${REPO}frontend/public/handbuch.html`;
writeFileSync(out, html);
console.log(`wrote ${out} — ${(html.length / 1024 / 1024).toFixed(2)} MB`);
