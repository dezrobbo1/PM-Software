# Phase 0 Amendment `phase0-0.1.2` — Follow-up Review Corrections

Date: 16 August 2026  
Source: follow-up Codex review of PR #1  
Reviewed commit: `166c6577b751454b425f9d63cb40e3fc17db7156`

## Evidence state before amendment

No CPM kernel, optimiser, native application comparison, practitioner evaluation or buyer test had been executed. The 50 fixture inputs and declared expected outputs were not changed in response to observed benchmark results.

## Accepted findings

All nine follow-up findings were accepted:

1. non-executed records could retain a canonical input hash;
2. scenario-state assignments could reference unknown resources;
3. feasible counterfactuals could omit validated output and objective evidence;
4. declared date-time formats were not actively checked;
5. objective validation checked aggregation keys rather than exact frozen values and ordering;
6. baseline and approved-forecast fields could carry the wrong schedule-state type;
7. a passing execution could claim both feasibility and proven infeasibility;
8. frozen activities could omit the coordinates that must remain fixed;
9. required experiment registers could be deleted without failing validation.

## Corrections

- Tightened execution-record status and feasibility/optimality conditions.
- Added context-specific state-type constraints.
- Added scenario-state assignment, state-coordinate and frozen-coordinate checks.
- Added status-dependent counterfactual evidence rules.
- Enabled RFC 3339 date-time checking through `FormatChecker` and pinned `rfc3339-validator==0.1.4` because `jsonschema` treats format validation as an optional dependency in a clean environment.
- Replaced key-presence objective validation with exact frozen-value and level-order validation.
- Required the complete register filename set.
- Added nine negative tests and advanced execution/explanation schema revision to `0.1.2`.

## Outcome classification

- Existing valid fixtures: unchanged.
- Existing expected results: unchanged.
- Reference semantic profile: unchanged.
- Objective policy: unchanged at executable `objective-v0.2`; validation is stricter.
- Phase 0 package version: advanced from 0.1.1 to 0.1.2.
