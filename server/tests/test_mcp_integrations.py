from __future__ import annotations

import base64
from datetime import datetime, timezone

import httpx
import jwt
import pytest
from app.modules.integrations.connectors.application.ports import ConnectorCredential
from app.modules.integrations.connectors.domain import ConnectorProvider
from app.modules.integrations.connectors.infrastructure.mcp import (
    ConnectorToolResolver,
    _PROVIDER_DEFINITIONS,
    _ConnectorToolsInvalid,
    _bounded_tool_description,
    _exception_contains,
    _external_connection,
    _looks_like_authentication_error,
    _normalize_json_schema,
    _normalize_result,
    _scholight_delegation_headers,
)
from app.modules.integrations.connectors.infrastructure.secrets import (
    AesGcmConnectorCredentialCipher,
)
from app.shared.application import Actor
from app.shared.domain import WorkspacePermission


class _Settings:
    scholight_mcp_url = "https://scholight.example/mcp"
    scholight_mcp_delegation_jwt_secret: str | None = None


class _ScholightSettings:
    scholight_mcp_url = "https://scholight.example/mcp"
    scholight_mcp_delegation_jwt_secret = "s" * 32


def _actor(user_id: int = 42) -> Actor:
    return Actor(
        id=user_id,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _cipher() -> AesGcmConnectorCredentialCipher:
    encoded = base64.urlsafe_b64encode(b"k" * 32).decode()
    return AesGcmConnectorCredentialCipher(encoded)


def test_connector_credentials_are_bound_to_user_and_provider() -> None:
    cipher = _cipher()
    encrypted = cipher.encrypt(
        user_id=42,
        provider=ConnectorProvider.EXA,
        plaintext="secret-api-key",
    )

    assert (
        cipher.decrypt(
            user_id=42,
            provider=ConnectorProvider.EXA,
            ciphertext=encrypted,
        )
        == "secret-api-key"
    )
    with pytest.raises(ValueError, match="credential decryption failed"):
        cipher.decrypt(
            user_id=43,
            provider=ConnectorProvider.EXA,
            ciphertext=encrypted,
        )
    with pytest.raises(ValueError, match="credential decryption failed"):
        cipher.decrypt(
            user_id=42,
            provider=ConnectorProvider.TAVILY,
            ciphertext=encrypted,
        )


@pytest.mark.parametrize(
    ("provider", "url", "headers"),
    [
        (
            ConnectorProvider.ANYSEARCH,
            "https://api.anysearch.com/mcp",
            {"Authorization": "Bearer api-key"},
        ),
        (
            ConnectorProvider.TAVILY,
            "https://mcp.tavily.com/mcp/",
            {"Authorization": "Bearer api-key"},
        ),
        (
            ConnectorProvider.EXA,
            "https://mcp.exa.ai/mcp",
            {"x-api-key": "api-key"},
        ),
        (
            ConnectorProvider.FIRECRAWL,
            "https://mcp.firecrawl.dev/api-key/v2/mcp",
            {},
        ),
    ],
)
def test_external_provider_auth_is_data_driven(
    provider: ConnectorProvider,
    url: str,
    headers: dict[str, str],
) -> None:
    connection = _external_connection(
        _PROVIDER_DEFINITIONS[provider],
        api_key="api-key",
        revision="test",
    )

    assert connection.url == url
    assert dict(connection.headers) == headers


def test_firecrawl_key_is_safely_encoded_in_fixed_endpoint() -> None:
    connection = _external_connection(
        _PROVIDER_DEFINITIONS[ConnectorProvider.FIRECRAWL],
        api_key="key/with?delimiters",
        revision="test",
    )

    assert connection.url == (
        "https://mcp.firecrawl.dev/key%2Fwith%3Fdelimiters/v2/mcp"
    )
    assert "key/with?delimiters" not in repr(connection)


def test_long_remote_description_is_bounded_instead_of_rejecting_connector() -> None:
    description = "x" * 12_000

    assert len(_bounded_tool_description(description)) == 8_000


def test_nested_mcp_errors_preserve_authentication_and_schema_semantics() -> None:
    request = httpx.Request("POST", "https://connector.example/mcp")
    response = httpx.Response(401, request=request)
    auth_error = httpx.HTTPStatusError(
        "unauthorized",
        request=request,
        response=response,
    )
    nested_auth = ExceptionGroup("mcp task group", [auth_error])
    nested_schema = ExceptionGroup(
        "mcp task group",
        [_ConnectorToolsInvalid("invalid tools")],
    )

    assert _looks_like_authentication_error(nested_auth) is True
    assert _exception_contains(nested_schema, _ConnectorToolsInvalid) is True


def test_scholight_delegation_identifies_current_user() -> None:
    secret = "d" * 32
    authorization = _scholight_delegation_headers(_actor(), secret)
    token = authorization["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience="scholight-mcp",
        issuer="scholens",
    )

    assert (claims["sub"], claims["scope"]) == ("42", "search")


def test_scholight_delegation_is_refreshed_for_each_remote_session() -> None:
    resolver = ConnectorToolResolver(
        credential_loader=lambda _actor: (),
        settings=_ScholightSettings(),
    )
    connection = resolver._connections(actor=_actor(), credentials=())[0]

    first = connection.request_headers()["Authorization"]
    second = connection.request_headers()["Authorization"]

    assert first != second


def test_mcp_schema_drops_provider_incompatible_metadata() -> None:
    assert _normalize_json_schema(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "params": {
                    "type": "object",
                    "additionalProperties": True,
                }
            },
        }
    ) == {
        "type": "object",
        "properties": {"params": {"type": "object"}},
    }


