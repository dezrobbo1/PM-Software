"""Microsoft Project pilot evidence and headless-characterisation tooling.

Legacy pilot APIs are exported lazily. Keeping package import side-effect free is
part of the headless native worker's capability boundary: starting that worker
must not eagerly load the oracle-capable pilot or normalizer modules.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORT_GROUPS = {
    ".pilot": (
        "CASE_IDS",
        "PILOT_ID",
        "PILOT_STATUS",
        "TRACK_IDS",
        "PilotBindingError",
        "PilotError",
        "PilotSafetyError",
        "PilotVerificationError",
        "prepare_pilot",
        "prepare_pilot_kit",
        "verify_pilot",
        "verify_pilot_kit",
    ),
    ".freeze": (
        "FrozenNativeInput",
        "NativeEvidenceError",
        "freeze_msproject_native_input",
        "load_canonical_json",
    ),
    ".normalizer": (
        "MSPDI_NAMESPACE",
        "MSPDI_SAVE_VERSION",
        "NativeAnalysis",
        "NativeOutputError",
        "analyse_msproject_native_output",
        "compare_normalized_output",
        "normalize_mspdi_output",
        "validate_native_run_record",
    ),
    ".stopped": (
        "NativeAttemptStopError",
        "STOP_CONDITION_IDS",
        "STOP_OUTCOME_CLASSIFICATIONS",
        "STOP_OUTCOME_BY_CONDITION_AND_NATIVE_CALCULATION",
        "STOP_RECORD_REQUIRED_FIELDS",
        "StoppedNativeAttempt",
        "record_msproject_native_attempt_stop",
    ),
}

_EXPORTS = {
    name: (module_name, name)
    for module_name, names in _EXPORT_GROUPS.items()
    for name in names
}

__all__ = [name for names in _EXPORT_GROUPS.values() for name in names]


def __getattr__(name: str) -> Any:
    """Resolve a public legacy API only when a caller actually requests it."""

    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
