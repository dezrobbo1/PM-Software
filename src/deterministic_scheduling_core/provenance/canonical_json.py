from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _normalise(value: Any) -> Any:
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        raise TypeError("floating-point values are outside dsc-canonical-json-v1")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalised_key = unicodedata.normalize("NFC", key)
            if normalised_key in result:
                raise ValueError(
                    f"canonical JSON object contains duplicate NFC key {normalised_key!r}"
                )
            result[normalised_key] = _normalise(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_normalise(item) for item in value]
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_text(value: Any) -> str:
    """Return dsc-canonical-json-v1 text.

    The executable domain contains strings, integers, booleans, null, arrays and
    objects only. Strings are NFC-normalised; object keys are sorted; whitespace
    is omitted; and semantic array ordering is prepared by the canonical loader.
    """

    return json.dumps(
        _normalise(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_text(value).encode("utf-8")


def sha256_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_text(value) + "\n", encoding="utf-8", newline="\n")
