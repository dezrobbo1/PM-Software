from __future__ import annotations

import json
import unittest
from pathlib import Path
import shutil
import tempfile

from tools import validate_phase1_governance


ROOT = Path(__file__).resolve().parents[3]


class WorkflowGovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow_texts = {
            filename: (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
            for filename in validate_phase1_governance.ACCEPTANCE_WORKFLOWS
        }

    def action_errors(self, text: str) -> list[str]:
        return validate_phase1_governance._workflow_action_pin_errors("workflow.yml", text)

    def test_acceptance_workflows_use_the_exact_reviewed_action_pins(self) -> None:
        for filename, text in self.workflow_texts.items():
            with self.subTest(workflow=filename):
                self.assertEqual(
                    [],
                    validate_phase1_governance._workflow_action_pin_errors(filename, text),
                )

    def test_mutable_action_tag_is_rejected(self) -> None:
        text = self.workflow_texts["validate-phase0.yml"].replace(
            "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
            "actions/checkout@v4",
        )
        self.assertTrue(any("immutable full commit SHA" in error for error in self.action_errors(text)))

    def test_equivalent_yaml_uses_keys_cannot_bypass_action_pin_validation(self) -> None:
        original = self.workflow_texts["validate-phase0.yml"]
        insertion = "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0"
        bypass_candidates = (
            "      - uses : example/action@v1",
            "      - 'uses': example/action@v1",
            '      - "uses": example/action@v1',
            '      - "u\\u0073es": example/action@v1',
            "      - &step uses: example/action@v1",
            "      - {uses: example/action@v1}",
        )
        for candidate in bypass_candidates:
            with self.subTest(candidate=candidate):
                text = original.replace(insertion, f"{insertion}\n{candidate}")
                self.assertTrue(self.action_errors(text))

    def test_combined_unicode_key_and_value_escape_cannot_hide_mutable_action(self) -> None:
        original = self.workflow_texts["validate-phase0.yml"]
        insertion = "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0"
        encoded = '      - "u\\u0073es": "example/action\\u0040v1"'
        errors = self.action_errors(
            original.replace(insertion, f"{insertion}\n{encoded}")
        )
        self.assertTrue(
            any("unreviewed or non-official action" in error for error in errors),
            errors,
        )

    def test_structural_parser_rejects_duplicate_and_unsupported_yaml(self) -> None:
        original = self.workflow_texts["validate-phase0.yml"]
        checkout = "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0"
        duplicate = (
            "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0\n"
            "        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0"
        )
        self.assertTrue(
            any(
                "workflow YAML parse failed closed" in error
                for error in self.action_errors(original.replace(checkout, duplicate))
            )
        )
        anchored = original.replace(checkout, f"{checkout}\n      - &hidden uses: example/action@v1")
        self.assertTrue(
            any(
                "workflow YAML parse failed closed" in error
                for error in self.action_errors(anchored)
            )
        )

    def test_action_shaped_text_inside_run_block_is_not_an_action_step(self) -> None:
        original = self.workflow_texts["validate-phase1.yml"]
        marker = "          git diff --check"
        script_only = original.replace(
            marker,
            marker + "\n          printf '%s\\n' 'example/action@v1'",
        )
        self.assertEqual([], self.action_errors(script_only))

    def test_abbreviated_and_unreviewed_action_commits_are_rejected(self) -> None:
        original = self.workflow_texts["validate-phase0.yml"]
        abbreviated = original.replace(
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            "actions/setup-python@a26af69",
        )
        self.assertTrue(
            any("immutable full commit SHA" in error for error in self.action_errors(abbreviated))
        )
        mismatched = original.replace(
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            f"actions/setup-python@{'0' * 40}",
        )
        self.assertTrue(
            any("does not use the reviewed commit SHA" in error for error in self.action_errors(mismatched))
        )

    def test_non_official_action_is_rejected_even_at_a_full_sha(self) -> None:
        text = self.workflow_texts["validate-phase0.yml"].replace(
            "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
            "example/checkout@11d5960a326750d5838078e36cf38b85af677262",
        )
        self.assertTrue(
            any("unreviewed or non-official action" in error for error in self.action_errors(text))
        )

    def test_reviewed_release_tag_comment_is_required(self) -> None:
        text = self.workflow_texts["validate-phase0.yml"].replace(" # v4.4.0", "")
        self.assertTrue(
            any("reviewed release tag comment v4.4.0" in error for error in self.action_errors(text))
        )

    def test_push_covers_feature_branches_while_pull_requests_target_main(self) -> None:
        for filename, text in self.workflow_texts.items():
            with self.subTest(workflow=filename):
                self.assertEqual(
                    [],
                    validate_phase1_governance._workflow_trigger_errors(filename, text),
                )
        main_only_push = self.workflow_texts["validate-phase0.yml"].replace(
            '      - "**"',
            "      - main",
            1,
        )
        self.assertTrue(
            validate_phase1_governance._workflow_trigger_errors(
                "validate-phase0.yml", main_only_push
            )
        )

