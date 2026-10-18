import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { readdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const testDirectory = path.join(frontendRoot, "tests");
const require = createRequire(import.meta.url);
const playwrightPath = fileURLToPath(import.meta.resolve("playwright"));
const requestedNames = process.argv.slice(2).filter((argument) => argument !== "--");
const allNames = (await readdir(testDirectory)).filter((name) =>
  name.endsWith(".browser.mjs"),
);
const selectedNames = requestedNames.length
  ? allNames.filter((name) => requestedNames.includes(name) || requestedNames.includes(name.replace(".browser.mjs", "")))
  : allNames;
const credentialsRequired = new Set(["ordinary-payment-settings.browser.mjs"]);
const explicitlyRequested = new Set(selectedNames.filter((name) =>
  requestedNames.includes(name) || requestedNames.includes(name.replace(".browser.mjs", "")),
));
const skippedNames = selectedNames.filter((name) => credentialsRequired.has(name) && !explicitlyRequested.has(name));
const runnableNames = selectedNames.filter((name) => !skippedNames.includes(name));

assert(selectedNames.length > 0, "No matching browser tests were found.");
assert.equal(selectedNames.length, requestedNames.length || selectedNames.length, "A requested browser test was not found.");

const environment = {
  ...process.env,
  PLAYWRIGHT_MODULE: playwrightPath,
  CHROMIUM_EXECUTABLE: browserExecutable(),
};
let server = null;

if (!environment.PANEL_ORIGIN) {
  const origin = "http://127.0.0.1:4523";
  server = spawn(
    "pnpm",
    ["--filter", "@papilio/panel", "exec", "vite", "--host", "127.0.0.1", "--port", "4523", "--strictPort"],
    { cwd: frontendRoot, env: process.env, stdio: ["ignore", "pipe", "pipe"] },
  );
  environment.PANEL_ORIGIN = origin;
}

try {
  if (server) await waitUntilReady(server, environment.PANEL_ORIGIN);
  let passed = 0;
  let failed = 0;
  for (const name of skippedNames) {
    process.stdout.write(`[SKIP] ${name} (requires explicit credential input)\n`);
  }
  for (const name of runnableNames) {
    const result = spawnSync(process.execPath, [path.join(testDirectory, name)], {
      cwd: frontendRoot,
      env: environment,
      stdio: "inherit",
    });
    if (result.status === 0) {
      passed += 1;
      process.stdout.write(`[PASS] ${name}\n`);
    } else {
      failed += 1;
      process.stdout.write(`[FAIL] ${name} (exit ${result.status ?? result.signal})\n`);
    }
  }
  process.stdout.write(`Browser tests: ${passed} passed, ${failed} failed, ${skippedNames.length} skipped.\n`);
  process.exitCode = failed ? 1 : 0;
} finally {
  if (server && server.exitCode === null) {
    server.kill("SIGTERM");
    await waitForExit(server);
  }
}

function waitUntilReady(child, origin) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(new Error(`Panel development server did not start at ${origin}.`));
    }, 30000);
    const started = (chunk) => {
      const output = chunk.toString();
      process.stdout.write(output);
      if (output.includes(origin)) {
        clearTimeout(timeout);
        resolve();
      }
    };
    child.stdout.on("data", started);
    child.stderr.on("data", (chunk) => process.stderr.write(chunk));
    child.once("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.once("exit", (code) => {
      if (code !== null && code !== 0) {
        clearTimeout(timeout);
        reject(new Error(`Panel development server exited with code ${code}.`));
      }
    });
  });
}

function waitForExit(child) {
  if (child.exitCode !== null) return Promise.resolve();
  return Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 5000)),
  ]);
}

function browserExecutable() {
  const configured = process.env.CHROMIUM_EXECUTABLE;
  if (configured) return configured;

  const { chromium } = require("playwright");
  const bundled = chromium.executablePath();
  if (existsSync(bundled)) return bundled;

  const systemBrowser = ["google-chrome", "chromium", "chromium-browser"]
    .map((name) => spawnSync("which", [name], { encoding: "utf8" }))
    .find((result) => result.status === 0 && result.stdout.trim());
  assert(systemBrowser, "Install Playwright Chromium or set CHROMIUM_EXECUTABLE.");
  return systemBrowser.stdout.trim();
}
