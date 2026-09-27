# Authoritative LB1-seeded exact finish (bounded v0)

This adoption follows the *historical* objective experiment in
[PR #47](finish-objective-search-formulation.md). Directly minimising the
algebraically equivalent placement-finish expression did not improve the
64/48 finish proof. The admissible, inexpensive precedence-only LB1 did equal
its finish of 19. A SAT question at that bound proved the exact finish with
much less deterministic solver work than objective minimisation in that
environment. This adoption changes only the proof of the first policy tier;
the rest remains controlling finish → weighted global start timing → methods
→ modes → flattened placements. `PLAN_SCHEMA`, `POLICY`, and the plan-hash
algorithm are unchanged.

## Admissible bound and exactness

For each of the at most 16 authorised method selections, LB1 materialises
the active network. In topological predecessor order, each activity's relaxed
finish is `max(not_before, relaxed predecessor finishes) + minimum authorised
processing_ticks`. LB1 is the minimum objective finish over all structures.
Every real selected structure has the same FS logic, no earlier admissible
start and at least the minimum work. Ignoring calendars, assignment, workface,
capacity and all further physical restrictions can only move a relaxed finish
earlier. Thus LB1 ≤ every executable finish; it uses no chosen plan, F or
historical actual periods. Accepted-history recovery first compiles its
future-only problem, then derives LB1 from that problem.

The production path compiles **one** objective-free joint model. It hashes
the base proto within the environment, clones it for each bound query, adds
exactly one `finish <= B` to each clone and checks that the original remains
objective-free, same-sized and byte-identical in its text-proto hash. SAT at
LB1 proves F=LB1. Otherwise query LB1+1, +2, +4, +8, ... capped at the
admitted horizon, then bisect between the last UNSAT and first SAT. SAT at F
and UNSAT at F−1 are the certificate. The algorithm never uses the known
optimum. On the untouched original model, it then fixes finish==F and proves
global timing and existing safe mixed-radix blocks, with OPTIMAL required
for every optimization stage. No dates or resource assignments are repaired
after solving; the independent physical and stored-plan validators still run.

For a positive horizon H, the initial query, at most `ceil(log2(H))`
exponential/capped queries and at most `ceil(log2(H))−1` bisections give the
conservative cap `max(2, 1+2*ceil(log2(H)))`. At admitted H≤480 the maximum
is 19. Exhaustive pure enumeration of every `0≤LB1≤F≤480` verifies exact
termination, distinct query bounds and the 19-query cap. Exceeding the cap
is an internal error, not an opportunity to skip the proof.

All finish queries share **one 60.0 deterministic-time-unit budget**. Every
query receives only the remaining budget and its response's deterministic
time is deducted; UNKNOWN, MODEL_INVALID, exhausted/overspent budget and an
unexpected SAT witness below LB1 return **no plan**. If LB1 exceeds the
admitted horizon or even the horizon bound is UNSAT, the existing bounded
project-infeasibility error is raised. There is no S0 fallback. A completed
objective-free SAT query may have OR-Tools status OPTIMAL or FEASIBLE; its
persisted proof result is SAT, never a fabricated optimization optimum.

## Artifact identity and metrics

New plans identify `native-work-method-time-lb1-seeded/0`. Their one logical
finish proof has `PROVEN_EXACT`, the bound kind/value and ordered bound/SAT
or bound/INFEASIBLE facts. These deterministic facts affect plan_hash;
intermediate SAT witness coordinates and solver timing do not. Timing and
canonical block proofs retain truthful OPTIMAL status. New artifacts can
have the same complete schedule as older ones yet different hashes because
their proof documents genuinely differ. Old hashes are neither migrated nor
special-cased.

`policy_stage_count` counts finish + timing + canonical blocks;
`solver_calls` counts *all* finish queries + timing + blocks. The one finish
aggregate stage metric includes total finish query wall and deterministic
effort. Non-persisted `finish_query_metrics` details each actual call;
`finish_lower_bound_derivation_ms`, `finish_remaining_deterministic_budget`,
build/extraction/validation metrics and model counts expose total cost. The
retained `max_deterministic_time_per_stage` in a plan applies to the whole
logical finish stage as well as each later optimization stage.

The private `_schedule_work_method_time_batched` retains the preceding
S0 objective-minimised finish/batched canonical generation; the private
sequential oracle retains the still older per-digit proof generation. They
run only when explicitly called by tests or historical experiments. Normal
production runs neither. Frozen S0-era small, professional and 64/48 plans,
accepted reference and rolling cycle were generated at verified base main
`33e7cf32f1f64482a79d06bdf578f39cb78d3a42` **before** production edits.
They coexist with older sequential-era frozen plans. All validate unchanged
without calling a CP-SAT solver. Historical accepted status and rolling
lineage are untouched; new recoveries and promoted reference plans receive
their own truthful S2 hashes. A saved S2-era cycle reopens without scheduling.

## Source-bound evidence and exclusions

The dedicated `authoritative-lb1-seeded-finish` workflow compares complete
S2/S0 semantic plans, every canonical digit and physical status on the
small named-resource case (including LB1<F), professional workface/deadline
case, whole-activity anonymous-group stress case, 64/48, and the 8–64
activity and 129–3841 placement ladders. It retains per-query deterministic
solver counters separately from noisy wall observations and reruns the
160/120 classifier; source SHA and evidence SHA must match checked-out HEAD.
The classifier must still stop at the 64-activity admission guard, with
64,068 raw and 64,032 deadline-eligible placements above the unchanged
20,000 placement cap. This is no evidence of 160/120 schedulability or
production-scale readiness.

The adoption does **not** adopt LB2, LB3, C2, R1, generic binary search, a
fallback optimizer or a new backend. It changes no activity/structure/
placement/workface/horizon/safety bounds, accepted-history meaning, workface
envelopes, hard deadlines or canonical policy. The next question should be
chosen from exact-head measurements after compatibility and review, without
automatically raising any bound.
