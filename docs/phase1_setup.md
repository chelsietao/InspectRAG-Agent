# 第一階段：資料與環境準備

目前已完成資料驗證與開發環境（Development Environment），模型、檢索增強生成（RAG）與代理（Agent）尚未實作，本階段沒有使用雲端模型或 API 金鑰。

## 在 VS Code 執行

用 VS Code 開啟專案，在終端機（Terminal）切到專案根目錄，隔離環境（Virtual Environment）已使用 Python 3.12.14 與 Pillow 12.3.0 建立。

```bash
.venv/bin/python --version
.venv/bin/python scripts/validate_data.py --root bottle --output data/manifests
.venv/bin/python -m unittest discover -s tests -p test_validate_data.py -v
```

預設直譯器（Interpreter）設定為 `.venv/bin/python`，若視窗尚未切換，可從命令選擇區選擇 `Python: Select Interpreter`，再指定此環境。

## 在其他電腦重建

先準備 Python 3.12，在專案根目錄執行以下指令，再從官方來源取得 bottle 資料，放到同名資料夾後進行驗證。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-data.txt
.venv/bin/python scripts/validate_data.py --root bottle --output data/manifests
.venv/bin/python -m unittest discover -s tests -p test_validate_data.py -v
```

目前 Mac 的環境由 Codex 提供的 Python 3.12 建立，原始直譯器若被移除，需要用自己的 Python 3.12 重建 `.venv`，隔離環境本身不會上傳 GitHub。

## 本次實測

| 分組 | 張數 |
|---|---:|
| 正常訓練圖片（Normal Training Images） | 209 |
| 正常測試圖片（Normal Test Images） | 20 |
| 異常測試圖片（Anomalous Test Images） | 63 |
| 瑕疵遮罩（Ground-truth Masks） | 63 |

圖片與遮罩共 355 個 PNG 檔，尺寸均為 900 × 900，驗證狀態為通過，10 項單元測試（Unit Tests）也通過。

程式完整解碼圖片、檢查遮罩二元值與尺寸、核對雙向對應，並使用像素雜湊（Pixel Hash）檢查跨切分完全重複，近似重複與標註的語意正確性仍需另外驗證。

## 產生檔案

- `data/manifests/bottle_manifest.jsonl`，逐檔保存相對路徑、尺寸與雜湊值（Hash）。
- `data/manifests/bottle_validation.json`，保存可供程式讀取的結果。
- `data/manifests/bottle_validation.md`，提供中文檢查報告。

原始 `bottle/` 與 `.venv/` 已由 Git 排除規則（Git Ignore Rules）排除，只上傳程式、測試與不含圖片的資料清單，使用資料時需遵守 [MVTec AD 官方授權](https://www.mvtec.com/research-teaching/datasets/mvtec-ad)。

## 下一階段

接下來建立視覺基準（Vision Baseline）與熱圖（Heatmap），在選定套件版本後處理模型權重下載、硬體設定與正常校準切分，完成前不宣稱具備瑕疵判定能力。
