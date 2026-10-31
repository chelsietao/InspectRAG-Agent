"""Create a small source-linked corpus from explicit, reviewed project summaries."""
from pathlib import Path
import hashlib
import json

SOURCES = [
    ("mvtec", "MVTec AD 官方資料說明", "https://www.mvtec.com/research-teaching/datasets/mvtec-ad", "官方資料集說明", "MVTec Software GmbH", "external_summary"),
    ("downloads", "MVTec AD 官方下載說明", "https://www.mvtec.com/research-teaching/datasets/mvtec-ad/downloads", "Download the MVTec AD dataset", "MVTec Software GmbH", "external_summary"),
    ("patchcore", "PatchCore 方法論文", "https://arxiv.org/abs/2106.08265v2", "Abstract", "Karsten Roth et al.", "external_summary"),
    ("anomalib", "Anomalib PatchCore 方法說明", "https://anomalib.readthedocs.io/en/latest/markdown/guides/reference/models/image/patchcore.html", "PatchCore / Architecture", "Anomalib contributors", "external_summary"),
    ("e5", "Multilingual E5 Small 模型說明", "https://huggingface.co/intfloat/multilingual-e5-small", "Usage / Model card", "intfloat model authors", "external_summary"),
    ("faiss", "FAISS 官方說明", "https://github.com/facebookresearch/faiss", "README / Introduction", "FAISS contributors", "external_summary"),
    ("project-config", "第二階段實驗設定", "https://github.com/chelsietao/InspectRAG-Agent/blob/main/docs/evaluation/vision_baseline_v1/config.json", "baseline config", "InspectRAG Agent project", "project_summary"),
    ("project-metrics", "第二階段整體評估", "https://github.com/chelsietao/InspectRAG-Agent/blob/main/docs/evaluation/vision_baseline_v1/metrics.json", "aggregate metrics", "InspectRAG Agent project", "project_summary"),
    ("project-guide", "第二階段操作與限制", "https://github.com/chelsietao/InspectRAG-Agent/blob/main/docs/phase2_vision.md", "phase-two guide", "InspectRAG Agent project", "project_summary"),
    ("project-data", "第一階段資料檢查", "https://github.com/chelsietao/InspectRAG-Agent/blob/main/data/manifests/bottle_validation.json", "validation summary", "InspectRAG Agent project", "project_summary"),
    ("project-scope", "專題範圍與資料使用說明", "https://github.com/chelsietao/InspectRAG-Agent/blob/main/README.md", "資料切分 / 功能範圍", "InspectRAG Agent project", "project_summary"),
]
# Authored paraphrases, not copied source passages. No evaluation questions or test labels.
CHUNKS = [
    ("dataset-content", "mvtec", "資料集內容", "MVTec AD 工業異常檢測資料集（Dataset）包含超過 5,000 張圖片與 15 種物件及材質類別，提供正常訓練圖片、正常與異常測試圖片，以及像素級異常標註（Pixel-level Annotation）。"),
    ("dataset-license", "mvtec", "資料授權", "MVTec AD 採姓名標示、非商業性、相同方式分享 4.0 授權（CC BY-NC-SA 4.0），使用與分享資料需遵守條款，商業使用需另洽資料提供者。"),
    ("download-folders", "downloads", "下載後的資料夾", "瓶子（Bottle）子集的官方下載大小約 148 MB，解壓縮後有 train 正常訓練圖片、test 測試圖片及 ground_truth 異常區域遮罩三個主要資料夾。"),
    ("method-nominal", "patchcore", "正常樣本與局部特徵", "PatchCore 使用正常樣本的局部特徵建立具代表性的記憶庫（Memory Bank），利用預訓練影像特徵處理異常檢測與定位，適用於先取得正常外觀樣本的設定。"),
    ("method-neighbor", "anomalib", "最近鄰與異常分數", "Anomalib 的 PatchCore 擷取預訓練骨幹的中間層特徵，推論時搜尋特徵庫中的最近鄰（Nearest Neighbor），以局部特徵距離產生異常分數與異常分布圖。"),
    ("embedding-e5", "e5", "跨語言文字向量", "Multilingual E5 Small 是 384 維的多語言文字向量模型（Embedding Model），檢索時問題加 query: 前綴、段落加 passage: 前綴，向量正規化後可比較相似程度，模型卡標示 MIT 授權。"),
    ("index-faiss", "faiss", "向量搜尋工具", "FAISS 提供稠密向量（Dense Vector）的相似度搜尋與分群功能，可用來建立圖片或文字的向量索引，段落文字與來源仍需另外保存。"),
    ("config-backbone", "project-config", "目前模型骨幹", "本專題 bottle 第一版採 ResNet18 預訓練骨幹（Backbone），取 layer2 與 layer3 特徵，輸入解析度為 128 × 128，並使用 CPU 與 4 個執行緒，這是本機基準設定。"),
    ("config-coreset", "project-guide", "特徵抽樣與最近鄰", "本次代表性核心集（Coreset）的抽樣比例為 1%，最近鄰數 num_neighbors 為 1，隨機種子為 42，正常特徵庫保留 458 個 384 維向量。"),
    ("config-threshold", "project-guide", "影像判斷門檻", "影像門檻（Image Threshold）採 30 張正常校準圖片的最高分數，約為 10.19447，分數大於門檻才判為異常，門檻在讀取測試結果前固定，沒有使用測試標籤調整。"),
    ("config-heatmap", "project-guide", "共用熱圖色階", "熱圖疊圖（Heatmap Overlay）共用正常校準資料決定的色階，正常圖片也可能有非零反應，並排範例的色階上限是校準分數圖最大值的兩倍，顏色只協助觀察局部分數。"),
    ("config-no-probability", "project-guide", "分數與機率", "異常分數（Anomaly Score）表示目前特徵與正常外觀的偏離程度，數值受模型和設定影響，尚未做機率校準，因此 0.8 或其他分數都不能解讀成瑕疵機率。"),
    ("split-fit", "project-guide", "正常訓練與校準切分", "原始 209 張正常訓練圖片中，179 張建立特徵庫、30 張作為正常校準集（Calibration Set），依排序與隨機種子 42 固定分組，校準圖片沒有放進特徵庫。"),
    ("split-test", "project-guide", "保留測試資料", "原始測試集（Test Set）有 83 張圖片，其中 20 張正常、63 張異常，只在模型與校準規則固定後評估，瑕疵遮罩只供評估和圖像對照。"),
    ("metrics-ranking", "project-metrics", "整體排序評估", "這次 bottle 基準的影像級排序指標（Image AUROC）為 0.996031746，像素級排序指標（Pixel AUROC）為 0.966502604，兩者衡量排序能力，不能等同分類正確率。"),
    ("metrics-resolution", "project-metrics", "像素評估解析度", "像素級評估（Pixel Evaluation）在 128 × 128 進行，原始 900 × 900 遮罩以最近鄰縮放後再比較，熱圖放大顯示不會增加模型解析度，也不能宣稱原尺寸定位表現。"),
    ("metrics-confusion", "project-metrics", "誤報與漏檢數量", "固定門檻下，20 張正常測試圖片沒有誤報，63 張異常測試圖片找出 61 張、漏檢 2 張，異常召回率（Anomaly Recall）為 61 ÷ 63，約 96.83%。"),
    ("metrics-latency", "project-metrics", "推論等待時間", "暖機後的 CPU 推論時間，中位數（p50）約 13.3 毫秒、第 95 百分位（p95）約 14.4 毫秒，包含讀圖與前處理，排除模型載入、存圖與報告，並非整個服務等待時間。"),
    ("limit-generalization", "project-guide", "泛化與真實產線限制", "目前只測試 bottle 一個類別與一個隨機種子，尚無信賴區間或真實產線驗證，拍攝環境、產品外觀與資料分布改變時需要重新評估，不能直接套用現有成效。"),
    ("limit-calibration", "project-guide", "校準門檻的限制", "30 張正常校準樣本的最大值只能提供目前的判斷門檻，無法保證未來資料的假陽性率（False Positive Rate），正常測試資料也只有 20 張，零誤報仍有樣本數限制。"),
    ("data-counts", "project-data", "已驗證圖片數量", "第一階段驗證了 292 張檢驗圖片與 63 張瑕疵遮罩（Ground-truth Masks），共 355 個 PNG 檔，圖片尺寸皆為 900 × 900，圖片為 RGB、遮罩為單通道。"),
    ("data-integrity", "project-data", "檔案檢查與標註限制", "資料驗證檢查解碼、遮罩二元值、圖片與遮罩的對應及尺寸，未發現訓練與測試之間像素完全相同的圖片，近似重複與標註語意正確性仍需要額外檢查。"),
    ("use-no-root-cause", "project-scope", "根因與允收範圍", "專題目前可提供外觀分數、參考圖與方法說明，製程根因（Root Cause）、修復處置與產品允收標準（Acceptance Criteria）缺少專業資料支持，這類問題需要回覆證據不足。"),
    ("use-memory", "project-scope", "案件記憶與證據快照", "案件記憶（Case Memory）已保存同案件的歷史工具結果、來源執行與使用者確認觀察，追問時以最多 6,000 字元的快照提供資料，使用者觀察與量測結果分開標記，舊模型回答不作為新事實，撤回觀察只影響之後建立的快照。"),
    ("use-local-files", "project-guide", "模型與分析產物位置", "模型檢查點（Checkpoint）保存在 artifacts/vision_baseline_v1/patchcore_bottle.pt，熱圖與單張推論結果保留本機，原始圖片、權重與執行環境不放進公開 GitHub。"),
    ("use-cli-predict", "project-guide", "單張推論操作", "在專案根目錄執行 .venv/bin/python scripts/predict_image.py 圖片路徑，會載入已保存的模型並產生分數與熱圖，輸出位置用 --output 指定，既有資料夾不會覆寫。"),
    ("use-cli-baseline", "project-guide", "重新執行基準", "執行 scripts/run_vision_baseline.py 可以重建基準，若輸出資料夾已存在會停止，重跑需用 --output 與 --report-dir 指定新位置，保留先前實驗紀錄。"),
    ("use-locked-env", "project-guide", "環境與版本", "視覺環境（Vision Environment）使用 Python 3.12，直接套件寫在 requirements-vision.txt，完整 Mac 套件快照在 requirements-vision.lock.txt，跨平台仍需確認相容性。"),
    ("use-checkpoint", "project-guide", "重新載入與一致性", "單張推論載入模型檢查點時不需要重建特徵庫，測試已確認正常與異常各一張的重新載入分數，與保存的基準結果一致，模型雜湊用於辨識版本。"),
    ("use-training", "project-guide", "本次模型工作範圍", "本次使用預訓練骨幹擷取特徵並建立正常記憶庫，沒有更新神經網路權重，履歷應描述特徵擷取、模型整合與評估，尚未累積模型微調（Fine-tuning）成果。"),
    ("use-split-leakage", "project-scope", "資料洩漏與索引範圍", "正常參考圖索引只使用允許的訓練圖片，保留校準與測試資料不進入參考庫，同一張或相同像素圖片搜尋時需排除自身，避免資料洩漏（Data Leakage）。"),
    ("use-citation", "project-scope", "文件引用與主張", "文件檢索（Document Retrieval）需回傳來源標題、段落編號與版本，引用編號存在只代表結構有效，回答是否得到段落支持仍需要主張支持度（Claim Support）評估。"),
]

