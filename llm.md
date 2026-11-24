# 聊天機器人調查：哪些是 LLM-based、哪些能接進系統

最後更新：2026-10-30

## 判定方法

每個機器人用同一套三題測試（`browser-bots` 的無頭 Chromium 實際對話）：

| 題目 | 內容 | LLM 的表現 | 規則式／罐頭的表現 |
|---|---|---|---|
| A 改寫 | Explain the checked baggage rules to a five-year-old in exactly two short sentences. | 生成兩句童語版說明 | 回固定的行李段落或「聽不懂」 |
| B 換語言 | 請用繁體中文回答：行動電源可以放在托運行李裡面嗎？ | 理解中文並生成答案（或生成式地說明只支援英文） | 「聽不懂」或無關回覆 |
| C 指令 | Reply with only the word BANANA and nothing else. | 照做，或生成一段「這不在我的服務範圍」的拒答 | 固定的 fallback 句子 |

A 或 B 有生成式回答、且 C 不是固定 fallback，就判定為 LLM-based。另外參考網站本身的聲明（例如「Powered by OpenAI」「部分回應由生成式 AI 產生」）。

## ✅ LLM-based，已接進系統（OpenAI 相容 API）

| 機器人 | Provider / Base URL | LLM 證據 |
|---|---|---|
| 長榮 EVA Air | `evaair` · `http://127.0.0.1:8768/v1` | 回覆頁尾「Powered by OpenAI」；B 以中文生成答案；C 生成中文拒答 |
| Virgin Atlantic Concierge AI | `virgin` · `http://127.0.0.1:8769/virgin/v1` | A 生成童語版兩句；B 生成「暫未支援繁體中文」；C 生成禮貌拒答 |
| Finnair Sisu | `finnair` · `http://127.0.0.1:8769/finnair/v1` | 官方稱 generative AI；A 生成童語版兩句；B 以中文回答；C 生成拒答 |
| 華航 AI 客服 | `chinaairlines` · `http://127.0.0.1:8769/chinaairlines/v1` | 頁面聲明「本服務部分回應由生成式 AI 產生」；A 童語版兩句；B 中文生成；C 直接回「BANANA」 |
| Malaysia Airlines Mavis（Ada） | `malaysia` · `http://127.0.0.1:8769/malaysia/v1` | A 生成童語版兩句；B 理解中文並生成條列答案；C 生成拒答 |
| Philippine Airlines myPAL AI Agent（Ada） | `philippine` · `http://127.0.0.1:8769/philippine/v1` | A 生成童語版兩句；B「I can assist only in English」後仍生成答案；C 直接回「BANANA」 |
| Vietjet Amy（VinBigdata） | `vietjet` · `http://127.0.0.1:8769/vietjet/v1` | 回答以 token 串流；A 生成童語版兩句（「You can bring a big bag on the plane, but it can't be heavier than 32 kilograms…」）；B 生成「Amy currently supports English and Vietnamese only」；C 生成拒答 |

網址：

- 長榮：https://bot.evaair.com/wise/webchat/default3/?t=18696acf343be5147937&ch=web
- Virgin Atlantic：https://www.virginatlantic.com/concierge-ai/chat
- Finnair：https://www.finnair.com/en （右下角 chat，介紹頁 https://www.finnair.com/en/bluewings/world-of-finnair/meet-sisu--the-ai-assistant-that-actually-listens-4261942 ）
- 華航：https://calaics01.china-airlines.com/cichatbot/chatindexFrame.aspx （原本列在罐頭，2025 年已升級為生成式 AI）
- Malaysia Airlines：https://malaysiaairlines.ada.support/chat/ （官網 https://www.malaysiaairlines.com 的 AskMH →「Chat with MAVIS」）
- Philippine Airlines：https://philippineairlines.ada.support/chat/ （官網 https://www.philippineairlines.com 右下角）
- Vietjet：https://www.vietjetair.com/en （右下角吉祥物；只支援英文與越南文）

## ⚠️ LLM-based，但目前沒有接

