# browser-bots

用真的瀏覽器（Playwright + Chromium）操作網頁聊天機器人，再包成 **OpenAI 相容 API**，讓 llm-bias-pipeline 當成 Target LLM 使用。適用於沒有可直接呼叫的 HTTP API、只能透過網頁介面對話的機器人。

```text
llm-bias-pipeline backend ──OpenAI SDK──▶ browser-bots :8769/<bot>/v1 ──Chromium──▶ 機器人網頁
```

| Bot | Provider | Base URL | 狀態 |
|---|---|---|---|
| Virgin Atlantic Concierge AI | `virgin` | `http://127.0.0.1:8769/virgin/v1` | 可用 |
| Finnair Sisu | `finnair` | `http://127.0.0.1:8769/finnair/v1` | 可用 |
| 華航 AI 客服 | `chinaairlines` | `http://127.0.0.1:8769/chinaairlines/v1` | 可用 |
| Malaysia Airlines Mavis（Ada） | `malaysia` | `http://127.0.0.1:8769/malaysia/v1` | 可用 |
| Philippine Airlines myPAL（Ada） | `philippine` | `http://127.0.0.1:8769/philippine/v1` | 可用 |
| Vietjet Amy | `vietjet` | `http://127.0.0.1:8769/vietjet/v1` | 可用 |
| Volaris Ari | — | — | 暫緩：程式（`volaris.py`）已寫好並實測成功，但網站在數次自動化造訪後對自動化瀏覽器回空白頁，未註冊 |
| Priceline Penny | — | — | 暫緩：網站以 PerimeterX 封鎖自動化瀏覽器（403） |
| Air India AI Agent | — | — | 暫緩：網站以 Akamai 封鎖自動化瀏覽器（HTTP/2 連線被切斷） |

## 安裝與啟動

```bash
uv sync
PLAYWRIGHT_BROWSERS_PATH=.browsers uv run playwright install chromium   # 只需一次，約 650MB
uv run uvicorn browser_bots.app:app --host 127.0.0.1 --port 8769
```

根目錄的 `start_services.sh` 會自動啟動它，等 `/health` 就緒後才啟動 Django。

## API

| Method | Path | 說明 |
|---|---|---|
| GET | `/health` | `{"status": "ok", "bots": [...]}` |
| GET | `/<bot>/v1/models` | 只有一個模型，名稱同 bot |
| POST | `/<bot>/v1/chat/completions` | 取最後一則 `user` 訊息去問機器人，回傳 OpenAI chat completion 格式 |
| POST | `/<bot>/v1/conversation` | 多輪對話：遇到反問時以固定訊息回覆（見下） |

`temperature`、`top_p`、`max_tokens` 會被忽略。機器人出錯（頁面改版、逾時、無法開啟）時回 `502`，backend 會依 `TARGET_LLM_MAX_RETRIES` 重試。

`POST /<bot>/v1/conversation` 在**同一個 session** 內進行多輪對話（整段對話算一次限速呼叫）：

```json
{"question": "...", "follow_up_reply": "...", "max_turns": 5, "follow_up_patterns": ["請問.*艙等", "which class"]}
```

- 先送 `question`；只要最新回答符合任一 `follow_up_patterns`（Python regex，不分大小寫，`re.search`）且輪數 < `max_turns`（1–10，預設 5），就送出 `follow_up_reply`，再讀下一則回答。每輪的回答只含使用者該則訊息之後的新訊息。
- 回應：`{"turns": [{"user", "assistant", "latency_ms", "follow_up"}], "ended": "answered" | "max_turns", "latency_ms"}`。`follow_up` 表示該則回答是否符合 pattern；最後一則仍符合時 `ended` 為 `max_turns`；`latency_ms` 為各輪加總。
- 輸入錯誤（缺欄位、空字串、`max_turns` 超出範圍、regex 無效）回 `400`；機器人出錯回 `502`。

## 行為

- **每題都開新的瀏覽器**：不保留 cookie 或對話紀錄，前一題不會影響下一題。`/conversation` 的各輪在同一個頁面內進行。
- **限速**：同一個 bot 的請求排隊，兩次提問的開始時間至少間隔 `BROWSER_BOTS_MIN_INTERVAL` 秒（預設 3）。
- **Virgin Atlantic**：
  - 自動點過導覽頁的「Next」，勾選「I understand and accept the conditions of carriage and privacy policy」（專案負責人已同意條款），再按「Start a chat」。勾選時點的是方框本身，不是文字（文字裡有條款連結，點到會開新分頁而沒有勾選）。
  - 答案取自 `[data-role=assistant]`；出現讚/倒讚按鈕（`message-actions-container`）且文字 2 秒內不再變動，才視為回答完成。
  - 答案下方的建議連結（例如「What is my checked in baggage allowance?」）不算進答案。
  - 新版會先串流一段招呼語；招呼語串流中按送出只會中斷它，所以要等招呼語完成（出現讚／倒讚，或 8 秒沒變化）才送出問題，送出後確認輸入框已清空。
  - 讚／倒讚偶爾不會出現，所以答案 8 秒沒有變化也視為完成。
  - 每題約 15–20 秒（含開瀏覽器）。
