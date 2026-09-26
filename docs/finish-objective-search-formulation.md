# Exact finish objective and lower-bound-seeded search (experimental)

PR #46 found a solver-independent admissible LB1 of 19 on the retained 64/48
source, equal to its independently controlled production optimum F=19. Adding
`finish >= 19` to CP-SAT minimisation left the objective proof at 5.478313
deterministic seconds. This experiment tests objective representation and a
*different use* of the bound, while leaving production unchanged.

## Identical R0 base and exact policy

All controls compile the same objective-free production R0 model and verify
its text-proto SHA-256, source input hash, counts and variable domain **before**
adding an objective or bound. In the retained 64/48 environment this is 64
declared activities, 16 structures, 5,626 placements, 5,832 variables, 3,860
constraints, zero workface intervals and objective end domain `[0,64]`.
Every SAT question clones this objective-free model and adds exactly one
`finish <= B` constraint. No query inherits a previous bound. After exact F is
proven, a **fresh** compilation fixes finish to F, proves global timing, proves
every existing mixed-radix canonical block, extracts the plan, and invokes the
existing independent `validate_plan` and physical checks. Tests compare the
complete semantic projection, every policy digit and physical witness against
production. No experimental module is imported by production.

C1 minimises the existing objective end variable. The unchanged compiler
imposes `end == sum(placement.finish * placement_literal)` on the objective
activity and exactly one active literal. C2 minimises that latter expression
directly, leaving the end variable and all original constraints in place. A
counterexample test adds `end != expression` to the complete small base model
and proves it infeasible. C2 adds zero feasibility constraints. The optional
alias and variable-domain controls were omitted: an alias is redundant, and
changing the native domain requires rewriting the production compiler for a
diagnostic with no demonstrated need.

## Exact S2 search

The pre-existing LB1/LB2/LB3 derivations are used unchanged; they never use F.
For any mathematically admissible lower bound L, first ask `finish <= L`.
SAT immediately proves F=L. If UNSAT, query L+1, L+2, L+4, ... (capped by
the declared horizon) until SAT, then binary search between the last UNSAT
and first SAT bounds. At termination the trace contains SAT at F and UNSAT
at F-1, or the first SAT at the proven admissible bound L. Any UNKNOWN or
unproved optimisation status aborts. OR-Tools 9.15 reports `OPTIMAL` for a
completed objective-free satisfiability solve; the trace labels this SAT,
**not** an objective optimality proof. The subsequent full policy is proven
OPTIMAL using production's unchanged timing and canonical stages. C1/S2 and
C2/S2 use the same feasibility bound on the linked end variable; hence those
S2 cells are an intentional duplicate search control, not independent
formulation effects.

## Retained same-environment observations

The complete source-bound JSON includes all exact query traces, per-stage
statistics, wall observations, runtime, SHA and source/plan identities. Values
below are illustrative measurements from one Python 3.12 / OR-Tools 9.15 run,
not performance guarantees. `det` denotes cumulative solver deterministic
seconds; wall time includes compilation, Python bound derivation, cloning and
full policy completion.

| 64/48 cell | Finish proof/query det | Complete policy det | Queries / solver calls | Semantic result |
| --- | ---: | ---: | ---: | --- |
| C1/S0 current end objective | 5.47831 | 5.68881 | 1 / 11 | F=19, exact |
| C2/S0 direct placement expression | 5.47831 | 5.68881 | 1 / 11 | F=19, exact |
| C1/S2-LB1 | 0.06846 | 0.27896 | 1 / 11 | F=19, exact |
| C1/S2-LB2 | 0.06846 | 0.27896 | 1 / 11 | F=19, exact |
| C1/S2-LB3 | 0.06846 | 0.27896 | 1 / 11 | F=19, exact |
| C2/S2-LB1 | 0.06846 | 0.27896 | 1 / 11 | F=19, exact |

