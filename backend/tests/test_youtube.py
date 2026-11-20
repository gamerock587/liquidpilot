import pytest
from backend.youtube import search_topic,age_seconds,matching_videos,video_intent
from backend.agent import TaskRunner
from backend.config import Settings
from backend.schemas import TaskSpec
from backend.storage import Store
from backend.security import Policy,PolicyError
from backend.schemas import Action

@pytest.mark.parametrize('goal',['search to me about wartune video, the last vieo publsih','in search bar, search to me about wartune game, and run to me the last video published','Find the newest Wartune video on YouTube'])
def test_actual_failed_instructions_extract_the_topic(goal):assert search_topic(goal)=='wartune'

def test_recency_uses_dates_not_rank_and_rejects_unrelated_cards():
    videos=[{'title':'Wartune old','url':'https://www.youtube.com/watch?v=old','metadata':'1y ago'}, {'title':'Music new','url':'https://www.youtube.com/watch?v=music','metadata':'1 min ago'}, {'title':'Wartune new','url':'https://www.youtube.com/watch?v=new','metadata':'3\xa0min ago'}, {'title':'Wartune live','url':'https://www.youtube.com/watch?v=live','metadata':'LIVE'}, {'title':'Wartune channel','url':'https://www.youtube.com/@wartune','metadata':'1 min ago'}]
    result=matching_videos(videos,'wartune')
    assert [x['title'] for x in result]==['Wartune new','Wartune old']
    assert age_seconds('Streamed 15 min ago')==900
    assert age_seconds('19h ago')==68400
    assert age_seconds('No publication date') is None
    assert video_intent('latest video','https://www.youtube.com/')
    assert not video_intent('latest video','https://notyoutube.com/')

def test_explicit_playback_requires_a_user_play_request():
    action=Action(id='play',kind='site_play',description='Play selected video')
    with pytest.raises(PolicyError):Policy(TaskSpec(goal='Find a Wartune video')).require_action(action)
    Policy(TaskSpec(goal='Play the latest Wartune video')).require_action(action)

async def test_homepage_recommendations_are_not_valid_navigation_candidates(tmp_path):
    store=Store(tmp_path)
    spec=TaskSpec(goal='Find wartune',browser_mode='chrome',workflow='navigate')
    task=store.create(spec);runner=TaskRunner(Settings(workspace=str(tmp_path)),store,task['id']);runner.workflow='navigate'
    async def allowed(url):return True
    runner.policy.allows=allowed
    obs={'url':'https://www.youtube.com/','snapshot_id':'sample','text':'','nodes':[{'role':'link','name':'Awakening Music','href':'https://www.youtube.com/@awakeningrecords','download':False}]}
    actions=await runner.candidates(obs,[])
    assert not any(a.kind=='navigate' for a in actions)
    store.close()
