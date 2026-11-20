import asyncio
import json
import os
import shutil
import socket
from pathlib import Path
import pytest
import uvicorn
from playwright.async_api import async_playwright
from backend.chrome_bridge import ChromeBridge,bridge
from backend.api import create_app
from backend.config import Settings,ROOT
from backend.connected_browser import ConnectedBrowser
from backend.schemas import TaskSpec,Action
from backend.security import Policy,PolicyError
from backend.agent import TaskRunner

def test_pairing_codes_are_single_use_and_reconnect_requires_token():
    b=ChromeBridge();code=b.pairing()
    assert not b.authenticate('wrong')
    assert b.authenticate(code)
    assert not b.authenticate(code)
    assert b.authenticate(b.session_token)
    b.pairing();b.pair_until=0
    assert not b.authenticate(b.pair_code)

@pytest.mark.live
async def test_real_extension_existing_tab_form_and_disconnect(tmp_path,website):
    url,state=website
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    settings=Settings(port=port,workspace=str(tmp_path/'workspace'),private_origins=[url])
    app=create_app(settings);store=app.state.store
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    server_job=asyncio.create_task(server.serve())
    while not server.started:await asyncio.sleep(.05)
    ext=tmp_path/'extension';shutil.copytree(ROOT/'extension',ext)
    worker=ext/'worker.js';worker.write_text(worker.read_text().replace('127.0.0.1:7870',f'127.0.0.1:{port}'))
    exe=Path(os.environ['LOCALAPPDATA'])/'ms-playwright/chromium-1223/chrome-win64/chrome.exe'
    browser=None
    try:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch_persistent_context(str(tmp_path/'profile'),executable_path=str(exe),headless=True,args=[f'--disable-extensions-except={ext}',f'--load-extension={ext}'])
            page=await browser.new_page();await page.goto(url+'/form')
            other=await browser.new_page();await other.goto(url+'/products')
            worker=browser.service_workers[0] if browser.service_workers else await browser.wait_for_event('serviceworker')
            code=bridge.pairing()
            await worker.evaluate('''async ({url,code})=>{const tabs=await chrome.tabs.query({});const tab=tabs.find(t=>t.url===url);await connect(tab.id,code);}''',{'url':url+'/form','code':code})
            while not bridge.tab:await asyncio.sleep(.05)
            spec=TaskSpec(goal='Prepare the demonstration record',browser_mode='chrome',mode='assisted',workflow='form',fields={'Name':'Connector Test'},allowed_domains=['127.0.0.1'],allowed_actions=['type','click','navigate','extract'])
            task=store.create(spec);controller=ConnectedBrowser(settings,Policy(spec,[url]),store,task['id'])
            await controller.start();obs=await controller.observe()
            assert obs['url']==url+'/form' and any(n['name']=='Name' for n in obs['nodes'])
            name=next(n for n in obs['nodes'] if n['name']=='Name')
            action=Action(id='fill',kind='type',description='Fill Name',target=name['id'],value='Connector Test',snapshot_id=obs['snapshot_id'],requires_approval=True)
            with pytest.raises(PolicyError):await controller.execute(action)
            initial=await controller.fingerprint()
            result=await controller.execute(action,True);assert result['verified']
            assert await page.get_by_label('Name',exact=True).input_value()=='Connector Test'
            assert initial!=await controller.fingerprint()
            shot=await controller.screenshot();assert shot['size']>1000
            obs=await controller.observe();button=next(n for n in obs['nodes'] if n['name']=='Submit record')
            before=len(state['records'])
            await controller.execute(Action(id='submit',kind='click',description='Submit controlled test record',target=button['id'],snapshot_id=obs['snapshot_id'],requires_approval=True),True)
            await page.wait_for_url('**/records');assert len(state['records'])==before+1
            assert other.url==url+'/products'
            await controller.close();assert not page.is_closed()
            await page.goto(url+'/')
            task2=store.create(TaskSpec(goal='Find the product specifications and prices table, and export its three product rows.',browser_mode='chrome',workflow='extract',mode='observe',allowed_domains=['127.0.0.1'],source_target=1,max_steps=12))
            runner=TaskRunner(settings,store,task2['id']);await runner.run()
            completed=store.get(task2['id'])
            assert completed['state']=='COMPLETED',completed.get('issues')
            assert completed['metrics']['table_rows']==3
            assert completed['metrics']['d1_calls']>0
            assert not page.is_closed() and other.url==url+'/products'
            if os.environ.get('LP_YOUTUBE_LIVE')=='1':
                await page.goto('https://www.youtube.com/',wait_until='domcontentloaded')
                task3=store.create(TaskSpec(goal='search to me about wartune video, the last vieo publsih',browser_mode='chrome',workflow='navigate',allowed_domains=['youtube.com'],max_steps=16))
                youtube_runner=TaskRunner(settings,store,task3['id']);await youtube_runner.run()
                youtube_task=store.get(task3['id'])
                assert youtube_task['state']=='COMPLETED',youtube_task['issues']
                assert youtube_task['video_result']['compared']>=1
                assert 'wartune' in youtube_task['video_result']['title'].lower()
                assert other.url==url+'/products'
                (ROOT/'workspace/youtube-connector-result.json').write_text(json.dumps(youtube_task,ensure_ascii=False,indent=2),encoding='utf-8')
            await worker.evaluate('disconnect()');await asyncio.sleep(.1)
            with pytest.raises(PolicyError):await controller.observe()
            await browser.close();browser=None
    finally:
        if browser:
            try:await browser.close()
            except Exception:pass
        server.should_exit=True;await server_job
