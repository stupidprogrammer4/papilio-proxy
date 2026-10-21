"""Read authoritative Django authentication facts."""

from django.contrib.auth.models import User

from papilio_panel.shared.errors import AuthenticationRejected

from ..domain import AdminPrincipal


class DjangoPrincipalStorage:
    def read(self, actor_id: int) -> AdminPrincipal:
        try:
            user = User.objects.get(pk=actor_id)
        except User.DoesNotExist as error:
            raise AuthenticationRejected("The account is unavailable.") from error
        return AdminPrincipal(
            id=user.pk,
            username=user.username,
            is_active=user.is_active,
            is_staff=user.is_staff,
            is_superuser=user.is_superuser,
        )
