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
        for key in (
            "input_hash",
            "output_hash",
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
        from deterministic_scheduling_core.validation import execution_record_hash

        record = {"case_id": "CASE", "executed_at": "2026-01-01T00:00:00Z", "status": "pass"}
        changed_time = {**record, "executed_at": "2026-01-02T00:00:00Z"}
        changed_status = {**record, "status": "fail"}
        self.assertEqual(execution_record_hash(record), execution_record_hash(changed_time))
        self.assertNotEqual(execution_record_hash(record), execution_record_hash(changed_status))
