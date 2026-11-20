function observePage(){
  const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';};
  const elements=[...document.querySelectorAll('a[href],button,input,textarea,select,[role="button"],[role="link"]')].filter(visible).slice(0,120);
  const nodes=elements.map((el,i)=>{
    el.setAttribute('data-liquidpilot-id',String(i));const tag=el.tagName.toLowerCase(),type=el.getAttribute('type')||'';
    const name=(el.getAttribute('aria-label')||el.labels?.[0]?.innerText||el.innerText||el.getAttribute('placeholder')||el.getAttribute('name')||'').trim().replace(/\s+/g,' ').slice(0,140);
    const role=el.getAttribute('role')||(tag==='a'?'link':tag==='button'?'button':tag==='select'?'combobox':type==='checkbox'?'checkbox':type==='radio'?'radio':['input','textarea'].includes(tag)?'textbox':'');
    const r=el.getBoundingClientRect();return {id:'e'+i,index:i,name,role,tag,type,href:tag==='a'?el.href:'',disabled:!!el.disabled,download:el.hasAttribute('download'),box:{x:r.x,y:r.y,width:r.width,height:r.height},options:tag==='select'?[...el.options].slice(0,30).map(o=>({label:o.label,value:o.value})):[]};
  }).filter(n=>!['password','hidden'].includes(n.type)&&!n.disabled);
  const paragraphs=[...document.querySelectorAll('p,h1,h2,h3,main li,article li')].filter(visible).map(e=>e.innerText.trim()).filter(Boolean).slice(0,160);
  const tables=[...document.querySelectorAll('table')].filter(visible).slice(0,5).map(t=>({rows:[...t.rows].slice(0,251).map(r=>[...r.cells].map(c=>c.innerText.trim())),total_rows:t.rows.length}));
  return {title:document.title,url:location.href,text:document.body?.innerText?.slice(0,60000)||'',paragraphs,nodes,tables,meta:{description:document.querySelector('meta[name="description"]')?.content||''},ready:document.readyState,frames:[],errors:[],accessibility:'Semantic DOM from the selected Chrome tab.'};
}
function fingerprintPage(){
  return JSON.stringify({url:location.href,forms:[...document.forms].map(f=>({action:f.action,method:f.method,fields:[...f.elements].map(e=>({name:e.name,type:e.type,value:e.type==='password'?'[private]':e.value,checked:e.checked}))}))});
}
function maskSecrets(enable){
  const id='liquidpilot-private-mask';document.getElementById(id)?.remove();
  if(enable){const style=document.createElement('style');style.id=id;style.textContent='input[type=password],input[autocomplete=one-time-code],input[name*=token i]{visibility:hidden!important}';document.documentElement.appendChild(style);}
}
function interactPage(a){
  const el=a.target?document.querySelector('[data-liquidpilot-id="'+String(a.target).replace(/^e/,'')+'"]'):null;
  if(a.expected_url&&location.href!==a.expected_url)throw Error('The page changed; observe again.');
  if(a.target){
    if(!el||!el.getBoundingClientRect().width||!el.getBoundingClientRect().height||el.disabled)throw Error('The target is no longer available.');
    const name=(el.getAttribute('aria-label')||el.labels?.[0]?.innerText||el.innerText||el.getAttribute('placeholder')||el.getAttribute('name')||'').trim().replace(/\s+/g,' ').slice(0,140);
    if(name!==a.expected_name||(a.expected_href&&el.href!==a.expected_href))throw Error('The target changed; observe again.');
    if(el.type==='password'||el.autocomplete==='one-time-code')throw Error('Enter credentials manually.');
  }
  if(a.kind==='click')el.click();
  else if(a.kind==='double_click'){el.click();el.dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));}
  else if(a.kind==='hover')el.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));
  else if(a.kind==='scroll')window.scrollBy({top:a.value==='up'?-600:600,behavior:'instant'});
  else if(['type','clear'].includes(a.kind)){
    if(!['INPUT','TEXTAREA'].includes(el.tagName))throw Error('This target is not a text field.');
    const value=a.kind==='clear'?'':a.value;
    const prototype=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype,'value').set.call(el,value);
    el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));
    return {verified:el.value===value};
  }else if(a.kind==='select'){
    const option=[...el.options].find(o=>o.label===a.value);if(!option)throw Error('Option not found.');el.value=option.value;el.dispatchEvent(new Event('change',{bubbles:true}));return {verified:el.value===option.value};
  }else if(a.kind==='check'){
    const checked=!['false','0','no'].includes(a.value.toLowerCase());if(el.checked!==checked)el.click();return {verified:el.checked===checked};
  }else if(a.kind==='press'){
    if(a.value==='Enter'&&el?.form)el.form.requestSubmit();
    else if(a.value==='Escape')document.activeElement?.blur();
    else throw Error('Use an observed button instead of this keyboard command.');
  }else if(!['click','double_click','hover','scroll'].includes(a.kind))throw Error('Unsupported operation.');
  return {ok:true};
}
