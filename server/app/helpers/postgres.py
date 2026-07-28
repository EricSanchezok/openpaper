from typing import TypeVar, cast

T = TypeVar("T")


def sanitize_for_postgres(value: T) -> T:
    """Recursively remove null characters that PostgreSQL cannot store."""
    if isinstance(value, str):
        return cast(T, value.replace("\x00", "").replace("\u0000", ""))
    if isinstance(value, dict):
        return cast(
            T, {key: sanitize_for_postgres(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return cast(T, [sanitize_for_postgres(item) for item in value])
    if isinstance(value, tuple):
        return cast(T, tuple(sanitize_for_postgres(item) for item in value))
    return value
