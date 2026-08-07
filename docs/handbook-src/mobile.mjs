import puppeteer from "puppeteer-core";

const CHROME = process.env.CHROME_PATH || "/usr/bin/chromium";
const DOC = new URL("../handbuch.html", import.meta.url).href;
const browser = await puppeteer.launch({executablePath: CHROME,headless:"new",args:["--allow-file-access-from-files"]});
const page = await browser.newPage();
await page.setViewport({width:390,height:844,deviceScaleFactor:2,isMobile:true});
await page.goto(DOC,{waitUntil:"networkidle0"});
await new Promise(r=>setTimeout(r,600));
const w = await page.evaluate(()=>document.documentElement.scrollWidth);
console.log("scrollWidth", w, "(viewport 390 — no horizontal overflow if equal)");
await page.screenshot({path:`${new URL("./check/",import.meta.url).pathname}mobile-0.png`});
await page.evaluate(()=>window.scrollTo(0,4200));
await new Promise(r=>setTimeout(r,300));
await page.screenshot({path:`${new URL("./check/",import.meta.url).pathname}mobile-1.png`});
await browser.close();
