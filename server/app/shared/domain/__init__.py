"""Framework-independent shared domain primitives."""

from .errors import AppError, FailureKind
from .types import JsonScalar, JsonValue

__all__ = ["AppError", "FailureKind", "JsonScalar", "JsonValue"]
