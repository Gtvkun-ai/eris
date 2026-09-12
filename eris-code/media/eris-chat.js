
const vscode=acquireVsCodeApi();
const timeline=document.getElementById('timeline');
const input=document.getElementById('input');
const sessionTabs=document.getElementById('sessionTabs');
const sessionIndicator=document.getElementById('sessionIndicator');
const connection=document.getElementById('connection');
const sendButton=document.getElementById('send');
const attachmentBox=document.getElementById('attachments');
const contextSummary=document.getElementById('contextSummary');
const contextButton=document.getElementById('contextButton');
const notice=document.getElementById('notice');
const drawer=document.getElementById('drawer');
const drawerBody=document.getElementById('drawerBody');
const drawerTitle=document.getElementById('drawerTitle');
const menuPopover=document.getElementById('menuPopover');
const contextPopover=document.getElementById('contextPopover');
const planButton=document.getElementById('planButton');
const modelButton=document.getElementById('modelButton');
const modelPopover=document.getElementById('modelPopover');
const autopilotToggle=document.getElementById('autopilotToggle');
const workspaceMode=document.getElementById('workspaceMode'); // optional; chỉ hiện khi có nhiều môi trường
const NEW_SESSION_LABEL='Phiên mới';
const PREVIOUS_SESSION_LABEL='Phiên trước';

let activeThreadId='';
let activeTaskId='';
let sessions=[];
let catalogTasks=[];
let catalogSkills=[];
let planNextTurn=false;
let pendingTaskMode='auto';
const taskModes=new Map();
const persistedUiState=vscode.getState()||{};
let autopilotEnabled=persistedUiState.autopilot!==false;
let selectedModel=persistedUiState.model||'auto';
const rendered=new Set();
const pendingInterrupts=new Set();
const pendingInterruptNodes=new Map();
const attachmentState=new Map();
const taskGroups=new Map();
let composerContext={};
const knownTabs=new Set();
let pendingSwitchDirection=0;
let awaitingThreadHistory=false;
let deferredEvents=[];
let stickToBottom=true;

const MODEL_LABELS={
  'deepseek-v4-flash':'DS Flash',
  'deepseek-v4-pro':'DS Pro',
  'auto':'Auto'
};
if(!MODEL_LABELS[selectedModel]||String(selectedModel).indexOf('gemini-')===0){
  selectedModel='auto';
  vscode.setState(Object.assign({},vscode.getState(),{model:selectedModel}));
}
function syncPlanUi(){
  planButton.classList.toggle('active',planNextTurn);
  planButton.setAttribute('aria-pressed',String(planNextTurn));
  planButton.title=planNextTurn?'Plan đang bật · lượt này chỉ lập kế hoạch':'Plan · đọc repo và lập kế hoạch, không sửa file';
  input.placeholder=planNextTurn?'Mô tả việc cần lập kế hoạch…':'Giao việc cho Eris…';
}
function syncAutopilotUi(){
  autopilotToggle.classList.toggle('active',autopilotEnabled);
  autopilotToggle.setAttribute('aria-checked',String(autopilotEnabled));
  autopilotToggle.title=autopilotEnabled?'Tự làm tiếp đến khi hoàn tất.':'Tự động đang tắt.';
}
function syncModelUi(){
  modelButton.textContent=MODEL_LABELS[selectedModel]||'Flash';
  for(var opt of document.querySelectorAll('[data-model-option]'))opt.classList.toggle('active',opt.dataset.modelOption===selectedModel);
  modelButton.classList.toggle('active',modelPopover.classList.contains('visible'));
  modelButton.setAttribute('aria-expanded', String(modelPopover.classList.contains('visible')));
}

function placeSelectPopover(button,popover,alignRight){
  if(!popover.classList.contains('visible'))return;
  var margin=8;
  var rect=button.getBoundingClientRect();
  var width=Math.min(220,Math.max(150,window.innerWidth-margin*2));
  popover.style.width=Math.round(width)+'px';
  popover.style.right='auto';
  popover.style.bottom='auto';
  var left=alignRight?rect.right-width:rect.left;
  left=Math.max(margin,Math.min(left,window.innerWidth-width-margin));
  popover.style.left=Math.round(left)+'px';
  // Menu phải nằm trọn trong viewport của sidebar. Width của sidebar thay đổi
  // liên tục khi user kéo panel nên không thể neo cứng theo select-wrap.
  var height=popover.offsetHeight||0;
  var top=rect.top-height-8;
  if(top<margin&&rect.bottom+8+height<=window.innerHeight-margin)top=rect.bottom+8;
  top=Math.max(margin,Math.min(top,window.innerHeight-height-margin));
  popover.style.top=Math.round(top)+'px';
}
function placeOpenSelectPopovers(){
  placeSelectPopover(modelButton,modelPopover,true);
}

