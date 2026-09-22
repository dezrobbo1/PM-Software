// Agent-operated browser acceptance, not practitioner evidence or operational approval.
import fs from "node:fs";
import path from "node:path";

const actor = "agent-test-only-not-operational";

export async function plannerUpdateRecoveryTrial(browser, url, evidenceDir, assert) {
  const dir = path.join(evidenceDir, "planner-update-recovery-v1");
  fs.mkdirSync(dir, {recursive: true});
  const contexts = [];
  const errors = [];
  async function fresh() {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, acceptDownloads: true});
    contexts.push(context);
    const page = await context.newPage();
    page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(url, {waitUntil: "networkidle"});
    await page.locator(".activity-row").first().waitFor();
    return page;
  }
  async function state(page) { return page.evaluate(() => window.__pmTrialState); }
  async function click(page, selector) {
    await page.locator(selector).click();
    await page.waitForFunction(() => document.body.getAttribute("aria-busy") === "false");
    if (await page.locator("#message.error").count()) throw new Error(await page.locator("#message").innerText());
  }
  async function start(page) {
    await click(page, "#start-trial");
    await page.locator(".activity-row").filter({hasText: "A10"}).waitFor();
  }
  async function enable(page) {
    await page.locator("#status-point-input").fill("1@12:00");
    await click(page, "#enable-status");
  }
  async function acceptUpdate(page, id, executionState, periods = "", remainingHours = "") {
    await click(page, `[data-status-activity="${id}"]`);
    await page.locator("#execution-state").selectOption(executionState);
    if (executionState !== "NOT_STARTED") {
      const [start, finish] = periods.split("-");
      await page.locator("#actual-start").fill(start);
      if (executionState === "COMPLETED") await page.locator("#actual-finish").fill(finish);
      await page.locator("#actual-periods").fill(periods);
      await page.locator("#remaining-hours").fill(remainingHours);
    }
    await page.locator("#status-actor").fill(actor);
    await page.locator("#status-reason").fill("Synthetic practitioner-trial field briefing");
    await click(page, '#status-update-form button[type="submit"]');
    const update = (await state(page)).workspace.execution.updates.at(-1);
    await page.locator(`[data-status-acceptance-actor="${update.id}"]`).fill(actor);
    await click(page, `[data-accept-status="${update.id}"]`);
  }
  async function save(page, name) {
    const pending = page.waitForEvent("download");
    await click(page, "#save-workspace");
    const destination = path.join(dir, name);
    await (await pending).saveAs(destination);
    return destination;
  }

  const participantA = await fresh();
  const participantB = await fresh();
  try {
    assert(await participantA.getByRole("button", {name: "Start trial"}).isVisible(), "participant introduction leads to an explicit Start trial action");
    assert((await participantA.locator("#trial-identity").innerText()).includes("planner-update-recovery-v1"), "stable trial identity is visible");
    assert((await participantA.locator("#build-identity").innerText()).includes("Source/build"), "source/build identity is visible");
    await start(participantA); await start(participantB);
    const pristineA = await state(participantA);
    const pristineB = await state(participantB);
    assert(JSON.stringify(pristineA.workspace) === JSON.stringify(pristineB.workspace), "two fresh contexts receive the same pristine approved workspace");
    assert(pristineA.workspace.approved_plan.project_finish === 72 && pristineA.workspace.proposal === null, "trial starts at the pinned approved Day 2 12:00 handoff with no proposal");

    await enable(participantA);
    assert((await state(participantB)).workspace.schema === "pm-native-planning-workspace/1", "participant A status changes do not reach participant B");
    for (const [id, status, periods, remaining] of [
      ["A01", "COMPLETED", "1@07:00-1@08:00", "0"],
      ["A02", "COMPLETED", "1@08:00-1@10:00", "0"],
      ["A03", "COMPLETED", "1@10:00-1@11:00", "0"],
      ["A04", "IN_PROGRESS", "1@11:00-1@12:00", "7"],
      ["A05", "COMPLETED", "1@10:00-1@12:00", "0"],
      ["A06", "NOT_STARTED", "", ""], ["A07", "NOT_STARTED", "", ""],
      ["A08", "NOT_STARTED", "", ""], ["A09", "NOT_STARTED", "", ""],
      ["A10", "NOT_STARTED", "", ""],
    ]) await acceptUpdate(participantA, id, status, periods, remaining);
    let stateA = await state(participantA);
    assert(stateA.approved_status === "STALE" && stateA.workspace.proposal === null, "accepted history stales but does not replace or recalculate the approval");
    await participantA.locator(".status-panel").screenshot({path: path.join(dir, "01-accepted-field-update.png")});

    await click(participantA, "#calculate");
    stateA = await state(participantA);
    assert(stateA.workspace.proposal.project_finish === 77, "deterministic recovery reaches Day 2 14:30");
    const a04 = stateA.workspace.proposal.entries.find((entry) => entry.activity_id === "A04");
    assert(JSON.stringify(a04.actual_periods) === JSON.stringify([[22, 24]]) && JSON.stringify(a04.forecast_periods) === JSON.stringify([[25, 34], [62, 67]]), "actual A04 history remains fixed and seven forecast hours start after status");
    assert(stateA.comparison.unchanged_activity_ids.includes("A06"), "comparison identifies unaffected future work");
    assert((await participantA.locator("#comparison").innerText()).includes("A04"), "material movement is visible in the comparison");
    await participantA.locator(".workflow-panel").screenshot({path: path.join(dir, "02-recovery-comparison.png")});
    await participantA.locator("#approval-actor").fill(actor);
    await click(participantA, "#approve");
    const savedA = await save(participantA, "participant-a-approved-recovery.pm-workspace.json");

    await click(participantB, "#calculate");
    const stateB = await state(participantB);
    assert(stateB.workspace.proposal.project_finish === 72 && (await state(participantA)).workspace.approved_plan.project_finish === 77, "participant B performs a different calculation without receiving participant A's recovery");
    await save(participantB, "participant-b-independent-plan.pm-workspace.json");

    const reopened = await fresh();
    await reopened.locator("#open-file").setInputFiles(savedA);
    await reopened.getByText(/Opened .* without recalculating/).waitFor();
    const reopenedState = await state(reopened);
    assert(reopenedState.workspace.approved_plan.project_finish === 77 && reopenedState.workspace.proposal === null, "fresh context reopens the recovered approval without silent calculation");
    assert(reopenedState.workspace.execution.updates.length === 10, "fresh reopen preserves all accepted history and provenance");
    await reopened.locator("#history").screenshot({path: path.join(dir, "03-fresh-reopen-history.png")});

    await participantA.locator('[data-question="understanding"]').fill("Update accepted history and recover only the remaining plan.");
    const resultDownload = participantA.waitForEvent("download");
    await participantA.locator("#download-trial-result").click();
    const resultPath = path.join(dir, "participant-a-trial-result.json");
    await (await resultDownload).saveAs(resultPath);
    const result = JSON.parse(fs.readFileSync(resultPath, "utf8"));
    assert(result.trial.id === "planner-update-recovery-v1" && result.workspace.approved_plan.project_finish === 77, "completion download contains questionnaire answers, trial identity and trusted result");
    assert(errors.length === 0, "trial-core browser contexts have no console or page errors");
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
}
