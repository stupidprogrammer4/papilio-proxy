"""Native authorized service read shapes and private Xray credential adaptation."""

from uuid import UUID

from cryptography.fernet import InvalidToken
from django.core.paginator import EmptyPage, Paginator
from django.db.models import F, QuerySet

from papilio_panel.shared.credentials import credential_cipher
from papilio_panel.shared.errors import Conflict, Missing
from papilio_panel.shared.operations import OperationStatus

from ..domain import ServicePage, ServiceRead, ServiceSearch, SubscriptionGrant, XrayCredential
from ..models import ServiceAccount


def authorized_services(actor_id: int) -> QuerySet[ServiceAccount]:
    return ServiceAccount.objects.filter(
        owner_id=actor_id,
        core__owner_id=actor_id,
        core__node__owner_id=actor_id,
        xray__inbound__core_id=F("core_id"),
    ).select_related("xray")


def service_read(row: ServiceAccount) -> ServiceRead:
    return ServiceRead(
        row.id,
        row.owner_id,
        row.core_id,
        row.xray.inbound_id,
        row.name,
        OperationStatus(row.status),
        row.attempts,
        row.error_code,
        row.worker_pid,
        row.lease_until,
    )


def credential_read(row: ServiceAccount) -> XrayCredential:
    try:
        identifier = UUID(
            credential_cipher().decrypt(bytes(row.xray.credential_ciphertext)).decode()
        )
    except (InvalidToken, ValueError, UnicodeError) as error:
        raise Conflict("The persisted service credential cannot be read.") from error
    return XrayCredential(identifier, row.xray.email, row.xray.level)


class DjangoServiceReader:
    def read(self, service_id: UUID, actor_id: int) -> ServiceRead:
        try:
            row = authorized_services(actor_id).get(pk=service_id)
        except ServiceAccount.DoesNotExist as error:
            raise Missing("The service was not found.") from error
        return service_read(row)

    def credential(self, service_id: UUID, actor_id: int) -> XrayCredential:
        try:
            row = authorized_services(actor_id).get(pk=service_id)
        except ServiceAccount.DoesNotExist as error:
            raise Missing("The service was not found.") from error
        return credential_read(row)

    def search(self, values: ServiceSearch) -> ServicePage:
        rows = authorized_services(values.actor_id).order_by("created_at", "id")
        if values.query:
            rows = rows.filter(name__icontains=values.query)
        paginator = Paginator(rows, values.page_size)
        try:
            page = paginator.page(values.page)
        except EmptyPage as error:
            raise Missing("The requested service page was not found.") from error
        return ServicePage(
            tuple(service_read(row) for row in page), paginator.count, values.page, values.page_size
        )

    def subscription_grant(self, service_id: UUID, actor_id: int) -> SubscriptionGrant:
        try:
            row = authorized_services(actor_id).get(pk=service_id)
        except ServiceAccount.DoesNotExist as error:
            raise Missing("The service was not found.") from error
        return SubscriptionGrant(row.id, row.subscription_nonce)

    def read_grant(self, grant: SubscriptionGrant) -> ServiceRead:
        try:
            row = ServiceAccount.objects.select_related("xray").get(
                pk=grant.service_id,
                subscription_nonce=grant.nonce,
                core__owner_id=F("owner_id"),
                core__node__owner_id=F("owner_id"),
                xray__inbound__core_id=F("core_id"),
            )
        except ServiceAccount.DoesNotExist as error:
            raise Missing("The subscription is unavailable.") from error
        return service_read(row)
