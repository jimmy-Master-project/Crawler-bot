"""Vietjet "Amy Assistant" (VinBigdata chat widget on https://www.vietjetair.com/en).

Flow observed on the live site:

* The widget's launcher (``#prime``) sits under page content, so it is raised
  above it before being clicked. Opening the chat connects a socket.io
  websocket to ``cloud.vinbase.ai`` (namespace ``/api/v1/chat_gateway``) and
  sends a ``Start`` postback carrying the agent / channel ids and a guest user.
* The widget's own text box does not react to automated typing, so after the
  widget has connected we open a second connection from the page with the same
  URL and ids and speak the widget's protocol: wait for ``on_authenticated``
  (gives a ``client_id``), send the ``Start`` postback and ``join_room``, wait
  for the greeting, then ``on_user_message``. The connection stays open on
  ``window.__amy`` so follow-up turns of a conversation reuse it.
* Answers stream back as ``on_bot_message`` events. Every event repeats the
  text so far for its ``group_id``; the last one carries ``success: true``. A
  reply can have several groups.
"""

import time

from .base import BotError, ChatBot, fresh_page

CHAT_URL = "https://www.vietjetair.com/en"
NAMESPACE = "/api/v1/chat_gateway"
# Silence after the last streamed chunk (ms) that marks the reply complete.
QUIET_MS = 6_000

# Installed before the page loads: records the widget's socket URL and its Start postback.
_CAPTURE_JS = r"""(() => {
  const Native = window.WebSocket;
  window.WebSocket = function (url, protocols) {
    const ws = protocols === undefined ? new Native(url) : new Native(url, protocols);
    if (String(url).includes("vinbase.ai") && !window.__vinbase) {
      window.__vinbase = {url: String(url), start: null};
      const send = ws.send.bind(ws);
      ws.send = (data) => {
        if (typeof data === "string" && data.includes('"on_user_postback"') && !window.__vinbase.start) {
          window.__vinbase.start = JSON.parse(data.slice(data.indexOf(",") + 1))[1];
        }
        return send(data);
      };
    }
    return ws;
  };
  window.WebSocket.prototype = Native.prototype;
  Object.assign(window.WebSocket, {CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3});
})();"""

# Runs in the page: opens our own connection (kept on ``window.__amy`` for the
# rest of the conversation), sends the Start postback and waits for the greeting.
_OPEN_JS = r"""async ([url, ns, start, timeoutMs]) => new Promise((resolve) => {
  // The capture wrapper only records the widget's first connection, so this one is ignored.
  const ws = new WebSocket(url);
  const prefix = "42" + ns + ",";
  const amy = window.__amy = {
    ws, groups: new Map(), clientId: null, greeted: false, error: null, last: Date.now(),
    emit: (event, data) => ws.send(prefix + JSON.stringify([event, data])),
  };
  let done = false;
  const finish = (error) => {
    if (done) return;
    done = true; clearInterval(timer);
    if (error) ws.close();
    resolve({error});
  };
  ws.onmessage = (message) => {
    const data = message.data;
    if (data.startsWith("0{")) ws.send("40" + ns + "?token=" + new URL(url).searchParams.get("token"));
    else if (data === "2") ws.send("3");
    else if (data.startsWith(prefix)) {
      const [event, payload] = JSON.parse(data.slice(prefix.length));
      if (event === "on_authenticated") {
        amy.clientId = payload.client_id;
        amy.emit("on_user_postback", {...start, client_id: amy.clientId});
        amy.emit("join_room", amy.clientId);
      } else if (event === "on_bot_message" && !amy.greeted) {
        amy.greeted = true;  // The greeting.
        amy.last = Date.now();
        finish(null);
      } else if (event === "on_bot_message") {
        for (const block of payload.data || []) {
          if (block.type === "text") amy.groups.set(block.group_id || amy.groups.size, block.value);
        }
        amy.last = Date.now();
      }
    }
  };
  ws.onerror = () => { amy.error = "websocket error"; finish(amy.error); };
  const started = Date.now();
  const timer = setInterval(() => { if (Date.now() - started > timeoutMs) finish("timeout"); }, 250);
})"""

# Runs in the page: one turn on the open connection; resolves once the reply went quiet.
_SEND_JS = r"""async ([start, message, timeoutMs, quietMs]) => new Promise((resolve) => {
  const amy = window.__amy;
  amy.groups.clear();
  amy.last = Date.now();
  const {data: _, data_payload: __, ...ids} = start;
  setTimeout(() => amy.emit("on_user_message", {...ids, client_id: amy.clientId, data: message, timestamp: Date.now()}), 1500);
  const started = Date.now();
  const timer = setInterval(() => {
    const finish = (error) => { clearInterval(timer); resolve({error, groups: [...amy.groups.values()]}); };
    if (amy.error) finish(amy.error);
    else if (amy.groups.size && Date.now() - amy.last > quietMs) finish(null);
    else if (Date.now() - started > timeoutMs) finish(amy.groups.size ? null : "timeout");
  }, 250);
})"""


class VietjetBot(ChatBot):
    name = "vietjet"

    def __init__(self, chat_url=CHAT_URL, timeout=90.0, headless=True, page_factory=fresh_page, step_timeout=30.0):
        self.chat_url = chat_url
        self.timeout = timeout
        self.headless = headless
        self.page_factory = page_factory
        self.step_timeout = step_timeout

    def _open(self, page):
        page.set_default_timeout(self.step_timeout * 1000)
        url, start = self._widget_session(page)
        result = page.evaluate(_OPEN_JS, [url, NAMESPACE, start, int(self.timeout * 1000)])
        if result["error"]:
            raise BotError(f"Amy did not answer: {result['error']}.")
        return start

    def _send(self, page, start, message):
        started = time.monotonic()
        result = page.evaluate(_SEND_JS, [start, message, int(self.timeout * 1000), QUIET_MS])
        if result["error"]:
            raise BotError(f"Amy did not answer: {result['error']}.")
        text = "\n".join(g.strip() for g in result["groups"] if g and g.strip())
        if not text:
            raise BotError("Amy sent an empty answer.")
        return text, int((time.monotonic() - started) * 1000)

    def _close(self, page, start):
        try:
            page.evaluate("() => { if (window.__amy) window.__amy.ws.close(); }")
        except Exception:
            pass  # The page is closed right after anyway.

    def _widget_session(self, page):
        """Open the real widget and capture its socket URL and Start postback."""
        page.add_init_script(_CAPTURE_JS)
        try:
            page.goto(self.chat_url, wait_until="domcontentloaded", timeout=60_000)
            launcher = page.locator("#prime")
            launcher.wait_for(state="attached")
            page.wait_for_timeout(3_000)  # Let the widget finish initialising.
            page.evaluate(
                """() => { for (const id of ["prime", "aip-chat-box", "aip-chat-window"]) {
                     const e = document.getElementById(id); if (e) e.style.zIndex = 2147483647; } }"""
            )
            box = launcher.bounding_box()
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        except Exception as exc:
            raise BotError(f"Could not open the Vietjet chat widget: {str(exc).splitlines()[0]}") from exc
        deadline = time.monotonic() + self.step_timeout
        while True:
            session = page.evaluate("() => window.__vinbase")
            if session and session.get("start"):
                return session["url"], session["start"]
            if time.monotonic() > deadline:
                raise BotError("The Vietjet chat widget did not connect; the page may have changed.")
            page.wait_for_timeout(250)
