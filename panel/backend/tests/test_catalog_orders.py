"""Native catalogue snapshots and atomic wallet-to-service purchase contracts."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections
from rest_framework.test import APIClient
from test_nodes import node_input, owner_client

pytestmark = pytest.mark.django_db(transaction=True)


def product_input(client: APIClient) -> dict:
    node = client.post("/api/v1/nodes", node_input(), format="json").json()["node"]
    core = client.post(
        "/api/v1/cores/xray",
        {
            "request_key": str(uuid4()),
            "node_id": node["id"],
            "name": "Sales Xray",
            "default_user_level": 7,
        },
        format="json",
    )
    assert core.status_code == 201
    inbound = client.post(
        f"/api/v1/cores/{core.json()['id']}/xray/inbounds",
        {"request_key": str(uuid4()), "tag": "sales", "public_host": "127.0.0.1", "port": 10888},
        format="json",
    )
    assert inbound.status_code == 201
    return {
        "request_key": str(uuid4()),
        "definition": {
            "name": "Native product",
            "core_id": core.json()["id"],
            "inbound_id": inbound.json()["id"],
            "currency": "IRR",
            "price_minor": "1000",
            "user_level": None,
            "is_active": True,
        },
    }


def test_product_edits_keep_immutable_offers_and_initial_request_replay() -> None:
    owner = owner_client()
    values = product_input(owner)
    created = owner.post("/api/v1/products", values, format="json")
    assert created.status_code == 201
    first = created.json()
    assert first["offer"]["user_level"] == 7
    assert first["offer"]["revision"] == "1"
    assert first["offer"]["definition"]["price_minor"] == "1000"
    assert owner.post("/api/v1/products", values, format="json").status_code == 200
    path = f"/api/v1/products/{first['id']}"
    changed = owner.put(
        path,
        {
            "expected_revision": "1",
            "definition": values["definition"] | {"price_minor": "2000", "is_active": False},
        },
        format="json",
    )
    assert changed.status_code == 200
    assert changed.json()["offer"]["revision"] == "2"
    assert owner.get(f"/api/v1/product-offers/{first['offer']['id']}").json() == first["offer"]
    replay = owner.post("/api/v1/products", values, format="json")
    assert replay.status_code == 200 and replay.json() == changed.json()
    assert owner.get("/api/v1/products", {"active_only": True}).json()["count"] == 0
    assert owner.get("/api/v1/products", {"q": "Native"}).json()["count"] == 1
    assert (
        owner.put(
            path, {"expected_revision": "1", "definition": values["definition"]}, format="json"
        ).status_code
        == 409
    )
    foreign = owner_client("product-foreign")
    assert foreign.get(path).status_code == 404
    assert foreign.get(f"/api/v1/product-offers/{first['offer']['id']}").status_code == 404
    assert foreign.post("/api/v1/products", values, format="json").status_code == 404


def purchase_context() -> tuple[APIClient, dict, str, dict]:
    owner = owner_client()
    definition = product_input(owner)
    response = owner.post("/api/v1/products", definition, format="json")
    assert response.status_code == 201
    product = response.json()
    customer = owner.post(
        "/api/v1/customer-accounts", {"request_key": str(uuid4()), "name": "Buyer"}, format="json"
    )
    assert customer.status_code == 201
    wallet = f"/api/v1/customer-accounts/{customer.json()['id']}/wallet"
    assert owner.post(wallet, {"currency": "IRR"}, format="json").status_code == 201
    values = {
        "request_key": str(uuid4()),
        "customer_id": customer.json()["id"],
        "product_id": product["id"],
        "expected_revision": "1",
        "service_name": "Purchased service",
    }
    return owner, product, wallet, values


def test_purchase_commits_one_debit_service_outbox_and_frozen_contract() -> None:
    from papilio_panel.modules.services.models import ServiceAccount, ServiceOutbox, XrayService

    owner, product, wallet, values = purchase_context()
    assert owner.post("/api/v1/orders", values, format="json").status_code == 409
    assert owner.get("/api/v1/orders").json()["count"] == 0
    assert ServiceAccount.objects.count() == 0
    funds = {
        "request_key": str(uuid4()),
        "kind": "credit",
        "amount_minor": "5000",
        "reason": "Available funds",
    }
    assert owner.post(wallet + "/entries", funds, format="json").status_code == 201
    created = owner.post(
        "/api/v1/orders",
        values
        | {
            "price_minor": "0",
            "owner_id": 9999,
            "service_id": str(uuid4()),
            "wallet_entry_id": str(uuid4()),
        },
        format="json",
    )
    assert created.status_code == 201
    order = created.json()
    assert order["owner_id"] == product["owner_id"]
    assert owner.get(wallet).json()["balance_minor"] == "4000"
    assert order["service_id"] and order["wallet_entry_id"]
    assert order["terms"]["offer_id"] == product["offer"]["id"]
    assert order["terms"]["price_minor"] == "1000"
    assert order["terms"]["offer_revision"] == "1"
    assert ServiceOutbox.objects.get(service_id=order["service_id"]).dispatched_at is None
    assert XrayService.objects.get(service_id=order["service_id"]).level == 7
    assert owner.post("/api/v1/orders", values, format="json").json() == order
    assert owner.get(wallet + "/entries").json()["count"] == 2
    updated = owner.put(
        f"/api/v1/products/{product['id']}",
        {
            "expected_revision": "1",
            "definition": product["offer"]["definition"]
            | {"price_minor": "4000", "is_active": False},
        },
        format="json",
    )
    assert updated.status_code == 200
    assert owner.post("/api/v1/orders", values, format="json").json() == order
    assert (
        owner.post(
            "/api/v1/orders", values | {"request_key": str(uuid4())}, format="json"
        ).status_code
        == 409
    )
    assert owner.get(wallet).json()["balance_minor"] == "4000"
    assert ServiceAccount.objects.count() == 1
    foreign = owner_client("order-foreign")
    assert foreign.get(f"/api/v1/orders/{order['id']}").status_code == 404
    assert foreign.get("/api/v1/orders", {"customer_id": values["customer_id"]}).status_code == 404


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_purchase_never_double_spends_or_replays(same_key: bool) -> None:
    owner, _, wallet, values = purchase_context()
    assert (
        owner.post(
            wallet + "/entries",
            {
                "request_key": str(uuid4()),
                "kind": "credit",
                "amount_minor": "1000",
                "reason": "Exact funds",
            },
            format="json",
        ).status_code
        == 201
    )
    csrf = owner.get("/api/v1/admin/auth/csrf").json()["csrf_token"]
    clients = [APIClient(enforce_csrf_checks=True), APIClient(enforce_csrf_checks=True)]
    for client in clients:
        client.cookies.update(owner.cookies)
        client.credentials(HTTP_X_CSRF_TOKEN=csrf)
    barrier = Barrier(2)

    def purchase(client: APIClient) -> tuple[int, str | None]:
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            response = client.post(
                "/api/v1/orders",
                values if same_key else values | {"request_key": str(uuid4())},
                format="json",
            )
            return response.status_code, response.json().get("id")
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(purchase, clients))
    assert sorted(status for status, _ in outcomes) == ([200, 201] if same_key else [201, 409])
    assert len({identity for _, identity in outcomes if identity is not None}) == 1
    assert owner.get("/api/v1/orders").json()["count"] == 1
    assert owner.get(wallet).json()["balance_minor"] == "0"
    assert owner.get(wallet + "/entries").json()["count"] == 2


@pytest.mark.parametrize("price", ["-1", "1.001", "9223372036854775808", True, 1.0])
def test_invalid_product_prices_leave_no_product_or_offer(price: object) -> None:
    from papilio_panel.modules.catalog.models import ProductOffer

    owner = owner_client()
    values = product_input(owner)
    values["definition"]["price_minor"] = price
    assert owner.post("/api/v1/products", values, format="json").status_code == 400
    assert owner.get("/api/v1/products").json()["count"] == 0
    assert ProductOffer.objects.count() == 0


def test_free_purchase_has_no_wallet_or_financial_entry_requirement() -> None:
    from papilio_panel.modules.wallets.models import JournalEntry

    owner, product, _, values = purchase_context()
    changed = owner.put(
        f"/api/v1/products/{product['id']}",
        {
            "expected_revision": "1",
            "definition": product["offer"]["definition"] | {"price_minor": "0", "user_level": 0},
        },
        format="json",
    )
    assert changed.status_code == 200
    customer = owner.post(
        "/api/v1/customer-accounts",
        {"request_key": str(uuid4()), "name": "Free buyer"},
        format="json",
    ).json()
    order = owner.post(
        "/api/v1/orders",
        values | {"customer_id": customer["id"], "expected_revision": "2"},
        format="json",
    )
    assert order.status_code == 201
    assert order.json()["wallet_entry_id"] is None and order.json()["service_id"]
    assert order.json()["terms"]["price_minor"] == "0"
    assert JournalEntry.objects.count() == 0
    assert owner.get(f"/api/v1/customer-accounts/{customer['id']}/wallet").status_code == 404


def test_product_parent_scopes_pagination_and_purchase_access_guards() -> None:
    owner, product, wallet, values = purchase_context()
    alternate = product_input(owner)
    mismatched = alternate | {
        "definition": alternate["definition"]
        | {"inbound_id": product["offer"]["definition"]["inbound_id"]}
    }
    assert owner.post("/api/v1/products", mismatched, format="json").status_code == 404
    alternate["definition"]["name"] = "Other product"
    assert owner.post("/api/v1/products", alternate, format="json").status_code == 201
    first = owner.get("/api/v1/products", {"page_size": 1}).json()
    second = owner.get("/api/v1/products", {"page_size": 1, "page": 2}).json()
    assert first["count"] == second["count"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]
    staff = owner_client("purchase-staff", superuser=False)
    assert staff.post("/api/v1/orders", values, format="json").status_code == 401
    assert staff.get("/api/v1/products").status_code == 401
    missing_csrf = APIClient(enforce_csrf_checks=True)
    missing_csrf.cookies.update(owner.cookies)
    assert missing_csrf.post("/api/v1/orders", values, format="json").status_code == 403
    assert owner.get(wallet).json()["balance_minor"] == "0"
    assert owner.get("/api/v1/orders").json()["count"] == 0


def test_two_product_edits_publish_only_one_new_immutable_revision() -> None:
    from papilio_panel.modules.catalog.models import ProductOffer

    owner = owner_client()
    values = product_input(owner)
    product = owner.post("/api/v1/products", values, format="json").json()
    csrf = owner.get("/api/v1/admin/auth/csrf").json()["csrf_token"]
    clients = [APIClient(enforce_csrf_checks=True), APIClient(enforce_csrf_checks=True)]
    for client in clients:
        client.cookies.update(owner.cookies)
        client.credentials(HTTP_X_CSRF_TOKEN=csrf)
    barrier = Barrier(2)

    def edit(client: APIClient) -> int:
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            return client.put(
                f"/api/v1/products/{product['id']}",
                {
                    "expected_revision": "1",
                    "definition": values["definition"] | {"price_minor": "2000"},
                },
                format="json",
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(edit, clients))
    assert sorted(statuses) == [200, 409]
    assert ProductOffer.objects.filter(product_id=product["id"]).count() == 2
    assert owner.get(f"/api/v1/products/{product['id']}").json()["offer"]["revision"] == "2"


def test_invalid_saved_runtime_terms_leave_no_partial_financial_purchase() -> None:
    from papilio_panel.modules.catalog.models import ProductOffer
    from papilio_panel.modules.services.models import ServiceAccount, ServiceOutbox

    owner, product, wallet, values = purchase_context()
    assert (
        owner.post(
            wallet + "/entries",
            {
                "request_key": str(uuid4()),
                "kind": "credit",
                "amount_minor": "1000",
                "reason": "Available funds",
            },
            format="json",
        ).status_code
        == 201
    )
    ProductOffer.objects.filter(pk=product["offer"]["id"]).update(user_level=4294967296)
    assert owner.post("/api/v1/orders", values, format="json").status_code == 400
    assert owner.get(wallet).json()["balance_minor"] == "1000"
    assert owner.get(wallet + "/entries").json()["count"] == 1
    assert owner.get("/api/v1/orders").json()["count"] == 0
    assert ServiceAccount.objects.count() == ServiceOutbox.objects.count() == 0


def test_product_replacement_rejects_missing_settings_without_reapplying_defaults() -> None:
    owner = owner_client()
    values = product_input(owner)
    values["definition"].update(is_active=False, user_level=9)
    original = owner.post("/api/v1/products", values, format="json")
    assert original.status_code == 201
    path = f"/api/v1/products/{original.json()['id']}"
    partial = {
        key: value
        for key, value in values["definition"].items()
        if key not in {"is_active", "user_level", "currency"}
    }
    rejected = owner.put(path, {"expected_revision": "1", "definition": partial}, format="json")
    assert rejected.status_code == 400
    assert owner.get(path).json() == original.json()