const esc=function(v){return String(v==null?'':v).replace(/[&<>"']/g,function(ch){return({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[ch];});};
const clip=function(v,n){n=n||80;var t=String(v==null?'':v).replace(/\s+/g,' ').trim();return t.length<=n?t:t.slice(0,n-1)+'…';};
function isNearBottom(){return (timeline.scrollHeight-(timeline.scrollTop+timeline.clientHeight))<72;}
const scroll=function(force){requestAnimationFrame(function(){if(force||stickToBottom){timeline.scrollTop=timeline.scrollHeight;}});};
const fmtBytes=function(n){var v=Number(n||0);if(v<1024)return v+' B';if(v<1048576)return Math.round(v/102.4)/10+' KB';return Math.round(v/104857.6)/10+' MB';};

/* Markdown renderer nhỏ, không dùng HTML thô từ model. Mọi text đều escape
   trước khi gắn markup nên stream không thể chèn script hoặc tag tùy ý. */
function inlineMarkdown(value){
  var raw=String(value==null?'':value);var tick=String.fromCharCode(96);var parts=raw.split(tick);
  return parts.map(function(part,index){
    if(index%2===1)return '<code>'+esc(part)+'</code>';
    var safe=esc(part);
    safe=safe.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
    safe=safe.replace(/__([^_]+)__/g,'<strong>$1</strong>');
    safe=safe.replace(/(^|[^*])\*([^*\n]+)\*/g,'$1<em>$2</em>');
    safe=safe.replace(/(^|[^_])_([^_\n]+)_/g,'$1<em>$2</em>');
    return safe;
  }).join('');
}
function splitTableRow(line){
  var text=String(line||'').trim();
  if(text[0]==='|')text=text.slice(1);
  if(text[text.length-1]==='|')text=text.slice(0,-1);
  return text.split('|').map(function(cell){return cell.trim();});
}
function renderMarkdown(markdown){
  var lines=String(markdown==null?'':markdown).replace(/\r\n?/g,'\n').split('\n');
  var out=[];var paragraph=[];var listType='';var quote=[];var fence=false;var fenceLang='';var code=[];
  function flushParagraph(){if(!paragraph.length)return;out.push('<p>'+paragraph.map(inlineMarkdown).join(' ')+'</p>');paragraph=[];}
  function closeList(){if(listType){out.push('</'+listType+'>');listType='';}}
  function flushQuote(){if(!quote.length)return;out.push('<blockquote>'+quote.map(inlineMarkdown).join('<br>')+'</blockquote>');quote=[];}
  function flushCode(){
    if(!fence)return;
    var lang=fenceLang?'<span class="code-lang">'+esc(fenceLang)+'</span>':'';
    out.push('<pre>'+lang+'<code>'+esc(code.join('\n'))+'</code></pre>');
    fence=false;fenceLang='';code=[];
  }
  for(var i=0;i<lines.length;i++){
    var line=lines[i];var trimmed=line.trim();var fenceToken=String.fromCharCode(96).repeat(3);
    if(trimmed.indexOf(fenceToken)===0){
      if(fence){flushCode();}else{flushParagraph();closeList();flushQuote();fence=true;fenceLang=trimmed.slice(3).trim().slice(0,24);}
      continue;
    }
    if(fence){code.push(line);continue;}
    if(!trimmed){flushParagraph();closeList();flushQuote();continue;}

    /* Table GitHub-style cơ bản: header + separator + các row kế tiếp. */
    if(line.indexOf('|')>=0&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])&&lines[i+1].indexOf('|')>=0){
      flushParagraph();closeList();flushQuote();
      var headers=splitTableRow(line);i+=1;var rows=[];
      while(i+1<lines.length&&lines[i+1].trim()&&lines[i+1].indexOf('|')>=0){i+=1;rows.push(splitTableRow(lines[i]));}
      var table='<table><thead><tr>'+headers.map(function(c){return '<th>'+inlineMarkdown(c)+'</th>';}).join('')+'</tr></thead><tbody>';
      for(var r of rows)table+='<tr>'+headers.map(function(_,idx){return '<td>'+inlineMarkdown(r[idx]||'')+'</td>';}).join('')+'</tr>';
      out.push(table+'</tbody></table>');continue;
    }
    var h=/^(#{1,4})\s+(.+)$/.exec(line);
    if(h){flushParagraph();closeList();flushQuote();var level=h[1].length;out.push('<h'+level+'>'+inlineMarkdown(h[2])+'</h'+level+'>');continue;}
    if(/^\s*(?:---+|___+|\*\*\*+)\s*$/.test(line)){flushParagraph();closeList();flushQuote();out.push('<hr>');continue;}
    var ul=/^\s*[-*]\s+(.+)$/.exec(line);
    if(ul){flushParagraph();flushQuote();if(listType!=='ul'){closeList();listType='ul';out.push('<ul>');}out.push('<li>'+inlineMarkdown(ul[1])+'</li>');continue;}
    var ol=/^\s*\d+[.)]\s+(.+)$/.exec(line);
    if(ol){flushParagraph();flushQuote();if(listType!=='ol'){closeList();listType='ol';out.push('<ol>');}out.push('<li>'+inlineMarkdown(ol[1])+'</li>');continue;}
    var bq=/^\s*>\s?(.*)$/.exec(line);
    if(bq){flushParagraph();closeList();quote.push(bq[1]);continue;}
    closeList();flushQuote();paragraph.push(line.trim());
  }
  if(fence)flushCode();flushParagraph();closeList();flushQuote();return out.join('');
}
function decorateMarkdown(entry){
  /* Copy button chỉ đọc text đã render, không chạy HTML/model code. */
  for(var pre of entry.bubbleEl.querySelectorAll('pre')){
    if(pre.querySelector('.code-copy'))continue;
    var copy=document.createElement('button');copy.className='code-copy';copy.type='button';copy.textContent='Copy';
    copy.onclick=function(ev){ev.stopPropagation();var code=this.parentElement&&this.parentElement.querySelector('code');var value=code?code.textContent||'':'';vscode.postMessage({type:'clipboard.write',text:value});this.textContent='Đã copy';var self=this;setTimeout(function(){self.textContent='Copy';},900);};
    pre.appendChild(copy);
  }
  /* Inline code giống đường dẫn repo có thể mở thẳng file. */
  for(var code of entry.bubbleEl.querySelectorAll('code')){
    if(code.closest('pre'))continue;
    var raw=String(code.textContent||'').trim();
    var m=/^((?:src|app|lib|test|tests|packages|runtime|vscode-extension|assets|scripts|docs)[\\/][^\s]+?\.[A-Za-z0-9]{1,8})(?::(\d+))?(?::(\d+))?$/.exec(raw);
    if(!m)continue;
    code.classList.add('file-ref');code.title='Mở '+m[1];
    (function(path,line,column,node){node.onclick=function(){vscode.postMessage({type:'openArtifact',path:path,line:Number(line||1),column:Number(column||1)});};})(m[1],m[2],m[3],code);
  }
}
function scheduleMarkdown(entry){
  if(entry.renderPending)return;entry.renderPending=true;
  requestAnimationFrame(function(){entry.renderPending=false;entry.bubbleEl.innerHTML='<div class="markdown-body">'+renderMarkdown(entry.markdownText||'')+'</div>';decorateMarkdown(entry);scroll();});
}

/* Semantic labels: UI hiển thị hành động con người hiểu, không hiển thị RPC. */
const TOOL_LABELS={
  project_list_files:'Đọc cấu trúc dự án',project_read_file:'Đọc file',project_search_text:'Tìm trong code',project_find_symbol:'Tìm symbol',project_git_diff:'Kiểm tra thay đổi Git',project_apply_patch:'Áp dụng thay đổi',project_run_tests:'Chạy kiểm thử',project_run_command:'Chạy lệnh dự án',editor_open_file:'Mở file trong VS Code',editor_open_diff:'Mở diff',editor_focus_problems:'Mở Problems',editor_show_source_control:'Mở Source Control',ide_get_current_file:'Đọc file hiện tại',ide_get_selection:'Đọc vùng chọn',ide_get_problems:'Đọc lỗi và cảnh báo',ide_get_git_state:'Đọc trạng thái Git',ide_get_terminal_recent:'Đọc terminal gần nhất',ide_get_open_editors:'Đọc các tab đang mở',ide_get_workspace_info:'Đọc workspace',search_capabilities:'Tìm capability phù hợp',activate_skill:'Nạp skill cần thiết',ask_user_choice:'Chờ quyết định của bạn'
};
const KIND_LABELS={agent_plan:'Lập kế hoạch thực thi',skill_search:'Tìm capability phù hợp',skill_activated:'Nạp skill cần thiết',checkpoint_created:'Tạo checkpoint',checkpoint_restored:'Khôi phục checkpoint',repository_context_started:'Đọc và lập bản đồ repository',repository_context_ready:'Hiểu cấu trúc repository',context_gate_blocked:'Bổ sung ngữ cảnh trước khi sửa',completion_gate_blocked:'Xác minh thay đổi trước khi hoàn tất',supervisor_comment:'Eris rà lại hướng thực thi',supervisor_advisory:'Eris rà lại hướng thực thi',supervisor_redirect:'Eris đổi hướng thực thi',supervisor_veto:'Eris chặn hướng không phù hợp',task_paused:'Task đã tạm dừng',task_resumed:'Task đang tiếp tục',rollback_requested:'Khôi phục thay đổi',rollback_queued:'Khôi phục thay đổi',rollback_failed:'Khôi phục thất bại'};
function toolNameFromPayload(p){var d=p&&p.data&&typeof p.data==='object'?p.data:{};return String(d.tool||d.name||'').trim();}
function semanticToolLabel(tool){return TOOL_LABELS[tool]||String(tool||'Công cụ').replace(/_/g,' ');}
function cleanActivityText(value){
  var t=String(value==null?'':value).replace(/\s+/g,' ').trim();
  /* Chặn label legacy kiểu Bước kế tiếp: tool_a, tool_b từ history cũ. */
  if(/^Bước kế tiếp:/i.test(t))return 'Đang lập kế hoạch thực thi';
  return t;
}
const eventKey=function(e){
  // Protocol cũ từng chiếu activity.end + message.assistant cùng eventId.
  // Luôn thêm semantic type để history cũ cũng không nuốt mất final message.
  var id=String(e&&e.eventId!=null?e.eventId:e&&e.event_id!=null?e.event_id:'');
  return id?[id,e&&e.type].join(':'):[e&&e.type,e&&e.taskId,e&&e.seq,e&&e.timestamp].join(':');
};
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
  sessionTabs.innerHTML='';
  var liveIds=new Set(sessions.map(function(s){return String(s.threadId||'');}));
  for(var k of [...knownTabs])if(!liveIds.has(k))knownTabs.delete(k);
  for(var session of sessions){
    var tab=document.createElement('button');
    var isFresh=!knownTabs.has(session.threadId);
    tab.className='session-tab'+(session.threadId===activeThreadId?' active':'')+(isFresh?' tab-enter':'');
    tab.dataset.threadId=session.threadId;
    tab.title=session.title||NEW_SESSION_LABEL;
    var dot=document.createElement('span');dot.className='session-state '+String(session.status||'idle');
    var title=document.createElement('span');title.className='session-title';title.textContent=session.title||NEW_SESSION_LABEL;
    var close=document.createElement('button');close.className='close-tab';close.textContent='×';close.title='Đóng';
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
  // Update compact header title
  var headerTitle=document.getElementById('sessionHeaderTitle');
  if(headerTitle){
    var active=sessions.find(function(s){return s.threadId===activeThreadId;});
    var label=active?active.title||NEW_SESSION_LABEL:'Eris';
    var status=active?String(active.status||'idle'):'idle';
    // Header chỉ giữ tên session. Trạng thái task đã có Activity/Plan bên dưới.
    headerTitle.textContent=(label===NEW_SESSION_LABEL||!label)?'Eris Code':label;
    headerTitle.title=label||'Eris';
  }
  updateComposerState();
}

function relativeTime(ts){
  var delta=Math.max(0,Date.now()-Number(ts||0));
  if(delta<60*60*1000)return Math.max(1,Math.round(delta/60000))+' phút';
  if(delta<24*60*60*1000)return Math.max(1,Math.round(delta/3600000))+' giờ';
  return Math.max(1,Math.round(delta/86400000))+' ngày';
}
function recentSessions(){
  return sessions.filter(function(item){return String(item.threadId||'')!==activeThreadId;}).sort(function(a,b){return Number(b.updatedAt||0)-Number(a.updatedAt||0);}).slice(0,3);
}
function recentChatsHtml(recent){
  recent=Array.isArray(recent)?recent:recentSessions();
  if(!recent.length)return '<div class="recent-empty">Chưa có cuộc trò chuyện nào.</div>';
  return recent.map(function(item){return '<button class="recent-chat" type="button" data-recent-thread="'+esc(item.threadId||'')+'"><span>'+esc(item.title||PREVIOUS_SESSION_LABEL)+'</span><time>'+esc(relativeTime(item.updatedAt))+'</time></button>';}).join('');
}
function emptyHtml(){var recent=recentSessions();return '<div class="empty codex-empty" id="chatEmpty">'+
  '<section class="empty-hero"><div class="empty-hero-head"><div class="empty-mark">✦</div><div><div class="empty-eyebrow">Eris workspace</div><h2>Hôm nay xử gì?</h2></div></div><div class="empty-prompts"><button type="button" data-empty-prompt="Đánh giá nhanh repo này">Đánh giá repo</button><button type="button" data-empty-prompt="Tìm lỗi trong file đang mở">Sửa file đang mở</button><button type="button" data-empty-prompt="Viết test cho thay đổi gần nhất">Viết test</button></div></section>'+
  '<section class="recent-section"><div class="recent-title">Trò chuyện gần đây</div><div class="recent-chats">'+recentChatsHtml(recent)+'</div>'+(recent.length?'<button class="recent-all" id="recentAll" type="button">Xem tất cả</button>':'')+'</section>'+
'</div>';}
function ensureEmpty(){if(!timeline.children.length){timeline.innerHTML=emptyHtml();bindEmptyActions();}}
function refreshEmpty(){var e=document.getElementById('chatEmpty');if(!e)return;e.outerHTML=emptyHtml();bindEmptyActions();}
function removeEmpty(){var e=document.getElementById('chatEmpty');if(e)e.remove();}
function bindEmptyActions(){
  for(var action of timeline.querySelectorAll('[data-recent-thread]'))(function(a){a.onclick=function(){selectSessionFromUi(String(a.dataset.recentThread||''));};})(action);
  for(var prompt of timeline.querySelectorAll('[data-empty-prompt]'))(function(btn){btn.onclick=function(){input.value=String(btn.dataset.emptyPrompt||'');resizeInput();input.focus();};})(prompt);
  var all=document.getElementById('recentAll');if(all)all.onclick=function(){renderDrawer('history');};
}
function clearTimeline(showEmpty){if(showEmpty===undefined)showEmpty=true;timeline.innerHTML='';rendered.clear();pendingInterrupts.clear();pendingInterruptNodes.clear();taskGroups.clear();activeTaskId='';if(showEmpty)ensureEmpty();}
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
  var role=document.createElement('div');role.className='msg-role';role.textContent='Bạn';
  var bubble=document.createElement('div');bubble.className='bubble';bubble.textContent=String(content==null?'':content);
  body.append(role,bubble);
  if(Array.isArray(attachments)&&attachments.length){
    var row=document.createElement('div');row.className='msg-attachments';
    for(var item of attachments.slice(0,8)){
      var chip=document.createElement('div');chip.className='attach-chip-sm';
      chip.textContent=(String(item.kind||'')==='image'?'▧ ':'▤ ')+(item.name||item.relativePath||'attachment');
      row.appendChild(chip);
    }
    body.appendChild(row);
  }
  var spacer=document.createElement('div');spacer.className='avatar-spacer';
  msg.append(body,spacer);
  /* Fix ordering: if Eris group for current task already exists in DOM
     (activity events arrived before message.user in history replay),
     insert user bubble BEFORE it so conversation reads top-to-bottom */
  var existingGroup=taskGroups.has(String(activeTaskId||'main'))?taskGroups.get(String(activeTaskId||'main')).groupEl:null;
  if(existingGroup&&existingGroup.parentNode===timeline){
    timeline.insertBefore(msg,existingGroup);
  } else {
    timeline.appendChild(msg);
  }
  scroll();
}

