# Changelog

## phase0-0.1.2 — 2026-08-16

- Addressed nine follow-up Codex findings on PR #1 before any benchmark execution.
- Nullified input hashes for non-executed result states and tightened feasibility/optimality consistency.
- Added scenario-state resource-reference, coordinate, state-type and frozen-coordinate validation.
- Required validated output and objective evidence for feasible counterfactuals.
- Enabled RFC 3339 date-time format checking and pinned `rfc3339-validator==0.1.4` so clean validation environments enforce it.
- Froze exact objective-policy values, vector encoding and ordered levels.
- Enforced the complete required register set.
- Added nine negative guard tests; the guard suite now contains 21 tests.

## phase0-0.1.1 — 2026-08-16

- Addressed all 14 Codex review findings on PR #1 before any benchmark execution.
- Made manifest generation and validation operate on the exact tracked file set.
- Expanded canonical, execution-record and structured-explanation schemas to match the written contracts.
- Added status-dependent evidence, validator, feasibility, optimality and native-round-trip rules.
- Defined exact equal-priority milestone aggregation in `objective-v0.2`.
- Added stable-ID, reference, lag-calendar, interval and complete-expected-result validation.
- Enforced zero-duration milestones and unit-capacity exclusive resources.
- Added negative regression tests, consolidated-protocol verification and GitHub Actions validation.

## phase0-0.1.0 — 2026-08-16

- Froze prototype boundary and exclusions.
- Added reference semantic contract and canonical model.
- Added deterministic and objective-policy contracts.
- Added benchmark, comparator, data-access, decision-gate and change-control protocols.
- Added 50 preregistered semantic fixtures.
- Added machine-readable schemas, blank registers, validator and manifest.