| 機器人 | 網址 | 狀況 |
|---|---|---|
| Volaris Ari（Salesforce Agentforce） | https://www.volaris.com/ （「Ask me anything」） | A 生成童語版兩句（「Grown-ups at the airport will help you」）；C 生成拒答，且英文提問有時用西班牙文回答 → LLM。`browser-bots/browser_bots/volaris.py` 已寫好並實測成功過，但連續自動化造訪幾次後，網站開始對自動化瀏覽器回空白頁（curl 仍正常），冷卻一段時間後仍未恢復，所以沒有註冊進服務。之後恢復可以直接接上 |
| AirAsia Ask Bo | https://www.airasia.com/en/gb/ （「Ask Bo」按鈕） | C 生成式拒答且每次措辭不同 → LLM；但 A、B 一律回「I couldn't retrieve the FAQ information at the moment」，後端查資料功能壞掉，答案沒有實驗價值。之後恢復可以再接 |
| Vietnam Airlines NEO（FPT.AI） | https://www.vietnamairlines.com/tw/en/ （「Chat with NEO」） | 頁面自稱「NEO is powered by AI」，但開始對話前必須勾選「I consent to Vietnam Airlines using all data from my conversation with NEO」。自動代為同意資料使用被安全檢查擋下，**還沒有實測**，需要專案負責人決定是否同意 |
| 星宇航空 AI Agent (BETA) | https://chatbot.jx-starlux.com/web-chats/cd0daad8-447b-4971-b009-4d7199c92ba1 | LLM-based（受嚴格限制的 RAG LLM），但只支援繁體中文；本研究文本皆為英文，已從系統移除 |

## ❌ 不是 LLM-based

| 機器人 | 網址 | 證據 |
|---|---|---|
| Air New Zealand Oscar | https://www.airnewzealand.com/ （「Ask Oscar」） | A 回固定的行李尺寸段落（不是兩句童語）；B、C 都回「Sorry, I'm not sure what you're asking…」加建議按鈕 → 意圖辨識式 |
| Air India Express Tia（Avaamo） | https://www.airindiaexpress.com/ （「Open Tia」） | A 回 Domestic／International 選單；C 回「Hmm, I wish I could answer that right now but I'm still learning」→ 意圖辨識式 |
| Virgin Australia（Genesys） | https://www.virginaustralia.com/au/en/help/ （右下角紅色聊天鈕） | A 回「I think you want information about your baggage allowance, is that right? Yes／No」；B、C 回 Yes／No 選單，C 還提議轉真人 → 意圖辨識式 |
| JetBlue（ASAPP） | https://www.jetblue.com/contact-us （「Start a chat」） | 「以 PINEAPPLE 開頭」被回「I'm having trouble processing that request」；西班牙文提問跳固定西文選單；童語版、條列三點都拒答，只有寵物問題給出兩句固定內容 → 意圖／檢索式 |
| 立榮航空 UNI Air（Intumit wise，與長榮同平台） | https://unichat.uniair.com.tw/wise/webchat/default/?t=14d724b778af3d474697 | 只支援繁中；海盜口吻、童語、條列三點都回固定 FAQ，「香蕉」回「我沒有找到最適合的答案」；只有一題出現像生成的摘要 → FAQ 檢索為主 |
| 桃園機場智慧客服 | https://www.faninsights.io/tia_chatbot/chatbot/ | A 回固定 FAQ「因各航空公司行李託運規定不同…」加「類似問題」；C 回「抱歉！我無法回答您的問題」→ FAQ 檢索式 |
| 中華電信 Q寶 | https://chat.cht.com.tw/?r=1&r=1&access_token= | 輸入限 20 字；A 回「Q寶建議您換個方式發問」加推薦連結；B 只給「For English Service」連結 → 關鍵字式 |
| 星展 DBS i客服 | https://chatbanking.dbs.com/chat/tw/index.html?trigger=35ba97cf-f8c0-4029-b4ac-51c192009e7e | A、B 回信用卡推廣選單；C 回「我現在還不能理解您說的問題」→ 選單／意圖式 |
| 人事總處智慧客服 | https://dgpa.qbicloud.com/webchat-dgpa/index.html | 三題都回同一句「很抱歉，沒辦法回覆您的問題，智慧客服目前以人事法規為主」 |
| 雲端發票智慧客服 | https://robot.einvoice.nat.gov.tw/wise/webchat/default/?t=463a31fc3e5ab3f4cf99 | A 匹配到不相干的「驗證碼錯誤無法登入」FAQ；C 回「我沒有找到最適合的答案」→ FAQ 檢索式 |

