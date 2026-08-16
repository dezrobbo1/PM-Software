# Phase 0 Completion Record

## Decision

The experiment-design pass is complete and frozen as version `phase0-0.1.2`. This patch incorporates initial and follow-up review corrections before any scheduling or optimisation results existed.

## What has been executed

- The bounded prototype scope has been fixed.
- Reference semantics have been declared separately from future P6 and Microsoft Project compatibility profiles.
- The canonical model and four JSON Schemas have been created and meta-validated.
- A deterministic execution identity and hash contract has been fixed.
- A transparent, fully specified lexicographic objective policy has been fixed as a benchmark policy only.
- The comparator protocol requires default native levelling, expert-configured native levelling, an experienced planner, the optimiser, and planner-reviewed optimiser output.
- Fifty semantic micro-test schedules have been created with declared reference expectations or native-validation properties.
- Empty registers have been created for benchmark runs, semantic discrepancies, native round-trip loss, input economics, evidence and contradictions.
- Twenty-one negative guard tests cover the accepted review failure modes.
- The tracked protocol bundle, consolidated document and SHA-256 manifest have been validated.

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
