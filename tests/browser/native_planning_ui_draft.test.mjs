// Focused state regressions execute the production script; real keyboard and
// cross-tab integration remain in the Playwright acceptance harness.
import {readFileSync} from "node:fs";
import vm from "node:vm";
import test from "node:test";
import assert from "node:assert/strict";

function editor() {
  const nodes = new Map();
  const node = (selector) => {
    if (!nodes.has(selector)) nodes.set(selector, {disabled: false, textContent: "", className: "", value: "", handlers: {}, dataset: {},
      addEventListener(event, handler) { this.handlers[event] = handler; }, setAttribute() {},
      classList: {contains: () => false}});
    return nodes.get(selector);
  };
  const document = {querySelector: node, querySelectorAll: (selector) => selector.startsWith(".project-panel") ? [node("active-editor")] : [], body: node("body")};
  const context = vm.createContext({structuredClone, console, URL, Blob,
    window: {confirm: () => false}, document,
    fetch: async () => { throw new Error("unexpected fetch"); }});
  vm.runInContext(readFileSync("src/deterministic_scheduling_core/native_planning_ui/app.js", "utf8").replace(/start\(\);\s*$/, ""), context);
  vm.runInContext(`render = () => {}; renderStatus = () => {}; renderWorkflow = () => {}; renderResults = () => {};
    renderActivityEditor = () => {}; renderResources = () => {}; renderCalendars = () => {}; renderHistory = () => {};
    current = {revision: 0, proposal_status: 'NONE', workspace: {project: {id: 'base'}, proposal: null, reports: []}};
    draft = {id: 'draft', activities: [], resources: []}; draftDirty = true;
    if (typeof draftRevision !== 'undefined') draftRevision = 0;`, context);
  return {context, document, node, run: (code) => vm.runInContext(code, context)};
}

for (const action of ["apply", "save"]) test(`A: ${action} cannot retry an old draft with a conflict revision`, async () => {
  const {context, node, run} = editor();
  const requests = [];
  context.fetch = async (_url, options) => {
    requests.push(JSON.parse(options.body));
    return {ok: false, status: 409, json: async () => ({error: "conflict", state: {
      revision: 1, workspace: {project: {id: "tab-A"}, proposal: null},
    }})};
  };
  await assert.rejects(run("applyDraft()"));
  assert.equal(run("draft.id"), "draft");
  if (action === "apply") await assert.rejects(run("applyDraft()"));
  else await node("#save-workspace").handlers.click();
  assert.ok(requests.slice(1).every((request) => request.revision === 0), "no request rebases the unsent draft to revision 1");
});

test("A: unrelated state adoption cannot rebase a dirty draft", async () => {
  const {context, run} = editor();
  const requests = [];
  context.fetch = async (_url, options) => { requests.push(JSON.parse(options.body)); throw new Error("stop"); };
  run("adoptState({revision: 2, workspace: {project: {id: 'other'}, proposal: null}}, false)");
  await assert.rejects(run("applyDraft()"));
  assert.ok(requests.every((request) => request.revision === 0));
  assert.equal(run("draft.id"), "draft");
});

test("D: pending invalidation does not disable the active input", async () => {
  const {context, node, run} = editor();
  let finish;
  context.fetch = () => new Promise((resolve) => { finish = resolve; });
  run("draftDirty = false; current.workspace.proposal = {}; markDraftDirty()");
  assert.equal(node("active-editor").disabled, false);
  assert.equal(node("#calculate").disabled, true);
  assert.equal(node("#approve").disabled, true);
  run("draft.id = 'all typed characters'");
  finish({ok: true, json: async () => ({state: {revision: 1, workspace: {project: {id: "base"}, proposal: null}}})});
  await run("pendingInvalidation");
  assert.equal(run("draft.id"), "all typed characters");
});

test("E: omitted requirements render and support slot add/remove-resource checks", () => {
  const {run} = editor();
  run(`draft = {calendars: [{id: 'DAY'}], resources: [{id: 'M1', capabilities: ['MECH']}],
    activities: [{id: 'A', modes: [{id: 'FIXED', processing_ticks: 2, calendar_id: 'DAY'}]}]};`);
  assert.match(run("modeCard(draft.activities[0], draft.activities[0].modes[0], 0)"), /No resource slot/);
  run("addRequirement(draft.activities[0], 0)");
  assert.equal(run("draft.activities[0].modes[0].requirements.length"), 1);
  run("removeResource(0)");
  assert.equal(run("draft.resources.length"), 1, "referenced resource is retained");
  run("delete draft.activities[0].modes[0].requirements; removeResource(0)");
  assert.equal(run("draft.resources.length"), 0);
});

test("G: invalid visible work edit immediately blocks approval", () => {
  const {context, document, node, run} = editor();
  const work = node("mode-work");
  work.dataset.modeWork = "0";
  work.value = "1.2";
  document.querySelectorAll = (selector) => {
    if (selector === "[data-mode-work]") return [work];
    if (selector.startsWith(".project-panel")) return [node("active-editor")];
    return [];
  };
  context.fetch = () => new Promise(() => {});
  run(`current.proposal_status = 'CURRENT'; current.workspace.proposal = {};
    displayedPlanKind = 'proposal'; draftDirty = false;
    draft = {activities: [{modes: [{processing_ticks: 2}]}], resources: []};
    bindModeEditors(draft.activities[0]); syncActions();`);
  assert.equal(node("#approve").disabled, false, "current proposal starts approvable");
  work.handlers.change({target: work});
  assert.equal(run("draftDirty"), true, "invalid visible edit marks the draft dirty");
  assert.equal(run("draft.activities[0].modes[0].processing_ticks"), 2, "invalid value is not adopted into the model");
  assert.equal(node("#approve").disabled, true, "old proposal is immediately non-approvable");
  assert.match(node("#message").textContent, /nonnegative multiple of 0\.5/);
});
