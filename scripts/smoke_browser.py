import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.config import Settings
from backend.storage import Store
from backend.schemas import TaskSpec,Action
from backend.security import Policy
from backend.browser import BrowserController

async def main():
    settings=Settings()
    store=Store(settings.work)
    spec=TaskSpec(goal='Inspect the example domain',seed_urls=['https://example.com'])
    task=store.create(spec)
    browser=BrowserController(settings,Policy(spec),store,task['id'])
    try:
        await browser.start()
        result=await browser.execute(Action(id='test',kind='navigate',url='https://example.com',description='Open example.com'))
        obs=await browser.observe()
        print(result)
        print(obs['title'],obs['text'][:300])
        assert 'Example Domain' in obs['title']
        print(await browser.screenshot())
    finally:
        await browser.close();store.close()

asyncio.run(main())
