"""Native customer/wallet HTTP contracts, concurrency and exact monetary units."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from django.db import close_old_connections
from rest_framework.test import APIClient
from test_nodes import owner_client

pytestmark = pytest.mark.django_db(transaction=True)
ROOT = "/api/v1/customer-accounts"
MAXIMUM = 9223372036854775807


def make_customer(client: APIClient, name: str = "Customer") -> dict:
    response = client.post(ROOT, {"request_key": str(uuid4()), "name": name}, format="json")
    assert response.status_code == 201
    return response.json()


def test_customer_account_replay_scope_and_full_search() -> None:
    owner = owner_client("customer-owner")
    key = str(uuid4())
    input_data = {"request_key": key, "name": "First customer"}
    made = owner.post(ROOT, input_data, format="json")
    assert made.status_code == 201
    customer = made.json()
    assert owner.post(ROOT, input_data, format="json").status_code == 200
    assert owner.post(ROOT, input_data, format="json").json() == customer
    assert owner.post(ROOT, input_data | {"name": "changed"}, format="json").status_code == 409
    make_customer(owner, "Second customer")
    first = owner.get(ROOT, {"page_size": 1}).json()
    second = owner.get(ROOT, {"page_size": 1, "page": 2}).json()
    assert first["count"] == second["count"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert owner.get(ROOT, {"q": "Second"}).json()["count"] == 1
    foreign = owner_client("foreign-customer-owner")
    assert foreign.get(f"{ROOT}/{customer['id']}").status_code == 404
    assert foreign.get(ROOT).json()["count"] == 0
    staff = owner_client("customer-staff", superuser=False)
    assert (
        staff.post(ROOT, {"request_key": str(uuid4()), "name": "Denied"}, format="json").status_code
        == 401
    )
    assert owner.get(ROOT).json()["count"] == 2


def test_wallet_explicit_units_replay_parent_scope_and_rollback() -> None:
    owner = owner_client("wallet-owner")
    customer = make_customer(owner)
    wallet = f"{ROOT}/{customer['id']}/wallet"
    assert owner.get(wallet).status_code == 404
    opened = owner.post(wallet, {"currency": "IRR", "credit_limit_minor": "0"}, format="json")
    assert opened.status_code == 201
    assert opened.json()["balance_minor"] == "0"
    assert opened.json()["currency"] == "IRR" and opened.json()["unit"] == "rial"
    assert (
        owner.post(
            wallet, {"currency": "IRR", "credit_limit_minor": "0"}, format="json"
        ).status_code
        == 200
    )
    assert (
        owner.post(
            wallet, {"currency": "IRR", "credit_limit_minor": "1"}, format="json"
        ).status_code
        == 409
    )
    entries = wallet + "/entries"
    values = {
        "request_key": str(uuid4()),
        "kind": "credit",
        "amount_minor": "100001",
        "reason": "Manual receipt adjustment",
    }
    credited = owner.post(entries, values, format="json")
    assert credited.status_code == 201
    entry = credited.json()
    assert entry["actor_id"] == customer["owner_id"]
    assert entry["balance_before_minor"] == "0" and entry["balance_after_minor"] == "100001"
    assert owner.post(entries, values, format="json").json() == entry
    assert (
        owner.post(entries, values | {"amount_minor": "100002"}, format="json").status_code == 409
    )
    assert owner.get(wallet).json()["balance_minor"] == "100001"
    rejected = values | {"request_key": str(uuid4()), "kind": "debit", "amount_minor": "100002"}
    assert owner.post(entries, rejected, format="json").status_code == 409
    assert owner.get(entries).json()["count"] == 1
    assert owner.get(wallet).json()["balance_minor"] == "100001"
    other_customer = make_customer(owner, "Other customer")
    assert (
        owner.get(f"{ROOT}/{other_customer['id']}/wallet/entries/{entry['id']}").status_code == 404
    )
    foreign = owner_client("wallet-foreign")
    assert foreign.get(wallet).status_code == 404
    assert (
        foreign.post(entries, values | {"request_key": str(uuid4())}, format="json").status_code
        == 404
    )
    assert foreign.get(entries + f"/{entry['id']}").status_code == 404
    assert owner.get(entries + f"/{entry['id']}").json() == entry
    assert owner.get(wallet).json()["balance_minor"] == "100001"


@pytest.mark.parametrize(
    "amount", ["0", "-1", "1.5", "1.000", "1e3", "NaN", 1.0, str(MAXIMUM + 1), True]
)
def test_invalid_wallet_amount_does_not_write(amount: object) -> None:
    owner = owner_client()
    customer = make_customer(owner)
    wallet = f"{ROOT}/{customer['id']}/wallet"
    assert (
        owner.post(
            wallet, {"currency": "IRR", "credit_limit_minor": "0"}, format="json"
        ).status_code
        == 201
    )
    response = owner.post(
        wallet + "/entries",
        {
            "request_key": str(uuid4()),
            "kind": "credit",
            "amount_minor": amount,
            "reason": "Invalid amount",
        },
        format="json",
    )
    assert response.status_code == 400
    assert owner.get(wallet).json()["balance_minor"] == "0"
    assert owner.get(wallet + "/entries").json()["count"] == 0


def test_wallet_native_bigint_overflow_and_configured_credit_limit() -> None:
    owner = owner_client()
    customer = make_customer(owner)
    wallet = f"{ROOT}/{customer['id']}/wallet"
    assert (
        owner.post(
            wallet, {"currency": "IRR", "credit_limit_minor": "50"}, format="json"
        ).status_code
        == 201
    )
    entries = wallet + "/entries"
    values = {
        "request_key": str(uuid4()),
        "kind": "credit",
        "amount_minor": str(MAXIMUM),
        "reason": "Representable limit",
    }
    assert owner.post(entries, values, format="json").status_code == 201
    assert owner.get(wallet).json()["balance_minor"] == str(MAXIMUM)
    assert (
        owner.post(
            entries, values | {"request_key": str(uuid4()), "amount_minor": "1"}, format="json"
        ).status_code
        == 409
    )
    assert (
        owner.post(
            entries, values | {"request_key": str(uuid4()), "kind": "debit"}, format="json"
        ).status_code
        == 201
    )
    debit = values | {"request_key": str(uuid4()), "kind": "debit", "amount_minor": "50"}
    assert owner.post(entries, debit, format="json").status_code == 201
    assert owner.get(wallet).json()["balance_minor"] == "-50"
    assert (
        owner.post(
            entries, debit | {"request_key": str(uuid4()), "amount_minor": "1"}, format="json"
        ).status_code
        == 409
    )
    assert owner.get(entries).json()["count"] == 3
    last = owner.get(entries, {"page": 3, "page_size": 1}).json()
    assert last["count"] == 3 and len(last["items"]) == 1
    assert last["items"][0]["balance_after_minor"] == "-50"


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_debits_never_double_spend_or_replay(same_key: bool) -> None:
    owner = owner_client()
    customer = make_customer(owner)
    wallet = f"{ROOT}/{customer['id']}/wallet"
    assert (
        owner.post(
            wallet, {"currency": "IRR", "credit_limit_minor": "0"}, format="json"
        ).status_code
        == 201
    )
    values = {
        "request_key": str(uuid4()),
        "kind": "credit",
        "amount_minor": "100",
        "reason": "Seed funds",
    }
    assert owner.post(wallet + "/entries", values, format="json").status_code == 201
    clients = [APIClient(enforce_csrf_checks=True), APIClient(enforce_csrf_checks=True)]
    csrf = owner.get("/api/v1/admin/auth/csrf").json()["csrf_token"]
    for client in clients:
        client.cookies.update(owner.cookies)
        client.credentials(HTTP_X_CSRF_TOKEN=csrf)
    barrier = Barrier(2)
    key = str(uuid4())

    def debit(client: APIClient) -> int:
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            response = client.post(
                wallet + "/entries",
                values
                | {
                    "request_key": key if same_key else str(uuid4()),
                    "kind": "debit",
                    "amount_minor": "75",
                },
                format="json",
            )
            return response.status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(debit, clients))
    assert owner.get(wallet).json()["balance_minor"] == "25"
    assert sorted(statuses) == ([200, 201] if same_key else [201, 409])
    assert owner.get(wallet + "/entries").json()["count"] == 2


def test_wallet_credit_limit_can_be_edited_without_rewriting_journal() -> None:
    owner = owner_client()
    customer = make_customer(owner)
    wallet = f"{ROOT}/{customer['id']}/wallet"
    initial = owner.post(wallet, {"currency": "IRR", "credit_limit_minor": "50"}, format="json")
    assert initial.status_code == 201
    changed = owner.put(
        wallet, {"expected_revision": 1, "credit_limit_minor": "100"}, format="json"
    )
    assert changed.status_code == 200
    assert changed.json()["revision"] == "2" and changed.json()["credit_limit_minor"] == "100"
    assert (
        owner.put(
            wallet, {"expected_revision": str(MAXIMUM), "credit_limit_minor": "100"}, format="json"
        ).status_code
        == 400
    )
    assert (
        owner.put(
            wallet, {"expected_revision": 1, "credit_limit_minor": "999"}, format="json"
        ).status_code
        == 409
    )
    entry = owner.post(
        wallet + "/entries",
        {
            "request_key": str(uuid4()),
            "kind": "debit",
            "amount_minor": "75",
            "reason": "Within configured credit",
        },
        format="json",
    )
    assert entry.status_code == 201
    assert (
        owner.put(
            wallet, {"expected_revision": 2, "credit_limit_minor": "74"}, format="json"
        ).status_code
        == 409
    )
    assert owner.get(wallet).json()["credit_limit_minor"] == "100"
    assert (
        owner.put(
            wallet, {"expected_revision": 2, "credit_limit_minor": "75"}, format="json"
        ).status_code
        == 200
    )
    assert owner.get(wallet + f"/entries/{entry.json()['id']}").json() == entry.json()
    foreign = owner_client("limit-foreign")
    assert (
        foreign.put(
            wallet, {"expected_revision": 3, "credit_limit_minor": "1000"}, format="json"
        ).status_code
        == 404
    )


def test_denied_wallet_requests_and_protected_fields_leave_no_financial_effect() -> None:
    from django.contrib.auth.models import User

    owner = owner_client()
    customer = make_customer(owner)
    wallet = f"{ROOT}/{customer['id']}/wallet"
    assert owner.post(wallet, {"currency": "USD"}, format="json").status_code == 400
    opening = {
        "currency": "IRR",
        "balance_minor": "9999",
        "customer_id": str(uuid4()),
        "owner_id": 9999,
    }
    made = owner.post(wallet, opening, format="json")
    assert made.status_code == 201 and made.json()["balance_minor"] == "0"
    missing_csrf = APIClient(enforce_csrf_checks=True)
    missing_csrf.cookies.update(owner.cookies)
    entry = {
        "request_key": str(uuid4()),
        "kind": "credit",
        "amount_minor": "1000",
        "reason": "Denied",
    }
    assert missing_csrf.post(wallet + "/entries", entry, format="json").status_code == 403
    assert (
        owner.post(wallet + "/entries", entry | {"kind": "unknown"}, format="json").status_code
        == 400
    )
    assert owner.post(f"{ROOT}/{uuid4()}/wallet/entries", entry, format="json").status_code == 404
    staff = owner_client("wallet-staff", superuser=False)
    assert staff.get(wallet).status_code == 401
    assert staff.post(wallet + "/entries", entry, format="json").status_code == 401
    User.objects.filter(pk=customer["owner_id"]).update(is_active=False)
    assert owner.post(wallet + "/entries", entry, format="json").status_code == 401
    User.objects.filter(pk=customer["owner_id"]).update(is_active=True)
    assert owner.get(wallet).json()["balance_minor"] == "0"
    assert owner.get(wallet + "/entries").json()["count"] == 0


def test_native_balance_update_rejects_a_configuration_changed_after_observation() -> None:
    from django.db import transaction

    from papilio_panel.modules.wallets.app.amounts import balance_change
    from papilio_panel.modules.wallets.domain import EntryKind, JournalInput
    from papilio_panel.modules.wallets.infra.storage import DjangoWalletStorage
    from papilio_panel.modules.wallets.providers import wallets
    from papilio_panel.shared.errors import Conflict

    owner = owner_client()
    customer = make_customer(owner)
    path = f"{ROOT}/{customer['id']}/wallet"
    assert (
        owner.post(
            path, {"currency": "IRR", "credit_limit_minor": "100"}, format="json"
        ).status_code
        == 201
    )
    observed = wallets.read(UUID(customer["id"]), customer["owner_id"])
    debit = JournalInput(uuid4(), EntryKind.DEBIT, 75, "Old configured credit")
    change = balance_change(observed, debit)
    assert (
        owner.put(
            path, {"expected_revision": 1, "credit_limit_minor": "0"}, format="json"
        ).status_code
        == 200
    )
    with pytest.raises(Conflict), transaction.atomic():
        DjangoWalletStorage().change_balance(change, customer["owner_id"])
    assert owner.get(path).json()["balance_minor"] == "0"
    assert owner.get(path + "/entries").json()["count"] == 0
