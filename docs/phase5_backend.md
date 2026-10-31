# 第五階段，把分析流程接成能保存案件的後端

## 這一階段完成什麼

前一版能用命令列（Command Line Interface，CLI）問問題，這一版加入應用程式介面（Application Programming Interface，API），讓之後的網頁能上傳圖片、送出問題，再從同一個案件查回結果。

例如我建立「瓶底外觀檢查」案件，上傳一張瓶子照片，系統先回傳執行編號，等分析完成後，就能用這個編號讀取分數、模型版本與熱圖，關掉服務再開啟也能取回紀錄。

這一階段沒有需要建立的帳號或下載的資料，套件已裝進專案虛擬環境（Virtual Environment），圖片分析在本機執行，代理問答沿用前一階段的 Groq 設定。

## 完成範圍與驗證結果

| 項目 | 本版成果 |
|---|---|
| 案件與圖片 | 建立案件、列出案件、上傳與讀取圖片 |
| 分析與問答 | 串接現有圖片工具與 Groq 代理，保存問題、回答、引用與工具紀錄 |
| 背景工作（Background Job） | 單一工作執行緒，同時執行與等候合計最多四筆 |
| 重送保護（Idempotency） | 同案件、同請求編號與內容，回傳原本的執行紀錄 |
| 報告草稿（Report Draft） | 從有回答的成功代理執行建立快照，保存版本與確認時間 |
| 持久保存（Persistence） | 重新啟動後可取回案件、圖片與執行結果 |
| 中斷處理 | 啟動時把未完成工作標記失敗，保留 `server_restarted` 原因 |
| 案件隔離（Case Isolation） | 圖片、執行與報告查詢都檢查案件關係 |
| 測試 | 後端 20 項，包含既有功能的完整測試共 70 項 |

實際圖片展示使用 `bottle/test/broken_large/000.png`，分數為 **19.47983169555664**，門檻為 **10.19447135925293**，判定為外觀異常，熱圖讀取成功，重送取得同一筆執行，服務重新啟動後結果一致。

本次展示透過行程內測試用戶端（ASGI TestClient）操作真正的 API 與 PatchCore 推論，外部語言模型呼叫次數為 **0**，本次沒有新增模型準確率評估，也沒有重新訓練或調整門檻。

問答、報告版本、失敗與容量限制由離線替身（Test Double）驗證，第四階段的 Groq 真實執行紀錄保留在原位置，本階段沒有新增 Groq 線上問答品質數字。

## 怎麼開啟

在 VS Code 開啟專案資料夾，再於終端機執行以下指令。

