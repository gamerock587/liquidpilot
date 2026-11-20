import asyncio
import json
import pytest
from backend.agent import TaskRunner,AgentManager
from backend.config import Settings
from backend.schemas import TaskSpec,State,Action,TERMINAL
from backend.storage import Store
from backend.security import PolicyError

@pytest.mark.live
async def test_form_task_pauses_then_verifies_exact_approved_submission(tmp_path,website):
    url,state=website;before=len(state['records'])
    settings=Settings(workspace=str(tmp_path),private_origins=[url],timeout_ms=5000)
    store=Store(tmp_path)
    spec=TaskSpec(goal='Fill the Name and Email fields with the supplied values, submit the record after approval, and verify Record created successfully.',workflow='form',mode='assisted',seed_urls=[url+'/form'],allowed_domains=['127.0.0.1'],allowed_actions=['navigate','type','click'],fields={'Name':'LiquidPilot Test','Email':'test@example.com'},success_text='Record created successfully',max_steps=10)
    task=store.create(spec);runner=TaskRunner(settings,store,task['id']);job=asyncio.create_task(runner.run())
    try:
        async def wait_approval():
            while store.get(task['id'])['state']!=State.WAITING_FOR_APPROVAL:
                if job.done():raise AssertionError(store.get(task['id']))
                await asyncio.sleep(.05)
        await asyncio.wait_for(wait_approval(),30)
        assert len(state['records'])==before
        pending=store.get(task['id'])['pending_approval'];assert pending['action']['requires_approval']
        await runner.browser.page.get_by_label('Name',exact=True).fill('Changed after preview')
        with pytest.raises(PolicyError):await runner.approve(pending['token'],True)
        await runner.browser.page.get_by_label('Name',exact=True).fill('LiquidPilot Test')
        await runner.approve(pending['token'],True)
        with pytest.raises(PolicyError):await runner.approve(pending['token'],True)
        await asyncio.wait_for(job,20)
        result=store.get(task['id'])
        assert result['state']==State.COMPLETED,result['issues']
        assert len(state['records'])==before+1
        assert state['records'][-1]['name']=='LiquidPilot Test'
    finally:
        if not job.done():runner.cancel();job.cancel();await asyncio.gather(job,return_exceptions=True)
        store.close()

@pytest.mark.live
async def test_d1_bounded_recovery_after_transient_navigation_failure(tmp_path,website):
    url,state=website;state['flaky']=0
    settings=Settings(workspace=str(tmp_path),private_origins=[url],timeout_ms=5000)
    store=Store(tmp_path);spec=TaskSpec(goal='Open the product catalogue. Retry temporary server failures once.',seed_urls=[url+'/flaky'],allowed_domains=['127.0.0.1'])
    task=store.create(spec);runner=TaskRunner(settings,store,task['id']);await runner.browser.start()
    action=Action(id='retry-test',kind='navigate',url=url+'/flaky',description='Open the product catalogue')
    try:
        with pytest.raises(RuntimeError):await runner.browser.execute(action)
        success=await runner.recover(action,RuntimeError('Temporary HTTP 503. The server explicitly asks for one retry.'))
        assert state['flaky']<=2
        assert success and 'Recovered page' in (await runner.browser.observe())['text']
        assert runner.recovery_attempts==1 and runner.recoveries==1
    finally:await runner.browser.close();store.close()

@pytest.mark.live
async def test_pause_and_cancel_are_durable(tmp_path,website):
    url,_=website;settings=Settings(workspace=str(tmp_path),private_origins=[url]);store=Store(tmp_path)
    manager=AgentManager(settings,store);task=manager.submit(TaskSpec(goal='Read the catalogue',seed_urls=[url]))
    await manager.control(task['id'],'pause')
    await asyncio.sleep(.15)
    assert store.get(task['id'])['paused'] is True
    await manager.control(task['id'],'cancel')
    await asyncio.gather(manager.jobs[task['id']],return_exceptions=True)
    assert store.get(task['id'])['state']==State.CANCELLED
    await manager.close();store.close()
