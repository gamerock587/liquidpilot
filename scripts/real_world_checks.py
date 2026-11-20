import asyncio,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8')
from backend.config import Settings
from backend.schemas import TaskSpec
from backend.storage import Store
from backend.agent import TaskRunner

async def main():
    root=Path(__file__).resolve().parents[1]/'workspace'/'real-world-verification'
    settings=Settings(workspace=str(root),timeout_ms=15000,search_provider='bing-rss')
    store=Store(root)
    tests=[
       ('A_research',TaskSpec(goal='Find three reliable sources explaining PostgreSQL features, compare their claims, and give me the source URLs.',workflow='research',source_target=3,max_steps=22,queries=['PostgreSQL features'],seed_urls=['https://www.postgresql.org/about','https://www.postgresql.org/docs/current/features.html','https://www.geeksforgeeks.org/postgresql/introduction-to-postgresql/'])),
       ('B_navigation',TaskSpec(goal='Open Laravel documentation, find authentication information, and identify the relevant documentation section.',workflow='navigate',seed_urls=['https://laravel.com/docs'],allowed_domains=['laravel.com'],source_target=1,max_steps=12))]
    results=[]
    for name,spec in tests:
        task=store.create(spec);runner=TaskRunner(settings,store,task['id'])
        print('Starting '+name+' '+task['id'],flush=True)
        job=asyncio.create_task(runner.run())
        while not job.done():
            if store.get(task['id'])['state']=='WAITING_FOR_APPROVAL':
                runner.cancel('Verification harness stopped at a human-verification checkpoint. No CAPTCHA or access control was bypassed.');job.cancel()
                break
            await asyncio.sleep(.2)
        await asyncio.gather(job,return_exceptions=True)
        result=store.get(task['id']);events=store.events(task['id'])
        (root/(name+'.json')).write_text(json.dumps({'task':result,'events':events,'sources':store.sources(task['id'])},indent=2),encoding='utf-8')
        results.append({'test':name,'state':result['state'],'metrics':result['metrics'],'outcome':result['outcome'],'issues':result['issues']})
        print(json.dumps(results[-1]),flush=True)
    (root/'summary.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    store.close()

asyncio.run(main())