```bash
cd '/Users/chelsietao/vscode/InspectRAG Agent'
.venv/bin/python -m uvicorn app.backend:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

啟動後開啟 [互動介面文件（Swagger UI）](http://127.0.0.1:8000/docs)，可展開每個操作，按 `Try it out` 填寫欄位，再按 `Execute` 送出。

服務綁定本機位址，適用目前的單人開發環境，尚未加入登入、使用者權限與公開部署設定，執行時請維持單一工作程序（Worker）。

如果是重新安裝環境，使用專案的 Python 3.12 虛擬環境安裝下列依賴套件，圖片、模型、索引與 Groq 金鑰則沿用前幾階段的設定。

```bash
.venv/bin/python -m pip install -r requirements-backend.txt
```

完整環境版本另外保存在 `requirements-backend.lock.txt`，目前驗證環境為 macOS，單程序鎖使用 `fcntl`，Windows 環境尚未支援。

## 照著做一個案件

### 1. 建立案件，取得案件編號

呼叫 `POST /cases`，填入下列內容，回傳的 `id` 就是後面路徑中的 `case_id`。

```json
{"title": "瓶底外觀檢查"}
```

### 2. 上傳圖片，取得圖片編號

呼叫 `POST /cases/{case_id}/images`，選取本機 `bottle/test/broken_large/000.png`，回傳的 `id` 就是後面使用的 `image_id`。

圖片接受 PNG 與 JPEG，檔案上限為 10 MiB，像素總數上限為 1,600 萬，系統會檢查解碼結果、轉為 RGB PNG，再以系統產生的編號保存。

原始檔名只用於上傳，儲存路徑由伺服器建立，圖片不會依使用者提供的檔名寫進任意資料夾。

### 3. 送出圖片分析，取得執行編號

呼叫 `POST /cases/{case_id}/runs`，把剛才的圖片編號填進 `image_id`，HTTP 202 表示已接受工作，結果要透過查詢取得。

```json
{
  "kind": "analysis",
  "image_id": "填入圖片編號",
  "request_key": "bottle-analysis-001"
}
```

執行狀態依序為待處理（Pending）、執行中（Running）與成功（Succeeded）或失敗（Failed），上傳完成本身不會開始推論，也不會呼叫外部語言模型。

### 4. 查詢結果與熱圖

呼叫 `GET /cases/{case_id}/runs/{run_id}`，成功時可以讀取 `result.score`、`result.threshold` 與 `result.is_anomalous`，熱圖位於 `GET /cases/{case_id}/runs/{run_id}/heatmap`。

異常分數（Anomaly Score）用來比較目前模型的門檻，數值不代表瑕疵機率，也無法證明瑕疵成因或產品是否符合出貨標準。

### 5. 在同一案件提問

呼叫同一個 `POST /cases/{case_id}/runs`，把 `kind` 改成 `agent`，這時才會使用前一階段設定的 Groq 工具呼叫（Tool Calling）。

```json
{
  "kind": "agent",
  "question": "請分析這張瓶子照片，找正常參考圖片，說明異常分數的限制並附上來源",
  "image_id": "填入圖片編號",
  "request_key": "bottle-question-001"
}
```

如果只問文件問題，可以省略 `image_id`，例如詢問「異常分數能解讀成瑕疵機率嗎」，系統會沿用既有文件搜尋流程。

每次問答的模型與工具次數仍受第四階段設定限制，程式沒有自動重試或付費供應商備援，遇到免費額度限制（Rate Limit）會保存失敗原因，同一個請求編號重送也不會重新呼叫模型。

Groq 帳號需維持免費方案，程式無法透過模型介面驗證帳號計費層級，這一階段沒有新增付費服務。

### 6. 建立與確認報告

呼叫 `POST /cases/{case_id}/reports`，填入已完成且回答狀態為 `answered` 的代理執行編號，系統會把回答、引用、工具紀錄與模型資訊保存成報告快照（Snapshot）。

```json
{"run_id": "填入有回答的代理執行編號"}
```

接著核對草稿內容，再呼叫 `POST /cases/{case_id}/reports/{report_id}/confirm`，填入下列內容，系統才會寫入確認時間。

```json
{"accepted": true}
```

確認同一份報告多次會保留第一次的確認時間，建立新的草稿則會產生下一個版本，確認動作代表使用者完成審閱，內容支持度仍需依引用資料判斷。

## 介面列表

| 方法 | 路徑 | 用途 |
|---|---|---|
| GET | `/health` | 檢查服務與資料庫，這個操作不測試外部模型 |
| POST / GET | `/cases` | 建立與列出案件 |
| GET | `/cases/{case_id}` | 讀取案件 |
| POST / GET | `/cases/{case_id}/images` | 上傳與列出圖片 |
| GET | `/cases/{case_id}/images/{image_id}` | 讀取保存的圖片 |
| POST / GET | `/cases/{case_id}/runs` | 送出工作與讀取案件執行紀錄 |
| GET | `/cases/{case_id}/runs/{run_id}` | 讀取狀態、結果與錯誤 |
| GET | `/cases/{case_id}/runs/{run_id}/heatmap` | 讀取熱圖 |
| POST / GET | `/cases/{case_id}/reports` | 建立與列出報告草稿 |
| GET | `/cases/{case_id}/reports/{report_id}` | 讀取報告版本 |
| POST | `/cases/{case_id}/reports/{report_id}/confirm` | 確認已審閱的報告 |

## 遇到錯誤時怎麼看

| 狀況 | 結果 | 你可以怎麼做 |
|---|---|---|
| 案件不存在或圖片屬於另一案件 | HTTP 404 | 核對案件與圖片編號 |
| 同請求編號搭配不同內容 | HTTP 409 | 新工作使用新的 `request_key` |
| 同請求編號搭配相同內容 | HTTP 202，回傳同一筆執行 | 繼續查原本的 `run_id` |
| 圖片超出檔案或尺寸限制 | HTTP 413 | 縮小圖片後再上傳 |
| 圖片損毀或格式不支援 | HTTP 415 | 換成可解碼的單張 PNG 或 JPEG |
| 問題空白、欄位錯誤或缺少圖片 | HTTP 422 | 核對互動文件的欄位 |
| 四筆工作正在執行或等候 | HTTP 429，`local_queue_full` | 等前一筆結束後再送出新工作 |
| Groq 免費額度不足 | 執行失敗，`rate_limited` | 等額度恢復，再以新請求編號提出工作 |
| 金鑰未設定 | 執行失敗，`credential_not_configured` | 在本機環境補上既有 Groq 金鑰 |
| 服務啟動前有未完成工作 | 執行失敗，`server_restarted` | 查閱紀錄後決定是否另開新工作 |
| 從其他網站或主機名稱存取 | HTTP 403 | 使用本機 `localhost` 或 `127.0.0.1` |

後端不會把原始例外訊息回傳給使用者，已知供應商錯誤保留經過整理的錯誤碼，其餘失敗以 `execution_failed` 記錄，避免金鑰與內部錯誤內容進入回答。

## 資料存在哪裡

```text
artifacts/backend/
├── inspectrag.sqlite3
├── server.lock
├── images/<image_id>.png
└── runs/<run_id>/analysis/
    ├── result.json
    └── heatmap.png
