"""Decisions and their durable notification events share the native transaction."""

import pytest
from test_manual_payments import decision, issue, payment_setup
from test_nodes import owner_client

pytestmark = pytest.mark.django_db(transaction=True)


def test_decision_replay_has_one_durable_event_and_rejection_is_retained() -> None:
    from papilio_panel.modules.payments.models import PaymentDecisionEvent

    owner = owner_client()
    setup = payment_setup(owner)
    invoice = issue(owner, setup["customer_id"])
    root = f"/api/v1/invoices/{invoice['id']}"
    values = decision(invoice, "reject")
    first = owner.post(root + "/decisions", values, format="json")
    assert first.status_code == 201
    assert owner.post(root + "/decisions", values, format="json").status_code == 200
    assert PaymentDecisionEvent.objects.count() == 1
    rejected = PaymentDecisionEvent.objects.get()
    assert str(rejected.decision_id) == first.json()["decision"]["id"]
    assert rejected.processed_at is None and rejected.dispatched_at is None
    second = owner.post(root + "/decisions", decision(first.json()["invoice"]), format="json")
    assert second.status_code == 201 and PaymentDecisionEvent.objects.count() == 2
    assert set(PaymentDecisionEvent.objects.values_list("decision__action", flat=True)) == {
        "approve",
        "reject",
    }
    assert (
        owner.get(f"/api/v1/customer-accounts/{setup['customer_id']}/wallet").json()[
            "balance_minor"
        ]
        == "1000"
    )


def test_credit_failure_rolls_back_decision_invoice_and_durable_event() -> None:
    from uuid import uuid4

    from papilio_panel.modules.payments.models import PaymentDecision, PaymentDecisionEvent

    owner = owner_client()
    setup = payment_setup(owner)
    wallet = f"/api/v1/customer-accounts/{setup['customer_id']}/wallet"
    credited = owner.post(
        wallet + "/entries",
        {
            "request_key": str(uuid4()),
            "kind": "credit",
            "amount_minor": "9223372036854775807",
            "reason": "Maximum balance for rollback boundary",
        },
        format="json",
    )
    assert credited.status_code == 201
    invoice = issue(owner, setup["customer_id"], "1")
    root = f"/api/v1/invoices/{invoice['id']}"
    assert owner.post(root + "/decisions", decision(invoice), format="json").status_code == 409
    assert PaymentDecision.objects.count() == 0 and PaymentDecisionEvent.objects.count() == 0
    assert owner.get(root).json()["status"] == "open"
    assert owner.get(wallet).json()["balance_minor"] == "9223372036854775807"


def test_event_read_and_acknowledgement_revalidate_owner_and_customer_parent() -> None:
    from django.contrib.auth import get_user_model

    from papilio_panel.modules.customers.models import CustomerAccount
    from papilio_panel.modules.payments.domain import PaymentEventOutcome
    from papilio_panel.modules.payments.models import PaymentDecisionEvent
    from papilio_panel.modules.payments.providers import payment_events
    from papilio_panel.shared.errors import Missing

    owner = owner_client("events-one")
    setup = payment_setup(owner)
    invoice = issue(owner, setup["customer_id"])
    assert (
        owner.post(
            f"/api/v1/invoices/{invoice['id']}/decisions", decision(invoice), format="json"
        ).status_code
        == 201
    )
    event = PaymentDecisionEvent.objects.get()
    owner_client("events-two")
    other = get_user_model().objects.get(username="events-two")
    with pytest.raises(Missing):
        payment_events.read(event.id, other.pk)
    with pytest.raises(Missing):
        payment_events.acknowledge(event.id, other.pk, PaymentEventOutcome.QUEUED)
    event.refresh_from_db()
    assert event.processed_at is None
    original_actor = event.decision.actor_id
    CustomerAccount.objects.filter(pk=setup["customer_id"]).update(owner_id=other.pk)
    with pytest.raises(Missing):
        payment_events.read(event.id, original_actor)
