# Microsoft Project headless relationship characterisation

Status: **completed with protocol/tooling defects**

Characterisation label: `headless_native_characterisation`

Run ID: `20260830T185000p0800`

Starting `main`: `4c7c6d62902c62e822f059ee33aa4db40aba9594`

This experiment used the installed Microsoft Project Professional desktop
calculation engine through fresh, hidden `MSProject.Application` COM instances.
It is not the frozen `manual_native_semantic_parity` evidence track, does not
execute the frozen `saved_file_reopen_recalculate_stability` track, and does not
unblock the `adapter_interchange_round_trip` track. It is non-claim-eligible
characterisation evidence only. No optimiser or P6 execution was involved.

The redacted machine-readable record is
`native-validation/characterisations/microsoft-project-relationship-v0.1/headless-native-characterisation-20260830T185000p0800.json`.
Raw MPP, XML, journals, observations and manifests remain ignored beneath
`native-files/headless-msproject-characterisation/`.

## Environment

- Microsoft Project Professional, COM version `16.0`, application build
  `16.0.20228`.
- Observed `WINPROJ.EXE` file version `16.0.20228.20186`, SHA-256
  `517739145e66a5be53eea3140471717e278b756b8cd13a42443968469ee48b8f`.
- Windows 11 Pro 25H2, x64, build `26200.9168`.
- CPython `3.12.13`, x64. The run used late-bound
  `DispatchEx("MSProject.Application")` automation.
- Locale `English_Australia.1252`; Windows time zone
  `W. Australia Standard Time` (`+08:00`).

The preflight completed its then-implemented set/readback checks for blank-project
creation, hidden operation, Manual calculation, project start, automatic Fixed
Duration tasks, Effort Driven false, signed relationship lag, built-in 24 Hours
assignment, native calculation, task readback, MPP save, close, fresh-instance
reopen, recalculate, Project XML export and process exit. Its datetime check used
the same faulty timezone conversion and therefore did **not** establish the
requested `08:00` Perth wall-clock start.

## Twelve-case result

Coordinates below are what the post-freeze comparator derived from the serialized
COM timestamps, as hours from `2026-01-05T08:00:00+08:00`; no rounding was
applied. `Reference` preserves that comparator's result, but `*` marks it
provisional because Project's own XML wall-clock timestamps are exactly eight
hours earlier. Overall execution integrity is therefore inconclusive for every
case. The comparator also ran after the first worker-attributed forced
termination, which was a mandatory batch-stop trigger; its output is retained
only as provisional raw evidence.

| Case | Relationship | Lag | A start | A finish | B start | B finish | Project finish | Reference | Reopen stable | XML relationship | Execution integrity |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|
| SEM-REL-001 | FS | 0 | 0 | 4 | 4 | 7 | 7 | characterisation_exact* | yes | preserved | inconclusive: COM/XML -8h |
| SEM-REL-002 | SS | 0 | 0 | 4 | 0 | 3 | 4 | characterisation_exact* | yes | preserved | inconclusive: COM/XML -8h |
| SEM-REL-003 | FF | 0 | 0 | 4 | 1 | 4 | 4 | characterisation_exact* | yes | preserved | inconclusive: COM/XML -8h |
| SEM-REL-004 | SF | 0 | 4 | 8 | 1 | 4 | 8 | characterisation_exact* | yes | preserved | inconclusive: COM/XML -8h |
| SEM-REL-005 | FS | +2 | 0 | 4 | 6 | 9 | 9 | characterisation_exact* | yes | preserved | inconclusive: COM/XML -8h; worker-attributed termination |
| SEM-REL-006 | SS | +2 | 0 | 4 | 2 | 5 | 5 | characterisation_exact* | yes | preserved | inconclusive: COM/XML -8h; worker-attributed termination |
| SEM-REL-007 | FF | +2 | 0 | 4 | 3 | 6 | 6 | characterisation_exact* | yes | preserved | inconclusive: COM/XML -8h |
| SEM-REL-008 | SF | +2 | 4 | 8 | 3 | 6 | 8 | characterisation_exact* | yes | preserved | inconclusive: COM/XML -8h; worker-attributed termination |
| SEM-REL-009 | FS | -2 | 4 | 8 | 6 | 9 | 9 | characterisation_exact* | yes | preserved | inconclusive: COM/XML -8h |
| SEM-REL-010 | SS | -2 | 4 | 8 | 2 | 5 | 8 | characterisation_exact* | yes | preserved | inconclusive: COM/XML -8h |
| SEM-REL-011 | FF | -2 | 4 | 8 | 3 | 6 | 8 | characterisation_exact* | yes | preserved | inconclusive: COM/XML -8h |
| SEM-REL-012 | SF | -2 | 8 | 12 | 3 | 6 | 12 | characterisation_exact* | yes | preserved | inconclusive: COM/XML -8h |

All relationship assignments retained native type, signed magnitude and
`LagType=5` (hours). Project XML retained the corresponding `Type`, `LinkLag`
in tenths of a minute, and `LagFormat=5`. All twelve MPPs reopened in a fresh
COM process with no claimed Start, Finish or Project Finish change before or
after explicit recalculation. The initial and reopened XML relationship records
were equal for every case. However, each XML Start/Finish wall clock was exactly
eight hours earlier than its serialized COM counterpart. An earlier failure log
shows pywin32 returned `00:00` with a `GMT Standard Time` tzinfo, and the adapter
converted that value to `08:00+08:00`; Project XML retained `00:00`. This is an
adapter time-semantics defect, so neither the requested `08:00` local start nor
the normalized reference comparison is established by this run.

