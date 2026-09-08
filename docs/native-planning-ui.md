# Minimal native planning trial UI

This is the local launch guide for the thin browser interface over the native planning workflow. It calls the existing Python project validation, CP-SAT scheduling, exact physical checker, resource-report acceptance, proposal approval and JSON workspace persistence functions. It does not calculate dates or assignments in JavaScript. The stateless Vercel Preview adaptation is documented separately in [`hosted-native-planning-ui.md`](hosted-native-planning-ui.md).

## Install and launch

Prerequisites:

- Python 3.11 or later;
- a current desktop browser;
- permission to install the pinned Python dependencies from `pyproject.toml`.

From the repository root:

```bash
python -m pip install -e .
python -m deterministic_scheduling_core.native_planning_ui
```

Open `http://127.0.0.1:8765`. The service binds only to IPv4 loopback. Stop it with `Ctrl+C`; restart it with the same command. Browser sessions live in memory, so download the workspace before stopping if it must be retained.

Windows PowerShell uses the same two commands when `python` is on `PATH`. If Windows provides the Python launcher instead, use `py -m pip install -e .` and `py -m deterministic_scheduling_core.native_planning_ui`. Those Windows instructions are documented but were not executed in the Linux implementation environment.

## Practitioner walkthrough

1. Choose **Load example** or **New project**. New project creates eight editable native activities; the trial accepts 8–15.
2. Select an activity in the table. Edit its name, finish-to-start predecessors, not-before time, authorised modes, productive work, activity calendar, continuity and requirement slots. Activity IDs are chosen when adding a row and remain read-only afterwards.
3. Open **Resources and calendars** to edit explicit resource capabilities, calendar membership and daily working windows. Each physical resource has capacity one.
4. Choose **Apply input changes**. Invalid references, cycles, qualifications or disconnected work are rejected without replacing the last valid/approved workspace.
5. Choose **Calculate plan / recovery**. The Python scheduler returns selected modes, productive execution periods and assignments; the independent physical checker must pass before a proposal is displayed.
6. Inspect the plan table and read-only Gantt. Each blue/green segment is productive execution. A visible gap across lunch or overnight is suspension, not resource occupancy.
7. Enter an approval actor and choose **Approve displayed proposal**. Edits invalidate a pending proposal and pause approval until inputs are reapplied and recalculated.
8. Report an availability interval with resource, relative start/finish, reporter and reason. A reported item is not trusted scheduling input. Accept it separately with an acceptance actor, calculate a recovery, compare it with the retained approval, then approve the recovery separately if appropriate.
9. Choose **Save workspace** to download the complete `pm-native-planning-workspace/0` JSON. **Open workspace** uploads that file back to this loopback service. Inputs, reports, acceptance metadata, the current approval, pending proposal and earlier approvals round-trip without recalculation.

Relative times use `day@HH:MM`, for example `1@07:00` or `2@08:30`. Days are project-relative 24-hour buckets, not dates or time zones. All editable time values use 30-minute increments. Productive work is shown in hours rather than internal ticks.

## Requirement and assignment meanings

- One requirement row is one physical slot. Several qualification values in that row describe one slot that needs all of them.
- Several requirement rows on a mode are simultaneous physical slots.
- Checked resources within one row are alternatives; the optimiser selects one eligible physical resource.
- When the two capacity-one riggers remain genuinely interchangeable, the solver may show a deferred `RIGGER` pool instead of an arbitrary person. The exact checker supplies a consistent allocation witness.
- Capabilities and eligibility are explicit inputs. The interface does not infer either from names or job titles.

## State and persistence protections

Each browser session has a monotonic revision. Mutating requests must submit the revision they read; an older response cannot overwrite newer state. The interface disables conflicting actions during a calculation, and a second acceptance/approval request fails after the first transition advances the revision. Rendering and refresh only read current state—they do not solve or approve.

Each editor draft retains its base revision. If another tab in the same browser session changes the workspace, a conflict keeps the unsent draft visible and blocks both Apply and Save. Copy any edits you want to retain, then choose **Reload current inputs** and confirm discarding the old draft before making a deliberate new edit. No automatic merge or silent rebasing occurs. Proposal invalidation runs without disabling the active editor; calculation and approval remain blocked while inputs are unapplied.

Unapplied form edits are visibly marked and block calculation/approval. Editing a displayed proposal immediately invalidates it. Applying a project edit is atomic: validation succeeds before trusted project inputs are replaced. Accepted infeasibility keeps the accepted report and previous approval, labels that approval stale and leaves no proposal.

