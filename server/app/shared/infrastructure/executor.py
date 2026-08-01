"""SQLAlchemy implementation of the application execution boundary."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from time import monotonic
from typing import Generic, TypeVar

from scholens_observability import add_counter, instrumented_span, record_histogram
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
        return self._execute_sync("query", operation, commit=False)

    def command(
        self,
        operation: Callable[[CapabilitiesT], ResultT],
    ) -> ResultT:
        return self._execute_sync("command", operation, commit=True)

    async def command_async(
        self,
        operation: Callable[[CapabilitiesT], Awaitable[ResultT]],
    ) -> ResultT:
        token = self._enter()
        session = self._session_factory()
        started = monotonic()
        status = "success"
        try:
            with instrumented_span(
                "application.command_async",
                attributes={"application.operation.kind": "command_async"},
            ):
                result = await operation(self._capabilities_factory(session))
                session.commit()
                return result
        except BaseException:
            status = "failure"
            session.rollback()
            raise
        finally:
            self._record_execution("command_async", status, started)
            session.close()
            self._active.reset(token)

    def _execute_sync(
        self,
        kind: str,
        operation: Callable[[CapabilitiesT], ResultT],
        *,
        commit: bool,
    ) -> ResultT:
        token = self._enter()
        session = self._session_factory()
        started = monotonic()
        status = "success"
        try:
            with instrumented_span(
                f"application.{kind}",
                attributes={"application.operation.kind": kind},
            ):
                result = operation(self._capabilities_factory(session))
                if commit:
                    session.commit()
                return result
        except BaseException:
            status = "failure"
            session.rollback()
            raise
        finally:
            if not commit:
                session.rollback()
            self._record_execution(kind, status, started)
            session.close()
            self._active.reset(token)

    @staticmethod
    def _record_execution(kind: str, status: str, started: float) -> None:
        attributes = {"kind": kind, "status": status}
        add_counter("scholens.application.operations", attributes=attributes)
        record_histogram(
            "scholens.application.operation.duration",
            (monotonic() - started) * 1000,
            attributes=attributes,
        )

    def _enter(self) -> Token[bool]:
        if self._active.get():
            raise RuntimeError("nested_application_operation")
        return self._active.set(True)
