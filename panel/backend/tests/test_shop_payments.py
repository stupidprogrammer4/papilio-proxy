"""Bot invoices and private evidence use customer-scoped shared payment contracts."""

from uuid import UUID, uuid4

import pytest
from rest_framework.test import APIClient
from telegram_server import TelegramServer
from test_nodes import owner_client
from test_shop_customers import configured_event

from papilio_panel.modules.bots.models import TelegramInbox
from papilio_panel.modules.bots.providers import polling
from papilio_panel.modules.payments.models import Invoice, Receipt
from papilio_panel.modules.shop.models import InboxWork, OutgoingMessage
from papilio_panel.modules.shop.providers import execution, shop_customers
from papilio_panel.shared.errors import Conflict, Missing

pytestmark = pytest.mark.django_db(transaction=True)


def payment_bot(
    client: APIClient,
    server: TelegramServer,
    address: str,
    instructions: str = "Preserved invoice instructions",
    receipt_limit: int = 4194304,
) -> tuple[UUID, str]:
    event_id = configured_event(client, server, address)
    context = shop_customers.register(event_id)
    assert (
        client.post(
            "/api/v1/payment-settings",
            {
                "recipient": "Controlled operator",
                "destination": "CONTROLLED-ACCOUNT",
                "instructions": instructions,
                "receipt_max_bytes": receipt_limit,
            },
            format="json",
        ).status_code
        == 201
    )
    return context.event.bot.id, str(context.customer.id)


def incoming_text(
    server: TelegramServer, bot_id: UUID, update_id: int, text: str, sender: int = 987654
) -> InboxWork:
    server.push(update_id, text, chat_id=sender)
    polling.poll(bot_id)
    return InboxWork.objects.create(
        event=TelegramInbox.objects.get(bot_id=bot_id, update_id=update_id)
    )


def process(work: InboxWork) -> None:
    claim = execution.begin(work.id)
    assert claim is not None
    prepared = execution.prepare(claim)
    execution.process(claim, prepared)


def test_topup_invoice_and_reference_receipt_do_not_credit_before_owner_review() -> None:
    from papilio_panel.modules.shop.models import InvoiceConversation

    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        bot, customer = payment_bot(client, server, address)
        issued = incoming_text(server, bot, 2, "/topup 9007199254740993")
        process(issued)
        invoice = Invoice.objects.get()
        assert str(invoice.customer_id) == customer and invoice.request_key == issued.id
        assert invoice.base_amount_minor == 9007199254740993
        origin = InvoiceConversation.objects.get(invoice=invoice)
        assert origin.event_id == issued.event_id
        assert (
            OutgoingMessage.objects.filter(
                event=issued.event, invoice=invoice, administrator=False
            ).count()
            == 2
        )
        evidence = incoming_text(server, bot, 3, f"/receipt {invoice.id} CONTROLLED-TRANSFER-123")
        process(evidence)
        receipt = Receipt.objects.get(invoice=invoice)
        assert receipt.reference == "CONTROLLED-TRANSFER-123" and receipt.request_key == evidence.id
        invoice.refresh_from_db()
        assert invoice.status == "review"
        assert (
            client.get(f"/api/v1/customer-accounts/{customer}/wallet").json()["balance_minor"]
            == "0"
        )
        assert (
            OutgoingMessage.objects.filter(
                event=evidence.event, administrator=True, invoice=invoice
            ).count()
            == 1
        )
        from urllib.parse import parse_qs, urlsplit

        from papilio_panel.modules.shop.infra.replies import decrypt_reply

        notice = OutgoingMessage.objects.get(event=evidence.event, administrator=True)
        buttons = decrypt_reply(bytes(notice.payload_ciphertext)).buttons
        links = [button.url for button in buttons if button.url]
        assert any(
            parse_qs(urlsplit(url).query)
            == {"invoice_id": [str(invoice.id)], "receipt_id": [str(receipt.id)]}
            for url in links
        )
        assert execution.begin(evidence.id) is None
        assert Receipt.objects.count() == 1


