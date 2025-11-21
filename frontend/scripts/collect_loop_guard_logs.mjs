import { chromium } from "playwright";

const target = process.env.PW_TARGET ?? "http://127.0.0.1:4176/";
const sampleMs = Number(process.env.PW_SAMPLE_MS ?? "5000");

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();

page.on("console", (msg) => {
    console.log(`[console] ${msg.type()} ${msg.text()}`);
});

page.on("pageerror", (err) => {
    console.error("[pageerror]", err);
});

try {
    await page.goto(target, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(sampleMs);
} finally {
    await browser.close();
}
