"""Generative AI agents hosted on Ada (``https://<handle>.ada.support/chat/``).

Used by Malaysia Airlines ("Mavis", handle ``malaysiaairlines``) and Philippine
Airlines ("myPAL AI Agent", handle ``philippineairlines``). The airlines embed
the same widget on their sites; the standalone chat page skips their homepages.

Flow observed on the live pages:

* The chat runs in an iframe whose URL contains ``/app/index.html``; it has a
  single ``textarea`` (Enter sends).
* The agent greets first (one or more bubbles). Every agent bubble renders its
  text in ``.ada-markdown`` inside the ``[role=log]`` message list; user
  bubbles and quick-reply buttons do not use that class.
* Answers can arrive as several bubbles; there is no reliable completion
  marker, so a reply is complete once nothing changed for ``QUIET`` seconds.
"""

import time

from .base import BotError, ChatBot, fresh_page, wait_until_stable

APP_FRAME = "/app/index.html"
AGENT_TEXT = "[role=log] .ada-markdown"
# Bubbles of one reply arrive within a few seconds of each other.
QUIET = 5.0


class AdaBot(ChatBot):
    def __init__(self, name, handle, timeout=90.0, headless=True, page_factory=fresh_page, step_timeout=30.0):
        self.name = name
        self.chat_url = f"https://{handle}.ada.support/chat/"
        self.timeout = timeout
        self.headless = headless
        self.page_factory = page_factory
        self.step_timeout = step_timeout

    def _open(self, page):
        page.set_default_timeout(self.step_timeout * 1000)
        try:
            page.goto(self.chat_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            raise BotError(f"Cannot open {self.name} chat page: {str(exc).splitlines()[0]}") from exc
        frame = self._chat_frame(page)
        bubbles = frame.locator(AGENT_TEXT)
        # Let the greeting finish so it is not mistaken for the answer.
        wait_until_stable(lambda: bubbles.count(), timeout=self.step_timeout, quiet=QUIET)
        return frame

    def _send(self, page, frame, message):
        bubbles = frame.locator(AGENT_TEXT)
        before = bubbles.count()
        frame.locator("textarea").fill(message)
        frame.locator("textarea").press("Enter")
        started = time.monotonic()

        def answer():
            texts = [b.inner_text().strip() for b in bubbles.all()[before:]]
            return "\n".join(t for t in texts if t)

        text = wait_until_stable(answer, timeout=self.timeout, quiet=QUIET)
        return text, int((time.monotonic() - started) * 1000)

    def _chat_frame(self, page):
        deadline = time.monotonic() + self.step_timeout
        while time.monotonic() < deadline:
            frame = next((f for f in page.frames if APP_FRAME in f.url), None)
            if frame is not None and frame.locator("textarea").count():
                frame.locator(AGENT_TEXT).first.wait_for(timeout=self.step_timeout * 1000)
                return frame
            page.wait_for_timeout(500)
        raise BotError(f"Could not find the {self.name} chat input; the Ada page may have changed.")
