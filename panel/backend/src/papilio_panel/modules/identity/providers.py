"""Explicit identity implementation bindings."""

from .app.access import AdminAccess
from .app.setup import OwnerSetup
from .infra.credentials import DjangoCredentialValidation
from .infra.principals import DjangoPrincipalStorage
from .infra.setup import DjangoSetupStorage
from .interfaces import AdminAccessCapability, OwnerSetupCapability

owner_setup: OwnerSetupCapability = OwnerSetup(DjangoSetupStorage(), DjangoCredentialValidation())
admin_access: AdminAccessCapability = AdminAccess(DjangoPrincipalStorage())
