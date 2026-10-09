from src.modules.billing.sms_origins.domain.facts import SmsIntakeFacts
from src.modules.billing.sms_origins.infra.intake import SmsIntakeReader


class SmsOriginIntakeQuery:
    def __init__(self, reader: SmsIntakeReader) -> None:
        self.reader = reader

    async def get(self, device_id: int) -> SmsIntakeFacts | None:
        result = await self.reader.get(device_id)
        return result
