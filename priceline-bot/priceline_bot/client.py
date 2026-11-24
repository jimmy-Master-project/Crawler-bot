"""Priceline Penny chat client.

Observed from the site's own frontend (captured by the project owner, who has a
research agreement with Priceline and a whitelisted IP):

* ``POST https://www.priceline.com/penny/api/chat``
* JSON body carries ``messages`` in an OpenAI-ish shape
  (``[{"role": "user", "content": [{"type": "text", "text": "..."}]}]``) plus a
  ``pennysid`` token and several feature flags.
* ``pennysid`` is a Priceline-signed JWT that embeds a chat id, so it cannot be
  minted locally; it must be obtained from a session the site hands out.

Two things still need confirming against a real capture before this works
end to end (see NEEDS-CONFIRMATION markers):
  1. how a fresh ``pennysid`` is obtained for a new session, and
  2. the exact response shape (JSON vs. SSE, and where the answer text sits).
``_parse_answer`` already handles the common shapes defensively.
"""

import json
import re
import time

import httpx

PAGE_URL = "https://www.priceline.com/penny"
CHAT_URL = "https://www.priceline.com/penny/api/chat"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)

# Default feature flags from the captured request; kept verbatim so the backend
# behaves like the site. Overridable via PricelineBot(extra_flags=...).
DEFAULT_FLAGS = {
    "hotelRecommendPartialJSON": True,
    "rcSearch": True,
    "flightSearch": True,
    "customerCare": True,
    "webSearch": True,
    "enabledUnifiedBlockBasedResponseFormat": True,
    "language": "en-US",
    "languageLabel": "English (US)",
    "askPromptFromUrl": "",
    "profileContext": "",
    "enableCopilotActionTool": False,
}

# NEEDS-CONFIRMATION (1): how the page exposes a fresh pennysid. A JWT with this
# audience is what we are looking for in the page HTML or a bootstrap response.
_PENNYSID_RE = re.compile(r'"pennysid"\s*:\s*"([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"')


class BotError(Exception):
    """Penny could not produce an answer (network, session, or format change)."""


# Keys whose string value is answer text (not metadata like role / id / type).
_TEXT_KEYS = ("text", "answer", "response", "output", "markdown")


def _collect_text(node, out):
    """Walk an arbitrary JSON value and collect answer text.

    Only text blocks (``{"type": "text", "text": ...}``) and strings under a
    text-ish key are collected, so role names and ids are not mistaken for
    answer text. Every nested container is still traversed.
    """
    if isinstance(node, list):
        for item in node:
            _collect_text(item, out)
    elif isinstance(node, dict):
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            out.append(node["text"])
            return
        for key, value in node.items():
            if key in _TEXT_KEYS and isinstance(value, str):
                out.append(value)
            else:
                _collect_text(value, out)


def _parse_answer(response):
    """Extract the assistant's plain-text answer.

    NEEDS-CONFIRMATION (2): confirm against a real response body. Handles both a
    single JSON document and an SSE / JSON-lines stream of blocks.
    """
    body = response.text.strip()
    if not body:
        raise BotError("Empty response from Penny.")

    content_type = response.headers.get("content-type", "")
    pieces = []
    if "text/event-stream" in content_type or body.startswith("data:"):
        for line in body.splitlines():
            line = line.strip()
            if not line or line in ("data: [DONE]", "[DONE]"):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            try:
                _collect_text(json.loads(line), pieces)
            except json.JSONDecodeError:
                continue
    else:
        try:
            _collect_text(response.json(), pieces)
        except json.JSONDecodeError as exc:
            raise BotError(f"Could not parse Penny response: {exc}") from exc

    # Keep the longest contiguous run; blocks often repeat partial + final text.
    answer = "\n".join(dict.fromkeys(p.strip() for p in pieces if p and p.strip()))
    if not answer:
        raise BotError("No answer text found in Penny response.")
    return answer


class PricelineBot:
    name = "priceline"

    def __init__(self, timeout=60.0, extra_flags=None, transport=None):
        self.timeout = timeout
        self.flags = {**DEFAULT_FLAGS, **(extra_flags or {})}
        self.transport = transport

    def _client(self):
        return httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/event-stream"},
            transport=self.transport,
        )

    def _new_pennysid(self, client):
        """Obtain a fresh pennysid for a new conversation.

        NEEDS-CONFIRMATION (1): current guess is that loading the penny page sets
        the session cookies and embeds a pennysid. If Penny instead mints it from
        a dedicated bootstrap endpoint, point this there.
        """
        try:
            page = client.get(PAGE_URL)
            page.raise_for_status()
        except httpx.HTTPError as exc:
            raise BotError(f"Cannot open Penny page: {exc}") from exc
        match = _PENNYSID_RE.search(page.text)
        if not match:
            raise BotError(
                "No pennysid found on the Penny page; confirm how a session token is issued "
                "(see NEEDS-CONFIRMATION (1) in client.py)."
            )
        return match.group(1)

    def ask(self, question):
        """Ask one question in a fresh session; returns (answer, latency_ms)."""
        with self._client() as client:
            pennysid = self._new_pennysid(client)
            payload = {
                **self.flags,
                "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
                "pennysid": pennysid,
            }
            started = time.monotonic()
            try:
                response = client.post(CHAT_URL, json=payload, headers={"Referer": PAGE_URL})
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise BotError(f"Penny chat request failed: {exc}") from exc
            latency_ms = int((time.monotonic() - started) * 1000)
        return _parse_answer(response), latency_ms
