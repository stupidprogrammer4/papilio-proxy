"""Administrative access policy for authoritative native principals."""

from papilio_panel.shared.errors import AuthenticationRejected

from ..domain import AdminPrincipal
from ..interfaces import PrincipalStorage


class AdminAccess:
    """Keep the administrative permission check on the application path."""

    def __init__(self, storage: PrincipalStorage) -> None:
        self.storage = storage

    def authorize(self, principal: AdminPrincipal) -> None:
        if not principal.is_active or not principal.is_staff:
            raise AuthenticationRejected("The supplied credentials cannot access this panel.")

    def permitted(self, actor_id: int) -> bool:
        principal = self.storage.read(actor_id)
        return principal.is_active and principal.is_staff

    def authorize_actor(self, actor_id: int) -> None:
        principal = self.storage.read(actor_id)
        self.authorize(principal)

    def authorize_owner(self, actor_id: int) -> None:
        principal = self.storage.read(actor_id)
        self.authorize(principal)
        if not principal.is_superuser:
            raise AuthenticationRejected("Only the installation owner can change this setting.")
