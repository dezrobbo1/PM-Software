from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

MANIFEST_NAME = "manifest.sha256"
_EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}
_EXCLUDED_FILE_NAMES = {MANIFEST_NAME, ".DS_Store"}


def _safe_relative_path(raw: str) -> PurePosixPath:
    rel = PurePosixPath(raw)
    if rel.is_absolute() or not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError(f"Unsafe repository-relative path: {raw!r}")
    return rel


def _git_tracked_paths(root: Path) -> list[PurePosixPath] | None:
    """Return tracked paths when *root* is a Git worktree, otherwise ``None``."""

    try:
        probe = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        return None
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return None

    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    paths: list[PurePosixPath] = []
    for raw in result.stdout.decode("utf-8").split("\0"):
        if not raw:
            continue
        rel = _safe_relative_path(raw)
        if rel.name in _EXCLUDED_FILE_NAMES:
            continue
        if any(part in _EXCLUDED_DIR_NAMES for part in rel.parts):
            continue
        paths.append(rel)
    return sorted(set(paths), key=lambda p: p.as_posix())


def _archive_paths(root: Path) -> list[PurePosixPath]:
    """Deterministic fallback for a source archive without Git metadata."""

    paths: list[PurePosixPath] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = _safe_relative_path(path.relative_to(root).as_posix())
        if rel.name in _EXCLUDED_FILE_NAMES:
            continue
        if any(part in _EXCLUDED_DIR_NAMES for part in rel.parts):
            continue
        paths.append(rel)
    return sorted(set(paths), key=lambda p: p.as_posix())


def repository_paths(root: Path) -> list[PurePosixPath]:
    """Return the exact file set covered by ``manifest.sha256``.

    In a Git worktree this is the tracked file set, excluding the manifest itself.
    In a source archive it is the deterministic non-metadata file set.
    """

    root = root.resolve()
    tracked = _git_tracked_paths(root)
    paths = tracked if tracked is not None else _archive_paths(root)

    missing = [rel.as_posix() for rel in paths if not (root / rel).is_file()]
    if missing:
        raise FileNotFoundError(f"Tracked repository files are missing: {', '.join(missing)}")
    return paths
