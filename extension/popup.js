const status=document.querySelector('#status');
document.querySelector('#connect').onclick=async()=>{
  try{const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    const result=await chrome.runtime.sendMessage({kind:'connect',tabId:tab.id,code:document.querySelector('#code').value.trim()});
    status.textContent=result.error||'Connected. Return to LiquidPilot to give an instruction.';
  }catch(e){status.textContent=e.message;}
};
document.querySelector('#disconnect').onclick=async()=>{await chrome.runtime.sendMessage({kind:'disconnect'});status.textContent='Disconnected. You have control.';};
chrome.runtime.sendMessage({kind:'status'}).then(s=>{status.textContent=s.connected?'Connected to: '+(s.tab?.title||s.tab?.url||'selected tab'):'Not connected';});
