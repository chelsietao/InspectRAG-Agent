# 第三階段：正常圖片搜尋與文件知識庫

這個階段要把第二階段的分析結果接上參考資料，讓程式能找出正常圖片與相關文件段落，接下來才能把這些工具交給代理（Agent）使用。

## 目前這一版負責什麼

正常圖片搜尋（Image Retrieval）會回傳 3 張相近的正常訓練圖片，文件檢索（Document Retrieval）會回傳有來源的候選段落，生成回答、案件資料庫與代理流程將在後續階段串接。

例如輸入「異常分數可以當成瑕疵機率嗎」，程式會列出相關段落、來源網址與段落編號，使用者可核對原文，這個輸出階段尚未判定完整回答是否獲得證據支持。

## 正常圖片怎麼搜尋

參考庫只放第二階段用來建立特徵庫的 179 張正常訓練圖片，30 張正常校準圖片與 83 張測試圖片都排除在外，來源清單與雜湊值（Hash）一起保存在索引資訊中。

我沿用已保存的 ResNet18 模型，取 layer2 與 layer3 的特徵，各自做 4 × 4 的空間平均池化（Spatial Average Pooling），再串成 6,144 維向量（Embedding），保留一些位置資訊。

向量經 L2 正規化（L2 Normalization）後，使用 FAISS 的精確內積索引（IndexFlatIP）搜尋，結果以餘弦相似度（Cosine Similarity）排序，分數用來描述外觀接近程度，無法據此判定瑕疵根因。

查詢時會比對像素雜湊（Pixel Hash），就算同一張圖換了檔名或壓縮方式，也會排除像素相同的參考圖，近似圖片仍需另外定義辨識方式。

目前圖片搜尋的測試確認來源、排除規則與執行結果，還沒有建立人工標註的相似圖片標準答案，因此尚未宣稱相似性精確率（Precision）。

## 文件內容從哪裡來

目前以 11 個來源、32 個自行撰寫的來源摘要建立知識庫（Knowledge Base），涵蓋官方資料集、方法論文、模型說明、向量搜尋工具，以及專題自己的設定與整體評估。

每段包含段落識別碼（Chunk ID）、來源識別碼（Source ID）、標題、網址、來源位置、版本與內容雜湊，外部資料保留連結並使用摘要，沒有公開重製整份第三方文件。

本版由助理核對來源後整理，來源審閱狀態（Review Status）標示為 `assistant_source_checked_pending_user_review`，內容仍待使用者審閱，知識庫也不代表已經過品質工程專家認證。

### 可以收錄與必須隔離的資料

| 內容 | 使用方式 |
|---|---|
| 官方資料集與方法說明 | 整理成附來源摘要 |
| 本專題的模型設定 | 說明實際骨幹、解析度與門檻 |
| 已完成的整體評估 | 說明量測範圍與限制 |
| 逐張測試圖片的答案與標籤 | 保留評估用途，不放入知識庫 |
| 問答測試題與相關段落標註 | 獨立保存，不放入檢索索引 |
| 製程根因與產品允收條件 | 目前缺少支持資料，只收錄專題範圍限制 |

來源摘要與原始內容分開記錄，這版著重可核對的小型知識庫，PDF 自動解析與長文件切塊（Chunking）尚待擴充。

## 中文問題怎麼找到段落

文字模型使用本機的 Multilingual E5 Small，問題加上 `query:` 前綴、段落加上 `passage:` 前綴，向量模型版本會固定到下載時的提交編號（Model Revision）。

問題與段落轉成 384 維向量後，用 FAISS 做語意搜尋（Semantic Search），另外用字元片段的詞頻與逆文件頻率（TF-IDF）計算文字相似程度，兼顧中文描述與明確的術語。

兩路排名使用倒數排名融合（Reciprocal Rank Fusion，RRF）合併，常數固定為 60，初期取前 5 段，這組設定在保留題評估前固定，評估後有修改時需另存版本並說明。

結果會顯示兩路分數與來源，檢索成功只代表找到了候選，對於沒有答案的問題也可能回傳相近文字，拒答與主張支持判斷將在生成回答階段處理。

## Mac 上的套件衝突怎麼處理

實作時遇到 PyTorch 與 FAISS 各自載入 OpenMP 執行庫（Runtime），同一個 Python 程序會發生原生程式錯誤，單純改載入順序或執行緒數沒有解決。

