# 代理回答與工具紀錄

執行狀態（Run Status），`answered`。

- 異常分數（Anomaly Score）表示目前特徵與正常外觀的偏離程度，數值受模型和設定影響，尚未做機率校準，因此 0.8 或其他分數都不能解讀成瑕疵機率。 [doc:config-no-probability]
- 影像門檻（Image Threshold）採 30 張正常校準圖片的最高分數，約為 10.19447，分數大於門檻才判為異常，門檻在讀取測試結果前固定，沒有使用測試標籤調整。 [doc:config-threshold]
- Anomalib 的 PatchCore 擷取預訓練骨幹的中間層特徵，推論時搜尋特徵庫中的最近鄰（Nearest Neighbor），以局部特徵距離產生異常分數與異常分布圖。 [doc:method-neighbor]

## 限制

- 未提供具體圖片，無法示範實際分數與門檻的比較。
- 文件未提供機率校準（calibration）的具體方法或替代指標。

## 資料來源

- `doc:config-no-probability`，[分數與機率](https://github.com/chelsietao/InspectRAG-Agent/blob/main/docs/phase2_vision.md)。
- `doc:config-threshold`，[影像判斷門檻](https://github.com/chelsietao/InspectRAG-Agent/blob/main/docs/phase2_vision.md)。
- `doc:method-neighbor`，[最近鄰與異常分數](https://anomalib.readthedocs.io/en/latest/markdown/guides/reference/models/image/patchcore.html)。

## 工具執行順序

- 第 1 步，`search_documents` → `succeeded`。
- 第 2 步，`search_documents` → `succeeded`。
- 第 3 步，`search_documents` → `succeeded`。
- 第 4 步，`submit_answer` → `succeeded`。

## 驗證範圍

本版檢查引用編號與工具流程，回答內容仍需核對來源，語意支持度尚未自動驗證。
