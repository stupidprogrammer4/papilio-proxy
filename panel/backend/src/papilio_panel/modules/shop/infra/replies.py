"""Native encrypted reply serialization independent of broker and HTTP credentials."""

import json
from dataclasses import asdict

from rest_framework import serializers

from papilio_panel.modules.bots.domain import TelegramButton, TelegramReply
from papilio_panel.shared.credentials import credential_cipher


class ButtonSerializer(serializers.Serializer):
    text = serializers.CharField(trim_whitespace=False)
    callback_data = serializers.CharField(max_length=64, allow_blank=True)
    url = serializers.CharField(allow_blank=True, trim_whitespace=False)


class ReplySerializer(serializers.Serializer):
    text = serializers.CharField(trim_whitespace=False)
    buttons = ButtonSerializer(many=True)


def encrypt_reply(reply: TelegramReply) -> bytes:
    return credential_cipher().encrypt(json.dumps(asdict(reply), ensure_ascii=False).encode())


def decrypt_reply(ciphertext: bytes) -> TelegramReply:
    packet = ReplySerializer(data=json.loads(credential_cipher().decrypt(ciphertext)))
    packet.is_valid(raise_exception=True)
    values = packet.validated_data
    return TelegramReply(
        values["text"],
        tuple(
            TelegramButton(item["text"], item["callback_data"], item["url"])
            for item in values["buttons"]
        ),
    )
