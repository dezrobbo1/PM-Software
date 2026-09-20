# Planner-level capacity trial

## Contract

The productive-calendar workspace now has an explicit version 1 profile. A
resource group stores `id`, display `name`, positive integer `capacity`, an existing
`calendar_id`, and declarations `disjoint: true`, `interchangeable: true`. These
declarations exclude membership in any other group or named resource. Member lists,
overlapping groups and automatic qualification inference are unsupported. Available
capacity is a planner's committed input, not a deduction from an external MaxUnits
field. Unreported real-world overlap cannot be detected.

An authorised activity mode can contain `group_requirements`, for example
`[{"group_id":"CREW","demand":2}]`. Each group occurs once. Different rows are
simultaneous requirements; they are not alternatives. Demand must be a positive
integer no greater than capacity. Zero-work milestones have no resource demand.
Capacity/quantity edits never change productive duration automatically.

Existing explicit `requirements` remain available alongside group quantities for
schedule-critical capacity-one resources, mixed qualifications and eligibility.
Legacy version 0 files remain version 0, with unchanged source snapshots, hashes,
reports and history. There is no automatic collapse or migration of their roster.
New project creates version 1 without an invented workforce. Load example remains
the original explicit-eligibility / legacy-rigging demonstration.

## Compilation and independent proof

The same Python CP-SAT finite-placement workflow and objective hierarchy are used.
Groups are expanded only inside compilation/checking into anonymous capacity units
with the group's calendar. Each activity selects one set for all its productive
segments. Enumerating combinations rather than permutations removes meaningless
within-crew naming choices. No anonymous unit is a planner-maintained record or
claimed worker assignment. Anonymous choices carry no assignment-preservation cost.
Named assignment-preservation terms remain unchanged.

Execution intersects the activity calendar with every mandatory group calendar and
the calendars of selected named resources, not every eligible alternative. Capacity
is occupied only during productive segments. Continuous work remains uninterrupted;
suspendable work resumes at the next joint availability, not an optimiser-selected
arbitrary pause. Fixed anonymous allocation through all segments preserves the prior
no-handover assumption. A time-slice capacity check alone is **not** that stronger proof.

The result contains `group_demands`, not anonymous identities. Independent validation
recomputes aggregate occupancy directly from the submitted periods and native demands,
then performs the existing exact global fixed-allocation check with fresh anonymous
units and submitted named assignments. Stored plans are checked against their own
versioned source snapshot, never silently recalculated on Open.

Bounds remain 8–15 browser activities, 30-minute relative days, 1–14 days, up to 16
mode combinations and the existing workspace size limit. New bounds: at most 8 groups,
32 total anonymous capacity units, and 64 assignment/set combinations per activity-mode.
These are a bounded compiler profile, not a universal workforce architecture.

## Planner instructions

1. Install once: `python -m pip install -e .`. Launch:
   `python -m deterministic_scheduling_core.native_planning_ui`.
   Open `http://127.0.0.1:8765`; stop with Ctrl+C. Hosted access uses the PR's exact
   Preview URL and needs no local installation.
2. Choose **New project**, then **Resources and calendars**. Add each group with
   an ID, name, capacity and the disjoint/interchangeable declaration. Select its
   calendar. Do not include separately represented named resources in that capacity.
3. Select an activity. Enter **Productive activity duration (hours)** and its
   calendar/continuity. Add one **group quantity** per mandatory group. Quantity 2
   means two units at once, not twice the processing time. Use named slots only
   where explicit identity/eligibility matters. Predecessors show IDs and names.
4. **Apply input changes**, **Calculate**, inspect group usage/productive gaps and
   checker status, then separately **Approve** if appropriate. Solver and hash
   details remain available under the plan's audit disclosure.
5. Edit group capacity through normal project inputs. Pool-specific timed partial
   outages are not supported; do not create fictitious-person reports. Existing
   named-resource report → accept → recovery → approve remains available.
6. **Save workspace** downloads the complete workspace. **Open workspace** restores
   it without solving, approving, changing old hashes or losing history.

Windows PowerShell uses the same Python commands (or `py -m ...`); Windows is not
verified by this Linux trial. Relative days are not real dates/time zones.

## Bounded evidence

The private retained 15-item workfront and its separate group-input counterpart
were recalculated without changing processing, dependencies, calendars or continuity.
Both returned finish tick 125 and objective `[125,0,0,0,9038]`; all productive periods
and modes matched. Repeating the pooled solve returned the same result/hash in this
environment. Planner input records changed from 4 anonymous representatives / 22
slots / 44 eligibility memberships to 2 groups / 12 quantity rows / 0 memberships.
This measures representation, not human time savings or practitioner acceptance.
Private identifying source records are not committed here.

Operational interpretation still needs confirmation of working windows, committed
capacity without outside competing demand, inspection position, and conditional
required scope. A successful solve is not safety authorisation or actual progress.

Version 2 now reuses this group representation for accepted history and executable
remaining work; see [`accepted-progress-executable-remainder.md`](accepted-progress-executable-remainder.md).
That later profile does not add WBS, overlapping capability pools, timed partial-pool
reporting, anonymous worker identities or a new objective.