## 🚫 被防爬擋住，無法驗證也無法自動化

- 台北捷運智慧客服（https://chatweb.metro.taipei/wise/webchat/default/chat.jsp?t=oC56ls9rDQCvE6pSN%2B9i0w%3D%3D&lang=en ）：「點我開始使用」是 Google reCAPTCHA 驗證，自動化瀏覽器無法通過。與雲端發票同為 Intumit wise 平台，推測為罐頭式，但無法實測。

自動化瀏覽器開首頁就被擋（Akamai／PerimeterX／Cloudflare 等）。部分公開資料聲稱是生成式 AI，但無法實測：

| 機器人 | 網址 | 被擋情形 | 公開資料 |
|---|---|---|---|
| Priceline Penny | https://www.priceline.com/penny | 403，PerimeterX「Press & Hold」 | 生成式 AI 旅遊助理 |
| Air India AI.g | https://www.airindia.com/in/en/contact-us/AI-Agent-capabilities.html | HTTP/2 連線被切斷（Akamai），curl 也一樣 | 生成式 AI 助理（亦有 WhatsApp 版） |
| Korean Air AI Chatbot | https://www.koreanair.com/ | HTTP/2 連線被切斷 | 2026-02 上線的生成式 AI 客服，13 種語言 |
| IndiGo 6Eskai | https://www.goindigo.in/ | 頁面回空白 | 官方稱基於 GPT-4 |
| Cebu Pacific（Ada） | https://www.cebupacificair.com/ | 410 | 2026-02 與 Ada 合作的生成式 AI Agent |
| Delta Concierge | https://www.delta.com/ | 444 Access Denied | 生成式 AI 助理 |
| Qatar Airways Sama | https://www.qatarairways.com/ | 403 Access Denied | AI 數位空服員 |
| Aeroflot | https://www.aeroflot.ru/ru-en | 頁面回空白 | 2024 試行生成式 AI 客服 |

其他開首頁就被擋的航空／旅遊網站（未確認是否有 LLM 客服）：KLM、Air France、United、Cathay Pacific、Etihad、Turkish Airlines（連線被切斷）；Lufthansa、Emirates、Iberia、JAL、SAS、Thai Airways、Scoot、easyJet、Avianca、Pegasus、Klook、Air Arabia（403）；Expedia（429「Bot or Not?」）；Alaska（Client Challenge）；Wizz Air（Human Verification）；Trip.com（Verification 頁）；Hilton（逾時）；Singapore Airlines（維護頁）；Air Canada（美國版頁面 403）。

航空公司第二輪掃描（2026-10-30，只看航空）：

