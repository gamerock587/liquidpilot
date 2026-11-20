from pathlib import Path
p=Path('frontend/src/App.tsx');s=p.read_text(encoding='utf-8')
s=s.replace('sources?:any[];artifacts?:any[]','sources?:any[];artifacts?:any[];video_result?:any')
s=s.replace("const [browserMode,setBrowserMode]=useState('chrome')", "const [searchQuery,setSearchQuery]=useState('');\n const [browserMode,setBrowserMode]=useState('chrome')")
s=s.replace('JSON.stringify({goal,mode,browser_mode:', 'JSON.stringify({goal,mode,queries:searchQuery.trim()?[searchQuery.trim()]:[],browser_mode:')
s=s.replace('<label>Starting URLs <small>', '<label>Search query <small>Optional: topic words only; for example Wartune</small><input value={searchQuery} onChange={e=>setSearchQuery(e.target.value)} placeholder="Wartune"/></label><label>Starting URLs <small>')
needle='      {!!task.sources?.length&&<>'
replacement='''      {task.video_result&&<article className="video-result"><div className="eyebrow">VERIFIED VIDEO RESULT</div><h3><a href={task.video_result.url} target="_blank" rel="noreferrer">{task.video_result.title}<ExternalLink size={15}/></a></h3><p>{task.video_result.channel}</p><p>{task.video_result.published}</p><small>Compared {task.video_result.compared} dated matches · {task.video_result.scope}<br/>{task.video_result.limitation}</small></article>}
'''+needle
s=s.replace(needle,replacement)
p.write_text(s,encoding='utf-8')
p=Path('frontend/src/style.css');p.write_text(p.read_text(encoding='utf-8')+'\n.video-result{padding:20px;border:1px solid #427561;border-radius:12px;background:#75dbac0b;margin:20px 0}.video-result h3{font-size:18px;line-height:1.5}.video-result a{color:inherit;display:flex;gap:12px}.video-result p{font-size:12px;line-height:1.6}.video-result small{opacity:.65;line-height:1.8}\n',encoding='utf-8')
