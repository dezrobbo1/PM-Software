"use strict";

let current = null;
let draft = null;
let selectedActivityId = null;
let selectedStatusActivityId = null;
let displayedPlanKind = "proposal";
let draftDirty = false;
let draftRevision = null;
let draftConflict = false;
let busy = false;
let invalidating = false;
let pendingInvalidation = Promise.resolve();
let questionnaireDirty = false;
let activeTrial = false;
const browserLocation = window.location || {protocol: "", search: ""};
const hostedTransport = browserLocation.protocol === "https:"
  || /(?:^|[?&])transport=stateless(?:&|$)/.test(browserLocation.search);

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const clone = (value) => structuredClone(value);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
})[character]);

function tickLabel(tick) {
  const day = Math.floor(tick / 48) + 1;
  const withinDay = tick % 48;
  const hour = Math.floor(withinDay / 2);
  const minute = withinDay % 2 ? "30" : "00";
  return `Day ${day} ${String(hour).padStart(2, "0")}:${minute}`;
}

function compactTick(tick) {
  return tickLabel(tick).replace("Day ", "D");
}

function inputTick(tick) {
  const day = Math.floor(tick / 48) + 1;
  const withinDay = tick % 48;
  const hour = Math.floor(withinDay / 2);
  const minute = withinDay % 2 ? "30" : "00";
  return `${day}@${String(hour).padStart(2, "0")}:${minute}`;
}

function parseRelativeTime(value) {
  const match = /^\s*(\d+)@(\d{1,2}):(00|30)\s*$/.exec(value);
  if (!match) throw new Error("Use relative time such as 1@07:00 or 2@08:30.");
  const day = Number(match[1]);
  const hour = Number(match[2]);
  if (day < 1 || hour > 23) throw new Error("Relative day must be at least 1 and hour must be 00–23.");
  return (day - 1) * 48 + hour * 2 + (match[3] === "30" ? 1 : 0);
}

function optionalRelativeTime(value) {
  return value.trim() ? parseRelativeTime(value) : null;
}

function parseProductivePeriods(value) {
  if (!value.trim()) return [];
  return value.split(";").map((part) => {
    const pieces = part.trim().split(/\s*[-–]\s*/);
    if (pieces.length !== 2) throw new Error("Productive periods use start-finish pairs separated by semicolons.");
    const start = parseRelativeTime(pieces[0]);
    const finish = parseRelativeTime(pieces[1]);
    if (start >= finish) throw new Error("Each productive period must finish after it starts.");
    return [start, finish];
  });
}

function parseNamedAssignments(value) {
  if (!value.trim()) return [];
  return value.split(",").map((part) => {
    const [slot, resource, ...extra] = part.split("=").map((item) => item.trim());
    if (!slot || !resource || extra.length) throw new Error("Named assignments use SLOT=RESOURCE pairs separated by commas.");
    return [slot, resource];
  });
}

function periodsInput(periods) {
  return (periods || []).map(([start, finish]) => `${inputTick(start)}-${inputTick(finish)}`).join("; ");
}

function parseRemainingHours(value) {
  const ticks = Number(value) * 2;
  if (!value.trim() || !Number.isInteger(ticks) || ticks < 0) {
    throw new Error("Enter an explicit remaining-work estimate in multiples of 0.5 hours; zero does not confirm completion.");
  }
  return ticks;
}

function currentExecutionUpdates(workspace) {
  if (workspace.schema !== "pm-native-planning-workspace/2") return {};
  const accepted = workspace.execution.updates.filter((update) => update.status === "ACCEPTED");
  const superseded = new Set(accepted.map((update) => update.supersedes_update_id).filter(Boolean));
  return Object.fromEntries(accepted.filter((update) => !superseded.has(update.id)).map((update) => [update.activity_id, update]));
}

function clockLabel(tick) {
  const hour = Math.floor(tick / 2);
  const minute = tick % 2 ? "30" : "00";
  return `${String(hour).padStart(2, "0")}:${minute}`;
}

function parseClock(value, allowEndOfDay = false) {
  const match = /^\s*(\d{1,2}):(00|30)\s*$/.exec(value);
  if (!match) throw new Error(`Invalid 30-minute clock value: ${value}`);
  const hour = Number(match[1]);
  if (hour > 23 && !(allowEndOfDay && hour === 24 && match[2] === "00")) {
    throw new Error(`Clock value must be between 00:00 and ${allowEndOfDay ? "24:00" : "23:30"}.`);
  }
  return hour * 2 + (match[2] === "30" ? 1 : 0);
}

function windowsLabel(windows) {
  return windows.map(([start, finish]) => `${clockLabel(start)}-${finish === 48 ? "24:00" : clockLabel(finish)}`).join(", ");
}

function parseWindows(value) {
  const windows = value.split(",").map((part) => {
    const pieces = part.trim().split("-");
    if (pieces.length !== 2) throw new Error("Calendar windows use HH:MM-HH:MM, separated by commas.");
    const start = parseClock(pieces[0]);
    const finish = parseClock(pieces[1], true);
    if (start >= finish) throw new Error("Each calendar window must finish after it starts.");
    return [start, finish];
  });
  if (!windows.length) throw new Error("A calendar needs at least one working window.");
  return windows;
}

function showMessage(message, kind = "success") {
  const target = $("#message");
  target.textContent = message;
  target.className = `message visible ${kind}`;
}

function clearMessage() {
  const target = $("#message");
  target.textContent = "";
  target.className = "message";
}

function workspaceDownloadJson(data) {
  return data.workspace_json ?? `${JSON.stringify(data.state.workspace, null, 2)}\n`;
}

