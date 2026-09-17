// Form-driven synthetic group profile; company data belongs only in private evidence.
import fs from "node:fs";
import path from "node:path";

export async function capacityTrial(browser, url, evidenceDir, assert, consoleErrors) {
  let context = await browser.newContext({viewport:{width:1366,height:900},acceptDownloads:true});
  await context.tracing.start({screenshots:true,snapshots:true});
  let page = await context.newPage();
  page.on("pageerror", e => consoleErrors.push(`capacity: ${e.message}`));
  page.on("dialog", d => d.accept());
  await page.goto(url); await page.locator("#activity-list .activity-row").first().waitFor();
  await page.locator("#new-project").click();
  await page.getByText(/New eight-activity starter/).waitFor();
  await page.getByText("Resources and calendars", {exact:true}).click();
  assert(await page.locator(".resource-row").count() === 0,"capacity: New has no invented workforce");
  for (const id of ["CREW","TOOLS"]) {
    await page.locator("#new-group-id").fill(id);
    await page.locator("#new-group-name").fill(`Interchangeable ${id}`);
    await page.locator("#new-group-capacity").fill("2");
    await page.locator("#new-group-declared").check();
    await page.locator("#add-group").click();
  }
  for (let i=1;i<=8;i++) {
    await page.locator(`[data-activity-id="N0${i}"]`).click();
    await page.locator("#activity-name").fill(i===8 ? "Capacity handoff" : `Synthetic concurrent operation ${i}`);
    for (const input of await page.locator("[data-predecessor]").all()) await input.setChecked(i===8);
    if (i<8) {
      await page.locator('[data-add-group-requirement="0"]').click();
      if (i===1) await page.locator('[data-add-group-requirement="0"]').click();
    }
  }
  await page.screenshot({path:path.join(evidenceDir,"capacity-input-1366.png"),fullPage:true});
  const apply = async()=> {await page.locator("#apply-project").click(); await page.getByText(/Trusted project inputs applied/).waitFor();};
  const calculate = async()=> {await page.locator("#calculate").click(); await page.locator("#proposal-state").filter({hasText:"current"}).waitFor();};
  const approve = async()=> {await page.locator("#approval-actor").fill("agent-test-only");await page.locator("#approve").click(); await page.locator("#approved-state").filter({hasText:"current"}).waitFor();};
  await apply(); await calculate();
  let state = await page.evaluate(()=>window.__pmTrialState);
  assert(state.workspace.proposal.project_finish===22,"capacity: two-unit synthetic plan finishes Day 1 11:00");
  assert(state.workspace.proposal.physical_status==="PROVEN_FEASIBLE","capacity: independent check passes");
  assert(await page.locator("#plan-table tr").filter({hasText:"CREW × 1 (group capacity)"}).count()===7
    && !(await page.locator("#plan-table").innerText()).includes("@group/"),"capacity: results display quantities without fake assignments");
  assert(await page.locator('#report-form button').isDisabled(),"capacity: no fictitious-person outage reporting");
  assert(!(await page.locator("#plan-summary").innerText()).includes("Rigging identity"),"capacity: no irrelevant rigging status");
  await approve();
  const originalApproval = (await page.evaluate(()=>window.__pmTrialState)).workspace.approved_plan;
  await page.locator('[data-group-capacity="0"]').fill("0");await page.locator('[data-group-capacity="0"]').press("Tab");
  await page.locator("#apply-project").click();await page.locator("#message.error").filter({hasText:"group capacity"}).waitFor();
  assert((await page.evaluate(()=>window.__pmTrialState)).workspace.approved_plan.plan_hash===originalApproval.plan_hash,"capacity: rejected input retains approval");
  await page.locator('[data-group-capacity="0"]').fill("1");await page.locator('[data-group-capacity="0"]').press("Tab");
  await apply();
  assert((await page.locator("#approved-state").innerText()).includes("stale"),"capacity: applied capacity edit leaves stale approval, not an outage report");
  await calculate(); state=await page.evaluate(()=>window.__pmTrialState);
  assert(state.workspace.proposal.project_finish===29 && state.workspace.reports.length===0,"capacity: one-unit recovery finishes Day 1 14:30 without fabricated reports");
  assert(state.workspace.approved_plan.plan_hash===originalApproval.plan_hash && state.workspace.proposal,"capacity: proposal remains separate from old approval");
  await page.screenshot({path:path.join(evidenceDir,"capacity-recovery-1366.png"),fullPage:true});
  await approve();
  const downloaded = page.waitForEvent("download");await page.locator("#save-workspace").click();
  const destination=path.join(evidenceDir,"capacity-browser-entered.pm-workspace.json");await (await downloaded).saveAs(destination);
  await context.tracing.stop({path:path.join(evidenceDir,"capacity-trace.zip")});await context.close();
  context=await browser.newContext({viewport:{width:390,height:844}});page=await context.newPage();
  page.on("pageerror", e=>consoleErrors.push(`capacity reopen: ${e.message}`));
  await page.goto(url);await page.locator("#activity-list .activity-row").first().waitFor();
  await page.locator("#open-file").setInputFiles(destination);await page.getByText(/Opened .*without recalculating/).waitFor();
  state=await page.evaluate(()=>window.__pmTrialState);
  assert(state.workspace.plan_history.length===1 && state.workspace.approved_plan.project_finish===29 && state.workspace.proposal===null,"capacity: fresh session reopens exact approval/history without solving");
  assert(await page.evaluate(()=>document.documentElement.scrollWidth===document.documentElement.clientWidth),"capacity: narrow viewport has no page-level horizontal overflow");
  await page.screenshot({path:path.join(evidenceDir,"capacity-reopened-390.png"),fullPage:true});
  fs.writeFileSync(path.join(evidenceDir,"capacity-observation.json"),JSON.stringify({groups:2,quantity_rows:8,manual_eligibility_memberships:0,viewports:["1366x900","390x844"],agent_test_approvals:true},null,2));
  await context.close();
}
