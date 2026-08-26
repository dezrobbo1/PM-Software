from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from deterministic_scheduling_core import cli
from deterministic_scheduling_core.provenance.canonical_json import write_canonical_json


ROOT = Path(__file__).resolve().parents[3]


class MicrosoftProjectPilotCliTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "deterministic_scheduling_core", *arguments],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_help_exposes_all_preparation_and_evidence_commands(self) -> None:
        result = self.run_cli("--help")
        self.assertEqual(0, result.returncode, result.stderr)
        for command in (
            "prepare-msproject-relationship-pilot",
            "verify-msproject-relationship-pilot",
            "freeze-msproject-native-input",
            "record-msproject-native-attempt-stop",
            "analyse-msproject-native-output",
        ):
            self.assertIn(command, result.stdout)

    def test_prepare_and_verify_commands_preserve_prepared_only_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pilot"
            prepared = self.run_cli(
                "prepare-msproject-relationship-pilot",
                "--repository-root",
                str(ROOT),
                "--output-dir",
                str(output),
            )
            self.assertEqual(0, prepared.returncode, prepared.stderr)
            self.assertIn("status: prepared_not_executed", prepared.stdout)
            self.assertIn("adapter preparation: preparation_blocked", prepared.stdout)
            self.assertIn("Microsoft Project executed: no", prepared.stdout)

            verified = self.run_cli(
                "verify-msproject-relationship-pilot",
                "--repository-root",
                str(ROOT),
                "--output-dir",
                str(output),
            )
            self.assertEqual(0, verified.returncode, verified.stderr)
            self.assertIn("VERIFICATION: PASS", verified.stdout)
            self.assertIn("full 45-case gate satisfied: no", verified.stdout)

    def test_analysis_dispatches_action_log_and_unique_evidence_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "manifest.json"
            write_canonical_json(
                manifest,
                {
                    "pilot_id": "microsoft-project-relationship-v0.1",
                    "case_id": "SEM-REL-001",
                    "execution_track_id": "manual_native_semantic_parity",
                },
            )
            with patch.object(
                cli,
                "analyse_msproject_native_output",
                return_value=SimpleNamespace(
                    native_run_record={"status": "executed_inconclusive"}
                ),
            ) as analyser:
                result = cli.main(
                    [
                        "analyse-msproject-native-output",
                        "--repository-root",
                        str(ROOT),
                        "--case",
                        "SEM-REL-001",
                        "--track",
                        "manual_native_semantic_parity",
                        "--native-output",
                        str(root / "output.xml"),
                        "--case-realisation-manifest",
                        str(manifest),
                        "--sealed-expected",
                        str(root / "sealed.json"),
                        "--environment-capture",
                        str(root / "environment.json"),
                        "--post-execution-attestation",
                        str(root / "attestation.json"),
                        "--post-execution-action-log",
                        str(root / "actions.json"),
                        "--prerequisite-manual-case-realization-manifest",
                        str(root / "prerequisite.json"),
                        "--stage-artifact",
                        f"native_calculated_file_sha256={root / 'calculated.mpp'}",
                        "--evidence-artifact",
                        f"task_table={root / 'task-table.png'}",
                        "--output-dir",
                        str(root / "analysis"),
                        "--run-id",
                        "test-run",
                        "--executed-at",
                        "2026-08-26T11:00:00+08:00",
                    ]
                )
            self.assertEqual(result, 0)
            kwargs = analyser.call_args.kwargs
            self.assertEqual(kwargs["post_execution_action_log_path"], root / "actions.json")
            self.assertEqual(
                kwargs[
                    "prerequisite_manual_case_realization_manifest_path"
                ],
                root / "prerequisite.json",
            )
            self.assertEqual(
                kwargs["independent_evidence_artifact_paths"],
                {"task_table": root / "task-table.png"},
            )

            duplicate = cli.main(
                [
                    "analyse-msproject-native-output",
                    "--repository-root",
                    str(ROOT),
                    "--case",
                    "SEM-REL-001",
                    "--track",
                    "manual_native_semantic_parity",
                    "--native-output",
                    str(root / "output.xml"),
                    "--case-realisation-manifest",
                    str(manifest),
                    "--environment-capture",
                    str(root / "environment.json"),
                    "--post-execution-attestation",
                    str(root / "attestation.json"),
                    "--post-execution-action-log",
                    str(root / "actions.json"),
                    "--stage-artifact",
                    f"native_calculated_file_sha256={root / 'calculated.mpp'}",
                    "--evidence-artifact",
                    f"task_table={root / 'one.png'}",
                    "--evidence-artifact",
                    f"task_table={root / 'two.png'}",
                    "--output-dir",
                    str(root / "analysis-two"),
                    "--run-id",
                    "test-run-two",
                    "--executed-at",
                    "2026-08-26T11:00:00+08:00",
                ]
            )
            self.assertEqual(duplicate, 1)

    def test_stopped_attempt_dispatch_is_explicitly_nonclaimable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observed = root / "observed.xml"
            with patch.object(
                cli,
                "record_msproject_native_attempt_stop",
                return_value=SimpleNamespace(record_sha256="a" * 64),
            ) as recorder:
                result = cli.main(
                    [
                        "record-msproject-native-attempt-stop",
                        "--repository-root",
                        str(ROOT),
                        "--case",
                        "SEM-REL-001",
                        "--track",
                        "manual_native_semantic_parity",
                        "--stopped-at",
                        "2026-08-26T11:00:00+08:00",
                        "--recorded-by",
                        "operator-001",
                        "--stop-condition",
                        "relationship_or_lag_transformed",
                        "--reason",
                        "Synthetic CLI dispatch test only.",
                        "--outcome-classification",
                        "executed_fail",
                        "--native-calculation-observed",
                        "--observed-artifact",
                        f"native_export={observed}",
                        "--output-dir",
                        str(root / "stop-record"),
                    ]
                )
            self.assertEqual(result, 0)
            kwargs = recorder.call_args.kwargs
            self.assertTrue(kwargs["native_calculation_observed"])
            self.assertEqual(kwargs["observed_artifact_paths"], {"native_export": observed})
            self.assertIsNone(kwargs["case_realisation_manifest_path"])
            self.assertIsNone(kwargs["environment_capture_path"])


if __name__ == "__main__":
    unittest.main()