async function request(path, payload = {}) {
  const expectedRevision = payload.revision ?? current.revision;
  let requestPath = path;
  let body = {revision: current.revision, ...payload};
  if (hostedTransport) {
    const actionPayload = {...payload, action: path.replace(/^\/api\//, "")};
    delete actionPayload.revision;
    requestPath = "/api/planning";
    body = {
      expected_revision: expectedRevision,
      state: {
        revision: current.revision,
        dirty: current.dirty,
        source: current.source,
        workspace: current.workspace,
      },
      payload: actionPayload,
    };
  }
  const response = await fetch(requestPath, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  let data;
  try {
    data = await response.json();
  } catch (_error) {
    throw new Error(`The planning service returned HTTP ${response.status} without a JSON response.`);
  }
  if (data.runtime) {
    window.__pmTrialRuntime = [...(window.__pmTrialRuntime || []), {path, ...data.runtime}];
  }
  if (!response.ok) {
    if (response.status === 409) draftConflict = true;
    else if (data.state && JSON.stringify(data.state.workspace.project) === JSON.stringify(current.workspace.project)) draftRevision = data.state.revision;
    if (data.state) adoptState(data.state, false);
    throw new Error(data.error || `Request failed with HTTP ${response.status}.`);
  }
  return data;
}

function adoptState(state, replaceDraft) {
  current = state;
  if (replaceDraft || !draft) {
    draft = clone(state.workspace.project);
    draftDirty = false;
    draftRevision = state.revision;
    draftConflict = false;
    selectedActivityId = draft.activities[0]?.id ?? null;
  } else if (draftRevision !== state.revision) {
    draftConflict = true;
  }
  if (state.workspace.proposal) displayedPlanKind = "proposal";
  else if (state.workspace.approved_plan) displayedPlanKind = "approved";
  window.__pmTrialState = clone(state);
  if (replaceDraft || !draft) render();
  else {
    renderStatus(); renderStatusWorkflow(); renderWorkflow(); renderResults(); renderHistory(); syncActions();
  }
}

function setBusy(value) {
  busy = value;
  document.body.setAttribute("aria-busy", String(value));
  syncActions();
}

async function perform(path, payload, message, replaceDraft = false) {
  await pendingInvalidation;
  if (draftConflict) {
    const error = new Error("Draft conflict: reload current inputs explicitly before applying or saving. Your draft is retained.");
    showMessage(error.message, "error");
    throw error;
  }
  clearMessage();
  setBusy(true);
  try {
    const data = await request(path, payload);
    // This response belongs to our own serialized mutation, not an unrelated
    // refresh. Project inputs remain the draft's base unless Apply replaces it.
    draftRevision = data.state.revision;
    adoptState(data.state, replaceDraft);
    if (message) showMessage(message);
    return data;
  } catch (error) {
    showMessage(error.message, "error");
    throw error;
  } finally {
    setBusy(false);
  }
}

function discardNeedsConfirmation() {
  if (!draftDirty && !current?.dirty && !questionnaireDirty) return true;
  return window.confirm("This workspace or questionnaire has unsaved or unapplied changes. Discard them and continue?");
}

function finishWorkspaceReplacement(trialIsActive) {
  $$('[data-question]').forEach((field) => { field.value = ""; });
  questionnaireDirty = false;
  activeTrial = trialIsActive;
  document.body.classList.toggle("trial-started", trialIsActive);
  syncActions();
}

function markDraftDirty() {
  if (!draftDirty) {
    draftDirty = true;
    if (current.workspace.proposal && !draftConflict) {
      invalidating = true;
      const baseRevision = draftRevision;
      pendingInvalidation = (async () => {
        try {
          const data = await request("/api/invalidate-proposal", {revision: baseRevision});
          current = data.state;
          draftRevision = data.state.revision;
          window.__pmTrialState = clone(current);
          showMessage("The prior proposal was invalidated. Apply the edited inputs, then calculate again.");
          renderStatus();
          renderWorkflow();
          renderResults();
        } catch (error) {
          showMessage(error.message, "error");
        } finally {
          invalidating = false;
          syncActions();
        }
      })();
    }
  }
  renderStatus();
  syncActions();
}

function requireIdentifier(value, label) {
  const normalized = value.trim();
  if (!/^[A-Za-z][A-Za-z0-9_-]{0,19}$/.test(normalized)) {
    throw new Error(`${label} must start with a letter and use at most 20 letters, digits, underscores or hyphens.`);
  }
  return normalized;
}

function render() {
  if (!current || !draft) return;
  if (!draft.activities.some((activity) => activity.id === selectedActivityId)) {
    selectedActivityId = draft.activities[0]?.id ?? null;
  }
  renderStatus();
  renderProjectSettings();
  renderActivityList();
  renderActivityEditor();
  renderResources();
  renderCalendars();
  renderStatusWorkflow();
  renderWorkflow();
  renderResults();
  renderHistory();
  syncActions();
}

function renderStatus() {
  $("#source-label").textContent = current.source;
  $("#save-state").textContent = current.dirty || draftDirty ? "Unsaved changes" : "Saved / unchanged";
  $("#save-state").className = `badge ${current.dirty || draftDirty ? "unsaved" : "current"}`;
  $("#approved-state").textContent = `Approved: ${current.approved_status.toLowerCase()}`;
  $("#approved-state").className = `badge ${current.approved_status.toLowerCase()}`;
  $("#proposal-state").textContent = `Proposal: ${current.proposal_status.toLowerCase()}`;
  $("#proposal-state").className = `badge ${current.proposal_status.toLowerCase()}`;
  $("#trusted-hash").textContent = `Trusted input ${current.trusted_input_hash.slice(0, 12)}…`;
  $("#trusted-hash").title = current.trusted_input_hash;
  $("#draft-state").textContent = draftConflict ? "Draft conflict — draft retained; reload current inputs to continue" : draftDirty ? "Unapplied edits — calculation and approval paused" : "Inputs applied";
  $("#reload-inputs").hidden = !draftConflict;
  if (current.trial) {
    $("#trial-identity").textContent = `${current.trial.name} · ${current.trial.id}`;
    $("#build-identity").textContent = `Source/build ${current.trial.build_sha}`;
  }
}

function renderProjectSettings() {
  $("#project-settings").innerHTML = `
    <label>Project ID<input id="project-id" value="${escapeHtml(draft.id)}" maxlength="60"></label>
    <label>Project name<input id="project-name" value="${escapeHtml(draft.name)}" maxlength="100"></label>
    <label>Horizon (days)<input id="project-horizon" type="number" min="1" max="14" step="1" value="${draft.horizon_ticks / 48}"></label>
    <label>Controlling completion<select id="objective-activity">${draft.activities.map((activity) => `<option value="${escapeHtml(activity.id)}" ${activity.id === draft.objective_activity_id ? "selected" : ""}>${escapeHtml(activity.id)} · ${escapeHtml(activity.name)}</option>`).join("")}</select></label>
    <label class="checkbox-label" ${draft.resources.some(r => r.capabilities.includes("RIGGER")) ? "" : "hidden"}><input id="pool-riggers" type="checkbox" ${draft.pool_riggers ? "checked" : ""}> Defer interchangeable RIGGER identity (legacy)</label>`;
  $("#project-id").addEventListener("input", (event) => { draft.id = event.target.value; markDraftDirty(); });
  $("#project-name").addEventListener("input", (event) => { draft.name = event.target.value; markDraftDirty(); });
  $("#project-horizon").addEventListener("change", (event) => {
    const days = Number(event.target.value);
    if (!Number.isInteger(days) || days < 1 || days > 14) {
      markDraftDirty();
      return showMessage("Horizon must be 1–14 whole relative days.", "error");
    }
    draft.horizon_ticks = days * 48; markDraftDirty();
  });
  $("#objective-activity").addEventListener("change", (event) => { draft.objective_activity_id = event.target.value; markDraftDirty(); });
  $("#pool-riggers").addEventListener("change", (event) => { draft.pool_riggers = event.target.checked; markDraftDirty(); });
}

function renderActivityList() {
  $("#activity-count").textContent = `${draft.activities.length} / 15`;
  $("#activity-list").innerHTML = draft.activities.map((activity) => `
    <tr class="activity-row ${activity.id === selectedActivityId ? "selected" : ""}" data-activity-id="${escapeHtml(activity.id)}" tabindex="0">
      <td><strong>${escapeHtml(activity.id)}</strong></td>
      <td>${escapeHtml(activity.name)}</td>
      <td>${escapeHtml(activity.predecessors?.join(", ") || "—")}</td>
      <td>${activity.modes.length}</td>
    </tr>`).join("");
  $$(".activity-row").forEach((row) => {
    const select = () => {
      if (busy) return; // Rebuilding the editor must not bypass calculation locking.
      selectedActivityId = row.dataset.activityId; renderActivityList(); renderActivityEditor();
    };
    row.addEventListener("click", select);
    row.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } });
  });
}

function renderActivityEditor() {
  const activity = draft.activities.find((item) => item.id === selectedActivityId);
  if (!activity) {
    $("#activity-editor").innerHTML = '<p class="empty">Select an activity.</p>';
    return;
  }
  $("#activity-editor").innerHTML = `
    <div class="subheading-row"><h3>Selected activity</h3><span>IDs remain stable after creation</span></div>
    <div class="editor-fields">
      <label>Activity ID<input value="${escapeHtml(activity.id)}" readonly></label>
      <label>Name<input id="activity-name" value="${escapeHtml(activity.name)}" maxlength="100"></label>
      <label>Not before<input id="activity-not-before" value="${escapeHtml(inputTick(activity.not_before || 0))}" aria-describedby="relative-time-help"></label>
    </div>
    <p id="relative-time-help" class="guidance">Not-before uses relative day@time, for example 1@07:00. Values move in 30-minute increments.</p>
    <div class="predecessor-box" aria-label="Finish-to-start predecessors">
      ${draft.activities.filter((other) => other.id !== activity.id).map((other) => `<label class="checkbox-label"><input type="checkbox" data-predecessor="${escapeHtml(other.id)}" ${(activity.predecessors || []).includes(other.id) ? "checked" : ""}> ${escapeHtml(other.id)} · ${escapeHtml(other.name)}</label>`).join("")}
    </div>
    <div class="mode-list">${activity.modes.map((mode, modeIndex) => modeCard(activity, mode, modeIndex)).join("")}</div>
    <div class="editor-actions"><button id="add-mode" type="button">Add authorised mode</button>&nbsp;<button id="delete-activity" class="danger" type="button">Remove activity</button></div>`;

  $("#activity-name").addEventListener("input", (event) => { activity.name = event.target.value; markDraftDirty(); renderActivityList(); });
  $("#activity-not-before").addEventListener("change", (event) => {
    try { activity.not_before = parseRelativeTime(event.target.value); markDraftDirty(); }
    catch (error) { markDraftDirty(); showMessage(error.message, "error"); }
  });
  $$('[data-predecessor]').forEach((input) => input.addEventListener("change", () => {
    activity.predecessors = $$('[data-predecessor]:checked').map((item) => item.dataset.predecessor);
    markDraftDirty(); renderActivityList();
  }));
  bindModeEditors(activity);
  $("#add-mode").addEventListener("click", () => addMode(activity));
  $("#delete-activity").addEventListener("click", () => deleteActivity(activity));
}

