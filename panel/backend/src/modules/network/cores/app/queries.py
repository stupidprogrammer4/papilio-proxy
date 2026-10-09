import asyncio

from papilio.errors.exceptions import ConflictException

from src.config.settings import PapilioSettings
from src.modules.network.configurations.interfaces import IConfigurationCommand
from src.modules.network.cores.app.exports import CoreDocumentComposition
from src.modules.network.cores.domain.exports import (
    CoreExport,
    CoreExportRequest,
)
from src.modules.network.cores.domain.models import CoreModel
from src.modules.network.cores.infra.readers import CoreConfigurationReader
from src.modules.network.cores.interfaces import ICoreService


class CoreExportQuery:
    def __init__(
        self,
        cores: ICoreService,
        configurations: IConfigurationCommand,
        reader: CoreConfigurationReader,
        settings: PapilioSettings,
    ) -> None:
        self.cores = cores
        self.configurations = configurations
        self.reader = reader
        self.settings = settings

    async def export(
        self, core_id: int, data: CoreExportRequest
    ) -> CoreExport:
        core = await self.cores.get(core_id)
        capacity = self.settings.core_exports
        if capacity is None or not capacity.enabled:
            raise ConflictException(
                message="Core exports are disabled.",
                message_code="core_export_disabled",
                unique_dict={},
            )
        revisions = await self.reader.configurations(
            core_id, capacity.max_configurations + 1
        )
        if not revisions:
            raise ConflictException(
                message="Core has no configurations.",
                message_code="core_export_empty",
                unique_dict={"core_id": core_id},
            )
        if len(revisions) > capacity.max_configurations:
            raise ConflictException(
                message="Core export capacity exceeded.",
                message_code="core_export_capacity",
                unique_dict={"core_id": core_id},
            )
        exports = await self.configurations.server_many(
            [row.configuration_id for row in revisions]
        )
        expected = {row.configuration_id: row.revision for row in revisions}
        if any(
            expected[row.configuration_id] != row.revision for row in exports
        ):
            raise ConflictException(
                message="Configuration changed; retry export.",
                message_code="core_export_stale",
                unique_dict={"core_id": core_id},
            )
        result = await asyncio.to_thread(
            CoreDocumentComposition.compose,
            CoreModel.model_validate(core.model_dump()),
            data,
            exports,
            capacity,
        )
        return result
