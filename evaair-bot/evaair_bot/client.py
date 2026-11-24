"""EVA Air web chatbot (Intumit SmartRobot "wise" webchat).

Protocol, read from the public webchat page (js/chatbot.js):

* Loading the chat page sets a session cookie and embeds ``window.qaId``.
* ``POST {origin}/wise/chats-ajax.jsp`` with ``id`` (qaId), ``q`` (question),
  ``fk`` (the page's ``t`` query parameter), ``ch`` and ``et=message``.
  The answer is in ``output`` and/or ``rm.messages[].html``.
* An ``error`` key or ``Hangup`` means the session expired.
"""

import re
import time
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

DEFAULT_CHAT_URL = "https://bot.evaair.com/wise/webchat/default3/?t=18696acf343be5147937&ch=web"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) llm-bias-pipeline research client"

_QA_ID = re.compile(r"window\.qaId\s*=\s*'([^']+)'")
_CONTEXT_PATH = re.compile(r"window\.contextPath\s*=\s*'([^']*)'")


class BotError(Exception):
    """The bot could not produce an answer (network, protocol or session)."""


def run_conversation(send, question, follow_up_reply, max_turns, patterns):
    """Ask ``question`` with ``send(message) -> (text, latency_ms)`` and answer follow-ups.

    While an answer matches one of ``patterns`` (case-insensitive ``re.search``)
    and fewer than ``max_turns`` turns were taken, ``follow_up_reply`` is sent.
    """
    compiled = [re.compile(p, re.IGNORECASE) if isinstance(p, str) else p for p in patterns]
    turns, message = [], question
    while True:
        text, latency_ms = send(message)
        follow_up = any(p.search(text) for p in compiled)
        turns.append({"user": message, "assistant": text, "latency_ms": latency_ms, "follow_up": follow_up})
        if not follow_up:
            ended = "answered"
            break
        if len(turns) >= max_turns:
            ended = "max_turns"
            break
        message = follow_up_reply
    return {"turns": turns, "ended": ended, "latency_ms": sum(t["latency_ms"] for t in turns)}


class _TextExtractor(HTMLParser):
    _BREAKS = {"br", "p", "div", "li", "tr"}

    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self._BREAKS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(html):
    parser = _TextExtractor()
    parser.feed(html or "")
    text = unescape("".join(parser.parts))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


# Widget boilerplate appended to generated answers; not part of the answer.
_FOOTER = re.compile(r"\s*Powered by OpenAI\s*$", re.IGNORECASE)


def extract_answer(payload):
    """Join the plain-text answer from ``output`` and rich messages."""
    pieces = []
    if payload.get("output"):
        pieces.append(html_to_text(payload["output"]))
    for message in (payload.get("rm") or {}).get("messages") or []:
        if not isinstance(message, dict):
            continue
        if message.get("html"):
            pieces.append(html_to_text(message["html"]))
        elif message.get("text"):
            pieces.append(str(message["text"]).strip())
    answer = "\n\n".join(piece for piece in pieces if piece)
    return _FOOTER.sub("", answer).strip()


class EvaAirBot:
    name = "evaair"

    def __init__(self, chat_url=DEFAULT_CHAT_URL, timeout=60.0, transport=None):
        parsed = urlparse(chat_url)
        params = parse_qs(parsed.query)
        self.chat_url = chat_url
        self.frontend_key = (params.get("t") or [""])[0]
        self.channel = (params.get("ch") or ["web"])[0]
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.timeout = timeout
        self.transport = transport

    def ask(self, question):
        """Ask one question in a brand-new session; returns (answer, latency_ms).

        A fresh session per question keeps earlier prompts from leaking into
        later answers, which would confound the bias measurement.
        """
        return self._session(lambda send: send(question))

    def converse(self, question, follow_up_reply, max_turns, patterns):
        """One conversation in a brand-new session (same cookies and qaId for every turn)."""
        return self._session(lambda send: run_conversation(send, question, follow_up_reply, max_turns, patterns))

    def _session(self, run):
        with httpx.Client(
            timeout=self.timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            session = self._open(client)
            return run(lambda message: self._send(client, session, message))

    def _open(self, client):
        """Load the chat page (sets the session cookie); returns (qa_id, context_path)."""
        try:
            page = client.get(self.chat_url)
            page.raise_for_status()
        except httpx.HTTPError as exc:
            raise BotError(f"Cannot open chat page: {exc}") from exc
        qa_id = _QA_ID.search(page.text)
        if not qa_id:
            raise BotError("Chat page did not contain window.qaId; the page layout may have changed.")
        context = _CONTEXT_PATH.search(page.text)
        context_path = context.group(1).replace("\\/", "/") if context else "/wise"
        return qa_id.group(1), context_path

    def _send(self, client, session, message):
        qa_id, context_path = session
        started = time.monotonic()
        try:
            response = client.post(
                urljoin(self.origin, f"{context_path}/chats-ajax.jsp"),
                data={
                    "id": qa_id,
                    "q": message,
                    "fk": self.frontend_key,
                    "ch": self.channel,
                    "et": "message",
                },
                headers={"Referer": self.chat_url, "X-Requested-With": "XMLHttpRequest"},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BotError(f"Ask request failed: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        if "error" in payload or payload.get("Hangup"):
            raise BotError(f"Bot session error: {payload.get('error') or 'hangup'}")
        answer = extract_answer(payload)
        if not answer:
            raise BotError("Bot returned an empty answer.")
        return answer, latency_ms
