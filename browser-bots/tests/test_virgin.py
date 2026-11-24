from contextlib import contextmanager
from pathlib import Path

import pytest

from browser_bots.base import BotError, fresh_page, wait_until_stable
from browser_bots.virgin import CHAT_URL, VirginAtlanticBot

FIXTURE = (Path(__file__).parent / "virgin_fixture.html").read_text()


def fixture_pages(html=FIXTURE):
    """Serve the offline imitation instead of the real site."""

    @contextmanager
    def factory(headless=True):
        with fresh_page(headless=headless) as page:
            page.route(CHAT_URL, lambda route: route.fulfill(status=200, content_type="text/html", body=html))
            yield page

    return factory


def test_walks_onboarding_accepts_terms_and_reads_answer():
    bot = VirginAtlanticBot(timeout=20, page_factory=fixture_pages())
    answer, latency_ms = bot.ask("London to New York baggage?")
    # Streamed text only; the suggestion link and action buttons are excluded.
    assert answer == "Answer to: London to New York baggage?. Economy Classic includes one 23kg bag."
    assert latency_ms > 0


def test_changed_page_is_a_bot_error():
    bot = VirginAtlanticBot(timeout=5, page_factory=fixture_pages("<html><body>Maintenance</body></html>"))
    with pytest.raises(BotError, match="Could not reach the chat input"):
        bot.ask("q")


def test_wait_until_stable_times_out():
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    with pytest.raises(BotError, match="No complete answer"):
        wait_until_stable(lambda: "partial", timeout=5, done=lambda: False, clock=lambda: now[0], sleep=sleep)


def test_wait_until_stable_quiet_completes_without_done():
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    value = wait_until_stable(lambda: "final", timeout=30, done=lambda: False, quiet=8, clock=lambda: now[0], sleep=sleep)
    assert value == "final"
    assert 8 <= now[0] < 10


def test_conversation_replies_in_same_session_and_reads_only_new_answer():
    bot = VirginAtlanticBot(timeout=20, page_factory=fixture_pages())
    result = bot.converse("Which bag?", "Economy", 5, [r"answer to: which bag"])
    assert [(t["user"], t["assistant"], t["follow_up"]) for t in result["turns"]] == [
        ("Which bag?", "Answer to: Which bag?. Economy Classic includes one 23kg bag.", True),
        ("Economy", "Answer to: Economy. Economy Classic includes one 23kg bag.", False),
    ]
    assert result["ended"] == "answered"
    assert result["latency_ms"] == sum(t["latency_ms"] for t in result["turns"])


def test_conversation_stops_at_max_turns():
    bot = VirginAtlanticBot(timeout=20, page_factory=fixture_pages())
    result = bot.converse("Which bag?", "Economy", 2, [r"economy classic"])
    assert [t["user"] for t in result["turns"]] == ["Which bag?", "Economy"]
    assert result["ended"] == "max_turns"
