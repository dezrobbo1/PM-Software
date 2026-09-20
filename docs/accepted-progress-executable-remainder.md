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

This first slice establishes one status point per test workspace and permits
explicit corrections at that point. Advancing to a later status point, carrying
assertions forward and reviewing new execution is a separate capability. Begun
work requires a known actual start in this profile. Out-of-sequence predecessor
history and interrupted continuous work are retained as assertions but block
authoritative recovery; the engine does not invent a repair. When the controlling
activity is explicitly completed, calculation reports that no future recovery
remains instead of manufacturing a new plan.

Historical validation uses the captured activity/resource calendar context.
Exceptional historical overtime outside that context needs an explicit future
modelling decision; this slice does not silently admit it or rewrite the fact.
The existing bounded trial size and allocation-set limits still apply.

This milestone does not add arbitrary preemption, crew handover, percent
complete, timesheets, earned value, structural Work–Method choice, adaptive
repair, a new objective policy, authentication, database persistence, or an EAM
interface. Actor strings are local provenance, not enterprise identity. The
planner remains responsible for reviewing facts and approving proposals.
