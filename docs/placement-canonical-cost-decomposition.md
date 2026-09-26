# Placement generation and canonical proof cost decomposition v0

## Experiment question and boundary

This experiment asks where the next observed cost lies in the converged
Work-Method/productive-time scheduler: input/model construction, repeated
canonical optimality proofs, or their interaction. It measures the existing
sequential policy as the authoritative oracle and compares one bounded exact
challenger.

The experiment does not change the production scheduler or any retained bound.
The limits remain 64 declared activities, 16 authorised structures, 20,000
placement alternatives, 20,000 workface intervals, a 480-tick horizon and 60.0
deterministic-time units per solver stage. The 160/120 professional case remains
classification-only.

The authoritative order remains:

1. controlling finish;
2. weighted global start timing;
3. declared Work-Package method index, package by package;
4. declared activity-mode index, activity by activity;
5. declared placement index, activity by activity.

Each authoritative stage still proves `OPTIMAL` and fixes its value before the
next stage. `schedule_work_method_time(...)`, its plan schema, policy string,
hash and persisted plan representation are unchanged.

## Instrumentation

Instrumentation is additive `WorkMethodTimeResult.metrics` data outside the
persisted plan.

| Metric | Meaning |
|---|---|
| `input_copy_ms` | defensive input copy before validation |
| `validation_ms` | native/admission validation, including materialised structural projections |
| `productive_case_compile_ms` | compilation of the activity-mode productive cases |
| `placement_generation_ms` | productive placement enumeration, ordering and latest-finish filtering |
| `cp_model_assembly_ms` | remaining base CP-SAT variable and constraint assembly |
| `base_variables`, `base_constraints` | base model size before objective-fixing constraints |
| `stage_metrics` | name, type, status, value, maximum, wall observation, solver wall time, deterministic-time counter and cumulative counters for every proof |
| `result_extraction_ms` | conversion of the selected candidate to the existing plan document |
| `independent_allocation_ms` | independent physical allocation check immediately after solving |
| `stored_plan_validation_ms` | complete no-solve `validate_plan(...)` pass |
| `end_to_end_ms` | observed full call time |

Wall-clock values are noisy observations. The OR-Tools deterministic-time value
is a solver proof counter and is not milliseconds. Both are retained because
they answer different questions.

## Controlled fixture matrix

| Family | Cases | Controlled variable |
|---|---|---|
| Existing anchor | 13 declared / 11 active Work-Method integration | small known composition and plan-hash control |
| Professional semantics anchor | 10 declared / 8 active | active workface exclusion, hard latest finish and an inactive constrained alternative |
| Admitted scale anchor | 64 declared / 48 active | retained 5,626-placement converged scale case and 138-stage oracle |
| Activity/stage ladder | 8, 16, 32, 48, 64 active | one legal placement per activity; activity count, base model and canonical stage count grow together |
| Fixed-model proof-prefix ladder | one 64-activity / 64-placement model | base variables and constraints remain fixed while 18, 34, 66, 98 or 130 sequential stages are proved |
| Placement ladder | horizon 16, 64, 192, 480 with 8 active | 18 authoritative stages stay fixed while placements grow from 129 to 3,841 |

The ladders are diagnostic controls, not production benchmarks. They remain
within all retained bounds. Only the final fixed-model prefix row proves the
complete policy; shorter rows measure proof cost and do not produce candidate
plans.

## Exact batching challenger

The challenger leaves finish and global timing as separate higher-order proofs.
Only the adjacent method, mode and placement digits are batched. The two global
objectives are solved and fixed on the unchanged base model before the batching
variables are added.

For a block with ordered digits `d[i]`, known maxima `M[i]` and radices
`R[i] = M[i] + 1`, the coefficient is:

\[
C_i = \prod_{j > i} R_j
\]

and the block objective is:

\[
E = \sum_i d_i C_i.
\]

The maximum contribution of every digit below `i` is `C[i] - 1`. One increment
of `d[i]` therefore dominates every possible lower-order suffix. Minimising `E`
is exactly the same lexicographic order for all vectors in the declared bounded
domain, including the zero value contributed by an inactive alternative.

