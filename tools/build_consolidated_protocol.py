from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_NAME = "PHASE-0-PROTOCOL-CONSOLIDATED.md"
AUTHORITATIVE_CHAPTERS = (
    "00-source-basis.md",
    "01-prototype-scope.md",
    "02-semantic-contract.md",
    "03-canonical-schedule-model.md",
    "04-deterministic-contract.md",
    "05-objective-policy.md",
    "06-benchmark-protocol.md",
    "07-comparator-protocol.md",
    "08-data-access-and-anonymisation.md",
    "09-decision-gates-and-stop-conditions.md",
    "10-change-control.md",
    "11-phase-1-entry-plan.md",
)
HEADER = (
    "# Deterministic Scheduling Core — Phase 0 Protocol\n\n"
    "This consolidated review document mirrors the authoritative files in this bundle. "
    "The individual files remain the change-controlled source.\n\n\n---\n\n"
)


def authoritative_sources(root: Path = ROOT) -> list[Path]:
    docs = root / "docs"
    discovered = {path.name for path in docs.glob("[0-9][0-9]-*.md")}
    expected = set(AUTHORITATIVE_CHAPTERS)
    missing = sorted(expected - discovered)
    unexpected = sorted(discovered - expected)
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        raise RuntimeError("Authoritative protocol chapter set mismatch (" + "; ".join(details) + ")")
    return [docs / name for name in AUTHORITATIVE_CHAPTERS]


def render(root: Path = ROOT) -> str:
    sources = authoritative_sources(root)
    return HEADER + "\n\n---\n\n".join(
        path.read_text(encoding="utf-8").strip() for path in sources
    ) + "\n"


def main() -> int:
    out = ROOT / OUT_NAME
    out.write_text(render(ROOT), encoding="utf-8", newline="\n")
    print(f"Wrote consolidated protocol from {len(AUTHORITATIVE_CHAPTERS)} source documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
