"""Stable connector identities and ownership rules."""

from __future__ import annotations

from enum import StrEnum


class ConnectorProvider(StrEnum):
    SCHOLIGHT = "scholight"
    ANYSEARCH = "anysearch"
    TAVILY = "tavily"
    EXA = "exa"
    FIRECRAWL = "firecrawl"


BUILT_IN_CONNECTOR = ConnectorProvider.SCHOLIGHT
EXTERNAL_CONNECTOR_PROVIDERS = (
    ConnectorProvider.ANYSEARCH,
    ConnectorProvider.TAVILY,
    ConnectorProvider.EXA,
    ConnectorProvider.FIRECRAWL,
)
