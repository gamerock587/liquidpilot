import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8')
from backend.config import Settings,ROOT
from backend.storage import Store
from backend.schemas import TaskSpec
from backend.agent import TaskRunner

async def main():
    settings=Settings(workspace=str(ROOT/'workspace/youtube-verification'),timeout_ms=20000)
    store=Store(settings.work)
    spec=TaskSpec(goal='search to me about wartune video, the last vieo publsih',workflow='navigate',seed_urls=['https://www.youtube.com/'],allowed_domains=['youtube.com'],max_steps=16)
    task=store.create(spec);runner=TaskRunner(settings,store,task['id'])
    await runner.run();result=store.get(task['id'])
    print(json.dumps({'state':result['state'],'issues':result['issues'],'video':result.get('video_result'),'metrics':result['metrics'],'actions':[e['message'] for e in store.events(task['id']) if e['kind']=='action']},ensure_ascii=False,indent=2))
    (settings.work/'latest-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    store.close()
asyncio.run(main())
