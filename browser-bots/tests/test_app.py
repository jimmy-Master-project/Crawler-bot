import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from browser_bots.app import RateLimiter, create_app
from browser_bots.base import BotError, run_conversation


class FakeBot:
    def __init__(self, fail=False):
        self.questions = []
        self.fail = fail

    def ask(self, question):
        self.questions.append(question)
        if self.fail:
            raise BotError("Could not reach the chat input")
        return f"answer to {question}", 42

    def converse(self, question, follow_up_reply, max_turns, patterns):
        self.conversations = getattr(self, "conversations", []) + [(question, follow_up_reply, max_turns)]
        return run_conversation(self.ask, question, follow_up_reply, max_turns, patterns)


def client(bot, name="virgin"):
    return TestClient(create_app(bots={name: bot}, min_interval=0))


def test_health_lists_bots():
    assert client(FakeBot()).get("/health").json() == {"status": "ok", "bots": ["virgin"]}


def test_models_are_per_bot():
    assert client(FakeBot()).get("/virgin/v1/models").json()["data"][0]["id"] == "virgin"


def test_chat_completion_asks_last_user_message():
    bot = FakeBot()
    response = client(bot).post(
        "/virgin/v1/chat/completions",
        json={"model": "virgin", "messages": [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}], "temperature": 0.7},
    )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "answer to b"
    assert bot.questions == ["b"]


def test_bot_failure_is_upstream_error():
    response = client(FakeBot(fail=True)).post("/virgin/v1/chat/completions", json={"messages": [{"role": "user", "content": "q"}]})
    assert response.status_code == 502


def test_missing_user_message_is_400():
    response = client(FakeBot()).post("/virgin/v1/chat/completions", json={"messages": []})
    assert response.status_code == 400


def test_works_with_openai_sdk():
    sdk = OpenAI(base_url="http://testserver/virgin/v1", api_key="unused", http_client=client(FakeBot()))
    completion = sdk.chat.completions.create(model="virgin", messages=[{"role": "user", "content": "hi"}])
    assert completion.choices[0].message.content == "answer to hi"
    assert [m.id for m in sdk.models.list()] == ["virgin"]


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
    bot = FakeBot()
    response = client(bot).post(
        "/virgin/v1/conversation",
        json={"question": "Which class?", "follow_up_reply": "Economy", "follow_up_patterns": ["CLASS\\?"]},
    )
    assert response.status_code == 200
    assert response.json() == {
        "turns": [
            {"user": "Which class?", "assistant": "answer to Which class?", "latency_ms": 42, "follow_up": True},
            {"user": "Economy", "assistant": "answer to Economy", "latency_ms": 42, "follow_up": False},
        ],
        "ended": "answered",
        "latency_ms": 84,
    }
    assert bot.conversations == [("Which class?", "Economy", 5)]


def test_conversation_stops_at_max_turns():
    response = client(FakeBot()).post(
        "/virgin/v1/conversation",
        json={"question": "q", "follow_up_reply": "r", "max_turns": 3, "follow_up_patterns": ["^answer"]},
    )
    body = response.json()
    assert [t["user"] for t in body["turns"]] == ["q", "r", "r"]
    assert body["ended"] == "max_turns"


def test_conversation_bot_failure_is_upstream_error():
    response = client(FakeBot(fail=True)).post("/virgin/v1/conversation", json={"question": "q", "follow_up_reply": "r"})
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
    response = client(bot).post("/virgin/v1/conversation", json=body)
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert bot.questions == []


def test_chat_completion_validation_still_422():
    assert client(FakeBot()).post("/virgin/v1/chat/completions", json={}).status_code == 422
