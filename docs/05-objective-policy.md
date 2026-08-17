# Benchmark Objective Policy `objective-v0.3`

This is a transparent experimental policy. It is not a validated universal planner preference.

`objective-v0.1` and `objective-v0.2` remain in `config/` as superseded preregistrations. Version 0.1 left equal-priority milestone aggregation ambiguous. Version 0.2 fixed that ambiguity but did not completely define the mandatory-milestone predicate, the combined level-five metric or the final case-specific vector shape. No benchmark result existed when `objective-v0.3` superseded them.

## Lexicographic levels

1. Zero hard safety, temporal, calendar, resource and operational violations.
2. Minimise mandatory milestone lateness using the exact priority-group rule below.
3. Minimise project completion time.
4. Minimise movement from the approved forecast.
5. Minimise the ordered operational-resource tuple: overtime units, mobilisation blocks, then summed resource peak demand.
6. Minimise continuity interruptions.
7. Resolve remaining equality through the complete canonical scenario-decision vector.

A lower level cannot improve at the expense of a higher level.

## Mandatory milestone definition

A mandatory milestone is an activity where all of the following hold:

- `kind` is `start_milestone` or `finish_milestone`;
- `milestone_priority > 0`;
- `due_time` is not null.

A normal task does not become a mandatory milestone merely because it has a priority and due time.

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

This rule makes equal-priority outcomes reproducible. It does not claim that sum-first aggregation is a universal planner preference.

## Approved-forecast movement

For the same canonical input, objective level 4 is:

```text
sum over stable ascending activity IDs of:
  abs(proposed_start - approved_start)
  + abs(proposed_finish - approved_finish)
```

If the canonical input contains no approved forecast, the component is exactly `0`. Competing scenarios are never permitted to add or remove the approved forecast; it belongs to the immutable input snapshot.

## Exact level-five tuple

Level 5 is not a weighted composite. It is compared lexicographically as:

```text
(
  overtime_units,
  mobilisation_block_count,
  resource_peak_demand_sum
)
```

For canonical schema `0.1.3`:

- `overtime_units` is fixed at `0` because overtime availability is not yet represented. Introducing non-zero overtime creates a new canonical-model and objective-policy version.
- `mobilisation_block_count` is the sum, across stable resource IDs, of maximal contiguous or overlapping productive assignment blocks.
- `resource_peak_demand_sum` is the sum, across stable resource IDs, of each resource's maximum concurrent integer assignment demand.

This ordering means one less overtime unit is preferred before mobilisation or peak demand; one less mobilisation block is preferred before peak demand.

## Continuity component

`continuity_interruption_count` is fixed at `0` under canonical schema `0.1.3` because split execution is not yet represented. It is retained as an explicit reserved component rather than an undefined prose penalty. Enabling split work or a non-zero continuity metric requires a new canonical-model and objective-policy version.

## Canonical tie-break vector

For every activity in stable ascending activity-ID order, append:

```text
start,
finish,
mode_ordinal,
assignment demand for every resource in stable ascending resource-ID order
```

`mode_ordinal` is `0` when no mode is selected. Otherwise it is one plus the selected mode's index in stable ascending mode-ID order. Missing resource assignments encode as `0`.

This is a vector, not an opaque integer rank. Its exact length depends on the canonical input.

## Complete objective-vector encoding

The canonical integer vector is flattened in this order:

```text
[
  hard_violation_count,
  for each mandatory-milestone priority group in descending order:
    group_sum_lateness,
    group_maximum_lateness,
    each individual lateness in stable ascending milestone-ID order,
  project_finish,
  approved_forecast_movement,
  overtime_units,
  mobilisation_block_count,
  resource_peak_demand_sum,
  continuity_interruption_count,
  for each activity in stable ascending activity-ID order:
    start,
    finish,
    mode_ordinal,
    each resource demand in stable ascending resource-ID order
]
```

The Phase 0 validator derives the required vector layout from the canonical schedule and rejects incomplete or surplus entries. A fixed seven-entry vector is invalid because levels 2 and 7 are deliberately case-specific vectors.

## Required scenario comparison

For every candidate scenario, retain the full vector and separate metrics. Do not collapse quality, runtime, stability, modelling effort and practitioner acceptance into one composite score.

## Change control

Any change to level order, mandatory-milestone definition, aggregation, metric definition, reserved-component behaviour or tie-break creates a new objective-policy version and a new execution identity. It cannot be changed retroactively after benchmark outputs are inspected.