Blocks are constructed greedily in declared order. A digit closes the current
block before the complete mixed-radix domain would exceed `2^60 - 1`. This gives
headroom below CP-SAT's signed 64-bit integer limit. A single digit above the
bound is rejected. The artifact records every digit, maximum, coefficient,
block membership and maximum possible block value; no saturation is allowed.

This paragraph describes the historical PR #42 experiment. Subsequently the
same block mathematics moved to `scheduling/canonical_batching.py`, and the
authoritative scheduler adopted it. The experiment now compares authoritative
batching against the retained sequential oracle; see
[the adoption evidence](authoritative-canonical-batching.md).

## Representative observed results

The table below is one same-environment Linux development run using Python
3.12.14 and OR-Tools 9.15.6755. The dedicated workflow artifact contains the
complete exact-head observations; these numbers are not cross-environment
performance promises.

| Case | Placements | Sequential stages | Sequential solve ms | Challenger stages | Challenger solve ms | Solve ratio | End-to-end ratio |
|---|---:|---:|---:|---:|---:|---:|---:|
| Small existing | 972 | 32 | 808.50 | 4 | 437.44 | 1.85x | 1.89x |
| Professional semantics | 59 | 27 | 56.07 | 3 | 10.47 | 5.35x | 3.55x |
| Converged 64/48 | 5,626 | 138 | 19,071.53 | 11 | 4,821.47 | 3.96x | 3.89x |
| Stage 8 | 8 | 18 | 7.55 | 3 | 1.38 | 5.47x | 2.67x |
| Stage 16 | 16 | 34 | 18.68 | 3 | 1.90 | 9.84x | 3.23x |
| Stage 32 | 32 | 66 | 56.01 | 4 | 4.00 | 14.02x | 1.58x |
| Stage 48 | 48 | 98 | 101.39 | 4 | 4.90 | 20.68x | 4.71x |
| Stage 64 | 64 | 130 | 198.82 | 5 | 9.16 | 21.71x | 5.75x |
| Density 16 | 129 | 18 | 20.65 | 3 | 4.00 | 5.16x | 3.19x |
| Density 64 | 513 | 18 | 43.62 | 3 | 16.64 | 2.62x | 2.21x |
| Density 192 | 1,537 | 18 | 111.23 | 4 | 63.15 | 1.76x | 1.64x |
| Density 480 | 3,841 | 18 | 499.22 | 4 | 321.57 | 1.55x | 1.52x |

The additional fixed-model prefix control held 64 activities, 64 placements,
257 variables and 319 base constraints constant:

| Canonical stages proved | Total stages | Observed solve ms |
|---:|---:|---:|
| 16 | 18 | 26.93 |
| 32 | 34 | 68.45 |
| 64 | 66 | 83.06 |
| 96 | 98 | 139.34 |
| 128 | 130 | 180.81 |

For the 64/48 anchor, pre-solve construction was 123.97 ms:

| Pre/post phase | Observed ms |
|---|---:|
| Input copy | 0.78 |
| Validation/admission | 16.52 |
| Productive mode-case compilation | 17.14 |
| Placement generation | 16.59 |
| Remaining CP model assembly | 72.94 |
| Result extraction | 7.19 |
| Independent allocation | 0.74 |
| Complete stored-plan validation | 19.47 |

The base model had 5,832 variables and 3,860 constraints. Sequential solving was
98.97% of the observed 19,270.60 ms end-to-end time.

| Sequential stage type | Proofs | Wall ms | Deterministic time |
|---|---:|---:|---:|
| Finish | 1 | 3,730.61 | 5.478313350 |
| Global timing | 1 | 292.77 | 0.089326106 |
| Method canonical | 8 | 1,725.12 | 0.331480346 |
| Mode canonical | 64 | 8,502.36 | 0.952896590 |
| Placement canonical | 64 | 4,820.67 | 0.269341445 |

