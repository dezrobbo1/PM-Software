# W1 original-rank model integration (diagnostic v0)

PR #51 proved a domain-level W1 relaxation without assembling a professional 160/120 model. This experiment compiles a compact diagnostic CP-SAT model, checks the already admitted 64/48 problem against the unchanged public authority, and assembles—but **never solves**—the faithful 160/120 projection. Production admission remains 64 declared activities, 20,000 placements and 20,000 workface intervals. Public scheduler, persisted schema, policy, hashes, accepted history and rolling lineage are unchanged.

## Three exact paths

| Path | Model | Purpose |
| --- | --- | --- |
| P0 | Public authority and unmodified production compiler replay | Freeze authoritative schedule, plan hash and actual model shape. |
| E0 | Production compiler with each W1-removed placement literal fixed to zero | Falsify W1 without changing any original literal, rank, or canonical digit expression. |
| E1 | Bounded experimental compiler with only surviving placement literals | Test the real model-size reduction and prove the same original-rank policy. |

All paths use the production LB1 finish proof, weighted global timing, exact canonical block construction, solver parameters, extraction and independent physical validation. For E1 each original production row is compared by activity, mode, original one-based rank, start, finish, productive periods and **full assignment tuple** to the PR #51 row before filtering. An original domain `[1,…,N]` retaining ranks `2,5,9` uses `2*l2 + 5*l5 + 9*l9`, with digit maximum **N**. Method and mode digits and declared activity weights are unchanged. Canonical block definitions and the full vector, including every placement digit, equal P0. E0's unchanged literals make it the stronger W1 semantic falsification; E1 measures the compact model actually assembled.

The complete 64/48 P0, E0 and E1 semantic plans (everything except proof identity and plan hash), selected rank maps, allocation witnesses and physical results agree. The independent 64-fixed-network oracle agrees only on methods, modes, controlling finish and weighted timing; it does not independently canonicalize placements. The checks are separate.

## Actual model shapes and estimate reconciliation

The source-bound CI result records exact pre-canonical, post-witness-context and final solved proto variables, constraints and serialized bytes for all three admitted paths. The admitted post-witness context includes the fixed finish and timing equalities as well as the per-digit witness IntVar/equality. E0 adds exactly one equality per disabled row. E1 retains original rank maxima even where rank holes occur. The PR #51 mechanical estimates exclude package-root arcs; this experiment counts them from the assembled problem and asserts that they explain the entire pre-canonical constraint difference. An admitted post-witness context also has two stage-fixing equalities; the unsolved professional post-witness context has none.

The faithful professional model retains all 160 declared / 120 active activities, twelve packages, four flexible packages, sixteen method structures, C04, MECH/ELEC/QA, workfaces and protected latest finish. W1 retains 7,812 placements, 6,705 resource optional intervals, 409 workface optional intervals, 332 canonical digits in 26 blocks. Actual **unsolved** proto: 8,308 variables, 7,952 constraints and 838,675 serialized bytes before canonical witnesses; 8,640 variables, 8,284 constraints and 952,123 bytes after witnesses. PR #51's estimated pre-canonical constraints were 7,937: the 15 additional constraints are package-root arcs it explicitly excluded. A test patches `CpSolver.solve` to raise during professional assembly, verifying that no professional solver call occurs.

## Isolated admission and decision

Synthetic chains of 65, 96, 128 and 160 declared activities have one structure, one mode, one forced rank-one placement each and independently calculated starts/finishes. E1 solves them exactly under its diagnostic-only 160-activity validator; the public `validate_problem` rejects each at 64. These are low-density correctness controls, not evidence that the professional 160/120 model can be solved within its proof budget.

**Classification A — W1 model integration proven. READY for a subsequent first exact professional 160/120 solve *experiment*.** The next bounded milestone may attempt that exact solve using this diagnostic architecture and a stated proof budget. This result neither adopts W1 nor raises production admission, and it makes no professional scheduling or performance claim. The machine-readable evidence separates exact proto counts, deterministic solver counters and noisy wall observations.
