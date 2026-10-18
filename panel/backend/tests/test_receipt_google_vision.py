import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from pydantic import SecretStr

from src.config.settings import ReceiptSettings
from src.modules.billing.receipts.app.ocr_interfaces import (
    ReceiptOcrRetryableError,
)
from src.modules.billing.receipts.domain.extraction import (
    ReceiptOcrLine,
    ReceiptOcrResult,
)
from src.modules.billing.receipts.infra import google_vision
from src.modules.billing.receipts.infra.google_vision import (
    GoogleVisionReceiptOcr,
    GoogleVisionResponseError,
    parse_google_vision_response,
)

pytestmark = [pytest.mark.billing, pytest.mark.unit]


def word(text: str, confidence: float, break_type: str) -> dict:
    return {
        "confidence": confidence,
        "boundingBox": {
            "vertices": [
                {"x": 1, "y": 2},
                {"x": 10, "y": 2},
                {"x": 10, "y": 8},
                {"x": 1, "y": 8},
            ]
        },
        "symbols": [
            {
                "text": character,
                "property": {"detectedBreak": {"type": break_type}}
                if index == len(text) - 1
                else {},
            }
            for index, character in enumerate(text)
        ],
    }


def test_google_vision_words_become_confident_text_lines():
    payload = {
        "responses": [
            {
                "fullTextAnnotation": {
                    "pages": [
                        {
                            "blocks": [
                                {
                                    "paragraphs": [
                                        {
                                            "words": [
                                                word("واریز", 0.99, "SPACE"),
                                                word(
                                                    "وجه",
                                                    0.97,
                                                    "LINE_BREAK",
                                                ),
                                                word("۱۰۰۰۰۰", 0.96, "SPACE"),
                                                word(
                                                    "ریال",
                                                    0.98,
                                                    "LINE_BREAK",
                                                ),
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            }
        ]
    }

    result = parse_google_vision_response(payload)

    assert result == (
        ReceiptOcrLine(
            text="واریز وجه",
            confidence_milli=970,
            region=((1, 2), (10, 2), (10, 8), (1, 8)) * 2,
        ),
        ReceiptOcrLine(
            text="۱۰۰۰۰۰ ریال",
            confidence_milli=960,
            region=((1, 2), (10, 2), (10, 8), (1, 8)) * 2,
        ),
    )


def test_google_vision_api_error_is_not_treated_as_empty_ocr():
    with pytest.raises(GoogleVisionResponseError):
        parse_google_vision_response(
            {"responses": [{"error": {"message": "service unavailable"}}]}
        )


def test_google_vision_missing_word_confidence_is_rejected():
    with pytest.raises(GoogleVisionResponseError):
        parse_google_vision_response(
            {
                "responses": [
                    {
                        "fullTextAnnotation": {
                            "pages": [
                                {
                                    "blocks": [
                                        {
                                            "paragraphs": [
                                                {
                                                    "words": [
                                                        {
                                                            "symbols": [
                                                                {"text": "x"}
                                                            ]
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
        )


def test_google_vision_uses_async_http_and_keeps_key_out_of_url(monkeypatch):
    calls = []

    async def annotate(request: web.Request) -> web.Response:
        await asyncio.sleep(0.05)
        calls.append(
            (
                request.path_qs,
                request.headers.get("X-Goog-Api-Key"),
                await request.json(),
            )
        )
        return web.json_response(
            {
                "responses": [
                    {
                        "fullTextAnnotation": {
                            "pages": [
                                {
                                    "blocks": [
                                        {
                                            "paragraphs": [
                                                {
                                                    "words": [
                                                        word(
                                                            "رسید",
                                                            0.98,
                                                            "LINE_BREAK",
                                                        )
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
        )

    app = web.Application(client_max_size=10 * 1024 * 1024)
    app.router.add_post("/v1/images:annotate", annotate)

    async def run_request() -> tuple[ReceiptOcrResult, int]:
        async with TestServer(app) as server:
            monkeypatch.setattr(
                google_vision,
                "_ENDPOINT",
                str(server.make_url("/v1/images:annotate")),
            )
            settings = ReceiptSettings(
                enabled=True,
                max_image_bytes=1024,
                max_request_bytes=2048,
                max_per_topup=3,
                max_pixels=10000,
                allowed_formats=["JPEG"],
                jpeg_quality=80,
                max_concurrent_images=1,
                ocr_api_key=SecretStr("sensitive-key"),
                ocr_timeout_seconds=5,
            )
            ocr = GoogleVisionReceiptOcr(settings)
            request = asyncio.create_task(
                ocr.recognize(b"x" * (5 * 1024 * 1024))
            )
            ticks = 0
            while not request.done():
                ticks += 1
                await asyncio.sleep(0.005)
            return request.result(), ticks

    lines, ticks = asyncio.run(run_request())

    assert lines.lines[0].text == "رسید"
    assert calls[0][0] == "/v1/images:annotate"
    assert calls[0][1] == "sensitive-key"
    assert calls[0][2]["requests"][0]["features"] == [
        {"type": "DOCUMENT_TEXT_DETECTION"}
    ]
    assert calls[0][2]["requests"][0]["image"]["content"]
    assert ticks >= 5


def test_google_vision_rate_limit_is_marked_for_delayed_retry(monkeypatch):
    async def rate_limited(request: web.Request) -> web.Response:
        return web.json_response({"error": "limited"}, status=429)

    app = web.Application()
    app.router.add_post("/v1/images:annotate", rate_limited)

    async def run_request() -> None:
        async with TestServer(app) as server:
            monkeypatch.setattr(
                google_vision,
                "_ENDPOINT",
                str(server.make_url("/v1/images:annotate")),
            )
            settings = ReceiptSettings(
                enabled=True,
                max_image_bytes=1024,
                max_request_bytes=2048,
                max_per_topup=3,
                max_pixels=10000,
                allowed_formats=["JPEG"],
                jpeg_quality=80,
                max_concurrent_images=1,
                ocr_api_key=SecretStr("sensitive-key"),
                ocr_timeout_seconds=5,
            )
            await GoogleVisionReceiptOcr(settings).recognize(b"image")

    with pytest.raises(ReceiptOcrRetryableError):
        asyncio.run(run_request())


def test_google_vision_rejects_oversized_provider_response(monkeypatch):
    async def oversized(request: web.Request) -> web.Response:
        return web.Response(body=b"x" * 17, content_type="application/json")

    app = web.Application()
    app.router.add_post("/v1/images:annotate", oversized)

    async def run_request() -> ReceiptOcrResult:
        async with TestServer(app) as server:
            monkeypatch.setattr(
                google_vision,
                "_ENDPOINT",
                str(server.make_url("/v1/images:annotate")),
            )
            monkeypatch.setattr(google_vision, "_MAX_RESPONSE_BYTES", 16)
            settings = ReceiptSettings(
                enabled=True,
                max_image_bytes=1024,
                max_request_bytes=2048,
                max_per_topup=3,
                max_pixels=10000,
                allowed_formats=["JPEG"],
                jpeg_quality=80,
                max_concurrent_images=1,
                ocr_api_key=SecretStr("sensitive-key"),
                ocr_timeout_seconds=5,
            )
            return await GoogleVisionReceiptOcr(settings).recognize(b"image")

    result = asyncio.run(run_request())

    assert result.failure_code == "provider_response_too_large"