function getTaskGroup(taskId){
  var key=String(taskId||activeTaskId||'main');
  if(taskGroups.has(key))return taskGroups.get(key);
  removeEmpty();
  var group=document.createElement('div');group.className='msg msg-assistant';group.dataset.taskId=key;
  var avatar=document.createElement('div');avatar.className='avatar';avatar.textContent='✦';
  var body=document.createElement('div');body.className='msg-body';
  var role=document.createElement('div');role.className='msg-role';role.textContent='Eris';

  /* Activity là một group semantic duy nhất. User mở group khi cần xem steps. */
  var feed=document.createElement('details');feed.className='activity-feed';feed.style.display='none';
  var feedSum=document.createElement('summary');
  feedSum.innerHTML='<span class="feed-dot"></span><span class="feed-label">Đang xử lý…</span><span class="feed-count"></span><span class="feed-chevron">›</span>';
  var feedRows=document.createElement('div');feedRows.className='feed-rows';
  var developer=document.createElement('details');developer.className='developer-details';
  developer.innerHTML='<summary>Chi tiết kỹ thuật</summary><pre></pre>';
  feed.append(feedSum,feedRows,developer);

  /* Plan là state người dùng hiểu được; raw tool trace vẫn nằm trong Activity. */
  var plan=document.createElement('div');plan.className='plan-block';plan.style.display='none';
  plan.innerHTML='<div class="plan-head"><span>Kế hoạch</span><span class="plan-meta"></span></div><div class="plan-list"></div>';

  /* Lỗi có surface riêng để thấy agent đang phục hồi thay vì chỉ thấy tool fail. */
  var issues=document.createElement('div');issues.className='issues-host';
  var interruptHost=document.createElement('div');interruptHost.className='interrupt-host';

  /* Các file thay đổi được gom cạnh nhau như một review surface, không rải card. */
  var changes=document.createElement('div');changes.className='changes-block';changes.style.display='none';
  changes.innerHTML='<div class="changes-head"><span class="changes-title"><strong>Thay đổi</strong><span class="changes-meta"></span></span><button class="changes-review" type="button">Xem thay đổi</button></div><div class="changes-list"></div><div class="changeset-actions" style="display:none"></div>';
  changes.querySelector('.changes-review').onclick=function(){vscode.postMessage({type:'showSourceControl'});};

  /* Assistant document chỉ xuất hiện khi model thật sự có nội dung. */
  var bubble=document.createElement('div');bubble.className='bubble';
  var controls=document.createElement('div');controls.className='task-controls';controls.style.display='none';
  controls.innerHTML='<button class="ctrl-btn" data-control="pause">Tạm dừng</button><button class="ctrl-btn" data-control="resume">Tiếp tục</button><button class="ctrl-btn" data-control="rollback">Khôi phục</button><button class="ctrl-btn" data-control="stop">Dừng</button>';
  for(var btn of controls.querySelectorAll('[data-control]'))(function(b,k){b.onclick=function(){requestTaskControl(k,b.dataset.control);};})(btn,key);

  body.append(role,plan,feed,issues,interruptHost,changes,bubble,controls);group.append(avatar,body);timeline.appendChild(group);
  var entry={
    groupEl:group,bubbleEl:bubble,feedEl:feed,feedRowsEl:feedRows,feedLabelEl:feedSum.querySelector('.feed-label'),feedCountEl:feedSum.querySelector('.feed-count'),developerEl:developer,developerPreEl:developer.querySelector('pre'),controlsEl:controls,
    planEl:plan,planListEl:plan.querySelector('.plan-list'),planMetaEl:plan.querySelector('.plan-meta'),planSteps:new Map(),issuesEl:issues,issueRows:new Map(),interruptHostEl:interruptHost,
    changesEl:changes,changesListEl:changes.querySelector('.changes-list'),changesMetaEl:changes.querySelector('.changes-meta'),changeSetEl:changes.querySelector('.changeset-actions'),
    markdownText:'',renderPending:false,status:'running',currentLabel:'Đang hiểu yêu cầu',taskMode:taskModes.get(key)||'auto',operationRows:new Map(),rawEvents:[],files:new Set(),changeFiles:new Map(),actionCount:0,startedAt:Date.now()
  };
  taskGroups.set(key,entry);stickToBottom=true;scroll(true);return entry;
}


