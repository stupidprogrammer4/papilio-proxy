"""Shop configuration, sender identity and durable conversation contracts."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from papilio_panel.modules.bots.domain import BotEventRead, TelegramReply
from papilio_panel.modules.customers.domain import CustomerRead
from papilio_panel.modules.payments.domain import ReceiptContent
from papilio_panel.shared.errors import Conflict


class ReceiptDownloadFailure(Conflict):
    """Safe transport outcome retained for the native task's retry decision."""

    def __init__(self, transport_code: str, retry_after_seconds: int | None = None) -> None:
        super().__init__("The receipt could not be downloaded: " + transport_code)
        self.transport_code = transport_code
        self.retry_after_seconds = retry_after_seconds


class ShopTaskName(StrEnum):
    DISPATCH = "papilio.shop.dispatch"
    PROCESS = "papilio.shop.process"
    SEND = "papilio.shop.send"
    SETTLEMENT = "papilio.shop.settlement"


class WorkState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class MessageState(StrEnum):
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    RETRY = "retry"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


DEFAULT_TEXTS = {
    "en": {
        "welcome": "Welcome, $name. Choose an action.",
        ("help"): (
            "Choose a product, review its price and confirm a purchase using your wallet. "
            "To add credit, send /topup followed by the amount in rials. Reply to your "
            "invoice with a receipt photo or send /receipt INVOICE_ID TRANSFER_REFERENCE. "
            "Funds are credited only after the operator verifies the payment."
        ),
        "catalogue": "Products · page $page",
        "wallet": "Wallet: $balance IRR (rials).",
        ("offer"): (
            "$product\nPrice: $amount IRR (rials). Confirm to buy using your wallet. "
            "This initial service is unlimited VLESS/TCP without TLS. If terms change, "
            "select the product again."
        ),
        ("invoice"): (
            "Payment invoice: $invoice_id\nExact amount: $amount IRR (rials)\nAccount "
            "holder: $name\nReceiving account: $destination\nStatus: $status\nReply to this "
            "message with your receipt photo, or send /receipt $invoice_id "
            "TRANSFER_REFERENCE."
        ),
        "receipt": "Your payment evidence is recorded and awaits review. Invoice: $invoice_id",
        "paid": "Payment approved: $amount IRR has been credited once. Invoice: $invoice_id",
        ("queued"): (
            "Purchase recorded: $order_id\nAmount: $amount IRR. Provisioning continues "
            "in the background. Use the status button to obtain the subscription after "
            "delivery."
        ),
        "order": "Order: $order_id\nAmount: $amount IRR\nService state: $status",
        "subscription": "Your private subscription:\n$url",
        "error": "The operation could not be completed: $reason",
        ("admin_receipt"): (
            "Receipt awaiting review. Invoice: $invoice_id\nAmount: $amount IRR\nTransfer"
            " reference: $reference\nOpen the panel to inspect the private receipt and "
            "verify the transfer:\n$url"
        ),
        "products_button": "Products",
        "wallet_button": "Wallet",
        "help_button": "Top-up and help",
        "orders_button": "My purchases",
        "next_button": "Next page",
        "previous_button": "Previous page",
        "buy_button": "Confirm purchase",
        "status_button": "Service status / subscription",
        "menu_button": "Main menu",
        "orders": "Your purchases · page $page",
        "empty": "There are no items on this page.",
    },
    "fa": {
        "welcome": "$name، خوش آمدید. یک گزینه را انتخاب کنید.",
        ("help"): (
            "محصول را انتخاب، قیمت را بررسی و خرید از کیف پول را تأیید کنید. برای شارژ، "
            "دستور /topup و سپس مبلغ ریالی را بفرستید. عکس رسید را در پاسخ به فاکتور "
            "بفرستید یا /receipt شناسه‌فاکتور شماره‌پیگیری را ارسال کنید. شارژ تنها "
            "پس از بررسی پرداخت توسط اپراتور انجام می‌شود."
        ),
        "catalogue": "محصولات · صفحه $page",
        "wallet": "موجودی کیف پول: $balance ریال (IRR).",
        ("offer"): (
            "$product\nقیمت: $amount ریال. برای خرید از کیف پول تأیید کنید. سرویس اولیه "
            "نامحدود VLESS/TCP بدون TLS است. اگر شرایط عوض شد، محصول را دوباره انتخاب "
            "کنید."
        ),
        ("invoice"): (
            "فاکتور پرداخت: $invoice_id\nمبلغ دقیق: $amount ریال\nصاحب حساب: $name\nحساب "
            "مقصد: $destination\nوضعیت: $status\nعکس رسید را در پاسخ به همین پیام بفرستید "
            "یا دستور /receipt $invoice_id شماره‌پیگیری را ارسال کنید."
        ),
        "receipt": "مدرک پرداخت ثبت شد و منتظر بررسی است. فاکتور: $invoice_id",
        "paid": "پرداخت تأیید شد و $amount ریال یک بار به کیف پول رفت. فاکتور: $invoice_id",
        ("queued"): (
            "خرید ثبت شد: $order_id\nمبلغ: $amount ریال. ساخت سرویس در پس‌زمینه ادامه "
            "دارد؛ پس از آماده‌شدن، دکمهٔ وضعیت را برای دریافت اشتراک بزنید."
        ),
        "order": "سفارش: $order_id\nمبلغ: $amount ریال\nوضعیت سرویس: $status",
        "subscription": "اشتراک خصوصی شما:\n$url",
        "error": "انجام عملیات ممکن نشد: $reason",
        ("admin_receipt"): (
            "رسید در انتظار بررسی است. فاکتور: $invoice_id\nمبلغ: $amount ریال\nشماره "
            "پیگیری: $reference\nبرای دیدن پیوست خصوصی و بررسی واریز، پنل را باز کنید:\n"
            "$url"
        ),
        "products_button": "محصولات",
        "wallet_button": "کیف پول",
        "help_button": "شارژ و راهنما",
        "orders_button": "خریدهای من",
        "next_button": "صفحه بعد",
        "previous_button": "صفحه قبل",
        "buy_button": "تأیید خرید",
        "status_button": "وضعیت سرویس / اشتراک",
        "menu_button": "منوی اصلی",
        "orders": "خریدهای شما · صفحه $page",
        "empty": "در این صفحه موردی وجود ندارد.",
    },
}


