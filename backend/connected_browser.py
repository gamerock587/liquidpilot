"""Existing-profile browser adapter. Never owns or closes the user's Chrome."""
import asyncio
import base64
import hashlib
import json
import time
from .chrome_bridge import bridge
from .security import PolicyError,redact

class ConnectedPage:
    def __init__(self,controller):self.controller=controller
    @property
    def url(self):return (bridge.tab or {}).get('url','')
    def is_closed(self):return not bridge.socket
    async def wait_for_load_state(self,*args,**kwargs):await asyncio.sleep(.3)
    def get_by_text(self,text,exact=False):
        controller=self.controller
        class TextWait:
            @property
            def first(self):return self
            async def wait_for(self,timeout=15000):
                deadline=time.monotonic()+timeout/1000
                while time.monotonic()<deadline:
                    if text in (await controller.observe())['text']:return
                    await asyncio.sleep(.3)
                raise TimeoutError('Expected confirmation text was not observed.')
        return TextWait()

class ConnectedBrowser:
    def __init__(self,settings,policy,store,task_id):
        self.settings=settings;self.policy=policy;self.store=store;self.task_id=task_id
        self.page=ConnectedPage(self);self.last={};self.latencies=[];self.errors=[];self.screenshots=[];self.sequence=0;self.tab_id=None

    async def start(self):
        if not bridge.socket or not bridge.tab:raise PolicyError('Connect a website tab through the LiquidPilot Chrome extension first.')
        self.tab_id=bridge.tab['id'];await self.check_tab()
        self.store.event(self.task_id,'browser',{'message':'Attached to your selected Chrome tab. Existing login is used. The tab stays open after completion.'})

    async def check_tab(self):
        if not bridge.tab or bridge.tab['id']!=self.tab_id:raise PolicyError('The connected tab changed. Stop this task and start a new one.')
        metadata=await bridge.request('metadata')
        if metadata['id']!=self.tab_id:raise PolicyError('The connected tab changed.')
        await self.policy.resolve(metadata['url'])
        bridge.tab=metadata

    async def observe(self):
        await self.check_tab();data=await bridge.request('observe',expected_url=self.page.url)
        await self.policy.resolve(data['url'])
        data['text']=redact(data['text']);self.sequence+=1
        data['snapshot_id']=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()[:20]
        data['tabs']=[{'index':0,'url':data['url']}];self.last=data
        self.store.update(self.task_id,active_url=data['url']);return data

    async def fingerprint(self):
        await self.check_tab();return hashlib.sha256((await bridge.request('fingerprint',expected_url=self.page.url)).encode()).hexdigest()

    async def screenshot(self):
        await self.check_tab();result=await bridge.request('screenshot',expected_url=self.page.url)
        record=self.store.artifact(self.task_id,f'chrome-{time.time_ns()}.jpg','image/jpeg',base64.b64decode(result['data']))
        self.screenshots.append(record['id']);return record

    async def execute(self,action,approved=False):
        await self.check_tab();self.policy.require_action(action,approved)
        if action.snapshot_id and action.snapshot_id!=self.last.get('snapshot_id'):raise PolicyError('The observation expired.')
        start=time.perf_counter();before=self.page.url
        if action.kind in {'extract','inspect'}:result={'observation':await self.observe()}
        elif action.kind=='screenshot':result={'artifact':await self.screenshot()}
        else:
            if action.kind in {'type','clear','select','check','click','double_click','press'} and not approved:
                raise PolicyError('Signed-in browser interactions require approval because websites may autosave.')
            if action.kind=='navigate':await self.policy.resolve(action.url)
            payload=action.model_dump();payload['expected_url']=self.last.get('url')
            if action.target:
                node=next((n for n in self.last.get('nodes',[]) if n['id']==action.target),None)
                if not node:raise PolicyError('Target absent from the observation.')
                if node.get('href'):await self.policy.resolve(node['href'])
                payload.update(expected_name=node['name'],expected_href=node.get('href',''))
            result=await bridge.request('action',action=payload,approved=approved,expected_url=self.page.url)
            await asyncio.sleep(.25)
            await self.check_tab()
        latency=round((time.perf_counter()-start)*1000,1);self.latencies.append(latency)
        return {**(result or {}),'kind':action.kind,'before_url':before,'url':self.page.url,'latency_ms':latency,'ok':True}

    async def close(self):
        # Leave the user's chosen tab and login in place for follow-up instructions.
        pass
