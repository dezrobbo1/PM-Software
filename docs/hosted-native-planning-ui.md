# Hosted native planning UI trial

Prototype 3 makes the existing bounded native planning trial available through a protected Vercel Preview. A practitioner opens the Preview URL supplied on the Prototype 3 pull request; PM-Software does not need to be installed on that device.

This remains a trial, not a public production service.

## Architecture

```text
existing HTML/CSS/JavaScript UI
        |
        | same-origin HTTPS JSON
        v
Vercel Python Function (`api/index.py`)
        |
        v
stateless adapter (`native_planning_ui/hosted.py`)
        |
        v
existing validator -> CP-SAT scheduler -> exact physical checker
        |
        v
complete replacement workspace returned to the browser
```

The browser submits the complete current workspace, its local revision and one narrow action. The function validates the candidate workspace and stored plans before making a deep-copy candidate, delegates the action to the same dispatcher used by the loopback UI, and returns either the complete successful replacement or the unchanged submitted state. Vercel instance memory is diagnostic only and is never authoritative project state.

The hosted approval path validates the submitted proposal, recalculates it with the authoritative Python scheduler, compares the plan hash and only then calls the existing approval transition. Opening a saved workspace validates stored output and historical snapshots but does not optimise or silently reconstruct approvals.

## Hosted request boundary

All mutations use `POST /api/planning` with `Content-Type: application/json` and exactly:

```json
{
  "expected_revision": 0,
  "state": {
    "revision": 0,
    "dirty": false,
    "source": "Built-in example",
    "workspace": {}
  },
  "payload": {"action": "calculate"}
}
```

The adapter accepts only the existing bounded actions: load example, new, open, apply project, invalidate proposal, calculate, approve, report, accept and export. It applies the existing 8–15 activity, capacity-one resource, calendar and authorised-mode bounds. Requests larger than 2 MiB are rejected. Mutations require the exact serving HTTPS Origin and Vercel-forwarded HTTPS scheme. There is no wildcard CORS or public API contract.

The revision is a browser-workspace sequencing guard, not a multi-user lock. Because the function is deliberately stateless, two devices do not share a workspace unless a user explicitly moves the portable JSON file between them.

## Practitioner walkthrough

1. Open the protected Preview URL from the pull request and choose **Load example** or **New project**.
2. Edit activities, authorised modes, requirement slots, resources and calendars with the existing controls, then choose **Apply input changes**.
3. Choose **Calculate plan / recovery**. Inspect selected modes, productive segments, calendar gaps, assignments, controlling finish and physical-check result.
4. Enter the local actor label and approve the displayed current proposal.
5. Report a resource outage. Reporting remains untrusted information and does not change the approved plan or trusted-input hash.
6. Accept the report separately, calculate the recovery, inspect computed changes and evaluated alternatives, then approve the recovery separately if appropriate.
7. Choose **Save workspace** to download the complete native JSON workspace.
8. In a new tab or later session, choose **Open workspace** and select that file. Approval history, accepted reports and proposal/approval distinctions reopen without automatic calculation.

Times remain 30-minute, project-relative `day@HH:MM` values, not dates or time zones.

## Developer commands

Install the pinned Python package and browser harness:

```bash
python -m pip install -e .
npm install --ignore-scripts
```

The unchanged loopback application remains the one-command local development path:

```bash
python -m deterministic_scheduling_core.native_planning_ui
```

Open `http://127.0.0.1:8765` and stop it with `Ctrl+C`. The hosted adapter is deployed as a Vercel Preview with `vercel deploy`; `vercel.json` selects Python 3.12, a 60-second function maximum and the bounded bundle exclusions. Preview Protection should remain enabled. Windows launch commands are documented in the local guide and remain unverified in this Linux trial.

Run the hosted adapter regressions:

```bash
python -m unittest tests.test_hosted_native_planning_ui -v
```

Run real-browser acceptance against an authorised HTTPS Preview URL:

```bash
PM_HOSTED_URL="https://preview-url" \
PM_HOSTED_EVIDENCE_DIR="/tmp/pm-hosted-evidence" \
npm run browser:hosted
```

The harness uses Chromium at 1366x900, 1920x1080 and 390x844; exercises plan, approval, report/accept/recovery, download/reopen and a post-reopen duration edit; rejects loopback API traffic; and retains screenshots, a trace, assertion output, timing observations and the saved workspace.

## Observed hosted behaviour

The protected Preview reproduced the existing planning results through the real deployed Python backend:

- the example selected `A03` `SPECIALIST`, finished Day 1 15:00, passed the exact physical checker and drew two A03 productive segments around lunch;
- reporting M2 unavailable Day 1 10:00–17:00 changed neither the trusted-input hash nor the Day 1 15:00 approval;
- accepting that report made the old approval stale without approving a recovery;
- recovery selected `A03` `NORMAL`, finished Day 2 08:30 and retained the evaluated `SPECIALIST` alternative at Day 2 11:30;
- the approved recovery download contained the accepted report and the previous approval in history.

Deployment identifiers, timings, the remaining browser assertions and retained files belong in the pull request/evidence record for the exact final deployment, not in this rolling guide.

## Current limitations

- Preview Protection and its authorised access/share mechanism are deployment controls, not application user accounts.
- Actor strings retain the existing local-provenance meaning and are not authenticated identities.
- There is no server database, autosave, collaboration, cross-device merge or recovery of an unsaved browser workspace.
- A refresh intentionally starts from the example; users must download important workspaces before leaving and reopen them explicitly.
- Function cold starts and OR-Tools package size are trial observations, not production benchmarks or a scaling design.
- Workspace hashes are integrity checks, not signatures or proof of authorship/optimality. Imported historical plans are validated without silently replanning them.
- The existing 8–15 activity planning profile and native model limitations remain unchanged.

The hosted trial is suitable for the next bounded practitioner-use experiment if the final Preview acceptance remains green. It is not evidence of production readiness.