function modeCard(activity, mode, modeIndex) {
  const continuity = mode.continuity || "SUSPENDABLE_AT_AVAILABILITY_GAPS";
  const requirements = mode.requirements || [];
  return `<article class="mode-card" data-mode-card="${modeIndex}">
    <div class="mode-fields">
      <label class="${activity.modes?.length === 1 ? "single-mode-id" : ""}">${activity.modes?.length === 1 ? "Method ID (one method)" : "Mode ID"}<input data-mode-id="${modeIndex}" value="${escapeHtml(mode.id)}" maxlength="20"></label>
      <label>Productive activity duration (hours)<input data-mode-work="${modeIndex}" type="number" min="0" max="72" step="0.5" value="${mode.processing_ticks / 2}"></label>
      <label>Activity calendar<select data-mode-calendar="${modeIndex}">${calendarOptions(mode.calendar_id)}</select></label>
      <label>Continuity<select data-mode-continuity="${modeIndex}"><option value="SUSPENDABLE_AT_AVAILABILITY_GAPS" ${continuity === "SUSPENDABLE_AT_AVAILABILITY_GAPS" ? "selected" : ""}>Suspend at availability gaps</option><option value="CONTINUOUS" ${continuity === "CONTINUOUS" ? "selected" : ""}>Continuous productive execution</option></select></label>
      <button type="button" class="danger" data-remove-mode="${modeIndex}">Remove mode</button>
    </div>
    <p class="guidance">Duration is productive processing, not total resource-hours. Capacity and quantity never change it automatically. Zero hours means a milestone with no resource requirements.</p>
    ${draft.resource_groups ? `<div class="requirements"><div class="subheading-row"><strong>Group quantities — required simultaneously</strong><button type="button" data-add-group-requirement="${modeIndex}">Add group quantity</button></div>
      ${(mode.group_requirements || []).map((r, ri) => `<div class="group-demand-row">
        <label>Group<select data-demand-group="${modeIndex}:${ri}">${draft.resource_groups.map(g => `<option value="${escapeHtml(g.id)}" ${g.id === r.group_id ? "selected" : ""}>${escapeHtml(g.id)} · ${escapeHtml(g.name)}</option>`).join("")}</select></label>
        <label>Quantity<input data-group-demand="${modeIndex}:${ri}" type="number" min="1" step="1" value="${r.demand}"></label>
        <button type="button" data-remove-group-requirement="${modeIndex}:${ri}">Remove quantity</button></div>`).join("")}
      <p class="slot-note">One row per group; quantity 2 means two units together, not two eligible alternatives. No individual eligibility entry.</p></div>` : ""}
    <div class="requirements">
      <div class="subheading-row"><strong>Simultaneous requirement slots</strong><button type="button" data-add-requirement="${modeIndex}">Add slot</button></div>
      ${requirements.length ? requirements.map((requirement, requirementIndex) => requirementRow(requirement, modeIndex, requirementIndex)).join("") : `<p class="slot-note">${mode.processing_ticks === 0 ? "Zero-work milestone: no productive time or resource occupancy." : (mode.group_requirements || []).length ? "No named-resource slots. Group quantities above provide the capacity requirements." : "No resource slot: this mode currently consumes productive time without a physical resource."}</p>`}
      <p class="slot-note">One row is one physical slot. Checked resources are alternatives for that slot. Multiple rows are required simultaneously.</p>
    </div>
  </article>`;
}

function calendarOptions(selected) {
  return draft.calendars.map((calendar) => `<option value="${escapeHtml(calendar.id)}" ${calendar.id === selected ? "selected" : ""}>${escapeHtml(calendar.id)}</option>`).join("");
}

function requirementRow(requirement, modeIndex, requirementIndex) {
  return `<div class="requirement-row">
    <label>Slot ID<input data-requirement-id="${modeIndex}:${requirementIndex}" value="${escapeHtml(requirement.id)}" maxlength="20"></label>
    <label>Qualifications<input data-requirement-pools="${modeIndex}:${requirementIndex}" value="${escapeHtml(requirement.pool_ids.join(", "))}" placeholder="MECH"></label>
    <div><span class="field-label">Alternative eligible resources</span><div class="eligibility">${draft.resources.map((resource) => `<label class="checkbox-label"><input type="checkbox" data-eligible data-mode-index="${modeIndex}" data-requirement-index="${requirementIndex}" data-resource-id="${escapeHtml(resource.id)}" ${requirement.eligible_resource_ids.includes(resource.id) ? "checked" : ""}> ${escapeHtml(resource.id)}</label>`).join("")}</div></div>
    <button type="button" class="danger" data-remove-requirement="${modeIndex}:${requirementIndex}">Remove slot</button>
  </div>`;
}

function bindModeEditors(activity) {
  $$('[data-add-group-requirement]').forEach(button => button.addEventListener("click", () => addGroupRequirement(activity, Number(button.dataset.addGroupRequirement))));
  for (const [attribute, key] of [["data-demand-group", "group_id"], ["data-group-demand", "demand"]]) {
    $$(`[${attribute}]`).forEach(input => input.addEventListener("change", () => {
      const [mi, ri] = input.getAttribute(attribute).split(":").map(Number);
      activity.modes[mi].group_requirements[ri][key] = key === "demand" ? Number(input.value) : input.value;
      markDraftDirty();
    }));
  }
  $$('[data-remove-group-requirement]').forEach(button => button.addEventListener("click", () => {
    const [mi, ri] = button.dataset.removeGroupRequirement.split(":").map(Number);
    activity.modes[mi].group_requirements.splice(ri, 1); markDraftDirty(); renderActivityEditor();
  }));
  $$('[data-mode-id]').forEach((input) => input.addEventListener("input", (event) => {
    activity.modes[Number(input.dataset.modeId)].id = event.target.value; markDraftDirty();
  }));
  $$('[data-mode-work]').forEach((input) => input.addEventListener("change", (event) => {
    const hours = Number(event.target.value);
    if (!Number.isFinite(hours) || hours < 0 || !Number.isInteger(hours * 2)) {
      markDraftDirty();
      return showMessage("Productive work must be a nonnegative multiple of 0.5 hours.", "error");
    }
    activity.modes[Number(input.dataset.modeWork)].processing_ticks = hours * 2; markDraftDirty();
  }));
  $$('[data-mode-calendar]').forEach((input) => input.addEventListener("change", (event) => {
    activity.modes[Number(input.dataset.modeCalendar)].calendar_id = event.target.value; markDraftDirty();
  }));
  $$('[data-mode-continuity]').forEach((input) => input.addEventListener("change", (event) => {
    activity.modes[Number(input.dataset.modeContinuity)].continuity = event.target.value; markDraftDirty();
  }));
  $$('[data-remove-mode]').forEach((button) => button.addEventListener("click", () => {
    if (activity.modes.length === 1) return showMessage("Each activity needs at least one authorised mode.", "error");
    activity.modes.splice(Number(button.dataset.removeMode), 1); markDraftDirty(); renderActivityEditor();
  }));
  $$('[data-add-requirement]').forEach((button) => button.addEventListener("click", () => addRequirement(activity, Number(button.dataset.addRequirement))));
  $$('[data-requirement-id]').forEach((input) => input.addEventListener("input", (event) => {
    const [modeIndex, requirementIndex] = input.dataset.requirementId.split(":").map(Number);
    activity.modes[modeIndex].requirements[requirementIndex].id = event.target.value; markDraftDirty();
  }));
  $$('[data-requirement-pools]').forEach((input) => input.addEventListener("input", (event) => {
    const [modeIndex, requirementIndex] = input.dataset.requirementPools.split(":").map(Number);
    activity.modes[modeIndex].requirements[requirementIndex].pool_ids = event.target.value.split(",").map((value) => value.trim()).filter(Boolean);
    markDraftDirty();
  }));
  $$('[data-eligible]').forEach((input) => input.addEventListener("change", () => {
    const {modeIndex, requirementIndex, resourceId} = input.dataset;
    const eligible = activity.modes[Number(modeIndex)].requirements[Number(requirementIndex)].eligible_resource_ids;
    if (input.checked && !eligible.includes(resourceId)) eligible.push(resourceId);
    if (!input.checked) activity.modes[Number(modeIndex)].requirements[Number(requirementIndex)].eligible_resource_ids = eligible.filter((id) => id !== resourceId);
    markDraftDirty();
  }));
  $$('[data-remove-requirement]').forEach((button) => button.addEventListener("click", () => {
    const [modeIndex, requirementIndex] = button.dataset.removeRequirement.split(":").map(Number);
    activity.modes[modeIndex].requirements.splice(requirementIndex, 1); markDraftDirty(); renderActivityEditor();
  }));
}

function addMode(activity) {
  let suffix = activity.modes.length + 1;
  while (activity.modes.some((mode) => mode.id === `MODE${suffix}`)) suffix += 1;
  activity.modes.push({
    id: `MODE${suffix}`, processing_ticks: 2, calendar_id: draft.calendars[0]?.id || "DAY",
    continuity: "SUSPENDABLE_AT_AVAILABILITY_GAPS", requirements: [],
  });
  markDraftDirty(); renderActivityEditor();
}

function addRequirement(activity, modeIndex) {
  const mode = activity.modes[modeIndex];
  mode.requirements ??= [];
  let suffix = mode.requirements.length + 1;
  while (mode.requirements.some((requirement) => requirement.id === `SLOT${suffix}`)) suffix += 1;
  const resource = draft.resources[0];
  mode.requirements.push({
    id: `SLOT${suffix}`,
    pool_ids: resource?.capabilities?.length ? [resource.capabilities[0]] : ["CAPABILITY"],
    eligible_resource_ids: resource ? [resource.id] : [],
  });
  markDraftDirty(); renderActivityEditor();
}

