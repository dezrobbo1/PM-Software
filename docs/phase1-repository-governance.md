# Phase 1 repository governance

The tracked policy in `.github/repository-governance.json` is an optional
recommendation for possible future use. Live GitHub ruleset or branch-protection
enforcement is not required for this owner-operated research repository and is
not a completion or merge gate for Phase 1.

The Phase 0 and Phase 1 workflows still run for pull requests targeting `main`
and for pushes to `main`. Feature branches and pull requests remain the normal
working practice, but GitHub is not required to block every alternative path at
the server level.

The JSON file retains a recommended ruleset profile. Its
`live_ruleset_required: true` field means that, if that optional profile is
adopted, it must be implemented as a real GitHub rule rather than treated as if
the tracked JSON enforced anything. It does not mean the repository owner must
activate the profile.

If enabled later, the recommended profile would:

- require a pull request before merge;
- require `phase0-validation` and `phase1-validation` with the branch up to date;
- dismiss stale review state and require conversation resolution;
- block force pushes and branch deletion; and
- provide no administrator bypass.

The optional profile uses zero required approvals because this repository does
not currently have a separate mandatory reviewer. Review evidence may still be
recorded on each pull request.

A completion report may claim live branch protection only when the GitHub API
confirms it. Absence of live protection must not be reported as a blocker or as
incomplete Phase 1 work.

Historical workflow registrations and remote-branch cleanup remain separate
operations and are not implied by the current workflow files on `main`.
