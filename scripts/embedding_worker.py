"""Torch-only subprocess, isolated from FAISS's native OpenMP runtime on macOS."""
import argparse
import json
from pathlib import Path
import sys
import traceback

import numpy as np
import torch


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('kind',choices=['image','document'])
    parser.add_argument('model_path',type=Path)
    parser.add_argument('--download-model')
    parser.add_argument('--revision')
    args=parser.parse_args()
    torch.set_num_threads(4)
    if args.kind=='image':
        from run_vision_baseline import load_checkpoint,image_tensor
        from torch.nn import functional as F
        model,checkpoint=load_checkpoint(args.model_path)
        ready={k:checkpoint[k] for k in ['config','split','training_manifest_sha256']}
    else:
        from sentence_transformers import SentenceTransformer
        if args.download_model:
            model=SentenceTransformer(args.download_model,revision=args.revision,
                                      device='cpu',trust_remote_code=False)
            model.save(str(args.model_path))
        else:
            model=SentenceTransformer(str(args.model_path),device='cpu',local_files_only=True)
        model.max_seq_length=512
        ready={'max_seq_length':512}
    print(json.dumps({'ready':True,'info':ready}),flush=True)
    for line in sys.stdin:
        try:
            request=json.loads(line)
            if request.get('op')=='close':
                return
            if args.kind=='image':
                with torch.inference_mode():
                    features=model.feature_extractor(image_tensor(Path(request['path']),checkpoint['config']['input_size']))
                    vectors=[F.adaptive_avg_pool2d(model.feature_pooler(features[layer]),(4,4)).flatten(1)
                             for layer in model.layers]
                    array=torch.cat(vectors,dim=1).cpu().numpy()
            else:
                array=model.encode(request['texts'],batch_size=8,normalize_embeddings=True,show_progress_bar=False)
            array=np.asarray(array,dtype=np.float32)
            array=array/np.linalg.norm(array,axis=1,keepdims=True)
            print(json.dumps({'vectors':array.tolist()}),flush=True)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            print(json.dumps({'error':str(exc)}),flush=True)


if __name__=='__main__':
    main()