function deleteActivity(activity) {
  if (draft.activities.length <= 8) return showMessage("The browser trial requires at least 8 activities.", "error");
  if (draft.objective_activity_id === activity.id) return showMessage("Choose another controlling completion activity before removing this one.", "error");
  const dependent = draft.activities.find((item) => item.predecessors?.includes(activity.id));
  if (dependent) return showMessage(`${activity.id} is still a predecessor of ${dependent.id}. Remove that reference first.`, "error");
  draft.activities = draft.activities.filter((item) => item.id !== activity.id);
  selectedActivityId = draft.activities[0]?.id ?? null;
  markDraftDirty(); render();
}

function renderResources() {
  renderGroups();
  $("#resource-editor").innerHTML = draft.resources.map((resource, index) => `<div class="resource-row">
    <label>Resource ID<input value="${escapeHtml(resource.id)}" readonly></label>
    <label>Capabilities<input data-resource-capabilities="${index}" value="${escapeHtml(resource.capabilities.join(", "))}"></label>
    <label>Calendar<select data-resource-calendar="${index}">${calendarOptions(resource.calendar_id)}</select></label>
    <button type="button" class="danger" data-remove-resource="${index}">Remove</button>
  </div>`).join("");
  $$('[data-resource-capabilities]').forEach((input) => input.addEventListener("input", (event) => {
    draft.resources[Number(input.dataset.resourceCapabilities)].capabilities = event.target.value.split(",").map((value) => value.trim()).filter(Boolean); markDraftDirty();
  }));
  $$('[data-resource-calendar]').forEach((input) => input.addEventListener("change", (event) => {
    draft.resources[Number(input.dataset.resourceCalendar)].calendar_id = event.target.value; markDraftDirty();
  }));
  $$('[data-remove-resource]').forEach((button) => button.addEventListener("click", () => removeResource(Number(button.dataset.removeResource))));
}

function addGroupRequirement(activity, modeIndex) {
  const mode = activity.modes[modeIndex];
  const available = (draft.resource_groups || []).find(g => !(mode.group_requirements || []).some(r => r.group_id === g.id));
  if (!available) return showMessage("Add a resource group first, or edit the existing quantity row for that group.", "error");
  mode.group_requirements ??= [];
  mode.group_requirements.push({group_id: available.id, demand: 1});
  markDraftDirty(); renderActivityEditor();
}

function renderGroups() {
  $("#group-editor").innerHTML = (draft.resource_groups || []).map((g, i) => `<div class="group-row">
    <label>Group ID<input value="${escapeHtml(g.id)}" readonly></label>
    <label>Name<input data-group-name="${i}" value="${escapeHtml(g.name)}" maxlength="100"></label>
    <label>Capacity<input data-group-capacity="${i}" type="number" min="1" max="32" step="1" value="${g.capacity}"></label>
    <label>Calendar<select data-group-calendar="${i}">${calendarOptions(g.calendar_id)}</select></label>
    <button type="button" data-remove-group="${i}">Remove group</button></div>`).join("")
    || '<p class="guidance">No groups entered.</p>';
  $("#group-profile-help").textContent = draft.resource_groups
    ? "Declared disjoint and internally interchangeable; no outside demand assumed unless included in available capacity. At most 8 groups / 32 total units and 64 assignment/set combinations per activity-mode. Groups are not worker rosters."
    : "Legacy workspace retained unchanged. Use New project for the group-capacity profile; no automatic conversion of old resources, approvals or history.";
  for (const [attribute, key] of [["data-group-name", "name"], ["data-group-capacity", "capacity"], ["data-group-calendar", "calendar_id"]]) {
    $$(`[${attribute}]`).forEach(input => input.addEventListener(key === "name" ? "input" : "change", () => {
      draft.resource_groups[Number(input.getAttribute(attribute))][key] = key === "capacity" ? Number(input.value) : input.value;
      markDraftDirty();
    }));
  }
  $$('[data-remove-group]').forEach(button => button.addEventListener("click", () => removeGroup(Number(button.dataset.removeGroup))));
}

function removeGroup(index) {
  const id = draft.resource_groups[index].id;
  for (const a of draft.activities) for (const m of a.modes) {
    if ((m.group_requirements || []).some(r => r.group_id === id)) return showMessage(`${id} is still required by ${a.id}. Remove that quantity row first.`, "error");
  }
  draft.resource_groups.splice(index, 1); markDraftDirty(); renderResources(); renderActivityEditor();
}

function removeResource(index) {
  const id = draft.resources[index].id;
  for (const activity of draft.activities) for (const mode of activity.modes) for (const requirement of mode.requirements || []) {
    if (requirement.eligible_resource_ids.includes(id)) return showMessage(`${id} is still eligible for ${activity.id}/${mode.id}/${requirement.id}. Remove that reference first.`, "error");
  }
  if (current.workspace.reports.some((report) => report.resource_id === id)) return showMessage(`${id} has retained availability reports and cannot be removed from this workspace.`, "error");
  draft.resources.splice(index, 1); markDraftDirty(); renderResources(); renderActivityEditor(); renderWorkflow();
}

function renderCalendars() {
  $("#calendar-editor").innerHTML = draft.calendars.map((calendar, index) => `<div class="calendar-row">
    <label>Calendar ID<input value="${escapeHtml(calendar.id)}" readonly></label>
    <label>Working windows<input data-calendar-windows="${index}" value="${escapeHtml(windowsLabel(calendar.daily_windows))}"></label>
    <button type="button" class="danger" data-remove-calendar="${index}">Remove</button>
  </div>`).join("");
  $$('[data-calendar-windows]').forEach((input) => input.addEventListener("change", (event) => {
    try { draft.calendars[Number(input.dataset.calendarWindows)].daily_windows = parseWindows(event.target.value); markDraftDirty(); }
    catch (error) { markDraftDirty(); showMessage(error.message, "error"); }
  }));
  $$('[data-remove-calendar]').forEach((button) => button.addEventListener("click", () => removeCalendar(Number(button.dataset.removeCalendar))));
}

function removeCalendar(index) {
  const id = draft.calendars[index].id;
  const resource = [...draft.resources, ...(draft.resource_groups || [])].find((item) => item.calendar_id === id);
  if (resource) return showMessage(`${id} is still used by resource ${resource.id}. Change that reference first.`, "error");
  for (const activity of draft.activities) for (const mode of activity.modes) {
    if (mode.calendar_id === id) return showMessage(`${id} is still used by ${activity.id}/${mode.id}. Change that reference first.`, "error");
  }
  draft.calendars.splice(index, 1); markDraftDirty(); renderCalendars(); renderProjectSettings(); renderActivityEditor(); renderResources();
}

