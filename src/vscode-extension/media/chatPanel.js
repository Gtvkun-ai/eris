(() => {
  const showBootError = (error) => {
    try {
      const message = error && error.stack ? error.stack : String(error || 'Không rõ lỗi');
      document.documentElement.dataset.erisBoot = 'failed';
      const timeline = document.getElementById('timeline');
      if (timeline) {
        timeline.innerHTML = '<div class="boot-error"><strong>Eris UI không khởi động được</strong><span></span><button type="button" id="reloadWebview">Tải lại giao diện</button></div>';
        const text = timeline.querySelector('span');
        if (text) text.textContent = message;
        const reload = document.getElementById('reloadWebview');
        if (reload) reload.onclick = () => location.reload();
      }
      console.error('[Eris Webview] bootstrap failed', error);
    } catch (secondary) {
      console.error('[Eris Webview] bootstrap error handler failed', secondary);
    }
  };

  window.addEventListener('error', (event) => showBootError(event.error || event.message));
  window.addEventListener('unhandledrejection', (event) => showBootError(event.reason));

  try {
    const vscode=acquireVsCodeApi();
    const timeline=document.getElementById('timeline');
    const input=document.getElementById('input');
    const sessionStrip=document.getElementById('sessionStrip');
    const sessionTabs=document.getElementById('sessionTabs');
    const sessionIndicator=document.getElementById('sessionIndicator');
    const connection=document.getElementById('connection');
    const sendButton=document.getElementById('send');
    const attachmentBox=document.getElementById('attachments');
    const notice=document.getElementById('notice');
    const drawer=document.getElementById('drawer');
    const drawerBody=document.getElementById('drawerBody');
    const drawerTitle=document.getElementById('drawerTitle');
    const menuPopover=document.getElementById('menuPopover');
    const contextPopover=document.getElementById('contextPopover');
    const modelSelect=document.getElementById('modelSelect');
    const modeSelect=document.getElementById('mode');
    const modeButton=document.getElementById('modeButton');
    const modeLabel=document.getElementById('modeLabel');
    const modelButton=document.getElementById('modelButton');
    const modelLabel=document.getElementById('modelLabel');
    const modePopover=document.getElementById('modePopover');
    const modelPopover=document.getElementById('modelPopover');
    
    let activeThreadId='';
    let activeTaskId='';
    let sessions=[];
    let catalogTasks=[];
    let catalogSkills=[];
    let selectedMode=(vscode.getState()&&vscode.getState().mode)||'execute';
    let selectedModel=(vscode.getState()&&vscode.getState().model)||'gemini-3-flash';
    const rendered=new Set();
    const pendingInterrupts=new Set();
    const attachmentState=new Map();
    const taskGroups=new Map();
    const knownTabs=new Set();
    let pendingSwitchDirection=0;
    let awaitingThreadHistory=false;
    let deferredEvents=[];
    
    function modelName(value){return value==='gemini-3-pro'?'Pro':value==='gemini-3-flash-thinking'?'Suy luận':'Flash';}
    function modeName(value){return value==='inspect'?'Chỉ xem':'Tác vụ';}
    function statusName(value){var v=String(value||'').toLowerCase();return({idle:'Chờ',queued:'Đang xếp hàng',running:'Đang chạy',paused:'Tạm dừng',waiting:'Đang chờ',waiting_user:'Chờ bạn',waiting_permission:'Chờ quyền',completed:'Hoàn tất',done:'Hoàn tất',failed:'Lỗi',stopped:'Đã dừng',pending:'Chờ xác nhận',accepted:'Đã chấp nhận',reverted:'Đã hoàn tác',updated:'Đã cập nhật'})[v]||String(value||'');}
    function setMode(value){
      selectedMode=value==='inspect'?'inspect':'execute';
      modeSelect.value=selectedMode;modeLabel.textContent=modeName(selectedMode);
      vscode.setState(Object.assign({},vscode.getState(),{mode:selectedMode,model:selectedModel}));
      for(var row of modePopover.querySelectorAll('[data-mode]'))row.classList.toggle('selected',row.dataset.mode===selectedMode);
    }
    function setModel(value){
      selectedModel=value||'gemini-3-flash';
      modelSelect.value=selectedModel;modelLabel.textContent=modelName(selectedModel);
      vscode.setState(Object.assign({},vscode.getState(),{mode:selectedMode,model:selectedModel}));
      for(var row of modelPopover.querySelectorAll('[data-model]'))row.classList.toggle('selected',row.dataset.model===selectedModel);
    }
    setMode(selectedMode);setModel(selectedModel);
    
    const esc=function(v){return String(v==null?'':v).replace(/[&<>"']/g,function(ch){return({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[ch];});};
    const clip=function(v,n){n=n||80;var t=String(v==null?'':v).replace(/\\s+/g,' ').trim();return t.length<=n?t:t.slice(0,n-1)+'\u2026';};
    const scroll=function(){requestAnimationFrame(function(){timeline.scrollTop=timeline.scrollHeight;});};
    const fmtBytes=function(n){var v=Number(n||0);if(v<1024)return v+' B';if(v<1048576)return Math.round(v/102.4)/10+' KB';return Math.round(v/104857.6)/10+' MB';};
    const eventKey=function(e){return String(e&&e.eventId!=null?e.eventId:e&&e.event_id!=null?e.event_id:'')||[e&&e.type,e&&e.taskId,e&&e.seq,e&&e.timestamp].join(':');};
    function remember(e){var k=eventKey(e);if(!k)return true;if(rendered.has(k))return false;rendered.add(k);if(rendered.size>2500){var f=rendered.values().next().value;rendered.delete(f);}return true;}
    
    function updateSessionIndicator(){
      var active=sessionTabs.querySelector('.session-tab.active');
      if(!active){sessionIndicator.style.opacity='0';return;}
      var left=active.offsetLeft-sessionTabs.scrollLeft;
      sessionIndicator.style.width=active.offsetWidth+'px';
      sessionIndicator.style.transform='translateX('+left+'px)';
      sessionIndicator.style.opacity='1';
    }
    function selectSessionFromUi(threadId){
      var ci=sessions.findIndex(function(s){return s.threadId===activeThreadId;});
      var ni=sessions.findIndex(function(s){return s.threadId===threadId;});
      pendingSwitchDirection=ni===ci?0:(ni>ci?1:-1);
      awaitingThreadHistory=true;
      vscode.postMessage({type:'session.select',threadId:threadId});
    }
    function renderSessions(){
      sessionStrip.classList.toggle('no-sessions',sessions.length===0);
      sessionTabs.innerHTML='';
      var liveIds=new Set(sessions.map(function(s){return String(s.threadId||'');}));
      for(var k of [...knownTabs])if(!liveIds.has(k))knownTabs.delete(k);
      for(var session of sessions){
        var tab=document.createElement('button');
        var isFresh=!knownTabs.has(session.threadId);
        tab.className='session-tab'+(session.threadId===activeThreadId?' active':'')+(isFresh?' tab-enter':'');
        tab.dataset.threadId=session.threadId;
        tab.title=session.title==='New Session'?'Cuộc chat mới':(session.title||'Cuộc chat mới');
        var dot=document.createElement('span');dot.className='session-state '+String(session.status||'idle');
        var title=document.createElement('span');title.className='session-title';title.textContent=session.title==='New Session'?'Cuộc chat mới':(session.title||'Cuộc chat mới');
        var close=document.createElement('button');close.className='close-tab';close.textContent='\xD7';close.title='Đóng';
        (function(tid,t){close.onclick=function(ev){ev.stopPropagation();t.classList.add('tab-closing');setTimeout(function(){vscode.postMessage({type:'session.close',threadId:tid});},110);};})(session.threadId,tab);
        tab.append(dot,title,close);
        (function(tid){tab.onclick=function(){selectSessionFromUi(tid);};})(session.threadId);
        sessionTabs.appendChild(tab);knownTabs.add(session.threadId);
      }
      requestAnimationFrame(function(){
        var a=sessionTabs.querySelector('.active');
        if(a)a.scrollIntoView({block:'nearest',inline:'nearest'});
        requestAnimationFrame(updateSessionIndicator);
      });
    }
    
    function emptyHtml(){return '<div class="empty" id="chatEmpty"><div class="empty-inner"><div class="spark">✦</div><strong>Bắt đầu trò chuyện với Eris</strong><span>Gửi tin nhắn, đính kèm file/ảnh hoặc thêm # ngữ cảnh IDE khi cần.</span></div></div>';}
    function ensureEmpty(){if(!timeline.children.length){timeline.innerHTML=emptyHtml();bindEmptyModes();}}
    function removeEmpty(){var e=document.getElementById('chatEmpty');if(e)e.remove();}
    function bindEmptyModes(){}
    function clearTimeline(showEmpty){if(showEmpty===undefined)showEmpty=true;timeline.innerHTML='';rendered.clear();pendingInterrupts.clear();taskGroups.clear();activeTaskId='';if(showEmpty)ensureEmpty();}
    function animateTimelineIn(direction){
      direction=direction||0;
      timeline.classList.remove('anim-left','anim-right');
      if(!direction)return;
      void timeline.offsetWidth;
      timeline.classList.add(direction>0?'anim-right':'anim-left');
      setTimeout(function(){timeline.classList.remove('anim-left','anim-right');},220);
    }
    
    /* ---- Messages ---- */
    function addUserMessage(content,attachments){
      attachments=attachments||[];
      removeEmpty();
      var msg=document.createElement('div');msg.className='msg msg-user';
      var body=document.createElement('div');body.className='msg-body';
      var bubble=document.createElement('div');bubble.className='bubble';bubble.textContent=String(content==null?'':content);
      body.appendChild(bubble);
      if(Array.isArray(attachments)&&attachments.length){
        var row=document.createElement('div');row.className='msg-attachments';
        for(var item of attachments.slice(0,8)){
          var chip=document.createElement('div');chip.className='attach-chip-sm';
          chip.textContent=(String(item.kind||'')==='image'?'▧ ':'▤ ')+(item.name||item.relativePath||'đính kèm');
          row.appendChild(chip);
        }
        body.appendChild(row);
      }
      msg.appendChild(body);
      /* History replay đôi khi phát activity trước message.user. Luôn đặt tin nhắn
         của user lên trước nhóm trả lời Eris để conversation đọc đúng thứ tự. */
      var existingGroup=taskGroups.has(String(activeTaskId||'main'))?taskGroups.get(String(activeTaskId||'main')).groupEl:null;
      if(existingGroup&&existingGroup.parentNode===timeline)timeline.insertBefore(msg,existingGroup);else timeline.appendChild(msg);
      scroll();
    }
    
    function getTaskGroup(taskId){
      var key=String(taskId||activeTaskId||'main');
      if(taskGroups.has(key))return taskGroups.get(key);
      removeEmpty();
      var group=document.createElement('div');group.className='msg msg-assistant';group.dataset.taskId=key;
      var body=document.createElement('div');body.className='msg-body';
    
      var thinking=document.createElement('details');thinking.className='thinking running';thinking.hidden=true;
      var summary=document.createElement('summary');
      summary.innerHTML='<span class="thinking-chevron">⌄</span><span class="thinking-dot"></span><span class="thinking-title">Đang suy nghĩ · 0 giây</span>';
      var raw=document.createElement('pre');raw.className='thinking-raw thinking-empty';raw.textContent='Chưa có nhật ký thực thi.';
      var controls=document.createElement('div');controls.className='task-controls';
      controls.innerHTML='<button class="ctrl-btn" data-control="pause">Tạm dừng</button><button class="ctrl-btn" data-control="resume">Tiếp tục</button><button class="ctrl-btn" data-control="rollback">Hoàn tác</button><button class="ctrl-btn" data-control="stop">Dừng</button>';
      for(var btn of controls.querySelectorAll('[data-control]'))(function(b,k){b.onclick=function(){vscode.postMessage({type:'task.control',taskId:k,action:b.dataset.control});};})(btn,key);
      thinking.append(summary,raw,controls);
    
      var role=document.createElement('div');role.className='msg-role';role.textContent='Eris';role.style.display='none';
      var bubble=document.createElement('div');bubble.className='bubble';
      body.append(thinking,role,bubble);
      group.appendChild(body);timeline.appendChild(group);
      var entry={
        groupEl:group,bubbleEl:bubble,roleEl:role,thinkingEl:thinking,thinkingTitleEl:summary.querySelector('.thinking-title'),
        thinkingRawEl:raw,controlsEl:controls,startedAt:Date.now(),endedAt:0,thinkingLines:[],thinkingSeen:new Set(),status:'running'
      };
      taskGroups.set(key,entry);scroll();return entry;
    }
    
    /* "Raw thinking" ở đây là raw event CÔNG KHAI của Agent Harness: tool, activity,
       coding state. Không moi hidden chain-of-thought của model, nhưng user vẫn xem
       được agent đang đọc gì, chạy gì, vướng gì và đổi bước ra sao. */
    function thinkingSeconds(entry){return Math.max(0,Math.round(((entry.endedAt||Date.now())-entry.startedAt)/1000));}
    function refreshThinkingTitle(entry){
      var sec=thinkingSeconds(entry);
      if(entry.status==='running')entry.thinkingTitleEl.textContent='Đang suy nghĩ · '+sec+' giây';
      else if(entry.status==='failed')entry.thinkingTitleEl.textContent='Đã dừng sau '+sec+' giây';
      else entry.thinkingTitleEl.textContent='Đã suy nghĩ · '+sec+' giây';
    }
    function finishThinking(entry,status){
      if(!entry)return;
      entry.status=status==='failed'?'failed':'done';entry.endedAt=entry.endedAt||Date.now();
      entry.thinkingEl.classList.remove('running','failed','done');entry.thinkingEl.classList.add(entry.status);
      entry.controlsEl.classList.remove('visible');refreshThinkingTitle(entry);
    }
    function appendThinking(entry,text){
      if(!entry)return;var value=String(text==null?'':text).trim();if(!value)return;
      if(entry.thinkingSeen.has(value))return;entry.thinkingSeen.add(value);
      entry.thinkingEl.hidden=false;
      if(entry.thinkingRawEl.tagName === 'PRE'){
          var newRaw = document.createElement('div');
          newRaw.className = entry.thinkingRawEl.className;
          entry.thinkingRawEl.parentNode.replaceChild(newRaw, entry.thinkingRawEl);
          entry.thinkingRawEl = newRaw;
      }
      entry.thinkingRawEl.classList.remove('thinking-empty');
      var itemDetails = document.createElement('details');
      itemDetails.className = 'tool-activity-item';
      var itemSummary = document.createElement('summary');
      itemSummary.textContent = 'ℹ️ ' + value.split('\n')[0].substring(0, 80);
      itemDetails.appendChild(itemSummary);
      var pre = document.createElement('pre');
      pre.className = 'tool-activity-data';
      pre.textContent = value;
      itemDetails.appendChild(pre);
      entry.thinkingRawEl.appendChild(itemDetails);
      entry.controlsEl.classList.add('visible');refreshThinkingTitle(entry);
    }
    function addActivity(event){
      var p=event.payload||{};var taskId=String(event.taskId||activeTaskId||'');var entry=getTaskGroup(taskId);
      if(!entry)return;
      var label=String(p.label!=null?p.label:'').trim();var detail=String(p.detail!=null?p.detail:'').trim();
      var kind=String(p.kind!=null?p.kind:'').trim();var data=p.data&&typeof p.data==='object'?p.data:null;
      var dedupeVal = label + detail + kind + (data ? JSON.stringify(data) : '');
      if(!entry.thinkingSeen.has(dedupeVal)) {
          entry.thinkingSeen.add(dedupeVal);
          entry.thinkingEl.hidden=false;
          if(entry.thinkingRawEl.tagName === 'PRE'){
              var newRaw = document.createElement('div');
              newRaw.className = entry.thinkingRawEl.className;
              entry.thinkingRawEl.parentNode.replaceChild(newRaw, entry.thinkingRawEl);
              entry.thinkingRawEl = newRaw;
          }
          entry.thinkingRawEl.classList.remove('thinking-empty');
          var itemDetails = document.createElement('details');
          itemDetails.className = 'tool-activity-item';
          var itemSummary = document.createElement('summary');
          itemSummary.textContent = '⚡ ' + (label || kind || 'Đang thực thi...');
          if (detail && detail !== label) itemSummary.textContent += ' · ' + (detail.length > 80 ? detail.slice(0, 80) + '...' : detail);
          itemDetails.appendChild(itemSummary);
          if (data && Object.keys(data).length) {
              var pre = document.createElement('pre');
              pre.className = 'tool-activity-data';
              pre.textContent = JSON.stringify(data, null, 2);
              itemDetails.appendChild(pre);
          } else if (detail.length > 80) {
              var pre = document.createElement('pre');
              pre.className = 'tool-activity-data';
              pre.textContent = detail;
              itemDetails.appendChild(pre);
          }
          entry.thinkingRawEl.appendChild(itemDetails);
          entry.controlsEl.classList.add('visible');refreshThinkingTitle(entry);
      }
      var status=String(p.status!=null?p.status:(event.type==='activity.end'?'completed':'running'));
      if(status==='completed'||status==='done')finishThinking(entry,'done');
      else if(status==='failed'||status==='stopped')finishThinking(entry,'failed');
      scroll();
    }
    function mergeCoding(event){
      var p=event.payload||{};var taskId=String(event.taskId||activeTaskId||'');var entry=getTaskGroup(taskId);var rows=[];
      for(var pair of [['Hành động',p.current_action],['File',p.current_file],['Bước kế tiếp',p.next_action],['Vướng mắc',p.blocker],['Tóm tắt',p.last_summary]]){
        var value=String(pair[1]==null?'':pair[1]).trim();if(value)rows.push(pair[0]+': '+value);
      }
      if(rows.length)appendThinking(entry,rows.join('\n'));
      var status=String(p.status||'running');
      if(status==='completed'||status==='done')finishThinking(entry,'done');else if(status==='failed'||status==='stopped')finishThinking(entry,'failed');
    }
    setInterval(function(){for(var entry of taskGroups.values())if(entry.status==='running'&&!entry.thinkingEl.hidden)refreshThinkingTitle(entry);},1000);
    
    function disableChoices(node){for(var c of node.querySelectorAll('button,input'))c.disabled=true;}
    function addInterrupt(event){
      removeEmpty();
      var key=String(event.taskId!=null?event.taskId:activeTaskId!=null?activeTaskId:'');
      if(key&&pendingInterrupts.has(key))return;if(key)pendingInterrupts.add(key);
      var p=event.payload||{};
      var node=document.createElement('div');node.className='interrupt';
      node.innerHTML='<h3>'+esc(p.question||'Eris cần bạn chọn một hướng')+'</h3><p>Tác vụ đã được checkpoint và sẽ tiếp tục đúng từ đây.</p><div class="choices" role="listbox"></div>';
      var choices=node.querySelector('.choices');
      for(var option of(p.options||[]))(function(opt){
        var b=document.createElement('button');b.className='choice';
        b.innerHTML='<strong>'+esc(opt.label!=null?opt.label:opt.id)+'</strong>'+(opt.description||opt.desc?'<span>'+esc(opt.description!=null?opt.description:opt.desc)+'</span>':'');
        b.onclick=function(){disableChoices(node);if(key)pendingInterrupts.delete(key);vscode.postMessage({type:'interrupt.resolve',taskId:event.taskId,response:{choiceId:String(opt.id!=null?opt.id:''),value:String(opt.value!=null?opt.value:opt.label!=null?opt.label:''),text:String(opt.label!=null?opt.label:'')}});};
        choices.appendChild(b);
      })(option);
      if(p.allowOther!==false){
        var row=document.createElement('div');row.className='other-row';
        var field=document.createElement('input');field.placeholder='Hướng khác…';
        var sb=document.createElement('button');sb.className='ghost-btn';sb.textContent='Gửi';
        var submit=function(){var v=field.value.trim();if(!v)return;disableChoices(node);if(key)pendingInterrupts.delete(key);vscode.postMessage({type:'interrupt.resolve',taskId:event.taskId,response:{choiceId:'other',value:v,text:v}});};
        sb.onclick=submit;field.onkeydown=function(e){if(e.key==='Enter')submit();};
        row.append(field,sb);choices.appendChild(row);
      }
      timeline.appendChild(node);scroll();
    }
    
    function addArtifact(event){
      var p=event.payload||{};var filePath=String(p.path!=null?p.path:'');if(!filePath)return;
      removeEmpty();
      var node=document.createElement('div');node.className='artifact';
      node.innerHTML='<div class="artifact-head"><span class="pill">Đã sửa</span><code>'+esc(filePath)+'</code></div><div class="artifact-actions"><button data-action="open">Mở</button><button data-action="diff">Xem diff</button></div>';
      node.querySelector('[data-action="open"]').onclick=function(){vscode.postMessage({type:'openArtifact',path:filePath});};
      node.querySelector('[data-action="diff"]').onclick=function(){vscode.postMessage({type:'openDiff',path:filePath,diff:String(p.diff!=null?p.diff:'')});};
      timeline.appendChild(node);scroll();
    }
    function addChangeSet(event){
      var p=event.payload||{};var id=String(p.changeSetId!=null?p.changeSetId:p.operationId!=null?p.operationId:'');if(!id)return;
      removeEmpty();var files=Array.isArray(p.files)?p.files:[];var status=String(p.status!=null?p.status:'pending');
      var node=document.createElement('div');node.className='artifact';node.dataset.changeSetId=id;
      node.innerHTML='<div class="artifact-head"><span class="pill">Gói thay đổi \xB7 '+esc(status)+'</span><code>'+esc(files.slice(0,3).join(' \xB7 ')||id)+'</code></div><div class="artifact-actions"><button data-action="accept">Chấp nhận</button><button data-action="revert">Hoàn tác</button></div>';
      var accept=node.querySelector('[data-action="accept"]');var revert=node.querySelector('[data-action="revert"]');
      if(status!=='pending'){accept.disabled=true;revert.disabled=true;}
      accept.onclick=function(){if(activeTaskId)vscode.postMessage({type:'task.control',taskId:activeTaskId,action:'accept_changeset',changeSetId:id});};
      revert.onclick=function(){if(activeTaskId)vscode.postMessage({type:'task.control',taskId:activeTaskId,action:'revert_changeset',changeSetId:id});};
      timeline.appendChild(node);scroll();
    }
    function updateChangeSet(event){
      var p=event.payload||{};var id=String(p.changeSetId!=null?p.changeSetId:p.operationId!=null?p.operationId:'');
      var nodes=[...document.querySelectorAll('[data-change-set-id]')].reverse();
      var node=nodes.find(function(n){return n.dataset.changeSetId===id;});
      if(!node){addChangeSet(event);return;}
      var pill=node.querySelector('.pill');if(pill)pill.textContent='Gói thay đổi \xB7 '+statusName(p.status!=null?p.status:'updated');
      for(var b of node.querySelectorAll('button'))b.disabled=true;
    }
    
    function renderEvent(event){
      if(!event||!remember(event))return;
      if(event.taskId)activeTaskId=String(event.taskId);
      if(event.type==='message.user'){addUserMessage(event.payload&&event.payload.content!=null?event.payload.content:'',event.payload&&event.payload.attachments?event.payload.attachments:[]);return;}
      if(event.type==='message.assistant'){
        var entry=getTaskGroup(String(event.taskId||activeTaskId||'main'));
        entry.roleEl.style.display='';
        entry.bubbleEl.textContent=String(event.payload&&event.payload.content!=null?event.payload.content:'');
        entry.bubbleEl.classList.remove('streaming');
        finishThinking(entry,'done');
        return;
      }
      if(event.type==='message.assistant.delta'){
        removeEmpty();
        var dEntry=getTaskGroup(String(event.taskId||activeTaskId||'main'));
        dEntry.roleEl.style.display='';
        dEntry.bubbleEl.textContent+=String(event.payload&&event.payload.delta!=null?event.payload.delta:'');
        dEntry.bubbleEl.classList.add('streaming');
        scroll();return;
      }
      if(event.type==='coding.state'){mergeCoding(event);return;}
      if(String(event.type).startsWith('activity.')){addActivity(event);return;}
      if(event.type==='interrupt.request'){addInterrupt(event);return;}
      if(event.type==='interrupt.resolved'){pendingInterrupts.delete(String(event.taskId!=null?event.taskId:''));return;}
      if(event.type==='artifact.modified'||event.type==='artifact.created'){addArtifact(event);return;}
      if(event.type==='changeset.created'){addChangeSet(event);return;}
      if(event.type==='changeset.updated'){updateChangeSet(event);return;}
      if(event.type==='editor.result'){addActivity({type:'activity.update',taskId:event.taskId,payload:{detail:event.payload&&event.payload.message?event.payload.message:event.payload&&event.payload.command?event.payload.command:'VS Code',status:event.payload&&event.payload.success?'completed':'failed'}});}
    }
    
    function renderHistory(event){
      var direction=pendingSwitchDirection;
      function paint(){
        clearTimeline(false);
        var tasks=Array.isArray(event.tasks)?event.tasks:[];
        catalogTasks=[...new Map([...catalogTasks,...tasks].map(function(t){return[String(t&&t.task_id?t.task_id:''),t];})).values()];
        var task=[...tasks].reverse().find(function(t){return['queued','running','paused','waiting_user','waiting_permission'].includes(String(t&&t.status?t.status:''));});
        if(!task)task=tasks[tasks.length-1];
        if(task&&task.task_id)activeTaskId=String(task.task_id);
        for(var item of(event.events||[]))renderEvent(item);
        if(task&&(task.status==='waiting_user'||task.status==='waiting_permission')&&task.pending_interrupt)addInterrupt({taskId:task.task_id,payload:task.pending_interrupt,eventId:'restore:'+String(task.task_id)});
        ensureEmpty();awaitingThreadHistory=false;pendingSwitchDirection=0;animateTimelineIn(direction);
        var queued=deferredEvents;deferredEvents=[];for(var qe of queued)renderEvent(qe);
      }
      if(direction)setTimeout(paint,95);else paint();
    }
    
    function renderAttachments(){
      attachmentBox.innerHTML='';attachmentBox.classList.toggle('visible',attachmentState.size>0);
      for(var item of attachmentState.values()){
        var chip=document.createElement('div');chip.className='attach-chip';
        if(item.preview){var img=document.createElement('img');img.src=item.preview;chip.appendChild(img);}
        var icon=document.createElement('span');icon.textContent=item.kind==='image'?'\u25A7':'\u25A4';
        var name=document.createElement('span');name.className='attach-name';name.textContent=item.name;name.title=(item.relativePath||item.name)+' \xB7 '+fmtBytes(item.size);
        var rm=document.createElement('button');rm.className='attach-remove';rm.textContent='\xD7';
        (function(id,c){rm.onclick=function(){c.classList.add('removing');setTimeout(function(){attachmentState.delete(id);renderAttachments();vscode.postMessage({type:'attachment.remove',id:id});},100);};})(item.id,chip);
        chip.append(icon,name,rm);attachmentBox.appendChild(chip);
      }
      updateComposerState();
    }
    function contextKeys(){return [...contextPopover.querySelectorAll('input:checked')].map(function(n){return n.value;});}
    function updateComposerState(){var ready=Boolean(input.value.trim())||attachmentState.size>0;sendButton.classList.toggle('ready',ready);}
    function resizeInput(){input.style.height='auto';input.style.height=Math.min(140,Math.max(40,input.scrollHeight))+'px';updateComposerState();}
    function send(){var content=input.value.trim();var ids=[...attachmentState.keys()];if(!content&&!ids.length)return;input.value='';resizeInput();hidePopovers();vscode.postMessage({type:'sendMessage',content:content,taskMode:selectedMode,model:selectedModel,attachmentIds:ids,contextKeys:contextKeys()});}
    function hidePopovers(){menuPopover.classList.remove('visible');contextPopover.classList.remove('visible');modePopover.classList.remove('visible');modelPopover.classList.remove('visible');modeButton.classList.remove('active');modelButton.classList.remove('active');}
    function showNotice(message){notice.textContent=String(message||'');notice.classList.toggle('visible',Boolean(message));if(message)setTimeout(function(){notice.classList.remove('visible');},7000);}
    
    function renderDrawer(kind){
      drawer.classList.add('visible');menuPopover.classList.remove('visible');drawerBody.innerHTML='';
      if(kind==='history'){
        drawerTitle.textContent='Lịch sử chat';
        var byThread=new Map();
        for(var session of sessions)byThread.set(String(session.threadId||''),{threadId:String(session.threadId||''),title:session.title||'Cuộc chat mới',status:session.status||'idle',updatedAt:Number(session.updatedAt||0)});
        for(var task of catalogTasks){var tid=String(task.thread_id||task.threadId||'');if(!tid)continue;var ex=byThread.get(tid)||{};byThread.set(tid,{threadId:tid,title:ex.title||task.clarified_goal||task.goal||'Cuộc chat trước',status:String(task.status||ex.status||'idle'),updatedAt:Math.max(Number(ex.updatedAt||0),Number(task.updated_at||0)*(Number(task.updated_at||0)<10000000000?1000:1))});}
        var history=[...byThread.values()].sort(function(a,b){return b.updatedAt-a.updatedAt;});
        if(!history.length){drawerBody.innerHTML='<div class="empty"><div class="empty-inner"><p>Chưa có cuộc trò chuyện trước.</p></div></div>';return;}
        for(var item of history)(function(i){var b=document.createElement('button');b.className='drawer-card';b.innerHTML='<strong>'+esc(i.title||'Cuộc chat trước')+'</strong><span>'+esc(i.status||'idle')+'</span>';b.onclick=function(){drawer.classList.remove('visible');selectSessionFromUi(i.threadId);};drawerBody.appendChild(b);})(item);
        return;
      }
      if(kind==='tasks'){
        drawerTitle.textContent='Tác vụ';if(!catalogTasks.length){drawerBody.innerHTML='<div class="empty"><div class="empty-inner"><p>Chưa có tác vụ.</p></div></div>';return;}
        for(var t of [...catalogTasks].reverse())(function(task){var b=document.createElement('button');b.className='drawer-card';b.innerHTML='<strong>'+esc(task.clarified_goal||task.goal||task.task_id||'Tác vụ')+'</strong><span>'+esc(statusName(task.status||'idle')+(task.coding_state&&task.coding_state.current_file?' \xB7 '+task.coding_state.current_file:''))+'</span>';b.onclick=function(){drawer.classList.remove('visible');selectSessionFromUi(String(task.thread_id||''));};drawerBody.appendChild(b);})(t);
        return;
      }
      drawerTitle.textContent='Kỹ năng';if(!catalogSkills.length){drawerBody.innerHTML='<div class="empty"><div class="empty-inner"><p>Service chưa gửi danh sách kỹ năng.</p></div></div>';return;}
      for(var skill of catalogSkills){var b=document.createElement('div');b.className='drawer-card';b.innerHTML='<strong>'+esc(skill.label||skill.name||skill.id||'Kỹ năng')+'</strong><span>'+esc(skill.description||skill.summary||'')+'</span>';drawerBody.appendChild(b);}
    }
    
    document.getElementById('newChat').onclick=function(){vscode.postMessage({type:'newChat'});}
    document.getElementById('menuButton').onclick=function(e){e.stopPropagation();contextPopover.classList.remove('visible');modePopover.classList.remove('visible');modelPopover.classList.remove('visible');menuPopover.classList.toggle('visible');};
    document.getElementById('reconnect').onclick=function(){vscode.postMessage({type:'reconnect'});};
    document.getElementById('attach').onclick=function(){vscode.postMessage({type:'attachment.pick'});};
    document.getElementById('contextButton').onclick=function(e){e.stopPropagation();menuPopover.classList.remove('visible');modePopover.classList.remove('visible');modelPopover.classList.remove('visible');contextPopover.classList.toggle('visible');};
    modeButton.onclick=function(e){e.stopPropagation();contextPopover.classList.remove('visible');menuPopover.classList.remove('visible');modelPopover.classList.remove('visible');modePopover.classList.toggle('visible');modeButton.classList.toggle('active',modePopover.classList.contains('visible'));modelButton.classList.remove('active');};
    modelButton.onclick=function(e){e.stopPropagation();contextPopover.classList.remove('visible');menuPopover.classList.remove('visible');modePopover.classList.remove('visible');modelPopover.classList.toggle('visible');modelButton.classList.toggle('active',modelPopover.classList.contains('visible'));modeButton.classList.remove('active');};
    for(var mrow of modePopover.querySelectorAll('[data-mode]'))mrow.onclick=function(){setMode(this.dataset.mode||'execute');hidePopovers();input.focus();};
    for(var grow of modelPopover.querySelectorAll('[data-model]'))grow.onclick=function(){setModel(this.dataset.model||'gemini-3-flash');hidePopovers();input.focus();};
    document.getElementById('send').onclick=send;
    
    document.getElementById('drawerBack').onclick=function(){drawer.classList.remove('visible');};
    for(var dmrow of document.querySelectorAll('[data-menu]'))(function(row){row.onclick=function(){var a=row.dataset.menu;hidePopovers();if(a==='new')vscode.postMessage({type:'newChat'});else if(a==='history'||a==='tasks'||a==='skills')renderDrawer(a);else if(a==='source')vscode.postMessage({type:'showSourceControl'});else if(a==='test')vscode.postMessage({type:'selfTest'});else if(a==='reconnect')vscode.postMessage({type:'reconnect'});else if(a==='settings')vscode.postMessage({type:'settings'});};})(dmrow);
    input.addEventListener('input',resizeInput);
    input.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});
    document.addEventListener('click',function(){hidePopovers();});
    menuPopover.onclick=function(e){e.stopPropagation();};
    contextPopover.onclick=function(e){e.stopPropagation();};
    modePopover.onclick=function(e){e.stopPropagation();};
    modelPopover.onclick=function(e){e.stopPropagation();};
    sessionTabs.addEventListener('scroll',updateSessionIndicator,{passive:true});
    window.addEventListener('resize',updateSessionIndicator);
    
    async function ingestFiles(files){for(var file of [...files].slice(0,8)){if(file.type.startsWith('image/')){(function(f){var reader=new FileReader();reader.onload=function(){vscode.postMessage({type:'attachment.image',name:f.name||'image.png',dataUrl:String(reader.result||'')});};reader.readAsDataURL(f);})(file);}}} 
    input.addEventListener('paste',function(e){var files=[...(e.clipboardData&&e.clipboardData.files||[])];if(files.some(function(f){return f.type.startsWith('image/');})){e.preventDefault();ingestFiles(files);}});
    var dragDepth=0;
    document.addEventListener('dragenter',function(e){if(e.dataTransfer&&e.dataTransfer.types&&e.dataTransfer.types.includes('Files')){dragDepth++;document.getElementById('dropOverlay').classList.add('visible');}});
    document.addEventListener('dragleave',function(){dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)document.getElementById('dropOverlay').classList.remove('visible');});
    document.addEventListener('dragover',function(e){if(e.dataTransfer&&e.dataTransfer.types&&e.dataTransfer.types.includes('Files'))e.preventDefault();});
    document.addEventListener('drop',function(e){dragDepth=0;document.getElementById('dropOverlay').classList.remove('visible');if(e.dataTransfer&&e.dataTransfer.files&&e.dataTransfer.files.length){e.preventDefault();ingestFiles(e.dataTransfer.files);}});
    
    window.addEventListener('message',function(ev){
      var event=ev.data;
      if(event.type==='session.tabs'){sessions=Array.isArray(event.sessions)?event.sessions:[];activeThreadId=String(event.activeThreadId||'');renderSessions();return;}
      if(event.type==='chat.reset'){activeThreadId=String(event.threadId||activeThreadId);activeTaskId=String(event.preserveTask||'');drawer.classList.remove('visible');if(event.reason==='new'){var d=pendingSwitchDirection||1;clearTimeline(false);ensureEmpty();animateTimelineIn(d);awaitingThreadHistory=false;pendingSwitchDirection=0;deferredEvents=[];}return;}
      if(event.type==='connection'){var connected=event.state==='connected';var connecting=event.state==='connecting';connection.classList.toggle('visible',!connected);connection.classList.toggle('connecting',connecting);document.getElementById('connectionText').textContent=connecting?'Đang kết nối Eris Service…':'Mất kết nối với Eris Service';return;}
      if(event.type==='service.error'){return;}
      if(event.type==='attachment.add'){var att=Object.assign({},event.attachment||{},{preview:event.preview||''});if(att.id){attachmentState.set(att.id,att);renderAttachments();}return;}
      if(event.type==='attachments.clear'){attachmentState.clear();renderAttachments();return;}
      if(event.type==='session.ready'){catalogTasks=Array.isArray(event.tasks)?event.tasks:catalogTasks;catalogSkills=Array.isArray(event.capabilities&&event.capabilities.brain&&event.capabilities.brain.skills?event.capabilities.brain.skills:null)?event.capabilities.brain.skills:catalogSkills;return;}
      if(event.type==='task.list'){catalogTasks=Array.isArray(event.tasks)?event.tasks:[];return;}
      if(event.type==='thread.history'){renderHistory(event);return;}
      if(event.type==='task.detail'){if(event.task){catalogTasks=[...new Map([...catalogTasks,event.task].map(function(t){return[String(t&&t.task_id?t.task_id:''),t];})).values()];}return;}
      if(event.type==='message.accepted'){activeTaskId=String(event.taskId||activeTaskId);return;}
      if(event.type==='client.error'||event.type==='error'){showNotice(event.message||event.code||'Eris Service gặp lỗi');return;}
      if(awaitingThreadHistory){deferredEvents.push(event);return;}
      renderEvent(event);
    });
    
    sessionStrip.classList.add('no-sessions');
    ensureEmpty();
    resizeInput();
    document.documentElement.dataset.erisBoot = 'ready';
  } catch (error) {
    showBootError(error);
  }
})();
