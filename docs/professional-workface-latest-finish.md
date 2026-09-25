# Professional workface and protected latest finish v0

## Boundary and semantics

This is a bounded, future-only extension of `WorkMethodTimeProject`; existing
documents without either field keep their identifiers, hashes, fields, objective
policy and productive-time interpretation. `processing_ticks` remains the only
editable amount of execution work. Portable input schema stays
`pm-native-work-method-time/0`.

- An active activity with `exclusion_groups: ["WF-A"]` occupies every named
  workface over its half-open execution envelope `[start, finish)`. Another
  active activity in that group cannot enter during a productive suspension.
  Distinct groups are independent; zero-length milestones occupy no time.
- An active activity with integer `latest_finish` must finish at or before that
  tick. This is a hard constraint, never an objective penalty. An inactive
  method's deadline and workface names impose no occupancy or deadline.
- Empty/non-string/duplicate exclusion names, non-array groups, non-integer,
  negative or beyond-horizon latest finishes are invalid. A fixed activity
  with `not_before + shortest declared processing_ticks > latest_finish` is
  structurally invalid. An optional method can be validly infeasible.

The joint candidate filters late productive placements and adds optional
no-overlap intervals over full execution envelopes for each workface. Its
existing resource intervals still occupy only productive periods. Neither
constraint post-processes dates. Stored-plan validation independently checks
active latest finishes and pairwise workface envelopes without solving.

## Small falsification and independent control

`professional_workface_experiment.py` holds five Work Packages, ten declared
activities, two flexible packages and four authorised structures within eight
ticks. The DAY calendar is productive at `[0,2)` and `[4,8)`; a physical named
mechanic is shared by the access and crew work. `A_FAST` executes four ticks
over `[0,2)` and `[4,6)` while retaining its workface across `[2,4)`.

| Case | BUILD method | B start | Handoff finish | Why |
| --- | --- | ---: | ---: | --- |
| Baseline without workface/deadline | FAST | 2 | 6 | B can enter during A's suspension. |
| Shared workface, no deadline | FAST | 6 | 7 | B waits until A leaves its full envelope. |
| Shared workface, B latest finish 3 | ALT | 2 | 7 | FAST cannot satisfy B's hard bound within the preferred schedule. |

Removing only the workface from the workface case restores finish 6. Removing
only B's deadline from the protected case restores the preferred FAST method;
its B finish is 7 and would violate the protected tick 3. `C_ALT` has an
impossible `latest_finish: 0` and names `WF-A`; it is inactive in the protected
case, so it does not obstruct B. `A_FAST` also names `WF-A` and is inactive in
the protected case. These counterfactuals retain the same calendars, resources,
objective and other constraints.

An independent direct Python control enumerates all authorised method choices
and starts, constructs productive ticks from the fixture's raw windows, checks
the named mechanic's occupied ticks, compares workface envelopes and latest
finishes, then ranks feasible choices by the complete declared policy: finish,
weighted starts, method indices, active mode indices and placement starts.
It does not call the candidate, its placement compiler, its no-overlap
constraints or the physical checker. It agrees on objective, method choice and
every active start in all retained cases. The largest case here generates 71
candidate placement alternatives. Repeated same-environment calculations
return identical complete plans. Rehashed plans with edited overlap or late
finish are rejected without a solver call. Native save/reopen retains both
fields and validates the plan without solving.

Run:

```bash
python -m unittest tests.test_professional_workface_experiment tests.test_professional_scale_challenge -v
python -m deterministic_scheduling_core.professional_workface_experiment
python -m deterministic_scheduling_core.professional_scale_challenge
```

## Follow-up 160/120 classification

The faithful selected 120-active projection now validates both professional
fields. The first authoritative barrier for 160 declared activities remains
the unchanged 64-activity admission guard. The faithful diagnostic generates
64,068 raw placements and retains 64,032 after latest-finish filtering
(cap 20,000); unchanged stage construction
would imply 334 lexicographic stages if admission were raised. The PR #40
semantic projection barriers are closed in this bounded future-only profile.
The next focused scale question is placement generation/canonicalisation and
proof cost, without raising admission in this experiment.

This result does not establish generic workface capacities, soft deadlines,
accepted-history workface correctness, 160/120 schedulability, UI support,
cross-version deterministic plans or production readiness.