Loading another source with unsaved or unapplied changes requires confirmation. The server never accepts a browser-supplied server filesystem path or shell command. Persistence is download/upload only, and static assets are packaged locally without fonts or CDNs.

Opening validates every stored approval, proposal and history record against its own source snapshot and existing hashes, including execution periods and actual physical assignment checking. Valid historical approvals may remain stale relative to current inputs. Rejection leaves the existing workspace, revision and saved/dirty state intact. Import never optimises, repairs dates, recalculates hashes to bless changed output, or changes approval provenance. Integrity hashes are not signatures or proof of authorship or optimality. Optional native requirements remain optional; editor changes do not normalise historical snapshots. Moved milestones appear under **Changed timing / execution periods** with old/new occurrence times, without productive occupancy.

HTTP access is limited to `127.0.0.1` or `localhost` at the actual serving port. Any supplied Origin must match the serving HTTP scheme, hostname and effective port; null, malformed and foreign-port origins are rejected. Mutation endpoints require `Content-Type: application/json`. Origin-less local non-browser JSON clients are intentionally accepted with the same Host, session and revision checks. This is not an authentication boundary against other local processes. Use `--port 8766` (or another available port) to change the launch port; binding remains loopback-only.

## Tests and browser evidence

Backend and HTTP integration:

```bash
python -m unittest tests.test_native_planning_ui tests.test_native_planning_workflow -v
node --test tests/browser/native_planning_ui_draft.test.mjs
```

Repeatable real-browser acceptance (after `npm install` and `npx playwright install chromium`):

```bash
npm run browser:smoke
```

The browser harness starts its own loopback Python service and exercises the original example, a duration edit, a second project entered through controls, invalid input, accepted infeasibility, downloads/reopens and both required desktop viewports. Set `PM_UI_EVIDENCE_DIR` to retain screenshots, trace, workspaces and the observed result log in a chosen directory. CI stores these as the `native-planning-ui-browser` artifact.

The completed trial used Playwright with Headless Chrome 151.0.7922.34 on Linux x86_64 at 1366×900 and 1920×1080. Observed results were:

- the original example selected `A03` `SPECIALIST`, finished Day 1 15:00, passed the exact physical check and drew two A03 segments across lunch;
- reporting M2 unavailable on Day 1 10:00–17:00 changed neither the trusted-input hash nor approval until acceptance;
- the accepted recovery selected `A03` `NORMAL`, finished Day 2 08:30 and retained the evaluated `SPECIALIST` alternative at Day 2 11:30;
- changing A01 from one to two productive hours through the form was received by Python and moved the observed finish from Day 1 15:00 to Day 1 16:00; a subsequent edit disabled stale approval;
- the independently entered project finished Day 1 15:00, chose `N06` `QUICK`, assigned parallel mechanical work to distinct M1/M2 resources and split pooled rigging across 11:00–12:00 and 12:30–13:30;
- invalid cyclic input and accepted full-horizon M2 infeasibility remained visible without losing the previous approval or accepted report;
- save/reopen retained approval history, accepted reports and pending-vs-approved distinctions without recalculation;
- neither desktop viewport had page-level horizontal overflow, and no unexpected console error occurred. Chromium logged the expected failed-resource diagnostics for the deliberately exercised HTTP 400 and 422 responses.

The exact retained evidence location and artifact inventory are in [`evidence/native-planning-ui/README.md`](../evidence/native-planning-ui/README.md).

The bounded PR #26 corrections also exercise same-session two-tab conflicts, keyboard typing during delayed real invalidation responses, stored-plan rejection without replacement, tick-30-to-65 zero-work handoff movement, omitted requirements and colon-containing resource IDs, and a real second-port browser mutation attempt. See the evidence index for measured counts and the tested commit/run, rather than treating the earlier 39-assertion trial as a fresh result.

## Current limitations

This is a bounded practitioner trial, not a production application. The local launch has an in-memory single-process session store; both transports use local actor strings rather than authenticated identities, repeated daily calendars, capacity-one physical resources, finish-to-start precedence, at most 16 authorised mode combinations, and 8–15 activities in the browser profile. It has no drag scheduling, partial progress/actual history, structural Work–Method subgraphs, adaptive-neighbourhood integration, external schedule import/export, database, collaboration, enterprise permissions, touch-specific interaction design or general workforce/calendar language. The hosted Preview removes the installation requirement but does not remove those domain limitations.

Output dates remain calculated results. To change a plan, edit trusted native inputs and calculate another proposal.
