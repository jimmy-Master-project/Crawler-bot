from contextlib import contextmanager
from pathlib import Path

import pytest

import json

from browser_bots import ada, chinaairlines, vietjet
from browser_bots.ada import AdaBot
from browser_bots.base import BotError, fresh_page
from browser_bots.chinaairlines import CHAT_URL, ChinaAirlinesBot
from browser_bots.vietjet import VietjetBot

HERE = Path(__file__).parent


def html(name):
    body = (HERE / name).read_text()
    return lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)


def serving(routes):
    """Serve offline imitations instead of the real sites."""

    @contextmanager
    def factory(headless=True):
        with fresh_page(headless=headless) as page:
            for pattern, handler in routes.items():
                page.route(pattern, handler)
            yield page

    return factory


@pytest.fixture
def short_quiet(monkeypatch):
    # Keep the "nothing new for a while means done" waits short in tests.
    monkeypatch.setattr(ada, "QUIET", 3.0)
    monkeypatch.setattr(chinaairlines, "QUIET", 3.0)
    monkeypatch.setattr(chinaairlines, "GREETING_QUIET", 2.0)


def test_ada_skips_greeting_and_joins_answer_bubbles(short_quiet):
    factory = serving({
        "https://testair.ada.support/chat/": html("ada_fixture.html"),
        "https://static.ada.support/**": html("ada_app_fixture.html"),
    })
    bot = AdaBot("testair", "testair", timeout=20, page_factory=factory)
    answer, latency_ms = bot.ask("Can I bring my dog?")
    # Greeting bubbles, our own message and suggested replies are excluded.
    assert answer == "Answer to: Can I bring my dog?\nPets travel in the cargo hold."
    assert latency_ms > 0


def test_ada_missing_chat_is_a_bot_error():
    factory = serving({"https://testair.ada.support/chat/": lambda route: route.fulfill(body="Maintenance")})
    bot = AdaBot("testair", "testair", timeout=5, step_timeout=2, page_factory=factory)
    with pytest.raises(BotError, match="Could not find the testair chat input"):
        bot.ask("q")


def test_chinaairlines_skips_greeting_and_reads_answer(short_quiet):
    factory = serving({
        CHAT_URL: html("chinaairlines_fixture.html"),
        "**/chatindex.aspx": html("chinaairlines_chat_fixture.html"),
    })
    bot = ChinaAirlinesBot(timeout=20, page_factory=factory)
    answer, latency_ms = bot.ask("Can I bring my dog?")
    # Blank lines are collapsed; the feedback prompt and suggestions are excluded.
    assert answer == "Answer to: Can I bring my dog?\nDogs travel in the cargo hold."
    assert latency_ms > 0


def test_chinaairlines_missing_chat_is_a_bot_error():
    factory = serving({CHAT_URL: lambda route: route.fulfill(body="Maintenance")})
    bot = ChinaAirlinesBot(timeout=5, step_timeout=2, page_factory=factory)
    with pytest.raises(BotError, match="Could not find the China Airlines chat input"):
        bot.ask("q")


def fake_vinbase(ws, sent):
    """Imitate cloud.vinbase.ai: greet after Start, then stream a two-group answer."""
    prefix = "42" + vietjet.NAMESPACE + ","

    def emit(event, payload):
        ws.send(prefix + json.dumps([event, payload]))

    def on_message(message):
        if message.startswith("40"):
            ws.send("40" + vietjet.NAMESPACE)
            emit("on_authenticated", {"client_id": "CID", "data": []})
        elif message.startswith(prefix):
            event, payload = json.loads(message[len(prefix):])
            sent.append((event, payload))
            if event == "on_user_postback":
                emit("on_bot_message", {"data": [{"type": "text", "value": "I'm Amy, your virtual assistant."}]})
            elif event == "on_user_message":
                for value in ("Answer", "Answer to: " + payload["data"]):
                    emit("on_bot_message", {"data": [{"type": "text", "value": value, "group_id": "g1"}]})
                emit("on_bot_message", {"data": [{"type": "text", "value": "Pets travel in the cabin.", "group_id": "g2", "success": True}]})

    ws.on_message(on_message)
    ws.send('0{"sid":"S","pingInterval":25000,"pingTimeout":60000}')


