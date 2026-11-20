"""Windows launcher: reuse d1 when available; only stop model processes we own."""
import asyncio
import atexit
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from backend.config import ROOT,load_settings
from backend.models import D1

def main():
    os.chdir(ROOT)
    settings=load_settings();settings.work.mkdir(parents=True,exist_ok=True)
    if sys.stdout is None or sys.stderr is None:
        output=(settings.work/'service.log').open('a',encoding='utf-8',buffering=1);sys.stdout=output;sys.stderr=output
    url=f'http://127.0.0.1:{settings.port}'
    try:
        with urllib.request.urlopen(url+'/api/session',timeout=2) as response:
            if json.load(response).get('app')=='LiquidPilot AI':
                if '--no-browser' not in sys.argv:webbrowser.open(url)
                return
    except Exception:pass
    owned=None
    if not asyncio.run(D1(settings).health()):
        model=settings.path(settings.model_path);exe=settings.path(settings.llama_path)
        if not model.exists() or not exe.exists():raise SystemExit('Existing model/runtime not found. Configure their paths in config/settings.json.')
        key=settings.path(settings.decision_key_file)
        if not key.exists():
            import secrets
            key.parent.mkdir(parents=True,exist_ok=True);key.write_text(secrets.token_hex(32))
        args=[str(exe),'-m',str(model),'--host','127.0.0.1','--port',str(__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(settings.decision_url).port or 8081),'-ngl','all','-c','4096','-np','1','-b','512','-ub','512','-t','6','--no-webui','--api-key-file',str(key),'--cors-origins',url]
        projector=settings.path(settings.projector_path)
        if projector.exists():args+=['--mmproj',str(projector)]
        log=(settings.work/'model.log').open('w',encoding='utf-8')
        owned=subprocess.Popen(args,cwd=exe.parent,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        def cleanup():
            if owned.poll() is None:owned.terminate()
            log.close()
        atexit.register(cleanup)
    (settings.work/'process.json').write_text(json.dumps({'pid':os.getpid(),'model_pid':owned.pid if owned else None,'created':time.time(),'script':str(ROOT/'main.py')}))
    if '--no-browser' not in sys.argv:threading.Timer(2,lambda:webbrowser.open(url)).start()
    import uvicorn
    from backend.api import create_app
    uvicorn.run(create_app(settings),host='127.0.0.1',port=settings.port,log_level='warning',use_colors=False)

if __name__=='__main__':main()
