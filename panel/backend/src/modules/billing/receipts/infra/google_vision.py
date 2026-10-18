import asyncio
import base64
import json
from collections.abc import Mapping
from typing import Any

import aiohttp

from src.config.settings import ReceiptSettings
from src.modules.billing.receipts.app.ocr_interfaces import (
    ReceiptOcrRetryableError,
)
from src.modules.billing.receipts.domain.extraction import (
    ReceiptOcrLine,
    ReceiptOcrResult,
)

_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_LINE_BREAKS = {"LINE_BREAK", "EOL_SURE_SPACE"}
_SPACE_BREAKS = {"SPACE", "SURE_SPACE"}


class GoogleVisionResponseError(RuntimeError):
    """Google Vision returned an unusable response."""


class GoogleVisionReceiptOcr:
    def __init__(self, settings: ReceiptSettings) -> None:
        self.settings = settings

    async def recognize(self, content: bytes) -> ReceiptOcrResult:
        api_key = self.settings.ocr_api_key
        if api_key is None:
            raise ReceiptOcrRetryableError("Google Vision is not configured")
        body = await asyncio.to_thread(_request_body, content)
        timeout = aiohttp.ClientTimeout(
            total=self.settings.ocr_timeout_seconds
        )
        headers = {"X-Goog-Api-Key": api_key.get_secret_value()}
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    _ENDPOINT,
                    data=body,
                    headers={**headers, "Content-Type": "application/json"},
                ) as response:
                    if response.status == 401:
                        return ReceiptOcrResult(
                            failure_code="provider_rejected"
                        )
                    if response.status == 403:
                        return ReceiptOcrResult(
                            failure_code="provider_rejected"
                        )
                    if response.status == 429 or response.status >= 500:
                        raise ReceiptOcrRetryableError(
                            "Google Vision is temporarily unavailable"
                        )
                    if response.status >= 400:
                        return ReceiptOcrResult(
                            failure_code="provider_rejected"
                        )
                    response_body = await response.content.read(
                        _MAX_RESPONSE_BYTES + 1
                    )
                    if len(response_body) > _MAX_RESPONSE_BYTES:
                        return ReceiptOcrResult(
                            failure_code="provider_response_too_large"
                        )
                    try:
                        result = json.loads(response_body)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        return ReceiptOcrResult(
                            failure_code="invalid_provider_response"
                        )
        except (aiohttp.ClientError, TimeoutError) as error:
            raise ReceiptOcrRetryableError(
                "Google Vision request failed"
            ) from error
        try:
            lines = parse_google_vision_response(result)
        except GoogleVisionResponseError:
            return ReceiptOcrResult(failure_code="invalid_provider_response")
        return ReceiptOcrResult(lines=lines)


def parse_google_vision_response(
    payload: object,
) -> tuple[ReceiptOcrLine, ...]:
    response = _first_response(payload)
    error = response.get("error")
    if isinstance(error, Mapping):
        code = error.get("code")
        if code in {429, 500, 503, 504}:
            raise ReceiptOcrRetryableError(
                "Google Vision is temporarily unavailable"
            )
        raise GoogleVisionResponseError("Google Vision rejected the image")
    annotation = response.get("fullTextAnnotation")
    if not isinstance(annotation, Mapping):
        raise GoogleVisionResponseError("Google Vision returned no text")
    pages = annotation.get("pages")
    if not isinstance(pages, list):
        raise GoogleVisionResponseError("Google Vision returned no pages")
    lines: list[ReceiptOcrLine] = []
    text: list[str] = []
    confidences: list[int] = []
    points: list[tuple[int, int]] = []
    for page in pages:
        for block in _children(page, "blocks"):
            for paragraph in _children(block, "paragraphs"):
                for word in _children(paragraph, "words"):
                    word_text, confidence, region, break_type = _word(word)
                    text.append(word_text)
                    confidences.append(confidence)
                    points.extend(region)
                    if break_type in _LINE_BREAKS:
                        _append_line(lines, text, confidences, points)
                    elif break_type in _SPACE_BREAKS:
                        text.append(" ")
                _append_line(lines, text, confidences, points)
    _append_line(lines, text, confidences, points)
    if not lines:
        raise GoogleVisionResponseError("Google Vision returned no words")
    return tuple(lines)


def _first_response(payload: object) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise GoogleVisionResponseError("Google Vision returned invalid JSON")
    responses = payload.get("responses")
    if not isinstance(responses, list) or not responses:
        raise GoogleVisionResponseError("Google Vision returned no response")
    response = responses[0]
    if not isinstance(response, Mapping):
        raise GoogleVisionResponseError("Google Vision returned invalid text")
    return response


def _children(value: object, key: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        raise GoogleVisionResponseError("Google Vision returned invalid text")
    children = value.get(key, [])
    if not isinstance(children, list):
        raise GoogleVisionResponseError("Google Vision returned invalid text")
    result = []
    for child in children:
        if not isinstance(child, Mapping):
            raise GoogleVisionResponseError(
                "Google Vision returned invalid text"
            )
        result.append(child)
    return result


def _word(
    value: Mapping[str, Any],
) -> tuple[str, int, tuple[tuple[int, int], ...], str | None]:
    symbols = _children(value, "symbols")
    if not symbols:
        raise GoogleVisionResponseError("Google Vision returned an empty word")
    characters = []
    break_type = None
    for symbol in symbols:
        character = symbol.get("text")
        if not isinstance(character, str) or not character:
            raise GoogleVisionResponseError(
                "Google Vision returned invalid text"
            )
        characters.append(character)
    properties = symbols[-1].get("property")
    if isinstance(properties, Mapping):
        detected_break = properties.get("detectedBreak")
        if isinstance(detected_break, Mapping):
            break_type = detected_break.get("type")
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise GoogleVisionResponseError(
            "Google Vision returned invalid confidence"
        )
    return (
        "".join(characters),
        round(confidence * 1000),
        _vertices(value),
        break_type if isinstance(break_type, str) else None,
    )


def _vertices(value: Mapping[str, Any]) -> tuple[tuple[int, int], ...]:
    bounding_box = value.get("boundingBox")
    if not isinstance(bounding_box, Mapping):
        return ()
    vertices = bounding_box.get("vertices", [])
    if not isinstance(vertices, list):
        return ()
    points = []
    for vertex in vertices:
        if not isinstance(vertex, Mapping):
            continue
        x, y = vertex.get("x", 0), vertex.get("y", 0)
        if isinstance(x, int) and isinstance(y, int):
            points.append((x, y))
    return tuple(points)


def _append_line(
    lines: list[ReceiptOcrLine],
    text: list[str],
    confidences: list[int],
    points: list[tuple[int, int]],
) -> None:
    value = "".join(text).strip()
    if value:
        lines.append(
            ReceiptOcrLine(
                text=value,
                confidence_milli=min(confidences),
                region=tuple(points),
            )
        )
    text.clear()
    confidences.clear()
    points.clear()


def _base64(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


def _request_body(content: bytes) -> str:
    payload = {
        "requests": [
            {
                "image": {"content": _base64(content)},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            }
        ]
    }
    return json.dumps(payload, separators=(",", ":"))
