"""OpenAI-compatible HTTP API backed by the EVA Air web chatbot.

Endpoints (enough for the OpenAI Python SDK used by llm-bias-pipeline):

* ``GET  /health``
* ``GET  /v1/models``            → one model, ``evaair``
* ``POST /v1/chat/completions``  → the last user message is asked in a fresh
  chatbot session; sampling parameters are ignored (the bot has none).
* ``POST /v1/conversation``      → a question plus canned replies to the bot's
  follow-up questions, all in one fresh chatbot session.

Upstream requests (a whole conversation counts as one) are serialized and spaced at least ``EVAAIR_MIN_INTERVAL``
seconds apart, however many callers there are.
"""

import os
import re
import threading
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .client import DEFAULT_CHAT_URL, BotError, EvaAirBot

MODEL_ID = "evaair"


class ChatMessage(BaseModel):
    role: str
    content: str | list | None = None


class ChatCompletionRequest(BaseModel):
    model: str = MODEL_ID
    messages: list[ChatMessage]

    model_config = {"extra": "allow"}


class ConversationRequest(BaseModel):
    question: str
    follow_up_reply: str
    max_turns: int = Field(5, ge=1, le=10)
    follow_up_patterns: list[str] = []


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


def _conversation_patterns(request):
    """Validate a conversation request; returns (compiled patterns, error response)."""
    if not request.question.strip():
        return None, _error(400, "question must not be empty.", "invalid_request_error")
    if not request.follow_up_reply.strip():
        return None, _error(400, "follow_up_reply must not be empty.", "invalid_request_error")
    try:
        return [re.compile(p, re.IGNORECASE) for p in request.follow_up_patterns], None
    except re.error as exc:
        return None, _error(400, f"Invalid follow_up_patterns regex: {exc}", "invalid_request_error")


async def _validation_error(request: Request, exc: RequestValidationError):
    # Bad conversation input is a 400 like other input errors; other routes keep FastAPI's 422.
    if request.url.path.endswith("/conversation"):
        message = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        return _error(400, message, "invalid_request_error")
    return await request_validation_exception_handler(request, exc)


def create_app(bot=None, limiter=None):
    bot = bot or EvaAirBot(
        chat_url=os.environ.get("EVAAIR_CHAT_URL", DEFAULT_CHAT_URL),
        timeout=float(os.environ.get("EVAAIR_TIMEOUT_SECONDS", "60")),
    )
    limiter = limiter or RateLimiter(float(os.environ.get("EVAAIR_MIN_INTERVAL", "3")))
    app = FastAPI(title="EVA Air bot (OpenAI-compatible)")
    app.add_exception_handler(RequestValidationError, _validation_error)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/models")
    def models():
        return {
            "object": "list",
            "data": [{"id": MODEL_ID, "object": "model", "created": 0, "owned_by": "evaair"}],
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
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "latency_ms": latency_ms,
        }

    @app.post("/v1/conversation")
    def conversation(request: ConversationRequest):
        patterns, error = _conversation_patterns(request)
        if error:
            return error
        try:
            # The whole conversation is one rate-limited call.
            return limiter.run(
                bot.converse, request.question.strip(), request.follow_up_reply.strip(), request.max_turns, patterns
            )
        except BotError as exc:
            return _error(502, str(exc), "upstream_error")

    return app


app = create_app()
