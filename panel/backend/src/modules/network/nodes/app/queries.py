from datetime import UTC, datetime, timedelta

from src.config.settings import PapilioSettings
from src.modules.network.nodes.domain.results import NodeQuality
from src.modules.network.nodes.infra.readers import NodeQualityFactsReader


class NodeQualityQuery:
    def __init__(
        self, reader: NodeQualityFactsReader, settings: PapilioSettings
    ) -> None:
        self.reader = reader
        self.settings = settings

    async def ranked(self, client_network: str) -> list[NodeQuality]:
        now = datetime.now(UTC).replace(tzinfo=None)
        since = now - timedelta(
            minutes=self.settings.operations.quality_window_minutes
        )
        facts = await self.reader.for_network(client_network, since, now, True)
        result: list[NodeQuality] = []
        for item in facts:
            average = (
                round(item.latency_total_ms / item.successful_count)
                if item.successful_count
                else None
            )
            success_rate = (
                item.successful_count / item.sample_count
                if item.sample_count
                else 0.0
            )
            score = (
                round(average / success_rate, 2)
                if item.sample_count
                >= self.settings.operations.quality_min_samples
                and average is not None
                and success_rate
                >= self.settings.operations.quality_min_success_ratio
                else None
            )
            result.append(
                NodeQuality(
                    item.node_id,
                    item.code,
                    item.label,
                    item.protocol,
                    client_network,
                    item.sample_count,
                    item.successful_count,
                    average,
                    score,
                )
            )
        return sorted(
            result,
            key=lambda item: (
                item.score is None,
                item.score if item.score is not None else float("inf"),
                item.node_id,
            ),
        )