function recordRawEvent(entry,event){
  var p=event&&event.payload?event.payload:{};
  var raw={type:String(event&&event.type||''),kind:String(p.kind||''),label:cleanActivityText(p.label||''),detail:clip(p.detail||'',1200)};
  if(p.data&&typeof p.data==='object')raw.data=p.data;
  entry.rawEvents.push(raw);while(entry.rawEvents.length>30)entry.rawEvents.shift();
  try{entry.developerPreEl.textContent=JSON.stringify(entry.rawEvents,null,2);}catch(_){entry.developerPreEl.textContent='Không thể hiển thị telemetry.';}
}
function toolSuffix(p){
  var data=p&&p.data&&typeof p.data==='object'?p.data:{};var args=data.args&&typeof data.args==='object'?data.args:data.arguments&&typeof data.arguments==='object'?data.arguments:{};
  var path=args.path||args.file||args.file_path||args.relative_path||args.target||'';
  if(path)return clip(String(path).replace(/\\/g,'/'),42);
  var query=args.query||args.pattern||args.symbol||'';
  if(query)return clip(String(query),42);
  return '';
}
function planKey(label){return String(label||'').toLowerCase().replace(/^đang\s+/,'').replace(/[:·].*$/,'').replace(/[^a-z0-9à-ỹ]+/gi,' ').replace(/\s+/g,' ').trim();}
function setPlanStep(entry,label,status){
  label=cleanActivityText(label);if(!label)return;
  var key=planKey(label);if(!key)return;var item=entry.planSteps.get(key);
  if(!item){var row=document.createElement('div');row.className='plan-row pending';var mark=document.createElement('span');mark.className='plan-mark';var text=document.createElement('span');text.textContent=label;row.append(mark,text);entry.planListEl.appendChild(row);item={row:row,mark:mark,text:text,label:label,status:'pending'};entry.planSteps.set(key,item);}
  item.status=status||item.status;item.row.classList.remove('pending','running','done','failed');item.row.classList.add(item.status);
  item.mark.textContent=item.status==='done'?'✓':item.status==='failed'?'×':item.status==='running'?'●':'○';
  entry.planEl.style.display=entry.taskMode==='plan'?'':'none';entry.planMetaEl.textContent=entry.planSteps.size+' bước';return item;
}
function syncPlan(entry,steps){
  steps=Array.isArray(steps)?steps.map(cleanActivityText).filter(Boolean):[];if(!steps.length)return;
  /* Plan mới hoàn thành bước active cũ nếu model đã replan sang cụm hành động khác. */
  var incoming=new Set(steps.map(planKey));
  for(var old of entry.planSteps.values())if(old.status==='running'&&!incoming.has(planKey(old.label)))setPlanStep(entry,old.label,'done');
  steps.forEach(function(step,index){var existing=entry.planSteps.get(planKey(step));setPlanStep(entry,step,existing&&['done','failed'].includes(existing.status)?existing.status:(index===0?'running':'pending'));});
}
function markPlanByLabel(entry,label,status){
  var target=planKey(label);if(!target)return;var best=null;
  for(var item of entry.planSteps.values()){var k=planKey(item.label);if(k===target||k.includes(target)||target.includes(k)){best=item;break;}}
  if(best)setPlanStep(entry,best.label,status);
}
function setIssue(entry,key,title,detail,status){
  key=String(key||title||'issue');var row=entry.issueRows.get(key);
  if(!row){row=document.createElement('div');row.className='issue-row';row.innerHTML='<span class="issue-icon">×</span><span class="issue-copy"><strong></strong><span></span></span>';entry.issuesEl.appendChild(row);entry.issueRows.set(key,row);}
  var recovered=status==='recovered';row.classList.toggle('recovered',recovered);row.querySelector('.issue-icon').textContent=recovered?'✓':'×';row.querySelector('strong').textContent=recovered?'Đã phục hồi':String(title||'Có lỗi');row.querySelector('.issue-copy span').textContent=clip(detail||title||'',220);return row;
}
function simpleActivityLabel(label,status){
  var raw=cleanActivityText(label||'').toLowerCase();
  var state=String(status||'running').toLowerCase();
  if(state==='completed'||state==='done')return 'Hoàn tất';
  if(state==='failed')return 'Cần xem lại';
  if(state==='stopped')return 'Đã dừng';
  if(state==='paused')return 'Cần bạn quyết định';
  if(/kế hoạch|plan/.test(raw))return 'Đang lập kế hoạch';
  if(/test|kiểm tra|xác minh|verify|verification|build|lint|typecheck|regression/.test(raw))return 'Đang kiểm tra';
  if(/sửa|patch|ghi file|thay đổi|refactor|tạo file|apply|edit|modify|implement/.test(raw))return 'Đang thực hiện';
  if(/đọc|tìm|repository|repo|context|ngữ cảnh|symbol|file|capability|khả năng|search|inspect/.test(raw))return 'Đang đọc ngữ cảnh';
  if(/phân tích|hiểu yêu cầu|clarif|reason/.test(raw))return 'Đang hiểu yêu cầu';
  if(/thử lại|recover|phục hồi/.test(raw))return 'Đang thử lại';
  return 'Đang làm việc';
}
function updateActivitySummary(entry,label,status){
  if(label)entry.currentLabel=cleanActivityText(label)||entry.currentLabel;
  if(status)entry.status=status;
  var done=entry.status==='completed'||entry.status==='done';var failed=entry.status==='failed'||entry.status==='stopped';var paused=entry.status==='paused';
  entry.feedEl.classList.toggle('done',done);entry.feedEl.classList.toggle('failed',failed);entry.feedEl.classList.toggle('paused',paused);
  entry.feedLabelEl.textContent=simpleActivityLabel(entry.currentLabel,entry.status);
  var meta=[];if(entry.files.size)meta.push(entry.files.size+' tệp');entry.feedCountEl.textContent=meta.join(' · ');
  entry.feedEl.title='Bấm để xem chi tiết';
  entry.controlsEl.style.display=(done||failed)?'none':'flex';
  if(done||failed){entry.feedEl.open=false;for(var step of entry.planSteps.values())if(step.status==='running'||step.status==='pending')setPlanStep(entry,step.label,failed?'failed':'done');}
  /* Mặc định luôn đóng chi tiết. Người dùng chỉ mở khi họ muốn xem tool/trace. */
}

function applyLocalControlState(taskId,action){
  taskId=String(taskId||activeTaskId||'');action=String(action||'').toLowerCase();
  if(!taskId)return;
  var entry=taskGroups.get(taskId);
  if(action==='stop'){
    if(entry)updateActivitySummary(entry,'Đã dừng','stopped');
    syncSessionStatusFromEvent({taskId:taskId,threadId:activeThreadId},'stopped');
    return;
  }
  if(action==='pause'){
    if(entry)updateActivitySummary(entry,'Đã tạm dừng','paused');
    syncSessionStatusFromEvent({taskId:taskId,threadId:activeThreadId},'paused');
  }
}

function requestTaskControl(taskId,action){
  taskId=String(taskId||activeTaskId||'');action=String(action||'').toLowerCase();
  if(!taskId)return;
  applyLocalControlState(taskId,action);
  vscode.postMessage({type:'task.control',taskId:taskId,action:action});
}

function upsertOperation(entry,key,label,status,suffix,increment){
  key=String(key||label||'activity');label=cleanActivityText(label)||'Đang xử lý';status=String(status||'running');
  var op=entry.operationRows.get(key);
  if(!op){
    var row=document.createElement('div');row.className='feed-row';
    var mark=document.createElement('span');mark.className='fmark';
    var text=document.createElement('span');text.className='ftext';
    var meta=document.createElement('span');meta.className='fmeta';row.append(mark,text,meta);entry.feedRowsEl.appendChild(row);
    op={row:row,mark:mark,text:text,meta:meta,label:label,count:0,status:'running',lastSuffix:''};entry.operationRows.set(key,op);
  }
  if(increment!==false){op.count+=1;entry.actionCount+=1;}
  op.label=label;op.status=status;if(suffix)op.lastSuffix=suffix;
  var done=status==='completed'||status==='done';var failed=status==='failed'||status==='stopped';var paused=status==='paused';
  op.row.classList.toggle('done',done);op.row.classList.toggle('failed',failed);op.row.classList.toggle('paused',paused);
  op.mark.textContent=done?'✓':failed?'×':paused?'◦':'·';
  op.text.textContent=op.label+(op.lastSuffix?' · '+op.lastSuffix:'');
  op.meta.textContent=op.count>1?'×'+op.count:'';
  return op;
}

