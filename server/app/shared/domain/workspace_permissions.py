"""Transport-neutral workspace tool permissions."""

from collections.abc import Iterable
from enum import StrEnum


class WorkspacePermission(StrEnum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"


WORKSPACE_PERMISSION_ORDER = (
    WorkspacePermission.READ,
    WorkspacePermission.WRITE,
    WorkspacePermission.DELETE,
)


def normalize_workspace_permissions(
    values: Iterable[WorkspacePermission | str],
) -> frozenset[WorkspacePermission]:
    """Parse and deduplicate workspace permissions."""

    return frozenset(WorkspacePermission(value) for value in values)


def ordered_workspace_permissions(
    values: Iterable[WorkspacePermission | str],
) -> list[WorkspacePermission]:
    """Return normalized permissions in the public canonical order."""

    normalized = normalize_workspace_permissions(values)
    return [
        permission
        for permission in WORKSPACE_PERMISSION_ORDER
        if permission in normalized
    ]
