from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class RepeatedProcessDeterminismTests(unittest.TestCase):
    def test_three_fresh_processes_have_identical_deterministic_hashes(self) -> None:
        summaries = []
        timestamps = []
        with tempfile.TemporaryDirectory() as temporary:
            for run_number in range(3):
                output = Path(temporary) / f"run-{run_number}"
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "deterministic_scheduling_core",
                        "run-semantic-suite",
                        "--repository-root",
                        str(ROOT),
                        "--output-dir",
                        str(output),
                    ],
                    cwd=ROOT,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                summaries.append(json.loads((output / "suite-summary.json").read_text()))
                record = json.loads(
                    (output / "cases" / "SEM-REL-001" / "execution-record.json").read_text()
                )
                timestamps.append(record["executed_at"])
        self.assertEqual(summaries[0], summaries[1])
        self.assertEqual(summaries[1], summaries[2])
        self.assertNotIn("suite_hash", summaries[0])
        self.assertTrue(summaries[0]["portable_suite_result_hash"])
        self.assertTrue(summaries[0]["environment_suite_evidence_hash"])
        for key in (
            "input_hash",
            "output_hash",
            "portable_semantic_result_hash",
            "environment_evidence_hash",
            "execution_record_hash",
            "validation_hash",
            "explanation_hash",
            "evidence_bundle_hash",
        ):
            self.assertEqual(
                [summaries[0]["cases"][0][key]] * 3,
                [summary["cases"][0][key] for summary in summaries],
            )
        self.assertTrue(all(timestamps))

    def test_execution_record_hash_excludes_only_wall_clock_metadata(self) -> None:
        from deterministic_scheduling_core.provenance.canonical_json import sha256_digest
        from deterministic_scheduling_core.validation import (
            environment_evidence_document,
            execution_record_hash,
            portable_explanation_document,
        )

        record = {"case_id": "CASE", "executed_at": "2026-01-01T00:00:00Z", "status": "pass"}
        changed_time = {**record, "executed_at": "2026-01-02T00:00:00Z"}
        changed_status = {**record, "status": "fail"}
        self.assertEqual(execution_record_hash(record), execution_record_hash(changed_time))
        self.assertNotEqual(execution_record_hash(record), execution_record_hash(changed_status))

        explanation = {
            "case_id": "CASE",
            "recomputation": {"execution_identity": "a" * 64, "validator_status": "pass"},
            "calculation_trace": {"derived_start": 0, "derived_finish": 1},
        }
        changed_environment = json.loads(json.dumps(explanation))
        changed_environment["recomputation"]["execution_identity"] = "b" * 64
        self.assertEqual(
            sha256_digest(portable_explanation_document(explanation)),
            sha256_digest(portable_explanation_document(changed_environment)),
        )
        self.assertNotEqual(sha256_digest(explanation), sha256_digest(changed_environment))

        profile = {"environment_evidence_projection": "phase1-environment-evidence-v0.1"}
        first_environment = environment_evidence_document(
            profile=profile,
            case_id="CASE",
            portable_semantic_result_hash="c" * 64,
            portable_failure_result_hash=None,
            execution_identity_hash="a" * 64,
            explanation_hash="d" * 64,
            evidence_bundle_hash="e" * 64,
            execution_record_hash_value="f" * 64,
        )
        second_environment = {
            **first_environment,
            "execution_identity_hash": "b" * 64,
        }
        self.assertNotEqual(
            sha256_digest(first_environment), sha256_digest(second_environment)
        )
