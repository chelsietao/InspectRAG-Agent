"""Freeze a small project-authored retrieval question set before first evaluation."""
import hashlib
import json
from pathlib import Path

DEV=[
    ('資料集提供哪些圖片與標註',['dataset-content']),
    ('瓶子資料夾分成哪幾個目錄',['download-folders']),
    ('PatchCore 為什麼能只用正常樣本建立模型',['method-nominal']),
    ('目前模型骨幹與輸入大小是什麼',['config-backbone']),
    ('判斷異常的門檻怎麼訂',['config-threshold']),
    ('數值 0.8 能當成百分之八十瑕疵機率嗎',['config-no-probability']),
    ('179 與 30 張圖片各拿來做什麼',['split-fit']),
    ('測試集有多少正常和異常圖',['split-test']),
    ('像素級評估是用什麼解析度',['metrics-resolution']),
    ('單張圖片分析要用什麼指令',['use-cli-predict']),
    ('如何避免搜尋庫包含測試資料',['use-split-leakage']),
    ('引用編號存在就代表回答有根據嗎',['use-citation']),
]
TEST=[
    ('這批影像能不能拿去商業使用',['dataset-license']),
    ('找局部最近鄰跟異常圖有什麼關係',['method-neighbor']),
    ('E5 的 query 與 passage 前綴應怎麼用',['embedding-e5']),
    ('FAISS 在這個專題負責哪種工作',['index-faiss']),
    ('本機核心集抽樣比例和特徵維度是多少',['config-coreset']),
    ('每張熱圖的紅色可以拿來比較嗎',['config-heatmap']),
    ('這次 Image AUROC 和 Pixel AUROC 分別是多少',['metrics-ranking']),
    ('正常誤報和異常漏檢各有幾張',['metrics-confusion']),
    ('p95 等待時間包含模型載入嗎',['metrics-latency']),
    ('正常校準圖的最大分數能保證未來都不誤報嗎',['limit-calibration']),
    ('檔案都能開啟，是否代表已檢查標註語意正確',['data-integrity']),
    ('可不可以從目前資料判定瓶子的製程根因與出貨允收',['use-no-root-cause']),
]


def main():
    folder=Path('evaluation/retrieval_v1')
    if folder.exists():
        raise ValueError('評估題已存在，不能覆寫既有測試集')
    folder.mkdir(parents=True)
    for name,items in [('dev',DEV),('heldout',TEST)]:
        rows=[{'id':f'{name}-{index:02}','query':query,'relevant_chunks':chunks}
              for index,(query,chunks) in enumerate(items,1)]
        (folder/f'{name}.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob('*.jsonl'))}
    (folder/'frozen.json').write_text(json.dumps({'question_file_sha256':hashes,
        'note':'助理依知識庫內容指定相關段落，先固定題集再執行，非獨立外部評測，尚待使用者審閱。'},ensure_ascii=False,indent=2)+'\n')
    print('Frozen 12 development and 12 held-out retrieval questions')


if __name__=='__main__':
    main()
