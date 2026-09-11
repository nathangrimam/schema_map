import { chromium } from "playwright";
import { spawn } from "node:child_process";
import http from "node:http";
import process from "node:process";

const managedServer = !process.env.SCHEMA_MAP_URL;
const baseUrl = process.env.SCHEMA_MAP_URL || "http://127.0.0.1:8877/";
const server = managedServer
  ? spawn("python3", ["schema_map.py", "serve", "tests/mysql_sample.sql", "--no-open", "--port", "8877"], {
      cwd: process.cwd(), stdio: ["ignore", "pipe", "pipe"],
    })
  : null;

async function waitForServer() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const ready = await new Promise((resolve) => {
      const request = http.get(baseUrl, (response) => {
        response.resume();
        response.on("end", () => resolve(response.statusCode === 200));
      });
      request.on("error", () => resolve(false));
    });
    if (ready) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const stderr = server ? await new Promise((resolve) => {
    let value = "";
    server.stderr.on("data", (chunk) => { value += chunk; });
    setTimeout(() => resolve(value), 100);
  }) : "";
  throw new Error(`servidor não iniciou: ${stderr}`);
}

await waitForServer();
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("console", (message) => {
  if (message.type() === "error") errors.push(`console: ${message.text()}`);
});
page.on("pageerror", (error) => errors.push(`page: ${error.message}`));

try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.locator("#tbllist li").first().click();
  await page.locator("#inspector:not([hidden])").waitFor();
  await page.locator("#inspectorClose").click();

  const table = page.locator(".tb").first();
  const tableBox = await table.boundingBox();
  if (!tableBox) throw new Error("tabela não possui área clicável");
  await page.mouse.click(tableBox.x + Math.min(18, tableBox.width / 3), tableBox.y + 10);
  await page.locator("#inspector:not([hidden])").waitFor();
  const selectedTable = await page.locator(".schema-inspector__selection select").inputValue();
  if (!selectedTable) throw new Error("clique na tabela não selecionou uma entidade");

  await page.locator("#inspectorClose").click();
  const zoomedBox = await table.boundingBox();
  if (!zoomedBox) throw new Error("tabela deixou de possuir área clicável");
  await page.mouse.click(
    zoomedBox.x + Math.min(24, zoomedBox.width / 3),
    zoomedBox.y + Math.min(48, zoomedBox.height - 4),
  );
  await page.locator("#inspector:not([hidden])").waitFor();
  const activeTab = await page.locator(".schema-inspector__tabs .is-active").textContent();
  if (activeTab?.trim() !== "Colunas") {
    throw new Error(`clique na coluna abriu a aba ${activeTab || "nenhuma"}`);
  }
  await page.locator(".schema-inspector__form--card").waitFor();
  await page.screenshot({ path: "/tmp/schema-map-inspector-click.png", fullPage: true });

  if (errors.length) throw new Error(errors.join("\n"));
  console.log(JSON.stringify({
    ok: true,
    selectedTable,
    activeTab: activeTab.trim(),
    screenshot: "/tmp/schema-map-inspector-click.png",
  }));
} finally {
  await browser.close();
  if (server) server.kill("SIGINT");
}