function renderStatusWorkflow() {
  const workspace = current.workspace;
  const point = $("#status-point-control");
  const region = $("#status-workflow");
  if (workspace.schema !== "pm-native-planning-workspace/2") {
    point.innerHTML = `<label>Status point <input id="status-point-input" value="1@11:00" placeholder="1@11:00"></label><button id="enable-status" type="button">Enable accepted progress</button>`;
    region.innerHTML = '<p class="empty">No execution status has been recorded. Set the status point explicitly; existing approvals remain inspectable and become stale.</p>';
    $("#enable-status").addEventListener("click", async () => {
      try {
        await perform("/api/enable-status", {status_point: parseRelativeTime($("#status-point-input").value)}, "Status point established. Record and accept an explicit status for every activity.", true);
      } catch (error) {
        if (!$("#message").classList.contains("error")) showMessage(error.message, "error");
      }
    });
    return;
  }
  const statusPoint = workspace.execution.status_point;
  point.innerHTML = `<div class="status-point"><span>Status point</span><strong>${tickLabel(statusPoint)}</strong><small>tick ${statusPoint}</small></div>`;
  const currentUpdates = currentExecutionUpdates(workspace);
  if (!selectedStatusActivityId || !workspace.project.activities.some((activity) => activity.id === selectedStatusActivityId)) {
    selectedStatusActivityId = workspace.project.activities[0]?.id ?? null;
  }
  const activity = workspace.project.activities.find((item) => item.id === selectedStatusActivityId);
  const accepted = currentUpdates[selectedStatusActivityId] || null;
  const state = accepted?.execution_state || "NOT_STARTED";
  const modeId = accepted?.mode_id || activity.modes[0]?.id || "";
  const statusModes = [...activity.modes];
  if (accepted?.execution_context?.mode && !statusModes.some((item) => item.id === modeId)) {
    statusModes.push({...accepted.execution_context.mode, historicalOnly: true});
  }
  const mode = statusModes.find((item) => item.id === modeId) || statusModes[0];
  const groupLabel = (mode?.group_requirements || []).map((demand) => `${demand.group_id} × ${demand.demand}`).join(", ") || "None";
  const acceptedRows = workspace.project.activities.map((item) => {
    const update = currentUpdates[item.id];
    const status = update?.execution_state || "UNKNOWN";
    const actual = update?.actual_periods?.length ? update.actual_periods.map(([start, finish]) => `${compactTick(start)}–${compactTick(finish)}`).join("; ") : "—";
    const remaining = update?.remaining_processing_ticks == null ? "—" : `${update.remaining_processing_ticks / 2} h`;
    const provenance = update ? `${update.id} · ${update.accepted_by}${update.supersedes_update_id ? ` · corrects ${update.supersedes_update_id}` : ""}` : "No accepted assertion";
    return `<tr class="${item.id === selectedStatusActivityId ? "selected-status" : ""}"><td><button type="button" class="link-button" data-status-activity="${escapeHtml(item.id)}">${escapeHtml(item.id)}</button> · ${escapeHtml(item.name)}</td><td><span class="badge ${status === "UNKNOWN" ? "reported" : "current"}">${escapeHtml(status)}</span></td><td>${escapeHtml(actual)}</td><td>${escapeHtml(remaining)}</td><td>${escapeHtml(provenance)}</td></tr>`;
  }).join("");
  const pending = workspace.execution.updates.filter((update) => update.status === "REPORTED");
  const pendingHtml = pending.length ? pending.map((update) => `<article class="report-item status-update-item">
    <div><p><strong>${escapeHtml(update.id)} · ${escapeHtml(update.activity_id)} · ${escapeHtml(update.execution_state)}</strong> <span class="badge reported">REVIEW</span></p>
    <p>${update.actual_periods.length ? `Actual ${escapeHtml(periodsInput(update.actual_periods))}` : "No actual productive periods"} · remaining ${update.remaining_processing_ticks == null ? "—" : `${update.remaining_processing_ticks / 2} h`}</p>
    <p class="report-meta">Asserted by ${escapeHtml(update.asserted_by)} · occurrence ${tickLabel(update.occurred_at)}${update.supersedes_update_id ? ` · supersedes ${escapeHtml(update.supersedes_update_id)}` : ""} · ${escapeHtml(update.reason)}</p></div>
    <div><label>Acceptance actor<input data-status-acceptance-actor="${escapeHtml(update.id)}" value="trial-planner" maxlength="80"></label><button type="button" data-accept-status="${escapeHtml(update.id)}">Accept reviewed update</button></div>
  </article>`).join("") : '<p class="empty">No status updates are awaiting acceptance.</p>';
  region.innerHTML = `<div class="status-grid">
    <div class="status-table-region"><div class="subheading-row"><h3>Current accepted state</h3><span>Every UNKNOWN blocks recovery</span></div><div class="table-scroll"><table><thead><tr><th>Activity</th><th>Status</th><th>Actual productive periods</th><th>Remaining</th><th>Acceptance / correction</th></tr></thead><tbody>${acceptedRows}</tbody></table></div></div>
    <form id="status-update-form" class="status-editor"><div class="subheading-row"><h3>Draft update · ${escapeHtml(activity.id)}</h3><span>${accepted ? `Correction of ${escapeHtml(accepted.id)}` : "First assertion"}</span></div>
      <div class="status-form-grid">
        <label>Execution state<select id="execution-state">${["NOT_STARTED", "IN_PROGRESS", "COMPLETED"].map((value) => `<option ${value === state ? "selected" : ""}>${value}</option>`).join("")}</select></label>
        <label>Mode used<select id="execution-mode">${statusModes.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === modeId ? "selected" : ""}>${escapeHtml(item.id)}${item.historicalOnly ? " (accepted history; retired)" : ""}</option>`).join("")}</select></label>
        <label>Actual start<input id="actual-start" value="${accepted?.actual_start == null ? "" : inputTick(accepted.actual_start)}" placeholder="1@10:00"></label>
        <label id="status-finish-field" ${state === "COMPLETED" ? "" : "hidden"}>Actual finish<input id="actual-finish" value="${accepted?.actual_finish == null ? "" : inputTick(accepted.actual_finish)}" placeholder="1@11:00"></label>
        <label class="wide">Actual productive periods<input id="actual-periods" value="${escapeHtml(periodsInput(accepted?.actual_periods || []))}" placeholder="1@10:00-1@11:00; 1@12:30-1@13:00"></label>
        <label>Remaining productive hours<input id="remaining-hours" type="number" min="0" step="0.5" value="${accepted?.remaining_processing_ticks == null ? "" : accepted.remaining_processing_ticks / 2}"></label>
        <label id="status-assignments-field" class="wide" ${mode?.requirements?.length ? "" : "hidden"}>Named assignments<input id="actual-assignments" value="${escapeHtml((accepted?.named_assignments || []).map(([slot, resource]) => `${slot}=${resource}`).join(", "))}" placeholder="SLOT=RESOURCE"></label>
        <label>Occurred at<input id="status-occurred" value="${inputTick(accepted?.occurred_at ?? statusPoint)}"></label>
        <label>Asserted by<input id="status-actor" value="trial-planner" maxlength="80"></label>
        <label class="wide">Reason<input id="status-reason" value="${accepted ? "Reviewed correction" : "Reviewed status-point assertion"}" maxlength="160"></label>
      </div>
      <p class="guidance">Group requirement for the selected mode: <strong id="status-group-requirement">${escapeHtml(groupLabel)}</strong>. Group work records quantity only; do not enter anonymous unit identities.</p>
      <button class="primary" type="submit">Record update for review</button>
    </form>
  </div><div class="pending-status"><h3>Review and accept drafted updates</h3>${pendingHtml}</div>`;
  $("#execution-mode").addEventListener("change", () => {
    const selectedMode = statusModes.find((item) => item.id === $("#execution-mode").value);
    $("#status-group-requirement").textContent = (selectedMode?.group_requirements || []).map((demand) => `${demand.group_id} × ${demand.demand}`).join(", ") || "None";
    $("#status-assignments-field").hidden = !selectedMode?.requirements?.length;
    if (!selectedMode?.requirements?.length) $("#actual-assignments").value = "";
  });
  $("#execution-state").addEventListener("change", () => {
    $("#status-finish-field").hidden = $("#execution-state").value !== "COMPLETED";
  });
  $$('[data-status-activity]').forEach((button) => button.addEventListener("click", () => { selectedStatusActivityId = button.dataset.statusActivity; renderStatusWorkflow(); syncActions(); }));
  $$('[data-accept-status]').forEach((button) => button.addEventListener("click", async () => {
    const updateId = button.dataset.acceptStatus;
    const actor = $(`[data-status-acceptance-actor="${CSS.escape(updateId)}"]`).value;
    try { await perform("/api/accept-status", {update_id: updateId, actor}, `${updateId} accepted into trusted project state. Any prior approval is now stale.`); }
    catch (_error) { /* visible message is sufficient */ }
  }));
  $("#status-update-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const executionState = $("#execution-state").value;
      const begun = executionState !== "NOT_STARTED";
      const completed = executionState === "COMPLETED";
      const hoursValue = $("#remaining-hours").value;
      const remainingTicks = completed ? 0 : (begun ? parseRemainingHours(hoursValue) : null);
      await perform("/api/status-update", {
        activity_id: activity.id,
        execution_state: executionState,
        actor: $("#status-actor").value,
        reason: $("#status-reason").value,
        actual_start: begun ? optionalRelativeTime($("#actual-start").value) : null,
        actual_finish: completed ? optionalRelativeTime($("#actual-finish").value) : null,
        actual_periods: begun ? parseProductivePeriods($("#actual-periods").value) : [],
        mode_id: begun ? $("#execution-mode").value : null,
        named_assignments: begun ? parseNamedAssignments($("#actual-assignments").value) : [],
        remaining_processing_ticks: remainingTicks,
        occurred_at: parseRelativeTime($("#status-occurred").value),
        supersedes_update_id: accepted?.id || null,
      }, "Status update recorded for review. Trusted state is unchanged until acceptance.");
    } catch (error) {
      if (!$("#message").classList.contains("error")) showMessage(error.message, "error");
    }
  });
}

function planCard(title, plan, status) {
  if (!plan) return `<article class="summary-card"><h3>${title}</h3><p class="empty">None recorded.</p></article>`;
  const actor = plan.approved_by ? `<p class="guidance">Approved by ${escapeHtml(plan.approved_by)} at ${escapeHtml(plan.approved_at)}</p>` : '<p class="guidance">Calculated only — approval is still pending.</p>';
  return `<article class="summary-card ${status.toLowerCase()}">
    <div class="subheading-row"><h3>${title}</h3><span class="badge ${status.toLowerCase()}">${status}</span></div>
    <div class="metric-row">
      <div class="metric"><strong>${tickLabel(plan.project_finish)}</strong><span>Controlling finish</span></div>
      <div class="metric"><strong>${escapeHtml(plan.physical_status)}</strong><span>Physical checker</span></div>
      ${plan.source_snapshot.project.resources.some(r => r.capabilities.includes("RIGGER")) ? `<div class="metric"><strong>${plan.pooled_riggers ? "Deferred pool" : "Named"}</strong><span>Rigging identity (legacy)</span></div>` : ""}
    </div>${actor}<details><summary>Solver / audit details</summary><p class="guidance">${escapeHtml(plan.group_proof || "Exact physical assignment check under the declared roster and no-handover rule.")}</p><p class="guidance">${escapeHtml(plan.solver.name)} ${escapeHtml(plan.solver.version)} · ${escapeHtml(plan.solver.proof)}<br>Policy result: ${escapeHtml(JSON.stringify(plan.objective))}<br>Plan hash: ${escapeHtml(plan.plan_hash)}</p></details>
  </article>`;
}

function renderWorkflow() {
  const workspace = current.workspace;
  $("#outage-resource").innerHTML = draft.resources.map((resource) => `<option value="${escapeHtml(resource.id)}">${escapeHtml(resource.id)}</option>`).join("");
  $("#reports-list").innerHTML = workspace.reports.length ? workspace.reports.map((report) => `<article class="report-item">
    <div><p><strong>${escapeHtml(report.id)} · ${escapeHtml(report.resource_id)}</strong> <span class="badge ${report.status === "ACCEPTED" ? "current" : "reported"}">${escapeHtml(report.status)}</span></p>
      <p>${tickLabel(report.start)} – ${tickLabel(report.finish)} · ${escapeHtml(report.reason)}</p>
      <p class="report-meta">Reported by ${escapeHtml(report.reported_by)}${report.accepted_by ? ` · accepted by ${escapeHtml(report.accepted_by)}` : ""}</p></div>
    ${report.status === "REPORTED" ? `<div><label>Acceptance actor<input data-acceptance-actor="${escapeHtml(report.id)}" value="trial-planner" maxlength="80"></label><button type="button" data-accept-report="${escapeHtml(report.id)}">Accept selected report</button></div>` : ""}
  </article>`).join("") : '<p class="empty">No resource-availability information recorded.</p>';
  $$('[data-accept-report]').forEach((button) => button.addEventListener("click", async () => {
    const reportId = button.dataset.acceptReport;
    const actor = $(`[data-acceptance-actor="${CSS.escape(reportId)}"]`).value;
    try { await perform("/api/accept", {report_id: reportId, actor}, `${reportId} accepted as trusted scheduling input.`); }
    catch (_error) { /* visible message is sufficient */ }
  }));
  $("#plan-summary").innerHTML = planCard("Current approved plan", workspace.approved_plan, current.approved_status) + planCard("Pending proposal", workspace.proposal, current.proposal_status);
  renderComparison();
  renderAlternatives();
}

function listOrNone(items, formatter) {
  return items.length ? `<ul>${items.map((item) => `<li>${formatter(item)}</li>`).join("")}</ul>` : '<span class="guidance">None</span>';
}

function renderComparison() {
  const comparison = current.comparison;
  if (!comparison) {
    $("#comparison").innerHTML = '<h3>Computed recovery comparison</h3><p class="empty">A current approval and a separate proposal are both required for before/after comparison.</p>';
    return;
  }
  $("#comparison").innerHTML = `<h3>Computed recovery comparison</h3>
    <div class="metric-row"><div class="metric"><strong>${tickLabel(comparison.old_finish)}</strong><span>Approved finish</span></div><div class="metric"><strong>${tickLabel(comparison.new_finish)}</strong><span>Proposed finish</span></div></div>
    <div class="comparison-grid">
      <div class="change-box"><h4>Changed modes</h4>${listOrNone(comparison.changed_modes, (item) => `${escapeHtml(item.activity_id)}: ${escapeHtml(item.old ?? "not present")} → ${escapeHtml(item.new ?? "not present")}`)}</div>
      <div class="change-box"><h4>Changed assignments</h4>${listOrNone(comparison.changed_assignments, (item) => escapeHtml(item.activity_id))}</div>
      <div class="change-box"><h4>Changed group quantities</h4>${listOrNone(comparison.changed_group_demands || [], (item) => `${escapeHtml(item.activity_id)}: ${escapeHtml(JSON.stringify(item.old))} → ${escapeHtml(JSON.stringify(item.new))}`)}</div>
      <div class="change-box"><h4>Changed timing / execution periods</h4>${listOrNone(comparison.changed_periods, (item) => `${escapeHtml(item.activity_id)}: ${timingChangeLabel(item.old_start, item.old_finish)} → ${timingChangeLabel(item.new_start, item.new_finish)}`)}</div>
      <div class="change-box"><h4>Unchanged activities</h4>${listOrNone(comparison.unchanged_activity_ids, (item) => escapeHtml(item))}</div>
    </div><p class="guidance">These are computed changes and evaluated alternatives, not a causal explanation.</p>`;
}

function timingChangeLabel(start, finish) {
  if (start === null) return "not present";
  return start === finish ? tickLabel(start) : `${tickLabel(start)}–${tickLabel(finish)}`;
}

function renderAlternatives() {
  const proposal = current.workspace.proposal;
  if (!proposal) { $("#alternatives").innerHTML = ""; return; }
  $("#alternatives").innerHTML = `<h3>Evaluated authorised-mode alternatives</h3><div class="table-scroll"><table class="alternatives-table"><thead><tr><th>Mode choices</th><th>Solver result</th><th>Controlling finish</th></tr></thead><tbody>${proposal.alternatives.map((alternative) => `<tr><td>${Object.entries(alternative.modes).filter(([, mode]) => mode !== "FIXED").map(([activity, mode]) => `${escapeHtml(activity)} ${escapeHtml(mode)}`).join(", ") || "Fixed modes"}</td><td>${escapeHtml(alternative.status)}</td><td>${alternative.status === "OPTIMAL" ? tickLabel(alternative.objective[0]) : "—"}</td></tr>`).join("")}</tbody></table></div>`;
}

function selectedPlan() {
  const workspace = current.workspace;
  if (displayedPlanKind === "proposal" && workspace.proposal) return [workspace.proposal, "proposal"];
  if (workspace.approved_plan) return [workspace.approved_plan, "approved"];
  if (workspace.proposal) return [workspace.proposal, "proposal"];
  return [null, "none"];
}

function assignmentLabel(activity, plan, entry) {
  const modeId = plan.selected_modes[activity.id];
  const mode = activity.modes.find((item) => item.id === modeId);
  const requirements = Object.fromEntries((mode?.requirements || []).map((requirement) => [requirement.id, requirement]));
  const groups = (entry.group_demands || []).map(([id, quantity]) => `${escapeHtml(id)} × ${quantity} (group capacity)`);
  if (!entry.assignments.length && !groups.length) return "No resource demand";
  return [...groups, ...entry.assignments.map(([slot, resource]) => {
    if (resource !== null) return `${escapeHtml(slot)}: ${escapeHtml(resource)}`;
    return `<span class="deferred">${escapeHtml(slot)}: deferred ${escapeHtml((requirements[slot]?.pool_ids || []).join("+") || "pool")}</span>`;
  })].join("<br>");
}

function actualAssignmentLabel(entry) {
  const groups = (entry.actual_group_demands || []).map(([id, quantity]) => `${escapeHtml(id)} × ${quantity} (accepted group)`);
  const named = (entry.actual_assignments || []).map(([slot, resource]) => `${escapeHtml(slot)}: ${escapeHtml(resource)}`);
  return [...groups, ...named].join("<br>") || "No resource demand";
}

function renderResults() {
  const [plan, kind] = selectedPlan();
  displayedPlanKind = kind;
  const choices = [];
  if (current.workspace.approved_plan) choices.push(`<button type="button" data-plan-kind="approved" class="${kind === "approved" ? "active" : ""}">Approved</button>`);
  if (current.workspace.proposal) choices.push(`<button type="button" data-plan-kind="proposal" class="${kind === "proposal" ? "active" : ""}">Proposal</button>`);
  $("#plan-picker").innerHTML = choices.join("");
  $$('[data-plan-kind]').forEach((button) => button.addEventListener("click", () => { displayedPlanKind = button.dataset.planKind; renderResults(); syncActions(); }));
  if (!plan) {
    $("#plan-table").innerHTML = '<tr><td colspan="6" class="empty">Calculate a proposal to inspect actual scheduled results.</td></tr>';
    $("#timeline").innerHTML = '<p class="empty">No calculated productive periods.</p>';
    return;
  }
  const sourceActivities = plan.source_snapshot?.project?.activities || current.workspace.project.activities;
  const activities = Object.fromEntries(sourceActivities.map((activity) => [activity.id, activity]));
  const statused = Number.isInteger(plan.status_point);
  $("#plan-table").innerHTML = plan.entries.map((entry) => {
    const activity = activities[entry.activity_id];
    if (statused) {
      const actual = entry.actual_periods.length ? entry.actual_periods.map(([start, finish]) => `${compactTick(start)}–${compactTick(finish)}`).join("; ") : "None";
      const forecast = entry.forecast_periods.length ? entry.forecast_periods.map(([start, finish]) => `${compactTick(start)}–${compactTick(finish)}`).join("; ") : (entry.execution_state === "COMPLETED" ? "None — completed" : "Zero remaining; completion unconfirmed");
      const start = entry.actual_start == null ? (entry.forecast_start == null ? "—" : tickLabel(entry.forecast_start)) : tickLabel(entry.actual_start);
      const finish = entry.forecast_finish == null ? (entry.actual_finish == null ? "—" : tickLabel(entry.actual_finish)) : tickLabel(entry.forecast_finish);
      return `<tr><td><strong>${escapeHtml(entry.activity_id)}</strong> · ${escapeHtml(activity.name)}<br><span class="badge current">${escapeHtml(entry.execution_state)}</span></td><td>${activity.modes.length === 1 && plan.selected_modes[entry.activity_id] === "FIXED" ? '<span class="guidance" title="FIXED — sole authorised method">Single method</span>' : escapeHtml(plan.selected_modes[entry.activity_id])}</td><td>${start}</td><td>${finish}</td><td><div class="actual-line"><strong>ACTUAL</strong> ${escapeHtml(actual)}</div><div class="forecast-line"><strong>FORECAST</strong> ${escapeHtml(forecast)} · ${entry.remaining_processing_ticks / 2} h</div></td><td><div class="actual-line"><strong>ACTUAL</strong><br>${actualAssignmentLabel(entry)}</div><div class="forecast-line"><strong>FORECAST</strong><br>${assignmentLabel(activity, plan, entry)}</div></td></tr>`;
    }
    const periods = entry.periods.length ? entry.periods.map(([start, finish]) => `${compactTick(start)}–${compactTick(finish)}`).join("; ") : "Milestone";
    return `<tr><td><strong>${escapeHtml(entry.activity_id)}</strong> · ${escapeHtml(activity.name)}</td><td>${activity.modes.length === 1 && plan.selected_modes[entry.activity_id] === "FIXED" ? '<span class="guidance" title="FIXED — sole authorised method">Single method</span>' : escapeHtml(plan.selected_modes[entry.activity_id])}</td><td>${tickLabel(entry.start)}</td><td>${tickLabel(entry.finish)}</td><td class="period-list">${escapeHtml(periods)}</td><td>${assignmentLabel(activity, plan, entry)}</td></tr>`;
  }).join("");
  renderTimeline(plan, kind, activities);
}

function renderTimeline(plan, kind, activities) {
  const statused = Number.isInteger(plan.status_point);
  const nonempty = plan.entries.flatMap((entry) => statused ? [...entry.actual_periods, ...entry.forecast_periods] : entry.periods);
  const axisStart = nonempty.length ? Math.min(...nonempty.map((period) => period[0])) : 0;
  const axisFinish = Math.max(axisStart + 1, plan.project_finish);
  const span = axisFinish - axisStart;
  const markers = Array.from({length: 6}, (_, index) => Math.round(axisStart + (span * index / 5)));
  const statusLine = statused ? `<span class="timeline-status-point" title="Status point: ${tickLabel(plan.status_point)}" style="left:${((plan.status_point - axisStart) / span) * 100}%"></span>` : "";
  const axis = `${statused ? `<p class="guidance">ACTUAL · status point ${tickLabel(plan.status_point)} · FORECAST</p>` : ""}<div class="timeline-axis"><div class="timeline-label"><strong>${kind === "proposal" ? "Proposal" : "Approved plan"}</strong></div><div class="timeline-track">${markers.map((tick) => `<span class="axis-label" style="left:${((tick - axisStart) / span) * 100}%">${compactTick(tick)}</span>`).join("")}</div></div>`;
  const rows = plan.entries.map((entry) => {
    const segments = statused
      ? [...entry.actual_periods.map(([start, finish]) => `<span class="timeline-segment actual" title="ACTUAL: ${compactTick(start)} to ${compactTick(finish)}" style="left:${((start - axisStart) / span) * 100}%;width:${((finish - start) / span) * 100}%"></span>`),
         ...entry.forecast_periods.map(([start, finish]) => `<span class="timeline-segment forecast" title="FORECAST: ${compactTick(start)} to ${compactTick(finish)}" style="left:${((start - axisStart) / span) * 100}%;width:${((finish - start) / span) * 100}%"></span>`)]
      : entry.periods.map(([start, finish]) => `<span class="timeline-segment ${kind}" title="Productive: ${compactTick(start)} to ${compactTick(finish)}" style="left:${((start - axisStart) / span) * 100}%;width:${((finish - start) / span) * 100}%"></span>`);
    if (statused && !segments.length) {
      const tick = entry.execution_state === "COMPLETED" ? entry.actual_finish : entry.forecast_finish;
      segments.push(`<span class="timeline-milestone ${entry.execution_state === "COMPLETED" ? "actual" : "forecast"}" title="${entry.execution_state === "COMPLETED" ? "ACTUAL completed" : "FORECAST unconfirmed"}: ${compactTick(tick)}" style="left:${((tick - axisStart) / span) * 100}%">◆</span>`);
    }
    return `<div class="timeline-row"><div class="timeline-label" title="${escapeHtml(activities[entry.activity_id].name)}">${escapeHtml(entry.activity_id)} · ${escapeHtml(activities[entry.activity_id].name)}</div><div class="timeline-track">${statusLine}${segments.join("")}</div></div>`;
  }).join("");
  $("#timeline").innerHTML = axis + rows;
}

function renderHistory() {
  const history = current.workspace.plan_history;
  const approvals = history.length ? history.map((plan, index) => `<div class="history-row"><strong>Prior approval ${index + 1}</strong><span>${tickLabel(plan.project_finish)} · ${escapeHtml(plan.plan_hash.slice(0, 12))}…</span><span>Approved by ${escapeHtml(plan.approved_by)} at ${escapeHtml(plan.approved_at)}</span></div>`).join("") : '<p class="empty">No previous approved plans. Replaced approvals appear here.</p>';
  const updates = current.workspace.schema === "pm-native-planning-workspace/2" ? current.workspace.execution.updates.filter((update) => update.status === "ACCEPTED") : [];
  const currentIds = new Set(Object.values(currentExecutionUpdates(current.workspace)).map((update) => update.id));
  const execution = updates.length ? updates.map((update) => `<div class="history-row"><strong>${escapeHtml(update.id)} · ${escapeHtml(update.activity_id)}<br>${currentIds.has(update.id) ? "CURRENT" : "SUPERSEDED"}</strong><span>${escapeHtml(update.execution_state)}${update.supersedes_update_id ? ` · supersedes ${escapeHtml(update.supersedes_update_id)}` : ""}<br>${escapeHtml(update.reason)}<br>ACTUAL: ${escapeHtml(periodsInput(update.actual_periods)) || "No productive periods"}<br>Remaining forecast: ${update.remaining_processing_ticks == null ? "Current unstarted estimate" : `${update.remaining_processing_ticks / 2} h`} · mode ${escapeHtml(update.mode_id || "Unselected")}<br>Occurred ${tickLabel(update.occurred_at)}</span><span>Asserted by ${escapeHtml(update.asserted_by)} at ${escapeHtml(update.asserted_at)}<br>Accepted by ${escapeHtml(update.accepted_by)} at ${escapeHtml(update.accepted_at)}</span></div>`).join("") : '<p class="empty">No accepted execution assertions.</p>';
  $("#history").innerHTML = `<h3>Approved plan history</h3>${approvals}<h3>Accepted execution provenance</h3>${execution}`;
}

function syncActions() {
  if (!current) return;
  $$(".project-panel input, .project-panel select, .project-panel button, .status-panel input, .status-panel select, .status-panel button, .workflow-panel input, .workflow-panel select, .workflow-panel button").forEach((control) => {
    control.disabled = busy;
  });
  const blocked = busy || invalidating || draftConflict;
  $("#apply-project").disabled = blocked || !draftDirty;
  $("#calculate").disabled = blocked || draftDirty;
  $("#approve").disabled = blocked || draftDirty || current.proposal_status !== "CURRENT" || displayedPlanKind !== "proposal";
  $("#start-trial").disabled = blocked;
  $("#load-example").disabled = blocked;
  $("#new-project").disabled = blocked;
  $("#save-workspace").disabled = blocked;
  $("#open-file").disabled = blocked;
  $("#download-trial-result").disabled = blocked || draftDirty || !activeTrial;
  $("#reload-inputs").disabled = busy || invalidating;
  $$('.workflow-panel button').forEach((button) => { if (button.id !== "calculate" && button.id !== "approve") button.disabled = blocked; });
  $("#add-group").disabled = busy || !draft?.resource_groups;
  $$('#report-form input, #report-form select, #report-form button').forEach(control => {
    control.disabled = blocked || draftDirty || !current.workspace.project.resources?.length;
  });
  $$('.status-panel input, .status-panel select, .status-panel button').forEach(control => {
    control.disabled = blocked || draftDirty;
  });
}

async function applyDraft(message = "Trusted project inputs applied. Calculate a new proposal.") {
  await pendingInvalidation;
  const data = await perform("/api/project", {project: draft, revision: draftRevision}, message, true);
  return data;
}

$("#apply-project").addEventListener("click", async () => {
  try { await applyDraft(); }
  catch (_error) { /* last valid state and visible draft remain intact */ }
});

$("#reload-inputs").addEventListener("click", async () => {
  if (!window.confirm("Discard this tab's retained draft and reload the current server inputs? Copy any unsent edits you want to keep first.")) return;
  await start();
});

$("#calculate").addEventListener("click", async () => {
  try { await perform("/api/calculate", {}, "Executable proposal calculated and independently checked."); }
  catch (_error) { /* accepted facts and prior approval remain visible */ }
});

$("#approve").addEventListener("click", async () => {
  try { await perform("/api/approve", {actor: $("#approval-actor").value}, "The current validated proposal is now approved."); }
  catch (_error) { /* visible message is sufficient */ }
});

$("#report-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const start = parseRelativeTime($("#outage-start").value);
    const finish = parseRelativeTime($("#outage-finish").value);
    await perform("/api/report", {
      resource_id: $("#outage-resource").value, start, finish,
      reporter: $("#outage-reporter").value, reason: $("#outage-reason").value,
    }, "Availability reported. Trusted inputs and the approved plan are unchanged.");
  } catch (error) {
    if (!$("#message").classList.contains("error")) showMessage(error.message, "error");
  }
});

$("#load-example").addEventListener("click", async () => {
  if (!discardNeedsConfirmation()) return;
  try {
    await perform("/api/load-example", {}, "Built-in eight-activity example loaded without calculating it.", true);
    finishWorkspaceReplacement(false);
  }
  catch (_error) { /* visible message is sufficient */ }
});

$("#start-trial").addEventListener("click", async () => {
  if (busy || invalidating || draftConflict) return;
  if (!discardNeedsConfirmation()) return;
  try {
    await perform("/api/load-trial", {}, "Pristine approved practitioner trial loaded. Review the plan and field briefing before recording status.", true);
    finishWorkspaceReplacement(true);
    $("#trial-brief").scrollIntoView({behavior: "smooth", block: "start"});
  } catch (_error) { /* visible message is sufficient */ }
});

$("#new-project").addEventListener("click", async () => {
  if (!discardNeedsConfirmation()) return;
  try {
    await perform("/api/new", {}, "New eight-activity starter created. Edit its native inputs through the controls.", true);
    finishWorkspaceReplacement(false);
  }
  catch (_error) { /* visible message is sufficient */ }
});

$("#save-workspace").addEventListener("click", async () => {
  try {
    if (draftDirty) await applyDraft("Input changes applied before export.");
    const data = await perform("/api/export", {}, "Complete native workspace downloaded.");
    // Loopback returns the formatted download for compatibility. The hosted
    // response carries the workspace once in state to stay below Vercel's
    // response limit, so format that authoritative returned value locally.
    const workspaceJson = workspaceDownloadJson(data);
    const blob = new Blob([workspaceJson], {type: "application/json"});
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = data.filename.replace(/[^A-Za-z0-9_.-]/g, "-");
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
  } catch (_error) { /* visible message is sufficient */ }
});

$("#download-trial-result").addEventListener("click", async () => {
  let exporting = false;
  try {
    if (busy) throw new Error("Wait for the current workspace action to finish before downloading the trial result.");
    await pendingInvalidation;
    if (!activeTrial) throw new Error("Start the practitioner trial before downloading a trial result.");
    if (!current || invalidating || draftConflict || draftDirty) {
      throw new Error("Apply or resolve all pending workspace changes before downloading the trial result.");
    }
    exporting = true;
    setBusy(true);
    const responses = Object.fromEntries($$("[data-question]").map((field) => [field.dataset.question, field.value]));
    const result = {
      trial: current.trial,
      completed_at: new Date().toISOString(),
      responses,
      workspace: current.workspace,
    };
    const blob = new Blob([`${JSON.stringify(result, null, 2)}\n`], {type: "application/json"});
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${current.trial?.id || "planner-trial"}-result.json`;
    document.body.appendChild(link);
    link.click(); link.remove(); URL.revokeObjectURL(link.href);
    questionnaireDirty = false;
    showMessage("Trial result and questionnaire responses downloaded. Save Workspace separately for a reopenable native workspace.");
  } catch (error) { showMessage(error.message, "error"); }
  finally { if (exporting) setBusy(false); }
});

