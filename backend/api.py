import asyncio
from contextlib import asynccontextmanager
import json
import mimetypes
import re
import secrets
import statistics
import time
from pathlib import Path
from urllib.parse import urlsplit

import psutil
from fastapi import FastAPI,HTTPException,Request,UploadFile,File,WebSocket,WebSocketDisconnect
from fastapi.responses import FileResponse,JSONResponse,Response,StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .config import ROOT,Settings,load_settings
from .storage import Store
from .schemas import TaskSpec,TERMINAL
from .agent import AgentManager
from .models import D1
from .security import PolicyError
from .attachments import extract
from .chrome_bridge import bridge

def create_app(settings=None):
    settings=settings or load_settings()
    store=Store(settings.work)
    manager=AgentManager(settings,store)
    token=secrets.token_urlsafe(32)
    csrf=secrets.token_urlsafe(24)

    @asynccontextmanager
    async def lifespan(app):
        store.recover_interrupted();store.expire(settings.retention_days)
        yield
        await manager.close();store.close()

    app=FastAPI(title='LiquidPilot AI',docs_url=None,redoc_url=None,lifespan=lifespan)
    app.state.store=store;app.state.manager=manager;app.state.settings=settings

    @app.websocket('/browser-bridge')
    async def browser_bridge(socket:WebSocket):
        if socket.headers.get('host')!=f'127.0.0.1:{settings.port}' or not re.fullmatch(r'chrome-extension://[a-p]{32}',socket.headers.get('origin','')):
            await socket.close(code=1008);return
        await socket.accept()
        try:
            auth=await asyncio.wait_for(socket.receive_json(),5)
            if not isinstance(auth.get('token'),str) or not bridge.authenticate(auth['token']):
                await socket.close(code=1008);return
            if bridge.socket:
                await socket.close(code=1008,reason='Disconnect the current connector first.');return
            bridge.socket=socket
            await socket.send_json({'event':'authenticated','token':bridge.session_token})
            while True:bridge.receive(await socket.receive_json())
        except (WebSocketDisconnect,TimeoutError,ValueError):pass
        finally:await bridge.disconnected(socket)

    @app.post('/api/browser/pair')
    async def pair_browser():
        return {'code':bridge.pairing(),'extension_path':str(ROOT/'extension'),'expires_seconds':600}

    @app.get('/api/browser/status')
    async def browser_status():return bridge.status()

    @app.middleware('http')
    async def boundary(request,call_next):
        hosts={f'127.0.0.1:{settings.port}',f'localhost:{settings.port}'}
        if request.headers.get('host') not in hosts:return JSONResponse({'detail':'Local access only.'},403)
        origin=request.headers.get('origin')
        if origin and origin not in {'http://'+h for h in hosts}:return JSONResponse({'detail':'Cross-origin access denied.'},403)
        if int(request.headers.get('content-length','0'))>21*1024*1024:return JSONResponse({'detail':'Request exceeds 21 MB.'},413)
        if request.url.path.startswith('/api/') and request.url.path!='/api/session':
            if not secrets.compare_digest(request.cookies.get('lp_session',''),token):return JSONResponse({'detail':'Refresh the local application to establish a session.'},401)
            if request.method not in {'GET','HEAD'} and not secrets.compare_digest(request.headers.get('x-lp-csrf',''),csrf):return JSONResponse({'detail':'Invalid request token.'},403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Cache-Control']='no-store'
        response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        return response

    @app.exception_handler(PolicyError)
    async def policy_error(request,exc):return JSONResponse({'detail':str(exc)},400)
    @app.exception_handler(KeyError)
    async def not_found(request,exc):return JSONResponse({'detail':'Resource not found.'},404)

    @app.get('/api/session')
    async def session():
        response=JSONResponse({'csrf':csrf,'app':'LiquidPilot AI'})
        response.set_cookie('lp_session',token,httponly=True,samesite='strict')
        return response

    resource_cache={'at':0,'data':{}}
    async def resources():
        if time.monotonic()-resource_cache['at']<5:return resource_cache['data']
        memory=psutil.virtual_memory()
        process=psutil.Process()
        rss=process.memory_info().rss+sum(p.memory_info().rss for p in process.children(recursive=True) if p.is_running())
        result={'system_ram_total_gb':round(memory.total/2**30,1),'system_ram_available_gb':round(memory.available/2**30,1),'app_ram_mb':round(rss/2**20),'gpu':None}
        try:
            proc=await asyncio.create_subprocess_exec('nvidia-smi','--query-gpu=name,memory.total,memory.used,utilization.gpu','--format=csv,noheader,nounits',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,creationflags=0x08000000 if __import__('os').name=='nt' else 0)
            stdout,_=await asyncio.wait_for(proc.communicate(),3)
            name,total,used,util=stdout.decode().splitlines()[0].split(', ')
            result['gpu']={'name':name,'total_mb':int(total),'used_mb':int(used),'utilization':int(util)}
        except Exception:pass
        resource_cache.update(at=time.monotonic(),data=result);return result

    @app.get('/api/status')
    async def status():
        return {'model_ready':await D1(settings).health(),'model':'LiquidAI d1-3B Q4_K_M','planner_configured':bool(settings.planner_url and settings.planner_model),'browser':bridge.status(),'resources':await resources(),'running_tasks':len([j for j in manager.jobs.values() if not j.done()]),'version':'1.0.0'}

    @app.get('/api/settings')
    async def get_settings():
        return settings.model_dump(exclude={'decision_key_file'})

    @app.put('/api/settings')
    async def put_settings(request:Request):
        body=await request.json()
        allowed={'planner_url','planner_model','planner_adapter','search_provider','searxng_url','headless','decision_min_probability','private_origins','retention_days'}
        if set(body)-allowed:raise HTTPException(400,'Unsupported settings.')
        if any(not job.done() for job in manager.jobs.values()):raise HTTPException(409,'Stop active tasks before changing runtime settings.')
        try:
            updated=Settings(**(settings.model_dump()|body))
            for url in updated.private_origins:
                p=urlsplit(url)
                if p.scheme not in {'http','https'} or not p.hostname or p.path not in {'','/'}:raise ValueError('Private-origin grants must be exact origins, including a port when needed.')
            if updated.planner_adapter not in {'openai','ollama'}:raise ValueError('Choose openai or ollama adapter.')
        except ValueError as exc:raise HTTPException(400,str(exc))
        for key,value in updated.model_dump().items():setattr(settings,key,value)
        (ROOT/'config/settings.json').write_text(json.dumps(settings.model_dump(),indent=2),encoding='utf-8')
        return {'saved':True}

    @app.post('/api/tasks')
    async def create_task(spec:TaskSpec):
        if spec.browser_mode=='chrome':
            if not bridge.socket or not bridge.tab:raise HTTPException(409,'Connect your Chrome tab first using the connector.')
            bridge.tab=await bridge.request('metadata')
            if spec.remember_public:raise HTTPException(400,'Public indexing is disabled for signed-in Chrome tasks.')
            if not spec.allowed_domains:spec.allowed_domains=[urlsplit(bridge.tab['url']).hostname]
        # Only URLs literally supplied by the user are admitted before browser observation.
        if not spec.seed_urls:spec.seed_urls=re.findall(r'https?://[^\s<>"\)]+',spec.goal)
        if spec.mode!='observe' and not spec.allowed_domains:
            spec.allowed_domains=list({urlsplit(x).hostname for x in spec.seed_urls if urlsplit(x).hostname})
            if not spec.allowed_domains:raise HTTPException(400,'Assisted/Authorized tasks need explicit allowed domains or starting URLs.')
        for upload_id in spec.attachment_ids:store.get_upload(upload_id)
        if not await D1(settings).health():raise HTTPException(503,'The local d1 model is not ready. Start LiquidPilot with the Windows launcher.')
        return manager.submit(spec)

    @app.get('/api/tasks')
    async def tasks():return store.list()
    @app.get('/api/tasks/{ident}')
    async def task(ident:str):
        data=store.get(ident);data.update(sources=[{k:v for k,v in s.items() if k!='chunks'} for s in store.sources(ident)],artifacts=store.artifacts(ident));return data
    @app.get('/api/tasks/{ident}/events')
    async def events(ident:str,after:int=0):store.get(ident);return store.events(ident,after)
    @app.get('/api/tasks/{ident}/stream')
    async def stream(ident:str,request:Request):
        store.get(ident)
        async def generate():
            cursor=0
            while not await request.is_disconnected():
                records=store.events(ident,cursor)
                for record in records:
                    cursor=record['id'];yield 'data: '+json.dumps(record)+'\n\n'
                if store.get(ident)['state'] in TERMINAL and not records:break
                await asyncio.sleep(.5)
        return StreamingResponse(generate(),media_type='text/event-stream')

    @app.post('/api/tasks/{ident}/{command}')
    async def control(ident:str,command:str,request:Request):
        if command in {'pause','resume','cancel'}:return await manager.control(ident,command)
        if command=='approve':
            body=await request.json();runner=manager.runners.get(ident)
            if not runner:raise HTTPException(409,'The live task session is no longer available.')
            if not isinstance(body.get('approve'),bool):raise HTTPException(400,'An explicit approval choice is required.')
            await runner.approve(body.get('token',''),body['approve']);return {'accepted':True}
        raise HTTPException(404,'Unknown task command.')

    @app.delete('/api/tasks/{ident}')
    async def delete_task(ident:str):
        if store.get(ident)['state'] not in TERMINAL:raise HTTPException(409,'Stop the task before deleting it.')
        store.forget(ident);return {'deleted':True}

    @app.get('/api/library')
    async def library(q:str=''):
        return {'results':store.search(q),'note':'Only sources explicitly opted into public retrieval are indexed.'}

    @app.get('/api/artifacts/{ident}')
    async def artifact(ident:str,preview:bool=False):
        record,data=store.read_artifact(ident)
        safe=re.sub(r'[^a-zA-Z0-9._-]','_',record['name'])
        disposition='inline' if preview and record['mime'].startswith('image/') else 'attachment'
        return Response(data,media_type=record['mime'],headers={'Content-Disposition':f'{disposition}; filename="{safe}"'})

    @app.post('/api/attachments')
    async def attachment(file:UploadFile=File(...)):
        data=await file.read(20*1024*1024+1);await file.close()
        if len(data)>20*1024*1024:raise HTTPException(413,'Attachment exceeds 20 MB.')
        try:extracted=await asyncio.to_thread(extract,data,file.filename or 'file.txt')
        except Exception as exc:raise HTTPException(400,str(exc)[:200])
        return store.upload(Path(file.filename or 'file').name,file.content_type or 'application/octet-stream',data,extracted)

    @app.get('/api/workflows')
    async def workflows():return [
        {'title':'Research with sources','workflow':'research','goal':'Find three reliable sources explaining PostgreSQL features, compare their claims, and give me the source URLs.'},
        {'title':'Find a documentation section','workflow':'navigate','goal':'Open Laravel documentation, find authentication information, and identify the relevant documentation section.','seed_urls':['https://laravel.com/docs']},
        {'title':'Extract a product table','workflow':'extract','goal':'Find the product table, extract every visible row, and export CSV.'},
        {'title':'Prepare a form','workflow':'form','mode':'assisted','goal':'Fill the supplied fields, pause before submission, and verify the resulting confirmation.'}]

    dist=ROOT/'frontend/dist'
    if (dist/'assets').exists():app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')
    @app.get('/{path:path}')
    async def frontend(path:str):
        if (dist/'index.html').exists():return FileResponse(dist/'index.html')
        return Response('LiquidPilot frontend is not built. Run npm install and npm run build in frontend.',status_code=503)
    return app
