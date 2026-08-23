"""Bounded deterministic scheduling-core research prototype."""

from .errors import (
    CanonicalValidationError,
    SchedulingError,
    UnsupportedSemanticError,
    ValidationFailure,
)

__all__ = [
    "CanonicalValidationError",
    "SchedulingError",
    "UnsupportedSemanticError",
    "ValidationFailure",
]

__version__ = "0.2.0"
KERNEL_VERSION = "reference-cpm-kernel-v0.1.0"
DETERMINISTIC_PROFILE = "deterministic-v0.2"
SEMANTIC_PROFILE = "reference-v0.3"
OBJECTIVE_POLICY = "objective-v0.3"
