import asyncio
import json
import pytest
from backend.schemas import TaskSpec,Action,State
from backend.config import Settings
from backend.security import Policy,PolicyError
from backend.storage import Store
from backend.browser import BrowserController
from backend.agent import TaskRunner

async def make_browser(tmp_path,website,mode='observe'):
    url,state=website
    spec=TaskSpec(goal='Read the product catalogue',mode=mode,allowed_domains=['127.0.0.1'],allowed_actions=['navigate','extract','scroll','wait','back','forward','type','clear','select','check','click','double_click','press','hover','new_tab','switch_tab','close_tab','upload','dialog'])
    settings=Settings(workspace=str(tmp_path),private_origins=[url],timeout_ms=5000)
    store=Store(tmp_path);task=store.create(spec)
    browser=BrowserController(settings,Policy(spec,[url]),store,task['id']);await browser.start()
    return browser,store,task,spec

async def test_real_navigation_dom_table_screenshot_and_tabs(tmp_path,website):
    url,_=website;b,s,t,spec=await make_browser(tmp_path,website)
    try:
        await b.execute(Action(id='1',kind='navigate',url=url,description='Open catalogue'))
        obs=await b.observe();link=next(n for n in obs['nodes'] if n['name']=='View product catalogue')
        # Changing an implementation ID does not defeat the semantic target.
        await b.page.get_by_role('link',name='View product catalogue').evaluate('(e)=>e.id="changed-by-fixture"')
        locator,_=await b.semantic_target(link['id']);assert await locator.inner_text()=='View product catalogue'
        await b.execute(Action(id='2',kind='navigate',url=url+'/catalogue',description='Open section'))
        await b.execute(Action(id='3',kind='navigate',url=url+'/products',description='Read products'))
        obs=await b.observe();assert len(obs['tables'][0]['rows'])==4
        assert 'Atlas Keyboard' in obs['accessibility']
        shot=await b.screenshot();assert s.read_artifact(shot['id'])[1][:2]==b'\xff\xd8'
        await b.execute(Action(id='4',kind='new_tab',url=url+'/slow',description='Open delayed page'))
        assert 'Loaded after delay' in (await b.observe())['text']
        await b.execute(Action(id='5',kind='switch_tab',target='0',description='Return to product table'))
        assert b.page.url.endswith('/products')
        await b.execute(Action(id='6',kind='close_tab',description='Close tab'))
        assert len(b.context.pages)==1
    finally:await b.close();s.close()

async def test_form_preparation_blocks_submission_without_approval(tmp_path,website):
    url,state=website;before=len(state['records']);b,s,t,spec=await make_browser(tmp_path,website,'assisted')
    try:
        await b.execute(Action(id='1',kind='navigate',url=url+'/form',description='Prepare form'))
        obs=await b.observe();name=next(n for n in obs['nodes'] if n['name']=='Name')
        await b.execute(Action(id='2',kind='type',target=name['id'],value='Test Operator',description='Fill name'))
        assert await b.page.get_by_label('Name',exact=True).input_value()=='Test Operator'
        obs=await b.observe();submit=next(n for n in obs['nodes'] if n['name']=='Submit record')
        action=Action(id='3',kind='click',target=submit['id'],requires_approval=True,description='Submit record')
        with pytest.raises(PolicyError):await b.execute(action)
        assert len(state['records'])==before
        await b.execute(action,approved=True)
        assert 'Record created successfully' in (await b.observe())['text']
        assert len(state['records'])==before+1
    finally:await b.close();s.close()

async def test_malicious_page_cannot_expand_scope(tmp_path,website):
    url,state=website;posts=state['posts'];b,s,t,spec=await make_browser(tmp_path,website)
    try:
        await b.execute(Action(id='1',kind='navigate',url=url+'/malicious',description='Observe adversarial page'))
        await b.observe()
        assert not await b.policy.allows('http://127.0.0.1:8081/admin')
        assert not await b.policy.allows('file:///C:/private/passwords.txt')
        with pytest.raises(PolicyError):await b.execute(Action(id='2',kind='upload',target='invented',value='C:/private/passwords.txt',description='Injected upload'),True)
        assert state['posts']==posts
        assert any(e['kind']=='security' for e in s.events(t['id']))
    finally:await b.close();s.close()

@pytest.mark.live
async def test_d1_controlled_extraction_and_csv(tmp_path,website):
    url,_=website
    settings=Settings(workspace=str(tmp_path),private_origins=[url],timeout_ms=5000)
    s=Store(tmp_path);spec=TaskSpec(goal='Find the product specifications table, extract all three product rows with prices, and export CSV.',workflow='extract',seed_urls=[url],allowed_domains=['127.0.0.1'],max_steps=14)
    t=s.create(spec);runner=TaskRunner(settings,s,t['id']);await runner.run()
    result=s.get(t['id'])
    assert result['state']==State.COMPLETED,result.get('issues')
    assert result['outcome']['table_rows']==3
    csvs=[a for a in s.artifacts(t['id']) if a['name'].startswith('table-')]
    assert csvs and 'Atlas Keyboard' in s.read_artifact(csvs[0]['id'])[1].decode('utf-8-sig')
    decisions=[e for e in s.events(t['id']) if e['kind']=='decision' and e.get('phase')=='action']
    assert len(decisions)>=3
    assert all(e['selected_action']['id'] in {a['id'] for a in e['available_actions']} for e in decisions)
    (tmp_path/'verification.json').write_text(json.dumps({'task':result,'events':s.events(t['id'])},indent=2))
    s.close()
