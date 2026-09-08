import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const playwrightImport = process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES
  ? path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES, "playwright", "index.mjs")
  : "playwright";
const {chromium} = await import(playwrightImport);

const url = process.env.PM_HOSTED_URL;
if (!url || !url.startsWith("https://")) throw new Error("PM_HOSTED_URL must be the deployed HTTPS Preview URL.");
const expectedOrigin = new URL(url).origin;
const evidenceDir = path.resolve(process.env.PM_HOSTED_EVIDENCE_DIR || "/tmp/pm-hosted-native-planning-ui-evidence");
if (evidenceDir === path.parse(evidenceDir).root) throw new Error("Refusing to use a filesystem root as the evidence directory.");
fs.mkdirSync(evidenceDir, {recursive: true});

const observations = [];
const consoleErrors = [];
const apiFailures = [];
const apiRequests = [];
const timings = [];
const runtimeDiagnostics = [];

function assert(condition, message) {
  if (!condition) throw new Error(`Assertion failed: ${message}`);
  observations.push(`PASS: ${message}`);
}

function watch(page, label) {
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(`${label}: ${message.text()}`); });
  page.on("pageerror", (error) => consoleErrors.push(`${label} pageerror: ${error.message}`));
  page.on("request", (request) => {
    if (request.url().includes("/api/")) apiRequests.push({url: request.url(), method: request.method()});
  });
  page.on("response", (response) => {
    if (response.url().includes("/api/") && response.status() >= 400) apiFailures.push(`${response.status()} ${response.url()}`);
  });
}

async function ready(page) {
  await page.locator("#activity-list .activity-row").first().waitFor({state: "visible"});
}

async function calculate(page, label) {
  const started = performance.now();
  await page.getByRole("button", {name: "Calculate plan / recovery"}).click();
  await page.locator("#proposal-state").filter({hasText: "current"}).waitFor();
  const elapsed = Math.round(performance.now() - started);
  const runtime = await page.evaluate(() => window.__pmTrialRuntime?.at(-1) || null);
  timings.push({label, browser_elapsed_ms: elapsed, server_elapsed_ms: runtime?.server_elapsed_ms ?? null});
  runtimeDiagnostics.push({label, ...runtime});
  return elapsed;
}

async function approve(page) {
  await page.getByRole("button", {name: "Approve displayed proposal"}).click();
  await page.locator("#approved-state").filter({hasText: "current"}).waitFor();
}

async function fillAndBlur(locator, value) {
  await locator.fill(value);
  await locator.press("Tab");
}

async function save(page, destination) {
  const event = page.waitForEvent("download");
  await page.getByRole("button", {name: "Save workspace"}).click();
  await (await event).saveAs(destination);
}

