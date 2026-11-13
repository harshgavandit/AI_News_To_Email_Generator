'use strict';
const element = id => document.getElementById(id);
const msg = message => {element('source-status').textContent = message;};
let key = '';
async function api(url, method = 'GET', body) {
  const headers = method === 'GET' ? {} : {'Authorization':'Bearer '+key,'Content-Type':'application/json'};
  const response = await fetch(url,{method,headers,body:body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if(!response.ok) throw new Error(data.detail || 'The request could not be completed.');
  return data;
}
async function render() {
  const {sources} = await api('/api/sources');
  const list = element('source-rows');
  list.replaceChildren();
  for (const s of sources) {
    const row = document.createElement('article'); row.className = 'source-row';
    const name = document.createElement('a'); name.href = s.feed_url; name.textContent = s.label; name.target = '_blank'; name.rel = 'noopener noreferrer';
    const info = document.createElement('span'); info.textContent = !s.enabled ? 'Paused' : s.available === null ? 'Not checked yet' : s.available ? 'Available' : 'Last check failed';
    if(s.last_success) info.textContent += ' · Last fetched '+new Date(s.last_success).toLocaleString();
    row.append(name,info);
    if(key) {
      const button = document.createElement('button'); button.type='button'; button.className='button secondary'; button.textContent=s.enabled?'Pause':'Enable';
      button.addEventListener('click',async()=>{button.disabled=true;try {await api('/api/admin/sources/'+encodeURIComponent(s.id),'PATCH',{enabled:!s.enabled});await render();} catch(e){msg(e.message);} finally{button.disabled=false;}});
      row.append(button);
    }
    list.append(row);
  }
  msg(sources.length+' sources');
}
element('source-admin').addEventListener('submit',async e=>{e.preventDefault();key=element('source-key').value;element('source-key').value='';try{await api('/api/admin/sources','POST');element('source-refresh').hidden=false;await render();}catch(err){key='';element('source-refresh').hidden=true;msg(err.message);}});
element('source-refresh').addEventListener('click',async()=>{element('source-refresh').disabled=true;msg('Checking feeds…');try{await api('/api/admin/refresh','POST');await render();}catch(e){msg(e.message);}finally{element('source-refresh').disabled=false;}});
render().catch(e=>msg(e.message));
