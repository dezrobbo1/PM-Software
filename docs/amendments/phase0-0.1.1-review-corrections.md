# Phase 0 Amendment `phase0-0.1.1` — Review Corrections

Date: 16 August 2026  
Source: Codex review of PR #1  
Reviewed commit: `ca3ae184bc427c81943e66969f100ffff7827718`

## Evidence state before amendment

No CPM kernel, optimiser, native application comparison, practitioner evaluation or buyer test had been executed. The 50 fixture inputs and declared expected outputs were therefore not changed in response to observed benchmark results.

## Accepted findings

All 14 review findings were accepted:

1. manifest generation included repository metadata;
2. manifest validation did not detect omitted tracked files;
3. executed records could omit evidence hashes;
4. execution schema omitted fields required by the deterministic contract;
5. execution schema omitted four legitimate non-executed statuses;
6. canonical schema could not represent the documented canonical model;
7. equal-priority milestone aggregation was ambiguous;
8. explicit lag-calendar references were not resolved;
9. duplicate calendar, resource and relationship IDs were accepted;
10. invalid/overlapping/out-of-horizon working intervals were accepted;
11. declared fixtures could omit expected activity times;
12. structured explanations could omit recomputable causal/counterfactual data;
13. milestones could have positive duration;
14. exclusive resources could have capacity other than one.

## Corrections

- Added tracked-file manifest discovery with archive fallback and explicit metadata exclusions.
- Added exact manifest-set comparison, path safety and duplicate checks.
- Expanded and conditionally constrained the execution-record schema.
- Expanded the canonical schema for WBS, source hash, baseline, approved forecast, proposed scenario, modes, constraints and governance.
- Added objective policy `objective-v0.2` with an exact lexicographic milestone aggregation.
- Added cross-reference, uniqueness, interval and expected-oracle validation.
- Expanded structured explanation and counterfactual schemas.
- Added negative regression tests and GitHub Actions validation.
- Added generated consolidated-protocol consistency checking.

## Outcome classification

- Existing valid fixtures: unchanged.
- Existing expected results: unchanged.
- Reference semantic profile: unchanged.
- Objective policy: superseded from ambiguous v0.1 to executable v0.2.
- Phase 0 package version: advanced from 0.1.0 to 0.1.1.
