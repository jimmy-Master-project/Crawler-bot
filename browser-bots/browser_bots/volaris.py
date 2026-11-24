"""Volaris "Ari" (Salesforce Agentforce, opened from "Ask me anything" on https://www.volaris.com/).

Flow observed on the live site:

* Clicking "Ask me anything" (``.iva-link``) loads a Salesforce Embedded Messaging iframe from
  ``volarismktg.my.site.com`` whose ``textarea`` sends on Enter.
* Ari greets first. Messages are ``runtime_copilot`` blocks: agent bubbles are
  ``.message-block_inbound`` and their text is in ``.markdown-wrapper``; our own
  bubbles are ``.message-block_outbound``.
* Answers stream in and may span several bubbles; there is no completion
  marker, so a reply is complete once nothing changed for ``QUIET`` seconds.
* Ari sometimes answers English questions in Spanish (the site's default
  language); the reply is returned as is.
"""

import time

from .base import BotError, fresh_page, wait_until_stable

CHAT_URL = "https://www.volaris.com/"
CHAT_FRAME = "my.site.com"
LAUNCHER = ".iva-link, .iva-text"
AGENT_TEXT = ".message-block_inbound .markdown-wrapper"
QUIET = 5.0
# Time for the site to wire up the launcher after it renders.
SETTLE_MS = 8_000


class VolarisBot:
    name = "volaris"

    def __init__(self, chat_url=CHAT_URL, timeout=90.0, headless=True, page_factory=fresh_page, step_timeout=30.0):
        self.chat_url = chat_url
        self.timeout = timeout
        self.headless = headless
        self.page_factory = page_factory
        self.step_timeout = step_timeout

    def ask(self, question):
        with self.page_factory(headless=self.headless) as page:
            page.set_default_timeout(self.step_timeout * 1000)
            try:
                page.goto(self.chat_url, wait_until="domcontentloaded", timeout=60_000)
            except Exception as exc:
                raise BotError(f"Cannot open Volaris page: {str(exc).splitlines()[0]}") from exc
            frame = self._open_chat(page)
            bubbles = frame.locator(AGENT_TEXT)
            # Let the greeting finish so it is not mistaken for the answer.
            wait_until_stable(lambda: bubbles.count(), timeout=self.step_timeout, quiet=QUIET)
            before = bubbles.count()
            frame.locator("textarea").fill(question)
            frame.locator("textarea").press("Enter")
            started = time.monotonic()

            def answer():
                texts = [b.inner_text().strip() for b in bubbles.all()[before:]]
                return "\n".join(t for t in texts if t)

            text = wait_until_stable(answer, timeout=self.timeout, quiet=QUIET)
            return text, int((time.monotonic() - started) * 1000)

    def _open_chat(self, page):
        # By class: the label is "Ask me anything" or its Spanish version depending on the page language.
        launcher = page.locator(LAUNCHER).first
        try:
            launcher.wait_for()
        except Exception as exc:
            raise BotError(
                f"Could not open Ari; the Volaris page may have changed: {str(exc).splitlines()[0]}"
            ) from exc
        # The launcher renders before the site wires it up, so an early click does
        # nothing; a second click while the chat loads closes it again. Let the page
        # settle, click once, and only retry if no chat frame appears.
        page.wait_for_timeout(SETTLE_MS)
        for _ in range(2):
            launcher.click()
            deadline = time.monotonic() + self.step_timeout
            while time.monotonic() < deadline:
                frame = next((f for f in page.frames if CHAT_FRAME in f.url and f.locator("textarea").count()), None)
                if frame is not None:
                    return frame
                page.wait_for_timeout(500)
        raise BotError("Could not find the Ari chat input; the Volaris page may have changed.")
