import hashlib
import json
from typing import Any, NoReturn

from papilio.errors.exceptions import ConflictException

from src.modules.network.configurations.app.server_json import (
    ServerJsonComposition,
)
from src.modules.network.configurations.domain.results import (
    ConfigurationServerExport,
)
from src.modules.network.cores.domain.exports import (
    CoreArtifact,
    CoreConfigurationRevision,
    CoreExport,
    CoreExportCapacity,
    CoreExportRequest,
)
from src.modules.network.cores.domain.models import CoreModel


class CoreDocumentComposition:
    @staticmethod
    def reject(code: str) -> NoReturn:
        raise ConflictException(
            message=(
                "Core documents conflict; "
                "use isolated mode or align their settings."
            ),
            message_code=code,
            unique_dict={},
        )

    @classmethod
    def merged(
        cls, kind: str, exports: list[ConfigurationServerExport]
    ) -> str:
        if kind not in {"xray", "sing_box"}:
            cls.reject("core_export_merge_unsupported")
        root: dict[str, Any] | None = None
        inbounds: list[dict[str, Any]] = []
        outbounds: dict[str, dict[str, Any]] = {}
        tags: set[str] = set()
        for export in exports:
            try:
                document = json.loads(
                    export.download.content,
                    parse_constant=ServerJsonComposition.reject_constant,
                    object_pairs_hook=ServerJsonComposition.unique_object,
                )
            except (ValueError, TypeError, RecursionError):
                cls.reject("core_export_invalid_json")
            if not isinstance(document, dict):
                cls.reject("core_export_invalid_json")
            incoming = document.pop("inbounds", None)
            outgoing = document.pop("outbounds", None)
            if (
                not isinstance(incoming, list)
                or not incoming
                or not isinstance(outgoing, list)
            ):
                cls.reject("core_export_invalid_json")
            for inbound in incoming:
                if not isinstance(inbound, dict):
                    cls.reject("core_export_invalid_json")
                tag = inbound.get("tag")
                if not isinstance(tag, str) or not tag or tag in tags:
                    cls.reject("core_export_inbound_tag_conflict")
                tags.add(tag)
                inbounds.append(inbound)
            for outbound in outgoing:
                if not isinstance(outbound, dict):
                    cls.reject("core_export_invalid_json")
                tag = outbound.get("tag")
                if not isinstance(tag, str) or not tag:
                    cls.reject("core_export_outbound_tag_required")
                if tag in outbounds and outbounds[tag] != outbound:
                    cls.reject("core_export_outbound_conflict")
                outbounds[tag] = outbound
            if root is None:
                root = document
            elif root != document:
                cls.reject("core_export_global_conflict")
        if root is None:
            cls.reject("core_export_empty")
        root["inbounds"] = inbounds
        root["outbounds"] = list(outbounds.values())
        return json.dumps(root, ensure_ascii=False, indent=2, allow_nan=False)

    @classmethod
    def compose(
        cls,
        core: CoreModel,
        request: CoreExportRequest,
        exports: list[ConfigurationServerExport],
        capacity: CoreExportCapacity,
    ) -> CoreExport:
        artifacts: list[CoreArtifact] = []
        if request.mode == "merged":
            content = cls.merged(core.kind, exports)
            artifacts.append(
                CoreArtifact(
                    filename=f"core-{core.id}.json",
                    content=content,
                    media_type="application/json",
                    sha256=hashlib.sha256(content.encode()).hexdigest(),
                    configurations=[
                        CoreConfigurationRevision(
                            configuration_id=item.configuration_id,
                            revision=item.revision,
                        )
                        for item in exports
                    ],
                )
            )
        else:
            for item in exports:
                content = item.download.content
                artifacts.append(
                    CoreArtifact(
                        filename=item.download.filename,
                        content=content,
                        media_type=item.download.media_type,
                        sha256=hashlib.sha256(content.encode()).hexdigest(),
                        configurations=[
                            CoreConfigurationRevision(
                                configuration_id=item.configuration_id,
                                revision=item.revision,
                            )
                        ],
                    )
                )
        if (
            sum(len(item.content.encode()) for item in artifacts)
            > capacity.max_output_bytes
        ):
            cls.reject("core_export_output_capacity")
        return CoreExport(
            core_id=core.id,
            node_id=core.node_id,
            kind=core.kind,
            mode=request.mode,
            artifacts=artifacts,
        )
