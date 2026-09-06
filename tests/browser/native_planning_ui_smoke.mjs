import {spawn} from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const playwrightImport = process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES
  ? path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES, "playwright", "index.mjs")
  : "playwright";
const {chromium} = await import(playwrightImport);

const evidenceDir = path.resolve(process.env.PM_UI_EVIDENCE_DIR || "/tmp/pm-native-planning-ui-evidence");
if (evidenceDir === path.parse(evidenceDir).root) throw new Error("Refusing to use a filesystem root as the evidence directory.");
fs.mkdirSync(evidenceDir, {recursive: true});
const observations = [];
const consoleErrors = [];

function assert(condition, message) {
  if (!condition) throw new Error(`Assertion failed: ${message}`);
  observations.push(`PASS: ${message}`);
}

async function startServer() {
  return new Promise((resolve, reject) => {
    const child = spawn(process.env.PYTHON || "python", ["-m", "deterministic_scheduling_core.native_planning_ui", "--port", "0"], {
      cwd: process.cwd(), stdio: ["ignore", "pipe", "pipe"],
    });
    let buffer = "";
    const timer = setTimeout(() => reject(new Error(`Local UI did not start. Output: ${buffer}`)), 15000);
    child.stdout.on("data", (chunk) => {
      buffer += chunk.toString();
      const match = buffer.match(/http:\/\/127\.0\.0\.1:\d+/);
      if (match) { clearTimeout(timer); resolve({child, url: match[0]}); }
    });
    child.stderr.on("data", (chunk) => { buffer += chunk.toString(); });
    child.on("exit", (code) => { if (code && !buffer.match(/http:\/\//)) reject(new Error(`Local UI exited ${code}: ${buffer}`)); });
  });
}

async function waitReady(page) {
  await page.locator("#activity-list .activity-row").first().waitFor({state: "visible"});
}

async function clickActivity(page, id) {
  await page.locator(`.activity-row[data-activity-id="${id}"]`).click();
}

async function fillAndBlur(locator, value) {
  await locator.fill(value);
  await locator.press("Tab");
}

async function calculate(page) {
  await page.getByRole("button", {name: "Calculate plan / recovery"}).click();
  await page.locator("#proposal-state").filter({hasText: "current"}).waitFor();
}

async function approve(page) {
  await page.getByRole("button", {name: "Approve displayed proposal"}).click();
  await page.locator("#approved-state").filter({hasText: "current"}).waitFor();
}

async function saveDownload(page, destination) {
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", {name: "Save workspace"}).click();
  const download = await downloadPromise;
  await download.saveAs(destination);
}

async function reopen(page, filePath) {
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("#open-file").setInputFiles(filePath);
  await page.getByText(/Opened .* without recalculating/).waitFor();
}

async function exampleLifecycle(browser, url) {
  const context = await browser.newContext({viewport: {width: 1366, height: 900}, acceptDownloads: true});
  await context.tracing.start({screenshots: true, snapshots: true, sources: true});
  const page = await context.newPage();
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(`example: ${message.text()}`); });
  page.on("pageerror", (error) => consoleErrors.push(`example pageerror: ${error.message}`));
  await page.goto(url, {waitUntil: "networkidle"});
  await waitReady(page);
  assert(await page.getByRole("heading", {name: "Native planning trial"}).isVisible(), "application loads with meaningful planning content");
  assert(await page.locator("#activity-list .activity-row").count() === 8, "built-in example exposes eight activities");
  assert(await page.locator("body").getAttribute("aria-busy") === "false", "no loading overlay blocks the initial workspace");

  await calculate(page);
  const baseline = await page.evaluate(() => window.__pmTrialState.workspace.proposal);
  assert(baseline.selected_modes.A03 === "SPECIALIST", "example initially selects A03 SPECIALIST");
  assert(baseline.project_finish === 30, "example controlling finish is Day 1 15:00");
  assert(baseline.physical_status === "PROVEN_FEASIBLE", "example passes the independent physical checker");
  await page.locator('[data-plan-kind="proposal"]').click();
  const a03Timeline = page.locator(".timeline-row").filter({hasText: "A03"});
  assert(await a03Timeline.locator(".timeline-segment").count() === 2, "A03 shows separate productive segments across lunch suspension");
  await page.screenshot({path: path.join(evidenceDir, "01-example-baseline-1366x900.png"), fullPage: true});

  await approve(page);
  const approvedBefore = await page.evaluate(() => window.__pmTrialState.workspace.approved_plan.plan_hash);
  const hashBefore = await page.locator("#trusted-hash").getAttribute("title");
  await page.locator("#outage-resource").selectOption("M2");
  await fillAndBlur(page.locator("#outage-start"), "1@10:00");
  await fillAndBlur(page.locator("#outage-finish"), "1@17:00");
  await page.getByRole("button", {name: "Report unavailable"}).click();
  await page.locator("#reports-list").getByText("REPORTED").waitFor();
  const reported = await page.evaluate(() => window.__pmTrialState);
  assert(reported.trusted_input_hash === hashBefore, "unaccepted report leaves the trusted-input hash unchanged");
  assert(reported.workspace.approved_plan.plan_hash === approvedBefore, "unaccepted report leaves the approved plan unchanged");

  await page.getByRole("button", {name: "Accept selected report"}).click();
  await page.locator("#reports-list").getByText("ACCEPTED").waitFor();
  assert((await page.locator("#approved-state").innerText()).includes("stale"), "accepted availability makes the old approval visibly stale");
  await calculate(page);
  const recovery = await page.evaluate(() => window.__pmTrialState.workspace.proposal);
  assert(recovery.selected_modes.A03 === "NORMAL", "recovery changes A03 to NORMAL");
  assert(recovery.project_finish === 65, "recovery controlling finish is Day 2 08:30");
  const specialist = recovery.alternatives.find((item) => item.modes.A03 === "SPECIALIST");
  assert(specialist?.objective?.[0] === 71, "SPECIALIST alternative is evaluated at Day 2 11:30");
  assert(!recovery.approved_by, "recovery remains a proposal until a separate approval action");
  assert(await page.getByText("A03: SPECIALIST → NORMAL").isVisible(), "before/after comparison shows the computed A03 mode change");
  await page.screenshot({path: path.join(evidenceDir, "02-example-recovery-1366x900.png"), fullPage: true});

  await approve(page);
  const savedPath = path.join(evidenceDir, "example-approved-recovery.pm-workspace.json");
  await saveDownload(page, savedPath);
  await page.getByRole("button", {name: "New project"}).click();
  await page.getByText(/New eight-activity starter/).waitFor();
  await reopen(page, savedPath);
  const reopened = await page.evaluate(() => window.__pmTrialState.workspace);
  assert(reopened.approved_plan.selected_modes.A03 === "NORMAL", "downloaded recovery reopens with its approval intact");
  assert(reopened.plan_history.length === 1, "downloaded recovery reopens with prior approval history intact");
  assert(reopened.reports[0].status === "ACCEPTED", "downloaded recovery reopens with accepted availability intact");
  assert(reopened.proposal === null, "reopening does not silently calculate another proposal");
  await page.setViewportSize({width: 1920, height: 1080});
  await page.screenshot({path: path.join(evidenceDir, "03-example-reopened-1920x1080.png"), fullPage: true});
  await context.tracing.stop({path: path.join(evidenceDir, "example-trace.zip")});
  await context.close();
}

async function durationEdit(browser, url) {
  const context = await browser.newContext({viewport: {width: 1366, height: 900}});
  const page = await context.newPage();
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(`duration: ${message.text()}`); });
  page.on("pageerror", (error) => consoleErrors.push(`duration pageerror: ${error.message}`));
  await page.goto(url, {waitUntil: "networkidle"}); await waitReady(page);
  await calculate(page);
  await clickActivity(page, "A01");
  await fillAndBlur(page.locator('[data-mode-work="0"]'), "2");
  assert(await page.getByRole("button", {name: "Approve displayed proposal"}).isDisabled(), "editing after calculation immediately prevents stale approval");
  await page.getByRole("button", {name: "Apply input changes"}).click();
  await page.getByText(/Trusted project inputs applied/).waitFor();
  await calculate(page);
  const state = await page.evaluate(() => window.__pmTrialState);
  const entry = state.workspace.proposal.entries.find((item) => item.activity_id === "A01");
  assert(entry.periods.reduce((total, period) => total + period[1] - period[0], 0) === 4, "duration form sends A01's changed two productive hours to the Python scheduler");
  observations.push(`OBSERVED: duration edit proposal finish ${state.workspace.proposal.project_finish} (${state.workspace.proposal.project_finish === 30 ? "unchanged controlling finish" : "changed controlling finish"})`);
  await fillAndBlur(page.locator("#activity-name"), "Prepare workfront — edited after calculation");
  assert(await page.getByRole("button", {name: "Approve displayed proposal"}).isDisabled(), "a later name edit also blocks approval of the calculated proposal");
  await page.screenshot({path: path.join(evidenceDir, "04-duration-edit-stale-1366x900.png"), fullPage: true});
  await context.close();
}