def test_other_customer_cannot_submit_to_or_read_an_owned_invoice() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        bot, customer = payment_bot(client, server, address)
        process(incoming_text(server, bot, 2, "/topup 1000"))
        invoice = Invoice.objects.get()
        process(incoming_text(server, bot, 3, "/start", sender=998877))
        foreign = incoming_text(
            server, bot, 4, f"/receipt {invoice.id} NOT-MY-PAYMENT", sender=998877
        )
        claim = execution.begin(foreign.id)
        assert claim is not None
        with pytest.raises(Missing):
            execution.prepare(claim)
        assert Receipt.objects.count() == 0
        assert not OutgoingMessage.objects.filter(event=foreign.event).exists()
        assert (
            client.get(f"/api/v1/customer-accounts/{customer}/wallet").json()["balance_minor"]
            == "0"
        )


def test_approval_event_creates_one_notification_without_reposting_credit() -> None:
    from test_manual_payments import decision

    from papilio_panel.modules.payments.models import PaymentDecisionEvent
    from papilio_panel.modules.shop.infra.replies import decrypt_reply
    from papilio_panel.modules.shop.providers import settlements

    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        bot, customer = payment_bot(client, server, address)
        process(incoming_text(server, bot, 2, "/topup 1000"))
        invoice = Invoice.objects.get()
        root = f"/api/v1/invoices/{invoice.id}"
        accepted = client.post(
            root + "/decisions", decision(client.get(root).json()), format="json"
        )
        assert accepted.status_code == 201
        event = PaymentDecisionEvent.objects.get()
        settlements.notify(event.id, invoice.owner_id)
        settlements.notify(event.id, invoice.owner_id)
        event.refresh_from_db()
        assert event.processed_at is not None and event.outcome == "queued"
        message = OutgoingMessage.objects.get(source_event_id=event.id)
        assert (
            message.invoice_id == invoice.id and message.bot_id == bot and not message.administrator
        )
        assert "1000" in decrypt_reply(bytes(message.payload_ciphertext)).text
        assert (
            client.get(f"/api/v1/customer-accounts/{customer}/wallet").json()["balance_minor"]
            == "1000"
        )
        assert (
            client.get(f"/api/v1/customer-accounts/{customer}/wallet/entries").json()["count"] == 1
        )


def test_late_rejection_is_superseded_by_approval_and_panel_invoice_has_no_bot_origin() -> None:
    from test_manual_payments import decision

    from papilio_panel.modules.payments.models import PaymentDecisionEvent
    from papilio_panel.modules.shop.providers import settlements

    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        bot, customer = payment_bot(client, server, address)
        process(incoming_text(server, bot, 2, "/topup 1000"))
        invoice = Invoice.objects.get()
        root = f"/api/v1/invoices/{invoice.id}"
        rejected = client.post(
            root + "/decisions", decision(client.get(root).json(), "reject"), format="json"
        )
        assert rejected.status_code == 201
        rejection = PaymentDecisionEvent.objects.get()
        accepted = client.post(
            root + "/decisions", decision(client.get(root).json()), format="json"
        )
        assert accepted.status_code == 201
        settlements.notify(rejection.id, invoice.owner_id)
        rejection.refresh_from_db()
        assert rejection.outcome == "superseded"
        assert not OutgoingMessage.objects.filter(source_event_id=rejection.id).exists()
        other = client.post(
            "/api/v1/invoices",
            {"request_key": str(uuid4()), "customer_id": customer, "base_amount_minor": "2000"},
            format="json",
        ).json()
        assert (
            client.post(
                f"/api/v1/invoices/{other['id']}/decisions", decision(other), format="json"
            ).status_code
            == 201
        )
        unrelated = PaymentDecisionEvent.objects.get(decision__invoice_id=other["id"])
        settlements.notify(unrelated.id, invoice.owner_id)
        unrelated.refresh_from_db()
        assert unrelated.outcome == "no_conversation"
        assert not OutgoingMessage.objects.filter(source_event_id=unrelated.id).exists()


