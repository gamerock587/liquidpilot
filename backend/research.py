import csv
import html
import io
import json
import re
import zipfile
from datetime import datetime,timezone
from urllib.parse import urlsplit,urlencode,parse_qs,urljoin
from .security import normalize_url,redact

STOPWORDS=set('the and for with from this that have into your find three sources explaining compare their claims give source urls please research open visit collect information about using official documentation me a an to of in on is it'.split())

def terms(text):return [x for x in re.findall(r'[\w-]+',text.lower()) if len(x)>2 and x not in STOPWORDS][:40]
def relevance(goal,text):
    wanted=set(terms(goal));found=set(terms(text))
    return len(wanted&found)/max(1,len(wanted))

def search_url(query,provider='duckduckgo',searxng=''):
    if provider=='bing-rss':return 'https://www.bing.com/search?'+urlencode({'q':query,'format':'rss'})
    if provider=='searxng' and searxng:return searxng.rstrip('/')+'/search?'+urlencode({'q':query})
    if provider=='bing':return 'https://www.bing.com/search?'+urlencode({'q':query})
    if provider=='google':return 'https://www.google.com/search?'+urlencode({'q':query})
    return 'https://html.duckduckgo.com/html/?'+urlencode({'q':query})

def clean_query(goal):
    result=re.sub(r'https?://\S+','',goal)
    result=re.sub(r'(?i)\b(find|give me|please|research|compare their claims|and give me the source urls|three reliable sources explaining)\b',' ',result)
    return re.sub(r'\s+',' ',result).strip(' ."')[:200] or goal[:200]

def unwrap_link(url):
    p=urlsplit(url);q=parse_qs(p.query)
    if p.hostname and p.hostname.endswith('duckduckgo.com') and 'uddg' in q:return q['uddg'][0]
    if p.hostname and p.hostname.endswith('google.com') and p.path=='/url':return q.get('q',q.get('url',[url]))[0]
    if p.hostname and p.hostname.endswith('bing.com') and p.path.startswith('/ck/'):
        import base64
        value=q.get('u',[''])[0]
        if value.startswith('a1'):
            try:return base64.urlsafe_b64decode(value[2:]+'===').decode()
            except Exception:pass
    return url

def is_search(url):
    p=urlsplit(url)
    return (p.hostname or '') in {'html.duckduckgo.com','duckduckgo.com','www.google.com','www.bing.com'} and ('search' in p.path or '/html' in p.path or bool(p.query))

def source_record(observation,goal,classification):
    text=observation['text']
    paragraphs=observation.get('paragraphs') or [x.strip() for x in text.split('\n') if len(x.strip())>45]
    substantive=[p for p in paragraphs if len(p)>60]
    if substantive:paragraphs=substantive
    ranked=sorted(enumerate(paragraphs),key=lambda item:(relevance(goal,item[1]),len(item[1])>80),reverse=True)
    selected=[];total=0
    for _,paragraph in ranked:
        paragraph=re.sub(r'\s+',' ',paragraph).strip()
        if len(paragraph)<25 or paragraph in selected:continue
        excerpt=paragraph[:220]
        if total+len(excerpt)>700:excerpt=excerpt[:700-total]
        if not excerpt:break
        selected.append(excerpt);total+=len(excerpt)
        if total>=700 or len(selected)>=4:break
    # Retrieval chunks stay encrypted unless the user explicitly enables public indexing.
    chunks=[text[i:i+1500] for i in range(0,min(len(text),24000),1300)]
    return {'url':normalize_url(observation['url']),'title':observation['title'],'domain':urlsplit(observation['url']).hostname,'accessed_at':datetime.now(timezone.utc).isoformat(),'publication_date':observation.get('meta',{}).get('publication_date') or None,'excerpts':selected,'chunks':chunks,'tables':observation.get('tables',[]),'evidence_status':'Observed in live browser; claims not independently established.','classification':classification,'relevant':classification.get('relevant',False),'uncertainty':'No independent fact-check or contradiction resolution. Undated pages are not assumed current.'}

def normalize_table(table):
    rows=table.get('rows',[])
    if not rows:return [],[]
    headers=[re.sub(r'\s+',' ',str(x)).strip() or f'column_{i+1}' for i,x in enumerate(rows[0])]
    seen={}
    for i,h in enumerate(headers):
        seen[h]=seen.get(h,0)+1
        if seen[h]>1:headers[i]=f'{h}_{seen[h]}'
    records=[]
    for row in rows[1:]:
        if not any(str(x).strip() for x in row):continue
        records.append({h:re.sub(r'\s+',' ',str(row[i])).strip() if i<len(row) else '' for i,h in enumerate(headers)})
    return headers,records