```

資料庫使用 Python 內建的 SQLite，透過外鍵（Foreign Key）維持案件關係，使用交易（Transaction）與唯一限制（Unique Constraint）處理重送與報告版本，目前資料結構版本為 `PRAGMA user_version = 1`。

資料表包含 `cases`、`images`、`runs` 與 `reports`，回答與工具軌跡以 JSON 快照保存，文件段落仍由前一階段的知識庫管理，本階段沒有引入 SQLAlchemy 或獨立資料庫伺服器。

同一個資料目錄只允許一個服務程序，啟動時會取得檔案鎖（File Lock），避免第二個服務把正在執行的工作誤認為中斷工作。

備份時先停止服務，再複製整個 `artifacts/backend/`，資料庫與圖片需要一起保存，這些檔案受 Git 忽略規則保護，沒有上傳 GitHub。

## 案件歷史與記憶的界線

這一版保存每次問題、圖片編號、結果、引用與工具紀錄，能從案件查回歷史，API 也會拒絕把另一個案件的圖片或報告拿來操作。

代理每次執行都建立新的工具狀態，目前沒有把歷史回答加入下一次的模型上下文（Context），所以「剛才那個」這類追問仍需要提供圖片編號或在問題中說清楚，跨輪摘要與已確認事實的記憶管理（Memory Management）留到後續實作。

本版單筆代理執行與 CLI 共用既有上下文預算，既有引用檢查只驗證本輪證據編號，主張支持度（Claim Support）仍需人工核對。

## 怎麼重跑驗證

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
.venv/bin/python scripts/demo_backend.py
```

前兩個指令檢查程式行為與套件依賴，第三個指令會建立新的展示資料夾，上傳固定瓶子圖片、執行本機推論、取回熱圖，再重新開啟服務確認資料仍在，整段流程不呼叫 Groq。

公開的展示結果位於 [`evaluation/backend_v1/demo_summary.json`](evaluation/backend_v1/demo_summary.json)，完整後端測試在 `tests/test_backend.py`，正式驗證紀錄與實作雜湊位於 [`evaluation/backend_v1/summary.json`](evaluation/backend_v1/summary.json)。

## 使用限制與下一步

這一版適用於本機單人展示，尚未完成登入、分頁、大量資料清理、可取消工作、持久化工作佇列、雲端部署與多程序擴充，服務重新啟動時會標記中斷工作，不會重新送出模型請求。

圖片上傳檢查發生在框架完成檔案接收之後，公開部署還需要反向代理的請求大小與逾時限制，目前的主機與來源檢查也無法取代使用者驗證。

下一階段會把這些介面接上網頁工作台（Web Dashboard），讓案件、原圖、熱圖、參考圖與回答能在畫面上操作，案件摘要記憶、MCP、容器與持續整合（CI）則依各自的驗收條件繼續完成。

## 參考文件

- [FastAPI 測試文件](https://fastapi.tiangolo.com/tutorial/testing/)，採用測試用戶端驗證 API 行為。
- [Python SQLite 文件](https://docs.python.org/3.12/library/sqlite3.html)，核對交易、參數綁定與資料庫操作。
