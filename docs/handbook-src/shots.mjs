// Drives the running dev app, writes handbook screenshots to ./shots and the
// bounding boxes of the annotated elements to ./shots/rects.json.
import puppeteer from "puppeteer-core";

const CHROME = process.env.CHROME_PATH || "/usr/bin/chromium";
import { writeFileSync } from "node:fs";

const BASE = process.env.APP_URL || "http://localhost:5173";
const OUT = new URL("./shots/", import.meta.url).pathname;
const EMAIL = "m.beispiel@schule.ch";
const PASSWORD = "handbuch-demo-2026";

const DESKTOP = { width: 1000, height: 800, deviceScaleFactor: 2 };
const MOBILE = {
  width: 390,
  height: 844,
  deviceScaleFactor: 3,
  isMobile: true,
  hasTouch: true,
};

const DICTATION =
  "Anna hat im Unterricht Netflix geschaut und liess sich auch durch wiederholte " +
  "Einwände meinerseits nicht davon überzeugen, dass der Unterricht spannender sein " +
  "könnte als ihre Serie. Colin hat die Diskussion zu Faust gerettet. Darian war " +
  "körperlich anwesend. Feli hat die Hausaufgaben vergessen, dafür eine kreative " +
  "Ausrede geliefert. Yannick hat sich gleich zweimal gemeldet.";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const meta = {};

async function clickText(page, selector, text) {
  const ok = await page.evaluate(
    (sel, txt) => {
      const el = [...document.querySelectorAll(sel)].find((e) =>
        e.textContent.trim().includes(txt)
      );
      if (!el) return false;
      el.click();
      return true;
    },
    selector,
    text
  );
  if (!ok) throw new Error(`no ${selector} matching "${text}"`);
  await sleep(500);
}

// The guided tour opens on a first login (and always for the demo teacher);
// it would sit on top of every screenshot.
async function dismissTour(page) {
  const find = () =>
    [...document.querySelectorAll("button")].find((b) =>
      ["Überspringen", "Schliessen"].includes(b.textContent.trim())
    );
  // It opens once /api/me has answered, a moment after the tabs render.
  const btn = await page
    .waitForFunction(find, { timeout: 4000 })
    .catch(() => null);
  if (!btn) return;
  await btn.asElement().click();
  await sleep(400);
}

// specs: [{ n, sel, nth?, text?, side }]  — sel resolved in page, optionally
// filtered by contained text or index.
async function shot(page, name, device, specs = []) {
  await sleep(350);
  await page.screenshot({ path: `${OUT}${name}.png`, fullPage: true });
  const info = await page.evaluate((sp) => {
    const box = (el) => {
      const r = el.getBoundingClientRect();
      return {
        x: r.left + window.scrollX,
        y: r.top + window.scrollY,
        w: r.width,
        h: r.height,
      };
    };
    const out = [];
    for (const s of sp) {
      let els = [...document.querySelectorAll(s.sel)];
      if (s.text) els = els.filter((e) => e.textContent.includes(s.text));
      const el = els[s.nth ?? 0];
      if (!el) {
        out.push({ n: s.n, missing: s.sel });
        continue;
      }
      out.push({ n: s.n, side: s.side, dy: s.dy ?? 0, ...box(el) });
    }
    return {
      pageW: document.documentElement.scrollWidth,
      pageH: document.documentElement.scrollHeight,
      marks: out,
    };
  }, specs);
  meta[name] = { device, ...info };
  const missing = info.marks.filter((m) => m.missing);
  if (missing.length) console.log("  !! missing:", missing);
  console.log("wrote", name, `${info.pageW}x${info.pageH}`);
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--font-render-hinting=none", "--force-color-profile=srgb"],
});

