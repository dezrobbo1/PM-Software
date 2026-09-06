# Native planning browser evidence

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
