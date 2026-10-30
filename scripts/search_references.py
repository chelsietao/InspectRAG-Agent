"""Search normal images or document evidence from a local CLI."""
import argparse
import json
from pathlib import Path
from retrieval_core import ImageRetriever,DocumentRetriever,write_json

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='kind',required=True)
    image=sub.add_parser('image')
    image.add_argument('path',type=Path)
    image.add_argument('--k',type=int,default=3)
    image.add_argument('--output',type=Path)
    document=sub.add_parser('document')
    document.add_argument('query')
    document.add_argument('--k',type=int,default=5)
    document.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.output and args.output.exists():
        parser.error('輸出檔案已存在，請選新路徑')
    if args.kind=='image':
        result=ImageRetriever(ROOT,ROOT/'indexes/normal_images_v1').search(args.path,args.k)
    else:
        result=DocumentRetriever(ROOT,ROOT/'indexes/documents_v1').search(args.query,args.k)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        write_json(args.output,result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
