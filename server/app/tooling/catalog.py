"""Validated tool definitions and independently selectable profiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from app.tooling.contracts import ToolDefinition

CapabilitiesT = TypeVar("CapabilitiesT")


@dataclass(frozen=True, slots=True)
class ToolProfile:
    name: str
    tool_names: frozenset[str]


class ToolCatalog(Generic[CapabilitiesT]):
    def __init__(
        self,
        definitions: list[ToolDefinition[CapabilitiesT]],
        profiles: list[ToolProfile],
    ) -> None:
        self._definitions: dict[str, ToolDefinition[CapabilitiesT]] = {}
        for definition in definitions:
            if definition.name in self._definitions:
                raise ValueError(f"duplicate tool definition: {definition.name}")
            if not definition.description.strip():
                raise ValueError(f"tool {definition.name} requires a description")
            schema = definition.input_model.model_json_schema()
            if schema.get("type") != "object":
                raise ValueError(
                    f"tool {definition.name} input schema must be an object"
                )
            self._definitions[definition.name] = definition
        self._profiles: dict[str, ToolProfile] = {}
        for profile in profiles:
            if profile.name in self._profiles:
                raise ValueError(f"duplicate tool profile: {profile.name}")
            missing = profile.tool_names.difference(self._definitions)
            if missing:
                raise ValueError(
                    f"profile {profile.name} references missing tools: "
                    f"{', '.join(sorted(missing))}"
                )
            self._profiles[profile.name] = profile

    def definition(self, name: str) -> ToolDefinition[CapabilitiesT]:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def definitions_for(self, profile_name: str) -> list[ToolDefinition[CapabilitiesT]]:
        try:
            profile = self._profiles[profile_name]
        except KeyError as exc:
            raise KeyError(f"unknown tool profile: {profile_name}") from exc
        return [self._definitions[name] for name in sorted(profile.tool_names)]

    def provider_declarations(self, profile_name: str) -> list[dict[str, object]]:
        return [
            {
                "name": definition.name,
                "description": definition.description,
                "parameters": definition.input_model.model_json_schema(),
            }
            for definition in self.definitions_for(profile_name)
        ]
