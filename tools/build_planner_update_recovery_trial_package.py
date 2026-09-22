"""Build the deterministic owner-ready Planner Update & Recovery Trial v1 ZIP."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import zipfile

from deterministic_scheduling_core.native_planning_ui.trial import TRIAL_ID, new_trial_workspace

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "trials" / TRIAL_ID
DOC_NAMES = (
    "README.md", "participant-brief.md", "scenario-brief.md",
    "facilitator-observation.md", "questionnaire.md", "exit-gate.md", "deployment.md",
)


def source_sha(explicit: str | None) -> str:
    if explicit:
        return explicit
    for key in ("GITHUB_SHA", "VERCEL_GIT_COMMIT_SHA", "PM_BUILD_SHA"):
        if os.environ.get(key):
            return os.environ[key]
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def build(output: Path, sha: str) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    files = {name: (DOCS / name).read_bytes() for name in DOC_NAMES}
    workspace_name = "pristine-starting-workspace.pm-workspace.json"
    files[workspace_name] = (json.dumps(new_trial_workspace(), indent=2, ensure_ascii=False) + "\n").encode()
    manifest = {
        "trial_id": TRIAL_ID,
        "source_sha": sha,
        "architecture": "stateless hosted requests; portable browser-downloaded native workspace",
        "reset": "Select Start trial to load the pristine approved plan in the current browser.",
        "save_reopen": "Save workspace, then Open workspace in a fresh browser context; no silent calculation or approval.",
        "files": {name: sha256(content).hexdigest() for name, content in sorted(files.items())},
    }
    files["BUILD-SOURCE-MANIFEST.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    destination = output / f"{TRIAL_ID}-{sha}.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(f"{TRIAL_ID}/{name}", (2026, 9, 22, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha")
    args = parser.parse_args()
    destination = build(args.output, source_sha(args.source_sha))
    print(destination)
    print(sha256(destination.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
