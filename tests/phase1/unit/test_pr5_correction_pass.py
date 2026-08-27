from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from deterministic_scheduling_core.native.msproject import normalizer
from tools.validate_phase0 import _is_canonical_ascii_date
from tools.validate_phase1_governance import (
    REVIEWED_ACTION_PINS,
    _workflow_action_pin_errors,
)


ROOT = Path(__file__).resolve().parents[3]


class WorkflowBlockScalarTests(unittest.TestCase):
    def _pinned(self, action: str) -> str:
        record = REVIEWED_ACTION_PINS[action]
        return f"{action}@{record['sha']} # {record['release_tag']}"

    def test_block_scalar_does_not_hide_sibling_uses(self) -> None:
        workflow = f"""name: probe
on:
  push:
    branches:
      - "**"
jobs:
  probe:
    runs-on: ubuntu-latest
    steps:
      - uses: {self._pinned('actions/checkout')}
      - name: |
          harmless text
        uses: evil/action@v1
      - uses: {self._pinned('actions/setup-python')}
"""
        errors = _workflow_action_pin_errors("probe.yml", workflow)
        self.assertTrue(
            any("evil/action" in error or "unreviewed" in error for error in errors),
            errors,
        )

    def test_folded_scalar_ends_before_next_sequence_item(self) -> None:
        workflow = f"""name: probe
on:
  push:
    branches:
      - "**"
jobs:
  probe:
    runs-on: ubuntu-latest
    steps:
      - uses: {self._pinned('actions/checkout')}
      - name: script
        run: >-
          echo one
          echo two
      - uses: {self._pinned('actions/setup-python')}
"""
        self.assertEqual(_workflow_action_pin_errors("probe.yml", workflow), [])


class CanonicalDateTests(unittest.TestCase):
    def test_real_ascii_iso_dates_only(self) -> None:
        self.assertTrue(_is_canonical_ascii_date("2024-02-29"))
        self.assertTrue(_is_canonical_ascii_date("2026-08-27"))
        for invalid in (
            "2026-02-30",
            "2025-02-29",
            "２０２６-０８-２７",
            "2026-8-27",
            " 2026-08-27",
            "2026-08-27 ",
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(_is_canonical_ascii_date(invalid))


class DurableObservationDispatchTests(unittest.TestCase):
    def test_windows_dispatch_uses_windows_primitive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "observation.json"
            with (
                mock.patch.object(normalizer.os, "name", "nt"),
                mock.patch.object(normalizer, "_write_durable_windows") as windows_write,
                mock.patch.object(normalizer, "_write_durable_posix") as posix_write,
            ):
                normalizer._write_durable_normalized_observation(
                    path, {"value": 1}, label="probe"
                )
            windows_write.assert_called_once()
            posix_write.assert_not_called()


class ProceduralBlindTests(unittest.TestCase):
    def test_public_pilot_declares_non_access_controlled_blinding(self) -> None:
        kit = (
            ROOT
            / "native-validation"
            / "pilot-kits"
            / "microsoft-project-relationship-v0.1"
        )
        runbook = (kit / "operator-runbook.md").read_text(encoding="utf-8")
        self.assertIn("procedural blind", runbook)
        self.assertIn("access-controlled blind", runbook)
        self.assertIn("public repository necessarily contains frozen", runbook)


if __name__ == "__main__":
    unittest.main()
