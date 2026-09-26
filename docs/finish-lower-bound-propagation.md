# Exact controlling-finish lower-bound propagation V0

This is a diagnostic follow-up to PR #45, which rejected a larger factored
anonymous-group model and a costlier complete bounded-feasibility finish search.
The current enumerated compiler, CP-SAT finish minimisation, canonical batching,
policy, plan identity, accepted history, physical validation and admission bounds
remain authoritative and unchanged.

## Questions and contract

The 64-declared/48-active anchor has exact controlling finish **F=19**. Is the
finish minimiser expensive because its lower bound remains weak after it finds an
incumbent? Each sample starts with a fresh copy of the **same** 5,626-placement,
5,832-variable, 3,860-constraint objective-free production model. Its text proto
SHA-256 in OR-Tools 9.15.6755 is
`02828dd59cfd718abf1f4ff2f612094ed05f8fcde6a4d688ce16b895eeb07ea7`.
The JSON also records the complete source-input hash for each fixture.
The injected diagnostic adds precisely one `finish >= L` constraint, then proves
the unchanged finish objective OPTIMAL. Selected methods are separately fixed in
the same union model; the selected-network control is explicitly a pruned model.

`best_objective_bound`, incumbent, deterministic time, branches, conflicts and
both propagation counters come from `CpSolver.response_proto`. A diagnostic
UNKNOWN/FEASIBLE result cannot become an authoritative schedule. Wall readings
are observations, not deterministic proof measures. The installed solver offers
end-of-solve bound snapshots here; no sampled callback or parsed log certifies
when within a run an incumbent was found.

## Admissible bounds

All four bounds are integer ticks and are computed without knowing F or the
selected production method. They minimise over **every** authorised method
selection, materialising package arcs without solving the joint scheduler.

| Bound | Calculation | Why it cannot exceed the true optimum |
| --- | --- | --- |
| LB0 | Objective not-before plus its least declared processing ticks | Every feasible objective execution needs at least that much work after not-before. |
| LB1 | Earliest finish through each selected network's FS arcs, not-before constraints and fastest modes; minimum across structures | Removes calendars and every shared physical/workface conflict. |
| LB2 | LB1's network traversal, but each mode must find its earliest productive periods on its own working calendar with its declared continuity | Still ignores named/group availability, contention, workface exclusion and deadlines. |
| LB3 | Earliest finish after predecessor lower-bound completion from the production compiler's local placements for each mode; minimum across structures | Uses real individual calendars, locally eligible whole-activity assignments, accepted availability and latest-finish filtering; drops *only cross-activity* resource and workface conflict. |

For LB1–LB3, an earlier local completion never worsens any FS successor; taking
the minimum over modes and structures relaxes the original joint feasibility
problem. A structure without a locally feasible chain contributes no candidate.
The selected-network and method-fixed bounds use solution knowledge only for
their *diagnostic controls*, never for a deployable full-model bound. LB3 is an
exact relaxation lower bound, **not** a physically executable schedule. It uses
existing generated placement domains and does not construct a second CP-SAT
scheduler or anonymous resource witnesses.

## First retained same-environment observation

| Control | F | LB0 | LB1 | LB2 | LB3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 64/48 full | 19 | 0 | 19 | 19 | 19 |
| Same-union selected methods fixed | 19 | 0 | 19 | 19 | 19 |
| Pruned selected network | 19 | 0 | 19 | 19 | 19 |
| Small named-resource fixture | 30 | 0 | 27 | 28 | 28 |
| Workface, suspension, latest finish, inactive alternative | 7 | 0 | 4 | 6 | 6 |
| Anonymous whole-activity group witness stress | 5 | 0 | 3 | 3 | 3 |

The 64/48 LB0–LB3 derivations took approximately 0.019, 10.9, 10.8 and
16.4 ms respectively in the first retained run; all used **zero solver time**
for derivation. These are marginal calculations after the placement domains
are compiled. The JSON separately records the shared domain-compilation wall
cost, every fresh proof-model compile, the incremental derivation-plus-proof
cost, and a conservative total including both compilations. Thus LB3's
placement-generation cost is not hidden. The respective gaps to F are
19, 0, 0, 0 ticks. Their injected
finish proofs all took 5.478313 deterministic seconds, equal to no injected
bound. A perfect oracle bound `finish >= F` also took 5.478313. Thus even a
cheap deployable exact LB1 did not change the solver's deterministic work here;
its derivation still adds wall time. Approximate first-run baseline wall finish
proof was 3.75 s; wall readings vary by runner.

The objective-budget ladder used 0.001, 0.01, 0.1, 0.5, 2, 6, 20, 60
deterministic-second limits on fresh identical base models. Through budget 2,
all returned UNKNOWN without an incumbent and reported bound 0. Budget 6
completed OPTIMAL with incumbent 19 and best bound 19 after 5.478313
deterministic seconds (7,937 branches; 6 conflicts). The endpoint samples
cannot say whether the incumbent preceded the final bound *within* that last
run. Do not infer a long incumbent-before-bound gap from them.

The known-bound injection ladder `0,11,15,17,18,19` returned OPTIMAL F=19
for every bound and the same 5.478313 deterministic seconds each time.
Methods-fixed and selected-network objective proofs measured 3.458 and 3.756
deterministic seconds, respectively; their LB1–LB3 also equal 19 and injection
did not reduce those proof costs. This shows a structural decision effect but
does not establish that structural *lower-bound weakness* caused it.

The retained low-density activity ladder has F=8/16/32/48/64 at exactly
8/16/32/48/64 placements; all four bounds equal F. The fixed-eight-activity
density ladder has 129/513/1,537/3,841 placements and F=1; LB0=0 and
LB1–LB3=1 throughout. Baseline and bound-injected proof counters, derivation
costs and the sum of derivation plus solve wall time are in the JSON artifact.
No wall-speed requirement is a correctness test.

The classifier still rejects the faithful 160/120 source at the 64-declared
admission guard. Its counts remain 64,068 raw and 64,032 latest-finish eligible
placements versus the unchanged 20,000 cap. The 160/120 source is not solved.

## Exit decision

**E — lower bounds do not explain the objective cost on this anchor.** The
full-model LB1 is already exact, yet injecting even the oracle F lower bound
leaves deterministic finish-proof effort unchanged. The diagnostic budget
snapshots do not establish an incumbent-before-bound bottleneck. This result
rules out adopting LB0–LB3 as finish acceleration from this evidence; it does
not explain every internal CP-SAT search decision or imply that exact bounds
never help other projects. A separately authorised next investigation could
inspect the existing finish objective/model formulation and CP-SAT presolve and
search behaviour under exact controls. This PR implements no such change.

The separately authorised follow-up is documented in
[exact finish objective and LB-seeded search](finish-objective-search-formulation.md).