本版把模型計算放到工作程序（Worker Process），主程序只負責 FAISS 搜尋與資料管理，兩者透過逐行 JSON 的程序間通訊（Inter-process Communication，IPC）交換向量，避免同一程序載入兩套衝突的原生執行庫。

工作程序有啟動與請求逾時（Timeout），錯誤會回傳結構化訊息，程式結束時關閉子程序，沒有啟用允許重複執行庫的強制忽略設定。

這個設計增加了模型載入與通訊成本，正式 API 階段需要管理程序生命週期與併發，本版先驗證單一使用者的命令列流程。

## 怎麼在 VS Code 使用

在專案根目錄開啟終端機（Terminal），目前已建立的環境與索引可以執行以下指令，使用者本階段不需要建立帳號或提供模型金鑰。

```bash
.venv/bin/python scripts/search_references.py image bottle/test/broken_large/000.png
.venv/bin/python scripts/search_references.py document "異常分數可以當成瑕疵機率嗎"
.venv/bin/python -m unittest discover -s tests -v
```

如果要保存搜尋輸出，用 `--output` 指定新的 JSON 路徑，既有檔案不會覆寫，候選數則用 `--k` 調整，接受範圍是 1 至 20。

```bash
.venv/bin/python scripts/search_references.py document "正常校準集怎麼分" --k 5 --output artifacts/query_example.json
```

單次命令列查詢需要載入模型，回覆等待時間包含程序啟動成本，後續 API 可重用同一個已載入的工作程序，再量測服務延遲。

## 重新建置的順序

其他電腦先完成第一、二階段與資料下載，再安裝檢索依賴（Retrieval Dependencies），以下步驟會建立小型知識庫與兩種索引。

```bash
.venv/bin/python -m pip install -r requirements-retrieval.txt
.venv/bin/python scripts/prepare_knowledge.py
.venv/bin/python scripts/build_retrieval_indexes.py --kind image
.venv/bin/python scripts/build_retrieval_indexes.py --kind document
```

既有索引或文字模型資料夾存在時，建置程式會停止以保留舊版本，新增版本目前需在程式中更換版本名稱與路徑，後續會再整理成設定檔。

正常圖片索引、文件索引與模型保留在本機 `indexes/` 和 `models/`，公開儲存庫只保存程式、來源摘要、評估題與可公開報告。

## 評估方式與限制

在首次執行文件評估前，先固定 12 題開發集（Development Set）與 12 題保留題（Held-out Set），每題由專題指定相關段落，記錄前五段召回率（Recall@5）與前五名平均倒數排名（MRR@5）。

題目與知識庫由同一個專題建立，這是小型作者自訂評估，還需要使用者與獨立評閱者審查，結果無法代表廣泛工業問答能力。

評估檔案另存於 `evaluation/retrieval_v1/`，索引建置只讀明確指定的 `data/knowledge/`，不會搜尋整個儲存庫或把評估答案加進知識庫。

本階段不評分生成品質、主張支持率或拒答成功率，引用編號檢查只驗證回傳段落是否存在，語意支持度需要後續回答流程與人工審閱。

## 這次量到的結果

| 指標 | 開發集 12 題 | 保留題 12 題 |
|---|---:|---:|
| 前五段召回率（Recall@5） | 100% | 100% |
| 前五名平均倒數排名（MRR@5） | 0.9583 | 1.0000 |
| 回傳段落編號有效率（Citation ID Validity） | 100% | 100% |

這次完整程式測試共 24 項通過，涵蓋資料驗證、模型回歸、索引完整性、自身排除、來源與錯誤參數，測試未以跳過方式取代已建立索引的整合檢查。

題目內容與逐題結果見 [question_results.json](evaluation/retrieval_v1/question_results.json)，指標、程式雜湊與限制見 [metrics.json](evaluation/retrieval_v1/metrics.json)，模型已載入後的檢索耗時也保存其中，該耗時排除首次載入與模型檔案完整性檢查，不能等同命令列總等待時間。

目前只有 32 個摘要段落與 24 個自訂問題，分數不代表廣泛工業問答品質，下一輪需增加獨立問題、模糊問題與沒有資料的問題，並保留使用者審閱與改版紀錄。

## 下一步

接下來把圖片分析、圖片搜尋與文件搜尋整理成代理工具（Agent Tools），接上語言模型前會先確認供應商、憑證與費用，現階段先保留檢索工具與可核對來源。