function addActivity(event){
  var p=event.payload||{};var taskId=String(event.taskId||activeTaskId||'');var entry=getTaskGroup(taskId);entry.feedEl.style.display='';recordRawEvent(entry,event);
  var type=String(event.type||'');var kind=String(p.kind||'');var status=String(p.status!=null?p.status:(type==='activity.end'?'completed':'running'));
  var tool=toolNameFromPayload(p);var label=cleanActivityText(p.label!=null?p.label:p.detail!=null?p.detail:'');

  if(type==='activity.start'){
    updateActivitySummary(entry,label||'Đang phân tích yêu cầu','running');scroll();return;
  }
  if(type==='activity.end'){
    var terminalFailed=status==='failed'||status==='stopped';
    if(terminalFailed&&p.detail){upsertOperation(entry,'terminal:error',clip(cleanActivityText(p.detail),150),'failed','',entry.operationRows.has('terminal:error')?false:true);}
    syncSessionStatusFromEvent(event,status);
    updateActivitySummary(entry,label,status);scroll();return;
  }

  /* agent_plan/coding state cập nhật headline; tool events mới tạo rows. */
  if(kind==='agent_plan'){
    var semanticSteps=p.data&&Array.isArray(p.data.semantic_steps)?p.data.semantic_steps:[];syncPlan(entry,semanticSteps);
    upsertOperation(entry,'plan',KIND_LABELS.agent_plan,'completed','',entry.operationRows.has('plan')?false:true);
    updateActivitySummary(entry,semanticSteps.length?semanticSteps[0]:'Đang lập kế hoạch thực thi','running');scroll();return;
  }
  if(kind==='skill_search'){
    /* search_capabilities đã có row tool riêng; event này chỉ giữ trong Developer Details. */
    updateActivitySummary(entry,'Đang tìm capability phù hợp','running');scroll();return;
  }
  if(kind==='repository_context_started'||kind==='repository_context_ready'){
    var repoData=p.data&&typeof p.data==='object'?p.data:{};var repoReady=kind==='repository_context_ready';
    var repoLabel=repoReady?'Đã hiểu cấu trúc repository':'Đang lập bản đồ repository';
    var repoMeta=repoReady?([repoData.files?repoData.files+' file':'',repoData.symbols?repoData.symbols+' symbol':''].filter(Boolean).join(' · ')):'';
    upsertOperation(entry,'repo-context',repoLabel,repoReady?'completed':'running',repoMeta,entry.operationRows.has('repo-context')?false:true);
    updateActivitySummary(entry,repoLabel,repoReady?'running':'running');scroll();return;
  }
  if(kind==='context_gate_blocked'||kind==='completion_gate_blocked'){
    var gateLabel=KIND_LABELS[kind];upsertOperation(entry,'context-gate',gateLabel,'running','',entry.operationRows.has('context-gate')?false:true);updateActivitySummary(entry,gateLabel,'running');scroll();return;
  }
  if(kind==='tool_started'){
    var startLabel=semanticToolLabel(tool);upsertOperation(entry,'tool:'+tool,startLabel,'running',toolSuffix(p),true);markPlanByLabel(entry,startLabel,'running');updateActivitySummary(entry,startLabel,'running');scroll();return;
  }
  if(kind==='tool_result'){
    var resultLabel=semanticToolLabel(tool);upsertOperation(entry,'tool:'+tool,resultLabel,'completed',toolSuffix(p),false);markPlanByLabel(entry,resultLabel,'done');if(entry.issueRows.has('tool:'+tool))setIssue(entry,'tool:'+tool,resultLabel,p.detail||'Agent đã thử lại thành công.','recovered');updateActivitySummary(entry,resultLabel,'running');scroll();return;
  }
  if(kind==='tool_failed'){
    var failLabel=semanticToolLabel(tool);upsertOperation(entry,'tool:'+tool,failLabel,'failed',toolSuffix(p),false);markPlanByLabel(entry,failLabel,'failed');setIssue(entry,'tool:'+tool,failLabel,p.detail||'Tool thất bại; Eris sẽ replan từ lỗi quan sát được.','failed');updateActivitySummary(entry,failLabel,'running');scroll();return;
  }
  if(kind&&KIND_LABELS[kind]){
    var semantic=KIND_LABELS[kind];var completed=['skill_activated','checkpoint_created','checkpoint_restored'].includes(kind);var key='kind:'+kind;
    upsertOperation(entry,key,semantic,completed?'completed':status,'',entry.operationRows.has(key)?false:true);updateActivitySummary(entry,semantic,status);scroll();return;
  }

  /* Các event semantic như Tests/editor.result vẫn được gom, không tạo card raw. */
  var genericLabel=label||'Đang xử lý';var genericKey='generic:'+genericLabel.toLowerCase();
  upsertOperation(entry,genericKey,genericLabel,status,'',entry.operationRows.has(genericKey)?false:true);if(status==='failed')setIssue(entry,genericKey,genericLabel,p.detail||genericLabel,'failed');updateActivitySummary(entry,genericLabel,status);scroll();
}

function mergeCoding(event){
  var p=event.payload||{};var taskId=String(event.taskId||activeTaskId||'');var entry=getTaskGroup(taskId);entry.feedEl.style.display='';
  var title=cleanActivityText(p.current_action||p.next_action||p.phase||'Đang xử lý');var file=String(p.current_file||'').replace(/\\/g,'/');
  if(file)entry.files.add(file);
  var status=String(p.status||'running');var live=title+(file?' · '+clip(file,44):'');updateActivitySummary(entry,live,status);scroll();
}

function disableChoices(node){for(var c of node.querySelectorAll('button,input'))c.disabled=true;}
function permissionDetail(p){
  var tool=String(p.tool||'');var args=p.args&&typeof p.args==='object'?p.args:{};
  if(tool==='project_run_command'&&args.command)return String(args.command);
  if(args.path)return String(args.path);
  if(args.source)return String(args.source);
  var keys=Object.keys(args).slice(0,6);if(!keys.length)return '';
  try{return JSON.stringify(Object.fromEntries(keys.map(function(k){return[k,args[k]];})),null,2);}catch(_){return '';}
}
function resolveInterruptNode(key){
  var node=pendingInterruptNodes.get(String(key||''));if(!node)return;node.classList.add('resolving');disableChoices(node);setTimeout(function(){node.remove();},180);pendingInterruptNodes.delete(String(key||''));pendingInterrupts.delete(String(key||''));
}
function addInterrupt(event){
  removeEmpty();
  var key=String(event.taskId!=null?event.taskId:activeTaskId!=null?activeTaskId:'');
  if(key&&pendingInterrupts.has(key))return;if(key)pendingInterrupts.add(key);
  var p=event.payload||{};var isPermission=String(p.reason||'')==='tool_permission';
  var waitEntry=getTaskGroup(key||'main');waitEntry.feedEl.style.display='';updateActivitySummary(waitEntry,isPermission?'Chờ cấp quyền':'Chờ bạn quyết định','paused');
  var node=document.createElement('div');node.className='interrupt'+(isPermission?' permission':'');
  var question=String(p.question||'Eris cần bạn quyết định');
  var kicker=isPermission?'<div class="interrupt-kicker">Yêu cầu quyền</div>':'';
  var explanation=isPermission?'Eris đã dừng trước side effect này. Quyền chỉ áp dụng cho lần chạy hiện tại.':'Task đã checkpoint và sẽ tiếp tục đúng từ quyết định này.';
  node.innerHTML=kicker+'<h3>'+esc(question)+'</h3><p>'+esc(explanation)+'</p><div class="choices" role="listbox"></div>';
  if(isPermission){var detail=permissionDetail(p);if(detail){var pre=document.createElement('pre');pre.className='permission-command';pre.textContent=detail;node.insertBefore(pre,node.querySelector('.choices'));}}
  var choices=node.querySelector('.choices');
  for(var option of(p.options||[]))(function(opt){
    var b=document.createElement('button');b.className='choice';
    b.innerHTML='<strong>'+esc(opt.label!=null?opt.label:opt.id)+'</strong>'+(opt.description||opt.desc?'<span>'+esc(opt.description!=null?opt.description:opt.desc)+'</span>':'');
    b.onclick=function(){disableChoices(node);node.classList.add('resolving');vscode.postMessage({type:'interrupt.resolve',taskId:event.taskId,response:{choiceId:String(opt.id!=null?opt.id:''),value:String(opt.value!=null?opt.value:opt.label!=null?opt.label:''),text:String(opt.label!=null?opt.label:'')}});};
    choices.appendChild(b);
  })(option);
  if(p.allowOther!==false){
    var row=document.createElement('div');row.className='other-row';
    var field=document.createElement('input');field.placeholder='Hướng khác…';
    var sb=document.createElement('button');sb.className='ghost-btn';sb.textContent='Gửi';
    var submit=function(){var v=field.value.trim();if(!v)return;disableChoices(node);node.classList.add('resolving');vscode.postMessage({type:'interrupt.resolve',taskId:event.taskId,response:{choiceId:'other',value:v,text:v}});};
    sb.onclick=submit;field.onkeydown=function(e){if(e.key==='Enter')submit();};row.append(field,sb);choices.appendChild(row);
  }
  waitEntry.interruptHostEl.appendChild(node);if(key)pendingInterruptNodes.set(key,node);scroll();
}

