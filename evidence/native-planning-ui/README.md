# Native planning browser evidence

## Bounded PR #26 corrections

Starting head: `0d148689d37fe1a9805430d04a0a3662d8b794a0`; live main/base: `d2b2b386cca80b82f1d3737343ce3ef0a59ba067`.

The corrected executable source at `a0d240f1a563f4c11afdd8be37172bc25893728c` passed both CI jobs:

- run: <https://github.com/dezrobbo1/PM-Software/actions/runs/34034069189>
- browser artifact: `native-planning-ui-browser`, ID `9989588673`
- artifact SHA-256: `0ee4429f7698621a67ecf59d883a43b57c4f4ca8ad58162f4c12286bf015bf75`
- 149 focused Python tests; 5 JavaScript state regressions; 73 real-browser assertions
- all existing experiment/workflow commands, compilation and JavaScript syntax checks passed locally; both CI jobs passed
- Headless Chrome 151.0.7922.34, Linux x86_64, 1366×900 and 1920×1080
- six deliberately induced HTTP 400/403/409/422 console diagnostics; no unexpected browser errors

The final documentation commit is rerun in CI before handoff; its exact SHA, run and artifact identifiers are recorded in the delivered ZIP's final manifest and the PR description. `browser-smoke-output.txt` records the corrected run; `initial-browser-smoke-output.txt` retains the original trial record below.

| Finding | Reproduced starting behaviour | Correction and passing regression |
|---|---|---|
| A / 3943816649 | Retrying a draft after 409 reused the newer revision | Draft revision and explicit conflict state; Apply/Save blocked until confirmed reload. Same-context two-tab browser test preserves tab A, retains tab B's unsent text, and verifies deliberate editing after recovery. |
| B / 3943816663 | Changed finish/allocation and damaged history accepted; malformed plans could poison the session | Candidate-only validation of each stored plan against its own source/hash and exact physical checker before adoption. Tests cover recovery/history, stale approval/proposal, modified finish/hash, recomputed-hash invalid allocation, malformed records and continued use after rejection. No optimisation or uploaded-output repair. |
| C / 3943816668 | Empty-period milestone moving 30→65 reported unchanged | Compare start/finish as well as periods; browser shows Day 1 15:00 → Day 2 08:30. Unchanged milestone remains unchanged; no invented productive periods or assignments. |
| D / 3943816656 | First input event disabled the focused control | Background invalidation blocks mutations, not the editor. Sequential keyboard tests in name and capability fields use a 700ms delay on actual Python responses, preserve text/focus/caret, then apply/calculate/approve successfully. |
| E / 3943816661 | Omitted optional requirements crashed rendering | Safe empty-list defaults; create a list only in editable slot addition. Browser tests render, edit slots, enforce resource references, calculate/save/reopen, and retain the prior hashed snapshot byte-for-byte. |
| F / 3943816666 | Foreign-port Origin and text/plain JSON accepted | Exact loopback Host/serving-port, complete supplied Origin, JSON content-type checks. HTTP tests verify rejection is atomic; a second-port real-browser attempt receives 403 and leaves the target state/revision unchanged. Origin-less local JSON clients remain explicitly supported. |

The prior three regressions also pass: stale removed activities render from source snapshots, approval is disabled when Approved is displayed, and colon-containing resource IDs survive eligibility edits. Original planning numbers are unchanged: initial SPECIALIST Day 1 15:00; NORMAL recovery Day 2 08:30; SPECIALIST alternative Day 2 11:30; duration-edit Day 1 16:00; independent QUICK case Day 1 15:00 with distinct mechanics and lunch-suspended rigging.

The complete handoff ZIP includes the files themselves: 12 screenshots, 7 actual Playwright traces, 5 saved native workspace files, independent-case preregistration, final assertion output, baseline failing and corrected targeted logs, local smoke/experiment results, documentation, final CI metadata and checksums. Trace copies redact only ephemeral session-cookie values, retaining actual events/responses/screenshots. No new automated review was manually requested. This is a bounded trial correction, not production-readiness or exhaustive-defect coverage.

## Original trial evidence (retained)

The successful real-browser run is GitHub Actions **POC smoke #163**, commit `4bc39ea2714a559fd6cc72f1a83660f19900f79e`:

- workflow run: <https://github.com/dezrobbo1/PM-Software/actions/runs/34030149375>
- retained artifact: `native-planning-ui-browser`, ID `9988333685`
- artifact digest: `sha256:96ed308bc74700613a023308c4297312173d708cbe082fade25b16e9b50c9d6a`
- GitHub expiry reported at capture: 2026-12-05 11:24 UTC

The artifact contains:

- `01-example-baseline-1366x900.png`
- `02-example-recovery-1366x900.png`
- `03-example-reopened-1920x1080.png`
- `04-duration-edit-stale-1366x900.png`
- `05-independent-case-1366x900.png`
- `06-independent-reopened-1920x1080.png`
- `07-infeasible-recovery-1366x900.png`
- `example-trace.zip`
- `example-approved-recovery.pm-workspace.json`
- `independent-browser-entered.pm-workspace.json`
- `independent-case-preregistered.json`
- `browser-smoke-output.txt`

The assertion log is copied beside this file for durable review. Synthetic data only was used.

Direct cloud-browser navigation to the implementation container's `127.0.0.1` returned `net::ERR_BLOCKED_BY_CLIENT`, and a local Playwright browser download timed out against `cdn.playwright.dev`. The real-browser run therefore executed on the repository's GitHub-hosted Ubuntu runner, where Playwright launched Headless Chrome 151.0.7922.34 against the actual loopback Python service and scheduler. Backend/HTTP checks were also run directly in the implementation environment; no browser success is inferred from those checks.
