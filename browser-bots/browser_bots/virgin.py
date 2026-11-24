"""Virgin Atlantic "Concierge AI" (https://www.virginatlantic.com/concierge-ai/chat).

Flow observed on the live site (Beta v3.2):

1. Onboarding screens with a "Next" button.
2. A notice with ``[data-testid=accept-terms-checkbox]`` ("I understand and
   accept the conditions of carriage and privacy policy") and "Start a chat".
   The project owner accepted these terms and asked for them to be ticked.
3. Chat: ``textarea`` + ``[data-testid=send-button]``. Answers stream into
   ``[data-role=assistant]``; ``[data-testid=message-actions-container]``
   (like / dislike) appears once an answer is complete. Suggested follow-up
   links (``<a>``) under the answer are not part of it.
"""

import time

from .base import BotError, ChatBot, fresh_page, wait_until_stable

CHAT_URL = "https://www.virginatlantic.com/concierge-ai/chat"
ASSISTANT = '[data-role="assistant"]'
# Streaming pauses last about 2s; this much silence means the message is complete.
QUIET = 8.0

# innerText of the answer without suggestion links, icons, loaders or actions.
_ANSWER_TEXT_JS = """el => {
  const copy = el.cloneNode(true);
  copy.querySelectorAll('a, svg, button, [data-testid=message-actions-container]').forEach(n => n.remove());
  document.body.appendChild(copy);
  const text = copy.innerText;
  copy.remove();
  return text.trim();
}"""


class VirginAtlanticBot(ChatBot):
    name = "virgin"

    def __init__(self, chat_url=CHAT_URL, timeout=90.0, headless=True, page_factory=fresh_page):
        self.chat_url = chat_url
        self.timeout = timeout
        self.headless = headless
        self.page_factory = page_factory

    def _open(self, page):
        page.set_default_timeout(30_000)
        try:
            page.goto(self.chat_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            raise BotError(f"Cannot open chat page: {str(exc).splitlines()[0]}") from exc
        self._reach_chat(page)
        self._wait_for_greeting(page)

    def _send(self, page, state, message):
        before = page.locator(ASSISTANT).count()
        page.locator("textarea").fill(message)
        page.locator("[data-testid=send-button]").click()
        started = time.monotonic()
        page.wait_for_timeout(1000)
        if page.locator("textarea").input_value().strip():
            raise BotError("Question was not sent; the Concierge AI page may have changed.")

        def answer():
            messages = page.locator(ASSISTANT)
            if messages.count() <= before:
                return ""
            return messages.last.evaluate(_ANSWER_TEXT_JS)

        def finished():
            # Like / dislike actions appear inside the message once it is complete.
            last = page.locator(ASSISTANT).last
            return last.locator("[data-testid=message-actions-container]").count() > 0

        # The actions occasionally never appear; a long pause then also means done.
        text = wait_until_stable(answer, timeout=self.timeout, done=finished, quiet=QUIET)
        return text, int((time.monotonic() - started) * 1000)

    @staticmethod
    def _wait_for_greeting(page, appear=10.0, settle=2.5, timeout=45.0):
        """Newer versions stream a greeting first; sending while it streams only stops it."""
        greeting = page.locator(ASSISTANT)
        deadline = time.monotonic() + appear
        while not greeting.count():
            if time.monotonic() > deadline:
                return  # No greeting in this version of the page.
            page.wait_for_timeout(250)
        # It pauses mid-stream; like / dislike actions mark it complete, as for answers.
        wait_until_stable(
            lambda: greeting.last.inner_text(),
            timeout=timeout,
            settle=settle,
            done=lambda: greeting.last.locator("[data-testid=message-actions-container]").count() > 0,
            quiet=QUIET,
        )

    def _reach_chat(self, page, steps=12):
        for _ in range(steps):
            if page.locator("textarea").count():
                return
            terms = page.locator("[data-testid=accept-terms-checkbox]")
            if terms.count():
                if not terms.is_checked():
                    # The input is visually hidden; click its box, not the label text,
                    # which contains the "conditions of carriage" / "privacy policy" links.
                    terms.locator("xpath=..").click()
                if not terms.is_checked():
                    terms.check(force=True)
                start = page.locator("button", has_text="Start a chat").first
                if start.is_enabled():
                    start.click()
            elif page.locator("button", has_text="Next").count():
                page.locator("button", has_text="Next").first.click()
            page.wait_for_timeout(1500)
        raise BotError("Could not reach the chat input; the Concierge AI page may have changed.")