function diffStats(diff){
  var plus=0,minus=0;for(var line of String(diff||'').split('\n')){if(line.startsWith('+++')||line.startsWith('---'))continue;if(line.startsWith('+'))plus++;else if(line.startsWith('-'))minus++;}return{plus:plus,minus:minus};
}
function ensureChangeFile(entry,filePath,diff,changeKind){
  filePath=String(filePath||'').replace(/\\/g,'/');if(!filePath)return;
  entry.files.add(filePath);entry.changesEl.style.display='';var row=entry.changeFiles.get(filePath);
  if(!row){
    row=document.createElement('div');row.className='change-row';
    var status=document.createElement('span');status.className='change-status';status.textContent=changeKind==='created'?'A':'M';if(changeKind==='created')status.classList.add('added');
    var file=document.createElement('span');file.className='change-file';file.textContent=filePath;file.title=filePath;
    var stat=document.createElement('span');stat.className='change-stat';
    var actions=document.createElement('span');actions.className='change-actions';var open=document.createElement('button');open.textContent='Mở';var showDiff=document.createElement('button');showDiff.textContent='Diff';
    open.onclick=function(){vscode.postMessage({type:'openArtifact',path:filePath});};showDiff.onclick=function(){vscode.postMessage({type:'openDiff',path:filePath,diff:String(row._diff||'')});};
    actions.append(open,showDiff);row.append(status,file,stat,actions);entry.changesListEl.appendChild(row);row._stat=stat;row._status=status;entry.changeFiles.set(filePath,row);
  }
  if(changeKind==='created'){row._status.textContent='A';row._status.classList.add('added');}
  if(diff){row._diff=String(diff);var stats=diffStats(diff);row._stat.innerHTML=(stats.plus?'<span class="plus">+'+stats.plus+'</span> ':'')+(stats.minus?'<span class="minus">-'+stats.minus+'</span>':'');}
  entry.changesMetaEl.textContent=entry.changeFiles.size+' file';updateActivitySummary(entry,entry.currentLabel,entry.status);
}
function addArtifact(event){
  var p=event.payload||{};var filePath=String(p.path!=null?p.path:'');if(!filePath)return;
  var entry=getTaskGroup(String(event.taskId||activeTaskId||'main'));ensureChangeFile(entry,filePath,String(p.diff!=null?p.diff:''),event.type==='artifact.created'?'created':'modified');scroll();
}
function changeSetStatusLabel(status){
  status=String(status||'pending');if(status==='accepted')return 'Đã chấp nhận';if(status==='reverted')return 'Đã hoàn tác';if(status==='pending')return 'Có thể hoàn tác';return status;
}
function addChangeSet(event){
  var p=event.payload||{};var id=String(p.changeSetId!=null?p.changeSetId:p.operationId!=null?p.operationId:'');if(!id)return;
  var taskId=String(event.taskId||activeTaskId||'main');var entry=getTaskGroup(taskId);var files=Array.isArray(p.files)?p.files:[];for(var file of files)ensureChangeFile(entry,String(file||''),'');
  var status=String(p.status!=null?p.status:'pending');var bar=entry.changeSetEl;bar.style.display='flex';bar.dataset.changeSetId=id;bar.innerHTML='';
  var state=document.createElement('span');state.className='changeset-state';state.textContent=changeSetStatusLabel(status);
  var accept=document.createElement('button');accept.className='primary';accept.textContent='Giữ thay đổi';
  var revert=document.createElement('button');revert.textContent='Hoàn tác';
  if(status!=='pending'){accept.disabled=true;revert.disabled=true;}
  accept.onclick=function(){if(taskId)vscode.postMessage({type:'task.control',taskId:taskId,action:'accept_changeset',changeSetId:id});};
  revert.onclick=function(){if(taskId)vscode.postMessage({type:'task.control',taskId:taskId,action:'revert_changeset',changeSetId:id});};
  bar.append(state,accept,revert);entry.changesEl.style.display='';scroll();
}
function updateChangeSet(event){
  var p=event.payload||{};var id=String(p.changeSetId!=null?p.changeSetId:p.operationId!=null?p.operationId:'');
  var bars=[...document.querySelectorAll('.changeset-actions[data-change-set-id]')];var bar=bars.find(function(n){return n.dataset.changeSetId===id;});
  if(!bar){addChangeSet(event);return;}
  var state=bar.querySelector('.changeset-state');if(state)state.textContent=changeSetStatusLabel(p.status!=null?p.status:'updated');
  for(var b of bar.querySelectorAll('button'))b.disabled=true;
}

function renderEvent(event){
  if(!event||!remember(event))return;
  if(event.taskId)activeTaskId=String(event.taskId);
  if(event.type==='message.user'){addUserMessage(event.payload&&event.payload.content!=null?event.payload.content:'',event.payload&&event.payload.attachments?event.payload.attachments:[]);return;}
  if(event.type==='message.assistant'){
    var entry=getTaskGroup(String(event.taskId||activeTaskId||'main'));
    entry.markdownText=String(event.payload&&event.payload.content!=null?event.payload.content:'');
    scheduleMarkdown(entry);entry.bubbleEl.classList.remove('streaming');scroll();
    return;
  }
  if(event.type==='message.assistant.delta'){
    removeEmpty();
    var dEntry=getTaskGroup(String(event.taskId||activeTaskId||'main'));
    dEntry.markdownText+=String(event.payload&&event.payload.delta!=null?event.payload.delta:'');
    scheduleMarkdown(dEntry);dEntry.bubbleEl.classList.add('streaming');scroll();
    return;
  }
  if(event.type==='coding.state'){mergeCoding(event);return;}
  if(String(event.type).startsWith('activity.')){addActivity(event);return;}
  if(event.type==='interrupt.request'){addInterrupt(event);return;}
  if(event.type==='interrupt.resolved'){resolveInterruptNode(String(event.taskId!=null?event.taskId:''));return;}
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
    ensureEmpty();awaitingThreadHistory=false;pendingSwitchDirection=0;animateTimelineIn(direction);scroll(true);
    var queued=deferredEvents;deferredEvents=[];for(var qe of queued)renderEvent(qe);
  }
  if(direction)setTimeout(paint,95);else paint();
}

