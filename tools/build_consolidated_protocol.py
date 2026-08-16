from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = ROOT / "PHASE-0-PROTOCOL-CONSOLIDATED.md"
HEADER = (
    "# Deterministic Scheduling Core — Phase 0 Protocol\n\n"
    "This consolidated review document mirrors the authoritative files in this bundle. "
    "The individual files remain the change-controlled source.\n\n\n---\n\n"
)


def render() -> str:
    sources = sorted(DOCS.glob("[0-9][0-9]-*.md"))
    if not sources:
        raise RuntimeError("No numbered protocol documents found")
    return HEADER + "\n\n---\n\n".join(path.read_text(encoding="utf-8").strip() for path in sources) + "\n"


def main() -> int:
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"Wrote consolidated protocol from {len(list(DOCS.glob('[0-9][0-9]-*.md')))} source documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
