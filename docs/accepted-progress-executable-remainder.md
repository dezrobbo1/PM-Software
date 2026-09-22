# Accepted progress and executable remaining work

The native planning workspace has an explicit version 2 profile for a bounded
statused recovery. It answers one scheduling question: given reviewed execution
facts at an explicit project-relative status point, which productive work can
still execute without rewriting the accepted past?

Version 2 keeps the version 1 disjoint resource-group model. Version 0 and
version 1 workspaces still validate and open with no inferred progress. Moving a
workspace to version 2 is an explicit action that records a status point and an
initially empty update ledger. Existing plan snapshots and hashes are retained
unchanged; an existing approval becomes stale against the new trusted state.

## Semantic contract

Every activity must have one current accepted assertion before an authoritative
statused recovery can run:

- `NOT_STARTED` has no accepted execution history. Its current forecast work is
  eligible to start at or after the status point.
- `IN_PROGRESS` fixes its accepted mode, actual start, productive periods and
  applicable named assignments. Its future processing comes from the separately
  accepted remaining-work estimate and starts at or after the status point.
- `COMPLETED` has an explicit actual finish and zero future processing. It is
  represented only as accepted history.

No state is inferred from dates, predecessors, zero remaining work, or the
status point. Missing state remains `UNKNOWN` and blocks calculation. Remaining
productive work is a forecast assertion: the engine does not derive it by
subtracting actual work from the original estimate.

The status point is a relative-project tick. It is neither wall-clock “now” nor
an automatically advanced date. Accepted productive periods must finish no
later than the point; calculated future periods must start at or after it.

For begun named-resource work, the accepted resource identity is fixed for the
remainder in this bounded slice. For begun group work, the accepted group and
quantity continue into the forecast. Internal anonymous units may be used to
prove capacity and no-handover feasibility, but are removed from all planner
records and calculated output.

## Acceptance and corrections

A status update first enters `REPORTED` review state. Reporting it does not
change the trusted-input hash, invalidate a current proposal, or mutate an
approval. Acceptance records the accepting actor and time, invalidates a pending
proposal, and makes any prior approval stale. It never calculates or approves a
recovery.

A correction names the current accepted update it supersedes. The old assertion
remains in the ledger. Current state is resolved through the supersession link,
not by sorting occurrence times, so a correction that refers to an earlier field
occurrence still wins. Each accepted assertion retains:

- asserted state and values;
- occurrence tick;
- asserting actor and timestamp;
- accepting actor and timestamp;
- optional superseded update identity and reason;
- a compact execution-context snapshot used to validate historical facts.

Historical context is separate from current future-planning facts. A later
calendar edit does not move or invalidate already accepted productive periods.
New assertions also capture the accepted named-resource outages applicable to
their historical assignments. This optional version-2 context field is never
backfilled into older assertions or plan snapshots. A context without it makes
no historical outage claim; current outages cannot retrospectively justify a
gap. Corrections retaining execution choices retain that historical context;
named assignment row order does not change the slot-to-resource mapping.
Captured outages must belong to the accepted named assignments. An extra
unassigned resource in imported context cannot justify a historical gap.

Suspendable in-progress work with a positive remaining estimate must account for
every historically eligible productive tick from its actual start through the
status point. Empty history is valid only when that interval has no executable
opportunity. Completed work and explicitly zero remaining work are checked
through their recorded productive periods; zero remaining does not confirm
completion or assert continued processing up to the status point.
Future work still uses current calendars, accepted named-resource outages,
capacities, precedence, continuity and the retained objective hierarchy.

## Compiler and independent validation

The version 2 compiler removes completed activities from the future model,
replaces in-progress processing with the accepted remaining estimate, fixes
begun mode and named assignment choices, and gives every future activity a
not-before boundary at the status point. Completed predecessor links become
satisfied history; unresolved future links stay in the CP-SAT model.

Calculated entries expose `actual_*` and `forecast_*` fields separately. Actual
periods are copied from accepted assertions; forecast periods are solver output.
The legacy `periods` field remains the future portion only, so historical bars
are never presented as editable calculated bars.

