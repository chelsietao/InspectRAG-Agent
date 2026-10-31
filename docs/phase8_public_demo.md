# 第八階段：公開展示網址

公開入口為 https://chelsietao.github.io/InspectRAG-Agent/ ，GitHub Pages 使用 main 分支的 docs 資料夾發布，頁面不需要登入與 API 金鑰。

## 可以操作什麼

切換原始圖片、異常熱圖與三張正常參考圖片，查看保存的分數與門檻，再選擇案件追問與方法解讀範例，來源清單提供標題搜尋。

## 資料與功能範圍

案件追問重播 docs/evaluation/case_memory_v1/live_followup.json 的結果，方法解讀為本專題撰寫的說明，頁面標明兩者差異。

網站沒有執行模型或接受圖片上傳，完整後端仍以本機 FastAPI 啟動，公開版不會傳送圖片或呼叫 Groq，也不會產生 API 費用。

## 維護

修改 docs/index.html 與 docs/demo-assets/ 後推送 main，GitHub Pages 會重建公開頁面，既有模型與 Python 後端不受影響。

範例圖像與衍生熱圖依 MVTec AD 的 CC BY-NC-SA 4.0 授權使用，頁尾與素材說明保留來源、授權與變更說明。