The historical PR #45 0..horizon S1 implementation, rerun without alteration
in this environment, required seven queries and approximately 9.229 solver
deterministic seconds for its unknown-optimum search (full trace in JSON).
S2-LB1 instead hits exact F with a single query. In this local
run C1/S0 end-to-end was approximately 6.2 s and C1/S2-LB1 approximately
2.8 s; compile and policy proof still cost time, so the deterministic finish
ratio is not the end-to-end ratio.

OR-Tools' public solution callback first observed an incumbent of 19 at
approximately 4.005 deterministic seconds on C1/S0; the final proof completed
at 5.478 deterministic seconds with best bound 19. The public bound callback
observed 0 and then 19 near the first incumbent. Callback wall timestamps
are observations, not exact proof timing, and neither callback replaces final
`OPTIMAL` certification. They give no evidence of a long-lived incumbent at
19 with a weak lower bound. Finish callbacks are detached before subsequent
policy stages. Response-proto branches, conflicts, propagations and solver
wall time are retained per proof in the JSON.

## Non-exact bounds and controlled ladders

| Control | F | LB1 / query sequence | LB2, LB3 / query sequence | S0 / S2-LB1 finish det |
| --- | ---: | --- | --- | ---: |
| Small named eligibility | 30 | 27: 27−, 28−, 29−, 31+, 30+ | 28: 28−, 29−, 30+ | 0.44538 / 0.00618 |
| Workface, suspension, protected finish | 7 | 4: 4−, 5−, 6−, 8+, 7+ | 6: 6−, 7+ | 0.00039 / 0.00068 |
| Anonymous whole-activity group stress | 5 | 3: 3−, 4−, 5+ | 3: 3−, 4−, 5+ | 0.00014 / 0.00005 |
| Suspended workface without deadline | 7 | 4: 4−, 5−, 6−, 8+, 7+ | 6: 6−, 7+ | 0.00217 / 0.00443 |

`+` is completed SAT; `−` is completed INFEASIBLE. S2 can be slower on small
professional models, especially where LB1 is below F, and entails multiple
model clones. S2's total cost also includes unchanged bound derivation and a
fresh policy compilation. The JSON retains all derivation and clone wall costs
rather than hiding them in finish proof time. On the activity ladder (8, 16,
32, 48, 64), one placement per activity and LB1=F for every row; both S0 and
S2 proofs are effectively solved in presolve. On the fixed-eight-activity
density ladder, 129/513/1,537/3,841 placements with F=LB1=1, S0 finish
proof ranges approximately 0.00007 to 0.02938 deterministic seconds and S2
one-query proof 0.00002 to 0.00062. These are controlled observations, not a
universal scaling curve.

The exact production plan hashes on verified merged main and the final head
are the frozen small `458a5927a645fb2eed8a8ac432c0262d2bfcf23d3ae222a4e9f32d4682569ab5`,
professional `61add1ea57ede769cb676aa11f93b31eb5696f8f691b22b22a38b9f146172a7d`,
and 64/48 `88f125d76b5cdbe4f18e14834767e964e5b29f2db21a2c839481e1399e21f63f`.
The independent fixed-network policy control agrees with F=19. The professional
160/120 classifier still stops at 64 declared activities, with 64,068 raw
placements and 64,032 deadline-eligible against the unchanged 20,000 cap.
It is not scheduled here.

## Classification and next question

**A — LB-seeded exact search justified in these admitted controls.** It
reproduces the full policy on exact and non-exact bound cases and markedly
reduces deterministic finish proof on the important 64/48 anchor, without a
material large-case regression among retained controls. Small professional
cases show modest absolute overhead and warrant further adoption checks. The
algebraically equivalent C2 objective supplies no improvement on the anchor;
changing the objective expression alone is not justified. Next, a separate
production-adoption proof should test S2's end-to-end behavior, failure
handling and truthful proof metadata across historical plans and recovery
before making it authoritative. **This experiment adopts nothing:** no new
objective, search strategy, scale bound, resource semantics, plan hash or
accepted-history/lineage behavior enters production.
