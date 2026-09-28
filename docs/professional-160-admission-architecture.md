# Professional 160/120 placement and admission architecture (diagnostic v0)

The verified baseline is merged main `8a8a2cfae650afc2a064ab7900e358917aea9817` (PR #50). That experiment closed the method/mode canonical block split as an optimisation candidate. This milestone instead asks which exact domain architecture would justify a *subsequent* professional 160/120 scheduling experiment. It performs **no 160/120 solve** and changes no production scheduler, persisted plan, validator, or admission limit. The faithful professional source still has 160 declared activities, 120 active in every one of 16 authorised structures, twelve Work Packages and four flexible packages. Its workfaces, protected latest finish, C04, MECH, ELEC and QA remain present.

## Ordered barriers and exact U0 census

Production first rejects 160 activities against the unchanged 64-activity admission. The existing production placement generator, run diagnostically without scheduling, gives 64,068 raw rows and 64,032 rows after `latest_finish`, against the unchanged 20,000-placement admission. Each activity/mode row retains its package/method, calendar/work, not-before, deadline, exclusion groups, named requirements, group demands and original per-activity flattened rank. The 36 filtered rows are only deadline-ineligible candidates.

| Professional domain | Flattened eligible | Temporal patterns | Temporal + named patterns | Internal anonymous-witness expansion | Resource optional intervals | Workface optional intervals |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| U0, current integrated union | 64,032 | 14,880 | 14,880 | 49,152 | 55,484 | 2,496 |
| U1, exact union-safe window pruning | 7,812 | 1,860 | 1,860 | 5,952 | 6,705 | 409 |

The anonymous group unit sets are solver-internal whole-activity witnesses; the table does not assign professional identities to them. No named assignment multiplication occurs in this source. U0 has 32,022 rows on activities present in all 16 structures and 32,010 rows on optional structural alternatives. These optional rows represent legitimate authorised methods. The machine-readable result includes per-mode and per-activity ownership, every selected structure and each original-rank list.

## S0 and exact W1 pruning

Each selected structure's *unpruned* current domain S0 has 120 active activities and 48,024–48,030 eligible rows. Every S0 structure exceeds 20,000. W1 starts from precisely those generated rows, including productive calendar gaps, continuity, local physical eligibility, not-before and latest finish. `materialise` provides the selected activity and package FS arcs. It iterates two **necessary** arc support rules to a fixed point:

* A successor row must start no earlier than the minimum finish of at least one currently admissible predecessor row.
* A predecessor row must finish no later than the maximum start of at least one currently admissible successor row.

Every feasible complete schedule has a supporting placement on every FS arc. Thus deletion by either rule cannot remove a placement in a feasible schedule, and repeated deletion remains safe by induction. This is a sound relaxation, **not a complete reachability algorithm for arbitrary precedence DAGs**. W1 does not consider resource contention or workface conflict. It preserves each group's existing locally valid, continuous anonymous unit set because it selects among the exact current generated placement rows.

S1 applies W1 to all 16 selected structures. The exact S0/S1 count vectors, in the generator's declared method-selection order, are:

| Domain | All 16 eligible counts | Min / median / max |
| --- | --- | --- |
| S0 | 48030, 48028, 48030, 48028, 48028, 48026, 48028, 48026, 48028, 48026, 48028, 48026, 48026, 48024, 48026, 48024 | 48024 / 48028 / 48030 |
| S1 | 6048, 5964, 6048, 5964, 5964, 5880, 5964, 5880, 5964, 5880, 5964, 5880, 5880, 5796, 5880, 5796 | 5796 / 5880 / 6048 |

U1 is **exactly the union** of rows surviving S1 in at least one structure in which their activity is active. It removes 56,220 of U0's 64,032 eligible rows (87.8% as a descriptive fraction). Since each S1 deletion is sound, U1 is safe for every authorised structure. Original one-based U0 placement ranks are retained as keys and digit maxima, with sorted rank lists and full row-identity digests in the JSON; a future implementation must not compress ranks and silently change the canonical policy. The tiny independent Python oracle exhaustively enumerates complete precedence-feasible combinations in both methods of a calendar-gap/deadline fixture and matches W1's surviving rank sets. Production-selected placements survive W1 in the small named, professional small, 64/48 and anonymous-group controls. On 64/48, the separate 64-fixed-network control independently agrees with authority **only on selected methods, selected modes, controlling finish, and global timing**; its U0/U1 row counts are 5,626/4,284. That control does not canonicalize placements or independently prove placement-rank equality. Original U0 rank identity, retained-rank mapping, production-selected placement survival, and the tiny exhaustive pruning oracle provide separate rank-preservation evidence; they are not a full independent 64/48 lexicographic placement proof.

## Model pressure and exactness boundaries

Current-compiler pressure is **mechanically derived**, not measured CP-SAT protos. Production `_canonical_block_stages` adds exactly one `IntVar` and one equality per canonical digit. This census separates the estimated pre-canonical base from those exact per-digit additions:

| Union domain | Pre-canonical estimated variables | Witness IntVars | Post-witness estimated variables | Pre-canonical estimated constraints | Witness equalities | Post-witness estimated constraints |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| U0 | 64,528 | 332 | 64,860 | 58,803 | 332 | 59,135 |
| U1 | 8,308 | 332 | 8,640 | 7,937 | 332 | 8,269 |

The same fields apply to each S0/S1 selected-structure projection: **252 digits, +252 witness IntVars, +252 witness equalities, 20 safe blocks**. All estimates exclude integrated union package-root arcs and constant variables where applicable; the post-witness estimates also exclude later stage-fixing equalities and objective state. They are not final solved-model proto counts. Workface intervals fall from 2,496 to 409. Resource optional intervals fall from 55,484 to 6,705; the JSON breaks them out by named C04 and solver-internal group category. Actual model build cost and proof performance are **unknown**. A no-solve production-style proto was not built: the production compiler enforces its 64-activity guard before assembly; constructing it would require bypassing that guard or duplicating the compiler.

Exact structural decomposition is mathematically available but untested as an implementation: solve *all* 16 authorised structures exactly under finish, weighted global timing using the **original union's declared activity indices** (inactive starts contribute zero), modes and **original** placement ranks, then choose the lexicographic minimum over (finish, timing, declared method digits, mode digits, placement digits). Reindexing active activities for timing or evaluating one preferred structure would change the policy. This experiment does not perform those solves or adopt decomposition.

**Classification A — union-safe pruning is sufficient to make a bounded next architecture challenge credible.** U1 is below both the existing placement cap and the workface interval cap, while the 160-activity admission still blocks production. The decision for a **subsequent first exact 160/120 solve experiment is READY as an architecture question**, contingent on first implementing and falsifying rank-preserving W1 in a separately bounded diagnostic model and independently justifying any activity-admission change. READY does not claim that a 160/120 solve has been run, that a larger scale limit is safe, or that authoritative production should change now. The next milestone should test adoption-style exact U1 preprocessing and an admitted experimental model on 64/48 before attempting the first 160/120 solve. No generic factoring, R1, cumulative group capacity, solver micro-optimisation, UI or accepted-history/lineage change is included here.