$$("[data-question]").forEach((field) => field.addEventListener("input", () => { questionnaireDirty = true; }));

window.addEventListener?.("beforeunload", (event) => {
  if (!current || (!current.dirty && !draftDirty && !questionnaireDirty)) return;
  event.preventDefault();
  event.returnValue = "";
});

$("#open-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  if (!discardNeedsConfirmation()) { event.target.value = ""; return; }
  try {
    const workspace = JSON.parse(await file.text());
    await perform("/api/open", {workspace, filename: file.name}, `Opened ${file.name} without recalculating or approving it.`, true);
    finishWorkspaceReplacement(false);
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    event.target.value = "";
  }
});

$("#add-activity").addEventListener("click", () => {
  try {
    if (draft.activities.length >= 15) throw new Error("The browser trial supports at most 15 activities.");
    const id = requireIdentifier($("#new-activity-id").value, "Activity ID");
    if (draft.activities.some((activity) => activity.id === id)) throw new Error(`Activity ID ${id} already exists.`);
    draft.activities.push({id, name: $("#new-activity-name").value.trim() || "New activity", predecessors: [], not_before: 0, modes: [{id: "FIXED", processing_ticks: 2, calendar_id: draft.calendars[0]?.id || "DAY", continuity: "SUSPENDABLE_AT_AVAILABILITY_GAPS", requirements: []}]});
    selectedActivityId = id; markDraftDirty(); render();
    $("#new-activity-id").value = ""; $("#new-activity-name").value = "";
  } catch (error) { showMessage(error.message, "error"); }
});

