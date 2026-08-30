from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from deterministic_scheduling_core.native.msproject.normalizer import (
    NativeOutputError,
    _write_durable_normalized_observation,
)
from deterministic_scheduling_core.native.msproject.headless_com import (
    ProjectNotInstalledError,
    registered_project_executable,
)


if os.name != "nt":
    raise RuntimeError("windows_native_smoke.py must run on a Windows host")


class WindowsNativeDurabilitySmoke(unittest.TestCase):
    def test_exclusive_write_through_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "normalized-native-output.json"
            document = {"schema_version": "smoke-v0.1", "value": 1}
            _write_durable_normalized_observation(path, document, label="Windows smoke")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), document)
            with self.assertRaises(NativeOutputError):
                _write_durable_normalized_observation(
                    path, document, label="Windows overwrite smoke"
                )

    def test_project_registration_detection_is_read_only(self) -> None:
        try:
            executable = registered_project_executable()
        except ProjectNotInstalledError as error:
            self.skipTest(f"actual Microsoft Project execution is unavailable in CI: {error}")
        self.assertEqual("WINPROJ.EXE", executable.name.upper())
        self.assertTrue(executable.is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