def test_vietjet_speaks_widget_protocol_and_joins_streamed_groups(monkeypatch):
    monkeypatch.setattr(vietjet, "QUIET_MS", 1500)
    sent = []

    @contextmanager
    def factory(headless=True):
        with fresh_page(headless=headless) as page:
            page.route(vietjet.CHAT_URL, html("vietjet_fixture.html"))
            page.route_web_socket("wss://cloud.vinbase.ai/**", lambda ws: fake_vinbase(ws, sent))
            yield page

    bot = VietjetBot(timeout=20, page_factory=factory)
    answer, latency_ms = bot.ask("Can I bring my dog?")
    # Only the final text of each streamed group; the greeting is excluded.
    assert answer == "Answer to: Can I bring my dog?\nPets travel in the cabin."
    assert latency_ms > 0
    message = next(payload for event, payload in sent if event == "on_user_message")
    # Our message reuses the ids and guest user from the widget's own Start postback.
    assert (message["agent_id"], message["channel_id"], message["user_name"]) == ("AGENT", "CHANNEL", "USER1")


def test_vietjet_missing_widget_is_a_bot_error():
    factory = serving({vietjet.CHAT_URL: lambda route: route.fulfill(body="Maintenance")})
    bot = VietjetBot(timeout=5, step_timeout=2, page_factory=factory)
    with pytest.raises(BotError, match="Could not open the Vietjet chat widget"):
        bot.ask("q")



def test_ada_conversation_stops_when_no_follow_up(short_quiet):
    factory = serving({
        "https://testair.ada.support/chat/": html("ada_fixture.html"),
        "https://static.ada.support/**": html("ada_app_fixture.html"),
    })
    bot = AdaBot("testair", "testair", timeout=20, page_factory=factory)
    result = bot.converse("Can I bring my dog?", "Economy", 5, [r"which class"])
    assert [t["follow_up"] for t in result["turns"]] == [False]
    assert result["ended"] == "answered"


def test_ada_conversation_reads_only_new_bubbles(short_quiet):
    factory = serving({
        "https://testair.ada.support/chat/": html("ada_fixture.html"),
        "https://static.ada.support/**": html("ada_app_fixture.html"),
    })
    bot = AdaBot("testair", "testair", timeout=20, page_factory=factory)
    result = bot.converse("Can I bring my dog?", "A small one", 5, [r"my dog"])
    assert [t["assistant"] for t in result["turns"]] == [
        "Answer to: Can I bring my dog?\nPets travel in the cargo hold.",
        "Answer to: A small one\nPets travel in the cargo hold.",
    ]
    assert result["ended"] == "answered"


def test_chinaairlines_conversation_reads_only_new_answer(short_quiet):
    factory = serving({
        CHAT_URL: html("chinaairlines_fixture.html"),
        "**/chatindex.aspx": html("chinaairlines_chat_fixture.html"),
    })
    bot = ChinaAirlinesBot(timeout=20, page_factory=factory)
    result = bot.converse("Can I bring my dog?", "A small one", 5, [r"my dog"])
    assert [t["assistant"] for t in result["turns"]] == [
        "Answer to: Can I bring my dog?\nDogs travel in the cargo hold.",
        "Answer to: A small one\nDogs travel in the cargo hold.",
    ]
    assert result["ended"] == "answered"


def test_vietjet_conversation_reuses_one_socket(monkeypatch):
    monkeypatch.setattr(vietjet, "QUIET_MS", 1500)
    sent, sockets = [], []

    def handler(ws):
        sockets.append(ws)
        fake_vinbase(ws, sent)

    @contextmanager
    def factory(headless=True):
        with fresh_page(headless=headless) as page:
            page.route(vietjet.CHAT_URL, html("vietjet_fixture.html"))
            page.route_web_socket("wss://cloud.vinbase.ai/**", handler)
            yield page

    bot = VietjetBot(timeout=20, page_factory=factory)
    result = bot.converse("Can I bring my dog?", "A small one", 3, [r"cabin"])
    # Each answer ends with "...in the cabin.", so the reply is sent until max_turns.
    assert [(t["user"], t["assistant"]) for t in result["turns"]] == [
        ("Can I bring my dog?", "Answer to: Can I bring my dog?\nPets travel in the cabin."),
        ("A small one", "Answer to: A small one\nPets travel in the cabin."),
        ("A small one", "Answer to: A small one\nPets travel in the cabin."),
    ]
    assert result["ended"] == "max_turns"
    # The widget's own connection plus ours; our Start postback is sent once.
    assert len(sockets) == 2
    assert [event for event, _ in sent].count("on_user_message") == 3
    assert [event for event, _ in sent].count("on_user_postback") == 2