DEPENDENCIES = [
    "docs/evaluation/vision_baseline_v1/config.json",
    "docs/evaluation/vision_baseline_v1/metrics.json",
    "docs/phase2_vision.md", "data/manifests/bottle_validation.json",
]


def main():
    out = Path("data/knowledge")
    out.mkdir(parents=True, exist_ok=True)
    source_rows = []
    by_id = {}
    for source_id, title, url, locator, author, kind in SOURCES:
        row = {"source_id": source_id, "title": title, "url": url, "locator": locator,
               "author_or_org": author, "type": kind, "checked_at": "2026-10-30",
               "content_policy": "專題自行撰寫的來源摘要，原文權利依原始來源，不重製整份文件。",
               "review_status": "assistant_source_checked_pending_user_review"}
        source_rows.append(row)
        by_id[source_id] = row
    chunks = []
    for chunk_id, source_id, title, text in CHUNKS:
        row = {"chunk_id": chunk_id, "source_id": source_id, "title": title, "text": text,
               "source_url": by_id[source_id]["url"], "source_locator": by_id[source_id]["locator"],
               "content_type": "authored_summary", "corpus_version": "knowledge-v2-case-memory",
               "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
        chunks.append(row)
    assert len({r["chunk_id"] for r in chunks}) == len(chunks)
    dependencies = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in DEPENDENCIES}
    for name, rows in [("sources.jsonl", source_rows),("chunks.jsonl", chunks)]:
        (out / name).write_text("".join(json.dumps(row,ensure_ascii=False)+"\n" for row in rows))
    (out / "dependencies.json").write_text(json.dumps(dependencies,indent=2)+"\n")
    print(json.dumps({"sources":len(source_rows),"chunks":len(chunks)},ensure_ascii=False))


if __name__ == "__main__":
    main()