Independent validation checks accepted history against its captured context,
including period shape, historical calendars, named eligibility and occupancy,
group quantities/capacity, and explicit predecessor completion. It then checks
the future against current trusted inputs, including the status boundary,
remaining productive total, current calendars and outages, capacity, fixed begun
mode and named resources, precedence, continuity, and the controlling finish.
An additional exact search proves that a consistent anonymous group-unit set
exists across accepted and forecast productive periods without persisting those
units as people. Rehashing edited output does not bypass these checks.

History-only no-handover feasibility is checked atomically at acceptance, even
before all activities have a status. Per-tick capacity alone is insufficient.
An inconsistent assertion remains reported for inspection; it is not committed
to trusted history and misdiagnosed later as future infeasibility.

Continuous completed history fills its entire actual-start/actual-finish
envelope; continuous in-progress history fills through the status point.
An activity starting exactly at that point may have no elapsed history yet.
Its positive continuous remainder must start there; current unavailability makes
recovery infeasible instead of moving that accepted start into a later window.
Adjacent recorded periods are permitted, but leading, internal and
completed trailing gaps are not. Suspendable history may omit only ticks that
were unavailable under the captured joint activity/resource conditions.
Completed positive-processing work requires recorded productive periods; an
explicit zero-duration milestone may have none. This is not a requirement that
actual processing equal its original forecast. Distinct simultaneous named
slots require distinct resource identities even before any productive period.

Completed activities use their captured mode even if it is later retired from
current planning choices. An in-progress assertion may also be superseded by
explicit completion using that same historical mode and assignments after
retirement. In-progress remainder still requires its already-used
mode to remain authorised. Recovery comparisons combine actual and forecast
execution (including named assignments and group quantities), so completing
work exactly as approved is not a move, and correcting history is not hidden
by an unchanged future remainder.

Opening or validating a version-2 workspace checks current accepted history
against captured historical conditions, even when no stored plan exists.
Partial status entry remains valid: missing statuses block calculation, not
opening. Reported assertions remain reviewable and superseded assertions retain
their provenance; neither is reinterpreted as current accepted execution.

## Planner workflow

The browser exposes the bounded sequence directly:

1. Establish the status point explicitly.
2. Draft one activity assertion at a time.
3. Review and accept each assertion into trusted state.
4. Inspect the retained stale approval, if any.
5. Calculate and inspect actual versus forecast periods.
6. Approve the calculated recovery explicitly.
7. Save and reopen the complete workspace.

Accepted named-resource availability records remain a separate forecast input.
Multiple records have distinct identities and all reach calculation. Timed
partial outages for an interchangeable group remain unsupported.

## Boundaries

The original slice established one status point. The bounded headless rolling
experiment now adds explicit atomic advancement to a later point while retaining
the same version-two representation. Every still-open activity must be
re-attested, completed history carries forward unchanged, begun choices and
previous productive periods cannot be rewritten, and the prior approval becomes
stale before a separately calculated/approved recovery. This first rolling
capability deliberately rejects begun work whose captured historical execution
context changed across the boundary; see
[`headless-rolling-status.md`](headless-rolling-status.md).

Begun work requires a known actual start in this profile. Out-of-sequence
predecessor history blocks authoritative recovery; interrupted continuous work
remains a reported assertion and cannot be accepted into this bounded model.
The engine does not invent a repair. When the controlling activity is explicitly
completed, calculation reports that no future recovery remains instead of
manufacturing a new plan.

Historical validation uses the captured activity/resource calendar context.
Exceptional historical overtime outside that context needs an explicit future
modelling decision; this slice does not silently admit it or rewrite the fact.
The existing bounded trial size and allocation-set limits still apply.

This milestone does not add arbitrary preemption, crew handover, percent
complete, timesheets, earned value, structural Work–Method choice, adaptive
repair, a new objective policy, authentication, database persistence, or an EAM
interface. Actor strings are local provenance, not enterprise identity. The
planner remains responsible for reviewing facts and approving proposals.