async function setPredecessors(page, activityId, predecessorIds) {
  await clickActivity(page, activityId);
  for (const checkbox of await page.locator("[data-predecessor]").all()) {
    const id = await checkbox.getAttribute("data-predecessor");
    await checkbox.setChecked(predecessorIds.includes(id));
  }
}

async function addSlot(page, activityId, capability, eligibleIds) {
  await clickActivity(page, activityId);
  await page.getByRole("button", {name: "Add slot"}).click();
  await fillAndBlur(page.locator('[data-requirement-pools="0:0"]'), capability);
  for (const resourceId of ["M1", "M2", "N1", "R1", "R2"]) {
    await page.locator(`[data-eligible="0:0:${resourceId}"]`).setChecked(eligibleIds.includes(resourceId));
  }
}

async function independentCase(browser, url) {
  const context = await browser.newContext({viewport: {width: 1366, height: 900}, acceptDownloads: true});
  const page = await context.newPage();
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(`independent: ${message.text()}`); });
  page.on("pageerror", (error) => consoleErrors.push(`independent pageerror: ${error.message}`));
  await page.goto(url, {waitUntil: "networkidle"}); await waitReady(page);
  await page.getByRole("button", {name: "New project"}).click();
  await page.getByText(/New eight-activity starter/).waitFor();

  const names = {
    N01: "Independent site briefing",
    N02: "Parallel mechanical branch alpha with a deliberately long practitioner-facing name",
    N03: "Parallel mechanical branch beta",
    N04: "Independent inspection",
    N05: "Rigging support across lunch",
    N06: "Authorised recovery choice",
    N07: "Independent validation",
    N08: "Independent controlling handoff",
  };
  for (const [id, name] of Object.entries(names)) {
    await clickActivity(page, id);
    await fillAndBlur(page.locator("#activity-name"), name);
  }
  await setPredecessors(page, "N02", ["N01"]);
  await setPredecessors(page, "N03", ["N01"]);
  await setPredecessors(page, "N04", ["N02"]);
  await setPredecessors(page, "N05", ["N03"]);
  await setPredecessors(page, "N06", ["N04", "N05"]);
  await setPredecessors(page, "N07", ["N06"]);
  await setPredecessors(page, "N08", ["N07"]);

  for (const [id, hours] of [["N02", "3"], ["N03", "3"], ["N05", "2"]]) {
    await clickActivity(page, id); await fillAndBlur(page.locator('[data-mode-work="0"]'), hours);
  }
  await addSlot(page, "N02", "MECH", ["M1", "M2"]);
  await addSlot(page, "N03", "MECH", ["M1", "M2"]);
  await addSlot(page, "N04", "INSPECT", ["M2"]);
  await addSlot(page, "N05", "RIGGER", ["R1", "R2"]);
  await addSlot(page, "N07", "INSPECT", ["M2"]);
  await clickActivity(page, "N06");
  await page.getByRole("button", {name: "Add authorised mode"}).click();
  await fillAndBlur(page.locator('[data-mode-id="1"]'), "QUICK");
  await fillAndBlur(page.locator('[data-mode-work="1"]'), "0.5");

  const preregistered = {
    recorded_before_calculation: true,
    project: "new-native-project",
    activities: names,
    expected_properties: [
      "N02 and N03 compete concurrently for the same explicit M1/M2 alternatives after N01.",
      "A globally consistent capacity-one physical assignment should exist.",
      "N05's two productive hours should show the DAY lunch calendar gap.",
      "N06 QUICK should be preferred to FIXED under the unchanged controlling-finish-first objective.",
      "No controlling finish was assumed before calculation.",
    ],
  };
  fs.writeFileSync(path.join(evidenceDir, "independent-case-preregistered.json"), JSON.stringify(preregistered, null, 2) + "\n");
  await page.getByRole("button", {name: "Apply input changes"}).click();
  await page.getByText(/Trusted project inputs applied/).waitFor();
  await calculate(page);
  const proposal = await page.evaluate(() => window.__pmTrialState.workspace.proposal);
  assert(proposal.physical_status === "PROVEN_FEASIBLE", "independent browser-entered project is physically assignable");
  assert(proposal.selected_modes.N06 === "QUICK", "independent project selects the authorised QUICK mode");
  const n02 = proposal.entries.find((item) => item.activity_id === "N02");
  const n03 = proposal.entries.find((item) => item.activity_id === "N03");
  assert(new Set([n02.assignments[0][1], n03.assignments[0][1]]).size === 2, "parallel mechanical branches receive distinct physical resources");
  const n05 = proposal.entries.find((item) => item.activity_id === "N05");
  assert(n05.periods.length === 2, "independent rigging work displays two productive segments across lunch");
  observations.push(`OBSERVED: independent case finish ${proposal.project_finish}; N02 ${n02.assignments[0][1]}; N03 ${n03.assignments[0][1]}; N05 periods ${JSON.stringify(n05.periods)}`);
  await page.screenshot({path: path.join(evidenceDir, "05-independent-case-1366x900.png"), fullPage: true});

  const independentPath = path.join(evidenceDir, "independent-browser-entered.pm-workspace.json");
  await saveDownload(page, independentPath);
  await page.getByRole("button", {name: "Load example"}).click();
  await page.getByText(/Built-in eight-activity example loaded/).waitFor();
  await reopen(page, independentPath);
  const reopened = await page.evaluate(() => window.__pmTrialState.workspace);
  assert(reopened.project.activities[1].name === names.N02, "independent project reopens with browser-entered names");
  assert(reopened.proposal?.selected_modes.N06 === "QUICK", "independent project reopens with its pending calculated proposal, without recalculation");
  await page.setViewportSize({width: 1920, height: 1080});
  await page.screenshot({path: path.join(evidenceDir, "06-independent-reopened-1920x1080.png"), fullPage: true});
  await context.close();
}

