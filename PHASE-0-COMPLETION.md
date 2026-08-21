# Phase 0 Completion Record

## Decision

The experiment-design pass is complete and frozen as version `phase0-0.1.4`. This patch incorporates all review corrections received before Phase 1 before any scheduling or optimisation results existed.

## What has been executed

- The bounded prototype scope has been fixed.
- Reference semantics have been declared as active `reference-v0.3`, separately from future P6 and Microsoft Project compatibility profiles; historical `reference-v0.1` and `reference-v0.2` are retained for auditability.
- The canonical model and four JSON Schemas have been created and meta-validated.
- A deterministic execution identity and hash contract has been fixed.
- A transparent, fully specified case-dependent lexicographic objective policy has been fixed as `objective-v0.3`, as a benchmark policy only.
- The comparator protocol requires default native levelling, expert-configured native levelling, an experienced planner, the optimiser, and planner-reviewed optimiser output.
- Fifty semantic micro-test schedules have been created with declared reference expectations or native-validation properties.
- Declared relationship formulas are independently checked across all four relationship types with signed successor-calendar lag.
- All 49 declared fixture coordinate sets are independently recomputed and must match productive duration, supported lower bounds, actual/status policy and canonical earliest placement exactly.
- Exclusive-resource feasibility, DET-049/050 objective-selected ordering, restricted float and curated governing-relationship assertions are independently checked.
- Complete objective-vector values are recomputed from complete feasible selected states for proposed, execution and counterfactual evidence; missing output-state evidence fails closed.
- The exact 50 case identities and filenames are frozen; supplied approved forecasts must cover every activity.
- Alternate lag-calendar and cumulative-capacity semantics remain preserved-only until direct fixtures exist, and infeasible proofs cannot publish selected-scenario or objective evidence.
- Empty registers have been created for benchmark runs, semantic discrepancies, native round-trip loss, input economics, evidence and contradictions.
- Sixty-seven negative and positive guard tests cover the accepted review failure modes and preserved valid states.
- The tracked protocol bundle, exact chapter/catalogue/register sets, consolidated document and SHA-256 manifest have been validated.

## What has deliberately not been executed

- No CPM engine has been implemented.
- No OR-Tools or other optimisation model has been implemented.
- No P6 or Microsoft Project binaries have been run.
- No real or anonymised professional schedule has been benchmarked.
- No practitioner blind comparison has occurred.
- No buyer validation has occurred.

## Entry condition for Phase 1

Phase 1 begins only after PR review is complete and both commands pass from a clean checkout:

```bash
python -m unittest discover -s tests -v
python tools/validate_phase0.py
```

Amendments must continue to follow `docs/10-change-control.md` before results are generated.
