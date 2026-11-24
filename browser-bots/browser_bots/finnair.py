"""Finnair "Sisu" AI assistant (chat widget on https://www.finnair.com/en).

Flow observed on the live site:

1. A cookie banner ("Allow all").
2. ``#chat-help-button`` opens the "Ask Sisu" panel; "Chat with us" opens a
   pre-chat form: ``#firstName``, ``#lastName``, ``#email`` and "Is your
   question related to an existing booking?" (Yes / No), then "Start the chat".
3. The chat is Salesforce Embedded Messaging in an iframe from
   ``finnair.my.site.com`` (``?lwc.mode=prod``). Sisu greets first; our
   question goes into its ``textarea`` (Enter sends). Answers are
   ``.embedded-messaging-inbound-chat-message`` bubbles, and Sisu may send
   several per question; ``.chat-typing-indicator`` is shown while it writes.
"""

import time

from .base import BotError, ChatBot, fresh_page, wait_until_stable

CHAT_URL = "https://www.finnair.com/en"
CHAT_FRAME = "iframe[src*='my.site.com'][src*='lwc.mode']"
INBOUND = ".embedded-messaging-inbound-chat-message"
TYPING = ".chat-typing-indicator"


class FinnairBot(ChatBot):
    name = "finnair"

    def __init__(
        self,
        chat_url=CHAT_URL,
        timeout=90.0,
        headless=True,
        page_factory=fresh_page,
        first_name="Research",
        last_name="Tester",
        email="research@example.com",
        step_timeout=30.0,
    ):
        self.chat_url = chat_url
        self.timeout = timeout
        self.headless = headless
        self.page_factory = page_factory
        self.first_name = first_name
        self.last_name = last_name
        self.email = email
        self.step_timeout = step_timeout

    def _open(self, page):
        page.set_default_timeout(self.step_timeout * 1000)
        try:
            page.goto(self.chat_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            raise BotError(f"Cannot open Finnair page: {str(exc).splitlines()[0]}") from exc
        frame = self._start_chat(page)
        inbound = frame.locator(INBOUND)
        typing = frame.locator(TYPING)
        # Let the greeting finish so it is not mistaken for the answer.
        wait_until_stable(lambda: inbound.count(), timeout=30, settle=1.5, done=lambda: typing.count() == 0)
        return frame

    def _send(self, page, frame, message):
        inbound = frame.locator(INBOUND)
        typing = frame.locator(TYPING)
        before = inbound.count()
        frame.locator("textarea").fill(message)
        frame.locator("textarea").press("Enter")
        started = time.monotonic()

        def answer():
            texts = [m.inner_text().strip() for m in inbound.all()[before:]]
            return "\n".join(t for t in texts if t)

        # Sisu can send several bubbles; wait until it stops typing and nothing new arrives.
        text = wait_until_stable(answer, timeout=self.timeout, settle=3.0, done=lambda: typing.count() == 0)
        return text, int((time.monotonic() - started) * 1000)

    def _start_chat(self, page):
        try:
            cookies = page.locator("button", has_text="Allow all")
            try:
                cookies.first.wait_for(timeout=min(8.0, self.step_timeout) * 1000)
                cookies.first.click()
            except Exception:
                pass  # No banner (already accepted or not shown).
            page.locator("#chat-help-button").click()
            page.locator("button", has_text="Chat with us").click()
            form = page.locator("form:has(#firstName)")
            form.locator("#firstName").fill(self.first_name)
            form.locator("#lastName").fill(self.last_name)
            form.locator("#email").fill(self.email)
            form.get_by_text("No", exact=True).click()
            form.locator("button", has_text="Start the chat").click()
            frame = page.frame_locator(CHAT_FRAME)
            frame.locator(INBOUND).first.wait_for(timeout=self.step_timeout * 2000)
        except BotError:
            raise
        except Exception as exc:
            raise BotError(
                f"Could not start a Sisu chat; the Finnair page may have changed: {str(exc).splitlines()[0]}"
            ) from exc
        return frame
