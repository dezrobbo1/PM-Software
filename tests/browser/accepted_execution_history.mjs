// Agent-operated local UI acceptance, never operational/practitioner approval.
import fs from "node:fs";
import path from "node:path";
import {execFileSync} from "node:child_process";

const tick = (t) => `${Math.floor(t / 48) + 1}@${String(Math.floor(t % 48 / 2)).padStart(2, "0")}:${t % 2 ? "30" : "00"}`;
const actor = "agent-test-only-not-operational";

export async function acceptedProgressTrial(browser, url, evidenceDir, assert) {
  const dir = path.join(evidenceDir, "accepted-progress");
  fs.mkdirSync(dir, {recursive: true});
  const errors = [];
  const sessions = [];
  async function fresh() {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, acceptDownloads: true});
    sessions.push(context);
    const page = await context.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(url);
    await page.locator(".activity-row").first().waitFor();
    return page;
  }
  async function state(page) { return page.evaluate(() => window.__pmTrialState); }
  async function click(page, selector) {
    await page.locator(selector).click();
    await page.waitForFunction(() => document.body.getAttribute("aria-busy") === "false");
    if (await page.locator("#message.error").count()) throw new Error(await page.locator("#message").innerText());
  }
  async function shot(page, name, selector = ".status-panel") {
    await page.locator(selector).screenshot({path: path.join(dir, name + ".png")});
  }
  async function save(page, name) {
    const downloading = page.waitForEvent("download");
    await click(page, "#save-workspace");
    const download = await downloading;
    const destination = path.join(dir, name + ".json");
    await download.saveAs(destination);
    return destination;
  }
  async function open(page, file) {
    page.once("dialog", (dialog) => dialog.accept());
    await page.locator("#open-file").setInputFiles(file);
    await page.getByText(/Opened .* without recalculating/).waitFor();
  }
  async function enable(page, point) {
    await page.locator("#status-point-input").fill(tick(point));
    await click(page, "#enable-status");
  }
  async function update(page, id, executionState, periods = [], remaining = null, mode = "FIXED", assignments = [], occurred = null, rejection = null) {
    await click(page, `[data-status-activity="${id}"]`);
    await page.locator("#execution-state").selectOption(executionState);
    if (executionState !== "NOT_STARTED") {
      await page.locator("#execution-mode").selectOption(mode);
      const point = (await state(page)).workspace.execution.status_point;
      await page.locator("#actual-start").fill(tick(periods[0]?.[0] ?? point));
      if (executionState === "COMPLETED") await page.locator("#actual-finish").fill(tick(periods.at(-1)?.[1] ?? point));
      await page.locator("#actual-periods").fill(periods.map(([s, f]) => `${tick(s)}-${tick(f)}`).join("; "));
      await page.locator("#remaining-hours").fill(remaining == null ? "" : String(remaining / 2));
      if (await page.locator("#actual-assignments").isVisible()) await page.locator("#actual-assignments").fill(assignments.map(([s, r]) => `${s}=${r}`).join(", "));
    }
    if (occurred !== null) await page.locator("#status-occurred").fill(tick(occurred));
    await page.locator("#status-actor").fill(actor);
    await page.locator("#status-reason").fill("Synthetic software validation only");
    const before = await state(page);
    await click(page, '#status-update-form button[type="submit"]');
    const reported = await state(page);
    assert(reported.trusted_input_hash === before.trusted_input_hash, `${id}: reported update leaves trusted state unchanged`);
    const record = reported.workspace.execution.updates.at(-1);
    await page.locator(`[data-status-acceptance-actor="${record.id}"]`).fill(actor);
    if (rejection) {
      await page.locator(`[data-accept-status="${record.id}"]`).click();
      await page.locator("#message.error").filter({hasText: rejection}).waitFor();
      assert(JSON.stringify((await state(page)).workspace) === JSON.stringify(reported.workspace), `${id}: rejected acceptance preserves the reported assertion and entire previous workspace`);
      return;
    }
    await click(page, `[data-accept-status="${record.id}"]`);
    assert((await state(page)).workspace.proposal === null, `${id}: acceptance invalidates proposal without approval`);
  }
  async function approve(page) {
    await page.locator("#approval-actor").fill(actor);
    await click(page, "#approve");
  }
  const named = await fresh();
  try {
    await click(named, "#calculate");
    await approve(named);
    const oldApproval = (await state(named)).workspace.approved_plan;
    await save(named, "legacy-v0-approved");
    await enable(named, 22);
    await shot(named, "01-explicit-status-entry");
    await update(named, "A01", "COMPLETED", [[14, 16]], 0);
    await update(named, "A02", "COMPLETED", [[16, 20]], 0, "FIXED", [["INSPECT", "M2"]]);
    await update(named, "A03", "IN_PROGRESS", [[20, 22]], 4, "SPECIALIST", [["MECH", "M1"], ["SPECIALIST", "M2"]]);
    await update(named, "A04", "NOT_STARTED");
    await update(named, "A05", "COMPLETED", [[16, 22]], 0, "FIXED", [["RIGGER", "R1"]]);
    await update(named, "A06", "COMPLETED", [[16, 22]], 0, "FIXED", [["RIGGER", "R2"]]);
    await update(named, "A07", "COMPLETED", [[16, 19]], 0, "FIXED", [["MECH", "M1"]]);
    await update(named, "A08", "NOT_STARTED");
    await named.locator("#outage-resource").selectOption("M2");
    await named.locator("#outage-start").fill("1@11:00");
    await named.locator("#outage-finish").fill("1@14:00");
    await click(named, '#report-form button[type="submit"]');
    await click(named, '[data-accept-report="E001"]');
    assert((await state(named)).approved_status === "STALE", "accepting status/outage leaves baseline stale");
    assert(JSON.stringify((await state(named)).workspace.approved_plan) === JSON.stringify(oldApproval), "status workflow preserves complete old approval");
    await shot(named, "02-accepted-history");
    await shot(named, "03-stale-approval", ".workflow-panel");
    await save(named, "named-statused-input");
    await click(named, "#calculate");
    const namedState = await state(named), plan = namedState.workspace.proposal;
    const byId = Object.fromEntries(plan.entries.map((e) => [e.activity_id, e]));
    assert(plan.project_finish === 63 && plan.selected_modes.A03 === "SPECIALIST", "named statused control keeps begun SPECIALIST and finish 63");
    assert(JSON.stringify(byId.A03.actual_periods) === "[[20,22]]", "named accepted actual remains [20,22)");
    assert(JSON.stringify(byId.A03.forecast_periods) === "[[28,32]]" && JSON.stringify(byId.A04.forecast_periods) === "[[32,34]]" && JSON.stringify(byId.A08.forecast_periods) === "[[62,63]]", "named exact future periods independently match the control");
    assert(["A01", "A02", "A05", "A06", "A07"].every((id) => namedState.comparison.unchanged_activity_ids.includes(id)), "completed-as-approved history is not falsely reported as changed");
    await shot(named, "11-completed-history-comparison", "#comparison");
    assert(await named.locator(".timeline-segment.actual").count() > 0 && await named.locator(".timeline-segment.forecast").count() > 0, "ACTUAL and FORECAST are distinct rendered bars");
    assert(await named.locator(".timeline-status-point").count() === 8, "status boundary is visible for all eight timeline rows");
    await shot(named, "04-named-actual-forecast", ".results-panel");
    await save(named, "named-calculated");
    await approve(named);
    await save(named, "named-approved");
    const retiredCompletion = await fresh();
    await open(retiredCompletion, path.join(dir, "named-approved.json"));
    await retiredCompletion.locator('.activity-row[data-activity-id="A03"]').click();
    const specialistIndex = (await state(retiredCompletion)).workspace.project.activities.find((a) => a.id === "A03").modes.findIndex((m) => m.id === "SPECIALIST");
    await retiredCompletion.locator(`[data-remove-mode="${specialistIndex}"]`).click();
    await click(retiredCompletion, "#apply-project");
    await update(retiredCompletion, "A03", "COMPLETED", [[20, 22]], 0, "SPECIALIST", [["MECH", "M1"], ["SPECIALIST", "M2"]]);
    await click(retiredCompletion, "#calculate");
    const completedEntry = (await state(retiredCompletion)).workspace.proposal.entries.find((e) => e.activity_id === "A03");
    assert(completedEntry.execution_state === "COMPLETED" && completedEntry.forecast_periods.length === 0, "in-progress activity can be confirmed completed using its retired historical mode");
    await approve(retiredCompletion);
    const completedFile = await save(retiredCompletion, "retired-in-progress-completion-TEST-ONLY");
    await shot(retiredCompletion, "14-retired-mode-completion", ".status-panel");
    const completedReopen = await fresh();
    await open(completedReopen, completedFile);
    assert(JSON.stringify((await state(completedReopen)).workspace) === JSON.stringify(JSON.parse(fs.readFileSync(completedFile, "utf8"))), "retired-mode completion preserves provenance and approval on fresh reopen");

    const incompleteContinuous = await fresh();
    await incompleteContinuous.locator('.activity-row[data-activity-id="A01"]').click();
    await incompleteContinuous.locator('[data-mode-continuity="0"]').selectOption("CONTINUOUS");
    await click(incompleteContinuous, "#apply-project");
    await enable(incompleteContinuous, 22);
    await update(incompleteContinuous, "A01", "IN_PROGRESS", [[14, 16]], 2, "FIXED", [], null, /continuous.*status/);
    await shot(incompleteContinuous, "15-incomplete-continuous-history-rejected", "#message");
    const reportedFile = await save(incompleteContinuous, "rejected-continuous-still-reported");
    const reportedReopen = await fresh();
    await open(reportedReopen, reportedFile);
    assert((await state(reportedReopen)).workspace.execution.updates[0].status === "REPORTED", "invalid reported history remains inspectable after reopen without becoming trusted");

    const emptyCompleted = await fresh();
    await enable(emptyCompleted, 22);
    await update(emptyCompleted, "A01", "COMPLETED", [], 0, "FIXED", [], null, /completed.*productive.*period/);
    await shot(emptyCompleted, "16-empty-completion-rejected", "#message");
    const duplicateNamed = await fresh();
    await enable(duplicateNamed, 22);
    await update(duplicateNamed, "A03", "IN_PROGRESS", [], 4, "SPECIALIST", [["MECH", "M2"], ["SPECIALIST", "M2"]], null, /distinct.*named/);
    await shot(duplicateNamed, "17-duplicate-named-assignment-rejected", "#message");

    const invalidImport = JSON.parse(fs.readFileSync(path.join(dir, "named-approved.json"), "utf8"));
    invalidImport.approved_plan = invalidImport.proposal = null; invalidImport.plan_history = [];
    Object.assign(invalidImport.execution.updates.find((u) => u.activity_id === "A01"), {actual_start: 0, actual_finish: 2, actual_periods: [[0, 2]]});
    const invalidFile = path.join(dir, "INVALID-import-calendar-history-EXPECTED-REJECTION.json");
    fs.writeFileSync(invalidFile, JSON.stringify(invalidImport, null, 2));
    const importTarget = await fresh();
    const beforeImport = JSON.stringify((await state(importTarget)).workspace);
    await importTarget.locator("#open-file").setInputFiles(invalidFile);
    await importTarget.locator("#message.error").filter({hasText: /Cannot open.*historical activity calendar/}).waitFor();
    assert(JSON.stringify((await state(importTarget)).workspace) === beforeImport, "invalid accepted history is rejected on open without replacing the active workspace");
    await shot(importTarget, "18-invalid-history-import-rejected", "#message");
    const trailingGap = await fresh();
    await open(trailingGap, path.join(dir, "named-approved.json"));
    await update(trailingGap, "A03", "IN_PROGRESS", [[20, 21]], 4, "SPECIALIST", [["MECH", "M1"], ["SPECIALIST", "M2"]], null, /suspension gap/);
    await shot(trailingGap, "19-suspendable-trailing-gap-rejected", "#message");
    await save(trailingGap, "suspendable-trailing-gap-REPORTED-ONLY");

    const reordered = await fresh();
    await open(reordered, path.join(dir, "named-approved.json"));
    const priorAssignmentState = await state(reordered);
    const priorAssertion = priorAssignmentState.workspace.execution.updates.find((u) => u.activity_id === "A03");
    await update(reordered, "A03", "IN_PROGRESS", [[20, 22]], 6, "SPECIALIST", [["SPECIALIST", "M2"], ["MECH", "M1"]]);
    const reorderedState = await state(reordered);
    assert(JSON.stringify(reorderedState.workspace.execution.updates.at(-1).execution_context) === JSON.stringify(priorAssertion.execution_context), "reordered assignment mapping preserves original historical context despite later accepted outage");
    assert(reorderedState.approved_status === "STALE" && reorderedState.workspace.execution.updates.some((u) => JSON.stringify(u) === JSON.stringify(priorAssertion)), "reordered correction retains provenance and stales previous approval");
    await click(reordered, "#calculate");
    await approve(reordered);
    await shot(reordered, "20-reordered-correction-provenance", "#history");
    const reorderedFile = await save(reordered, "reordered-assignment-correction-approved-TEST-ONLY");
    const reorderedReopen = await fresh();
    await open(reorderedReopen, reorderedFile);
    assert(JSON.stringify((await state(reorderedReopen)).workspace) === JSON.stringify(JSON.parse(fs.readFileSync(reorderedFile, "utf8"))), "reordered correction history, forecast and approval survive fresh reopen exactly");

    const unrelatedImport = JSON.parse(fs.readFileSync(path.join(dir, "named-approved.json"), "utf8"));
    unrelatedImport.approved_plan = unrelatedImport.proposal = null;
    unrelatedImport.plan_history = [];
    const unrelatedActual = unrelatedImport.execution.updates.find((u) => u.activity_id === "A03");
    unrelatedActual.actual_periods = [[20, 21]];
    unrelatedActual.execution_context.named_resources.push(unrelatedImport.project.resources.find((r) => r.id === "R1"));
    unrelatedActual.execution_context.accepted_outages = [{...unrelatedImport.reports[0], resource_id: "R1", start: 21, finish: 22}];
    const unrelatedFile = path.join(dir, "INVALID-unassigned-outage-EXPECTED-REJECTION.json");
    fs.writeFileSync(unrelatedFile, JSON.stringify(unrelatedImport, null, 2));
    const unrelatedTarget = await fresh();
    const beforeUnrelated = JSON.stringify((await state(unrelatedTarget)).workspace);
    await unrelatedTarget.locator("#open-file").setInputFiles(unrelatedFile);
    await unrelatedTarget.locator("#message.error").filter({hasText: /invalid historical accepted outage/}).waitFor();
    assert(JSON.stringify((await state(unrelatedTarget)).workspace) === beforeUnrelated, "unassigned resource outage cannot justify imported history or replace active workspace");
    await shot(unrelatedTarget, "21-unassigned-outage-import-rejected", "#message");
    const historyOnlyCorrection = await fresh();
    await open(historyOnlyCorrection, path.join(dir, "named-approved.json"));
    await update(historyOnlyCorrection, "A03", "IN_PROGRESS", [[21, 22]], 4, "SPECIALIST", [["MECH", "M1"], ["SPECIALIST", "M2"]], 20);
    await click(historyOnlyCorrection, "#calculate");
    const historyCorrectionState = await state(historyOnlyCorrection);
    assert(JSON.stringify(historyCorrectionState.workspace.proposal.entries.find((e) => e.activity_id === "A03").forecast_periods) === "[[28,32]]", "history-only correction leaves the future control unchanged");
    assert(historyCorrectionState.comparison.changed_periods.some((e) => e.activity_id === "A03") && !historyCorrectionState.comparison.unchanged_activity_ids.includes("A03"), "history-only correction is visible in recovery comparison");
    await shot(historyOnlyCorrection, "12-actual-only-correction-comparison", "#comparison");
    await save(historyOnlyCorrection, "actual-only-correction");

    const retired = await fresh();
    await open(retired, path.join(dir, "named-approved.json"));
    await retired.locator('.activity-row[data-activity-id="A01"]').click();
    await retired.locator('[data-mode-id="0"]').fill("REPLACEMENT");
    await click(retired, "#apply-project");
    await click(retired, "#calculate");
    assert((await state(retired)).workspace.proposal.selected_modes.A01 === "FIXED", "completed recovery uses captured historical mode after current mode retirement");
    await click(retired, '[data-status-activity="A01"]');
    assert(await retired.locator("#execution-mode").inputValue() === "FIXED" && (await retired.locator('#execution-mode option:checked').innerText()).includes("retired"), "status editor retains and labels retired historical mode");
    await shot(retired, "13-retired-historical-mode");
    await update(retired, "A01", "COMPLETED", [[14, 16]], 0);
    await click(retired, "#calculate");
    await approve(retired);
    const retiredFile = await save(retired, "completed-retired-mode-approved-TEST-ONLY");
    const retiredReopen = await fresh();
    await open(retiredReopen, retiredFile);
    assert(JSON.stringify((await state(retiredReopen)).workspace) === JSON.stringify(JSON.parse(fs.readFileSync(retiredFile, "utf8"))), "retired-mode correction and approval reopen without changing historical context");
    await update(named, "A03", "IN_PROGRESS", [[21, 22]], 6, "SPECIALIST", [["MECH", "M1"], ["SPECIALIST", "M2"]], 20);
    const corrected = await state(named);
    assert(corrected.approved_status === "STALE" && corrected.workspace.execution.updates.length === 9, "earlier-occurrence actual correction stales recovery and preserves all nine assertions");
    await save(named, "correction-stale");
    await click(named, "#calculate");
    const correctionPlan = (await state(named)).workspace.proposal;
    const correctedEntry = correctionPlan.entries.find((e) => e.activity_id === "A03");
    assert(JSON.stringify(correctedEntry.actual_periods) === "[[21,22]]" && correctedEntry.remaining_processing_ticks === 6, "superseding actual and estimate correction governs recalculation");
    await approve(named);
    await shot(named, "05-correction-provenance", "#history");
    const correctionFile = await save(named, "correction-approved");
    const reopened = await fresh();
    await open(reopened, correctionFile);
    assert(JSON.stringify((await state(reopened)).workspace) === JSON.stringify(JSON.parse(fs.readFileSync(correctionFile, "utf8"))), "fresh session reopens correction, full provenance and approvals exactly without calculation");
    await shot(reopened, "06-fresh-reopen", ".status-panel");
    const beforeFailure = (await state(reopened)).workspace;
    await reopened.locator("#outage-resource").selectOption("M1");
    await reopened.locator("#outage-start").fill("1@11:00");
    await reopened.locator("#outage-finish").fill("3@23:30");
    await click(reopened, '#report-form button[type="submit"]');
    await click(reopened, '[data-accept-report="E002"]');
    await reopened.locator("#calculate").click();
    await reopened.locator("#message.error").filter({hasText: /no executable future/}).waitFor();
    const failed = await state(reopened);
    assert(failed.workspace.proposal === null && failed.approved_status === "STALE", "infeasible recovery returns an error with prior approval stale");
    assert(JSON.stringify(failed.workspace.execution) === JSON.stringify(beforeFailure.execution) && JSON.stringify(failed.workspace.approved_plan) === JSON.stringify(beforeFailure.approved_plan), "infeasible recovery preserves accepted execution and full approved plan");
    assert(failed.workspace.reports.filter((r) => r.status === "ACCEPTED").length === 2, "two named-resource outages coexist after failure");
    await shot(reopened, "07-failed-recovery", ".workflow-panel");
    await shot(reopened, "07b-failed-recovery-error", "#message");
    await save(reopened, "infeasible-preserved");
    const legacy = await fresh();
    await open(legacy, path.join(dir, "legacy-v0-approved.json"));
    assert((await state(legacy)).workspace.schema === "pm-native-planning-workspace/0" && !(await state(legacy)).workspace.execution, "v0 approval opens unchanged without invented status");

    const pooled = await fresh();
    const source = process.env.PM_BOILER_WORKSPACE;
    const input = source ? JSON.parse(fs.readFileSync(source, "utf8")) : JSON.parse(execFileSync(process.env.PYTHON || "python", ["-c", "import json; from tests.test_accepted_execution_history import pooled_statused; w=pooled_statused(); del w['execution']; w['schema']='pm-native-planning-workspace/1'; print(json.dumps(w))"], {encoding: "utf8"}));
    assert(input.approved_plan === null, "pooled reference is unapproved before test-copy use");
    const referenceBytes = source ? fs.readFileSync(source) : null;
    const inputFile = path.join(dir, "pooled-v1-reference-copy.json");
    fs.writeFileSync(inputFile, JSON.stringify(input, null, 2));
    await open(pooled, inputFile);
    assert((await state(pooled)).workspace.schema === "pm-native-planning-workspace/1" && !(await state(pooled)).workspace.execution, "v1 grouped workspace opens without inferred progress or approval");
    const completed = {N02: [15, 19], N08: [15, 17], N09: [17, 23], N14: [23, 29]};
    const begun = {N03: [[29, 31], 6], N10: [[23, 31], 16]};
    fs.writeFileSync(path.join(dir, "pooled-overlay-before-calculation.json"), JSON.stringify({label: "SYNTHETIC SOFTWARE VALIDATION ONLY", status_point: 31, statuses: input.project.activities.map((a) => ({id: a.id, state: completed[a.id] ? "COMPLETED" : begun[a.id] ? "IN_PROGRESS" : "NOT_STARTED", periods: completed[a.id] ? [completed[a.id]] : begun[a.id] ? [begun[a.id][0]] : [], remaining: begun[a.id]?.[1] ?? (completed[a.id] ? 0 : null)}))}, null, 2));
    await enable(pooled, 31);
    for (const activity of input.project.activities) {
      const id = activity.id;
      if (completed[id]) await update(pooled, id, "COMPLETED", [completed[id]], 0);
      else if (begun[id]) await update(pooled, id, "IN_PROGRESS", [begun[id][0]], begun[id][1]);
      else await update(pooled, id, "NOT_STARTED");
    }
    await click(pooled, '[data-status-activity="N10"]');
    await shot(pooled, "08-pooled-history-and-eight-hours");
    await save(pooled, "pooled-statused-input");
    await click(pooled, "#calculate");
    let pooledPlan = (await state(pooled)).workspace.proposal;
    const n10 = pooledPlan.entries.find((e) => e.activity_id === "N10");
    assert(n10.actual_periods.reduce((n, [s, f]) => n + f - s, 0) === 8 && n10.forecast_periods.reduce((n, [s, f]) => n + f - s, 0) === 16, "pooled N10 retains four actual hours and schedules eight remaining hours");
    assert(JSON.stringify(n10.actual_group_demands) === '[["ETP",2]]' && JSON.stringify(n10.group_demands) === '[["ETP",2]]' && !JSON.stringify(pooledPlan).includes("@group/"), "pooled actual/future requirements stay ETP × 2 without fictitious worker identity");
    await shot(pooled, "09-pooled-actual-forecast", ".results-panel");
    await pooled.locator("#plan-table tr").filter({hasText: "N10"}).scrollIntoViewIfNeeded();
    await shot(pooled, "09b-n10-actual-forecast-and-group", ".results-panel");
    await save(pooled, "pooled-calculated");
    await approve(pooled);
    const poolFile = await save(pooled, "pooled-approved-TEST-ONLY");
    const poolReopen = await fresh();
    await open(poolReopen, poolFile);
    assert(JSON.stringify((await state(poolReopen)).workspace) === JSON.stringify(JSON.parse(fs.readFileSync(poolFile, "utf8"))), "fresh pooled reopen retains accepted history, forecast and approval exactly");
    await update(poolReopen, "N10", "IN_PROGRESS", [[23, 31]], 18);
    await click(poolReopen, "#calculate");
    const revised = (await state(poolReopen)).workspace.proposal.entries.find((e) => e.activity_id === "N10");
    assert(JSON.stringify(revised.actual_periods) === JSON.stringify(n10.actual_periods) && revised.remaining_processing_ticks === 18, "revising pooled estimate changes only future productive work");
    await save(poolReopen, "pooled-estimate-correction");
    await poolReopen.setViewportSize({width: 390, height: 844});
    assert(await poolReopen.evaluate(() => document.documentElement.scrollWidth === document.documentElement.clientWidth), "statused planner has no page overflow at 390px");
    await shot(poolReopen, "10-statused-narrow-layout");
    if (source) assert(referenceBytes.equals(fs.readFileSync(source)), "retained private Boiler reference bytes remain unchanged and unapproved");
    assert(errors.length === 0, `status browser workflows have no page errors (${errors.length})`);
    fs.writeFileSync(path.join(dir, "browser-version.json"), JSON.stringify({version: browser.version(), userAgent: await named.evaluate(() => navigator.userAgent), viewports: ["1440x1000", "390x844"], pooledSource: source ? "retained private Boiler workspace copy" : "public synthetic mathematical counterpart"}, null, 2));
  } finally {
    for (const context of sessions) await context.close();
  }
}