def safe_csv(value):
    value=str(value)
    return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value

def write_reports(store,task_id):
    task=store.get(task_id);sources=store.sources(task_id);events=store.events(task_id)
    goal=task['spec']['goal'];outcome=task.get('outcome') or {}
    plan=task.get('plan') or {}
    lines=['# LiquidPilot evidence report','',f'**Objective:** {goal}','',f'**Outcome:** {outcome.get("summary","Task ended.")}',f'**Status:** {task["state"]}','', 'This report is assembled deterministically from observed pages. It is not a generated research synthesis.','', '## Sources and observed claims','']
    for i,s in enumerate(sources,1):
        lines += [f'### [{i}] {s["title"]}',f'URL: {s["url"]}',f'Accessed: {s["accessed_at"]}',f'Publication date: {s["publication_date"] or "Not available"}',f'Type: {s["classification"].get("source_type","unclassified")} (model estimate)',f'Evidence: {s["evidence_status"]}','']
        lines += ['> '+quote.replace('\n',' ') for quote in s['excerpts']]
        lines += ['']
    lines+=['## Comparison and uncertainty','']
    words=set(terms(goal))
    if sources:
        lines+=['| Source | Relevant terms present in excerpts | Date available |','|---|---|---|']
        for i,s in enumerate(sources,1):
            found=sorted(words&set(terms(' '.join(s['excerpts']))))
            lines.append(f'| [{i}] | {", ".join(found) or "No direct term overlap"} | {"Yes" if s["publication_date"] else "No"} |')
    lines+=['','Term overlap is not agreement between sources. No missing facts are inferred.']
    for comparison in task.get('comparisons',[]):
        lines+=['',f'- {comparison.get("source_a","")} vs {comparison.get("source_b","")}: **{comparison.get("relationship","unavailable")}**. {comparison["status"]}.']
    if task.get('synthesis'):
        lines+=['','## Optional local-planner synthesis','', 'The following is generated analysis, not independently verified fact. Source labels map to the numbered sources above.','',task['synthesis']]
    lines+=['']+[f'- {x}' for x in plan.get('limitations',[])+task.get('issues',[])]+['','## Verification','',json.dumps(outcome,ensure_ascii=False,indent=2),'','## Performance','',json.dumps(task.get('metrics',{}),indent=2)]
    markdown='\n'.join(lines)
    store.artifact(task_id,'report.md','text/markdown',markdown.encode())
    document='<!doctype html><meta charset="utf-8"><title>LiquidPilot report</title><style>body{font:16px/1.7 system-ui;max-width:950px;margin:50px auto;padding:0 25px;color:#243042}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#2563eb}</style><h1>LiquidPilot evidence report</h1><pre>'+html.escape(markdown)+'</pre>'
    store.artifact(task_id,'report.html','text/html',document.encode())
    public_sources=[{k:v for k,v in s.items() if k!='chunks'} for s in sources]
    bundle={'task':task,'sources':public_sources,'events':events}
    store.artifact(task_id,'evidence.json','application/json',json.dumps(bundle,ensure_ascii=False,indent=2).encode())
    csv_buffer=io.StringIO(newline='')
    writer=csv.writer(csv_buffer)
    table_count=0
    for index,s in enumerate(sources):
        for ti,table in enumerate(s.get('tables',[])):
            headers,rows=normalize_table(table)
            if not rows:continue
            buffer=io.StringIO(newline='');csvwriter=csv.DictWriter(buffer,fieldnames=headers);csvwriter.writeheader()
            csvwriter.writerows({k:safe_csv(v) for k,v in row.items()} for row in rows)
            store.artifact(task_id,f'table-{index+1}-{ti+1}-{len(rows)}-rows.csv','text/csv',('\ufeff'+buffer.getvalue()).encode())
            table_count+=len(rows)
    writer.writerow(['title','url','domain','accessed_at','publication_date','evidence_status','excerpts'])
    for s in sources:writer.writerow([safe_csv(s.get(k) or '') for k in ('title','url','domain','accessed_at','publication_date','evidence_status')]+[safe_csv(' | '.join(s['excerpts']))])
    store.artifact(task_id,'sources.csv','text/csv',('\ufeff'+csv_buffer.getvalue()).encode())
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for record in store.artifacts(task_id):
            if record['name'].startswith('quarantine-'):continue
            _,content=store.read_artifact(record['id']);z.writestr(record['name'],content)
    store.artifact(task_id,'evidence-bundle.zip','application/zip',archive.getvalue())
    return table_count
