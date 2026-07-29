"""Recursive JSON value types shared by application contracts and adapters."""

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