def default_texts() -> dict[str, dict[str, str]]:
    return deepcopy(DEFAULT_TEXTS)


@dataclass(frozen=True)
class ShopDefinition:
    public_origin: str = ""
    enabled: bool = False
    delivery_enabled: bool = True
    locale: str = "fa"
    page_size: int = 10
    retry_seconds: int = 30
    lease_seconds: int = 120
    max_attempts: int = 5
    confirmation_ttl_seconds: int = 900
    ambiguous_delivery: str = "hold"
    texts: dict[str, dict[str, str]] = field(default_factory=default_texts)


@dataclass(frozen=True)
class ShopSettingsCreate:
    actor_id: int
    bot_id: UUID
    definition: ShopDefinition


@dataclass(frozen=True)
class ShopSettingsChange:
    actor_id: int
    bot_id: UUID
    expected_revision: int
    definition: ShopDefinition


@dataclass(frozen=True)
class ShopSettingsRead:
    bot_id: UUID
    owner_id: int
    revision: int
    definition: ShopDefinition


@dataclass(frozen=True)
class CustomerBinding:
    id: UUID
    owner_id: int
    telegram_user_id: int
    customer_id: UUID | None


@dataclass(frozen=True)
class BindingReservation:
    binding: CustomerBinding
    created: bool


@dataclass(frozen=True)
class ShopCustomerContext:
    event: BotEventRead
    settings: ShopSettingsRead
    customer: CustomerRead


@dataclass(frozen=True)
class InboxReference:
    event_id: int
    bot_id: UUID
    owner_id: int


@dataclass(frozen=True)
class WorkDelivery:
    id: UUID
    timeout_seconds: int


@dataclass(frozen=True)
class WorkRead:
    id: UUID
    event_id: int
    status: WorkState
    attempts: int
    error_code: str | None


@dataclass(frozen=True)
class WorkLease:
    token: UUID
    attempts: int


@dataclass(frozen=True)
class WorkRetryOutcome:
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class ShopSendOutcome:
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class SendDisposition:
    status: MessageState
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class MessageRead:
    id: UUID
    event_id: int
    bot_id: UUID
    owner_id: int
    administrator: bool
    status: MessageState
    attempts: int
    message_id: int | None
    error_code: str | None
    retry_at: datetime | None
    created_at: datetime
    lease_until: datetime | None


@dataclass(frozen=True)
class WorkClaim:
    id: UUID
    token: UUID
    event: BotEventRead
    settings: ShopSettingsRead
    attempts: int


@dataclass(frozen=True)
class ReplyWrite:
    event_id: int
    bot_id: UUID
    owner_id: int
    reply: TelegramReply
    administrator: bool = False
    invoice_id: UUID | None = None
    source_event_id: UUID | None = None


@dataclass(frozen=True)
class MessageClaim:
    id: UUID
    token: UUID
    attempts: int
    values: ReplyWrite
    settings: ShopSettingsRead


@dataclass(frozen=True)
class PurchaseConfirmation:
    id: UUID
    bot_id: UUID
    customer_id: UUID
    product_id: UUID
    offer_revision: int
    service_name: str
    expires_at: datetime
    order_id: UUID | None


@dataclass(frozen=True)
class InvoiceReplyLookup:
    bot_id: UUID
    owner_id: int
    telegram_user_id: int
    message_id: int


@dataclass(frozen=True)
class InvoiceOrigin:
    invoice_id: UUID
    event_id: int
    bot_id: UUID
    owner_id: int
    customer_id: UUID


@dataclass(frozen=True)
class ReceiptTarget:
    invoice_id: UUID
    reference: str
    note: str
    max_bytes: int


@dataclass(frozen=True)
class PreparedReceipt:
    event_id: int
    invoice_id: UUID
    reference: str
    note: str
    file: ReceiptContent | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ReceiptReplies:
    acknowledgement: TelegramReply
    review_notice: TelegramReply


@dataclass(frozen=True)
class ShopTextContext:
    name: str = ""
    product: str = ""
    amount: str = ""
    balance: str = ""
    page: str = ""
    invoice_id: str = ""
    order_id: str = ""
    destination: str = ""
    instructions: str = ""
    reference: str = ""
    status: str = ""
    url: str = ""
    reason: str = ""