Relationship-family summary:

- FS: zero, positive and negative comparator outputs exact but all time-semantics-inconclusive; positive also cleanup-inconclusive.
- SS: zero, positive and negative comparator outputs exact but all time-semantics-inconclusive; positive also cleanup-inconclusive.
- FF: zero, positive and negative comparator outputs exact but all time-semantics-inconclusive.
- SF: zero, positive and negative comparator outputs exact but all time-semantics-inconclusive; positive also cleanup-inconclusive.

## CAL-24X7 observation

Project authored an additional disposable schedule with the built-in **24
Hours** calendar and exported it through `Application.FileSaveAs`.

- Namespace: `http://schemas.microsoft.com/project`.
- `SaveVersion`: `14`.
- Project `CalendarUID`: `3`.
- Calendar `UID`: `3`; `IsBaseCalendar`: `1`; `BaseCalendarUID`: `0`.
- Day types `1` through `7` each have `DayWorking=1`.
- Every day contains one working interval with `FromTime=00:00:00` and
  `ToTime=00:00:00`; Project therefore serializes the continuous day using an
  equal-midnight pair, not `24:00:00`.
- The 24-hour task exported from `2026-01-05T00:00:00` to
  `2026-01-06T00:00:00` in the offset-free XML. The in-memory COM readback was
  not durably returned before the later watchdog stop, so this document makes
  no retained-readback claim for that disposable calendar task.

Post-run operator attestation reports that opening that exact Project-authored
XML with `FileOpenEx` displayed `Import Wizard - Import Mode` and that it was
not dismissed. The durable watchdog stop record contains a stale PID and no
window inventory, so the title is not claimed as machine-journalled evidence.
XML reopen, recalculate and re-export are **inconclusive**. The observed
serialization does not automatically remove the existing Track C blocker;
explicit change control remains required. This CAL-24X7 native work also ran
after SEM-REL-005's mandatory-stop trigger, so the retained serialization is
provisional characterisation rather than procedurally valid completion.

## Defects and limitations

1. A delegated read-only discovery search accidentally matched the sealed
   expectation tree before native execution. The executed construction branch
   used the source-only loader and the agent reported that the values were not
   used, but there was no operating-system access boundary and clean procedural
   blinding cannot be claimed.
2. Project-authored XML for all twelve cases is eight wall-clock hours earlier
   than the serialized COM observations. The requested Perth-local origin and
   the semantic comparison are not established; every case is inconclusive.
3. Three Project processes did not exit within the bounded quit wait and were
   attributed to their workers by the then-current PID/path-delta logic before
   forced termination. Full creation/caption/HWND ownership proof was not
   retained, so those executions are additionally inconclusive. The retained
   batch continued with SEM-REL-006 through SEM-REL-012 after the first such
   termination in SEM-REL-005, contrary to the mandatory-stop rule. The hardened
   tool now treats forced termination as an immediate stop condition.
4. Post-run operator attestation records that the initial parent watchdog could
   miss a fast reopen PID and that later cleanup misclassified and terminated
   an unrelated user Project process. The underlying watchdog journal does not
   retain the window/parent evidence, so this is disclosed as operator-attested;
   unsaved-work loss was possible and further native execution stopped. The
   hardened implementation refuses activation while any Project process exists,
   binds a unique new PID/creation identity to a caption and HWND, and permits
   destructive cleanup only after revalidation of that full identity.
5. Raw environment capture serialized the optional `FileBuildID` member as a
   bound-method representation. The independently captured `Application.Build`
   and independently observed executable file version remain valid.
6. The executed producer hashes retained in every case manifest are: runner
   `f1e09917f92e312fb32085d0aec27d07d8ca9a859a9d2872bbbceba8086e0d83`,
   core `25e78d83c1bc844f6f3a96b2d534d182b4472c28634f21acbba7e178a06d1140`,
   COM adapter `46a82cfdf03a6ef4a57458162965ce6cefff970535bf710e5d438f10c650ea62`,
   and worker `91dc8f8cccede56c3389c80c2a2cd3eaf2da086c967bfcb7a94f079d88764723`.
   The immutable v0.1 worker observations do not self-report or bind these
   identities; v0.2 requires both the manifest and worker-observation bindings.
   The reviewed branch contains post-run hardening and is not byte-identical to
   the code that produced the frozen observations.
7. The immutable raw `run-status.json` classified only the three
   worker-attributed terminations as inconclusive, and `run-anomalies.json`
   contained the earlier runtime-isolation and direct window/process assertions.
   The raw `observation-freeze-index.json` permitted oracle access despite the
   forced-session fact omitted from legacy `stop_conditions`, and the subsequent
   `comparison.json` was therefore produced after a mandatory-stop trigger.
   This tracked interpretation supersedes those conclusions without changing
   their raw bytes: all twelve cases are inconclusive, no OS/ACL oracle boundary
   existed, the dialog/process details are operator-attested, and the comparator
   output is provisional only.

Recommendation: **Protocol/tooling defect discovered**.

This experiment uses the actual Microsoft Project scheduling engine through
headless COM automation, but does not satisfy the frozen
`manual_native_semantic_parity` track and is therefore retained as native
characterisation evidence unless and until the protocol is explicitly amended
under change control.
