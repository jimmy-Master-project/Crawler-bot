"""OpenAI-compatible HTTP API in front of browser-driven chatbots.

Each bot lives under its own prefix so it looks like a separate endpoint to
the OpenAI SDK (base URL ``http://127.0.0.1:8769/<bot>/v1``):

* ``GET  /health``
* ``GET  /<bot>/v1/models``            → one model, named after the bot
* ``POST /<bot>/v1/chat/completions``  → the last user message is asked in a
  fresh browser; sampling parameters are ignored (chatbots have none).
* ``POST /<bot>/v1/conversation``      → a question plus canned replies to the
  bot's follow-up questions, all in one fresh browser.

Questions (and whole conversations) to the same bot are serialized and spaced
at least ``BROWSER_BOTS_MIN_INTERVAL`` seconds apart.
"""

import os
import re
import threading
import time
import uuid

from fastapi import APIRouter, FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .base import BotError


class ChatMessage(BaseModel):
    role: str
    content: str | list | None = None


class ChatCompletionRequest(BaseModel):
    model: str = ""
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
    return JSONResponse(status_code=status, content={"error": {"message": message, "type": code, "code": code}})


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


def bot_router(name, bot, limiter):
    router = APIRouter(prefix=f"/{name}/v1")

    @router.get("/models")
    def models():
        return {"object": "list", "data": [{"id": name, "object": "model", "created": 0, "owned_by": name}]}

    @router.post("/chat/completions")
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
            "model": name,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "latency_ms": latency_ms,
        }

    @router.post("/conversation")
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

    return router


def default_bots():
    from .ada import AdaBot
    from .chinaairlines import ChinaAirlinesBot
    from .finnair import FinnairBot
    from .vietjet import VietjetBot
    from .virgin import VirginAtlanticBot

    headless = os.environ.get("BROWSER_BOTS_HEADLESS", "1") != "0"
    timeout = float(os.environ.get("BROWSER_BOTS_TIMEOUT_SECONDS", "90"))
    finnair = FinnairBot(
        timeout=timeout,
        headless=headless,
        first_name=os.environ.get("FINNAIR_FIRST_NAME", "Research"),
        last_name=os.environ.get("FINNAIR_LAST_NAME", "Tester"),
        email=os.environ.get("FINNAIR_EMAIL", "research@example.com"),
    )
    return {
        "virgin": VirginAtlanticBot(timeout=timeout, headless=headless),
        "finnair": finnair,
        "chinaairlines": ChinaAirlinesBot(timeout=timeout, headless=headless),
        "malaysia": AdaBot("malaysia", "malaysiaairlines", timeout=timeout, headless=headless),
        "philippine": AdaBot("philippine", "philippineairlines", timeout=timeout, headless=headless),
        "vietjet": VietjetBot(timeout=timeout, headless=headless),
    }


def create_app(bots=None, min_interval=None):
    bots = default_bots() if bots is None else bots
    interval = float(os.environ.get("BROWSER_BOTS_MIN_INTERVAL", "3")) if min_interval is None else min_interval
    app = FastAPI(title="Browser chatbots (OpenAI-compatible)")
    app.add_exception_handler(RequestValidationError, _validation_error)

    @app.get("/health")
    def health():
        return {"status": "ok", "bots": sorted(bots)}

    for name, bot in bots.items():
        app.include_router(bot_router(name, bot, RateLimiter(interval)))
    return app


app = create_app()