The 136 lower-order digits became nine safe blocks of 62, 17, 9, 9, 9, 9, 9,
9 and 3 digits. Finish and global timing used the same deterministic proof
counters in both paths because batching is assembled afterward. The nine block
proofs took 971.42 ms and 0.121168033 deterministic-time units in this run.

## Exactness and adversarial evidence

All 12 matrix cases matched on:

- selected methods;
- selected modes;
- every canonical-vector digit;
- controlling finish and global timing objective;
- every entry's activity, mode, start, finish, productive periods, named assignments and group demands;
- allocation witness and independent physical status;
- the semantic plan after excluding only challenger solver metadata and its derived hash;
- repeated challenger output;
- unchanged source input.

The existing small and professional authoritative plan hashes stayed exactly
`3d8409958ca0b0248d78aad631ce4e0ded7f6c6a5af15ee5c6a108121fcdc7d0` and
`dea09dd2458b901faa1410c343827cc7bfd0f140ad059b1b87a47381575518bd`.
Targeted tests also retain the workface through the non-productive `[2,4)` gap,
enforce the active `latest_finish`, ignore the inactive alternative's impossible
deadline/workface occupancy, reject unsafe radix expansion, validate stored plans
without solving and retain the 64-activity admission guard.

## Answers and exit classification

**Q1 — before the first solve:** construction is measurable and grows with the
placement set, but it was secondary on the 64/48 anchor: 123.97 ms build versus
19,071.53 ms in solver calls.

**Q2 — stage cost:** the two global proofs remain material, particularly finish.
The 136 lower canonical proofs contributed 78.90% of sequential solve wall time
on 64/48. Mode and placement proofs were the largest aggregates.

**Q3 — scaling driver:** both axes matter. On the fixed 64-activity model, 18 to
130 prefix stages increased observed proof time from 26.93 to 180.81 ms. At a
fixed 18 complete-policy stages, 129 to 3,841 placements increased it from 20.65
to 499.22 ms. The separate activity ladder shows their natural combined growth,
not a pure stage-only effect. The real anchor therefore contains an interaction:
more proofs, each over a larger model. Raw placement generation itself was only
16.59 ms there.

**Q4 — safe adjacent decisions:** yes for this bounded vector. Mixed-radix blocks
preserved declared lexicographic order without approaching the conservative
integer limit.

**Q5 — benefit:** yes on every retained case. The 64/48 challenger reduced calls
from 138 to 11 and observed end-to-end time by 3.89x while matching the complete
policy and semantic plan exactly.

The machine-readable classifier derives the result from direct comparisons on
the 64/48 anchor: solve cost exceeds build cost, lower canonical proofs exceed
the two global proofs, safe blocks reduce lower canonical cost, and the challenger
reduces calls, solve wall time and end-to-end wall time. It uses no fixed speedup
threshold. A correctness mismatch would instead produce E; a run contradicting
the measured challenger benefit cannot produce A.

**Classification: A — canonical-proof dominated, with a material model-size
interaction.** The evidence supports a next milestone to prove and adopt the
bounded exact batching strategy in the authoritative path. That adoption should
retain the sequential oracle as a control and should measure whether the larger
model still makes finish/global proofs or block proofs the next cost. Placement
representation can be revisited after that evidence.

## Professional follow-up and exclusions

The 160/120 classifier remains unchanged: faithful professional semantics are
accepted, authoritative scheduling stops at the 64-activity admission guard,
raw placements remain 64,068, latest-finish filtering retains 64,032 and the
production placement cap remains 20,000. This experiment does not schedule that
case or weaken its resource, workface, deadline or physical validation rules.

No activity, placement, workface, horizon or deterministic-time limit changed.
No plan/workspace/history schema, accepted-history rule, objective order, solver
backend, UI or generic decomposition framework was added. The wall observations
do not establish production scalability.

Run the retained experiment once with:

```bash
CANONICAL_COST_EVIDENCE_OUTPUT=/tmp/canonical-cost/results.json \
  python -m unittest tests.test_canonical_cost_experiment -v
```
