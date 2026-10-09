import json
from collections.abc import Sequence

from papilio.errors.exceptions import ConflictException
from papilio.security.crypto import decrypt, encrypt

from src.modules.network.configurations.domain.models import (
    ConfigurationJsonRevisionModel,
)
from src.modules.network.configurations.domain.results import (
    ConfigurationDownload,
    StoredSettings,
)
from src.modules.network.configurations.domain.server_json import (
    ServerJsonCapacity,
    ServerJsonDocument,
    ServerJsonRevision,
)


class ServerJsonComposition:
    marker = {"$papilio": "managed"}
    kinds = {"xray", "sing_box"}

    @staticmethod
    def reject_constant(value: str) -> None:
        raise ValueError("Non-finite JSON numbers are not supported")

    @staticmethod
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    @classmethod
    def normalize(
        cls, document: ServerJsonDocument, capacity: ServerJsonCapacity
    ) -> ServerJsonDocument:
        if len(document.source.encode("utf-8")) > capacity.max_document_bytes:
            raise ValueError("JSON exceeds the configured byte capacity")
        value = json.loads(
            document.source,
            parse_constant=cls.reject_constant,
            object_pairs_hook=cls.unique_object,
        )
        if not isinstance(value, dict):
            raise ValueError("The server JSON root must be an object")
        pending: list[tuple[object, int]] = [(value, 1)]
        while pending:
            node, depth = pending.pop()
            if depth > capacity.max_depth:
                raise ValueError("JSON exceeds the configured depth capacity")
            if isinstance(node, dict):
                pending.extend((child, depth + 1) for child in node.values())
            elif isinstance(node, list):
                pending.extend((child, depth + 1) for child in node)
        if document.mode == "managed" and value.get("inbounds") != [
            cls.marker
        ]:
            raise ValueError("Managed JSON needs one managed inbound marker")
        source = json.dumps(
            value, ensure_ascii=False, indent=2, allow_nan=False
        )
        if len(source.encode("utf-8")) > capacity.max_document_bytes:
            raise ValueError("Formatted JSON exceeds the byte capacity")
        return ServerJsonDocument(mode=document.mode, source=source)

    @staticmethod
    def require_assignable(settings: StoredSettings) -> None:
        if (
            settings.server_json is not None
            and settings.server_json.mode == "experimental"
        ):
            raise ConflictException(
                message="ورودی آزمایشی به اشتراک کاربران تخصیص داده نمی‌شود.",
                message_code="configuration_json_experimental",
                unique_dict={},
            )

    @classmethod
    def apply(
        cls, generated: ConfigurationDownload, document: ServerJsonDocument
    ) -> ConfigurationDownload:
        custom = json.loads(document.source)
        if document.mode == "experimental":
            content = document.source
        else:
            base = json.loads(generated.content)
            if custom.get("inbounds") != [cls.marker]:
                raise ValueError("Managed inbound marker is missing")
            custom["inbounds"] = base["inbounds"]
            base.update(custom)
            content = json.dumps(
                base, ensure_ascii=False, indent=2, allow_nan=False
            )
        return ConfigurationDownload(
            generated.filename, content, "application/json"
        )

    @staticmethod
    def encode(settings: StoredSettings, key: str) -> str:
        return encrypt(settings.model_dump_json(), key)

    @staticmethod
    def decode(source: str, key: str) -> StoredSettings:
        return StoredSettings.model_validate_json(decrypt(source, key))

    @classmethod
    def history(
        cls, rows: Sequence[ConfigurationJsonRevisionModel], key: str
    ) -> list[ServerJsonRevision]:
        result: list[ServerJsonRevision] = []
        for row in rows:
            if row.created_at is None:
                raise ValueError("Persisted history requires a timestamp")
            result.append(
                ServerJsonRevision(
                    id=row.id,
                    revision=row.revision,
                    staff_id=row.staff_id,
                    reason=row.reason,
                    created_at=row.created_at,
                    document=cls.decode(
                        row.encrypted_settings, key
                    ).server_json,
                )
            )
        return result
