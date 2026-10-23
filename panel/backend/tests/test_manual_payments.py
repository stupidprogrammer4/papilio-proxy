"""Native invoice, private evidence and exactly-once wallet settlement contracts."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from rest_framework.test import APIClient
from test_nodes import owner_client

pytestmark = pytest.mark.django_db(transaction=True)


def payment_setup(client: APIClient) -> dict:
    settings = {
        "enabled": True,
        "recipient": "Test account holder",
        "destination": "TEST-ACCOUNT-1234",
        "instructions": "Send the exact amount and submit your receipt.",
        "receipt_max_bytes": 4194304,
    }
    response = client.post("/api/v1/payment-settings", settings, format="json")
    assert response.status_code == 201
    customer = client.post(
        "/api/v1/customer-accounts",
        {"request_key": str(uuid4()), "name": "Invoice customer"},
        format="json",
    ).json()
    response = client.post(
        f"/api/v1/customer-accounts/{customer['id']}/wallet",
        {"currency": "IRR"},
        format="json",
    )
    assert response.status_code == 201
    return {"customer_id": customer["id"], "definition": settings}


def issue(client: APIClient, customer_id: str, amount: str = "1000") -> dict:
    response = client.post(
        "/api/v1/invoices",
        {"request_key": str(uuid4()), "customer_id": customer_id, "base_amount_minor": amount},
        format="json",
    )
    assert response.status_code == 201
    return response.json()


def receipt(client: APIClient, invoice_id: str, request_key: str | None = None) -> dict:
    response = client.post(
        f"/api/v1/invoices/{invoice_id}/receipts",
        {
            "request_key": request_key or str(uuid4()),
            "reference": "TEST-TRANSFER-100",
            "note": "Customer supplied evidence, not bank verification.",
            "file": SimpleUploadedFile("receipt.png", b"private-test-receipt", "image/png"),
        },
        format="multipart",
    )
    assert response.status_code in (200, 201)
    return response.json()


def decision(invoice: dict, action: str = "approve", receipt_id: str | None = None) -> dict:
    return {
        "request_key": str(uuid4()),
        "expected_revision": invoice["revision"],
        "action": action,
        "reason": "Checked in the receiving account statement.",
        "receipt_id": receipt_id,
    }


def test_receipt_approval_credits_once_and_retains_issued_settings() -> None:
    client = owner_client()
    setup = payment_setup(client)
    customer_id = setup["customer_id"]
    values = {
        "request_key": str(uuid4()),
        "customer_id": customer_id,
        "base_amount_minor": "9007199254740993",
    }
    created = client.post("/api/v1/invoices", values, format="json")
    assert created.status_code == 201
    invoice = created.json()
    root = f"/api/v1/invoices/{invoice['id']}"
    assert invoice["mode"] == "manual"
    assert invoice["amount_due_minor"] == "9007199254740993"
    assert "identifier" not in invoice
    assert client.post("/api/v1/invoices", values, format="json").json() == invoice
    changed = setup["definition"] | {"destination": "NEW-ACCOUNT", "enabled": False}
    updated = client.put(
        "/api/v1/payment-settings", {"expected_revision": "1", **changed}, format="json"
    )
    assert updated.status_code == 200
    evidence = receipt(client, invoice["id"])
    invoice = client.get(root).json()
    assert invoice["settings"]["destination"] == "TEST-ACCOUNT-1234"
    assert invoice["status"] == "review"
    downloaded = client.get(root + f"/receipts/{evidence['id']}/file")
    assert downloaded.status_code == 200
    assert downloaded.content == b"private-test-receipt"
    assert downloaded["Content-Type"] == "application/octet-stream"
    assert "attachment" in downloaded["Content-Disposition"]
    assert downloaded["Cache-Control"] == "private, no-store"
    accepted = decision(invoice, receipt_id=evidence["id"])
    first = client.post(root + "/decisions", accepted, format="json")
    assert first.status_code == 201
    assert first.json()["invoice"]["status"] == "settled"
    assert client.post(root + "/decisions", accepted, format="json").status_code == 200
    wallet = client.get(f"/api/v1/customer-accounts/{customer_id}/wallet").json()
    assert wallet["balance_minor"] == "9007199254740993"
    journal = client.get(f"/api/v1/customer-accounts/{customer_id}/wallet/entries").json()
    assert journal["count"] == 1
    assert journal["items"][0]["request_key"] == invoice["id"]
    assert (
        client.post(root + "/decisions", decision(invoice, "reject"), format="json").status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/invoices", values | {"request_key": str(uuid4())}, format="json"
        ).status_code
        == 409
    )


def test_receipts_and_decisions_validate_parent_scope_and_replay() -> None:
    client = owner_client("payment-one")
    other = owner_client("payment-two")
    staff = owner_client("payment-staff", superuser=False)
    setup = payment_setup(client)
    first = issue(client, setup["customer_id"])
    second = issue(client, setup["customer_id"])
    root = f"/api/v1/invoices/{first['id']}"
    key = str(uuid4())
    evidence = receipt(client, first["id"], key)
    assert receipt(client, first["id"], key)["id"] == evidence["id"]
    changed = client.post(
        root + "/receipts",
        {"request_key": key, "reference": "changed", "note": ""},
        format="multipart",
    )
    assert changed.status_code == 409
    alien_receipt = receipt(client, second["id"])
    current = client.get(root).json()
    assert (
        client.post(
            root + "/decisions", decision(current, receipt_id=alien_receipt["id"]), format="json"
        ).status_code
        == 404
    )
    assert other.get(root).status_code == 404
    assert other.get(root + "/receipts").status_code == 404
    assert other.get(root + f"/receipts/{evidence['id']}/file").status_code == 404
    assert other.post(root + "/decisions", decision(current), format="json").status_code == 404
    assert staff.get("/api/v1/invoices").status_code == 401
    assert staff.get("/api/v1/payment-settings").status_code == 401
    denied = APIClient(enforce_csrf_checks=True)
    denied.cookies = client.cookies
    assert denied.post(root + "/decisions", decision(current), format="json").status_code == 403
    rejected = client.post(root + "/decisions", decision(current, "reject"), format="json")
    assert rejected.status_code == 201
    assert rejected.json()["invoice"]["status"] == "rejected"
    # Manual approval remains available for every unsettled invoice.
    accepted = client.post(root + "/decisions", decision(rejected.json()["invoice"]), format="json")
    assert accepted.status_code == 201
    assert client.get(root + "/decisions").json()["count"] == 2


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_approval_has_one_financial_effect(same_key: bool) -> None:
    client = owner_client()
    setup = payment_setup(client)
    invoice = issue(client, setup["customer_id"])
    root = f"/api/v1/invoices/{invoice['id']}"
    first = decision(invoice)
    second = first if same_key else decision(invoice)
    csrf = client.get("/api/v1/admin/auth/me").json()["csrf_token"]
    barrier = Barrier(2)

    def approve(values: dict) -> int:
        close_old_connections()
        local = APIClient(enforce_csrf_checks=True)
        local.cookies = client.cookies
        local.credentials(HTTP_X_CSRF_TOKEN=csrf)
        barrier.wait(timeout=5)
        try:
            return local.post(root + "/decisions", values, format="json").status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(approve, [first, second]))
    assert outcomes == ([200, 201] if same_key else [201, 409])
    wallet = client.get(f"/api/v1/customer-accounts/{setup['customer_id']}/wallet").json()
    assert wallet["balance_minor"] == "1000"
    assert client.get(root + "/decisions").json()["count"] == 1


@pytest.mark.parametrize("amount", ["0", "-1", "1.5", True, 1.5, "9223372036854775808"])
def test_invoice_rejects_invalid_amount_without_persistence(amount: object) -> None:
    from papilio_panel.modules.payments.models import Invoice

    client = owner_client()
    setup = payment_setup(client)
    result = client.post(
        "/api/v1/invoices",
        {
            "request_key": str(uuid4()),
            "customer_id": setup["customer_id"],
            "base_amount_minor": amount,
        },
        format="json",
    )
    assert result.status_code == 400
    assert not Invoice.objects.exists()


def test_settings_replacements_and_invoice_receipt_caps_preserve_existing_choices() -> None:
    from papilio_panel.modules.payments.models import PaymentSettings, Receipt

    client = owner_client()
    assert client.get("/api/v1/payment-settings").status_code == 404
    defaults = client.get("/api/v1/payment-defaults")
    assert defaults.status_code == 200
    assert defaults.json()["receipt_max_bytes"] == 4194304
    assert defaults.json()["enabled"] is True
    assert not PaymentSettings.objects.exists()
    setup = payment_setup(client)
    initial = setup["definition"] | {"receipt_max_bytes": 5}
    assert (
        client.put(
            "/api/v1/payment-settings", {"expected_revision": "1", **initial}, format="json"
        ).status_code
        == 200
    )
    invoice = issue(client, setup["customer_id"])
    changed = initial | {"receipt_max_bytes": 1, "enabled": False}
    assert (
        client.put(
            "/api/v1/payment-settings", {"expected_revision": "2", **changed}, format="json"
        ).status_code
        == 200
    )
    for missing in ("enabled", "receipt_max_bytes", "instructions"):
        partial = {"expected_revision": "3", **changed}
        del partial[missing]
        assert client.put("/api/v1/payment-settings", partial, format="json").status_code == 400
    assert client.get("/api/v1/payment-settings").json()["definition"] == changed
    assert (
        client.put(
            "/api/v1/payment-settings", {"expected_revision": "1", **initial}, format="json"
        ).status_code
        == 409
    )
    root = f"/api/v1/invoices/{invoice['id']}"
    oversized = client.post(
        root + "/receipts",
        {
            "request_key": str(uuid4()),
            "file": SimpleUploadedFile("receipt.png", b"123456", "image/png"),
        },
        format="multipart",
    )
    assert oversized.status_code == 400
    assert not Receipt.objects.exists()
    accepted = client.post(
        root + "/receipts",
        {
            "request_key": str(uuid4()),
            "file": SimpleUploadedFile("receipt.png", b"12345", "image/png"),
        },
        format="multipart",
    )
    assert accepted.status_code == 201
    assert client.get(root).json()["settings"]["receipt_max_bytes"] == 5
    assert client.get(root + "/receipts").json()["items"][0]["size_bytes"] == 5
    assert "content" not in client.get(root + "/receipts").json()["items"][0]


def test_settlement_overflow_rolls_back_invoice_decision_and_credit() -> None:
    from papilio_panel.modules.payments.models import PaymentDecision

    client = owner_client()
    setup = payment_setup(client)
    wallet = f"/api/v1/customer-accounts/{setup['customer_id']}/wallet"
    assert (
        client.post(
            wallet + "/entries",
            {
                "request_key": str(uuid4()),
                "kind": "credit",
                "amount_minor": "9223372036854775807",
                "reason": "Boundary before settlement",
            },
            format="json",
        ).status_code
        == 201
    )
    invoice = issue(client, setup["customer_id"], "1")
    root = f"/api/v1/invoices/{invoice['id']}"
    response = client.post(root + "/decisions", decision(invoice), format="json")
    assert response.status_code == 409
    assert client.get(root).json() == invoice
    assert not PaymentDecision.objects.exists()
    assert client.get(wallet).json()["balance_minor"] == "9223372036854775807"
    assert client.get(wallet + "/entries").json()["count"] == 1


def test_reference_only_receipts_paging_filters_and_immutable_decisions() -> None:
    client = owner_client()
    setup = payment_setup(client)
    invoice = issue(client, setup["customer_id"])
    root = f"/api/v1/invoices/{invoice['id']}"
    other = issue(client, setup["customer_id"])
    assert client.get("/api/v1/invoices?page_size=1&page=2").json()["items"][0]["id"] == other["id"]
    assert client.get("/api/v1/invoices?q=no-match").json()["count"] == 0
    assert client.get("/api/v1/invoices?q=Invoice%20customer").json()["count"] == 2
    assert client.get(f"/api/v1/invoices?customer_id={uuid4()}").status_code == 404
    assert client.get("/api/v1/invoices?page=0").status_code == 400
    evidence = client.post(
        root + "/receipts",
        {"request_key": str(uuid4()), "reference": "BANK-ONLY"},
        format="multipart",
    )
    assert evidence.status_code == 201
    assert client.get(root + f"/receipts/{evidence.json()['id']}/file").status_code == 404
    assert client.get(root + "/receipts?q=BANK").json()["count"] == 1
    assert client.get(root + "/receipts?q=missing").json()["count"] == 0
    assert client.get("/api/v1/invoices?status=review").json()["count"] == 1
    current = client.get(root).json()
    approved = decision(current, receipt_id=evidence.json()["id"])
    first = client.post(root + "/decisions", approved, format="json")
    assert first.status_code == 201
    changed = approved | {"reason": "A different claim"}
    assert client.post(root + "/decisions", changed, format="json").status_code == 409
    assert (
        client.post(
            f"/api/v1/invoices/{other['id']}/decisions", approved, format="json"
        ).status_code
        == 404
    )
    assert (
        client.post(
            root + "/receipts",
            {"request_key": str(uuid4()), "reference": "AFTER-SETTLED"},
            format="multipart",
        ).status_code
        == 409
    )
    assert client.get(root + "/receipts").json()["count"] == 1
    assert client.get(root + "/decisions?q=statement").json()["count"] == 1
    assert client.get(root + "/decisions?q=absent").json()["count"] == 0


def test_receipt_openapi_declares_a_binary_multipart_upload() -> None:
    client = owner_client()
    response = client.get("/api/schema/?format=json")
    assert response.status_code == 200
    schema = response.json()
    upload = schema["paths"]["/api/v1/invoices/{invoice_id}/receipts"]["post"]["requestBody"][
        "content"
    ]["multipart/form-data"]["schema"]
    name = upload["$ref"].rsplit("/", 1)[1]
    assert schema["components"]["schemas"][name]["properties"]["file"]["format"] == "binary"
