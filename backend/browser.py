"""Isolated, observable Playwright runtime. Model outputs never become JavaScript."""
import asyncio
import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, TimeoutError as BrowserTimeout
from .config import ROOT
from .security import EgressProxy, PolicyError, origin, redact

DOM_SCRIPT = r'''() => {
 const visible = el => {const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};
 const elements=[...document.querySelectorAll('a[href],button,input,textarea,select,[role="button"],[role="link"]')].filter(visible).slice(0,120);
 const nodes=elements.map((el,i)=>{
   el.setAttribute('data-liquidpilot-id',String(i));
   const tag=el.tagName.toLowerCase(),type=el.getAttribute('type')||'';
   const name=(el.getAttribute('aria-label')||el.labels?.[0]?.innerText||el.innerText||el.getAttribute('placeholder')||el.getAttribute('name')||'').trim().replace(/\s+/g,' ').slice(0,140);
   const role=el.getAttribute('role')||(tag==='a'?'link':tag==='button'?'button':tag==='select'?'combobox':type==='checkbox'?'checkbox':type==='radio'?'radio':['input','textarea'].includes(tag)?'textbox':'');
   const r=el.getBoundingClientRect();
   return {index:i,name,role,tag,type,href:tag==='a'?el.href:'',disabled:!!el.disabled,download:el.hasAttribute('download'),box:{x:r.x,y:r.y,width:r.width,height:r.height},options:tag==='select'?[...el.options].slice(0,30).map(x=>({label:x.label,value:x.value})):[]};
 }).filter(n=>n.type!=='password'&&n.type!=='hidden'&&!n.disabled);
 const paragraphs=[...document.querySelectorAll('p,h1,h2,h3,main li,article li')].filter(visible).map(x=>x.innerText.trim()).filter(Boolean).slice(0,160);
 const tables=[...document.querySelectorAll('table')].filter(visible).slice(0,5).map(t=>({rows:[...t.rows].slice(0,251).map(r=>[...r.cells].map(c=>c.innerText.trim())),total_rows:t.rows.length}));
 const meta={description:document.querySelector('meta[name="description"]')?.content||'',publication_date:document.querySelector('meta[property="article:published_time"],meta[name="date"],meta[name="datePublished"]')?.content||document.querySelector('time[datetime]')?.getAttribute('datetime')||'',canonical:document.querySelector('link[rel="canonical"]')?.href||''};
 return {title:document.title,text:document.body?.innerText?.slice(0,60000)||'',paragraphs,nodes,tables,meta,ready:document.readyState};
}'''

