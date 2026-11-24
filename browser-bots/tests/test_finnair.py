from contextlib import contextmanager
from pathlib import Path

import pytest

from browser_bots.base import BotError, fresh_page
from browser_bots.finnair import CHAT_URL, FinnairBot

HERE = Path(__file__).parent
PAGE = (HERE / "finnair_fixture.html").read_text()
CHAT = (HERE / "finnair_chat_fixture.html").read_text()


def fixture_pages(page_html=PAGE):
    """Serve offline imitations of finnair.com and the Sisu iframe."""

    def html(body):
        return lambda route: route.fulfill(status=200, content_type="text/html", body=body)

    @contextmanager
    def factory(headless=True):
        with fresh_page(headless=headless) as page:
            page.route(CHAT_URL, html(page_html))
            page.route("https://finnair.my.site.com/**", html(CHAT))
            yield page

    return factory


def test_fills_prechat_form_and_joins_all_answer_bubbles():
    bot = FinnairBot(timeout=20, page_factory=fixture_pages())
    answer, latency_ms = bot.ask("Baggage in economy?")
    # The greeting is not part of the answer; both answer bubbles are.
    assert answer == "Answer to: Baggage in economy?\nEconomy Classic includes 1 checked bag, up to 23 kg."
    assert latency_ms > 0


def test_changed_page_is_a_bot_error():
    bot = FinnairBot(timeout=5, step_timeout=2, page_factory=fixture_pages("<html><body>Maintenance</body></html>"))
    with pytest.raises(BotError, match="Could not start a Sisu chat"):
        bot.ask("q")


def test_conversation_reads_only_bubbles_after_the_reply():
    bot = FinnairBot(timeout=20, page_factory=fixture_pages())
    result = bot.converse("Baggage?", "Economy", 5, [r"to: baggage"])
    assert [t["assistant"] for t in result["turns"]] == [
        "Answer to: Baggage?\nEconomy Classic includes 1 checked bag, up to 23 kg.",
        "Answer to: Economy\nEconomy Classic includes 1 checked bag, up to 23 kg.",
    ]
    assert result["ended"] == "answered"
