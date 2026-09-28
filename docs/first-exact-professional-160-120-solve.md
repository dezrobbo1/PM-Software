# First exact professional 160/120 solve

## Question and frozen source

This diagnostic asks whether the original-rank W1 compact model can prove the complete existing policy on the faithful professional 160-declared, 120-active fixture. The starting merged main is `166d6e209f5fd29795cc92108d42ed5e17225751` (PR #52). The fixture input hash is `92a2a346a64d916ff2f8346bd016915553737f3c9d71423157f5579defc0cc46`. The dedicated workflow records its checked-out HEAD **before installation**, then verifies the SHA and clean tracked tree before and after solving. Its JSON and checksum artifact are the source-bound final-head measurements; the figures below are the first successful local run at `f22aed3a664a4ea1dcf87e0c8b54c3f199e2dd06`.

No fixture, production admission, scheduling authority, schema, policy, resource rule, history rule, or lineage rule changes. Public validation still rejects 160 activities. This plan is validated with the production physical checker through an experimental validator that changes only the activity admission check; it is not a production-supported stored plan.

## Frozen model and proof configuration

The fixture has 12 packages, four with alternative Work Methods, and 16 authorised structures. Each structure activates 120 activities. The original generator gives 64,068 raw and 64,032 deadline-eligible placements. W1 retains 7,812 placements and their original U0 ranks and maxima, yielding 6,705 resource intervals, 409 workface intervals, 332 canonical digits and 26 exact blocks. The assembled compact model has 8,308 variables and 7,952 constraints before canonical witnesses; adding witnesses gives 8,640 variables and 8,284 constraints. Serialized proto byte counts are in the source-bound JSON.

The experiment calls the production LB1 relaxation, exact bounded finish search, global weighted timing and mixed-radix block builder. Finish queries share the existing 60 deterministic-unit budget. Global timing and each block retain the production 60-unit stage budget. The production one-worker, seed-zero solver configuration is reused. No budget, seed or worker count is changed after seeing the result. Intermediate FEASIBLE is allowed only for objective-free SAT queries; global timing and every canonical block require OPTIMAL. UNKNOWN is recorded as an incomplete proof, and proven infeasibility is distinct from an unproven result. Partial JSON is saved after every completed solver call. The CLI returns success only for `COMPLETE_EXACT_POLICY_PROVEN`; bounded incomplete and infeasible outcomes leave a failing CI job while the workflow still uploads their partial artifacts.

## First successful bounded result

| Exact fact or counter | Local observation |
| --- | ---: |
| Classification | `COMPLETE_EXACT_POLICY_PROVEN` |
| LB1 and exact controlling finish | 60 and 60 |
| Finish queries | one SAT query at `finish <= 60` |
| Finish deterministic effort / remaining shared budget | 8.3313901001 / 51.6686098999 |
| Exact weighted global timing | 363,133, OPTIMAL |
| Global timing deterministic effort | 8.8446618693 |
| Canonical blocks | 26 of 26 OPTIMAL |
| Combined canonical deterministic effort | approximately 13.4453585421 |
| First-run solver calls / total deterministic effort | 28 / 30.6214105115 |
| Independent physical and experimental stored-plan validation | `PROVEN_FEASIBLE` |
| Same-environment exact repeat | `EXACT_MATCH`, 28 calls, same deterministic effort |
| Physical plan signature | `fb9207410a9a7f9279a4f83caff93e5e3aebd60e819ef700907b9293938695d1` |

The selected method is STANDARD in WP-01 through WP-08, CRANE in WP-09, STANDARD in WP-10 and WP-11, and HANDOVER in WP-12. Exactly 120 selected modes and original placement ranks, with 40 inactive zero ranks, are recorded in JSON. Of the selected placements, 109 have an original rank above one. Their rank holes are preserved: no surviving placement is assigned a compressed rank. The complete 332-digit vector and each stage status are likewise recorded in JSON rather than abbreviated here.

Wall observations are separate from deterministic counters. The local whole experiment, including a second complete solve, took approximately 58.24 seconds. Such wall values are not correctness gates. A first repeatability comparison accidentally included wall-time observations, producing a false mismatch classification at the preceding implementation commit; it was corrected to compare proved policy, plan signature and physical result. The successful local run above uses that correction. Final-head workflow evidence reruns the experiment from its own recorded SHA.

The optional all-16 fixed-structure cross-check was not implemented under an independently declared budget; its status is `STRUCTURAL_ORACLE_INCONCLUSIVE`. The joint exact proof and independent physical checks stand on their own. A future control could test that decomposition without making it production authority.

## What follows

This result proves a complete exact policy **on this frozen professional fixture in the tested environment and declared budgets**. It does not prove general production scalability, cross-version determinism, accepted-history scale, or safety of raising admission. The next milestone may be a bounded adoption/admission experiment, with separate evidence for public validation and historical compatibility. This PR does not perform that work.