class BrowserController:
    def __init__(self,settings,policy,store,task_id):
        self.settings=settings;self.policy=policy;self.store=store;self.task_id=task_id
        self.pw=None;self.browser=None;self.context=None;self.page=None;self.proxy=EgressProxy(policy)
        self.targets={};self.last={};self.sequence=0;self.latencies=[];self.errors=[]
        self.write_origin='';self.write_until=0;self.freeze_network=False;self.pending_dialog=None
        self.download_approved=False;self.downloads=[];self.screenshots=[];self.closed=False
        self.feed=None

    async def start(self):
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'runtime/browsers'))
        proxy=await self.proxy.start()
        self.pw=await async_playwright().start()
        launch={'headless':self.settings.headless,'proxy':{'server':proxy,'bypass':'<-loopback>'},'args':['--force-webrtc-ip-handling-policy=disable_non_proxied_udp']}
        if not Path(self.pw.chromium.executable_path).exists():launch['channel']='chrome'
        self.browser=await self.pw.chromium.launch(**launch)
        self.context=await self.browser.new_context(viewport={'width':1280,'height':800},accept_downloads=True,service_workers='block',permissions=[])
        self.context.set_default_timeout(self.settings.timeout_ms)
        self.context.set_default_navigation_timeout(self.settings.timeout_ms)
        await self.context.route('**/*',self._route)
        if hasattr(self.context,'route_web_socket'):
            await self.context.route_web_socket('**/*',lambda ws: ws.close())
        self.context.on('page',lambda page:asyncio.create_task(self._configure_page(page)))
        self.page=await self.context.new_page()
        await self._configure_page(self.page)

    async def _configure_page(self,page):
        if len(self.context.pages)>self.settings.max_tabs:
            await page.close();return
        if getattr(page,'_liquid_configured',False):return
        page._liquid_configured=True
        page.on('dialog',self._dialog)
        page.on('pageerror',lambda error:self.errors.append(redact(str(error))[:180]))
        page.on('download',lambda download:asyncio.create_task(self._download(download)))

    async def _dialog(self,dialog):
        if dialog.type=='alert':await dialog.dismiss()
        else:self.pending_dialog=dialog

    async def _download(self,download):
        if not self.download_approved:
            await download.cancel()
            self.store.event(self.task_id,'security',{'message':'An unsolicited download was cancelled.'})
            return
        self.download_approved=False
        path=await download.path()
        if not path:return
        path=Path(path)
        try:
            if path.stat().st_size>20*1024*1024:raise PolicyError('Download exceeds the 20 MB limit.')
            name=Path(download.suggested_filename).name
            record=self.store.artifact(self.task_id,'quarantine-'+name,'application/octet-stream',path.read_bytes())
            self.downloads.append(record)
        finally:path.unlink(missing_ok=True)

    async def _route(self,route,request):
        try:
            await self.policy.resolve(request.url,scoped=request.is_navigation_request())
            if self.freeze_network:
                raise PolicyError('Network is frozen while preparing form fields.')
            if request.method not in {'GET','HEAD','OPTIONS'}:
                if time.monotonic()>self.write_until or origin(request.url)!=self.write_origin:
                    raise PolicyError('A website write was blocked pending approval.')
            if self.write_origin and origin(request.url)!=self.write_origin and request.method not in {'GET','HEAD','OPTIONS'}:
                raise PolicyError('Cross-origin data transmission was blocked.')
            await route.continue_()
        except (PolicyError,ValueError) as exc:
            if request.is_navigation_request() or request.method not in {'GET','HEAD','OPTIONS'}:
                message=redact(str(exc))
                self.policy.blocked.append(message)
                self.store.event(self.task_id,'security',{'message':message,'url':redact(request.url.split('?')[0])})
            await route.abort('blockedbyclient')

    async def observe(self):
        if not self.page or self.page.is_closed():raise RuntimeError('Browser page closed.')
        self.targets={}
        data=await self.page.evaluate(DOM_SCRIPT)
        if urlsplit(self.page.url).hostname in {'www.youtube.com','youtube.com','m.youtube.com'}:
            script=(ROOT/'extension/youtube.js').read_text(encoding='utf-8')
            data['youtube']=await self.page.evaluate('() => {'+script+';return youtubeObservation();}')
        if self.feed and self.feed['url']==self.page.url:
            data={**data,**self.feed}
        frames=[]
        all_nodes=[]
        for fi,frame in enumerate(self.page.frames[:5]):
            try:
                fd=data if fi==0 else await frame.evaluate(DOM_SCRIPT)
                for node in fd['nodes']:
                    target=f'f{fi}e{node["index"]}'
                    node['id']=target;node['frame']=fi
                    self.targets[target]=(frame,node)
                    all_nodes.append(node)
                if fi:frames.append({'url':frame.url,'text':fd['text'][:2000]})
            except Exception:continue
        self.sequence+=1
        text=redact(data['text'])
        sid=hashlib.sha256((self.page.url+text[:12000]+json.dumps([(n['id'],n['name'],n['href']) for n in all_nodes])).encode()).hexdigest()[:20]
        self.last={**data,'text':text,'url':self.page.url,'nodes':all_nodes,'frames':frames,'snapshot_id':sid,'tabs':[{'index':i,'url':p.url} for i,p in enumerate(self.context.pages)],'errors':self.errors[-3:]}
        try:self.last['accessibility']=(await self.page.locator('body').aria_snapshot())[:14000]
        except Exception:self.last['accessibility']='Unavailable; semantic DOM inspection used.'
        self.store.update(self.task_id,active_url=self.page.url)
        return self.last

    def locator(self,target):
        if target not in self.targets:raise PolicyError('The element is absent from the current observation.')
        frame,node=self.targets[target]
        return frame.locator('[data-liquidpilot-id="'+str(node['index'])+'"]'),node,frame

    async def semantic_target(self,target):
        fallback,node,frame=self.locator(target)
        if node['role'] and node['name']:
            semantic=frame.get_by_role(node['role'],name=node['name'],exact=True)
            if await semantic.count()==1:
                locator=semantic
            else:locator=fallback
        else:locator=fallback
        if await locator.count()!=1 or not await locator.is_visible():raise PolicyError('The element changed or is no longer visible; observe again.')
        if node['href']:
            actual=await locator.get_attribute('href')
            from urllib.parse import urljoin
            if urljoin(frame.url,actual or '')!=node['href']:raise PolicyError('The link destination changed after observation.')
        return locator,node

    async def fingerprint(self):
        # Includes form values to invalidate approval if the prepared form changes.
        forms=await self.page.locator('form').evaluate_all('(forms)=>forms.map(f=>({action:f.action,method:f.method,fields:[...f.elements].map(e=>({name:e.name,type:e.type,value:e.type==="password"?"[private]":e.value,checked:e.checked}))}))')
        return hashlib.sha256(json.dumps({'url':self.page.url,'forms':forms},sort_keys=True).encode()).hexdigest()

    async def screenshot(self):
        mask=self.page.locator('input[type="password"],input[autocomplete="one-time-code"],input[name*="token" i]')
        image=await self.page.screenshot(type='jpeg',quality=65,full_page=False,mask=[mask],timeout=5000)
        record=self.store.artifact(self.task_id,f'browser-{self.sequence}-{time.time_ns()}.jpg','image/jpeg',image)
        self.screenshots.append(record['id'])
        # Bounded cache; exported bundles retain only currently registered screenshots.
        while len(self.screenshots)>8:
            aid=self.screenshots.pop(0)
            row=self.store.db.execute('SELECT sealed_name FROM artifacts WHERE id=?',(aid,)).fetchone()
            if row:
                (self.store.vault.root/row['sealed_name']).unlink(missing_ok=True)
                with self.store.db:self.store.db.execute('DELETE FROM artifacts WHERE id=?',(aid,))
        return record

    async def execute(self,action,approved=False):
        self.policy.require_action(action,approved)
        started=time.perf_counter()
        before=self.page.url
        result={}
        if action.snapshot_id and action.snapshot_id!=self.last.get('snapshot_id'):raise PolicyError('The action belongs to an old browser observation.')
        kind=action.kind
        target=None
        if action.target and kind not in {'switch_tab','dialog'}:target,node=await self.semantic_target(action.target)
        if kind in {'site_search_filters','site_play'}:
            script=(ROOT/'extension/youtube.js').read_text(encoding='utf-8')
            result=await self.page.evaluate('(kind) => {'+script+';return youtubeControl(kind);}',kind)
        elif kind in {'navigate','new_tab'}:
            self.feed=None
            await self.policy.resolve(action.url)
            if kind=='new_tab':
                if len(self.context.pages)>=self.settings.max_tabs:raise PolicyError('Tab limit reached.')
                self.page=await self.context.new_page()
            response=await self.page.goto(action.url,wait_until='domcontentloaded')
            await self.policy.resolve(self.page.url)
            if response and response.status>=400:raise RuntimeError(f'Page returned HTTP {response.status}.')
            result['status']=response.status if response else None
            if response and 'xml' in response.headers.get('content-type',''):
                import xml.etree.ElementTree as ET
                body=await response.body()
                if len(body)<2*1024*1024 and b'<!ENTITY' not in body and b'<!DOCTYPE' not in body:
                    try:
                        root=ET.fromstring(body)
                        items=root.findall('.//item')[:20]
                        if items:
                            nodes=[];paragraphs=[]
                            for i,item in enumerate(items):
                                title=item.findtext('title','');link=item.findtext('link','');description=item.findtext('description','')
                                paragraphs.append(title+'\n'+description+'\n'+link)
                                nodes.append({'index':i,'name':title,'role':'link','tag':'a','type':'','href':link,'disabled':False,'download':False,'options':[],'box':{}})
                            self.feed={'url':self.page.url,'title':root.findtext('./channel/title','Search results'),'text':'\n\n'.join(paragraphs),'paragraphs':paragraphs,'nodes':nodes,'tables':[],'meta':{},'ready':'complete'}
                    except ET.ParseError:pass
        elif kind in {'click','double_click','download'}:
            if approved:
                self.freeze_network=False;self.write_origin=origin(self.page.url);self.write_until=time.monotonic()+8
            if kind=='download':self.download_approved=True
            if kind=='double_click':await target.dblclick()
            else:await target.click()
            await self.page.wait_for_load_state('domcontentloaded',timeout=self.settings.timeout_ms)
        elif kind in {'type','clear','select','check'}:
            self.freeze_network=True
            if kind in {'type','clear'}:
                await target.fill(action.value if kind=='type' else '')
                result['verified']=await target.input_value()==(action.value if kind=='type' else '')
            elif kind=='select':
                await target.select_option(label=action.value)
                result['verified']=await target.locator('option:checked').inner_text()==action.value
            else:
                await target.set_checked(action.value.lower() not in {'false','0','no'})
                result['verified']=await target.is_checked()==(action.value.lower() not in {'false','0','no'})
            if not result['verified']:raise RuntimeError('The field did not retain the supplied value.')
        elif kind=='press':
            if action.value=='Enter' and not approved:raise PolicyError('Enter may submit a form and requires approval.')
            if approved:self.freeze_network=False;self.write_origin=origin(self.page.url);self.write_until=time.monotonic()+8
            await (target.press(action.value) if target else self.page.keyboard.press(action.value))
        elif kind=='hover':await target.hover()
        elif kind=='scroll':await self.page.mouse.wheel(0,600 if action.value!='up' else -600)
        elif kind=='back':await self.page.go_back(wait_until='domcontentloaded')
        elif kind=='forward':await self.page.go_forward(wait_until='domcontentloaded')
        elif kind=='switch_tab':
            index=int(action.target)
            if not 0<=index<len(self.context.pages):raise PolicyError('Unknown tab.')
            self.page=self.context.pages[index]
        elif kind=='close_tab':
            if len(self.context.pages)<=1:raise PolicyError('Cannot close the final task tab.')
            await self.page.close();self.page=self.context.pages[0]
        elif kind=='wait':
            if target:await target.wait_for(state='visible')
            else:await self.page.wait_for_load_state('domcontentloaded')
        elif kind=='upload':
            if not approved:raise PolicyError('Uploads require approval.')
            if action.value not in self.policy.spec.attachment_ids:raise PolicyError('The upload was not selected for this task.')
            info,data=self.store.get_upload(action.value)
            self.freeze_network=False;self.write_origin=origin(self.page.url);self.write_until=time.monotonic()+8
            await target.set_input_files({'name':info['name'],'mimeType':info['mime'],'buffer':data})
        elif kind=='dialog':
            if not self.pending_dialog:raise PolicyError('There is no pending dialog.')
            if approved and action.value=='accept':await self.pending_dialog.accept()
            else:await self.pending_dialog.dismiss()
            self.pending_dialog=None
        elif kind=='screenshot':result['artifact']=await self.screenshot()
        elif kind in {'extract','inspect'}:result['observation']=await self.observe()
        else:raise PolicyError('Unsupported browser action.')
        latency=round((time.perf_counter()-started)*1000,1);self.latencies.append(latency)
        result.update({'kind':kind,'before_url':before,'url':self.page.url,'latency_ms':latency,'ok':True})
        return result

    async def close(self):
        if self.closed:return
        self.closed=True
        if self.browser:await self.browser.close()
        if self.pw:await self.pw.stop()
        await self.proxy.close()