def test_full_length_unicode_payment_instructions_are_delivered_separately() -> None:
    from papilio_panel.modules.shop.infra.replies import decrypt_reply

    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        instructions = "🦋" * 2000
        bot, _ = payment_bot(client, server, address, instructions=instructions)
        work = incoming_text(server, bot, 2, "/topup 1000")
        process(work)
        invoice = Invoice.objects.get()
        rows = OutgoingMessage.objects.filter(event=work.event, invoice=invoice)
        assert rows.count() == 2
        texts = {decrypt_reply(bytes(row.payload_ciphertext)).text for row in rows}
        assert instructions in texts
        assert all(len(text.encode("utf-16-le")) <= 8192 for text in texts)


def test_photo_reply_is_scoped_downloaded_outside_transaction_and_saved_privately() -> None:
    from django.db import close_old_connections, connection

    from papilio_panel.modules.shop.providers import sending

    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        bot, _ = payment_bot(client, server, address, instructions="", receipt_limit=32)
        issued = incoming_text(server, bot, 2, "/topup 1000")
        process(issued)
        invoice = Invoice.objects.get()
        outgoing = OutgoingMessage.objects.get(event=issued.event)
        settings = client.get("/api/v1/payment-settings").json()
        changed = settings["definition"] | {"receipt_max_bytes": 1}
        assert (
            client.put(
                "/api/v1/payment-settings",
                changed | {"expected_revision": settings["revision"]},
                format="json",
            ).status_code
            == 200
        )
        send_claim = sending.begin(outgoing.id)
        assert send_claim is not None
        sending.send(send_claim)
        outgoing.refresh_from_db()
        assert outgoing.message_id is not None and outgoing.chat_id == 987654
        content = b"controlled-private-photo"
        server.files["photos/proof.jpg"] = content
        with server.lock:
            server.pending.append(
                {
                    "update_id": 3,
                    "message": {
                        "message_id": 3,
                        "chat": {"id": 987654, "type": "private"},
                        "from": {"id": 987654},
                        "reply_to_message": {
                            "message_id": outgoing.message_id,
                            "chat": {"id": 987654, "type": "private"},
                        },
                        "photo": [{"file_id": "proof", "file_size": len(content)}],
                        "caption": "Bank evidence, awaiting review",
                    },
                }
            )
        polling.poll(bot)
        work = InboxWork.objects.create(event=TelegramInbox.objects.get(bot_id=bot, update_id=3))
        claim = execution.begin(work.id)
        assert claim is not None
        assert connection.connection is not None
        backend_pid = connection.connection.info.backend_pid
        observed: list[str] = []

        def observe_download() -> None:
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT state FROM pg_stat_activity WHERE pid = %s", [backend_pid]
                    )
                    state = cursor.fetchone()
                assert state is not None
                observed.append(state[0])
            finally:
                close_old_connections()

        server.download_observer = observe_download
        prepared = execution.prepare(claim)
        assert prepared is not None and prepared.file is not None and prepared.file.data == content
        assert observed == ["idle"]
        execution.process(claim, prepared)
        evidence = Receipt.objects.get(invoice=invoice)
        assert (
            bytes(evidence.content) == content and evidence.note == "Bank evidence, awaiting review"
        )
        download = client.get(f"/api/v1/invoices/{invoice.id}/receipts/{evidence.id}/file")
        assert download.status_code == 200 and download.content == content
        assert download["Cache-Control"] == "private, no-store"
        assert server.file_calls == ["photos/proof.jpg"]
        # The issued cap remains 32 bytes even after settings changed to one byte.
        server.files["photos/too-big.jpg"] = b"x" * 33
        identity = client.get(f"/api/v1/bots/{bot}").json()["telegram_id"]
        server.push_photo(
            4, "too-big", chat_id=987654, reply_to_message_id=outgoing.message_id, bot_id=identity
        )
        polling.poll(bot)
        oversized = InboxWork.objects.create(
            event=TelegramInbox.objects.get(bot_id=bot, update_id=4)
        )
        oversized_claim = execution.begin(oversized.id)
        assert oversized_claim is not None
        with pytest.raises(Conflict, match="file_limit"):
            execution.prepare(oversized_claim)
        assert server.file_calls == ["photos/proof.jpg"] and Receipt.objects.count() == 1
        # The same message ID in another private chat cannot resolve this invoice.
        process(incoming_text(server, bot, 5, "/start", sender=998877))
        with server.lock:
            server.pending.append(
                {
                    "update_id": 6,
                    "message": {
                        "message_id": 6,
                        "chat": {"id": 998877, "type": "private"},
                        "from": {"id": 998877},
                        "reply_to_message": {
                            "message_id": outgoing.message_id,
                            "chat": {"id": 998877, "type": "private"},
                        },
                        "photo": [{"file_id": "proof", "file_size": len(content)}],
                    },
                }
            )
        polling.poll(bot)
        foreign = InboxWork.objects.create(event=TelegramInbox.objects.get(bot_id=bot, update_id=6))
        foreign_claim = execution.begin(foreign.id)
        assert foreign_claim is not None
        with pytest.raises(Missing):
            execution.prepare(foreign_claim)
        assert server.file_calls == ["photos/proof.jpg"] and Receipt.objects.count() == 1


