# InspectRAG Agent｜影像檢驗與證據查詢工作台

結合影像異常偵測（Anomaly Detection）、檢索增強生成（Retrieval-Augmented Generation，RAG）與人工智慧代理（AI Agent），將圖片分析、文件查詢、案件追問與報告整理放在同一個工作台。

**[開啟互動展示](https://chelsietao.github.io/InspectRAG-Agent/)** · **[完整專案紀錄](README_DETAILED.md)**

公開展示提供預先計算的圖片、熱圖與問答範例，本機版本提供圖片上傳、模型分析與即時問答。

## 專案功能

圖片檢查產生的分數需要搭配方法說明與參考資料，InspectRAG Agent 將這些資訊接到同一個案件，讓使用者從查看結果、查詢來源走到報告確認。

| 功能 | 工作內容 |
|---|---|
| 圖片分析 | 使用 PatchCore 計算異常分數，顯示判斷門檻與異常熱圖（Heatmap） |
| 正常圖片檢索（Image Retrieval） | 從正常訓練圖片中找出三張參考圖，顯示來源與相似度 |
| 文件問答 | 結合語意搜尋與文字比對，從知識庫（Knowledge Base）檢索段落並產生附引用的回答 |
| 工具編排（Tool Orchestration） | 由代理呼叫圖片、文件與案件記憶工具，保存呼叫順序、參數與執行結果 |
| 案件記憶（Case Memory） | 保存歷史分析與使用者確認的觀察，讓追問引用前次紀錄 |
| 報告管理 | 將回答與證據保存成報告草稿，經使用者審閱後記錄版本與確認時間 |

例如上傳一張瓶子照片，先查看瓶口熱圖與正常參考圖片，再問「這個分數怎麼解讀」或「剛才的判斷門檻是多少」，回答會附上文件段落或歷史執行紀錄，供使用者核對。

## 操作畫面

![InspectRAG Agent 工作台，顯示原圖與異常熱圖](docs/images/dashboard/overview.png)

畫面中的產品圖片來自 MVTec AD，截圖來源與授權見[圖片說明](docs/images/dashboard/README.md)。

## 系統流程與技術

```text
網頁工作台 → FastAPI → 代理與工具 → 分析結果、引用與報告
                         ├─ PatchCore：異常分數與熱圖
                         ├─ 圖片檢索：正常參考圖片
                         ├─ 文件檢索：知識段落與來源
                         └─ 案件記憶：歷史工具結果與確認觀察
                    SQLite 保存案件、執行紀錄與報告版本
```

| 模組 | 使用技術與實作 |
|---|---|
| 影像分析 | Python、PyTorch、Anomalib、PatchCore、ResNet18 |
| 檢索系統 | Sentence Transformers、多語言 E5 向量模型、FAISS、文字比對與排名融合（Reciprocal Rank Fusion） |
| 代理問答 | Groq、工具呼叫（Tool Calling）、Pydantic 參數驗證、引用編號檢查 |
| 上下文管理（Context Management） | 每次工作保存上限 6,000 字元的證據快照，記錄來源執行與圖片範圍 |
| 後端與儲存 | FastAPI、SQLite、背景工作（Background Job）、重送保護（Idempotency） |
| 前端與展示 | HTML、CSS、JavaScript、GitHub Pages |
| 程式測試 | Python unittest、API 整合測試、Node.js 測試執行器 |

案件、圖片、工具結果與報告透過識別碼串接，同一請求重送會取回原執行紀錄，報告保留回答與證據的版本快照。

## 資料與驗證結果

影像使用 MVTec AD 的瓶子（bottle）類別，179 張正常圖片建立特徵庫，30 張正常圖片校準判斷門檻，83 張測試圖片用於評估。

| 項目 | 已記錄結果 |
|---|---|
| 影像級排序指標（Image AUROC） | 0.9960 |
| 像素級排序指標（Pixel AUROC） | 0.9665，評估解析度為 128 × 128 |
| 異常圖片檢出 | 63 張中找出 61 張 |
| 正常圖片誤報 | 20 張中誤報 0 張 |
| 程式測試 | 第七階段驗證共 118 項通過，包含 105 項 Python 與 13 項 JavaScript 測試 |

影像指標對應上述資料切分與實驗設定，完整數據見[視覺評估紀錄](docs/evaluation/vision_baseline_v1/metrics.json)，測試與案件記憶驗證見[測試摘要](docs/evaluation/case_memory_v1/summary.json)。

案件追問的實測以兩次模型呼叫讀回前次分數與門檻，工具流程為 `read_case_memory → submit_answer`，原始結果見[追問執行紀錄](docs/evaluation/case_memory_v1/live_followup.json)。

## 本機使用

本機環境完成資料、模型、索引與 Groq 設定後，在專案根目錄執行以下指令。

```bash
.venv/bin/python -m uvicorn app.backend:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

開啟 [本機工作台](http://127.0.0.1:8000/)，建立案件並上傳圖片，即可進行分析、搜尋參考圖片與問答，介面文件位於 [API Docs](http://127.0.0.1:8000/docs)。

環境與操作步驟依序見[資料準備](docs/phase1_setup.md)、[視覺模型](docs/phase2_vision.md)、[圖片與文件索引](docs/phase3_retrieval.md)、[代理設定](docs/phase4_agent.md)及[工作台操作](docs/phase6_dashboard.md)，案件記憶與追問見[操作說明](docs/phase7_memory.md)。

## 資料來源與方法

影像資料來自 [MVTec AD](https://www.mvtec.com/research-teaching/datasets/mvtec-ad)，依姓名標示、非商業性、相同方式分享 4.0（CC BY-NC-SA 4.0）使用，公開素材與衍生熱圖保留[來源及授權標示](docs/demo-assets/README.md)。

異常偵測採用 Karsten Roth 等人提出的 PatchCore 方法，原始論文為 [Towards Total Recall in Industrial Anomaly Detection（CVPR 2022）](https://arxiv.org/abs/2106.08265)，作者程式碼見 [Amazon Science 官方儲存庫](https://github.com/amazon-science/patchcore-inspection)。
