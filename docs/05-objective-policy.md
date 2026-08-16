# Benchmark Objective Policy `objective-v0.1`

This is a transparent experimental policy. It is not a validated universal planner preference.

## Lexicographic levels

1. Zero hard safety, temporal, calendar, resource and operational violations.
2. Minimise mandatory milestone lateness. Milestones are evaluated in descending `milestone_priority`; lateness at a higher priority is minimised before lateness at a lower priority.
3. Minimise project completion time.
4. Minimise movement from the approved forecast.
5. Minimise overtime, mobilisation events and resource peaks.
6. Minimise crew and workface continuity interruptions.
7. Resolve any remaining equality using stable ascending activity IDs and stable mode/resource IDs.

A lower level cannot improve at the expense of a higher level.

## Objective vector

The canonical vector is:

```text
[
  hard_violation_count,
  mandatory_milestone_lateness_by_descending_priority,
  project_finish,
  approved_forecast_movement,
  overtime_mobilisation_peak_penalty,
  continuity_interruption_penalty,
  canonical_tie_rank
]
```

Each element is an integer in the declared time/cost unit. No opaque weighted total is used for the initial benchmark.

## Required scenario comparison

For every candidate scenario, retain the full vector and separate metrics. Do not collapse quality, runtime, stability, modelling effort and practitioner acceptance into one composite score.

## Change control

Any change to level order, metric definition or tie-break creates a new objective-policy version and a new execution identity. It cannot be changed retroactively after benchmark outputs are inspected.
