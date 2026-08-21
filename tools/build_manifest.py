from __future__ import annotations

import hashlib
from pathlib import Path

try:
    from .repository_files import repository_paths
except ImportError:  # Direct execution: python tools/build_manifest.py
    from repository_files import repository_paths

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "manifest.sha256"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    paths = repository_paths(ROOT)
    lines = [f"{sha256(ROOT / rel)}  {rel.as_posix()}" for rel in paths]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(lines)} tracked entries to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
