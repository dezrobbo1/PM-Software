from __future__ import annotations

import argparse
import sys
from pathlib import Path

from deterministic_scheduling_core.execution import SemanticSuiteHarness
from deterministic_scheduling_core.native.msproject import (
    CASE_IDS as MSPROJECT_PILOT_CASE_IDS,
    PILOT_ID as MSPROJECT_PILOT_ID,
    TRACK_IDS as MSPROJECT_PILOT_TRACK_IDS,
    STOP_CONDITION_IDS as MSPROJECT_STOP_CONDITION_IDS,
    STOP_OUTCOME_CLASSIFICATIONS as MSPROJECT_STOP_OUTCOMES,
    analyse_msproject_native_output,
    freeze_msproject_native_input,
    load_canonical_json,
    prepare_pilot,
    record_msproject_native_attempt_stop,
    verify_pilot,
)


def find_repository_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "benchmarks" / "semantic" / "catalogue.csv").is_file()
            and (candidate / "schemas" / "canonical-schedule.schema.json").is_file()
        ):
            return candidate
    raise FileNotFoundError("could not locate the deterministic scheduling repository root")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deterministic_scheduling_core")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser(
        "run-semantic-suite", help="execute the exact frozen 50-case semantic corpus"
    )
    run.add_argument("--repository-root", type=Path)
    run.add_argument("--cases-dir", type=Path)
    run.add_argument("--catalogue", type=Path)
    run.add_argument("--output-dir", type=Path)
    run.add_argument(
        "--executed-at",
        help="RFC 3339 execution metadata; omitted from deterministic record hashes",
    )

    prepare = subparsers.add_parser(
        "prepare-msproject-relationship-pilot",
        help=(
            "prepare the deterministic 12-case Microsoft Project relationship kit "
            "without executing Microsoft Project"
        ),
    )
    prepare.add_argument("--repository-root", type=Path)
    prepare.add_argument("--output-dir", type=Path)

    verify = subparsers.add_parser(
        "verify-msproject-relationship-pilot",
        help="regenerate the pilot in a temporary directory and require byte identity",
    )
    verify.add_argument("--repository-root", type=Path)
    verify.add_argument("--output-dir", type=Path)

    freeze = subparsers.add_parser(
        "freeze-msproject-native-input",
        help="freeze one reviewed native input before any native result is observed",
    )
    freeze.add_argument("--repository-root", type=Path)
    freeze.add_argument("--pilot", default=MSPROJECT_PILOT_ID)
    freeze.add_argument("--case", required=True, choices=MSPROJECT_PILOT_CASE_IDS)
    freeze.add_argument("--track", required=True, choices=MSPROJECT_PILOT_TRACK_IDS)
    freeze.add_argument("--native-file", required=True, type=Path)
    freeze.add_argument("--environment-capture", required=True, type=Path)
    freeze.add_argument("--output-dir", required=True, type=Path)
    freeze.add_argument(
        "--prerequisite-manual-case-realization-manifest",
        type=Path,
        help="required for the saved-file reopen/recalculate track",
    )
    freeze.add_argument("--prepared-at", required=True)
    freeze.add_argument("--prepared-by", required=True)
    freeze.add_argument("--independent-pre-execution-reviewed-by", required=True)
    freeze.add_argument(
        "--attest-no-native-result-observed-before-freeze",
        required=True,
        action="store_true",
        help="required affirmative pre-observation attestation",
    )

    analyse = subparsers.add_parser(
        "analyse-msproject-native-output",
        help=(
            "strictly normalize and compare an actual frozen Microsoft Project MSPDI "
            "output; this command cannot establish the full 45-case gate"
        ),
    )
    analyse.add_argument("--repository-root", type=Path)
    analyse.add_argument("--pilot", default=MSPROJECT_PILOT_ID)
    analyse.add_argument("--case", required=True, choices=MSPROJECT_PILOT_CASE_IDS)
    analyse.add_argument("--track", required=True, choices=MSPROJECT_PILOT_TRACK_IDS)
    analyse.add_argument("--native-output", required=True, type=Path)
    analyse.add_argument("--case-realisation-manifest", required=True, type=Path)
    analyse.add_argument("--sealed-expected", type=Path)
    analyse.add_argument("--environment-capture", required=True, type=Path)
    analyse.add_argument("--post-execution-attestation", required=True, type=Path)
    analyse.add_argument("--post-execution-action-log", required=True, type=Path)
    analyse.add_argument(
        "--prerequisite-manual-case-realization-manifest",
        type=Path,
        help="required only for the saved-file reopen/recalculate track",
    )
    analyse.add_argument(
        "--stage-artifact",
        action="append",
        required=True,
        default=[],
        metavar="ROLE=PATH",
        help=(
            "repeat for every exact track-specific stage role; files are hashed by the analyser"
        ),
    )
    analyse.add_argument(
        "--evidence-artifact",
        action="append",
        required=True,
        default=[],
        metavar="ROLE=PATH",
        help=(
            "repeat for every planned independent screenshot/report evidence role; "
            "raw files remain external and are hash-bound"
        ),
    )
    analyse.add_argument("--output-dir", required=True, type=Path)
    analyse.add_argument("--run-id", required=True)
    analyse.add_argument("--executed-at", required=True)

    stopped = subparsers.add_parser(
        "record-msproject-native-attempt-stop",
        help=(
            "record a fail-closed Microsoft Project attempt stop without creating "
            "native run or claim evidence"
        ),
    )
    stopped.add_argument("--repository-root", type=Path)
    stopped.add_argument("--pilot", default=MSPROJECT_PILOT_ID)
    stopped.add_argument("--case", required=True, choices=MSPROJECT_PILOT_CASE_IDS)
    stopped.add_argument("--track", required=True, choices=MSPROJECT_PILOT_TRACK_IDS)
    stopped.add_argument("--case-realisation-manifest", type=Path)
    stopped.add_argument("--environment-capture", type=Path)
    stopped.add_argument("--stopped-at", required=True)
    stopped.add_argument("--recorded-by", required=True)
    stopped.add_argument(
        "--stop-condition", required=True, choices=MSPROJECT_STOP_CONDITION_IDS
    )
    stopped.add_argument("--reason", required=True)
    stopped.add_argument(
        "--outcome-classification", required=True, choices=MSPROJECT_STOP_OUTCOMES
    )
    stopped.add_argument("--native-calculation-observed", action="store_true")
    stopped.add_argument(
        "--observed-artifact",
        action="append",
        default=[],
        metavar="ROLE=PATH",
        help="repeat for each actually available stopped-attempt artifact",
    )
    stopped.add_argument("--output-dir", required=True, type=Path)
    return parser


