"""Persistence for the one-time installation owner setup."""

import uuid

from django.conf import settings
from django.db import models


class OwnerSetupState(models.Model):
    """The singleton row serializes initialization through a conditional write."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    claimed = models.BooleanField(default=False)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)


class SetupGrant(models.Model):
    """Only the signed token's non-secret identity is persisted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
