# Professional-Shape 160/120 Scale Classification v0

## Question

What is the first real barrier when the earlier professional-shaped scheduling
fixture is projected onto the current converged Work-Method/productive-time path?

This milestone deliberately does **not** raise production limits or change
scheduling semantics. It classifies failure before architecture is changed.

## Source fixture

The challenge reuses the already-retained adaptive-repair fixture shape:

- **160 possible activities**;
- **120 selected/active activities**;
- **12 Work Packages**;
- **4 flexible Work Packages**;
- exactly **16 authorised structural combinations**;
- pooled MECH / ELEC / QA capacity;
- scarce named crane `C04`;
- workface exclusion groups;
- protected latest-finish handoff semantics.

The old fixture is translated into the current `WorkMethodTimeProject`
vocabulary without silently dropping the workface or protected-finish fields.

## Classification result

The current authoritative converged path fails first at admission:

```text
ADMISSION_BOUND
bounded composition requires 1..64 declared activities
```

That is expected because PR #38 deliberately kept 65+ declared activities
outside the admitted profile.

However, admission is not the only barrier.

Materialising the selected 120-activity professional structure and validating it
against the current productive workspace schema exposes a semantic projection
gap:

```text
UNSUPPORTED_ACTIVITY_SEMANTICS
unsupported activity fields on P03A04
```

The faithful professional projection contains two activity concepts that the
current converged productive-time profile does not accept:

- `exclusion_groups` — the workface/exclusion semantics used by the adaptive
  repair fixture;
- `latest_finish` — the protected handoff deadline semantics used by the same
  fixture.

Those fields are retained by the challenge specifically so the larger case
cannot appear to pass by silently deleting professional scheduling semantics.

## Diagnostic-only stripped projection

For diagnosis only, the challenge makes a copy with those two unsupported fields
removed. This copy is **not** an authoritative candidate and does not change the
production schema.

That stripped selected projection validates, allowing the next scale pressures
to be measured without scheduling.

Observed diagnostic shape:

- placement alternatives using the current productive placement generator:
  **64,068**;
- current placement cap: **20,000**;
- therefore the current placement cap would also be exceeded after admission;
- theoretical current lexicographic stage count if all 160 declared activities
  were admitted: **334** stages.

The 334-stage count follows directly from the current compiler shape:

```text
2 global objective stages
+ 12 Work-Package method stages
+ 160 activity-mode stages
+ 160 activity-placement stages
= 334
```

This is substantially above the already-material 138-stage signal observed in
the 64/48 experiment.

## Result

The professional-shaped challenge identifies three ordered barriers:

1. **authoritative admission:** 160 declared activities exceeds the retained
   64-activity bound;
2. **semantic projection:** workface/exclusion groups and protected latest-finish
   semantics are not yet composed into the current productive Work-Method path;
3. **diagnostic scaling:** even after stripping those semantics, the current
   placement generator produces 64,068 alternatives, above the retained 20,000
   cap, with 334 lexicographic stages implied by the current canonicalisation
   scheme.

Therefore the next step is **not** to raise the declared-activity limit to 160.

The next focused implementation should first compose the missing professional
semantics on a smaller controlled fixture:

- workface/exclusion constraints;
- protected latest-finish / handoff constraints;

while preserving the current Work-Method, productive-time, resource and
accepted-history behaviour.

After those semantics are demonstrated and independently checked, rerun this
160/120 challenge. At that point the next genuine scale barrier can be addressed
without weakening the model to make the fixture fit.

## Evidence

Run:

```bash
python -m unittest tests.test_professional_scale_challenge -v
python -m deterministic_scheduling_core.professional_scale_challenge \
  --output /tmp/professional-shape-scale/results.json
```

The focused workflow records the exact source SHA, runtime metadata, focused test
log, result JSON and console output.

## Explicit boundary

This milestone does not:

- raise the 64-activity admission limit;
- raise the 20,000 placement cap;
- schedule the 160/120 case;
- implement workface exclusions;
- implement protected latest-finish semantics;
- redesign canonicalisation;
- claim a production performance limit.

It is a failure-classification milestone only.