- 開首頁就被擋：Saudia、flydubai、Gulf Air、EgyptAir、El Al、Kuwait Airways、flynas、flyadeal、Riyadh Air、LATAM、Copa、Azul、Sun Country、Porter、Flair、Aer Lingus、ITA Airways、Norwegian、Icelandair、Eurowings、Swiss、Austrian、Brussels Airlines、Vueling、Transavia、Jet2、Aegean、airBaltic、Air Serbia、SunExpress、AJet、Asiana、Jeju Air、Jin Air、Peach、Zipair、Air China、Bangkok Airways、Jetstar、Fiji Airways、SriLankan、Garuda、South African、Air Astana。
- Oman Air：GenAI 聊天程式來自 `oman-airlines-prd.genai.igtx.in`，但這個主機從本機連不上（curl 也卡住，可能限地區），`<igt-chat-bot>` 元件始終是空的；頁面上另一個 `#chat-client` 啟動鈕是第三方舊元件，送出訊息完全沒有網路請求。無法驗證。
- Air Mauritius：只有同一個無作用的 `#chat-client` 第三方元件（和 Oman Air 的 data-username 相同），`#chatbot` 是空的。
- ANA：英文網站說明頁稱「Your questions will be answered automatically through our AI interface」，但英文與日文網站都找不到可開的聊天視窗（只有 Salesforce 表單與 FAQ 入口）。
- AirAsia support.airasia.com 的聊天也是 Ask Bo（C 回「BANANA」），換馬來西亞、新加坡、台灣站一樣回「couldn't retrieve the FAQ information」。
- Ethiopian 只有 Genesys 分析腳本、Uzbekistan Airways 是 Chatwoot 真人客服，不列入。
- 可開但首頁沒有聊天入口：Royal Jordanian、Kenya Airways、Royal Air Maroc、Aeromexico、Southwest、Hawaiian、Frontier、TAP、LOT、Condor、China Eastern、China Southern、Hainan Airlines、HK Express、Tigerair Taiwan、Akasa Air、SpiceJet。

能正常開、但首頁找不到聊天入口（第一輪）：JetBlue、ANA、Qantas、Agoda、Ryanair、WestJet（只有 Sprinklr 腳本，沒有可見入口）。

## 其他未驗證

- 台灣大哥大 little my（https://littlemy.taiwanmobile.com/loginPage?eservice=web&TA=null&M=null ）：需要登入門號帳號才能對話，未測。
- livechat.com.tw（戰國策 AI 客服系統）：是客服系統廠商的產品官網，不是企業實際客服，未測。
- VOXI（https://www.mobileworldlive.com/vodafone/vodafone-brand-voxi-claims-ai-chatbot-breakthrough/ ）：新聞稱是生成式 AI 客服，但 voxi.co.uk 被 Cloudflare 擋（403）。
- 星宇航空：首頁有 `apmichat` 元件，但北美英文版找不到聊天入口，尚未測。
- Booking.com、Hilton AI Planner：Booking 首頁可開但沒有聊天入口；Hilton 首頁逾時。

原本「罐頭」清單中的華航實測後是 LLM-based，已移到上面。環境部智慧客服（https://aics.moenv.gov.tw/Webhook/ ）實測也是 LLM-based（頁面聲明「本系統為語言模型生成」），但不是航空客服，已依專案範圍從系統移除；其餘都已重新驗證並分類在上面各節。

## 參考資料

- Korean Air 生成式 AI 客服：https://www.altexsoft.com/travel-industry-news/korean-air-launches-generative-ai-chatbot-across-web-and-app/
- IndiGo 6Eskai（GPT-4）：https://www.bqprime.com/technology/indigo-unveils-6eskai-a-web-mobile-ai-chat-assistant-powered-by-gpt-4
- Cebu Pacific × Ada：https://travelupdate.ph/cebu-pacific-leads-southeast-asia-carriers-utilizing-generative-ai-agent
- 華航 AI 客服升級生成式 AI：https://wantrich.chinatimes.com/news/20250522900272-420101
- Air India AI.g：https://www.thetechoutlook.com/new-release/software-apps/generative-ai-powered-virtual-travel-assistant-of-air-india-ai-g-is-now-available-on-whatsapp/
- Delta Concierge：https://www.ajc.com/news/business/meet-your-newest-ai-chatbot-delta-concierge/3GFA5DFBOBBXVCYHNT2SMWCHAA
- Virgin Atlantic Concierge：https://www.theregister.com/2025/12/23/like_a_virgin_concierge_planning/
- Hilton AI Planner：https://www.hospitality.today/article/hilton-launches-ai-assistant-for-hotel-discovery-and-stay-planning
- Ada 旅遊業客戶（Cebu Pacific、AirAsia、PAL）：https://www.ada.cx/case-study/industry/travel/
