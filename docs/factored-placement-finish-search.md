# Experimental exact finish search and factored placement v0

## Question and controls

PR #44 measured an admitted 64-declared / 48-active controlling-finish proof. The production optimum is F=19. A separate objective-free `finish <= 18` query is infeasible in presolve, yet minimizing finish costs substantially more. This experiment independently changes (R0 → R1) the representation of *anonymous, solver-internal group witnesses* and (S0 → S1) the way the exact controlling finish is discovered. The authoritative batched scheduler, plan schema, hashing, policy, validation, accepted history and all admission bounds remain untouched.

R0 is the unchanged production compiler. S0 uses its existing minimize-finish objective, then global timing and exact canonical blocks. S1 starts from the solver-independent integer lower bound 0 and the admitted horizon as a safe upper bound. It queries feasibility at the horizon and bisects the monotone interval; every objective-free query must finish SAT (`OPTIMAL` or `FEASIBLE` for a satisfaction model) or `INFEASIBLE`. At termination it checks SAT at the discovered F and UNSAT at F−1, fixes `finish == F` in a **fresh** model, and proves the existing global timing and canonical blocks. UNKNOWN aborts the experiment. F is never supplied to S1. This search is experimental and does not modify production output.

## R1 assembly and exact placement rank

For each activity/mode R1 groups the *same already generated* current placements by `(start, finish, productive periods, named assignment)`. Distinct anonymous group unit sets become witness choices. A temporal/named choice reserves the full `[start, finish)` workface envelope and occupies its named resources over productive periods. A compatible temporal–witness conjunction occupies anonymous units during **all** productive periods. Both the temporal and witness sums select exactly one compatible pair for an active grouped mode. No group unit can be handed off between segments. Modes without an anonymous group use the temporal literal directly.

The R1 compiler deliberately reuses source validation, `_mode_cases`, and `_group_placements`; it changes only experimental model assembly. It still enumerates original placements to retain exact semantics, so it makes **no placement-generation improvement**. Its `choices` list is rebuilt in the original sorted order and uses the conjunction literal for each grouped alternative. The placement canonical digit remains `sum(flattened_rank × selected_literal)`; its rank is compared *for all 5,626 alternatives*, including internal unit-set variants. This is an exact table mapping, not an assumed constant radix. Named assignments stay with the temporal choice because their availability can differ. Anonymous IDs remain only solver-internal physical witnesses; they do not appear in public plan entries.

| Admitted 64/48 base model | R0 current | R1 factored |
| --- | ---: | ---: |
| Flattened placement/rank rows | 5,626 | 5,626 |
| Temporal/named choices | embedded | 4,024 |
| Anonymous witness choices | embedded | 52 |
| Conjunction/pair BoolVars | embedded | 3,204 |
| All BoolVars | 5,704 | 7,358 |
| All IntVars | 128 | 128 |
| All variables | 5,832 | 7,486 |
| Constraints | 3,860 | 11,948 |
| Optional intervals | 3,524 | 3,524 |
| No-overlap constraints | 7 | 7 |
| Text-proto bytes in one environment | 1,629,112 | 2,847,320 |

The 3,204 pair literals cover grouped flattened alternatives; the *excess* of flattened placements over distinct temporal patterns is 1,602. These are different counts. R1 does **not** produce a smaller CP-SAT model here. Text-proto size is a same-environment observation, not a stable serialized wire format. Build and placement-generation wall times are recorded in JSON, not treated as deterministic proof counters.

## Four-cell result

All four cells prove F=19, independently prove F feasible and F−1 infeasible, match the complete canonical vector and semantic plan, and pass the existing independent allocation and stored-plan validators. The following is a single same-environment observation; the exact-head artifact contains each stage and bound query, solver branches/conflicts/propagations, model counters and measured wall times.

| Cell | Finish search | Full policy calls | Total deterministic solve time |
| --- | --- | ---: | ---: |
| R0/S0 | Current minimize objective | 11 | 5.689 s |
| R0/S1 | Exact bounded feasibility | 17 | 9.440 s |
| R1/S0 | Current minimize objective | 11 | 5.437 s |
| R1/S1 | Exact bounded feasibility | 17 | 8.931 s |

Both S1 cells begin with the actual horizon of 64 and query bounds `64, 32, 16, 24, 20, 18, 19`. The R0/S1 bound-64 query alone uses about 7.518 deterministic seconds. Bound 18 is infeasible in presolve. One cheap F−1 query therefore cannot stand in for the *complete* unknown-optimum search. No wall-clock improvement threshold is asserted.

## Independent and professional controls

A direct Python enumerator constructs raw productive ticks from three small calendars, two anonymous units and every allowed start. With a 6-tick horizon, the three suspendable activities form a pairwise conflict cycle across different ticks. A per-tick capacity-only interpretation would accept the fixed starts A=0, B=0, C=1, but no two-colour **whole-activity** assignment exists. Both R0 and R1 prove those fixed starts infeasible. Exhaustive CP-SAT solution collection independently agrees with the raw enumerator on **all 66 feasible flattened-rank tuples** and on the complete canonical optimum; there are eight fixed-start combinations that fail the whole-activity witness rule.

The existing 13-activity Work-Method case checks multiple named-resource eligibilities. Separate small professional cases check full-envelope workface occupancy through the productive gap `[[0,2],[4,6]]`, active hard latest finish, and an inactive structural alternative with an impossible bound. Every control compares the complete R0/R1 × S0/S1 semantic plan, canonical vector, rank map, and independent physical result.

The one-placement 8/16/32/48/64 activity ladder and fixed-eight-activity 129/513/1,537/3,841 placement ladder compare S0 finish optimization with **complete** S1 bound traces. They prove identical optima and F−1 infeasibility. They are controls, not a universal complexity curve.

## Boundary and classification

Production plan hashes on verified base main remain small `458a5927a645fb2eed8a8ac432c0262d2bfcf23d3ae222a4e9f32d4682569ab5`, professional `61add1ea57ede769cb676aa11f93b31eb5696f8f691b22b22a38b9f146172a7d`, and 64/48 `88f125d76b5cdbe4f18e14834767e964e5b29f2db21a2c839481e1399e21f63f`. The 160/120 professional projection remains outside the **64-activity** admission boundary and has 64,068 raw / 64,032 deadline-eligible flattened placements against the retained 20,000 cap. A diagnostic-only factored census finds 14,880 temporal/named choices, 576 anonymous witness choices and an estimated 55,296 conjunction/pair literals **if admitted**; no R1 model is assembled or solved for 160/120.

**E — neither challenger justified on this retained anchor.** S1 makes more exact solver calls and consumes more deterministic effort. R1 reduces temporal choice count but preserves pair literals and increases variables, constraints and model text. Its modest proof variation is insufficient evidence for adopting a larger model. The next separate milestone should investigate exact objective lower-bound propagation with new controls before selecting any production search or representation change. No limit or production scheduling policy changes follow from this experiment.

The dedicated read-only-permission CI workflow retains the source SHA, runtime, focused tests, full machine-readable report and checksums. Wall times are observations; deterministic counters and exact feasibility/semantic facts are separately labeled.