$("#add-resource").addEventListener("click", () => {
  try {
    const id = requireIdentifier($("#new-resource-id").value, "Resource ID");
    if ([...draft.resources, ...(draft.resource_groups || [])].some((resource) => resource.id === id)) throw new Error(`Resource ID ${id} already exists.`);
    const capabilities = $("#new-resource-capabilities").value.split(",").map((value) => value.trim()).filter(Boolean);
    if (!capabilities.length) throw new Error("Enter at least one explicit capability.");
    draft.resources.push({id, capabilities, calendar_id: draft.calendars[0]?.id || "DAY"});
    markDraftDirty(); renderResources(); renderActivityEditor(); renderWorkflow(); renderProjectSettings();
    $("#new-resource-id").value = ""; $("#new-resource-capabilities").value = "";
  } catch (error) { showMessage(error.message, "error"); }
});

$("#add-group").addEventListener("click", () => {
  try {
    if (!draft.resource_groups) throw new Error("Use New project for the group-capacity profile.");
    const id = requireIdentifier($("#new-group-id").value, "Group ID");
    if ([...draft.resource_groups, ...draft.resources].some(g => g.id === id)) throw new Error(`Resource/group ID ${id} already exists.`);
    const name = $("#new-group-name").value.trim();
    const capacity = Number($("#new-group-capacity").value);
    if (!name || !Number.isInteger(capacity) || capacity < 1) throw new Error("Enter a group name and positive whole-number capacity.");
    if (!$("#new-group-declared").checked) throw new Error("Confirm this group is disjoint from every other group and named resource, and internally interchangeable.");
    draft.resource_groups.push({id, name, capacity, calendar_id: draft.calendars[0]?.id || "DAY", disjoint: true, interchangeable: true});
    markDraftDirty(); renderResources(); renderActivityEditor();
    $("#new-group-id").value = ""; $("#new-group-name").value = ""; $("#new-group-declared").checked = false;
  } catch (error) { showMessage(error.message, "error"); }
});

$("#add-calendar").addEventListener("click", () => {
  try {
    const id = requireIdentifier($("#new-calendar-id").value, "Calendar ID");
    if (draft.calendars.some((calendar) => calendar.id === id)) throw new Error(`Calendar ID ${id} already exists.`);
    draft.calendars.push({id, daily_windows: parseWindows($("#new-calendar-windows").value)});
    markDraftDirty(); renderCalendars(); renderProjectSettings(); renderActivityEditor(); renderResources();
    $("#new-calendar-id").value = ""; $("#new-calendar-windows").value = "";
  } catch (error) { showMessage(error.message, "error"); }
});

async function start() {
  setBusy(true);
  try {
    const response = await fetch(hostedTransport ? "/api/planning" : "/api/state", {cache: "no-store"});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    if (data.runtime) window.__pmTrialRuntime = [{path: "/api/state", ...data.runtime}];
    adoptState(data.state, true);
    const footer = document.querySelector("footer");
    if (hostedTransport && footer) {
      footer.textContent = "Hosted bounded trial. Workspace state stays in this browser and portable JSON files; serverless functions retain no authoritative session state. Relative days are not dates or time zones.";
    }
  } catch (error) {
    showMessage(`Cannot reach the planning service: ${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

start();