    def test_tracked_pilot_has_the_exact_prepared_file_set(self) -> None:
        self.assertEqual(
            [],
            validate_phase1_governance.validate_msproject_relationship_pilot(ROOT),
        )

    def test_pilot_input_identity_is_recomputed_from_live_mapping_bytes(self) -> None:
        tracked_kit = (
            ROOT
            / "native-validation"
            / "pilot-kits"
            / validate_phase1_governance.MSPROJECT_PILOT_ID
        )
        baseline_projection, baseline_digest = (
            validate_phase1_governance.recompute_msproject_pilot_input_identity(
                ROOT, tracked_kit
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            copied_kit = Path(temporary) / "pilot-kit"
            copied_kit.mkdir()
            mapping = copied_kit / "mapping-source-register.json"
            shutil.copyfile(tracked_kit / mapping.name, mapping)
            shutil.copytree(
                tracked_kit / "source-only-case-projections",
                copied_kit / "source-only-case-projections",
            )
            copied_projection, copied_digest = (
                validate_phase1_governance.recompute_msproject_pilot_input_identity(
                    ROOT, copied_kit
                )
            )
            self.assertEqual(baseline_projection, copied_projection)
            self.assertEqual(baseline_digest, copied_digest)
            mapping.write_bytes(mapping.read_bytes() + b"\n")
            mutated_projection, mutated_digest = (
                validate_phase1_governance.recompute_msproject_pilot_input_identity(
                    ROOT, copied_kit
                )
            )
        self.assertNotEqual(baseline_projection, mutated_projection)
        self.assertNotEqual(baseline_digest, mutated_digest)

    def test_pilot_input_identity_is_recomputed_from_source_only_projection_bytes(self) -> None:
        tracked_kit = (
            ROOT
            / "native-validation"
            / "pilot-kits"
            / validate_phase1_governance.MSPROJECT_PILOT_ID
        )
        baseline_projection, baseline_digest = (
            validate_phase1_governance.recompute_msproject_pilot_input_identity(
                ROOT, tracked_kit
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            copied_kit = Path(temporary) / "pilot-kit"
            shutil.copytree(tracked_kit, copied_kit)
            projection = (
                copied_kit
                / "source-only-case-projections"
                / "SEM-REL-001.json"
            )
            projection.write_bytes(projection.read_bytes() + b"\n")
            mutated_projection, mutated_digest = (
                validate_phase1_governance.recompute_msproject_pilot_input_identity(
                    ROOT, copied_kit
                )
            )
        self.assertNotEqual(baseline_projection, mutated_projection)
        self.assertNotEqual(baseline_digest, mutated_digest)

    def test_operator_index_rejects_a_reintroduced_seal_binding(self) -> None:
        tracked_kit = (
            ROOT
            / "native-validation"
            / "pilot-kits"
            / validate_phase1_governance.MSPROJECT_PILOT_ID
        )
        with tempfile.TemporaryDirectory() as temporary:
            copied_kit = Path(temporary) / "pilot-kit"
            shutil.copytree(tracked_kit, copied_kit)
            index_path = copied_kit / "pilot-index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["cases"][0]["sealed_expected_normalized"] = {
                "relative_path": "sealed-expected-normalized/SEM-REL-001.json",
                "sha256": "0" * 64,
            }
            index_path.write_text(json.dumps(index), encoding="utf-8")
            errors = validate_phase1_governance.validate_msproject_pilot_oracle_blinding(
                ROOT, copied_kit
            )
        self.assertTrue(
            any("sealed-control binding alias" in error for error in errors), errors
        )

    def test_operator_manifest_rejects_a_reintroduced_control_reference(self) -> None:
        tracked_kit = (
            ROOT
            / "native-validation"
            / "pilot-kits"
            / validate_phase1_governance.MSPROJECT_PILOT_ID
        )
        with tempfile.TemporaryDirectory() as temporary:
            copied_kit = Path(temporary) / "pilot-kit"
            shutil.copytree(tracked_kit, copied_kit)
            manifest_path = copied_kit / "pilot-kit-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"].append(
                {
                    "relative_path": "sealed-expected-normalized/SEM-REL-001.json",
                    "sha256": "0" * 64,
                    "byte_size": 1,
                    "media_type": "application/json",
                }
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            errors = validate_phase1_governance.validate_msproject_pilot_oracle_blinding(
                ROOT, copied_kit
            )
        self.assertTrue(
            any("operator-visible pilot bytes expose" in error for error in errors),
            errors,
        )


if __name__ == "__main__":
    unittest.main()
