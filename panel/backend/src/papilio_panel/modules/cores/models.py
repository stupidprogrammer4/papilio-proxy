"""Shared native identity with separate Xray policy and existing inbound records."""

import uuid

from django.conf import settings
from django.db import models

from .domain import CoreKind


class Core(models.Model):
    xray: "XrayCore"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id: int
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    node_id: uuid.UUID
    node = models.ForeignKey("nodes.Node", on_delete=models.PROTECT)
    kind = models.CharField(max_length=16, choices=[(item.value, item.value) for item in CoreKind])
    name = models.CharField(max_length=80)
    request_key = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "request_key"], name="cores_owner_request"),
            models.UniqueConstraint(fields=["node", "kind"], name="cores_node_kind"),
        ]


class XrayCore(models.Model):
    core = models.OneToOneField(
        Core, primary_key=True, on_delete=models.CASCADE, related_name="xray"
    )
    default_user_level = models.BigIntegerField(default=0)


class XrayInbound(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    core_id: uuid.UUID
    core = models.ForeignKey(XrayCore, on_delete=models.PROTECT, related_name="inbounds")
    request_key = models.UUIDField()
    tag = models.CharField(max_length=255)
    public_host = models.CharField(max_length=255)
    port = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["core", "request_key"], name="xray_inbounds_request"),
            models.UniqueConstraint(fields=["core", "tag"], name="xray_inbounds_tag"),
        ]
