"""SQLAlchemy implementation of the application execution boundary."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from typing import Generic, TypeVar

from sqlalchemy.orm import Session, sessionmaker

CapabilitiesT = TypeVar("CapabilitiesT")
ResultT = TypeVar("ResultT")


class SqlAlchemyApplicationExecutor(Generic[CapabilitiesT]):
    """Own a fresh Session and exactly one transaction per operation."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        capabilities_factory: Callable[[Session], CapabilitiesT],
    ) -> None:
        self._session_factory = session_factory
        self._capabilities_factory = capabilities_factory
        self._active: ContextVar[bool] = ContextVar(
            f"application_executor_active_{id(self)}",
            default=False,
        )

    def query(
        self,
        operation: Callable[[CapabilitiesT], ResultT],
    ) -> ResultT:
        token = self._enter()
        session = self._session_factory()
        try:
            return operation(self._capabilities_factory(session))
        finally:
            session.rollback()
            session.close()
            self._active.reset(token)

    def command(
        self,
        operation: Callable[[CapabilitiesT], ResultT],
    ) -> ResultT:
        token = self._enter()
        session = self._session_factory()
        try:
            result = operation(self._capabilities_factory(session))
            session.commit()
            return result
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()
            self._active.reset(token)

    async def command_async(
        self,
        operation: Callable[[CapabilitiesT], Awaitable[ResultT]],
    ) -> ResultT:
        token = self._enter()
        session = self._session_factory()
        try:
            result = await operation(self._capabilities_factory(session))
            session.commit()
            return result
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()
            self._active.reset(token)

    def _enter(self) -> Token[bool]:
        if self._active.get():
            raise RuntimeError("nested_application_operation")
        return self._active.set(True)
