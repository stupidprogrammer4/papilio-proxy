"""Adapt native credential validators for every application entrypoint."""

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.db.models import CharField

from papilio_panel.shared.errors import InvalidInput


class DjangoCredentialValidation:
    def validate(self, username: str, password: str) -> None:
        try:
            username_field = User._meta.get_field("username")
            assert isinstance(username_field, CharField)
            username_field.clean(username, None)
            UnicodeUsernameValidator()(username)
            validate_password(password, user=User(username=username))
        except ValidationError as error:
            raise InvalidInput(" ".join(error.messages)) from error
