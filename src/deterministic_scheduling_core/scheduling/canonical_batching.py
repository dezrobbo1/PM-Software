"""Exact, integer-safe mixed-radix blocks for ordered canonical digits."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

MAX_SAFE_BLOCK_VALUE = (1 << 60) - 1


@dataclass(frozen=True)
class CanonicalDigit:
    name: str
    maximum: int


@dataclass(frozen=True)
class CanonicalBlock:
    name: str
    digits: tuple[CanonicalDigit, ...]
    coefficients: tuple[int, ...]
    maximum: int
    safety_bound: int

    def to_document(self) -> dict:
        return {
            "name": self.name,
            "digits": [
                {"name": digit.name, "maximum": digit.maximum, "coefficient": coefficient}
                for digit, coefficient in zip(self.digits, self.coefficients)
            ],
            "maximum_possible_value": self.maximum,
            "integer_safety_bound": self.safety_bound,
        }


def _finish_block(index: int, digits: list[CanonicalDigit], safety_bound: int) -> CanonicalBlock:
    coefficients = []
    coefficient = 1
    for digit in reversed(digits):
        coefficients.append(coefficient)
        coefficient *= digit.maximum + 1
    coefficients.reverse()
    return CanonicalBlock(
        f"canonical_block:{index:03d}", tuple(digits), tuple(coefficients),
        coefficient - 1, safety_bound,
    )


def build_lexicographic_blocks(
    digits: Iterable[CanonicalDigit], *, safety_bound: int = MAX_SAFE_BLOCK_VALUE,
) -> tuple[CanonicalBlock, ...]:
    """Greedily group adjacent digits without losing lexicographic significance.

    A more-significant coefficient exceeds every possible lower-digit contribution.
    Complete block values stay inside the conservative integer safety bound.
    """
    if type(safety_bound) is not int or safety_bound < 0 or safety_bound > MAX_SAFE_BLOCK_VALUE:
        raise ValueError(f"safety_bound must be an integer in 0..{MAX_SAFE_BLOCK_VALUE}")
    blocks: list[CanonicalBlock] = []
    current: list[CanonicalDigit] = []
    current_maximum = 0
    seen = set()
    for digit in digits:
        if (not isinstance(digit, CanonicalDigit) or not isinstance(digit.name, str)
                or not digit.name or type(digit.maximum) is not int or digit.maximum < 0):
            raise ValueError("canonical digits need a unique name and nonnegative integer maximum")
        if digit.name in seen:
            raise ValueError("canonical digit names must be unique")
        seen.add(digit.name)
        if digit.maximum > safety_bound:
            raise ValueError(f"{digit.name}: digit maximum exceeds the integer safety bound")
        candidate = digit.maximum if not current else (
            (current_maximum + 1) * (digit.maximum + 1) - 1
        )
        if current and candidate > safety_bound:
            blocks.append(_finish_block(len(blocks), current, safety_bound))
            current = [digit]
            current_maximum = digit.maximum
        else:
            current.append(digit)
            current_maximum = candidate
    if current:
        blocks.append(_finish_block(len(blocks), current, safety_bound))
    if any(block.maximum > safety_bound for block in blocks):
        raise ValueError("internal error: unsafe canonical block")
    return tuple(blocks)
