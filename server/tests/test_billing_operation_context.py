from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.bootstrap.workflows.billing import BillingWorkflow
from app.modules.billing.application.billing import Billing, CheckoutPreparation
from app.modules.billing.application.contracts import SubscriptionInterval
from app.modules.billing.application.ports import (
    ProviderCheckoutSession,
    SubscriptionRecord,
    SubscriptionWriteResult,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationJournalEntry
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 7, 31, tzinfo=timezone.utc)


class _JournalStore:
    def __init__(self) -> None:
        self.entries: list[OperationJournalEntry] = []

    def append(self, entries: tuple[OperationJournalEntry, ...]) -> None:
        self.entries.extend(entries)


class _Executor:
    def __init__(self, capabilities: object) -> None:
        self.capabilities = capabilities
        self.active = False

    def query(self, operation: object) -> object:
        self.active = True
        try:
            return operation(self.capabilities)  # type: ignore[operator]
        finally:
            self.active = False

    def command(self, operation: object) -> object:
        self.active = True
        try:
            return operation(self.capabilities)  # type: ignore[operator]
        finally:
            self.active = False

    async def command_async(self, operation: object) -> object:
        self.active = True
        try:
            return await operation(self.capabilities)  # type: ignore[operator]
        finally:
            self.active = False


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        display_name="Reader",
        status="active",
        email_verified=True,
    )


def _operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


def _subscription(**changes: object) -> SubscriptionRecord:
    values: dict[str, object] = {
        "id": uuid4(),
        "user_id": 7,
        "plan": "researcher",
        "stripe_customer_id": "cus_1",
        "stripe_subscription_id": "sub_1",
        "stripe_price_id": "price_month",
        "stripe_schedule_id": "sched_1",
        "status": "active",
        "current_period_start": None,
        "current_period_end": None,
        "cancel_at_period_end": False,
    }
    values.update(changes)
    return SubscriptionRecord(**values)  # type: ignore[arg-type]


def test_local_billing_noop_does_not_write_journal() -> None:
    subscription = _subscription()
    subscriptions = MagicMock()
    subscriptions.get.return_value = subscription
    subscriptions.save.return_value = SubscriptionWriteResult(
        record=subscription,
        changed=False,
    )
    journal_store = _JournalStore()
    billing = Billing(
        subscriptions=subscriptions,
        usage=MagicMock(),
        journal=OperationJournal(store=journal_store, clock=_Clock()),
        monthly_price_id="price_month",
        yearly_price_id="price_year",
    )

    assert (
        billing.complete_interval_change(
            actor=_actor(),
            operation=_operation(),
            schedule_id="sched_1",
        )
        is False
    )
    assert journal_store.entries == []


def test_checkout_business_write_and_journal_share_completion_stage() -> None:
    updated = _subscription(stripe_customer_id="cus_new")
    subscriptions = MagicMock()
    subscriptions.save.return_value = SubscriptionWriteResult(
        record=updated,
        changed=True,
    )
    journal_store = _JournalStore()
    billing = Billing(
        subscriptions=subscriptions,
        usage=MagicMock(),
        journal=OperationJournal(store=journal_store, clock=_Clock()),
        monthly_price_id="price_month",
        yearly_price_id="price_year",
    )
    operation = _operation()

    billing.complete_checkout(
        actor=_actor(),
        operation=operation,
        customer_id="cus_new",
    )

    subscriptions.save.assert_called_once_with(
        7,
        stripe_customer_id="cus_new",
    )
    assert [str(entry.action) for entry in journal_store.entries] == [
        "billing.customer_linked",
        "billing.checkout_created",
    ]
    assert {entry.operation_id for entry in journal_store.entries} == {
        operation.trace.operation_id
    }


def test_checkout_provider_and_telemetry_run_outside_executor_operation() -> None:
    billing = MagicMock()
    billing.prepare_checkout.return_value = CheckoutPreparation(
        subscription=None,
        price_id="price_month",
    )
    capabilities = SimpleNamespace(billing=billing)
    executor = _Executor(capabilities)
    payments = MagicMock()

    def create_customer(_actor: Actor) -> str:
        assert_outside_executor(executor)
        return "cus_new"

    def create_checkout_session(**_kwargs: object) -> ProviderCheckoutSession:
        assert_outside_executor(executor)
        return ProviderCheckoutSession(
            session_id="cs_1",
            status="open",
            client_secret="secret",
        )

    payments.create_customer.side_effect = create_customer
    payments.create_checkout_session.side_effect = create_checkout_session
    events = MagicMock()
    events.record.side_effect = lambda _event: assert_outside_executor(executor)
    workflow = BillingWorkflow(
        executor=executor,  # type: ignore[arg-type]
        payments=payments,
        events=events,
        notifier=MagicMock(),
        operation_factory=OperationContextFactory(),
    )

    response = workflow.create_checkout(
        actor=_actor(),
        operation=_operation(),
        interval=SubscriptionInterval.MONTHLY,
    )

    assert response.client_secret == "secret"
    billing.complete_checkout.assert_called_once()
    complete_operation = billing.complete_checkout.call_args.kwargs["operation"]
    assert complete_operation.trace.causation_id is not None
    events.record.assert_called_once()


def assert_outside_executor(executor: _Executor) -> None:
    assert executor.active is False
