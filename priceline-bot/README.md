# priceline-bot

把 Priceline Penny 的聊天 API 包成 **OpenAI 相容 API**，讓 llm-bias-pipeline 把它當成 Target LLM（provider `priceline`）使用。Penny 本身就有 HTTP API，所以這個服務不需要瀏覽器。

```text
llm-bias-pipeline backend ──OpenAI SDK──▶ priceline-bot :8770 ──HTTP──▶ www.priceline.com/penny
```

> 這個整合基於專案負責人與 Priceline 的研究合作（合約允許反向分析，IP 已列入白名單）。Penny 的 API 位在 PerimeterX 防爬之後，只有在白名單生效時才呼叫得到。

## 啟動

```bash
uv sync
uv run uvicorn priceline_bot.app:app --host 127.0.0.1 --port 8770
```

根目錄的 `start_services.sh` 會自動啟動它，等 `/health` 就緒後才啟動 Django。

## API

| Method | Path | 說明 |
|---|---|---|
| GET | `/health` | `{"status": "ok"}` |
| GET | `/v1/models` | 只有一個模型 `priceline` |
| POST | `/v1/chat/completions` | 取最後一則 `user` 訊息去問 Penny，回傳 OpenAI chat completion 格式 |

`temperature`、`top_p`、`max_tokens` 會被忽略。Penny 出錯時回 `502`，backend 會依 `TARGET_LLM_MAX_RETRIES` 重試。

## 已知的 Penny 請求格式

由前端側錄而來（`priceline_bot/client.py`）：

- `POST https://www.priceline.com/penny/api/chat`
- body 的 `messages` 是 OpenAI 風格：`[{"role":"user","content":[{"type":"text","text":"..."}]}]`，另帶 `pennysid` 與多個功能旗標。
- `pennysid` 是 Priceline 簽發的 JWT（內含 chatId），無法在本地產生，必須從網站取得。

## 還需確認的兩件事（client.py 內有 `NEEDS-CONFIRMATION` 標記）

目前還差兩項資訊，確認後這個服務才能端到端運作：

1. **如何取得一份新的 `pennysid`**：現在的做法是載入 `https://www.priceline.com/penny` 頁面、用正則從 HTML 抓 `pennysid`。若 Penny 其實是從另一支 bootstrap 端點取得，請改 `_new_pennysid`。
2. **回應格式**：`_parse_answer` 已同時處理「單一 JSON 文件」與「SSE / JSON-lines 串流」兩種常見形狀，但需要對照一筆真實回應確認答案文字放在哪個欄位。

確認方式：在白名單生效的機器上，用瀏覽器 DevTools（Network → Fetch/XHR）問 Penny 一題，看 `/penny/api/chat` 的回應 body，以及頁面載入時哪一筆請求帶回 `pennysid`。

## 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `PRICELINE_MIN_INTERVAL` | `3` | 兩次提問之間的最少秒數 |
| `PRICELINE_TIMEOUT_SECONDS` | `60` | 單次請求逾時 |

## 測試

```bash
uv run pytest
```

測試全部使用假的 HTTP 回應，不會連到 Priceline；涵蓋 JSON 與 SSE 兩種回應形狀的解析。
