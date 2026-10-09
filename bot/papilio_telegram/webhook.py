import asyncio
import json

from aiogram import Bot
from aiogram.types import Update
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web
from pydantic import ValidationError


class ForegroundRequestHandler(SimpleRequestHandler):
    async def _handle_request(
        self, bot: Bot, request: web.Request
    ) -> web.Response:
        raw = await request.read()
        try:
            update = await asyncio.to_thread(json.loads, raw)
            if not isinstance(update, dict):
                raise ValueError("Update must be an object")
            parsed = await asyncio.to_thread(
                Update.model_validate, update, context={"bot": bot}
            )
        except (ValueError, RecursionError, ValidationError):
            raise web.HTTPBadRequest() from None
        result = await self.dispatcher.feed_update(bot, parsed, **self.data)
        return web.Response(
            body=self._build_response_writer(bot=bot, result=result)
        )