// ---------- desktop ----------
{
  const page = await browser.newPage();
  await page.setViewport(DESKTOP);

  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('input[type="email"]');
  await page.type('input[type="email"]', EMAIL, { delay: 8 });
  await page.type('input[type="password"]', PASSWORD, { delay: 8 });
  await shot(page, "01-login", "desktop", [
    { n: 1, sel: 'input[type="email"]', side: "l" },
    { n: 2, sel: 'input[type="password"]', side: "l" },
    { n: 3, sel: 'button[type="submit"]', side: "r" },
  ]);

  await page.click('button[type="submit"]');
  await page.waitForSelector(".tabs", { timeout: 10000 });
  await dismissTour(page);
  await sleep(600);

  await clickText(page, ".tab", "Verwalten");
  await page.waitForSelector(".add-form");
  await shot(page, "02-klassen-verwalten", "desktop", [
    { n: 1, sel: ".tab", text: "Verwalten", side: "r" },
    { n: 2, sel: '.add-form input[placeholder^="Name"]', side: "l" },
    { n: 3, sel: ".add-form .row", side: "l" },
    { n: 4, sel: ".class-roster", side: "l" },
    { n: 5, sel: '.add-form button[type="submit"]', side: "l" },
    { n: 6, sel: ".manage-open", nth: 1, side: "l" },
    { n: 7, sel: ".manage-actions", nth: 1, side: "r" },
  ]);

  await clickText(page, ".manage-open", "3a Deutsch");
  await page.waitForSelector(".student-edit");
  await shot(page, "03-sus-verwalten", "desktop", [
    { n: 1, sel: ".batch-form", side: "l" },
    { n: 2, sel: ".single-form", side: "l" },
    { n: 3, sel: ".stud-name", side: "l" },
    { n: 4, sel: ".stud-short", side: "r" },
    { n: 5, sel: ".alias-row", nth: 2, side: "l" },
    { n: 6, sel: ".manage-item .manage-actions", nth: 2, side: "r" },
  ]);

  await clickText(page, ".tab", "Übersicht");
  await page.waitForSelector(".class-item");
  await clickText(page, ".class-item", "3a Deutsch");
  await page.waitForSelector(".student-item");
  await shot(page, "05-klassenuebersicht", "desktop", [
    { n: 1, sel: ".export-row", side: "l" },
    { n: 2, sel: ".student-item", side: "l" },
    { n: 3, sel: ".student-item .counts", nth: 0, side: "r" },
  ]);

  await clickText(page, ".student-item", "Anna Meier");
  await page.waitForSelector(".trend");
  await shot(page, "06-schueler-detail", "desktop", [
    { n: 1, sel: ".trend .bar", side: "l" },
    { n: 2, sel: ".avg", side: "r" },
    { n: 3, sel: ".obs-item textarea", side: "l" },
    { n: 4, sel: ".obs-item select", side: "l" },
    { n: 5, sel: ".obs-item .score", side: "r" },
    { n: 6, sel: ".obs-item .del", side: "r" },
  ]);

  await page.close();
}

// ---------- mobile ----------
{
  const page = await browser.newPage();
  await page.setViewport(MOBILE);
  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('input[type="email"], .tabs', { timeout: 15000 });
  if (await page.$('input[type="email"]')) {
    await page.type('input[type="email"]', EMAIL, { delay: 8 });
    await page.type('input[type="password"]', PASSWORD, { delay: 8 });
    await page.click('button[type="submit"]');
    await page.waitForSelector(".tabs", { timeout: 10000 });
    await dismissTour(page);
  }
  await sleep(600);

  await page.waitForSelector(".class-item");
  await shot(page, "07-klasse-waehlen", "mobile", [
    { n: 1, sel: ".tab", text: "Aufnehmen", side: "l" },
    { n: 2, sel: ".class-item", nth: 1, side: "r" },
  ]);

  await clickText(page, ".class-item", "3a Deutsch");
  await page.waitForSelector("textarea.transcript");
  // no red squiggles in the handbook, please
  await page.evaluate(() => {
    document.querySelector("textarea.transcript").spellcheck = false;
  });
  await page.type("textarea.transcript", DICTATION, { delay: 0 });
  await sleep(300);
  await page.evaluate(() => {
    document.querySelector("textarea.transcript").scrollTop = 0;
  });
  await shot(page, "08-aufnahme", "mobile", [
    { n: 1, sel: "textarea.transcript", side: "l" },
    { n: 2, sel: ".hint", side: "r" },
    { n: 3, sel: "button.primary", side: "l" },
    { n: 4, sel: ".roster-list", side: "r" },
  ]);

  await clickText(page, "button.primary", "Auswerten");
  await page.waitForSelector(".draft-item", { timeout: 15000 });
  await shot(page, "09-pruefen", "mobile", [
    { n: 1, sel: "details.sent-box", side: "l" },
    { n: 2, sel: ".draft-item .badge.ok", side: "r" },
    { n: 3, sel: ".draft-item textarea", side: "l" },
    { n: 4, sel: ".draft-controls select", nth: 0, side: "l" },
    { n: 5, sel: ".draft-controls select", nth: 1, side: "r" },
    { n: 6, sel: ".draft-item .badge.warn", side: "r" },
    { n: 7, sel: "button.primary", side: "l" },
  ]);

  await page.evaluate(() => {
    const d = document.querySelector("details.sent-box");
    if (d) d.open = true;
  });
  await sleep(250);
  await shot(page, "10-an-die-cloud", "mobile", [
    { n: 1, sel: ".sent-text", side: "l" },
    { n: 2, sel: ".sent-box .muted.small", side: "r" },
  ]);

  await page.evaluate(() => {
    const d = document.querySelector("details.sent-box");
    if (d) d.open = false;
  });
  await sleep(200);

  await clickText(page, "button.primary", "Speichern");
  await page.waitForSelector(".big-ok", { timeout: 15000 });
  await shot(page, "11-gespeichert", "mobile", [
    { n: 1, sel: "button.primary", side: "l" },
  ]);

  await page.close();
}

writeFileSync(`${OUT}rects.json`, JSON.stringify(meta, null, 2));
await browser.close();
console.log("done");
