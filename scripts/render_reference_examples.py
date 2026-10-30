"""Render local query/reference images without distributing dataset images."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]


def main():
    examples=json.loads((ROOT/'docs/evaluation/retrieval_v1/image_examples.json').read_text())
    figure,axes=plt.subplots(len(examples),4,figsize=(13,7))
    for row,example in enumerate(examples):
        paths=[example['query_path']]+[r['path'] for r in example['matches']]
        for column,path in enumerate(paths):
            with Image.open(ROOT/'bottle'/path) as image:
                axes[row,column].imshow(image)
            if column==0:
                title='Query\n'+path
            else:
                match=example['matches'][column-1]
                title=f"Normal reference {column} | cosine={match['cosine_similarity']:.3f}\n{path}"
            axes[row,column].set_title(title,fontsize=9)
            axes[row,column].axis('off')
    figure.suptitle('Normal-image retrieval | fit split only | normal references do not imply defect cause')
    figure.tight_layout()
    target=ROOT/'artifacts/retrieval_v1'
    target.mkdir(parents=True,exist_ok=True)
    figure.savefig(target/'normal_reference_examples.png',dpi=140,bbox_inches='tight')
    plt.close(figure)
    print('Saved local image-reference examples')


if __name__=='__main__':
    main()
