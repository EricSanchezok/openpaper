"""Framework-independent shared domain primitives."""

from .errors import AppError, FailureKind
from .types import JsonScalar, JsonValue
from .workspace_permissions import (
    WORKSPACE_PERMISSION_ORDER,
    WorkspacePermission,
    normalize_workspace_permissions,
    ordered_workspace_permissions,
)

__all__ = [
    "WORKSPACE_PERMISSION_ORDER",
    "AppError",
    "FailureKind",
    "JsonScalar",
    "JsonValue",
    "WorkspacePermission",
    "normalize_workspace_permissions",
    "ordered_workspace_permissions",
]
