# 第二階段：視覺基準與熱圖

這個階段已完成 PatchCore 基準模型（Baseline）、單張圖片推論（Single-image Inference）、固定資料切分與測試評估，使用者目前無需建立帳號或提供 API 金鑰，公開權重由程式下載。

## 我怎麼縮小第一個實驗

我先選 ResNet18 作為預訓練骨幹（Pretrained Backbone），圖片縮成 128 × 128，取 layer2 與 layer3 的特徵，使用中央處理器（CPU）與 4 個執行緒（Threads），讓 Mac 能完成一次端到端的基準實驗。

這是為本機資源設計的設定，與論文使用的較大骨幹、解析度及特徵庫不同，結果只能描述這份設定在 bottle 子集上的表現，不能直接當成論文重現或真實產線成效。

預訓練權重保持固定，正常圖片用來建立特徵庫（Memory Bank），本次沒有更新神經網路權重，程式設定與模型輸出均保留紀錄。

## 資料怎麼分

| 用途 | 圖片數 | 怎麼使用 |
|---|---:|---|
| 正常特徵庫 | 179 | 擷取局部特徵並做代表性抽樣 |
| 正常校準集（Calibration Set） | 30 | 決定影像判斷門檻與熱圖顯示尺度 |
| 原始測試集（Test Set） | 83 | 20 張正常與 63 張異常，最後才評估 |

209 張正常訓練圖片依檔名排序後，以固定隨機種子（Random Seed）42 分出校準資料，完整檔名保存在 [split.json](evaluation/vision_baseline_v1/split.json)，校準圖片沒有進入正常特徵庫。

特徵抽樣使用 1% 的代表性核心集（Coreset），最後保留 458 個 384 維向量，影像分數採單一最近鄰（Nearest Neighbor）設定，詳細參數見 [config.json](evaluation/vision_baseline_v1/config.json)。

## 門檻怎麼決定

本次影像門檻（Image Threshold）取 30 張正常校準圖片的最高分數，約為 10.19447，測試圖片分數大於此值時標為異常，該規則在讀取測試結果前就已固定。

例如正常測試圖片的分數約為 7.751，會落在門檻之下，一張破損測試圖片約為 19.480，會落在門檻之上，這些數字是外觀偏離程度的分數，不能當成瑕疵機率。

30 張正常校準樣本的最大值只能提供目前設定下的門檻，無法保證未來資料的假陽性率（False Positive Rate），本次測試的正常樣本也只有 20 張，需要保留樣本數限制。

## 實際評估結果

| 指標 | 本次結果 | 計算範圍 |
|---|---:|---|
| 影像級排序能力（Image AUROC） | 0.9960 | 83 張測試圖片 |
| 像素級排序能力（Pixel AUROC） | 0.9665 | 128 × 128 的模型分數圖與遮罩 |
| 正常誤報 | 0 / 20 | 固定校準門檻 |
| 異常漏檢 | 2 / 63 | 固定校準門檻 |
| 異常召回率（Anomaly Recall） | 96.83% | 61 / 63 |
| 中位推論時間（p50 Latency） | 約 13.3 毫秒 | 已載入模型、含讀圖與前處理 |
| 第 95 百分位推論時間（p95 Latency） | 約 14.4 毫秒 | 不含模型載入、存圖與報告 |

像素級評估先以最近鄰方式縮放真實遮罩（Ground-truth Mask），再與同解析度分數圖比較，這個數字不代表 900 × 900 原始解析度的定位評估，熱圖放大顯示也不會增加模型解析度。

本次只有一個類別與一個隨機種子，未報告信賴區間（Confidence Interval）或跨類別結果，時間也只是此 Mac、此設定下的暖機後量測，服務端到端延遲需要另測。

執行時的 Git 提交版本是這階段開發前的基底，當時的新程式尚未提交，重現時需核對報告保存的程式雜湊（Source Hash），完整數值、環境版本、程式雜湊與模型雜湊保存於 [metrics.json](evaluation/vision_baseline_v1/metrics.json)，逐張分數保存於 [predictions.csv](evaluation/vision_baseline_v1/predictions.csv)。

## 漏掉哪兩張

| 圖片 | 分數 | 固定門檻 |
|---|---:|---:|
| `test/contamination/003.png` | 9.0902 | 10.1945 |
| `test/contamination/019.png` | 8.0211 | 10.1945 |

這兩張都是污染類別（Contamination），在本次門檻下分數未超標，原因尚未經額外實驗確認，報告保留檔名與數值，也沒有根據這兩張測試圖片回頭修改門檻。

## 熱圖怎麼看

單張推論會輸出疊在原圖上的熱圖（Heatmap Overlay），共用校準資料決定的尺度，紅色表示較高的局部分數，正常圖片也可能有非零反應，顏色本身不能替代影像級判定。

範例總覽另外把原圖、真實遮罩與分數圖並排，四種類別各選檔名排序第一張，色階上限固定為校準分數圖最高值的兩倍，只用於顯示，真實遮罩只用於評估與對照，從未作為模型輸入。

這個顯示方式是為了檢查分數分布，沒有改變模型、測試分數、校準門檻或評估指標，圖片與衍生圖檔保留於本機 `artifacts/`，不放入公開 GitHub 儲存庫。

## 在 VS Code 執行

在專案根目錄開啟終端機（Terminal），可用已建立的環境執行以下指令，公開權重首次下載會花額外時間。

```bash
.venv/bin/python scripts/run_vision_baseline.py
.venv/bin/python scripts/predict_image.py bottle/test/broken_large/000.png --output artifacts/my_prediction
.venv/bin/python scripts/render_vision_examples.py
.venv/bin/python -m unittest discover -s tests -v
```

基準程式為保留實驗紀錄，遇到既有輸出資料夾會停止，若要新跑一輪，需指定新的分析與報告位置。

```bash
.venv/bin/python scripts/run_vision_baseline.py --output artifacts/vision_run_2 --report-dir docs/evaluation/vision_run_2
```

單張推論使用已保存的模型檢查點（Checkpoint），也會檢查輸出資料夾是否已存在，其他模型路徑可用 `--checkpoint` 指定，載入時不需重新下載權重或建立特徵庫。

## 重建環境

其他電腦先建立 Python 3.12 隔離環境（Virtual Environment），再安裝視覺階段的直接依賴，完整鎖定清單則保存本次 Mac 環境的實際版本，跨平台安裝仍需確認相容性。

```bash
.venv/bin/python -m pip install -r requirements-vision.txt
.venv/bin/python -m pip check
```

`requirements-vision.lock.txt` 是本次完整套件快照，模型與結果檔案保留在 `artifacts/vision_baseline_v1/`，資料來源與授權沿用專案 README 的說明。

## 接下來做什麼

下一階段建立正常圖片搜尋與文件知識庫（Knowledge Base），目前的單張推論可以作為代理工具的計算核心，接上雲端語言模型前再確認供應商、憑證與費用，這一階段沒有使用雲端生成服務。
