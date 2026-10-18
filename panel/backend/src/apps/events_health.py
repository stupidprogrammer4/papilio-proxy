import asyncio

import nats
from papilio.core.config import get_settings

from src.config.settings import PapilioSettings


async def check() -> None:
    settings = get_settings(PapilioSettings)
    client = await nats.connect(settings.events.nats_url, connect_timeout=2)
    try:
        await client.jetstream().consumer_info("receipt-ocr", "receipt-ocr-v1")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(check())
