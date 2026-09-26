# Controlling finish proof cost decomposition v0

## Question and boundary

PR #43 made exact canonical batching authoritative, reducing the 64-declared / 48-active case to 11 proof calls. The first, controlling-finish optimization became the largest admitted solve cost. This experiment asks which parts of that cost depend on knowing the optimum, structure, modes, physical identity, or placement representation. It does not change the production compiler, policy, plan hash, accepted history, lineage, or admission limits.

The experiment calls the same private production compiler on *fresh copies* of the 64/48 source. It obtains `F` from a normal authoritative batched plan each run and checks that plan against the existing independent fixed-network enumeration of all admitted method/mode controls. Here `F = 19`. It then checks the three distinct questions below on copies of an identical base proto. The original authoritative plan never receives the diagnostic bound.

| Proof question | Result | Observed wall ms | Deterministic time | Branches | Conflicts |
| --- | --- | ---: | ---: | ---: | ---: |
| Minimize finish | OPTIMAL, 19 | 4,133 | 5.47831 | 7,937 | 6 |
| Can finish by 19? | OPTIMAL, 19 | 262 | 0.06846 | 2,433 | 4 |
| Can finish by 18? | INFEASIBLE | 82 | 0 | 0 | 0 |

These are one local Python 3.12 / OR-Tools 9.15.6755 observations, not a runtime target. In particular, **the explicit F−1 infeasibility certificate is cheap in this model**. The optimization objective is much more expensive than either bounded query. Do not describe this as an expensive F−1 certificate or infer its cause from the objective wall time alone.

Every unmodified 64/48 base proto has 64 declared activities, 16 authorized structures, 5,626 placements, zero workface intervals, 5,832 variables and 3,860 constraints. The within-environment text-proto SHA-256 is `02828dd59cfd718abf1f4ff2f612094ed05f8fcde6a4d688ce16b895eeb07ea7`. It is compared **before** appending each diagnostic constraint, including fixed-decision optimization rows. Proto-text identity is a same-version control, not a portable cross-version hash. The bounds add one constraint each; method/mode/assignment controls are counted separately.

## Decision freedom

Each row begins with an identical full union base model. Methods are fixed by their existing method literals, active modes by existing mode literals, and named resources by excluding placements that disagree with the authoritative named assignment. Anonymous interchangeable group unit IDs are never fixed as professional identities. In this anchor, the last row adds *zero* assignment exclusions: its named assignments already have no alternative identity. The optimization column was added as a causal control because bounded feasibility does not measure objective optimization.

| Full union row | Control constraints | Finish optimization deterministic time | Bound F deterministic time | Bound F−1 deterministic time | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| All choices free | 0 | 5.47831 | 0.06846 | 0 | F feasible; F−1 infeasible |
| Methods fixed | 8 | 3.45797 | 0.02149 | 0 | Same finish |
| Methods and active modes fixed | 56 | 3.75647 | 0.01413 | 0 | Same finish |
| Named assignments also fixed | 56 | 3.75647 | 0.01413 | 0 | Same finish |

The selected-network control is a **different**, explicitly pruned diagnostic model: 48 declared activities, one structure, 4,000 placements, 4,152 variables and 2,600 constraints. It retains all productive temporal starts, calendar gaps, precedence, resources, hard finish limits and workfaces, while keeping only the selected structure/modes and narrowing chosen named eligibility. It proves F=19 and F−1 infeasible. Its finish optimization consumed about 3.756 deterministic seconds in the retained observation. Its proto digest differs from the union model, as expected. The pruned control is not a substitute public scheduler.

## Placement census and small controls

The 64/48 compiler generated and retained 5,626 placements. A census of every activity/mode reconciles exactly with the compiler. There are 4,024 distinct `(start, finish, productive periods)` patterns *within their activity/mode*, 1,442 placements belonging to inactive structural alternatives, 184 belonging to unselected modes of active activities, and 4,000 belonging to selected modes. The result JSON contains the per-activity/mode raw and deadline-filtered counts, starts, envelopes, named signatures, full internal signatures, and assignment variants per temporal pattern. Group unit IDs are counted solely as **solver-internal anonymous witnesses**, never as worker identities.

The low-density activity ladder has 8/16/32/48/64 activities and exactly one placement per activity; all controlling-finish optimizations finish in presolve. The fixed eight-activity placement ladder has 129/513/1,537/3,841 placements, respectively; it holds objective semantics and activity count fixed. Each case proves its optimum F and F−1 impossibility from fresh matching bases. In the retained local run, objective deterministic times increased from roughly 0.00007 to 0.02938 as density rose, while all F−1 queries finished in presolve. This provides a placement/model interaction signal, not a universal complexity curve.

The smaller professional control uses both the protected deadline with an inactive alternative and a separate suspended workface case. The latter's productive periods are `[[0,2],[4,6]]`, its entire workface envelope is `[0,6)`, and the next shared-workface activity starts no earlier than 6. Both controls preserve F feasibility and F−1 infeasibility after fixing choices. The hard active deadline and inactive alternative do not leak into one another.

## Interpretation and next experiment

**D — temporal placement / model representation dominated, with a measurable method-choice interaction.** Most objective proof cost remains after fixing methods and modes and even after pruning the selected network. Method fixing reduces but does not eliminate it; this anchor cannot assign named-resource-choice cost because there is no alternative named assignment. The explicit one-tick-better infeasibility proof is not the dominant cost. Density controls show model-size sensitivity. A next, separately authorized milestone should test an **exact factored placement/time representation against the current authoritative model**, including the objective optimizer's lower-bound behavior, without changing scheduling semantics. This PR implements no new representation.

Frozen base-main production plan hashes remain unchanged for small (`458a5927a645fb2eed8a8ac432c0262d2bfcf23d3ae222a4e9f32d4682569ab5`), professional (`61add1ea57ede769cb676aa11f93b31eb5696f8f691b22b22a38b9f146172a7d`) and 64/48 (`88f125d76b5cdbe4f18e14834767e964e5b29f2db21a2c839481e1399e21f63f`) plans. The professional 160/120 classifier still accepts faithful workface/deadline semantics, stops at the 64-activity guard, counts 64,068 raw and 64,032 deadline-eligible placements against the unchanged 20,000 cap. No 160/120 scheduling is attempted.

The dedicated workflow saves the exact head SHA, Python and OR-Tools versions, focused tests, complete JSON with per-proof deterministic counters, and SHA-256 checksums. Wall times are measurements, never correctness assertions. No production scheduling path imports this module.
