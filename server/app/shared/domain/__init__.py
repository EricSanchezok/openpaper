"""Framework-independent shared domain primitives."""

from .errors import AppError
from .types import JsonScalar, JsonValue

__all__ = ["AppError", "JsonScalar", "JsonValue"]
