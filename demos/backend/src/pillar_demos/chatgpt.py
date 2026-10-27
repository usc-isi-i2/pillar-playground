"""Server-side connection to the OpenAI Responses API.

Configured by environment variables; the key never reaches the page:

- ``OPENAI_API_KEY``: required to connect.
- ``OPENAI_MODEL``: required to connect, e.g. the model your account uses for ChatGPT-style replies.
- ``OPENAI_BASE_URL``: optional, defaults to ``https://api.openai.com/v1``.

Without both variables the pages fall back to the copy-and-paste ChatGPT hand-off.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

TIMEOUT_S = 90


class ChatGPTError(Exception):
    def __init__(self, message: str, code: str = "api_error", status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status


def configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_MODEL"))


def _output_text(data: dict[str, Any]) -> str:
    """Concatenate the ``output_text`` parts of a Responses API result."""
    parts = []
    for item in data.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") == "output_text":
                parts.append(content.get("text", ""))
    return "".join(parts)


async def respond(
    prompt: str, json_mode: bool = False, transport: httpx.AsyncBaseTransport | None = None
) -> str:
    """Send one prompt and return the reply text. ``json_mode`` asks for a JSON object."""
    if not configured():
        raise ChatGPTError("The ChatGPT API is not configured on the server.", "not_configured", 503)
    body: dict[str, Any] = {"model": os.environ["OPENAI_MODEL"], "input": prompt}
    if json_mode:
        body["text"] = {"format": {"type": "json_object"}}
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport) as client:
            r = await client.post(f"{base}/responses", json=body, headers=headers)
    except httpx.HTTPError as e:
        raise ChatGPTError(f"Could not reach the OpenAI API: {e}", "network_error") from e
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400:
        err = data.get("error") or {}
        raise ChatGPTError(
            err.get("message") or f"OpenAI request failed ({r.status_code})", err.get("code") or "api_error"
        )
    text = _output_text(data)
    if not text:
        raise ChatGPTError("OpenAI returned no text.", "empty_response")
    return text