def test_large_connector_result_is_safely_truncated() -> None:
    result = _normalize_result({"content": "x" * 160_000})

    assert isinstance(result, dict)
    assert result["truncated"] is True
    assert len(str(result["content"])) == 150_000


@pytest.mark.asyncio
async def test_resolver_is_read_gated_before_loading_credentials() -> None:
    loaded = False

    def load(_actor: Actor) -> tuple[ConnectorCredential, ...]:
        nonlocal loaded
        loaded = True
        return ()

    resolver = ConnectorToolResolver(
        credential_loader=load,
        settings=_Settings(),
    )

    resolved = await resolver.resolve(
        actor=_actor(),
        permissions=frozenset(),
    )

    assert resolved.declarations == ()
    assert loaded is False


@pytest.mark.asyncio
async def test_resolver_isolates_failures_and_routes_by_bound_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    credentials = (
        ConnectorCredential(ConnectorProvider.ANYSEARCH, "a-key", now),
        ConnectorCredential(ConnectorProvider.TAVILY, "t-key", now),
        ConnectorCredential(ConnectorProvider.EXA, "e-key", now),
    )
    resolver = ConnectorToolResolver(
        credential_loader=lambda _actor: credentials,
        settings=_Settings(),
    )

    async def discover(connection: object) -> list[dict[str, object]]:
        provider = connection.provider  # type: ignore[attr-defined]
        if provider is ConnectorProvider.TAVILY:
            raise RuntimeError("provider unavailable")
        if provider is ConnectorProvider.ANYSEARCH:
            return [
                {
                    "name": "shared_search",
                    "description": "AnySearch tool",
                    "parameters": {"type": "object"},
                }
            ]
        return [
            {
                "name": "shared_search",
                "description": "conflicting Exa tool",
                "parameters": {"type": "object"},
            },
            {
                "name": "exa_search",
                "description": "Exa tool",
                "parameters": {"type": "object"},
            },
        ]

    monkeypatch.setattr(
        "app.modules.integrations.connectors.infrastructure.mcp._list_declarations",
        discover,
    )

    resolved = await resolver.resolve(
        actor=_actor(),
        permissions=frozenset({WorkspacePermission.READ}),
    )

    assert [item["name"] for item in resolved.declarations] == [
        "shared_search",
        "exa_search",
    ]
    assert resolved.provider_for("shared_search") is ConnectorProvider.ANYSEARCH
    assert resolved.provider_for("exa_search") is ConnectorProvider.EXA
    assert {issue.code for issue in resolved.issues} == {
        "connector_unavailable",
        "connector_tool_name_conflict",
    }
