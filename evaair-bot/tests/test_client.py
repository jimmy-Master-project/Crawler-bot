from urllib.parse import parse_qs

import httpx
import pytest

from evaair_bot.client import BotError, EvaAirBot, extract_answer

CHAT_URL = "https://bot.example.test/wise/webchat/default3/?t=frontkey&ch=web"
CHAT_PAGE = """<script>
  window.contextPath = '\\/wise';
  window.qaId = 'session-1';
  window.channel = 'web';
</script>"""
# Shape captured from a real chats-ajax.jsp answer (trimmed).
ANSWER_PAYLOAD = {
    "__AnswerBy__": "SemanticSearchSnippetsAnswerRule",
    "output": "",
    "rm": {
        "messages": [
            {
                "html": "國際線經濟艙的免費托運行李額度會依航線而有所差異。<BR/><BR/>"
                "建議您透過<a href='https://booking.example/calc' class='al'>行李計算器</a>查詢。",
                "quickReply": {"items": [{"action": {"label": "其他問題"}}]},
            }
        ]
    },
}


def transport(payload=ANSWER_PAYLOAD, page=CHAT_PAGE, seen=None):
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, text=page)
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if seen is not None:
            seen.append((str(request.url), form))
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def test_reads_rich_message_html_as_text():
    assert extract_answer(ANSWER_PAYLOAD) == (
        "國際線經濟艙的免費托運行李額度會依航線而有所差異。\n建議您透過行李計算器查詢。"
    )


def test_combines_output_and_messages():
    assert extract_answer({"output": "<p>A</p>", "rm": {"messages": [{"text": "B"}, None]}}) == "A\n\nB"


def test_opens_session_and_asks():
    seen = []
    answer, latency_ms = EvaAirBot(chat_url=CHAT_URL, transport=transport(seen=seen)).ask("行李額度？")
    assert "行李計算器" in answer
    assert latency_ms >= 0
    url, form = seen[0]
    assert url == "https://bot.example.test/wise/chats-ajax.jsp"
    assert form == {"id": "session-1", "q": "行李額度？", "fk": "frontkey", "ch": "web", "et": "message"}


@pytest.mark.parametrize("payload", [{"error": "timeout"}, {"Hangup": True, "output": "bye"}, {"output": ""}])
def test_session_errors_raise(payload):
    with pytest.raises(BotError):
        EvaAirBot(chat_url=CHAT_URL, transport=transport(payload=payload)).ask("q")


def test_page_without_session_id_raises():
    with pytest.raises(BotError):
        EvaAirBot(chat_url=CHAT_URL, transport=transport(page="<html></html>")).ask("q")


def test_strips_widget_footer():
    payload = {"rm": {"messages": [{"html": "請洽客服中心。<BR/> Powered by OpenAI"}]}}
    assert extract_answer(payload) == "請洽客服中心。"


def conversation_transport(answers, seen):
    """A chat page that sets a cookie, then one scripted answer per POST."""

    def handler(request):
        if request.method == "GET":
            seen.append(("GET", None, None))
            return httpx.Response(200, text=CHAT_PAGE, headers={"Set-Cookie": "JSESSIONID=abc; Path=/"})
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        seen.append(("POST", form, request.headers.get("cookie")))
        posts = sum(1 for method, _, _ in seen if method == "POST")
        return httpx.Response(200, json={"output": answers[posts - 1]})

    return httpx.MockTransport(handler)


def test_conversation_stops_when_no_follow_up():
    seen = []
    bot = EvaAirBot(chat_url=CHAT_URL, transport=conversation_transport(["托運 23 公斤。"], seen))
    result = bot.converse("行李額度？", "經濟艙", 5, [r"請問.*艙等"])
    assert result["ended"] == "answered"
    assert result["turns"] == [{"user": "行李額度？", "assistant": "托運 23 公斤。", "latency_ms": result["latency_ms"], "follow_up": False}]
    assert len(seen) == 2


def test_conversation_replies_in_same_session():
    seen = []
    bot = EvaAirBot(chat_url=CHAT_URL, transport=conversation_transport(["請問您的艙等？", "經濟艙可托運 23 公斤。"], seen))
    result = bot.converse("行李額度？", "經濟艙", 5, [r"請問.*艙等"])
    assert [(t["user"], t["assistant"], t["follow_up"]) for t in result["turns"]] == [
        ("行李額度？", "請問您的艙等？", True),
        ("經濟艙", "經濟艙可托運 23 公斤。", False),
    ]
    assert result["ended"] == "answered"
    # One page load; every turn reuses its qaId and cookie.
    assert [method for method, _, _ in seen] == ["GET", "POST", "POST"]
    assert {form["id"] for method, form, _ in seen if method == "POST"} == {"session-1"}
    assert all(cookie == "JSESSIONID=abc" for method, _, cookie in seen if method == "POST")


def test_conversation_stops_at_max_turns():
    seen = []
    bot = EvaAirBot(chat_url=CHAT_URL, transport=conversation_transport(["Which CLASS?"] * 5, seen))
    result = bot.converse("Baggage?", "Economy", 3, [r"which class"])
    assert [t["user"] for t in result["turns"]] == ["Baggage?", "Economy", "Economy"]
    assert all(t["follow_up"] for t in result["turns"])
    assert result["ended"] == "max_turns"
