import asyncio,json,sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='chrome',headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        await page.goto('http://127.0.0.1:7870')
        await page.get_by_text('Local engine online',exact=True).wait_for()
        await page.screenshot(path=str(ROOT/'workspace/ui-desktop.jpg'),type='jpeg',quality=85,full_page=True)
        await page.get_by_role('button',name='Toggle color theme').click()
        await page.screenshot(path=str(ROOT/'workspace/ui-light.jpg'),type='jpeg',quality=85,full_page=True)
        await page.get_by_role('button',name='Toggle color theme').click()
        await page.get_by_role('button',name='Task scope').click()
        assert await page.get_by_text('Starting URLs',exact=False).is_visible()
        await page.get_by_role('button',name='Task scope').click()
        await page.set_viewport_size({'width':390,'height':844})
        await page.screenshot(path=str(ROOT/'workspace/ui-mobile.jpg'),type='jpeg',quality=85,full_page=True)
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        assert not errors,errors
        print(json.dumps({'desktop':True,'light_theme':True,'mobile_no_overflow':True,'console_errors':errors}))
        await browser.close()

asyncio.run(main())
