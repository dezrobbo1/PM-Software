from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "manifest.sha256"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


files = [
    p for p in ROOT.rglob("*")
    if p.is_file() and p != OUT and "__pycache__" not in p.parts
]
lines = [f"{sha256(p)}  {p.relative_to(ROOT).as_posix()}" for p in sorted(files)]
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"Wrote {len(lines)} entries to {OUT}")