async function failurePaths(browser, url) {
  const context = await browser.newContext({viewport: {width: 1366, height: 900}});
  const page = await context.newPage();
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(`failure: ${message.text()}`); });
  page.on("pageerror", (error) => consoleErrors.push(`failure pageerror: ${error.message}`));
  await page.goto(url, {waitUntil: "networkidle"}); await waitReady(page);
  await calculate(page); await approve(page);
  const approvedHash = await page.evaluate(() => window.__pmTrialState.workspace.approved_plan.plan_hash);

  await clickActivity(page, "A01");
  await page.locator('[data-predecessor="A08"]').check();
  await page.getByRole("button", {name: "Apply input changes"}).click();
  await page.locator("#message.error").filter({hasText: "precedence cycle"}).waitFor();
  assert(await page.evaluate((hash) => window.__pmTrialState.workspace.approved_plan.plan_hash === hash, approvedHash), "invalid cyclic input shows an actionable error and retains the prior approval");
  await page.locator('[data-predecessor="A08"]').uncheck();
  await page.getByRole("button", {name: "Apply input changes"}).click();
  await page.getByText(/Trusted project inputs applied/).waitFor();

  await page.locator("#outage-resource").selectOption("M2");
  await fillAndBlur(page.locator("#outage-start"), "1@00:00");
  await fillAndBlur(page.locator("#outage-finish"), "4@00:00");
  await fillAndBlur(page.locator("#outage-reason"), "Synthetic full-horizon infeasibility");
  await page.getByRole("button", {name: "Report unavailable"}).click();
  await page.getByRole("button", {name: "Accept selected report"}).click();
  await page.getByRole("button", {name: "Calculate plan / recovery"}).click();
  await page.locator("#message.error").filter({hasText: "no executable plan"}).waitFor();
  const infeasible = await page.evaluate(() => window.__pmTrialState);
  assert(infeasible.workspace.reports[0].status === "ACCEPTED", "infeasible recovery retains accepted availability information");
  assert(infeasible.workspace.approved_plan.plan_hash === approvedHash, "infeasible recovery retains the previous approved plan");
  assert(infeasible.approved_status === "STALE", "retained approval is clearly marked stale after accepted infeasibility");
  assert(infeasible.workspace.proposal === null, "infeasible recovery does not create or approve a proposal");
  await page.screenshot({path: path.join(evidenceDir, "07-infeasible-recovery-1366x900.png"), fullPage: true});
  await context.close();
}

const server = await startServer();
let browser;
try {
  browser = await chromium.launch({headless: true});
  await exampleLifecycle(browser, server.url);
  await durationEdit(browser, server.url);
  await independentCase(browser, server.url);
  await failurePaths(browser, server.url);
  assert(consoleErrors.length === 0, `browser console has no errors (${consoleErrors.length})`);
  const platformContext = await browser.newContext();
  const platformPage = await platformContext.newPage();
  const platform = await platformPage.evaluate(() => ({userAgent: navigator.userAgent, platform: navigator.platform}));
  await platformContext.close();
  observations.push(`PLATFORM: ${JSON.stringify(platform)}`);
  observations.push("VIEWPORTS: 1366x900 and 1920x1080");
  fs.writeFileSync(path.join(evidenceDir, "browser-smoke-output.txt"), observations.join("\n") + "\n");
  console.log(observations.join("\n"));
} catch (error) {
  fs.writeFileSync(path.join(evidenceDir, "browser-smoke-output.txt"), `${observations.join("\n")}\nFAIL: ${error.stack}\nConsole errors: ${consoleErrors.join("\n")}\n`);
  throw error;
} finally {
  if (browser) await browser.close();
  server.child.kill("SIGINT");
}
