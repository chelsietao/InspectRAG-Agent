# 瓶子資料檢查報告

本報告由資料驗證程式產生，僅描述目前檔案檢查結果。

- 驗證狀態（Validation Status），`passed`。
- 檢驗圖片（Inspection Images），292 張。
- 瑕疵遮罩（Ground-truth Masks），63 張。
- 圖片尺寸（Image Size），900x900。

| 資料分組 | 檔案數 |
|---|---:|
| `ground_truth/broken_large` | 20 |
| `ground_truth/broken_small` | 22 |
| `ground_truth/contamination` | 21 |
| `test/broken_large` | 20 |
| `test/broken_small` | 22 |
| `test/contamination` | 21 |
| `test/good` | 20 |
| `train/good` | 209 |

## 資料限制

- 雜湊檢查只能找出相同像素，無法排除近似圖片或同一物件的不同拍攝。
- 檔案可讀與標註對應不代表已驗證標註的語意正確性。
- 本階段尚未建立模型、校準切分或執行模型評估。

## 發現的錯誤

未發現檔案結構、解碼、遮罩或跨切分完全重複的錯誤，近似重複仍需要另作檢查。
