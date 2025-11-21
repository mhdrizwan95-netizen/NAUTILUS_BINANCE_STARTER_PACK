import { chromium } from "playwright";
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
page.on("console", (msg) => {
    console.log("[console]", msg.type(), msg.text());
});
page.on("pageerror", (err) => {
    console.error("[pageerror]", err);
});
await page.goto("http://127.0.0.1:4176/", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(4000);
await browser.close();
