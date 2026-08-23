from __future__ import annotations


class DeterministicSchedulingError(Exception):
    """Base error for the bounded reference implementation."""


class CanonicalValidationError(DeterministicSchedulingError):
    """A canonical input failed schema or reference validation."""

    def __init__(self, errors: list[str] | tuple[str, ...]):
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


class UnsupportedSemanticError(DeterministicSchedulingError):
    """A preserved canonical field is outside reference-v0.3 execution."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class SchedulingError(DeterministicSchedulingError):
    """The supported model could not produce a complete reference result."""


class ValidationFailure(DeterministicSchedulingError):
    """Calculated evidence failed independent validation."""