def _pilot_kit_path(root: Path) -> Path:
    return root / "native-validation" / "pilot-kits" / MSPROJECT_PILOT_ID


def _print_pilot_summary(summary: dict, *, operation: str) -> None:
    print(f"MICROSOFT PROJECT RELATIONSHIP PILOT {operation}: PASS")
    print(f"- pilot: {summary['pilot_id']}")
    print(f"- status: {summary['status']}")
    print(f"- cases: {summary['case_count']}")
    print(f"- adapter preparation: {summary['adapter_preparation_status']}")
    print(f"- pilot-kit manifest SHA-256: {summary['pilot_kit_manifest_sha256']}")
    print("- Microsoft Project executed: no")
    print("- full 45-case gate satisfied: no")


def _parse_role_paths(values: list[str], *, option: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        role, separator, raw_path = value.partition("=")
        if not separator or not role or not raw_path:
            raise ValueError(f"{option} must use ROLE=PATH")
        if role in result:
            raise ValueError(f"duplicate {option} role {role!r}")
        result[role] = Path(raw_path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = (args.repository_root or find_repository_root()).resolve()
        if args.command == "run-semantic-suite":
            output_dir = args.output_dir or root / "results" / "phase1-semantic-suite"
            run = SemanticSuiteHarness(root).run(
                output_dir=output_dir,
                cases_dir=args.cases_dir,
                catalogue_path=args.catalogue,
                executed_at=args.executed_at,
            )
        elif args.command == "prepare-msproject-relationship-pilot":
            output_dir = args.output_dir or _pilot_kit_path(root)
            summary = prepare_pilot(output_dir, repository_root=root)
            _print_pilot_summary(summary, operation="PREPARATION")
            return 0
        elif args.command == "verify-msproject-relationship-pilot":
            output_dir = args.output_dir or _pilot_kit_path(root)
            summary = verify_pilot(output_dir, repository_root=root)
            _print_pilot_summary(summary, operation="VERIFICATION")
            return 0
        elif args.command == "freeze-msproject-native-input":
            pilot_index_path = _pilot_kit_path(root) / "pilot-index.json"
            pilot_index = load_canonical_json(pilot_index_path, label="pilot index")
            frozen = freeze_msproject_native_input(
                repository_root=root,
                pilot_index=pilot_index,
                pilot_id=args.pilot,
                case_id=args.case,
                track_id=args.track,
                native_file=args.native_file,
                environment_capture_path=args.environment_capture,
                output_dir=args.output_dir,
                prerequisite_manual_case_realization_manifest_path=(
                    args.prerequisite_manual_case_realization_manifest
                ),
                prepared_at=args.prepared_at,
                prepared_by=args.prepared_by,
                independent_pre_execution_reviewed_by=(
                    args.independent_pre_execution_reviewed_by
                ),
                attestation_no_native_result_observed_before_freeze=(
                    args.attest_no_native_result_observed_before_freeze
                ),
            )
            print("MICROSOFT PROJECT NATIVE INPUT FREEZE: PASS")
            print(f"- pilot: {args.pilot}")
            print(f"- case: {args.case}")
            print(f"- track: {args.track}")
            print(f"- manifest SHA-256: {frozen.manifest_sha256}")
            print("- native result observed before freeze: no")
            return 0
        elif args.command == "record-msproject-native-attempt-stop":
            stopped = record_msproject_native_attempt_stop(
                repository_root=root,
                pilot_id=args.pilot,
                case_id=args.case,
                track_id=args.track,
                stopped_at=args.stopped_at,
                recorded_by=args.recorded_by,
                stop_condition_id=args.stop_condition,
                reason=args.reason,
                outcome_classification=args.outcome_classification,
                native_calculation_observed=args.native_calculation_observed,
                output_dir=args.output_dir,
                case_realisation_manifest_path=args.case_realisation_manifest,
                environment_capture_path=args.environment_capture,
                observed_artifact_paths=_parse_role_paths(
                    args.observed_artifact, option="--observed-artifact"
                ),
            )
            print("MICROSOFT PROJECT NATIVE ATTEMPT STOP: RECORDED")
            print(f"- case: {args.case}")
            print(f"- track: {args.track}")
            print(f"- outcome classification: {args.outcome_classification}")
            print(f"- record SHA-256: {stopped.record_sha256}")
            print("- native run evidence created: no")
            print("- claim evidence eligible: no")
            return 0
        elif args.command == "analyse-msproject-native-output":
            manifest = load_canonical_json(
                args.case_realisation_manifest, label="case-realisation manifest"
            )
            for field, expected in (
                ("pilot_id", args.pilot),
                ("case_id", args.case),
                ("execution_track_id", args.track),
            ):
                if manifest.get(field) != expected:
                    raise ValueError(
                        f"case-realisation manifest {field} is {manifest.get(field)!r}, "
                        f"not {expected!r}"
                    )
            sealed_expected = args.sealed_expected or (
                _pilot_kit_path(root)
                / "sealed-expected-normalized"
                / f"{args.case}.json"
            )
            analysis = analyse_msproject_native_output(
                repository_root=root,
                native_output_path=args.native_output,
                case_realisation_manifest_path=args.case_realisation_manifest,
                sealed_expected_path=sealed_expected,
                environment_capture_path=args.environment_capture,
                post_execution_attestation_path=args.post_execution_attestation,
                post_execution_action_log_path=args.post_execution_action_log,
                prerequisite_manual_case_realization_manifest_path=(
                    args.prerequisite_manual_case_realization_manifest
                ),
                stage_artifact_paths=_parse_role_paths(
                    args.stage_artifact, option="--stage-artifact"
                ),
                independent_evidence_artifact_paths=_parse_role_paths(
                    args.evidence_artifact, option="--evidence-artifact"
                ),
                output_dir=args.output_dir,
                run_id=args.run_id,
                executed_at=args.executed_at,
            )
            print("MICROSOFT PROJECT NATIVE OUTPUT ANALYSIS: COMPLETE")
            print(f"- case: {args.case}")
            print(f"- track: {args.track}")
            print(f"- candidate status: {analysis.native_run_record['status']}")
            print("- independent post-execution review: pending")
            print("- full 45-case gate satisfied: no")
            return 0
        else:
            return 2
    except Exception as exc:
        label = args.command.upper().replace("-", " ")
        print(f"{label}: FAIL\n{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.command != "run-semantic-suite":
        return 2
    counts = run.summary["counts"]
    print(
        "PHASE 1 SEMANTIC SUITE: " + ("PASS" if run.passed else "FAIL")
    )
    print(f"- declared reference cases: {counts['executed_pass']}/49 executed_pass")
    print(
        "- native-validation-only cases: "
        f"{counts['native_validation_required']}/1 native_validation_required"
    )
    print(f"- unexplained failures: {counts['executed_fail']}")
    print(f"- portable suite result hash: {run.summary['portable_suite_result_hash']}")
    print(
        "- environment suite evidence hash: "
        f"{run.summary['environment_suite_evidence_hash']}"
    )
    print(f"- evidence directory: {run.output_dir}")
    return 0 if run.passed else 1
