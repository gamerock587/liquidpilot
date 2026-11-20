import asyncio,json,sys
from pathlib import Path
from playwright.async_api import async_playwright
sys.stdout.reconfigure(encoding='utf-8')
async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='chrome',headless=True)
        page=await browser.new_page()
        await page.goto('https://www.youtube.com/results?search_query=wartune&sp=CAI%253D',wait_until='domcontentloaded',timeout=30000)
        await page.wait_for_selector('ytd-video-renderer',timeout=20000)
        await page.get_by_role('button',name='Search filters',exact=True).click()
        link=await page.get_by_role('link',name='Today',exact=True).get_attribute('href')
        await page.goto('https://www.youtube.com'+link,wait_until='domcontentloaded')
        await page.wait_for_selector('ytd-video-renderer')
        print(json.dumps(await page.locator('ytd-video-renderer').evaluate_all('''es=>es.slice(0,20).map(e=>({text:e.innerText,title:e.querySelector('#video-title')?.textContent,url:e.querySelector('#video-title')?.href}))'''),ensure_ascii=False))
        await page.screenshot(path='workspace/youtube-inspect.jpg')
        await browser.close()
asyncio.run(main())