function renderAttachments(){
  attachmentBox.innerHTML='';attachmentBox.classList.toggle('visible',attachmentState.size>0);
  for(var item of attachmentState.values()){
    var chip=document.createElement('div');chip.className='attach-chip';
    if(item.preview){var img=document.createElement('img');img.src=item.preview;chip.appendChild(img);}
    var icon=document.createElement('span');icon.textContent=item.kind==='image'?'▧':'▤';
    var name=document.createElement('span');name.className='attach-name';name.textContent=item.name;name.title=(item.relativePath||item.name)+' · '+fmtBytes(item.size);
    var rm=document.createElement('button');rm.className='attach-remove';rm.textContent='×';
    (function(id,c){rm.onclick=function(){c.classList.add('removing');setTimeout(function(){attachmentState.delete(id);renderAttachments();vscode.postMessage({type:'attachment.remove',id:id});},100);};})(item.id,chip);
    chip.append(icon,name,rm);attachmentBox.appendChild(chip);
  }
  updateComposerState();
}
function contextKeys(){return [...contextPopover.querySelectorAll('input:checked')].map(function(n){return n.value;});}
function activeSession(){return sessions.find(function(s){return String(s.threadId||'')===activeThreadId;})||null;}
function isActiveTaskRunning(){var s=activeSession();return Boolean(s&&String(s.status||'')==='running');}
function sessionStatusFromActivity(status){
  var value=String(status||'').toLowerCase();
  if(value==='completed'||value==='done')return 'done';
  if(value==='failed'||value==='stopped')return 'failed';
  if(value==='paused'||value==='waiting_user'||value==='waiting_permission')return 'waiting';
  if(value==='running'||value==='queued')return 'running';
  return '';
}
function syncSessionStatusFromEvent(event,status){
  var mapped=sessionStatusFromActivity(status);
  if(!mapped)return;
  var threadId=String(event&&event.threadId||'');
  var taskId=String(event&&event.taskId||'');
  var session=threadId?sessions.find(function(s){return String(s.threadId||'')===threadId;}):null;
  if(!session&&taskId)session=sessions.find(function(s){return String(s.taskId||'')===taskId;});
  if(!session&&(!taskId||taskId===activeTaskId))session=activeSession();
  if(!session)return;
  session.status=mapped;
  if(taskId)session.taskId=taskId;
  updateComposerState();
}
function contextLabelPath(value){var p=String(value||'').replace(/\\/g,'/');return p.split('/').pop()||p;}
function renderContextSummary(){
  contextSummary.innerHTML='';var enabled=new Set(contextKeys());var visibleCount=0;var activeCount=0;
  function available(key,condition){if(enabled.has(key)&&condition)activeCount++;}
  function chip(key,label,cls,title){if(!enabled.has(key)||!label)return;var b=document.createElement('button');b.type='button';b.className='context-chip'+(cls?' '+cls:'');b.title=title||('Bỏ '+label);b.innerHTML='<span class="ctx-text">'+esc(label)+'</span><span>×</span>';b.onclick=function(){var box=contextPopover.querySelector('input[value="'+key+'"]');if(box)box.checked=false;renderContextSummary();};contextSummary.appendChild(b);visibleCount++;}
  /* Current file, Git và open editors là context nền: vẫn gửi cho agent nhưng không
     biến composer thành hàng pill. Chỉ surface context đặc biệt mà user cần thấy. */
  var c=composerContext.current||{};available('current',Boolean(c.available));
  var s=composerContext.selection||{};available('selection',Boolean(s.available&&!s.empty));if(s.available&&!s.empty)chip('selection','Vùng chọn · '+(s.lineCount||1)+' dòng','',s.path||'Vùng chọn');
  var p=composerContext.problems||{};var problems=Number(p.error||0)+Number(p.warning||0);available('problems',problems>0);if(problems)chip('problems',(p.error?String(p.error)+' lỗi':String(problems)+' vấn đề')+(p.warning?' · '+p.warning+' cảnh báo':''),'problem','Lỗi / cảnh báo hiện tại');
  var g=composerContext.git||{};available('git',Boolean(g.available&&g.changeCount));
  var t=composerContext.terminal||{};available('terminal',Boolean(t.active));if(t.active)chip('terminal','Terminal · '+clip(t.active,24),'',t.active);
  var o=composerContext.openEditors||{};available('openEditors',Boolean(o.count));
  contextSummary.classList.toggle('visible',visibleCount>0);contextButton.textContent='@';contextButton.classList.toggle('has-context',activeCount>0);contextButton.title=activeCount?('Context tự động · '+activeCount+' nguồn'):'Chọn context';
  var w=composerContext.workspace||{};var name=String(w.name||w.workspaceName||'').trim();var label=workspaceMode&&workspaceMode.querySelector('span');if(label)label.textContent=name?('Cục bộ · '+clip(name,22)):'Làm việc cục bộ';
}
function updateComposerState(){
  var running=isActiveTaskRunning();var ready=Boolean(input.value.trim())||attachmentState.size>0;
  sendButton.classList.toggle('stop',running);sendButton.classList.toggle('ready',running||ready);sendButton.textContent=running?'■':'↑';sendButton.title=running?'Dừng tác vụ':'Gửi';
}
function resizeInput(){input.style.height='auto';input.style.height=Math.min(140,Math.max(40,input.scrollHeight))+'px';updateComposerState();}
function send(){
  if(isActiveTaskRunning()){var s=activeSession();var taskId=String(activeTaskId||(s&&s.taskId)||'');requestTaskControl(taskId,'stop');return;}
  var content=input.value.trim();var ids=[...attachmentState.keys()];if(!content&&!ids.length)return;var taskMode=planNextTurn?'plan':'auto';pendingTaskMode=taskMode;planNextTurn=false;syncPlanUi();stickToBottom=true;input.value='';resizeInput();hidePopovers();vscode.postMessage({type:'sendMessage',content:content,taskMode:taskMode,autopilot:autopilotEnabled,model:selectedModel,attachmentIds:ids,contextKeys:contextKeys()});
}
function hidePopovers(){menuPopover.classList.remove('visible');contextPopover.classList.remove('visible');modelPopover.classList.remove('visible');syncPlanUi();syncModelUi();}
function showNotice(message){notice.textContent=String(message||'');notice.classList.toggle('visible',Boolean(message));if(message)setTimeout(function(){notice.classList.remove('visible');},7000);}

function renderDrawer(kind){
  drawer.classList.add('visible');menuPopover.classList.remove('visible');drawerBody.innerHTML='';
  if(kind==='history'){
    drawerTitle.textContent='Hội thoại gần đây';
    var byThread=new Map();
    for(var session of sessions)byThread.set(String(session.threadId||''),{threadId:String(session.threadId||''),title:session.title||NEW_SESSION_LABEL,status:session.status||'idle',updatedAt:Number(session.updatedAt||0)});
    for(var task of catalogTasks){var tid=String(task.thread_id||task.threadId||'');if(!tid)continue;var ex=byThread.get(tid)||{};byThread.set(tid,{threadId:tid,title:ex.title||task.clarified_goal||task.goal||PREVIOUS_SESSION_LABEL,status:String(task.status||ex.status||'idle'),updatedAt:Math.max(Number(ex.updatedAt||0),Number(task.updated_at||0)*(Number(task.updated_at||0)<10000000000?1000:1))});}
    var history=[...byThread.values()].sort(function(a,b){return b.updatedAt-a.updatedAt;});
    if(!history.length){drawerBody.innerHTML='<div class="empty"><div class="empty-inner"><p>No previous chats.</p></div></div>';return;}
    for(var item of history)(function(i){var b=document.createElement('button');b.className='drawer-card';b.innerHTML='<strong>'+esc(i.title||PREVIOUS_SESSION_LABEL)+'</strong><span>'+esc(i.status||'idle')+'</span>';b.onclick=function(){drawer.classList.remove('visible');selectSessionFromUi(i.threadId);};drawerBody.appendChild(b);})(item);
    return;
  }
  if(kind==='tasks'){
    drawerTitle.textContent='Tác vụ';if(!catalogTasks.length){drawerBody.innerHTML='<div class="empty"><div class="empty-inner"><p>Chưa có tác vụ.</p></div></div>';return;}
    for(var t of [...catalogTasks].reverse())(function(task){var b=document.createElement('button');b.className='drawer-card';b.innerHTML='<strong>'+esc(task.clarified_goal||task.goal||task.task_id||'Task')+'</strong><span>'+esc(String(task.status||'idle')+(task.coding_state&&task.coding_state.current_file?' · '+task.coding_state.current_file:''))+'</span>';b.onclick=function(){drawer.classList.remove('visible');selectSessionFromUi(String(task.thread_id||''));};drawerBody.appendChild(b);})(t);
    return;
  }
  drawerTitle.textContent='Kỹ năng';if(!catalogSkills.length){drawerBody.innerHTML='<div class="empty"><div class="empty-inner"><p>GitPilot chưa gửi danh mục kỹ năng.</p></div></div>';return;}
  for(var skill of catalogSkills){var b=document.createElement('div');b.className='drawer-card';b.innerHTML='<strong>'+esc(skill.label||skill.name||skill.id||'Skill')+'</strong><span>'+esc(skill.description||skill.summary||'')+'</span>';drawerBody.appendChild(b);}
}

