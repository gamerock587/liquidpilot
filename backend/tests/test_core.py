import json
from pathlib import Path
import pytest
from backend.schemas import TaskSpec,Action,State
from backend.config import Settings
from backend.security import Policy,PolicyError,Vault
from backend.storage import Store
from backend.research import normalize_table,safe_csv,unwrap_link,source_record,write_reports
from backend.models import D1,ModelError,LocalPlanner

@pytest.mark.parametrize('url',['file:///C:/private.txt','javascript:alert(1)','http://127.0.0.1/admin','http://[::1]/','http://169.254.169.254/','http://localhost:8081/','http://user:pass@example.com/'])
async def test_unsafe_urls_rejected(url):
    with pytest.raises((PolicyError,ValueError)):await Policy(TaskSpec(goal='Read public documentation')).resolve(url)

async def test_scoped_public_destination():
    policy=Policy(TaskSpec(goal='Read example documentation',allowed_domains=['example.com']))
    assert await policy.allows('https://example.com')
    assert not await policy.allows('https://wikipedia.org')

def test_action_scopes_and_approvals():
    spec=TaskSpec(goal='Fill a controlled form',mode='assisted',allowed_actions=['type','click'])
    policy=Policy(spec)
    with pytest.raises(PolicyError):policy.require_action(Action(id='x',kind='click',description='Submit',requires_approval=False))
    policy.require_action(Action(id='x',kind='click',description='Submit'),True)
    with pytest.raises(PolicyError):policy.require_action(Action(id='x',kind='upload',description='Upload'),True)
    with pytest.raises(PolicyError):Policy(TaskSpec(goal='Observe only')).require_action(Action(id='x',kind='type',description='Change a value'))

def test_local_only_planner():
    with pytest.raises(ValueError):Settings(planner_url='https://third-party-ai.example')

def test_encrypted_store_and_terminal_state(tmp_path):
    store=Store(tmp_path)
    task=store.create(TaskSpec(goal='Unique private task marker 9786'))
    artifact=store.artifact(task['id'],'report.txt','text/plain',b'confidential report marker')
    assert store.read_artifact(artifact['id'])[1]==b'confidential report marker'
    assert 'Unique private' not in store.db.execute('SELECT payload FROM tasks').fetchone()[0]
    assert b'confidential report' not in (store.vault.root/(artifact['id']+'.sealed')).read_bytes()
    store.transition(task['id'],State.COMPLETED,'Verified.')
    with pytest.raises(ValueError):store.transition(task['id'],State.BROWSING,'Illegal replay')
    store.forget(task['id'])
    with pytest.raises(KeyError):store.get(task['id'])
    with pytest.raises(PolicyError):store.vault.file('../outside',b'no')
    store.close()

def test_restart_invalidates_approval(tmp_path):
    store=Store(tmp_path);task=store.create(TaskSpec(goal='Prepare a private form'))
    store.update(task['id'],state=State.WAITING_FOR_APPROVAL,pending_approval={'token':'old'})
    store.recover_interrupted();task=store.get(task['id'])
    assert task['state']==State.PAUSED and task['pending_approval'] is None
    store.close()

def test_table_normalization_and_formula_protection():
    headers,rows=normalize_table({'rows':[[' Name ','Price'],[' A  B ','=HYPERLINK("evil")'],['','']]})
    assert headers==['Name','Price'] and len(rows)==1 and rows[0]['Name']=='A B'
    assert safe_csv(rows[0]['Price']).startswith("'=")
    assert unwrap_link('https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com')=='https://example.com'

async def test_missing_planner_is_explicit():
    plan=await LocalPlanner(Settings()).plan(TaskSpec(goal='Research database features'),'research')
    assert 'No generative planner' in plan.limitations[0]

@pytest.mark.live
async def test_live_native_decision_schemas():
    d1=D1(Settings());assert await d1.health()
    result=await d1.decide('The customer was charged twice and wants a refund.',{
        'refund':{'type':'noul','instructions':'Is a refund requested?'},
        'team':{'type':'choice','instructions':'Which team handles this?','criteria':{'billing':'Payments and refunds','technical':'Software faults'}},
        'urgency':{'type':'score','instructions':'Rate urgency','criteria':['Low','Medium','High']}})
    assert result['answers']['refund']['noul']>.5
    assert result['answers']['team']['choice']=='billing'
    assert 0<=result['answers']['urgency']['score']<=2
