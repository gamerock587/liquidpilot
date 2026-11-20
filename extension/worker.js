/* Only fixed operations exist here. The model cannot supply JavaScript or CDP methods. */
importScripts('page.js','youtube.js');
let socket=null,selected=null,attached=false,heartbeat=null;
const cdp=(method,params={})=>chrome.debugger.sendCommand({tabId:selected.id},method,params);
function send(value){if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify(value));}
async function disconnect(){
  clearInterval(heartbeat);heartbeat=null;
  if(attached&&selected){try{await chrome.debugger.detach({tabId:selected.id});}catch{}}
  attached=false;selected=null;
  if(socket){const old=socket;socket=null;old.close();}
  await chrome.action.setBadgeText({text:''});
}
async function evaluate(fn,arg){
  const result=await cdp('Runtime.evaluate',{expression:'('+fn.toString()+')('+JSON.stringify(arg??null)+')',returnByValue:true,awaitPromise:true});
  if(result.exceptionDetails)throw Error(result.exceptionDetails.text+' '+(result.exceptionDetails.exception?.description||''));
  return result.result.value;
}
async function connect(tabId,code){
  await disconnect();
  const tab=await chrome.tabs.get(tabId);
  if(!/^https?:\/\//.test(tab.url)||new URL(tab.url).port==='7870')throw Error('Open a website tab first, then connect it. Chrome settings and LiquidPilot itself cannot be controlled.');
  const saved=await chrome.storage.session.get('token');const token=code||saved.token;
  if(!token)throw Error('Create a pairing code in LiquidPilot and paste it here.');
  selected={id:tab.id,url:tab.url,title:tab.title};
  await chrome.debugger.attach({tabId},'1.3');attached=true;
  try{
    await new Promise((resolve,reject)=>{
      const ws=new WebSocket('ws://127.0.0.1:7870/browser-bridge');socket=ws;
      const timer=setTimeout(()=>{reject(Error('Local connector did not respond. Start LiquidPilot.'));ws.close();},8000);
      ws.onopen=()=>send({token});
      ws.onmessage=async event=>{
        const message=JSON.parse(event.data);
        if(message.event==='authenticated'){
          clearTimeout(timer);await chrome.storage.session.set({token:message.token});send({event:'tab',tab:selected});
          heartbeat=setInterval(()=>send({event:'ping'}),15000);resolve();return;
        }
        if(!message.id)return;
        try{const result=await operate(message);send({id:message.id,result});}
        catch(e){send({id:message.id,error:e.message});}
      };
      ws.onerror=()=>{clearTimeout(timer);reject(Error('Cannot reach LiquidPilot at 127.0.0.1:7870.'));};
      ws.onclose=()=>{clearTimeout(timer);reject(Error('Pairing failed or expired. Generate a new code.'));if(socket===ws)disconnect();};
    });
    await chrome.action.setBadgeText({text:'ON'});await chrome.action.setBadgeBackgroundColor({color:'#39a880'});
  }catch(e){await disconnect();throw e;}
}
async function operate(message){
  if(!selected||!attached)throw Error('Select a tab in the extension first.');
  const tab=await chrome.tabs.get(selected.id);
  if(!/^https?:\/\//.test(tab.url))throw Error('This page cannot be controlled.');
  selected={id:tab.id,url:tab.url,title:tab.title};send({event:'tab',tab:selected});
  const op=message.operation;
  if(op==='metadata')return selected;
  if(message.expected_url&&tab.url!==message.expected_url)throw Error('The selected page changed. Observe it again before continuing.');
  if(op==='observe'){const observation=await evaluate(observePage);observation.youtube=await evaluate(youtubeObservation);return observation;}
  if(op==='fingerprint')return await evaluate(fingerprintPage);
  if(op==='screenshot'){
    await evaluate(maskSecrets,true);
    try{return await cdp('Page.captureScreenshot',{format:'jpeg',quality:65,captureBeyondViewport:false});}
    finally{await evaluate(maskSecrets,false);}
  }
  if(op==='release'){await disconnect();return {released:true};}
  if(op!=='action')throw Error('Unknown connector operation.');
  const a=message.action;
  if(['site_search_filters','site_play'].includes(a.kind))return await evaluate(youtubeControl,a.kind);
  if(a.kind==='navigate'){
    const u=new URL(a.url);if(!['http:','https:'].includes(u.protocol)||u.username||u.password||u.port==='7870')throw Error('Unsupported destination.');
    await chrome.tabs.update(selected.id,{url:a.url});
  }else if(['back','forward'].includes(a.kind)){
    if(a.kind==='back')await chrome.tabs.goBack(selected.id);else await chrome.tabs.goForward(selected.id);
  }else if(['type','clear','select','check','click','double_click','hover','scroll','press'].includes(a.kind)){
    if(['type','clear','select','check','click','double_click','press'].includes(a.kind)&&!message.approved)throw Error('An explicit approval is required for interactions in your signed-in browser.');
    const result=await evaluate(interactPage,a);if(result?.error)throw Error(result.error);return result;
  }else if(a.kind!=='wait')throw Error('This action is not supported in connected Chrome.');
  for(let n=0;n<100;n++){await new Promise(r=>setTimeout(r,150));const t=await chrome.tabs.get(selected.id);if(t.status==='complete'&&(!a.url||t.url===a.url||n>20)){selected={id:t.id,url:t.url,title:t.title};send({event:'tab',tab:selected});break;}}
  if(a.kind==='navigate'&&new URL(a.url).hostname.endsWith('youtube.com'))await new Promise(r=>setTimeout(r,1000));
  return {ok:true};
}
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(sender.id!==chrome.runtime.id)return;
  (async()=>{
    if(message.kind==='connect'){await connect(message.tabId,message.code);return {connected:true};}
    if(message.kind==='disconnect'){await disconnect();return {connected:false};}
    if(message.kind==='status')return {connected:!!attached&&socket?.readyState===WebSocket.OPEN,tab:selected};
    throw Error('Unknown request');
  })().then(reply).catch(e=>reply({error:e.message}));return true;
});
chrome.debugger.onDetach.addListener(source=>{if(source.tabId===selected?.id)disconnect();});
