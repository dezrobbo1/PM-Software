# Benchmark Objective Policy `objective-v0.2`

This is a transparent experimental policy. It is not a validated universal planner preference.

`objective-v0.1` is retained in `config/objective-policy-v0.1.json` as the superseded preregistration. It was not executable deterministically because “equal priority is aggregated” did not define the aggregation. No benchmark result existed when the ambiguity was corrected.

## Lexicographic levels

1. Zero hard safety, temporal, calendar, resource and operational violations.
2. Minimise mandatory milestone lateness using the exact priority-group rule below.
3. Minimise project completion time.
4. Minimise movement from the approved forecast.
5. Minimise overtime, mobilisation events and resource peaks.
6. Minimise crew and workface continuity interruptions.
7. Resolve any remaining equality using stable ascending activity IDs, then stable mode IDs, then stable resource IDs.

A lower level cannot improve at the expense of a higher level.

## Mandatory milestone definition

A mandatory milestone for this benchmark policy is an activity where:

- `kind` is `start_milestone` or `finish_milestone`;
- `milestone_priority > 0`;
- `due_time` is not null.

For each mandatory milestone `m`:

```text
lateness(m) = max(0, finish(m) - due_time(m))
```

All values are integers in the schedule's declared time unit.

## Exact priority-group aggregation

1. Group mandatory milestones by integer `milestone_priority`.
2. Evaluate groups in descending priority.
3. For one priority group, compare this tuple lexicographically:

```text
(
  sum of milestone lateness in the group,
  maximum individual milestone lateness in the group,
  individual lateness values ordered by stable ascending milestone ID
)
```

4. Advance to the next lower-priority group only when the complete tuple for the current group is equal.
5. Advance to project finish only when every priority-group tuple is equal.

This rule makes equal-priority outcomes reproducible. It does not claim that sum-first aggregation is a universal planner preference; changing it creates a new objective-policy version.

## Objective vector encoding

The canonical integer vector is flattened in this order:

```text
[
  hard_violation_count,
  for each priority group in descending order:
    group_sum_lateness,
    group_maximum_lateness,
    each individual lateness in stable ascending milestone ID order,
  project_finish,
  approved_forecast_movement,
  overtime_mobilisation_peak_penalty,
  continuity_interruption_penalty,
  canonical_tie_rank
]
```

The priority groups and stable milestone IDs used to decode the vector are part of the canonical input. No opaque weighted total is used for the initial benchmark.

## Required scenario comparison

For every candidate scenario, retain the full vector and separate metrics. Do not collapse quality, runtime, stability, modelling effort and practitioner acceptance into one composite score.

## Change control

Any change to level order, mandatory-milestone definition, aggregation, metric definition or tie-break creates a new objective-policy version and a new execution identity. It cannot be changed retroactively after benchmark outputs are inspected.