- **Finnair Sisu**：
  - 開 `https://www.finnair.com/en`，按「Allow all」接受 cookie，點右下角 `#chat-help-button` →「Chat with us」。
  - 填寫聊天前表單（名、姓、Email，「是否與既有訂位有關」選 No），再按「Start the chat」。表單內容由 `FINNAIR_*` 環境變數設定。
  - 聊天在 `finnair.my.site.com` 的 Salesforce Embedded Messaging iframe 裡。等 Sisu 打完招呼後才送出問題，招呼語不算進答案。
  - Sisu 可能分好幾則訊息回答：收集問題之後所有 `.embedded-messaging-inbound-chat-message`，等 `.chat-typing-indicator` 消失且 3 秒內沒有新訊息，才視為回答完成，各則以換行串接。
  - Sisu 常先反問（例如「Do you already have a booking?」或要航線、艙等）；`/chat/completions` 每題只問一輪，反問本身就是回傳的答案。
  - 每題約 25–35 秒（含開瀏覽器與填表）。
- **華航 AI 客服**（`browser_bots/chinaairlines.py`）：
  - 直接開 `calaics01.china-airlines.com/cichatbot/chatindexFrame.aspx`，聊天是同網域 iframe `chatindex.aspx` 裡的 Microsoft Bot Framework WebChat。
  - 開場會陸續送三則訊息（歡迎、使用須知、最新消息），等 6 秒沒有新訊息才送出問題。
  - 答案取 `.wc-message-from-bot .format-markdown`；建議問題按鈕與「這則回覆是否對您有幫助」不算進答案。出現回饋區塊或 8 秒沒變化就視為完成。
- **Malaysia Airlines Mavis／Philippine Airlines myPAL**（`browser_bots/ada.py`，同一個 `AdaBot` 類別）：
  - 兩家都用 Ada，直接開 `https://<handle>.ada.support/chat/`（`malaysiaairlines`、`philippineairlines`），不用經過航空公司首頁。
  - 聊天在網址含 `/app/index.html` 的 iframe 裡；答案取 `[role=log] .ada-markdown`（不含使用者訊息與建議按鈕），等招呼語結束才送出。
  - 答案可能分多則，5 秒沒有新內容就視為完成。
  - 每題約 10–20 秒。
- **Vietjet Amy**（`browser_bots/vietjet.py`，VinBigdata 的聊天元件）：
  - 開 `https://www.vietjetair.com/en`。啟動鈕 `#prime` 被頁面內容蓋住，先調高它的 z-index 再點開。
  - 元件自己的輸入框不接受自動化輸入，所以改成：用 init script 記下元件連到 `cloud.vinbase.ai` 的 socket.io 網址和它送出的 `Start` postback（含 agent／channel id 與訪客帳號），再從頁面內另開一條連線，照元件的協定送 `Start`、`join_room`、等招呼語、送 `on_user_message`。
  - 這條連線存在 `window.__amy`，`/conversation` 的後續輪次沿用同一條連線，對話結束才關閉。
  - 答案以 `on_bot_message` 串流回來，每則重送該 `group_id` 目前為止的全文；取每個 group 的最後版本，6 秒沒有新內容就視為完成。
  - 只支援英文與越南文，其他語言會回「Amy currently supports English and Vietnamese only」。
  - 每題約 12–15 秒。
## 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `BROWSER_BOTS_MIN_INTERVAL` | `3` | 同一 bot 兩次提問之間的最少秒數 |
| `BROWSER_BOTS_TIMEOUT_SECONDS` | `90` | 等待一則完整回答的上限 |
| `BROWSER_BOTS_HEADLESS` | `1` | 設 `0` 會顯示瀏覽器視窗，方便除錯 |
| `FINNAIR_FIRST_NAME` | `Research` | Finnair 聊天前表單的名 |
| `FINNAIR_LAST_NAME` | `Tester` | Finnair 聊天前表單的姓 |
| `FINNAIR_EMAIL` | `research@example.com` | Finnair 聊天前表單的 Email |

## 新增一個 bot

1. 在 `browser_bots/` 新增一個繼承 `base.ChatBot` 的類別，實作 `_open(page) -> state`（開啟聊天）與 `_send(page, state, message) -> (answer, latency_ms)`（送一則訊息、只讀新回答），失敗時拋 `BotError`；`ask` 與 `converse` 由 `ChatBot` 提供。
2. 在 `app.py` 的 `default_bots()` 註冊名稱。
3. 用離線的模擬頁面寫測試（參考 `tests/virgin_fixture.html`），不要讓測試連到真的網站。
4. 在 backend 的 `CLIENTS` / `KEYLESS_PROVIDERS` 和 frontend 的 `PROVIDER_OPTIONS` 加上新的 provider。

## 測試

```bash
uv run pytest
```

測試使用 `tests/*_fixture.html` 模擬各網站的頁面流程，會真的開 Chromium，但不會連到外部網站。
