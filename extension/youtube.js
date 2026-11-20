// Fixed site adapter: visible results and read-only search/media controls only.
function youtubeObservation(){
  if(!['www.youtube.com','youtube.com','m.youtube.com'].includes(location.hostname))return null;
  const visible=e=>!!(e&&e.getBoundingClientRect().width&&e.getBoundingClientRect().height);
  const filters=[...document.querySelectorAll('ytd-search-filter-renderer a')].filter(visible).map(e=>({label:e.innerText.trim(),url:e.href,selected:e.closest('ytd-search-filter-renderer')?.hasAttribute('selected')}));
  const videos=[...document.querySelectorAll('ytd-video-renderer')].filter(visible).slice(0,50).map(e=>{
    const a=e.querySelector('a#video-title');
    return {title:a?.textContent?.trim()||'',url:a?.href||'',channel:e.querySelector('ytd-channel-name a')?.textContent?.trim()||'',metadata:[...e.querySelectorAll('#metadata-line span')].map(x=>x.innerText).join(' · '),text:e.innerText.slice(0,1400)};
  }).filter(v=>v.title&&v.url);
  const player=document.querySelector('video');
  return {filters,videos,no_results:!!document.querySelector('ytd-background-promo-renderer'),watch:{title:document.querySelector('ytd-watch-metadata h1')?.innerText||'',published:document.querySelector('meta[itemprop="uploadDate"]')?.content||document.querySelector('meta[itemprop="datePublished"]')?.content||'',playing:!!player&&!player.paused&&!player.ended}};
}
async function youtubeControl(kind){
  if(!['www.youtube.com','youtube.com','m.youtube.com'].includes(location.hostname))throw Error('YouTube-only operation.');
  if(kind==='site_search_filters'){
    const button=document.querySelector('ytd-search-sub-menu-renderer button[aria-label],button[aria-label="Search filters"]');
    if(!button||location.pathname!=='/results')throw Error('YouTube search filters are not available.');
    button.click();await new Promise(r=>setTimeout(r,350));return {ok:true};
  }
  if(kind==='site_play'){
    const video=document.querySelector('video');if(location.pathname!=='/watch'||!video)throw Error('No selected video player.');
    await video.play();return {ok:!video.paused};
  }
  throw Error('Unknown YouTube control.');
}
