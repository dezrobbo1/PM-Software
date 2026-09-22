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
  async function confirmAndStart(page) {
    page.once("dialog", (dialog) => dialog.accept());
    await start(page);
  }
  function isAction(request, action) {
    if (request.url().endsWith(`/api/${action}`)) return true;
    try { return request.postDataJSON()?.payload?.action === action; }
    catch (_error) { return false; }
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
  const boundaryPage = await fresh();
  try {
    assert(await participantA.getByRole("button", {name: "Start trial"}).isVisible(), "participant introduction leads to an explicit Start trial action");
    assert((await participantA.locator("#trial-identity").innerText()).includes("planner-update-recovery-v1"), "stable trial identity is visible");
    assert((await participantA.locator("#build-identity").innerText()).includes("Source/build"), "source/build identity is visible");
    for (const page of [participantA, participantB, boundaryPage]) {
      const metadata = (await state(page)).trial;
      assert(!("recovered_finish" in metadata) && !("expected_movements" in metadata), "participant-visible trial metadata excludes the recovery oracle");
    }
    assert(await boundaryPage.locator("#download-trial-result").isDisabled(), "initial example cannot be exported as practitioner-trial evidence");
    await start(participantA); await start(participantB);
    const pristineA = await state(participantA);
    const pristineB = await state(participantB);
    assert(JSON.stringify(pristineA.workspace) === JSON.stringify(pristineB.workspace), "two fresh contexts receive the same pristine approved workspace");
    assert(pristineA.workspace.approved_plan.project_finish === 72 && pristineA.workspace.proposal === null, "trial starts at the pinned approved Day 2 12:00 handoff with no proposal");
    assert(await participantA.locator("#download-trial-result").isEnabled(), "successful Start trial activates participant-result export");

    await participantA.locator('[data-question="understanding"]').fill("Participant A private answer that must not survive replacement.");
    await participantA.evaluate(() => {
      const originalFetch = window.fetch;
      window.fetch = (...args) => {
        const [url, options] = args;
        let action = String(url).split("/").pop();
        try { action = JSON.parse(options?.body || "{}").payload?.action || action; } catch (_error) { /* use URL action */ }
        if (action === "load-trial") return Promise.reject(new Error("Synthetic failed trial load"));
        return originalFetch(...args);
      };
      window.__restoreTrialFetch = () => { window.fetch = originalFetch; delete window.__restoreTrialFetch; };
    });
    participantA.once("dialog", (dialog) => dialog.accept());
    await participantA.locator("#start-trial").click();
    await participantA.getByText(/Synthetic failed trial load/).waitFor();
    assert(await participantA.locator('[data-question="understanding"]').inputValue() === "Participant A private answer that must not survive replacement.", "failed Start trial preserves existing questionnaire answers");
    assert(await participantA.locator("#download-trial-result").isEnabled(), "failed Start trial preserves the existing active trial");
    await participantA.evaluate(() => window.__restoreTrialFetch());

    await confirmAndStart(participantA);
    assert(await participantA.locator('[data-question="understanding"]').inputValue() === "", "successful fresh Start trial clears the previous participant questionnaire");
    await start(participantA);
    assert(await participantA.locator('[data-question="understanding"]').inputValue() === "", "fresh trial questionnaire reset also clears its dirty state");

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
    let releaseApproval;
    let approvalIntercepted;
    const approvalSeen = new Promise((resolve) => { approvalIntercepted = resolve; });
    const approvalRelease = new Promise((resolve) => { releaseApproval = resolve; });
    const delayApproval = async (route) => {
      if (!isAction(route.request(), "approve")) return route.continue();
      approvalIntercepted();
      await approvalRelease;
      return route.continue();
    };
    await participantA.route("**/api/**", delayApproval);
    await participantA.locator("#approve").click();
    await approvalSeen;
    assert(await participantA.locator("#download-trial-result").isDisabled(), "trial-result export is disabled while approval is pending");
    const staleDownload = participantA.waitForEvent("download", {timeout: 300}).then(() => true, () => false);
    await participantA.locator("#download-trial-result").evaluate((button) => button.click());
    assert(!(await staleDownload), "pending approval cannot emit a stale trial-result download");
    releaseApproval();
    await participantA.locator("#approved-state").filter({hasText: "current"}).waitFor();
    await participantA.unroute("**/api/**", delayApproval);
    assert(await participantA.locator("#download-trial-result").isEnabled(), "trial-result export re-enables after authoritative approval settles");
    const savedA = await save(participantA, "participant-a-approved-recovery.pm-workspace.json");

    const racePage = await fresh();
    await start(racePage);
    let releaseCalculation;
    let calculationIntercepted;
    let resetRequests = 0;
    const calculationSeen = new Promise((resolve) => { calculationIntercepted = resolve; });
    const calculationRelease = new Promise((resolve) => { releaseCalculation = resolve; });
    const delayCalculation = async (route) => {
      if (isAction(route.request(), "load-trial")) resetRequests += 1;
      if (!isAction(route.request(), "calculate")) return route.continue();
      calculationIntercepted();
      await calculationRelease;
      return route.continue();
    };
    await racePage.route("**/api/**", delayCalculation);
    await racePage.locator("#calculate").click();
    await calculationSeen;
    assert(await racePage.locator("#start-trial").isDisabled(), "Start trial is disabled while calculation is pending");
    await racePage.locator("#start-trial").evaluate((button) => button.click());
    await racePage.locator("#start-trial").evaluate((button) => { button.disabled = false; button.click(); });
    await racePage.waitForTimeout(100);
    assert(resetRequests === 0, "disabled and stale programmatic Start trial events issue no reset request");
    releaseCalculation();
    await racePage.locator("#proposal-state").filter({hasText: "current"}).waitFor();
    assert(await racePage.locator("#start-trial").isEnabled(), "Start trial re-enables after calculation settles");
    await confirmAndStart(racePage);
    assert(resetRequests === 1, "one deliberate reset request is issued after the prior action settles");
    const freshRaceState = await state(racePage);
    assert(freshRaceState.workspace.approved_plan.project_finish === 72 && freshRaceState.workspace.proposal === null, "settled reset loads the pristine approved trial");
    await racePage.waitForTimeout(300);
    const stableRaceState = await state(racePage);
    assert(stableRaceState.workspace.approved_plan.project_finish === 72 && stableRaceState.workspace.proposal === null, "no earlier response overwrites the fresh trial");
    assert(await racePage.locator("#download-trial-result").isEnabled(), "fresh reset retains active practitioner-trial identity");
    await racePage.unroute("**/api/**", delayCalculation);

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
    assert(await reopened.locator("#download-trial-result").isDisabled(), "reopened native workspace is not silently reclassified as active trial evidence");
    await reopened.locator("#history").screenshot({path: path.join(dir, "03-fresh-reopen-history.png")});

    await participantA.locator('[data-question="understanding"]').fill("Participant B independently updated accepted history and recovered only remaining work.");
    const resultDownload = participantA.waitForEvent("download");
    await participantA.locator("#download-trial-result").click();
    const resultPath = path.join(dir, "participant-a-trial-result.json");
    await (await resultDownload).saveAs(resultPath);
    const result = JSON.parse(fs.readFileSync(resultPath, "utf8"));
    assert(result.trial.id === "planner-update-recovery-v1" && result.workspace.approved_plan.project_finish === 77, "completion download contains questionnaire answers, trial identity and trusted result");
    assert(result.responses.understanding === "Participant B independently updated accepted history and recovered only remaining work." && !JSON.stringify(result).includes("Participant A private answer"), "reused-tab result contains only the new participant questionnaire responses");
    assert(!("recovered_finish" in result.trial), "downloaded participant result excludes the hidden recovery oracle");

    await start(boundaryPage);
    await boundaryPage.locator('[data-question="understanding"]').fill("Must clear on example replacement");
    boundaryPage.once("dialog", (dialog) => dialog.accept());
    await click(boundaryPage, "#load-example");
    assert(await boundaryPage.locator("#download-trial-result").isDisabled() && await boundaryPage.locator('[data-question="understanding"]').inputValue() === "", "Load example clears questionnaire state and deactivates trial export");
    await start(boundaryPage);
    await boundaryPage.locator('[data-question="understanding"]').fill("Must clear on new project");
    boundaryPage.once("dialog", (dialog) => dialog.accept());
    await click(boundaryPage, "#new-project");
    assert(await boundaryPage.locator("#download-trial-result").isDisabled() && await boundaryPage.locator('[data-question="understanding"]').inputValue() === "", "New project clears questionnaire state and deactivates trial export");
    boundaryPage.once("dialog", (dialog) => dialog.accept());
    await start(boundaryPage);
    await boundaryPage.locator('[data-question="understanding"]').fill("Must clear on arbitrary open");
    boundaryPage.once("dialog", (dialog) => dialog.accept());
    await boundaryPage.locator("#open-file").setInputFiles(savedA);
    await boundaryPage.getByText(/Opened .* without recalculating/).waitFor();
    assert(await boundaryPage.locator("#download-trial-result").isDisabled() && await boundaryPage.locator('[data-question="understanding"]').inputValue() === "", "Open workspace clears questionnaire state and does not infer active trial identity");
    assert(errors.length === 0, "trial-core browser contexts have no console or page errors");
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
}
