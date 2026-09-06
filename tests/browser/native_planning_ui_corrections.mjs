import fs from "node:fs";
import path from "node:path";
import http from "node:http";

export async function correctionRegressions(browser, url, evidenceDir, assert, observations) {
  const errors = [];
  async function session(label) {
    const context = await browser.newContext({viewport: {width: 1366, height: 900}, acceptDownloads: true});
    await context.tracing.start({screenshots: true, snapshots: true, sources: true});
    const watch = (page) => {
      page.on("pageerror", (error) => errors.push(`${label}: ${error.message}`));
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(`${label}: ${message.text()}`);
      });
    };
    context.on("page", watch);
    const page = await context.newPage();
    await page.goto(url);
    await page.locator("#activity-name").waitFor();
    return {context, page, close: async () => {
      await context.tracing.stop({path: path.join(evidenceDir, `${label}-trace.zip`)});
      await context.close();
    }};
  }
  const state = (page) => page.evaluate(() => window.__pmTrialState);
  const actual = async (context) => (await (await context.request.get(url + "/api/state")).json()).state;
  const apply = async (page) => {
    await page.locator("#apply-project").click();
    await page.locator("#message").filter({hasText: "Trusted project inputs applied"}).waitFor();
  };
  const calculate = async (page) => {
    await page.locator("#calculate").click();
    await page.locator("#proposal-state").filter({hasText: "current"}).waitFor();
  };
  const approve = async (page) => {
    await page.locator("#approve").click();
    await page.locator("#proposal-state").filter({hasText: "none"}).waitFor();
  };
  const save = async (page, name) => {
    const downloaded = page.waitForEvent("download");
    await page.locator("#save-workspace").click();
    await (await downloaded).saveAs(path.join(evidenceDir, name));
  };
  const upload = async (page, workspace, name) => {
    // Generated test fixtures only; normal trial saved files come from download.
    await page.locator("#open-file").setInputFiles({name, mimeType: "application/json", buffer: Buffer.from(JSON.stringify(workspace))});
  };

  {
    const {context, page: a, close} = await session("A-conflict");
    const b = await context.newPage();
    await b.goto(url); await b.locator("#activity-name").waitFor();
    assert((await state(a)).revision === (await state(b)).revision, "A: same-context tabs start on the same server revision");
    await a.locator("#activity-name").fill("Tab A retained edit"); await apply(a);
    await b.locator("#activity-name").fill("Tab B unsent draft");
    await b.locator("#apply-project").click();
    await b.locator("#message.error").filter({hasText: "another request"}).waitFor();
    assert(await b.locator("#activity-name").inputValue() === "Tab B unsent draft", "A: conflict preserves the unsent draft");
    assert(await b.locator("#apply-project").isDisabled() && await b.locator("#save-workspace").isDisabled(), "A: Apply and Save cannot retry a conflicted draft");
    await b.locator("#apply-project").evaluate((button) => button.click());
    await b.locator("#save-workspace").evaluate((button) => button.click());
    assert((await actual(context)).workspace.project.activities[0].name === "Tab A retained edit", "A: retry controls do not overwrite tab A's accepted input");
    b.once("dialog", (dialog) => dialog.dismiss());
    await b.locator("#reload-inputs").click();
    assert(await b.locator("#activity-name").inputValue() === "Tab B unsent draft", "A: declining reload keeps the retained draft");
    await b.screenshot({path: path.join(evidenceDir, "08-conflict-draft-1366x900.png"), fullPage: true});
    b.once("dialog", (dialog) => dialog.accept());
    await b.locator("#reload-inputs").click();
    await b.waitForFunction(() => document.querySelector("#activity-name").value === "Tab A retained edit");
    assert(await b.locator("#reload-inputs").isHidden(), "A: confirmed reload clears the visible conflict state");
    await b.locator("#activity-name").fill("Deliberate reconciled edit"); await apply(b);
    assert((await actual(context)).workspace.project.activities[0].name === "Deliberate reconciled edit", "A: deliberate new edit works after confirmed reload");
    await close();
  }

  {
    const {context, page, close} = await session("D-typing");
    await calculate(page);
    let delayCount = 0;
    await page.route("**/api/invalidate-proposal", async (route) => {
      const response = await route.fetch();
      delayCount += 1;
      await new Promise((resolve) => setTimeout(resolve, 700));
      await route.fulfill({response}); // Real Python response, delivery delayed only.
    });
    for (const [selector, suffix] of [["#activity-name", " typed-completely"], ['[data-resource-capabilities="0"]', ", EXTRA"]]) {
      if (selector.includes("capabilities")) await page.locator("summary").filter({hasText: "Resources and calendars"}).click();
      const input = page.locator(selector);
      const before = await input.inputValue();
      await input.focus(); await input.press("End");
      await input.pressSequentially(suffix, {delay: 30});
      assert(await input.inputValue() === before + suffix && await input.evaluate((element) => document.activeElement === element && element.selectionStart === element.value.length), `D: sequential keyboard edit preserves complete value, focus and caret in ${selector}`);
      assert(await page.locator("#calculate").isDisabled() && await page.locator("#approve").isDisabled(), "D: pending invalidation immediately blocks calculation and approval");
      await page.waitForFunction(() => !document.querySelector("#apply-project").disabled);
      assert(await input.inputValue() === before + suffix && await input.evaluate((element) => document.activeElement === element), "D: late invalidation preserves the newer draft and focus");
      await apply(page); await calculate(page);
    }
    assert(delayCount === 2, "D: both keyboard regressions exercised delayed real invalidation responses");
    await page.route("**/api/calculate", async (route) => {
      const response = await route.fetch();
      await new Promise((resolve) => setTimeout(resolve, 700));
      await route.fulfill({response});
    });
    await page.locator("#calculate").click();
    await page.locator('[data-activity-id="A02"]').click();
    assert(await page.locator("#activity-name").isDisabled(), "D: selecting another row cannot recreate an enabled editor during an actual calculation");
    await page.waitForFunction(() => document.body.getAttribute("aria-busy") === "false");
    await approve(page);
    assert((await state(page)).approved_status === "CURRENT", "D: apply, calculate and approve still work after typing");
    await page.screenshot({path: path.join(evidenceDir, "09-typing-approved-1366x900.png"), fullPage: true});
    await close();
  }

  {
    const {context, page, close} = await session("B-upload");
    page.on("dialog", (dialog) => dialog.accept());
    let solves = 0;
    page.on("request", (request) => { if (request.url().endsWith("/api/calculate")) solves += 1; });
    const saved = JSON.parse(fs.readFileSync(path.join(evidenceDir, "example-approved-recovery.pm-workspace.json")));
    await upload(page, saved, "recovery-with-history.json");
    await page.locator("#message").filter({hasText: "Opened recovery-with-history"}).waitFor();
    assert(JSON.stringify((await state(page)).workspace) === JSON.stringify(saved) && solves === 0, "B: valid saved recovery, actors and history open intact without calculation");
    const bad = structuredClone(saved); bad.approved_plan.project_finish += 1;
    const before = await actual(context);
    await upload(page, bad, "damaged-finish.json");
    await page.locator("#message.error").filter({hasText: "stored"}).waitFor();
    assert(JSON.stringify(await actual(context)) === JSON.stringify(before), "B: rejected changed finish preserves active workspace, revision and dirty state");
    const malformed = structuredClone(saved); malformed.plan_history[0].entries = null;
    await upload(page, malformed, "malformed-history.json");
    await page.locator("#message.error").filter({hasText: "plan_history"}).waitFor();
    assert(JSON.stringify(await actual(context)) === JSON.stringify(before), "B: malformed historical output is rejected before replacing the session");
    await page.screenshot({path: path.join(evidenceDir, "10-rejected-upload-1366x900.png"), fullPage: true});
    await save(page, "recovery-after-rejected-upload.pm-workspace.json");
    const stale = structuredClone(saved); stale.project.name += " — edited current input";
    await upload(page, stale, "valid-stale-approval.json");
    await page.locator("#message").filter({hasText: "Opened valid-stale"}).waitFor();
    assert((await state(page)).approved_status === "STALE" && solves === 0, "B: historical snapshot validates independently of stale classification without a solve");
    await close();
  }

  {
    const {page, close} = await session("C-milestone");
    await page.locator("#new-project").click();
    await page.locator("#message").filter({hasText: "New eight-activity"}).waitFor();
    await page.locator('[data-activity-id="N08"]').click();
    await page.locator("#activity-not-before").fill("1@15:00"); await page.locator("#activity-not-before").press("Tab");
    await apply(page); await calculate(page); await approve(page);
    await page.locator('[data-activity-id="N08"]').click();
    await page.locator("#activity-not-before").fill("2@08:30"); await page.locator("#activity-not-before").press("Tab");
    await apply(page); await calculate(page);
    const comparison = (await state(page)).comparison;
    assert(comparison.changed_periods.some((item) => item.activity_id === "N08" && item.old_start === 30 && item.new_start === 65) && !comparison.unchanged_activity_ids.includes("N08"), "C: zero-work handoff moving tick 30 to 65 is a timing change, not unchanged");
    assert(await page.locator("#comparison").getByText("N08: Day 1 15:00 → Day 2 08:30", {exact: true}).isVisible(), "C: visible comparison shows old and new milestone occurrence times");
    const entry = (await state(page)).workspace.proposal.entries.find((entry) => entry.activity_id === "N08");
    assert(entry.periods.length === 0 && entry.assignments.length === 0, "C: moved milestone has no invented productive periods or occupancy");
    await page.setViewportSize({width: 1920, height: 1080});
    await page.screenshot({path: path.join(evidenceDir, "11-milestone-comparison-1920x1080.png"), fullPage: true});
    await save(page, "milestone-recovery.pm-workspace.json");
    await close();
  }

  {
    const {page, close} = await session("E-optional");
    page.on("dialog", (dialog) => dialog.accept());
    const workspace = (await state(page)).workspace;
    delete workspace.project.activities[0].modes[0].requirements;
    workspace.project.resources.push({id: "crew:1", capabilities: ["MECH"], calendar_id: "DAY"});
    await upload(page, workspace, "optional-requirements.json");
    await page.locator("#message").filter({hasText: "Opened optional"}).waitFor();
    assert(await page.getByText(/No resource slot: this mode/).isVisible(), "E: native omitted requirements render as no resource slots");
    await calculate(page); await approve(page);
    const historical = (await state(page)).workspace.approved_plan;
    assert(!("requirements" in historical.source_snapshot.project.activities[0].modes[0]), "E: calculating and approving preserves omission in the hashed source snapshot");
    await page.getByRole("button", {name: "Add slot", exact: true}).click();
    const crew = page.locator('[data-resource-id="crew:1"]');
    await crew.check(); await crew.uncheck(); await crew.check();
    await apply(page);
    assert(JSON.stringify((await state(page)).workspace.approved_plan) === JSON.stringify(historical), "E: editable slot normalization leaves the prior hashed approval untouched");
    assert((await state(page)).workspace.project.activities[0].modes[0].requirements[0].eligible_resource_ids.includes("crew:1"), "earlier regression: eligibility editing retains the complete colon-containing resource ID");
    await page.locator("summary").filter({hasText: "Resources and calendars"}).click();
    await page.locator('[data-remove-resource="5"]').click();
    assert(await page.locator("#message.error").filter({hasText: "still eligible"}).isVisible(), "E: slot reference prevents silently removing a resource");
    await page.getByRole("button", {name: "Remove slot", exact: true}).click();
    await page.locator('[data-remove-resource="5"]').click();
    await apply(page); await calculate(page);
    await save(page, "optional-requirements-edited.pm-workspace.json");
    await page.locator("#new-project").click();
    await page.locator("#open-file").setInputFiles(path.join(evidenceDir, "optional-requirements-edited.pm-workspace.json"));
    await page.locator("#message").filter({hasText: "Opened optional-requirements-edited"}).waitFor();
    assert((await state(page)).proposal_status === "CURRENT", "E: omitted requirements workspace supports slot editing, calculation, save and reopen");
    await page.screenshot({path: path.join(evidenceDir, "12-optional-reopened-1366x900.png"), fullPage: true});
    await close();
  }

  {
    const {context, page, close} = await session("F-origin");
    const before = await actual(context);
    const foreign = http.createServer((_request, response) => {
      response.writeHead(200, {"Content-Type": "text/html"});
      response.end("<!doctype html><title>Disposable cross-origin test</title><p>Synthetic second-port request source</p>");
    });
    await new Promise((resolve) => foreign.listen(0, "127.0.0.1", resolve));
    try {
      await page.goto(`http://127.0.0.1:${foreign.address().port}`);
      const responsePromise = page.waitForResponse((response) => response.url() === url + "/api/new");
      await page.evaluate(async ({url, revision}) => {
        await fetch(url + "/api/new", {method: "POST", credentials: "include", mode: "no-cors",
          headers: {"Content-Type": "text/plain"}, body: JSON.stringify({revision})});
      }, {url, revision: before.revision});
      const response = await responsePromise;
      assert(response.status() === 403, "F: real second-port browser mutation reaches the target and receives HTTP 403");
      assert(response.request().headers()["origin"] !== url, "F: rejected request supplied the distinct second-port Origin");
      assert(JSON.stringify(await actual(context)) === JSON.stringify(before), "F: cross-origin attempt leaves the disposable target workspace and revision unchanged");
      await page.goto(url); await page.locator("#activity-name").waitFor();
      await page.locator("#new-project").click();
      await page.locator("#message").filter({hasText: "New eight-activity"}).waitFor();
      assert((await state(page)).workspace.project.id === "new-native-project", "F: legitimate same-origin mutation still succeeds");
    } finally {
      await new Promise((resolve) => foreign.close(resolve));
      await close();
    }
  }
  const expected = errors.filter((message) => /^(A-conflict:.*status of 409|B-upload:.*status of 400|F-origin:.*status of 403)/.test(message));
  const unexpected = errors.filter((message) => !expected.includes(message));
  observations.push(`OBSERVED: bounded corrections expected console diagnostics ${JSON.stringify(expected)}`);
  assert(unexpected.length === 0, `bounded corrections have no unexpected browser errors: ${JSON.stringify(unexpected)}`);
}
