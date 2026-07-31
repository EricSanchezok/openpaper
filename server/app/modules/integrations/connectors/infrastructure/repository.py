"""SQLAlchemy Connector connection adapter."""

from __future__ import annotations

from datetime import datetime

from app.modules.integrations.connectors.application.ports import ConnectorRecord
from app.modules.integrations.connectors.domain import ConnectorProvider
from app.modules.integrations.connectors.infrastructure.models import ConnectorConnection
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


class SqlAlchemyConnectorGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_owned(self, *, user_id: int) -> tuple[ConnectorRecord, ...]:
        rows = self._db.scalars(
            select(ConnectorConnection)
            .where(ConnectorConnection.user_id == user_id)
            .order_by(ConnectorConnection.provider)
        ).all()
        return tuple(_record(row) for row in rows)

    def get_owned(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
        lock: bool = False,
    ) -> ConnectorRecord | None:
        statement = select(ConnectorConnection).where(
            ConnectorConnection.user_id == user_id,
            ConnectorConnection.provider == provider.value,
        )
        if lock:
            statement = statement.with_for_update()
        row = self._db.scalar(statement)
        return _record(row) if row is not None else None

    def upsert(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
        credential_ciphertext: str,
        verified_at: datetime,
    ) -> ConnectorRecord:
        statement = (
            insert(ConnectorConnection)
            .values(
                user_id=user_id,
                provider=provider.value,
                credential_ciphertext=credential_ciphertext,
                enabled=True,
                verified_at=verified_at,
                created_at=verified_at,
                updated_at=verified_at,
            )
            .on_conflict_do_update(
                index_elements=[
                    ConnectorConnection.user_id,
                    ConnectorConnection.provider,
                ],
                set_={
                    "credential_ciphertext": credential_ciphertext,
                    "enabled": True,
                    "verified_at": verified_at,
                    "updated_at": verified_at,
                },
            )
            .returning(ConnectorConnection)
        )
        row = self._db.scalar(statement)
        assert row is not None
        return _record(row)

    def set_enabled(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
        enabled: bool,
        verified_at: datetime | None = None,
    ) -> ConnectorRecord:
        row = self._db.scalar(
            select(ConnectorConnection).where(
                ConnectorConnection.user_id == user_id,
                ConnectorConnection.provider == provider.value,
            )
        )
        assert row is not None
        row.enabled = enabled
        if verified_at is not None:
            row.verified_at = verified_at
        self._db.flush()
        return _record(row)

    def delete(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
    ) -> None:
        self._db.execute(
            delete(ConnectorConnection).where(
                ConnectorConnection.user_id == user_id,
                ConnectorConnection.provider == provider.value,
            )
        )


def _record(row: ConnectorConnection) -> ConnectorRecord:
    return ConnectorRecord(
        user_id=row.user_id,
        provider=ConnectorProvider(row.provider),
        credential_ciphertext=row.credential_ciphertext,
        enabled=row.enabled,
        verified_at=row.verified_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
