from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class LoadedCase:
    case_id: str
    path: Path
    document: dict[str, Any]
    schedule: dict[str, Any]
    expected: dict[str, Any]
    input_hash: str
    fixture_hash: str
