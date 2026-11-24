"""OpenAI-compatible HTTP API backed by the Priceline Penny chat API.

Endpoints (enough for the OpenAI Python SDK used by llm-bias-pipeline):

* ``GET  /health``
* ``GET  /v1/models``            → one model, ``priceline``
* ``POST /v1/chat/completions``  → the last user message is asked in a fresh
  Penny session; sampling parameters are ignored (Penny has none).

Requests are serialized and spaced at least ``PRICELINE_MIN_INTERVAL`` seconds
apart, however many callers there are.
"""

import os
import threading
import time
import uuid

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .client import BotError, PricelineBot

MODEL_ID = "priceline"


class ChatMessage(BaseModel):
    role: str
    content: str | list | None = None


class ChatCompletionRequest(BaseModel):
    model: str = MODEL_ID
    messages: list[ChatMessage]

    model_config = {"extra": "allow"}


class RateLimiter:
    """Serialize calls and keep a minimum gap between their starts."""

    def __init__(self, min_interval, clock=time.monotonic, sleep=time.sleep):
        self.min_interval = min_interval
        self.clock = clock
        self.sleep = sleep
        self._lock = threading.Lock()
        self._last = None

    def run(self, fn, *args):
        with self._lock:
            if self._last is not None:
                wait = self.min_interval - (self.clock() - self._last)
                if wait > 0:
                    self.sleep(wait)
            self._last = self.clock()
            return fn(*args)


def _text_of(content):
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def _error(status, message, code):
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": code, "code": code}},
    )


def create_app(bot=None, limiter=None):
    bot = bot or PricelineBot(timeout=float(os.environ.get("PRICELINE_TIMEOUT_SECONDS", "60")))
    limiter = limiter or RateLimiter(float(os.environ.get("PRICELINE_MIN_INTERVAL", "3")))
    app = FastAPI(title="Priceline Penny (OpenAI-compatible)")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/models")
    def models():
        return {
            "object": "list",
            "data": [{"id": MODEL_ID, "object": "model", "created": 0, "owned_by": "priceline"}],
        }

    @app.post("/v1/chat/completions")
    def chat_completions(request: ChatCompletionRequest):
        question = next(
            (_text_of(m.content) for m in reversed(request.messages) if m.role == "user"), ""
        ).strip()
        if not question:
            return _error(400, "No user message to ask.", "invalid_request_error")
        try:
            answer, latency_ms = limiter.run(bot.ask, question)
        except BotError as exc:
            # 502 makes the OpenAI SDK retry it like any upstream failure.
            return _error(502, str(exc), "upstream_error")
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "latency_ms": latency_ms,
        }

    return app


app = create_app()
