"use strict";

let current = null;
let draft = null;
let selectedActivityId = null;
let displayedPlanKind = "proposal";
let draftDirty = false;
let busy = false;
let pendingInvalidation = Promise.resolve();

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

async function request(path, payload = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({revision: current.revision, ...payload}),
  });
  let data;
  try {
    data = await response.json();
  } catch (_error) {
    throw new Error(`The local service returned HTTP ${response.status} without a JSON response.`);
  }
  if (!response.ok) {
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
    selectedActivityId = draft.activities[0]?.id ?? null;
  }
  if (state.workspace.proposal) displayedPlanKind = "proposal";
  else if (state.workspace.approved_plan) displayedPlanKind = "approved";
  window.__pmTrialState = clone(state);
  render();
}

function setBusy(value) {
  busy = value;
  document.body.setAttribute("aria-busy", String(value));
  syncActions();
}

async function perform(path, payload, message, replaceDraft = false) {
  clearMessage();
  setBusy(true);
  try {
    const data = await request(path, payload);
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
  if (!draftDirty && !current?.dirty) return true;
  return window.confirm("This workspace has unsaved or unapplied changes. Discard them and continue?");
}

function markDraftDirty() {
  if (!draftDirty) {
    draftDirty = true;
    if (current.workspace.proposal) {
      pendingInvalidation = (async () => {
        setBusy(true);
        try {
          const data = await request("/api/invalidate-proposal");
          current = data.state;
          window.__pmTrialState = clone(current);
          showMessage("The prior proposal was invalidated. Apply the edited inputs, then calculate again.");
          renderStatus();
          renderWorkflow();
          renderResults();
        } catch (error) {
          showMessage(error.message, "error");
        } finally {
          setBusy(false);
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
  $("#draft-state").textContent = draftDirty ? "Unapplied edits — calculation and approval paused" : "Inputs applied";
}

function renderProjectSettings() {
  $("#project-settings").innerHTML = `
    <label>Project ID<input id="project-id" value="${escapeHtml(draft.id)}" maxlength="60"></label>
    <label>Project name<input id="project-name" value="${escapeHtml(draft.name)}" maxlength="100"></label>
    <label>Horizon (days)<input id="project-horizon" type="number" min="1" max="14" step="1" value="${draft.horizon_ticks / 48}"></label>
    <label>Controlling completion<select id="objective-activity">${draft.activities.map((activity) => `<option value="${escapeHtml(activity.id)}" ${activity.id === draft.objective_activity_id ? "selected" : ""}>${escapeHtml(activity.id)} · ${escapeHtml(activity.name)}</option>`).join("")}</select></label>
    <label class="checkbox-label"><input id="pool-riggers" type="checkbox" ${draft.pool_riggers ? "checked" : ""}> Defer interchangeable RIGGER identity</label>`;
  $("#project-id").addEventListener("input", (event) => { draft.id = event.target.value; markDraftDirty(); });
  $("#project-name").addEventListener("input", (event) => { draft.name = event.target.value; markDraftDirty(); });
  $("#project-horizon").addEventListener("change", (event) => {
    const days = Number(event.target.value);
    if (!Number.isInteger(days) || days < 1 || days > 14) return showMessage("Horizon must be 1–14 whole relative days.", "error");
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
    const select = () => { selectedActivityId = row.dataset.activityId; renderActivityList(); renderActivityEditor(); };
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
      ${draft.activities.filter((other) => other.id !== activity.id).map((other) => `<label class="checkbox-label"><input type="checkbox" data-predecessor="${escapeHtml(other.id)}" ${(activity.predecessors || []).includes(other.id) ? "checked" : ""}> ${escapeHtml(other.id)}</label>`).join("")}
    </div>
    <div class="mode-list">${activity.modes.map((mode, modeIndex) => modeCard(activity, mode, modeIndex)).join("")}</div>
    <div class="editor-actions"><button id="add-mode" type="button">Add authorised mode</button>&nbsp;<button id="delete-activity" class="danger" type="button">Remove activity</button></div>`;

  $("#activity-name").addEventListener("input", (event) => { activity.name = event.target.value; markDraftDirty(); renderActivityList(); });
  $("#activity-not-before").addEventListener("change", (event) => {
    try { activity.not_before = parseRelativeTime(event.target.value); markDraftDirty(); }
    catch (error) { showMessage(error.message, "error"); }
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
  return `<article class="mode-card" data-mode-card="${modeIndex}">
    <div class="mode-fields">
      <label>Mode ID<input data-mode-id="${modeIndex}" value="${escapeHtml(mode.id)}" maxlength="20"></label>
      <label>Work (hours)<input data-mode-work="${modeIndex}" type="number" min="0" max="72" step="0.5" value="${mode.processing_ticks / 2}"></label>
      <label>Activity calendar<select data-mode-calendar="${modeIndex}">${calendarOptions(mode.calendar_id)}</select></label>
      <label>Continuity<select data-mode-continuity="${modeIndex}"><option value="SUSPENDABLE_AT_AVAILABILITY_GAPS" ${continuity === "SUSPENDABLE_AT_AVAILABILITY_GAPS" ? "selected" : ""}>Suspend at availability gaps</option><option value="CONTINUOUS" ${continuity === "CONTINUOUS" ? "selected" : ""}>Continuous productive execution</option></select></label>
      <button type="button" class="danger" data-remove-mode="${modeIndex}">Remove mode</button>
    </div>
    <div class="requirements">
      <div class="subheading-row"><strong>Simultaneous requirement slots</strong><button type="button" data-add-requirement="${modeIndex}">Add slot</button></div>
      ${mode.requirements.length ? mode.requirements.map((requirement, requirementIndex) => requirementRow(requirement, modeIndex, requirementIndex)).join("") : '<p class="slot-note">No resource slot: this mode currently consumes productive time without a physical resource.</p>'}
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
    <div><span class="field-label">Alternative eligible resources</span><div class="eligibility">${draft.resources.map((resource) => `<label class="checkbox-label"><input type="checkbox" data-eligible="${modeIndex}:${requirementIndex}:${escapeHtml(resource.id)}" ${requirement.eligible_resource_ids.includes(resource.id) ? "checked" : ""}> ${escapeHtml(resource.id)}</label>`).join("")}</div></div>
    <button type="button" class="danger" data-remove-requirement="${modeIndex}:${requirementIndex}">Remove slot</button>
  </div>`;
}

function bindModeEditors(activity) {
  $$('[data-mode-id]').forEach((input) => input.addEventListener("input", (event) => {
    activity.modes[Number(input.dataset.modeId)].id = event.target.value; markDraftDirty();
  }));
  $$('[data-mode-work]').forEach((input) => input.addEventListener("change", (event) => {
    const hours = Number(event.target.value);
    if (!Number.isFinite(hours) || hours < 0 || !Number.isInteger(hours * 2)) return showMessage("Productive work must be a nonnegative multiple of 0.5 hours.", "error");
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
    const [modeIndex, requirementIndex, resourceId] = input.dataset.eligible.split(":");
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

function removeResource(index) {
  const id = draft.resources[index].id;
  for (const activity of draft.activities) for (const mode of activity.modes) for (const requirement of mode.requirements) {
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
    catch (error) { showMessage(error.message, "error"); }
  }));
  $$('[data-remove-calendar]').forEach((button) => button.addEventListener("click", () => removeCalendar(Number(button.dataset.removeCalendar))));
}

function removeCalendar(index) {
  const id = draft.calendars[index].id;
  const resource = draft.resources.find((item) => item.calendar_id === id);
  if (resource) return showMessage(`${id} is still used by resource ${resource.id}. Change that reference first.`, "error");
  for (const activity of draft.activities) for (const mode of activity.modes) {
    if (mode.calendar_id === id) return showMessage(`${id} is still used by ${activity.id}/${mode.id}. Change that reference first.`, "error");
  }
  draft.calendars.splice(index, 1); markDraftDirty(); renderCalendars(); renderProjectSettings(); renderActivityEditor(); renderResources();
}

function planCard(title, plan, status) {
  if (!plan) return `<article class="summary-card"><h3>${title}</h3><p class="empty">None recorded.</p></article>`;
  const actor = plan.approved_by ? `<p class="guidance">Approved by ${escapeHtml(plan.approved_by)} at ${escapeHtml(plan.approved_at)}</p>` : '<p class="guidance">Calculated only — approval is still pending.</p>';
  return `<article class="summary-card ${status.toLowerCase()}">
    <div class="subheading-row"><h3>${title}</h3><span class="badge ${status.toLowerCase()}">${status}</span></div>
    <div class="metric-row">
      <div class="metric"><strong>${tickLabel(plan.project_finish)}</strong><span>Controlling finish</span></div>
      <div class="metric"><strong>${escapeHtml(plan.physical_status)}</strong><span>Physical checker</span></div>
      <div class="metric"><strong>${plan.pooled_riggers ? "Deferred pool" : "Named"}</strong><span>Rigging identity</span></div>
    </div>${actor}
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
      <div class="change-box"><h4>Changed modes</h4>${listOrNone(comparison.changed_modes, (item) => `${escapeHtml(item.activity_id)}: ${escapeHtml(item.old)} → ${escapeHtml(item.new)}`)}</div>
      <div class="change-box"><h4>Changed assignments</h4>${listOrNone(comparison.changed_assignments, (item) => escapeHtml(item.activity_id))}</div>
      <div class="change-box"><h4>Changed execution periods</h4>${listOrNone(comparison.changed_periods, (item) => escapeHtml(item.activity_id))}</div>
      <div class="change-box"><h4>Unchanged activities</h4>${listOrNone(comparison.unchanged_activity_ids, (item) => escapeHtml(item))}</div>
    </div><p class="guidance">These are computed changes and evaluated alternatives, not a causal explanation.</p>`;
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
  if (!entry.assignments.length) return "No physical slot";
  return entry.assignments.map(([slot, resource]) => {
    if (resource !== null) return `${escapeHtml(slot)}: ${escapeHtml(resource)}`;
    return `<span class="deferred">${escapeHtml(slot)}: deferred ${escapeHtml((requirements[slot]?.pool_ids || []).join("+") || "pool")}</span>`;
  }).join("<br>");
}

function renderResults() {
  const [plan, kind] = selectedPlan();
  displayedPlanKind = kind;
  const choices = [];
  if (current.workspace.approved_plan) choices.push(`<button type="button" data-plan-kind="approved" class="${kind === "approved" ? "active" : ""}">Approved</button>`);
  if (current.workspace.proposal) choices.push(`<button type="button" data-plan-kind="proposal" class="${kind === "proposal" ? "active" : ""}">Proposal</button>`);
  $("#plan-picker").innerHTML = choices.join("");
  $$('[data-plan-kind]').forEach((button) => button.addEventListener("click", () => { displayedPlanKind = button.dataset.planKind; renderResults(); }));
  if (!plan) {
    $("#plan-table").innerHTML = '<tr><td colspan="6" class="empty">Calculate a proposal to inspect actual scheduled results.</td></tr>';
    $("#timeline").innerHTML = '<p class="empty">No calculated productive periods.</p>';
    return;
  }
  const activities = Object.fromEntries(current.workspace.project.activities.map((activity) => [activity.id, activity]));
  $("#plan-table").innerHTML = plan.entries.map((entry) => {
    const activity = activities[entry.activity_id];
    const periods = entry.periods.length ? entry.periods.map(([start, finish]) => `${compactTick(start)}–${compactTick(finish)}`).join("; ") : "Milestone";
    return `<tr><td><strong>${escapeHtml(entry.activity_id)}</strong> · ${escapeHtml(activity.name)}</td><td>${escapeHtml(plan.selected_modes[entry.activity_id])}</td><td>${tickLabel(entry.start)}</td><td>${tickLabel(entry.finish)}</td><td class="period-list">${escapeHtml(periods)}</td><td>${assignmentLabel(activity, plan, entry)}</td></tr>`;
  }).join("");
  renderTimeline(plan, kind, activities);
}

function renderTimeline(plan, kind, activities) {
  const nonempty = plan.entries.flatMap((entry) => entry.periods);
  const axisStart = nonempty.length ? Math.min(...nonempty.map((period) => period[0])) : 0;
  const axisFinish = Math.max(axisStart + 1, plan.project_finish);
  const span = axisFinish - axisStart;
  const markers = Array.from({length: 6}, (_, index) => Math.round(axisStart + (span * index / 5)));
  const axis = `<div class="timeline-axis"><div class="timeline-label"><strong>${kind === "proposal" ? "Proposal" : "Approved plan"}</strong></div><div class="timeline-track">${markers.map((tick) => `<span class="axis-label" style="left:${((tick - axisStart) / span) * 100}%">${compactTick(tick)}</span>`).join("")}</div></div>`;
  const rows = plan.entries.map((entry) => `<div class="timeline-row"><div class="timeline-label" title="${escapeHtml(activities[entry.activity_id].name)}">${escapeHtml(entry.activity_id)} · ${escapeHtml(activities[entry.activity_id].name)}</div><div class="timeline-track">${entry.periods.map(([start, finish]) => `<span class="timeline-segment ${kind}" title="Productive: ${compactTick(start)} to ${compactTick(finish)}" style="left:${((start - axisStart) / span) * 100}%;width:${((finish - start) / span) * 100}%"></span>`).join("")}</div></div>`).join("");
  $("#timeline").innerHTML = axis + rows;
}

function renderHistory() {
  const history = current.workspace.plan_history;
  $("#history").innerHTML = history.length ? history.map((plan, index) => `<div class="history-row"><strong>Prior approval ${index + 1}</strong><span>${tickLabel(plan.project_finish)} · ${escapeHtml(plan.plan_hash.slice(0, 12))}…</span><span>Approved by ${escapeHtml(plan.approved_by)} at ${escapeHtml(plan.approved_at)}</span></div>`).join("") : '<p class="empty">No previous approved plans. Replaced approvals appear here.</p>';
}

function syncActions() {
  if (!current) return;
  $$(".project-panel input, .project-panel select, .project-panel button, .workflow-panel input, .workflow-panel select, .workflow-panel button").forEach((control) => {
    control.disabled = busy;
  });
  $("#apply-project").disabled = busy || !draftDirty;
  $("#calculate").disabled = busy || draftDirty;
  $("#approve").disabled = busy || draftDirty || current.proposal_status !== "CURRENT";
  $("#load-example").disabled = busy;
  $("#new-project").disabled = busy;
  $("#save-workspace").disabled = busy;
  $("#open-file").disabled = busy;
  $$('[data-accept-report]').forEach((button) => { button.disabled = busy; });
}

async function applyDraft(message = "Trusted project inputs applied. Calculate a new proposal.") {
  await pendingInvalidation;
  const data = await perform("/api/project", {project: draft}, message, true);
  return data;
}

$("#apply-project").addEventListener("click", async () => {
  try { await applyDraft(); }
  catch (_error) { /* last valid state and visible draft remain intact */ }
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
  try { await perform("/api/load-example", {}, "Built-in eight-activity example loaded without calculating it.", true); }
  catch (_error) { /* visible message is sufficient */ }
});

$("#new-project").addEventListener("click", async () => {
  if (!discardNeedsConfirmation()) return;
  try { await perform("/api/new", {}, "New eight-activity starter created. Edit its native inputs through the controls.", true); }
  catch (_error) { /* visible message is sufficient */ }
});

$("#save-workspace").addEventListener("click", async () => {
  try {
    if (draftDirty) await applyDraft("Input changes applied before export.");
    const data = await perform("/api/export", {}, "Complete native workspace downloaded.");
    const blob = new Blob([data.workspace_json], {type: "application/json"});
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = data.filename.replace(/[^A-Za-z0-9_.-]/g, "-");
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
  } catch (_error) { /* visible message is sufficient */ }
});

$("#open-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  if (!discardNeedsConfirmation()) { event.target.value = ""; return; }
  try {
    const workspace = JSON.parse(await file.text());
    await perform("/api/open", {workspace, filename: file.name}, `Opened ${file.name} without recalculating or approving it.`, true);
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
    if (draft.resources.some((resource) => resource.id === id)) throw new Error(`Resource ID ${id} already exists.`);
    const capabilities = $("#new-resource-capabilities").value.split(",").map((value) => value.trim()).filter(Boolean);
    if (!capabilities.length) throw new Error("Enter at least one explicit capability.");
    draft.resources.push({id, capabilities, calendar_id: draft.calendars[0]?.id || "DAY"});
    markDraftDirty(); renderResources(); renderActivityEditor(); renderWorkflow();
    $("#new-resource-id").value = ""; $("#new-resource-capabilities").value = "";
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
    const response = await fetch("/api/state", {cache: "no-store"});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    adoptState(data.state, true);
  } catch (error) {
    showMessage(`Cannot reach the local planning service: ${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

start();
