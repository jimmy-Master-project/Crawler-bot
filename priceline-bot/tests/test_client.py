import json

import httpx
import pytest

from priceline_bot.client import (
    CHAT_URL,
    PAGE_URL,
    BotError,
    PricelineBot,
    _parse_answer,
)

FAKE_SID = "aaa.bbb.ccc"
PAGE_HTML = f'<html><body><script>window.__DATA__={{"pennysid":"{FAKE_SID}"}}</script></body></html>'


def _response(body, content_type="application/json"):
    return httpx.Response(200, text=body, headers={"content-type": content_type}, request=httpx.Request("POST", CHAT_URL))


def test_parse_plain_json_block_format():
    body = json.dumps({"messages": [{"role": "assistant", "content": [{"type": "text", "text": "Hello from Penny."}]}]})
    assert _parse_answer(_response(body)) == "Hello from Penny."


def test_parse_sse_stream_dedupes_partials():
    stream = "\n".join([
        'data: {"delta": {"type": "text", "text": "Economy includes"}}',
        'data: {"delta": {"type": "text", "text": "Economy includes one bag."}}',
        "data: [DONE]",
    ])
    assert _parse_answer(_response(stream, "text/event-stream")) == "Economy includes\nEconomy includes one bag."


def test_parse_empty_is_error():
    with pytest.raises(BotError):
        _parse_answer(_response(""))


def transport(answer_body, answer_ct="application/json", seen=None):
    def handler(request):
        if request.url.path == "/penny" or str(request.url) == PAGE_URL:
            return httpx.Response(200, text=PAGE_HTML)
        if seen is not None:
            seen.append(json.loads(request.content.decode()))
        return httpx.Response(200, text=answer_body, headers={"content-type": answer_ct})

    return httpx.MockTransport(handler)


def test_ask_sends_question_and_session():
    seen = []
    body = json.dumps({"content": [{"type": "text", "text": "One checked bag, 23kg."}]})
    bot = PricelineBot(transport=transport(body, seen=seen))
    answer, latency_ms = bot.ask("baggage on economy?")
    assert answer == "One checked bag, 23kg."
    assert latency_ms >= 0
    sent = seen[0]
    assert sent["messages"] == [{"role": "user", "content": [{"type": "text", "text": "baggage on economy?"}]}]
    assert sent["pennysid"] == FAKE_SID
    assert sent["customerCare"] is True  # feature flags preserved


def test_missing_pennysid_is_error():
    def handler(request):
        return httpx.Response(200, text="<html>no token here</html>")

    bot = PricelineBot(transport=httpx.MockTransport(handler))
    with pytest.raises(BotError, match="pennysid"):
        bot.ask("q")
