# Phase 1 repository governance

The tracked policy is `.github/repository-governance.json`. The required live
GitHub ruleset targets the default branch `main` and must:

- require a pull request before merge;
- require `phase0-validation` and `phase1-validation` with the branch up to date;
- dismiss stale review state and require conversation resolution;
- block force pushes and branch deletion; and
- provide no administrator bypass.

Required approvals are zero because this owner-operated research repository does
not currently have an independent mandatory reviewer. Review evidence may still
be recorded on each pull request. Increasing the approval count is safe only
when a separate eligible reviewer is available.

The JSON file is a reviewable target policy, not an enforcement mechanism. A
completion report may claim branch protection only after the live branch or
ruleset API confirms protection and the exact required checks.

The repository currently keeps historical workflow registrations and old remote
branches outside this hardening change. Disabling workflows or deleting branches
is a separate live cleanup operation and must not be inferred from the two
current workflow files on `main`.
