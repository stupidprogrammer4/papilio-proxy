"""Actual wallet purchase survives broker outage and connects a native client."""

import base64
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import until
from django.db import connection
from test_node_user_control import native_control as native_control
from test_service_runtime import existing_owner_client
from xray_client import subscription_client

from papilio_panel.config.celery import app
from papilio_panel.modules.cores.models import XrayCore
from papilio_panel.modules.nodes.domain import XrayApply
from papilio_panel.modules.orders.models import Order
from papilio_panel.modules.payments.models import Invoice, PaymentDecision
from papilio_panel.modules.services.models import ServiceAccount, ServiceOutbox, XrayService
from papilio_panel.modules.wallets.models import JournalEntry, Wallet

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]


@pytest.mark.timeout(120)
def test_native_purchase_outbox_recovers_and_delivers_the_paid_contract(
    native_control: tuple[XrayApply, int, str], tmp_path: Path
) -> None:
    container = os.environ.get("PAPILIO_TEST_BROKER_CONTAINER")
    if not container:
        pytest.skip("Explicitly test-owned RabbitMQ is required for this fault boundary.")
    # Keep a native pooled producer connection alive across the deliberate outage.
    app.control.purge()
    node, data_port, binary = native_control
    owner = existing_owner_client()
    core = owner.post(
        "/api/v1/cores/xray",
        {
            "request_key": str(uuid4()),
            "node_id": str(node.node_id),
            "name": "Order runtime Xray",
            "default_user_level": 7,
        },
        format="json",
    )
    assert core.status_code == 201
    inbound = owner.post(
        f"/api/v1/cores/{core.json()['id']}/xray/inbounds",
        {
            "request_key": str(uuid4()),
            "tag": "vless-test",
            "public_host": "127.0.0.1",
            "port": data_port,
        },
        format="json",
    )
    assert inbound.status_code == 201
    product = owner.post(
        "/api/v1/products",
        {
            "request_key": str(uuid4()),
            "definition": {
                "name": "Paid native service",
                "core_id": core.json()["id"],
                "inbound_id": inbound.json()["id"],
                "currency": "IRR",
                "price_minor": "1000",
            },
        },
        format="json",
    )
    assert product.status_code == 201
    customer = owner.post(
        "/api/v1/customer-accounts",
        {"request_key": str(uuid4()), "name": "Runtime buyer"},
        format="json",
    ).json()
    wallet_path = f"/api/v1/customer-accounts/{customer['id']}/wallet"
    assert owner.post(wallet_path, {"currency": "IRR"}, format="json").status_code == 201
    assert (
        owner.post(
            "/api/v1/payment-settings",
            {
                "recipient": "Controlled receiving account",
                "destination": "TEST-ACCOUNT",
            },
            format="json",
        ).status_code
        == 201
    )
    invoice_response = owner.post(
        "/api/v1/invoices",
        {
            "request_key": str(uuid4()),
            "customer_id": customer["id"],
            "base_amount_minor": "2500",
        },
        format="json",
    )
    assert invoice_response.status_code == 201
    invoice_id = invoice_response.json()["id"]
    values = {
        "request_key": str(uuid4()),
        "customer_id": customer["id"],
        "product_id": product.json()["id"],
        "expected_revision": "1",
        "service_name": "سفارش واقعی",
    }
    subprocess.run(
        ["docker", "exec", container, "rabbitmqctl", "stop_app"],
        check=True,
        capture_output=True,
        timeout=30,
    )
    try:
        receipt_response = owner.post(
            f"/api/v1/invoices/{invoice_id}/receipts",
            {
                "request_key": str(uuid4()),
                "reference": "CONTROLLED-NATIVE-PAYMENT",
            },
            format="multipart",
        )
        assert receipt_response.status_code == 201
        current_invoice = owner.get(f"/api/v1/invoices/{invoice_id}").json()
        approval = {
            "request_key": str(uuid4()),
            "expected_revision": current_invoice["revision"],
            "action": "approve",
            "reason": "Controlled account-statement confirmation.",
            "receipt_id": receipt_response.json()["id"],
        }
        payment_root = f"/api/v1/invoices/{invoice_id}/decisions"
        assert owner.post(payment_root, approval, format="json").status_code == 201
        assert owner.post(payment_root, approval, format="json").status_code == 200
        made = owner.post("/api/v1/orders", values, format="json")
        assert made.status_code == 201
        order = made.json()
        assert owner.post("/api/v1/orders", values, format="json").status_code == 200
        connection.close()
        assert Invoice.objects.get(pk=invoice_id).status == "settled"
        assert PaymentDecision.objects.filter(invoice_id=invoice_id).count() == 1
        assert Order.objects.get(pk=order["id"]).status == "purchased"
        service = ServiceAccount.objects.get(pk=order["service_id"])
        assert service.status == "queued" and service.attempts == 0
        assert ServiceOutbox.objects.get(service=service).dispatched_at is None
        assert Wallet.objects.get(customer_id=customer["id"]).balance_minor == 1500
        assert JournalEntry.objects.filter(wallet__customer_id=customer["id"]).count() == 2
        XrayCore.objects.filter(core_id=core.json()["id"]).update(default_user_level=11)
        changed = owner.put(
            f"/api/v1/products/{product.json()['id']}",
            {
                "expected_revision": "1",
                "definition": product.json()["offer"]["definition"]
                | {"price_minor": "3000", "is_active": False},
            },
            format="json",
        )
        assert changed.status_code == 200
        assert changed.json()["offer"]["user_level"] == 11
        assert owner.post("/api/v1/orders", values, format="json").json() == order
    finally:
        subprocess.run(
            ["docker", "exec", container, "rabbitmqctl", "start_app"],
            check=True,
            capture_output=True,
            timeout=30,
        )
    root = f"/api/v1/services/{order['service_id']}"
    until(lambda: owner.get(root).json()["status"] in {"succeeded", "failed"}, timeout=45)
    outcome = owner.get(root).json()
    assert outcome["status"] == "succeeded" and outcome["worker_pid"] != os.getpid()
    assert XrayService.objects.get(service_id=order["service_id"]).level == 7
    link = owner.get(root + "/subscription")
    assert link.status_code == 200
    subscription = owner.get(link.json()["url"])
    assert subscription.status_code == 200
    uri = base64.b64decode(subscription.content).decode().strip()
    with subscription_client(binary, tmp_path, uri) as probe:
        assert probe.fetch() == b"papilio-actual-subscription-client"
    assert owner.get(wallet_path).json()["balance_minor"] == "1500"
