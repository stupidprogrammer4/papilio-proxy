from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import (
    setup_application,
)
from aiohttp import web

from papilio_telegram.admission import WebhookAdmission
from papilio_telegram.api import BotApi
from papilio_telegram.config import BotSettings
from papilio_telegram.delivery import register_delivery
from papilio_telegram.handlers import register
from papilio_telegram.webhook import ForegroundRequestHandler


def main() -> None:
    settings = BotSettings.from_environment()
    bot = Bot(settings.telegram_token)
    api = BotApi(
        settings.api_url,
        settings.api_key,
        settings.api_timeout_seconds,
        settings.api_limits,
    )
    dispatcher = Dispatcher(disable_fsm=True)
    dispatcher.include_router(register(api, settings.checkout_limits))
    admission = WebhookAdmission(
        settings.webhook_max_inflight,
        settings.webhook_max_request_bytes,
        settings.webhook_processing_timeout_seconds,
    )
    application = web.Application(
        client_max_size=settings.webhook_max_request_bytes,
        middlewares=[admission.middleware],
    )
    register_delivery(application, bot, api, settings)
    handler = ForegroundRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        secret_token=settings.webhook_secret,
        handle_in_background=False,
    )
    handler.register(application, path="/telegram/webhook")
    setup_application(application, dispatcher, bot=bot)

    async def startup(_: web.Application) -> None:
        if settings.webhook_public_url:
            await bot.set_webhook(
                settings.webhook_public_url,
                secret_token=settings.webhook_secret,
            )

    async def shutdown(_: web.Application) -> None:
        await api.close()
        await bot.session.close()

    application.on_startup.append(startup)
    application.on_cleanup.append(shutdown)
    web.run_app(
        application, host=settings.listen_host, port=settings.listen_port
    )


if __name__ == "__main__":
    main()
