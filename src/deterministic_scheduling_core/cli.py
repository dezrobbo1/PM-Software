from __future__ import annotations

import argparse
import sys
from pathlib import Path

from deterministic_scheduling_core.execution import SemanticSuiteHarness


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "run-semantic-suite":
        return 2
    try:
        root = (args.repository_root or find_repository_root()).resolve()
        output_dir = args.output_dir or root / "results" / "phase1-semantic-suite"
        run = SemanticSuiteHarness(root).run(
            output_dir=output_dir,
            cases_dir=args.cases_dir,
            catalogue_path=args.catalogue,
            executed_at=args.executed_at,
        )
    except Exception as exc:
        print(f"PHASE 1 SEMANTIC SUITE: FAIL\n{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
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
