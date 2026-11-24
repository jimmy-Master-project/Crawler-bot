"""China Airlines "AI 客服" (https://calaics01.china-airlines.com/cichatbot/chatindexFrame.aspx).

Flow observed on the live page:

* The chat is Microsoft Bot Framework WebChat in a same-origin iframe
  (``chatindex.aspx``). The input is ``input.wc-shellinput`` (Enter sends).
* The bot greets first with three messages: a welcome, a usage notice (which
  states that some replies are produced by generative AI) and news.
* Bot replies are ``.wc-message-from-bot`` bubbles whose text is in
  ``.format-markdown``; suggested follow-up questions are separate buttons and
  not part of it. A finished reply gets a "這則回覆是否對您有幫助 ?" feedback
  block (``.wc-message-feedback``).
"""

import re
import time

from .base import BotError, ChatBot, fresh_page, wait_until_stable

CHAT_URL = "https://calaics01.china-airlines.com/cichatbot/chatindexFrame.aspx"
CHAT_FRAME = "chatindex.aspx"
BOT_MESSAGE = ".wc-message.wc-message-from-bot"
BOT_TEXT = f"{BOT_MESSAGE} .format-markdown"
INPUT = "input.wc-shellinput"
# The feedback block occasionally does not render; this much silence also means done.
QUIET = 8.0
GREETING_QUIET = 6.0


class ChinaAirlinesBot(ChatBot):
    name = "chinaairlines"

    def __init__(self, chat_url=CHAT_URL, timeout=90.0, headless=True, page_factory=fresh_page, step_timeout=30.0):
        self.chat_url = chat_url
        self.timeout = timeout
        self.headless = headless
        self.page_factory = page_factory
        self.step_timeout = step_timeout

    def _open(self, page):
        page.set_default_timeout(self.step_timeout * 1000)
        try:
            page.goto(self.chat_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            raise BotError(f"Cannot open China Airlines chat page: {str(exc).splitlines()[0]}") from exc
        frame = self._chat_frame(page)
        texts = frame.locator(BOT_TEXT)
        # The greeting is three messages (welcome, usage notice, news) 2–3s apart;
        # let it finish so it is not mistaken for the answer.
        wait_until_stable(lambda: texts.count(), timeout=self.step_timeout, quiet=GREETING_QUIET)
        return frame

    def _send(self, page, frame, message):
        texts = frame.locator(BOT_TEXT)
        before = texts.count()
        frame.locator(INPUT).fill(message)
        frame.locator(INPUT).press("Enter")
        started = time.monotonic()

        def answer():
            parts = [t.inner_text().strip() for t in texts.all()[before:]]
            # The markdown renderer leaves runs of empty lines between blocks.
            return re.sub(r"\n\s*\n+", "\n", "\n".join(p for p in parts if p))

        def finished():
            return frame.locator(BOT_MESSAGE).last.locator(".wc-message-feedback").count() > 0

        text = wait_until_stable(answer, timeout=self.timeout, done=finished, quiet=QUIET)
        return text, int((time.monotonic() - started) * 1000)

    def _chat_frame(self, page):
        deadline = time.monotonic() + self.step_timeout
        while time.monotonic() < deadline:
            frame = next((f for f in page.frames if CHAT_FRAME in f.url), None)
            if frame is not None and frame.locator(INPUT).count():
                return frame
            page.wait_for_timeout(500)
        raise BotError("Could not find the China Airlines chat input; the page may have changed.")
