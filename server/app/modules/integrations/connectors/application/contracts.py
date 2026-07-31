"""Transport-neutral connector contracts."""

from __future__ import annotations

from datetime import datetime

from app.modules.integrations.connectors.domain import ConnectorProvider
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ConnectorResponse(BaseModel):
    provider: ConnectorProvider
    display_name: str
    built_in: bool
    connected: bool
    enabled: bool
    verified_at: datetime | None = None


class ConnectorListResponse(BaseModel):
    items: list[ConnectorResponse]


class ConnectorConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    api_key: SecretStr = Field(min_length=8, max_length=2_048)


class ConnectorUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