const browser = await chromium.launch({headless: true});
try {
  const context = await browser.newContext({viewport: {width: 1366, height: 900}, acceptDownloads: true});
  await context.tracing.start({screenshots: true, snapshots: true, sources: true});
  const page = await context.newPage();
  watch(page, "desktop");
  await page.goto(url, {waitUntil: "networkidle"});
  await ready(page);
  assert(page.url().startsWith(expectedOrigin), "the trial loads from the deployed Vercel HTTPS origin");
  assert(await page.getByRole("heading", {name: "Native planning trial"}).isVisible(), "the existing native planning UI renders from the Preview URL");
  assert((await page.locator("footer").innerText()).includes("Hosted bounded trial"), "the UI identifies its stateless hosted boundary");

  await page.getByRole("button", {name: "Load example"}).click();
  await page.getByText(/Built-in eight-activity example loaded/).waitFor();
  await calculate(page, "first example calculation");
  let state = await page.evaluate(() => window.__pmTrialState);
  assert(state.workspace.proposal.selected_modes.A03 === "SPECIALIST", "hosted example selects A03 SPECIALIST");
  assert(state.workspace.proposal.project_finish === 30, "hosted example finishes Day 1 15:00");
  assert(state.workspace.proposal.physical_status === "PROVEN_FEASIBLE", "hosted example passes the exact physical checker");
  assert(state.workspace.proposal.solver.name === "CP-SAT", "the deployed Python backend returns a CP-SAT result");
  assert(await page.locator(".timeline-row").filter({hasText: "A03"}).locator(".timeline-segment").count() === 2, "hosted timeline displays A03 lunch suspension as separate productive segments");
  await page.screenshot({path: path.join(evidenceDir, "01-hosted-example-1366x900.png"), fullPage: true});

  await approve(page);
  const approvedHash = await page.evaluate(() => window.__pmTrialState.workspace.approved_plan.plan_hash);
  const trustedHash = await page.evaluate(() => window.__pmTrialState.trusted_input_hash);
  await page.locator("#outage-resource").selectOption("M2");
  await fillAndBlur(page.locator("#outage-start"), "1@10:00");
  await fillAndBlur(page.locator("#outage-finish"), "1@17:00");
  await page.getByRole("button", {name: "Report unavailable"}).click();
  await page.locator("#reports-list .badge").filter({hasText: "REPORTED"}).waitFor();
  state = await page.evaluate(() => window.__pmTrialState);
  assert(state.trusted_input_hash === trustedHash, "reported-only outage leaves trusted inputs unchanged");
  assert(state.workspace.approved_plan.plan_hash === approvedHash, "reported-only outage leaves approval unchanged");
  assert(state.workspace.proposal === null, "reporting alone does not silently calculate a plan");

  await page.getByRole("button", {name: "Accept selected report"}).click();
  await page.locator("#reports-list .badge").filter({hasText: "ACCEPTED"}).waitFor();
  assert((await page.locator("#approved-state").innerText()).toLowerCase().includes("stale"), "accepting the outage makes the old approval visibly stale");
  await calculate(page, "recovery calculation");
  state = await page.evaluate(() => window.__pmTrialState);
  const recovery = state.workspace.proposal;
  assert(recovery.selected_modes.A03 === "NORMAL", "hosted recovery changes A03 to NORMAL");
  assert(recovery.project_finish === 65, "hosted recovery finishes Day 2 08:30");
  assert(recovery.alternatives.find((item) => item.modes.A03 === "SPECIALIST")?.objective?.[0] === 71, "hosted recovery retains the SPECIALIST alternative at Day 2 11:30");
  assert(!recovery.approved_by, "hosted recovery remains separate from approval");
  await page.screenshot({path: path.join(evidenceDir, "02-hosted-recovery-1366x900.png"), fullPage: true});
  await approve(page);

  const savedPath = path.join(evidenceDir, "hosted-example-approved-recovery.pm-workspace.json");
  await save(page, savedPath);
  const saved = JSON.parse(fs.readFileSync(savedPath, "utf8"));
  assert(saved.approved_plan.selected_modes.A03 === "NORMAL", "download contains the approved hosted recovery");
  assert(saved.plan_history.length === 1 && saved.reports[0].status === "ACCEPTED", "download contains prior approval history and accepted availability");
  await context.tracing.stop({path: path.join(evidenceDir, "hosted-workflow-trace.zip")});
  await context.close();

  const reopenedContext = await browser.newContext({viewport: {width: 1920, height: 1080}, acceptDownloads: true});
  const reopenedPage = await reopenedContext.newPage();
  watch(reopenedPage, "reopen");
  await reopenedPage.goto(url, {waitUntil: "networkidle"});
  await ready(reopenedPage);
  await reopenedPage.locator("#open-file").setInputFiles(savedPath);
  await reopenedPage.getByText(/Opened .* without recalculating/).waitFor();
  state = await reopenedPage.evaluate(() => window.__pmTrialState);
  assert(state.workspace.approved_plan.selected_modes.A03 === "NORMAL", "fresh browser context reopens the approval without recalculation");
  assert(state.workspace.plan_history.length === 1 && state.workspace.proposal === null, "fresh browser context retains history and no pending proposal");
  assert(await reopenedPage.evaluate(() => document.documentElement.scrollWidth === document.documentElement.clientWidth), "1920px hosted layout has no page-level horizontal overflow");

  await reopenedPage.locator('.activity-row[data-activity-id="A01"]').click();
  await fillAndBlur(reopenedPage.locator('[data-mode-work="0"]'), "2");
  await reopenedPage.getByRole("button", {name: "Apply input changes"}).click();
  await reopenedPage.getByText(/Trusted project inputs applied/).waitFor();
  await calculate(reopenedPage, "post-reopen duration calculation");
  state = await reopenedPage.evaluate(() => window.__pmTrialState);
  const editedA01 = state.workspace.proposal.entries.find((item) => item.activity_id === "A01");
  assert(editedA01.periods.reduce((total, [start, finish]) => total + finish - start, 0) === 4, "post-reopen duration edit reaches the Python scheduler as two productive hours");
  observations.push(`OBSERVED: post-reopen duration proposal finish ${state.workspace.proposal.project_finish}`);
  await reopenedPage.screenshot({path: path.join(evidenceDir, "03-hosted-reopened-edited-1920x1080.png"), fullPage: true});
  await reopenedContext.close();

  const mobileContext = await browser.newContext({viewport: {width: 390, height: 844}});
  const mobilePage = await mobileContext.newPage();
  watch(mobilePage, "mobile");
  await mobilePage.goto(url, {waitUntil: "networkidle"});
  await ready(mobilePage);
  assert(await mobilePage.getByRole("button", {name: "Load example"}).isVisible(), "mobile-width view exposes workspace controls");
  await calculate(mobilePage, "mobile example calculation");
  assert((await mobilePage.locator("#proposal-state").innerText()).toLowerCase().includes("current"), "mobile-width view can perform the core calculation action");
  assert(await mobilePage.evaluate(() => document.documentElement.scrollWidth === document.documentElement.clientWidth), "390px hosted layout avoids page-level horizontal overflow");
  await mobilePage.screenshot({path: path.join(evidenceDir, "04-hosted-mobile-390x844.png"), fullPage: true});
  await mobileContext.close();

  assert(apiRequests.length > 0, "browser observed real deployed API requests");
  assert(apiRequests.every((item) => new URL(item.url).origin === expectedOrigin), "all API requests remain on the deployed origin");
  assert(apiRequests.every((item) => !/localhost|127\.0\.0\.1/.test(item.url)), "no browser API request uses loopback");
  assert(apiFailures.length === 0, "successful hosted workflow has no failed API responses");
  assert(consoleErrors.length === 0, "successful hosted workflow has no unexpected console errors");

  observations.push(`URL: ${expectedOrigin}`);
  observations.push(`TIMINGS: ${JSON.stringify(timings)}`);
  observations.push(`API REQUESTS: ${apiRequests.length}`);
  observations.push(`BROWSER: ${await browser.version()}`);
  observations.push("VIEWPORTS: 1366x900, 1920x1080, 390x844");
  fs.writeFileSync(path.join(evidenceDir, "hosted-browser-output.txt"), observations.join("\n") + "\n");
  fs.writeFileSync(path.join(evidenceDir, "hosted-performance.json"), JSON.stringify({
    origin: expectedOrigin,
    timings,
    runtime_diagnostics: runtimeDiagnostics,
    api_requests: apiRequests,
  }, null, 2) + "\n");
  console.log(observations.join("\n"));
} catch (error) {
  fs.writeFileSync(path.join(evidenceDir, "hosted-browser-output.txt"), `${observations.join("\n")}\nFAIL: ${error.stack}\nConsole errors: ${consoleErrors.join("\n")}\nAPI failures: ${apiFailures.join("\n")}\n`);
  throw error;
} finally {
  await browser.close();
}
