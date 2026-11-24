import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from evaair_bot.app import RateLimiter, create_app
from evaair_bot.client import BotError, run_conversation


class FakeBot:
    def __init__(self, fail=False):
        self.questions = []
        self.fail = fail

    def ask(self, question):
        self.questions.append(question)
        if self.fail:
            raise BotError("Bot session error: hangup")
        return f"answer to {question}", 42

    def converse(self, question, follow_up_reply, max_turns, patterns):
        return run_conversation(self.ask, question, follow_up_reply, max_turns, patterns)


def client(bot):
    return TestClient(create_app(bot=bot, limiter=RateLimiter(0)))


def test_models_lists_evaair():
    assert client(FakeBot()).get("/v1/models").json()["data"][0]["id"] == "evaair"


def test_chat_completion_asks_last_user_message():
    bot = FakeBot()
    response = client(bot).post(
        "/v1/chat/completions",
        json={
            "model": "evaair",
            "messages": [{"role": "user", "content": "first"}, {"role": "user", "content": "行李？"}],
            "temperature": 0.7,
            "max_tokens": 512,
        },
    )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "answer to 行李？"
    assert bot.questions == ["行李？"]


def test_bot_failure_is_upstream_error():
    response = client(FakeBot(fail=True)).post(
        "/v1/chat/completions", json={"messages": [{"role": "user", "content": "q"}]}
    )
    assert response.status_code == 502
    assert response.json()["error"]["type"] == "upstream_error"


def test_missing_user_message_is_400():
    response = client(FakeBot()).post("/v1/chat/completions", json={"messages": [{"role": "system", "content": "x"}]})
    assert response.status_code == 400


def test_works_with_openai_sdk():
    """The backend talks to this service through the OpenAI SDK."""
    test_client = client(FakeBot())
    sdk = OpenAI(base_url="http://testserver/v1", api_key="unused", http_client=test_client)
    completion = sdk.chat.completions.create(model="evaair", messages=[{"role": "user", "content": "hi"}])
    assert completion.choices[0].message.content == "answer to hi"
    assert [m.id for m in sdk.models.list()] == ["evaair"]


def test_rate_limiter_spaces_calls():
    now = [0.0]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(3, clock=lambda: now[0], sleep=sleep)
    limiter.run(lambda: None)
    now[0] += 1
    limiter.run(lambda: None)
    assert slept == [2]


def test_conversation_endpoint_shape():
    response = client(FakeBot()).post(
        "/v1/conversation",
        json={"question": "哪個艙等？", "follow_up_reply": "經濟艙", "follow_up_patterns": ["艙等？$"]},
    )
    assert response.status_code == 200
    assert response.json() == {
        "turns": [
            {"user": "哪個艙等？", "assistant": "answer to 哪個艙等？", "latency_ms": 42, "follow_up": True},
            {"user": "經濟艙", "assistant": "answer to 經濟艙", "latency_ms": 42, "follow_up": False},
        ],
        "ended": "answered",
        "latency_ms": 84,
    }


def test_conversation_stops_at_max_turns():
    response = client(FakeBot()).post(
        "/v1/conversation",
        json={"question": "q", "follow_up_reply": "r", "max_turns": 2, "follow_up_patterns": ["ANSWER"]},
    )
    body = response.json()
    assert [t["user"] for t in body["turns"]] == ["q", "r"]
    assert body["ended"] == "max_turns"


def test_conversation_is_one_rate_limited_call():
    calls = []

    class CountingLimiter(RateLimiter):
        def run(self, fn, *args):
            calls.append(fn.__name__)
            return super().run(fn, *args)

    test_client = TestClient(create_app(bot=FakeBot(), limiter=CountingLimiter(0)))
    test_client.post("/v1/conversation", json={"question": "q", "follow_up_reply": "r", "follow_up_patterns": ["answer"]})
    assert calls == ["converse"]


def test_conversation_bot_failure_is_upstream_error():
    response = client(FakeBot(fail=True)).post("/v1/conversation", json={"question": "q", "follow_up_reply": "r"})
    assert response.status_code == 502
    assert response.json()["error"]["type"] == "upstream_error"


@pytest.mark.parametrize(
    "body",
    [
        {"follow_up_reply": "r"},
        {"question": " ", "follow_up_reply": "r"},
        {"question": "q", "follow_up_reply": ""},
        {"question": "q", "follow_up_reply": "r", "max_turns": 0},
        {"question": "q", "follow_up_reply": "r", "max_turns": 11},
        {"question": "q", "follow_up_reply": "r", "follow_up_patterns": ["("]},
    ],
)
def test_conversation_bad_input_is_400(body):
    bot = FakeBot()
    response = client(bot).post("/v1/conversation", json=body)
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert bot.questions == []


def test_chat_completion_validation_still_422():
    assert client(FakeBot()).post("/v1/chat/completions", json={}).status_code == 422
