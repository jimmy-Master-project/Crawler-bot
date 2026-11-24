from fastapi.testclient import TestClient
from openai import OpenAI

from priceline_bot.app import RateLimiter, create_app
from priceline_bot.client import BotError


class FakeBot:
    def __init__(self, fail=False):
        self.questions = []
        self.fail = fail

    def ask(self, question):
        self.questions.append(question)
        if self.fail:
            raise BotError("Penny chat request failed")
        return f"answer to {question}", 55


def client(bot):
    return TestClient(create_app(bot=bot, limiter=RateLimiter(0)))


def test_models_lists_priceline():
    assert client(FakeBot()).get("/v1/models").json()["data"][0]["id"] == "priceline"


def test_chat_completion_asks_last_user_message():
    bot = FakeBot()
    response = client(bot).post(
        "/v1/chat/completions",
        json={
            "model": "priceline",
            "messages": [{"role": "user", "content": "first"}, {"role": "user", "content": "deal?"}],
            "temperature": 0.7,
        },
    )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "answer to deal?"
    assert bot.questions == ["deal?"]


def test_bot_failure_is_upstream_error():
    response = client(FakeBot(fail=True)).post(
        "/v1/chat/completions", json={"messages": [{"role": "user", "content": "q"}]}
    )
    assert response.status_code == 502


def test_missing_user_message_is_400():
    response = client(FakeBot()).post("/v1/chat/completions", json={"messages": []})
    assert response.status_code == 400


def test_works_with_openai_sdk():
    sdk = OpenAI(base_url="http://testserver/v1", api_key="unused", http_client=client(FakeBot()))
    completion = sdk.chat.completions.create(model="priceline", messages=[{"role": "user", "content": "hi"}])
    assert completion.choices[0].message.content == "answer to hi"
    assert [m.id for m in sdk.models.list()] == ["priceline"]


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
