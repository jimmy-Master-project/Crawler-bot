# evaair-bot

把長榮航空網頁客服機器人（`bot.evaair.com` 的 wise webchat）包成 **OpenAI 相容 API**，讓 llm-bias-pipeline 把它當成 Target LLM（provider `evaair`）使用。

```text
llm-bias-pipeline backend ──OpenAI SDK──▶ evaair-bot :8768 ──HTTP──▶ bot.evaair.com
```

## 啟動

```bash
uv sync
uv run uvicorn evaair_bot.app:app --host 127.0.0.1 --port 8768
```

根目錄的 `start_services.sh` 會自動啟動它，並等 `/health` 就緒後才啟動 Django。

## API

| Method | Path | 說明 |
|---|---|---|
| GET | `/health` | `{"status": "ok"}` |
| GET | `/v1/models` | 只有一個模型 `evaair` |
| POST | `/v1/chat/completions` | 取最後一則 `user` 訊息去問機器人，回傳 OpenAI chat completion 格式 |
| POST | `/v1/conversation` | 多輪對話：遇到反問時以固定訊息回覆（見下） |

`temperature`、`top_p`、`max_tokens` 等參數會被忽略（聊天機器人沒有這些設定）。機器人出錯（session 失效、空答案、連線失敗）時回 `502`，backend 的 OpenAI SDK 會依 `TARGET_LLM_MAX_RETRIES` 重試。

`POST /v1/conversation` 在**同一個 session** 內進行多輪對話（整段對話算一次限速呼叫）：

```json
{"question": "...", "follow_up_reply": "...", "max_turns": 5, "follow_up_patterns": ["請問.*艙等", "which class"]}
```

- 先送 `question`；只要最新回答符合任一 `follow_up_patterns`（Python regex，不分大小寫，`re.search`）且輪數 < `max_turns`（1–10，預設 5），就送出 `follow_up_reply`，再讀下一則回答。每輪的回答只含使用者該則訊息之後的新訊息。
- 回應：`{"turns": [{"user", "assistant", "latency_ms", "follow_up"}], "ended": "answered" | "max_turns", "latency_ms"}`。`follow_up` 表示該則回答是否符合 pattern；最後一則仍符合時 `ended` 為 `max_turns`；`latency_ms` 為各輪加總。
- 輸入錯誤（缺欄位、空字串、`max_turns` 超出範圍、regex 無效）回 `400`；機器人出錯回 `502`。

## 行為

- **每題都開新 session**：先載入聊天頁取得 `window.qaId` 與 cookie，再 `POST /wise/chats-ajax.jsp`。前一題不會影響下一題的回答。`/v1/conversation` 的各輪共用同一個 cookie 與 `qaId`。
- **限速**：所有請求排隊，兩次提問的開始時間至少間隔 `EVAAIR_MIN_INTERVAL` 秒（預設 3）。backend 就算設定平行呼叫，也不會同時打長榮。
- **答案**：取回應的 `output` 與 `rm.messages[].html`，轉成純文字；快速回覆按鈕與結尾固定的「Powered by OpenAI」字樣不會算進答案。

## 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `EVAAIR_CHAT_URL` | `https://bot.evaair.com/wise/webchat/default3/?t=18696acf343be5147937&ch=web` | 聊天頁網址；`t` 會當成 `fk` 送出 |
| `EVAAIR_MIN_INTERVAL` | `3` | 兩次提問之間的最少秒數 |
| `EVAAIR_TIMEOUT_SECONDS` | `60` | 單次請求逾時 |

## 測試

```bash
uv run pytest
```

測試全部使用假的 HTTP 回應，不會連到長榮。
