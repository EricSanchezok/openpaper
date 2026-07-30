"""Validated tool definitions and independently selectable profiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from app.tooling.contracts import (
    ToolAccess,
    ToolDefinition,
    ToolExecutionKind,
)

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

    def _profile(self, profile_name: str) -> ToolProfile:
        try:
            return self._profiles[profile_name]
        except KeyError as exc:
            raise KeyError(f"unknown tool profile: {profile_name}") from exc

    @staticmethod
    def _is_authorized(
        definition: ToolDefinition[CapabilitiesT],
        access: ToolAccess,
    ) -> bool:
        return (
            definition.execution is ToolExecutionKind.CONTROL
            or definition.required_permission in access.permissions
        )

    def definitions_for(
        self,
        access: ToolAccess,
    ) -> list[ToolDefinition[CapabilitiesT]]:
        profile = self._profile(access.profile_name)
        return [
            definition
            for name in sorted(profile.tool_names)
            if self._is_authorized(
                definition := self._definitions[name],
                access,
            )
        ]

    def definition_for(
        self,
        access: ToolAccess,
        name: str,
    ) -> ToolDefinition[CapabilitiesT]:
        profile = self._profile(access.profile_name)
        if name not in profile.tool_names:
            raise KeyError(f"tool unavailable: {name}")
        definition = self._definitions[name]
        if not self._is_authorized(definition, access):
            raise KeyError(f"tool unavailable: {name}")
        return definition

    def is_available(self, access: ToolAccess, name: str) -> bool:
        try:
            self.definition_for(access, name)
        except KeyError:
            return False
        return True

    def provider_declarations(self, access: ToolAccess) -> list[dict[str, object]]:
        return [
            {
                "name": definition.name,
                "description": definition.description,
                "parameters": definition.input_model.model_json_schema(),
            }
            for definition in self.definitions_for(access)
        ]
