/* Eris Conversation Studio — hành vi phía trình duyệt, không tạo agent thứ hai.
   Các hành động ở đây chỉ dùng transcript/runtime thật từ cổng Godot.
   Bookmarks chỉ lưu fingerprint tin nhắn tại máy, không sao lưu nội dung riêng tư. */
'use strict';
const ErisStudioUtils = Object.freeze({
  fingerprint(message) {
    const raw=String(message?.role||'')+'\u0000'+String(message?.date||'')+'\u0000'+String(message?.time||'')+'\u0000'+String(message?.text||'');
    let h=2166136261;for(let i=0;i<raw.length;i++){h^=raw.charCodeAt(i);h=Math.imul(h,16777619);}
    return (h>>>0).toString(36);
  },
  fileBlock(name,content) {
    const clean=String(name||'tài liệu').replace(/[\r\n\[\]`]/g,' ').slice(0,95);
    // Tilde fence đủ dài để văn bản người dùng không vô tình thoát ra ngoài khối.
    const largest=Math.max(0,...Array.from(String(content).matchAll(/~{3,}/g),m=>m[0].length));
    const fence='~'.repeat(Math.max(4,largest+1));
    return `\n\nTài liệu đính kèm: ${clean}\n${fence}text\n${content}\n${fence}`;
  },
  sizeOkay(message) {
    return message.length>0 && message.length<=6000 && new TextEncoder().encode(JSON.stringify({message})).length<=11900;
  }
});
if(typeof module!=='undefined'&&module.exports)module.exports=ErisStudioUtils;
if(typeof document!=='undefined')document.addEventListener('DOMContentLoaded',()=>{
  const $=id=>document.getElementById(id);
  const root=$('messages'),scroll=$('scroll'),input=$('input'),send=$('sendBtn');
  if(!root||!input||!send)return;
  const endpoint=path=>new URL(path,new URL('.',location.href)).pathname;
  const safeRead=(key,fallback)=>{try{return localStorage.getItem(key)??fallback;}catch{return fallback;}};
  const safeWrite=(key,value)=>{try{localStorage.setItem(key,value);}catch{/* storage không khả dụng */}};
  let saved=new Set();try{saved=new Set(JSON.parse(safeRead('eris.studio.bookmarks.v1','[]')));}catch{}
  let transcript=[],artifacts=[],files=[],recording=null,stream=null,streamSeen=0,streamFailures=0;
  let activeBefore=false, hadRuntimeActivity=false;
  const stageNames={idle:'Sẵn sàng',thinking:'Đang suy nghĩ',speaking:'Đang nói',planning:'Đang lên kế hoạch',staged:'Đang chuẩn bị',audio_buffering:'Đang chuẩn bị âm thanh',afterglow:'Đã hoàn tất'};
  const history=[];
  const notification=$('notifyFinished');
  if(notification){notification.checked=safeRead('eris.studio.notify','0')==='1'&&typeof Notification!=='undefined'&&Notification.permission==='granted';
    notification.addEventListener('change',async()=>{
      if(!notification.checked){safeWrite('eris.studio.notify','0');return;}
      if(typeof Notification==='undefined'){notification.checked=false;notify('Trình duyệt không hỗ trợ thông báo.');return;}
      const permission=Notification.permission==='granted'?'granted':await Notification.requestPermission();
      notification.checked=permission==='granted';safeWrite('eris.studio.notify',notification.checked?'1':'0');
      if(!notification.checked)notify('Cần cấp quyền thông báo trong trình duyệt.');
    });
  }
  const notify=text=>{const el=document.createElement('div');el.className='toast';el.textContent=text;document.body.appendChild(el);setTimeout(()=>el.remove(),2500);};
  function focusInput(value=null){if(value!==null)input.value=value;input.dispatchEvent(new Event('input'));input.focus();}
  function setView(open){document.body.classList.toggle('inspector-closed',!open);$('inspectorBtn')?.setAttribute('aria-pressed',String(open));safeWrite('eris.studio.inspector',open?'1':'0');}
  setView(safeRead('eris.studio.inspector',innerWidth>=1450?'1':'0')==='1');
  $('inspectorBtn')?.addEventListener('click',()=>setView(document.body.classList.contains('inspector-closed')));
  $('statusDetails')?.addEventListener('click',()=>setView(true));
  $('inspectorClose')?.addEventListener('click',()=>setView(false));
  $('sidebarCollapse')?.addEventListener('click',()=>{const on=document.body.classList.toggle('sidebar-collapsed');safeWrite('eris.studio.sidebar',on?'1':'0');});
  if(safeRead('eris.studio.sidebar','0')==='1')document.body.classList.add('sidebar-collapsed');
  $('avatarRoom').checked=safeRead('eris.studio.avatarRoom',innerWidth>=1570?'1':'0')==='1';
  document.body.classList.toggle('avatar-room',$('avatarRoom').checked);
  $('avatarRoom').addEventListener('change',()=>{document.body.classList.toggle('avatar-room',$('avatarRoom').checked);safeWrite('eris.studio.avatarRoom',$('avatarRoom').checked?'1':'0');});
  if(safeRead('eris.studio.theme','light')==='dark')document.body.classList.add('dark');
  $('themeBtn')?.addEventListener('click',()=>safeWrite('eris.studio.theme',document.body.classList.contains('dark')?'dark':'light'));
  $('newTopicBtn')?.addEventListener('click',()=>{if(input.value.trim()&&!confirm('Thay nội dung nháp bằng chủ đề mới?'))return;
    focusInput('Chủ đề mới: ');$('sidebar')?.classList.remove('open');
    notify('Đây là chủ đề mới trong transcript hiện tại, không phải phiên chat tách biệt.');});
  $('openWorkspace')?.addEventListener('click',()=>{if($('workspaceBtn')?.getAttribute('aria-pressed')!=='true')$('workspaceBtn')?.click();if(innerWidth<1150)setView(false);});
  const scrollDown=()=>{scroll.scrollTo({top:scroll.scrollHeight,behavior:'smooth'});};
  $('jumpBottom')?.addEventListener('click',scrollDown);$('contextGo')?.addEventListener('click',scrollDown);
  const jumpIndicator=()=>{$('jumpBottom').hidden=scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<220;};
  scroll.addEventListener('scroll',jumpIndicator,{passive:true});
  $('promptBtn')?.addEventListener('click',()=>focusInput('Eris, cùng tôi tìm hiểu sâu về '));
  // Thêm chỉ mục lưu tin nhắn theo fingerprint, không sao chép transcript vào localStorage.
  function topicNav(){const box=$('topicList');if(!box)return;box.replaceChildren();
    const topics=transcript.filter(m=>m.role==='user'&&/^Chủ đề mới:\s*\S/i.test(m.text||'')).slice(-10).reverse();
    if(!topics.length){const p=document.createElement('p');p.className='activity-empty';p.textContent='Các chủ đề mới sẽ xuất hiện tại đây.';box.append(p);return;}
    for(const m of topics){const button=document.createElement('button');button.className='saved-button';button.type='button';
      button.textContent='◇ '+m.text.replace(/^Chủ đề mới:\s*/i,'').slice(0,42);button.addEventListener('click',()=>{
        // Trở về tất cả các ngày trước khi điều hướng; không đổi transcript Eris.
        $('search').value='';$('search').dispatchEvent(new Event('input'));
        const first=$('dates')?.querySelector('.date-button');first?.click();
        setTimeout(()=>Array.from(root.querySelectorAll('.entry')).find(e=>e.dataset.msgKey===ErisStudioUtils.fingerprint(m))?.scrollIntoView({behavior:'smooth',block:'center'}),10);
        $('sidebar')?.classList.remove('open');
      });box.append(button);
    }
  }
  function savedNav(){const box=$('savedList');if(!box)return;box.replaceChildren();let count=0;
    for(const m of transcript){const key=ErisStudioUtils.fingerprint(m);if(!saved.has(key))continue;count++;
      const button=document.createElement('button');button.type='button';button.className='saved-button';button.textContent='✧ '+String(m.text).replace(/\s+/g,' ').slice(0,51);
      button.title='Tới tin nhắn đã đánh dấu';button.onclick=()=>{
        const element=Array.from(root.querySelectorAll('.entry')).find(row=>row.dataset.msgKey===key);
        if(element)element.scrollIntoView({behavior:'smooth',block:'center'});
        else {const search=$('search');search.value=m.text.slice(0,65);search.dispatchEvent(new Event('input'));setTimeout(()=>root.querySelector('.entry')?.scrollIntoView({behavior:'smooth',block:'center'}),30);}
        $('sidebar')?.classList.remove('open');
      };box.append(button);
    }
    $('savedCount').textContent=String(count);
    if(count===0){const p=document.createElement('p');p.className='activity-empty';p.textContent='Đánh dấu ✧ bên cạnh tin nhắn để lưu lối tắt.';box.append(p);}
  }
  root.addEventListener('click',event=>{
    const welcome=event.target.closest('[data-welcome-prompt]');
    if(welcome){focusInput(welcome.dataset.welcomePrompt);return;}
    const btn=event.target.closest('[data-studio-action]');if(!btn)return;
    const entry=btn.closest('.entry'),key=entry?.dataset.msgKey,role=entry?.classList.contains('user')?'user':'assistant';
    const msg=transcript.find(m=>ErisStudioUtils.fingerprint(m)===key);if(!msg)return;
    const action=btn.dataset.studioAction;
    if(action==='bookmark'){
      saved.has(key)?saved.delete(key):saved.add(key);safeWrite('eris.studio.bookmarks.v1',JSON.stringify(Array.from(saved).slice(-180)));
      btn.classList.toggle('marked',saved.has(key));btn.textContent=saved.has(key)?'★ Đã lưu':'✧ Lưu';savedNav();
    }else if(action==='quote'){
      const excerpt=msg.text.replace(/\s+/g,' ').slice(0,310);
      focusInput((input.value?input.value+'\n\n':'')+`> ${excerpt}\n\n`);
    }else if(action==='resend'){
      if(role!=='user')return;
      focusInput(msg.text);notify('Sửa và gửi lại sẽ tạo tin nhắn mới, không thay lịch sử cũ.');
    }else if(action==='retry'){
      if(role!=='assistant')return;
      focusInput('Eris, hãy xem lại câu trả lời vừa rồi và thử giải thích theo một hướng khác: ');
    }
  });
  // Tài liệu text được chèn vào nội dung gửi, không có dịch vụ upload giả.
  async function addFiles(list){
    for(const file of Array.from(list).slice(0,3)){
      if(files.length>=3){notify('Tối đa 3 tài liệu mỗi lần gửi.');break;}
      if(!/\.(txt|md|markdown|json|csv|xml|yaml|yml|py|js|ts|java|cs|cpp|c|h|html|css|sql|log|sh|bat)$/i.test(file.name)){
        notify('Hiện hỗ trợ tệp văn bản. Ảnh cần dùng Vision của Eris.');continue;
      }
      if(file.size>19000){notify('Tài liệu lớn quá; hãy gửi một đoạn nhỏ dưới 6.000 ký tự.');continue;}
      try{const content=await file.text();if(content.includes('\0'))throw Error('binary');
        files.push({name:file.name,text:content});renderFiles();
      }catch{notify('Không đọc được tệp '+file.name);}
    }
    updateCount();
  }
  function renderFiles(){const tray=$('attachmentTray');tray.replaceChildren();files.forEach((file,i)=>{
    const chip=document.createElement('span');chip.className='file-chip';chip.textContent='▤ '+file.name;
    const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','Bỏ '+file.name);
    remove.addEventListener('click',()=>{files.splice(i,1);renderFiles();updateCount();});chip.append(remove);tray.append(chip);
  });}
  function compose(){return input.value.trim()+files.map(f=>ErisStudioUtils.fileBlock(f.name,f.text)).join('');}
  function updateCount(){const message=compose();$('composerCounter').textContent=`${message.length} / 6000`;
    $('composerCounter').classList.toggle('critical',!ErisStudioUtils.sizeOkay(message)&&message.length>0);
    send.disabled=!ErisStudioUtils.sizeOkay(message)||send.dataset.busy==='1';}
  $('attachBtn')?.addEventListener('click',()=>$('fileInput').click());
  $('fileInput')?.addEventListener('change',event=>{addFiles(event.target.files);event.target.value='';});
  const composer=$('sendForm');
  for(const type of ['dragenter','dragover'])composer.addEventListener(type,event=>{if(event.dataTransfer?.types?.includes('Files')){event.preventDefault();composer.classList.add('drop-ready');}});
  composer.addEventListener('dragleave',()=>composer.classList.remove('drop-ready'));
  composer.addEventListener('drop',event=>{event.preventDefault();composer.classList.remove('drop-ready');addFiles(event.dataTransfer.files);});
  input.addEventListener('input',updateCount);
  // Chặn submit mặc định của chat.js bằng capture nếu có tài liệu hoặc quá giới hạn.
  composer.addEventListener('submit',event=>{
    if(!files.length){if(!ErisStudioUtils.sizeOkay(input.value.trim())){event.preventDefault();event.stopImmediatePropagation();notify('Tin nhắn vượt giới hạn ký tự/byte.');}return;}
    event.preventDefault();event.stopImmediatePropagation();
    const message=compose();if(!ErisStudioUtils.sizeOkay(message)){notify('Tệp + câu hỏi quá dài. Rút gọn tài liệu trước khi gửi.');return;}
    if(send.dataset.busy==='1')return;
    send.dataset.busy='1';updateCount();
    fetch(endpoint('api/send'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message})})
      .then(resp=>{if(!resp.ok)throw Error('send failed');files=[];renderFiles();input.value='';input.dispatchEvent(new Event('input'));$('draftStatus').textContent='Đã gửi tài liệu vào hội thoại';})
      .catch(()=>notify('Không gửi được tài liệu. Kiểm tra kết nối Eris.'))
      .finally(()=>{delete send.dataset.busy;updateCount();});
  },true);
  updateCount();
  // Nhập giọng nói do browser cung cấp; TTS Eris vẫn nằm ở Godot.
  const Recognizer=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!Recognizer){$('micBtn').title='Trình duyệt chưa hỗ trợ SpeechRecognition';}
  $('micBtn')?.addEventListener('click',()=>{
    if(!Recognizer){notify('Trình duyệt này chưa hỗ trợ nhập bằng giọng nói.');return;}
    if(recording){recording.stop();return;}
    const recognition=new Recognizer();recording=recognition;recognition.lang='vi-VN';recognition.continuous=false;recognition.interimResults=false;
    $('micBtn').classList.add('recording');$('micBtn').setAttribute('aria-label','Dừng nghe');
    recognition.onresult=event=>{const text=Array.from(event.results).map(r=>r[0]?.transcript||'').join(' ').trim();if(text)focusInput(input.value+(input.value?' ':'')+text);};
    recognition.onerror=()=>notify('Không nhận được âm thanh. Kiểm tra quyền micro.');
    recognition.onend=()=>{recording=null;$('micBtn').classList.remove('recording');$('micBtn').setAttribute('aria-label','Nhập bằng giọng nói');};
    try{recognition.start();}catch{recognition.onend();notify('Không thể mở micro.');}
  });
  document.addEventListener('keydown',event=>{
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();$('search').focus();$('sidebar').classList.add('open');}
    if(event.key==='/'&&!['INPUT','TEXTAREA'].includes(document.activeElement?.tagName)){event.preventDefault();$('search').focus();$('sidebar').classList.add('open');}
    if(event.key==='Escape'){if(recording)recording.stop();setView(false);$('sidebar').classList.remove('open');}
  });
  function activityUpdate(state){
    const runtime=state?.presence||{},speech=state?.speech||{};
    const phase=String(speech.phase||'idle'),stage=String(runtime.stage||phase);
    const label=String(runtime.activity||runtime.label||state.status||stageNames[stage]||stageNames[phase]).slice(0,180);
    const currentlyActive=phase==='thinking'||phase==='speaking'||!!runtime.isActive;
    // Chỉ thông báo sau khi đã THẤY một lượt làm việc thực sự trong tab này.
    // Không thông báo lần đầu nạp history, không thông báo khi mất kết nối.
    if(activeBefore&&!currentlyActive&&hadRuntimeActivity&&document.hidden&&notification?.checked){
      try{new Notification('Eris đã hoàn tất lượt',{body:'Bạn có thể mở lại hội thoại để xem kết quả.'});}catch{/* Tắt thông báo nếu browser từ chối. */}
    }
    activeBefore=currentlyActive;if(currentlyActive)hadRuntimeActivity=true;
    $('presenceLabel').textContent=label;
    $('stageTag').textContent=stageNames[stage]||stageNames[phase]||'Hoạt động';
    $('presenceOrb').className='presence-orb'+(phase==='thinking'?' thinking':phase==='speaking'?' speaking':'');
    $('contextText').textContent=label;
    const emotion=String(runtime.emotion||'');$('emotionTag').hidden=!emotion;if(emotion)$('emotionTag').textContent=emotion.slice(0,35);
    const key=[stage,label,runtime.activity||''].join('|');
    if(label && history[0]?.key!==key){history.unshift({key,label,stage,time:new Date().toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit'})});history.splice(12);renderHistory();}
    const count=artifacts.length;$('artifactCount').textContent=count?`${count} artifact đã xuất hiện trong transcript.`:'Chưa có kết quả công cụ trong transcript.';
  }
  function renderHistory(){const box=$('activityTimeline');box.replaceChildren();for(const item of history){
    const div=document.createElement('div');div.className='timeline-item';const content=document.createElement('div');content.textContent=item.label;
    const time=document.createElement('small');time.textContent=item.time+' · '+(stageNames[item.stage]||item.stage);content.append(time);div.append(content);box.append(div);
  }}
  window.addEventListener('eris:state',event=>{
    const state=event.detail;if(!state)return;
    transcript=Array.isArray(state.messages)?state.messages:[];
    artifacts=Array.isArray(state.bundles)?state.bundles.flatMap(b=>b.artifacts||[]):[];
    $('messageCount').textContent=transcript.length+' tin nhắn';
    activityUpdate(state);topicNav();savedNav();jumpIndicator();
    for(const row of root.querySelectorAll('.entry')){
      const btn=row.querySelector('[data-studio-action="bookmark"]');if(!btn)continue;
      const marked=saved.has(row.dataset.msgKey);btn.classList.toggle('marked',marked);btn.textContent=marked?'★ Đã lưu':'✧ Lưu';
    }
  });
  // EventSource phát toàn bộ snapshot thật (KHÔNG có stream token nếu runtime chưa phát token).
  // Nếu stream hỏng, chat.js tự quay về polling cũ.
  function startStream(){if(typeof EventSource==='undefined'||window.__ERIS_FIXTURE__)return;
    stream=new EventSource(endpoint('api/events'));
    stream.addEventListener('state',event=>{try{const state=JSON.parse(event.data);streamSeen=Date.now();streamFailures=0;
      window.dispatchEvent(new CustomEvent('eris:stream-state',{detail:state}));}catch(error){console.warn('[Eris] SSE invalid state',error);}});
    stream.addEventListener('error',()=>{streamFailures++;if(streamFailures>3){stream.close();stream=null;}});
  }
  window.ErisStudio=Object.freeze({isStreaming:()=>!!stream&&stream.readyState===1&&Date.now()-streamSeen<4000,
    saved:()=>saved,compose,updateCount});
  startStream();
  // chat.js có thể nhận snapshot fixture ngay trước khi studio.js đăng ký listener.
  if(window.__ERIS_LAST_STATE__)window.dispatchEvent(new CustomEvent('eris:state',{detail:window.__ERIS_LAST_STATE__}));
  // Xuất transcript cục bộ khi người dùng tự chọn (không gửi lên dịch vụ ngoài).
  const exportBtn=document.createElement('button');exportBtn.type='button';exportBtn.className='saved-button';exportBtn.textContent='↓ Xuất hội thoại (.md)';
  exportBtn.addEventListener('click',()=>{
    const body=transcript.map(m=>`## ${m.role==='user'?'Bạn':'Eris'} · ${m.date||''} ${m.time||''}\n\n${m.text||''}\n`).join('\n---\n');
    const blob=new Blob(['# Eris — Hội thoại\n\n',body],{type:'text/markdown;charset=utf-8'});
    const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='eris-conversation-'+new Date().toISOString().slice(0,10)+'.md';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });$('sidebar').querySelector('.sidebar-foot').prepend(exportBtn);
});