document.getElementById('newChat').onclick=function(){vscode.postMessage({type:'newChat'});}
document.getElementById('menuButton').onclick=function(e){e.stopPropagation();contextPopover.classList.remove('visible');modelPopover.classList.remove('visible');menuPopover.classList.toggle('visible');};
document.getElementById('reconnect').onclick=function(){vscode.postMessage({type:'reconnect'});};
document.getElementById('attach').onclick=function(){vscode.postMessage({type:'attachment.pick'});};
contextButton.onclick=function(e){e.stopPropagation();menuPopover.classList.remove('visible');modelPopover.classList.remove('visible');contextPopover.classList.toggle('visible');vscode.postMessage({type:'context.refresh'});};
for(var ctxBox of contextPopover.querySelectorAll('input'))ctxBox.addEventListener('change',renderContextSummary);
planButton.onclick=function(e){e.stopPropagation();planNextTurn=!planNextTurn;syncPlanUi();input.focus();};
autopilotToggle.onclick=function(e){e.stopPropagation();autopilotEnabled=!autopilotEnabled;vscode.setState(Object.assign({},vscode.getState(),{model:selectedModel,autopilot:autopilotEnabled}));syncAutopilotUi();input.focus();};
if(workspaceMode)workspaceMode.onclick=function(){vscode.postMessage({type:'context.refresh'});input.focus();};
modelButton.onclick=function(e){e.stopPropagation();menuPopover.classList.remove('visible');contextPopover.classList.remove('visible');modelPopover.classList.toggle('visible');syncPlanUi();syncModelUi();requestAnimationFrame(placeOpenSelectPopovers);};
for(var modelOpt of document.querySelectorAll('[data-model-option]'))(function(btn){btn.onclick=function(e){e.stopPropagation();selectedModel=btn.dataset.modelOption||'auto';vscode.setState(Object.assign({},vscode.getState(),{model:selectedModel}));hidePopovers();input.focus();};})(modelOpt);
document.getElementById('send').onclick=send;
document.getElementById('drawerBack').onclick=function(){drawer.classList.remove('visible');};
for(var dmrow of document.querySelectorAll('[data-menu]'))(function(row){row.onclick=function(){var a=row.dataset.menu;hidePopovers();if(a==='new')vscode.postMessage({type:'newChat'});else if(a==='history'||a==='tasks'||a==='skills')renderDrawer(a);else if(a==='source')vscode.postMessage({type:'showSourceControl'});else if(a==='test')vscode.postMessage({type:'selfTest'});else if(a==='reconnect')vscode.postMessage({type:'reconnect'});else if(a==='settings')vscode.postMessage({type:'settings'});};})(dmrow);
input.addEventListener('input',resizeInput);
input.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});
document.addEventListener('click',function(){hidePopovers();});
menuPopover.onclick=function(e){e.stopPropagation();};
contextPopover.onclick=function(e){e.stopPropagation();};
sessionTabs.addEventListener('scroll',updateSessionIndicator,{passive:true});
timeline.addEventListener('scroll',function(){stickToBottom=isNearBottom();},{passive:true});
window.addEventListener('resize',function(){updateSessionIndicator();requestAnimationFrame(placeOpenSelectPopovers);});
syncPlanUi();
syncAutopilotUi();
syncModelUi();
modelPopover.onclick=function(e){e.stopPropagation();};

async function ingestFiles(files){for(var file of [...files].slice(0,8)){if(file.type.startsWith('image/')){(function(f){var reader=new FileReader();reader.onload=function(){vscode.postMessage({type:'attachment.image',name:f.name||'image.png',dataUrl:String(reader.result||'')});};reader.readAsDataURL(f);})(file);}}} 
input.addEventListener('paste',function(e){var files=[...(e.clipboardData&&e.clipboardData.files||[])];if(files.some(function(f){return f.type.startsWith('image/');})){e.preventDefault();ingestFiles(files);}});
var dragDepth=0;
document.addEventListener('dragenter',function(e){if(e.dataTransfer&&e.dataTransfer.types&&e.dataTransfer.types.includes('Files')){dragDepth++;document.getElementById('dropOverlay').classList.add('visible');}});
document.addEventListener('dragleave',function(){dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)document.getElementById('dropOverlay').classList.remove('visible');});
document.addEventListener('dragover',function(e){if(e.dataTransfer&&e.dataTransfer.types&&e.dataTransfer.types.includes('Files'))e.preventDefault();});
document.addEventListener('drop',function(e){dragDepth=0;document.getElementById('dropOverlay').classList.remove('visible');if(e.dataTransfer&&e.dataTransfer.files&&e.dataTransfer.files.length){e.preventDefault();ingestFiles(e.dataTransfer.files);}});

window.addEventListener('message',function(ev){
  var event=ev.data;
  if(event.type==='session.tabs'){sessions=Array.isArray(event.sessions)?event.sessions:[];activeThreadId=String(event.activeThreadId||'');renderSessions();refreshEmpty();return;}
  if(event.type==='chat.reset'){activeThreadId=String(event.threadId||activeThreadId);activeTaskId=String(event.preserveTask||'');drawer.classList.remove('visible');if(event.reason==='new'){var d=pendingSwitchDirection||1;stickToBottom=true;clearTimeline(false);ensureEmpty();animateTimelineIn(d);awaitingThreadHistory=false;pendingSwitchDirection=0;deferredEvents=[];}return;}
  if(event.type==='connection'){
    var connected=event.state==='connected';var connecting=event.state==='connecting';
    // Backend chưa chạy là trạng thái dormant bình thường. Chỉ hiện status khi user
    // vừa giao task và client thực sự đang kết nối; không treo banner 'offline'.
    connection.classList.toggle('visible',connecting);connection.classList.toggle('connecting',connecting);
    document.getElementById('connectionText').textContent=connecting?'Đang kết nối GitPilot…':'GitPilot sẵn sàng';
    if(connected)connection.classList.remove('visible');
    return;
  }
  if(event.type==='service.error'){return;}
  if(event.type==='attachment.add'){var att=Object.assign({},event.attachment||{},{preview:event.preview||''});if(att.id){attachmentState.set(att.id,att);renderAttachments();}return;}
  if(event.type==='attachments.clear'){attachmentState.clear();renderAttachments();return;}
  if(event.type==='composer.context'){composerContext=event.context&&typeof event.context==='object'?event.context:{};renderContextSummary();return;}
  if(event.type==='session.ready'){catalogTasks=Array.isArray(event.tasks)?event.tasks:catalogTasks;catalogSkills=Array.isArray(event.capabilities&&event.capabilities.brain&&event.capabilities.brain.skills?event.capabilities.brain.skills:null)?event.capabilities.brain.skills:catalogSkills;return;}
  if(event.type==='task.list'){catalogTasks=Array.isArray(event.tasks)?event.tasks:[];return;}
  if(event.type==='task.control.ack'){var ackStatus=String(event.status||'').toLowerCase();if(['rejected','failed','not_found','unavailable'].includes(ackStatus))showNotice(event.reason||('Không thể '+String(event.action||'control')+' task'));else applyLocalControlState(event.taskId,event.action);return;}
  if(event.type==='thread.history'){renderHistory(event);return;}
  if(event.type==='task.detail'){if(event.task){catalogTasks=[...new Map([...catalogTasks,event.task].map(function(t){return[String(t&&t.task_id?t.task_id:''),t];})).values()];}return;}
  if(event.type==='message.accepted'){activeTaskId=String(event.taskId||activeTaskId);if(activeTaskId){taskModes.set(activeTaskId,pendingTaskMode||'auto');var acceptedEntry=taskGroups.get(activeTaskId);if(acceptedEntry){acceptedEntry.taskMode=taskModes.get(activeTaskId)||'auto';acceptedEntry.planEl.style.display=acceptedEntry.taskMode==='plan'?'':'none';}}pendingTaskMode='auto';updateComposerState();return;}
  if(event.type==='client.error'||event.type==='error'){showNotice(event.message||event.code||'GitPilot runtime error');return;}
  if(awaitingThreadHistory){deferredEvents.push(event);return;}
  renderEvent(event);
});

ensureEmpty();
resizeInput();
renderContextSummary();
vscode.postMessage({type:'context.refresh'});