def test_rejection_notification_does_not_publish_owner_audit_notes() -> None:
    from test_manual_payments import decision

    from papilio_panel.modules.payments.models import PaymentDecisionEvent
    from papilio_panel.modules.shop.infra.replies import decrypt_reply
    from papilio_panel.modules.shop.providers import settlements

    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        bot, _ = payment_bot(client, server, address)
        process(incoming_text(server, bot, 2, "/topup 1000"))
        invoice = Invoice.objects.get()
        root = f"/api/v1/invoices/{invoice.id}"
        values = decision(client.get(root).json(), "reject") | {
            "reason": "Private owner audit note; not a customer message"
        }
        assert client.post(root + "/decisions", values, format="json").status_code == 201
        event = PaymentDecisionEvent.objects.get()
        settlements.notify(event.id, invoice.owner_id)
        message = OutgoingMessage.objects.get(source_event=event)
        body = decrypt_reply(bytes(message.payload_ciphertext)).text
        assert "Private owner audit note" not in body
        assert "rejected" in body


def test_concurrent_notification_consumers_create_one_reply_and_keep_one_credit() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections
    from test_manual_payments import decision

    from papilio_panel.modules.payments.models import PaymentDecisionEvent
    from papilio_panel.modules.shop.providers import settlements

    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        bot, customer = payment_bot(client, server, address)
        process(incoming_text(server, bot, 2, "/topup 1000"))
        invoice = Invoice.objects.get()
        root = f"/api/v1/invoices/{invoice.id}"
        assert (
            client.post(
                root + "/decisions", decision(client.get(root).json()), format="json"
            ).status_code
            == 201
        )
        event = PaymentDecisionEvent.objects.get()
        barrier = Barrier(2)

        def consume(_: int) -> None:
            close_old_connections()
            barrier.wait(timeout=5)
            try:
                settlements.notify(event.id, invoice.owner_id)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(consume, [1, 2]))
        event.refresh_from_db()
        assert event.outcome == "queued" and event.processed_at is not None
        assert OutgoingMessage.objects.filter(source_event=event).count() == 1
        assert (
            client.get(f"/api/v1/customer-accounts/{customer}/wallet").json()["balance_minor"]
            == "1000"
        )
