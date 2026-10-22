"""Explicit native read shapes scoped to the core and node owner."""

from uuid import UUID

from django.core.paginator import EmptyPage, Paginator

from papilio_panel.shared.errors import Missing

from ..domain import (
    CoreKind,
    CorePage,
    CoreRead,
    CoreSearch,
    InboundPage,
    InboundSearch,
    XrayInboundRead,
    XraySettings,
)
from ..models import Core, XrayInbound


def core_read(row: Core) -> CoreRead:
    return CoreRead(
        row.id,
        row.owner_id,
        row.node_id,
        CoreKind(row.kind),
        row.name,
        XraySettings(row.xray.default_user_level),
    )


def inbound_read(row: XrayInbound) -> XrayInboundRead:
    return XrayInboundRead(row.id, row.core_id, row.tag, row.public_host, row.port)


class DjangoCoreReader:
    def read(self, core_id: UUID, actor_id: int) -> CoreRead:
        try:
            row = Core.objects.select_related("xray").get(
                pk=core_id,
                owner_id=actor_id,
                node__owner_id=actor_id,
                kind=CoreKind.XRAY,
            )
        except Core.DoesNotExist as error:
            raise Missing("The Xray core was not found.") from error
        return core_read(row)

    def search(self, values: CoreSearch) -> CorePage:
        rows = (
            Core.objects.filter(
                owner_id=values.actor_id, node__owner_id=values.actor_id, kind=CoreKind.XRAY
            )
            .select_related("xray")
            .order_by("created_at", "id")
        )
        if values.query:
            rows = rows.filter(name__icontains=values.query)
        paginator = Paginator(rows, values.page_size)
        try:
            page = paginator.page(values.page)
        except EmptyPage as error:
            raise Missing("The requested core page was not found.") from error
        return CorePage(
            tuple(core_read(row) for row in page), paginator.count, values.page, values.page_size
        )

    def read_inbound(self, core_id: UUID, inbound_id: UUID, actor_id: int) -> XrayInboundRead:
        try:
            row = XrayInbound.objects.get(
                pk=inbound_id,
                core_id=core_id,
                core__core__owner_id=actor_id,
                core__core__node__owner_id=actor_id,
            )
        except XrayInbound.DoesNotExist as error:
            raise Missing("The inbound was not found in this core.") from error
        return inbound_read(row)

    def search_inbounds(self, values: InboundSearch) -> InboundPage:
        rows = XrayInbound.objects.filter(
            core_id=values.core_id,
            core__core__owner_id=values.actor_id,
            core__core__node__owner_id=values.actor_id,
        ).order_by("tag", "id")
        if values.query:
            rows = rows.filter(tag__icontains=values.query)
        paginator = Paginator(rows, values.page_size)
        try:
            page = paginator.page(values.page)
        except EmptyPage as error:
            raise Missing("The requested inbound page was not found.") from error
        return InboundPage(
            tuple(inbound_read(row) for row in page), paginator.count, values.page, values.page_size
        )
