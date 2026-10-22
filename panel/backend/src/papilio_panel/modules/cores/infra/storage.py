"""Native core aggregate writes with database-enforced request/tag identity."""

from django.db import IntegrityError

from papilio_panel.shared.errors import Conflict

from ..domain import (
    CoreCreation,
    CoreKind,
    InboundCreation,
    XrayInboundRegistration,
    XrayRegistration,
)
from ..models import Core, XrayCore, XrayInbound
from .readers import DjangoCoreReader, inbound_read


class DjangoCoreStorage(DjangoCoreReader):
    def register_xray(self, values: XrayRegistration) -> CoreCreation:
        try:
            row, created = Core.objects.get_or_create(
                owner_id=values.actor_id,
                request_key=values.request_key,
                defaults={"node_id": values.node_id, "kind": CoreKind.XRAY, "name": values.name},
            )
        except IntegrityError as error:
            raise Conflict("This native core is already registered for the node.") from error
        if created:
            XrayCore.objects.create(core=row, default_user_level=values.xray.default_user_level)
        return CoreCreation(self.read(row.id, values.actor_id), created)

    def register_inbound(self, values: XrayInboundRegistration) -> InboundCreation:
        try:
            row, created = XrayInbound.objects.get_or_create(
                core_id=values.core_id,
                request_key=values.request_key,
                defaults={
                    "tag": values.definition.tag,
                    "public_host": values.definition.public_host,
                    "port": values.definition.port,
                },
            )
        except IntegrityError as error:
            raise Conflict("This inbound tag is already registered for the core.") from error
        return InboundCreation(inbound_read(row), created)
