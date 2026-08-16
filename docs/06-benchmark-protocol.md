# Benchmark Protocol

## Research question

Can the bounded core reproduce its declared semantics and, after that, materially improve selected resource-constrained and operationally constrained schedules compared with serious native and human baselines?

## Benchmark stages

### Stage 1 — Semantic micro-tests

- Corpus: 50 fixtures in `benchmarks/semantic/cases`
- Scale: 1–6 activities
- Purpose: exact reference semantics and native comparison preparation
- Pass: zero unexplained differences inside any claimed profile

### Stage 2 — Algorithm sanity

- Corpus: PSPLIB J30, J60, J90 and J120
- Purpose: verify solver modelling and known objective values where available
- Limitation: no professional-scale or native-semantic conclusion may be drawn

### Stage 3 — Synthetic professional RCPSP

- Scale: 100–2,000 activities
- Include: several resources, calendars, priorities, frozen horizon and perturbations
- Comparators: unlevelled, default native, expert native, planner, optimiser, optimiser plus planner

### Stage 4 — Rich operational constraints

- Scale: 100–2,000 activities
- Include: named crews/equipment, skills, workfaces, permit windows, SIMOPS, modes and mobilisation
- Charge the optimiser for all data preparation and maintenance effort

### Stage 5 — Real anonymised schedules

- Initial: at least three schedules of roughly 500–2,000 activities
- Expansion: 5,000–10,000 only after earlier gates pass
- Enterprise stress: 25,000–50,000 only through a separately approved scale/decomposition protocol

### Stage 6 — Perturbation and stability

For each case, alter one factor at a time:

- delayed activity
- remaining duration
- actual start/finish
- unavailable crew/equipment
- permit window
- emergent activity
- relationship/lag
- shift calendar
- milestone priority

Measure activities moved, movement hours, frozen-horizon changes, resource reassignment and critical-path churn.

### Stage 7 — Determinism

- repeated same-process runs
- process restart
- clean environment
- separate supported machine
- serial versus later parallel profile
- exact input/output/explanation hash comparison

### Stage 8 — Native round-trip

1. Import native schedule.
2. Canonicalise and hash.
3. Produce proposed scenario.
4. Export through controlled adapter.
5. Reopen in native application.
6. Recalculate.
7. Re-import.
8. Diff all claimed fields and dates.
9. Reject silent material difference.

## Metrics

Keep separate:

- semantic correctness
- hard violations
- project completion
- milestone lateness
- resource peaks/overload/overtime
- stability and frozen-horizon movement
- continuity and mobilisation
- model preparation and review time
- runtime, memory, bounds and gaps
- explanation completeness
- native interchange loss
- practitioner acceptance
- buyer outcome

## Result labels

- `executed_pass`
- `executed_fail`
- `executed_inconclusive`
- `not_executed`
- `not_accessible`
- `native_validation_required`
- `practitioner_validation_required`
- `buyer_validation_required`

No proposed result may be promoted to `executed_*` without saved evidence and hashes.
