"""Shared pieces for browser-driven chatbots."""

import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

# Keep downloaded browsers inside this project (see `playwright install`).
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(__file__).resolve().parent.parent / ".browsers"))

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


class BotError(Exception):
    """The bot could not produce an answer (navigation, UI change, timeout)."""


def run_conversation(send, question, follow_up_reply, max_turns, patterns):
    """Ask ``question`` with ``send(message) -> (text, latency_ms)`` and answer follow-ups.

    While an answer matches one of ``patterns`` (case-insensitive ``re.search``)
    and fewer than ``max_turns`` turns were taken, ``follow_up_reply`` is sent.
    """
    compiled = [re.compile(p, re.IGNORECASE) if isinstance(p, str) else p for p in patterns]
    turns, message = [], question
    while True:
        text, latency_ms = send(message)
        follow_up = any(p.search(text) for p in compiled)
        turns.append({"user": message, "assistant": text, "latency_ms": latency_ms, "follow_up": follow_up})
        if not follow_up:
            ended = "answered"
            break
        if len(turns) >= max_turns:
            ended = "max_turns"
            break
        message = follow_up_reply
    return {"turns": turns, "ended": ended, "latency_ms": sum(t["latency_ms"] for t in turns)}


class ChatBot:
    """A browser chatbot: ``_open(page) -> state`` starts a chat, ``_send`` speaks one turn.

    Subclasses set ``page_factory`` and ``headless`` and implement
    ``_open(page)`` and ``_send(page, state, message) -> (text, latency_ms)``.
    """

    def _close(self, page, state):
        """Release anything ``_open`` set up besides the page itself."""

    def _session(self, run):
        with self.page_factory(headless=self.headless) as page:
            state = self._open(page)
            try:
                return run(lambda message: self._send(page, state, message))
            finally:
                self._close(page, state)

    def ask(self, question):
        """Ask one question in a brand-new browser; returns (answer, latency_ms)."""
        return self._session(lambda send: send(question))

    def converse(self, question, follow_up_reply, max_turns, patterns):
        """One conversation in a brand-new browser; see ``run_conversation``."""
        return self._session(lambda send: run_conversation(send, question, follow_up_reply, max_turns, patterns))


@contextmanager
def fresh_page(locale="en-US", headless=True):
    """A brand-new browser for one question, so no session state carries over.

    Playwright's sync API is bound to the thread that started it; opening and
    closing it per question keeps the service safe under FastAPI's thread pool.
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            context = browser.new_context(locale=locale, viewport={"width": 1280, "height": 900})
            yield context.new_page()
        except PlaywrightError as exc:
            raise BotError(f"Browser error: {str(exc).splitlines()[0]}") from exc
        finally:
            browser.close()


def wait_until_stable(
    read, timeout, interval=0.5, settle=2.0, done=lambda: False, quiet=None, clock=time.monotonic, sleep=time.sleep
):
    """Poll ``read()`` until ``done()`` and the value stopped changing for ``settle`` seconds.

    With ``quiet``, a value unchanged for that long counts as complete even if ``done()``
    never turns true (for pages whose completion marker sometimes fails to appear).
    """
    deadline = clock() + timeout
    last, last_change = None, clock()
    while clock() < deadline:
        value = read()
        if value != last:
            last, last_change = value, clock()
        elif value and (
            (done() and clock() - last_change >= settle) or (quiet is not None and clock() - last_change >= quiet)
        ):
            return value
        sleep(interval)
    raise BotError(f"No complete answer within {timeout:.0f}s.")
