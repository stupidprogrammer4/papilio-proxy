from enum import StrEnum

from papilio.api.requests.queries import BaseQuery
from papilio.schemas.inputs import BaseDTO
from pydantic import Field, model_validator


class TicketStatus(StrEnum):
    OPEN = "open"
    WAITING_CUSTOMER = "waiting_customer"
    CLOSED = "closed"


class ClosedReplyMode(StrEnum):
    REJECT = "reject"
    REOPEN = "reopen"


class SupportPolicy(BaseDTO):
    new_tickets_enabled: bool
    customer_replies_enabled: bool
    staff_reply_status: TicketStatus
    staff_replies_enabled: bool
    customer_closure_enabled: bool
    customer_reopen_enabled: bool
    closed_reply_mode: ClosedReplyMode
    max_open_tickets: int = Field(gt=0)
    max_messages_per_ticket: int = Field(gt=0)
    max_message_chars: int = Field(gt=0, le=16383)


class TicketCreate(BaseDTO):
    request_key: str = Field(min_length=8, max_length=128)
    subject: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1)
    subscription_id: int | None = Field(default=None, gt=0)
    topup_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def valid_context(self) -> "TicketCreate":
        if self.subscription_id is not None and self.topup_id is not None:
            raise ValueError(
                "A ticket may retain one financial/service context"
            )
        if not self.subject.strip() or not self.body.strip():
            raise ValueError("Subject and message cannot be blank")
        return self


class TicketReply(BaseDTO):
    request_key: str = Field(min_length=8, max_length=128)
    expected_revision: int = Field(ge=1)
    body: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_body(self) -> "TicketReply":
        if not self.body.strip():
            raise ValueError("Message cannot be blank")
        return self


class TicketStateWrite(BaseDTO):
    status: TicketStatus
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=250)


class TicketSearch(BaseQuery):
    q: str | None = Field(default=None, max_length=100)
    status: TicketStatus | None = None
    customer_id: int | None = Field(default=None, gt=0)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class CustomerTicketSearch(BaseQuery):
    q: str | None = Field(default=None, max_length=100)
    status: TicketStatus | None = None
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class ThreadSearch(BaseQuery):
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
