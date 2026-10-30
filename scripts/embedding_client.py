"""JSON-line IPC for a local Torch encoder subprocess, with finite waits."""
import atexit
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys


class VectorWorker:
    def __init__(self,kind,model_path,download_model=None,revision=None):
        command=[sys.executable,'-u',str(Path(__file__).with_name('embedding_worker.py')),kind,str(model_path)]
        if download_model:
            command+=['--download-model',download_model,'--revision',revision]
        environment=os.environ.copy()
        environment.pop('KMP_DUPLICATE_LIB_OK',None)
        self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                       stderr=None,text=True,bufsize=1,env=environment)
        atexit.register(self.close)
        message=self._read(timeout=900 if download_model else 120)
        if not message.get('ready'):
            raise RuntimeError(f'向量程序未能啟動：{message}')
        self.info=message['info']

    def _read(self,timeout):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout,selectors.EVENT_READ)
            if not selector.select(timeout):
                self.close()
                raise TimeoutError('向量程序等待逾時')
            line=self.process.stdout.readline()
        if not line:
            raise RuntimeError(f'向量程序中斷，狀態：{self.process.poll()}')
        message=json.loads(line)
        if 'error' in message:
            raise RuntimeError(message['error'])
        return message

    def request(self,data):
        if self.process.poll() is not None:
            raise RuntimeError('向量程序已停止')
        self.process.stdin.write(json.dumps(data,ensure_ascii=False)+'\n')
        self.process.stdin.flush()
        return self._read(timeout=120)['vectors']

    def close(self):
        process=getattr(self,'process',None)
        if process and process.poll() is None:
            try:
                process.stdin.write(json.dumps({'op':'close'})+'\n')
                process.stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        if process:
            for stream in [process.stdin,process.stdout]:
                if stream and not stream.closed:
                    stream.close()
