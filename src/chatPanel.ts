import * as crypto from 'node:crypto';
import * as vscode from 'vscode';
import { captureIdeContext, currentWorkspaceRef } from './contextBridge';
import { WorkspaceDiffProvider } from './diffProvider';
import { openWorkspaceFile } from './editorBridge';
import { ErisClient } from './erisClient';
import { TerminalContextObserver } from './terminalObserver';

/**
 * Webview chính của Eris nằm trong View Container ở Primary Sidebar, cùng kiểu
 * bố trí với Cline. Activity Bar chỉ là lối vào; Webview vẫn chỉ render/gửi
 * intent, còn socket/file/terminal luôn nằm ở extension host.
 */
export class ErisChatPanel implements vscode.WebviewViewProvider, vscode.Disposable {
  static readonly viewType = 'eris.chat';

  private readonly disposables: vscode.Disposable[] = [];
  private readonly viewDisposables: vscode.Disposable[] = [];
  private view?: vscode.WebviewView;
  private threadId: string;
  private activeTaskId = '';

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly client: ErisClient,
    private readonly extensionContext: vscode.ExtensionContext,
    private readonly terminalObserver: TerminalContextObserver,
    private readonly diffProvider: WorkspaceDiffProvider,
  ) {
    const persisted = extensionContext.workspaceState.get<string>('eris.currentThreadId', '').trim();
    this.threadId = persisted || `thread_${crypto.randomUUID()}`;
    if (!persisted) {
      void extensionContext.workspaceState.update('eris.currentThreadId', this.threadId);
    }

    // Listener backend sống ở provider, không phụ thuộc iframe đang visible hay
    // đã bị VS Code deallocate. Khi view mở lại, history sẽ dựng UI từ state thật.
    this.disposables.push(
      client.onEvent((event) => void this.onAgentEvent(event)),
      client.onStateChanged((state) => void this.post({ type: 'connection', state })),
    );
  }

  resolveWebviewView(view: vscode.WebviewView): void {
    this.clearViewDisposables();
    this.view = view;
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.extensionUri],
    };
    view.webview.html = this.html(view.webview);
    view.description = 'LangGraph coding agent';

    this.viewDisposables.push(
      view.webview.onDidReceiveMessage((message) => void this.onWebviewMessage(message)),
      view.onDidDispose(() => {
        if (this.view === view) {
          this.view = undefined;
        }
        this.clearViewDisposables();
      }),
    );

    void this.post({ type: 'connection', state: this.client.connectionState });
    void this.client.connect().then(async () => {
      await this.client.createThread(this.threadId);
      await this.client.requestThreadHistory(this.threadId);
    }).catch((error) => {
      void this.post({ type: 'client.error', message: String(error) });
    });
  }

  /** Hiện Eris trong Primary Sidebar. Backend offline vẫn không ảnh hưởng việc reveal UI. */
  async show(preserveFocus = false): Promise<void> {
    if (this.view) {
      this.view.show(preserveFocus);
      return;
    }
    await vscode.commands.executeCommand(`${ErisChatPanel.viewType}.focus`);
    (this.view as vscode.WebviewView | undefined)?.show(preserveFocus);
  }

  newChat(): void {
    this.threadId = `thread_${crypto.randomUUID()}`;
    this.activeTaskId = '';
    void this.extensionContext.workspaceState.update('eris.currentThreadId', this.threadId);
    void this.post({ type: 'chat.reset' });
    void this.client.createThread(this.threadId).catch(() => undefined);
  }

  async selectTask(taskId: string, threadId: string): Promise<void> {
    const resolvedThread = String(threadId ?? '').trim();
    if (!resolvedThread) {
      return;
    }
    this.threadId = resolvedThread;
    this.activeTaskId = String(taskId ?? '').trim();
    void this.extensionContext.workspaceState.update('eris.currentThreadId', this.threadId);
    await this.show(false);
    await this.post({ type: 'chat.reset', preserveTask: this.activeTaskId });
    await this.client.requestThreadHistory(this.threadId).catch((error) => {
      void this.post({ type: 'client.error', message: String(error) });
    });
  }

  private async ideContext(): Promise<Record<string, unknown>> {
    return captureIdeContext(this.terminalObserver);
  }

  private async onWebviewMessage(message: any): Promise<void> {
    const type = String(message?.type ?? '');
    try {
      if (type === 'sendMessage') {
        const content = String(message.content ?? '').trim();
        if (!content) {
          return;
        }
        if (!vscode.workspace.isTrusted) {
          throw new Error('Workspace chưa được Trust trong VS Code; Eris sẽ không đọc/chạy code ở đây.');
        }
        await this.client.sendUserMessage(content, {
          threadId: this.threadId,
          taskMode: message.taskMode === 'inspect' ? 'inspect' : 'execute',
          workspaceRef: currentWorkspaceRef(),
          context: await this.ideContext(),
        });
        return;
      }
      if (type === 'interrupt.resolve') {
        const rawResponse = message.response && typeof message.response === 'object' ? message.response : {};
        await this.client.resolveInterrupt(String(message.taskId ?? this.activeTaskId), {
          ...rawResponse,
          // User có thể đã sửa file trong lúc graph pause. Resume phải nhận context
          // mới, không bê snapshot cũ đi tiếp rồi sửa nhầm một thế giới đã biến mất.
          ideContext: await this.ideContext(),
        });
        return;
      }
      if (type === 'task.control') {
        await this.client.controlTask(
          String(message.taskId ?? this.activeTaskId),
          String(message.action ?? ''),
          String(message.text ?? ''),
          String(message.checkpointId ?? ''),
          await this.ideContext(),
          String(message.changeSetId ?? ''),
        );
        return;
      }
      if (type === 'openArtifact') {
        await openWorkspaceFile(String(message.path ?? ''), Number(message.line ?? 1), Number(message.column ?? 1));
        return;
      }
      if (type === 'openDiff') {
        await this.diffProvider.openDiff(String(message.path ?? ''), String(message.diff ?? ''));
        return;
      }
      if (type === 'showSourceControl') {
        await vscode.commands.executeCommand('workbench.view.scm');
        return;
      }
      if (type === 'newChat') {
        this.newChat();
      }
    } catch (error) {
      await this.post({ type: 'client.error', message: String(error) });
    }
  }

  private async onAgentEvent(event: any): Promise<void> {
    const type = String(event?.type ?? '');
    if (event.taskId) {
      this.activeTaskId = String(event.taskId);
    }
    if (type === 'session.ready') {
      await this.post({ type: 'connection', state: 'connected' });
      await this.client.createThread(this.threadId);
      if (this.view) {
        await this.client.requestThreadHistory(this.threadId);
      }
      return;
    }
    if (type === 'thread.history') {
      if (String(event.threadId ?? '') !== this.threadId) {
        return;
      }
      const tasks = Array.isArray(event.tasks) ? event.tasks : [];
      const active = [...tasks].reverse().find((task: any) =>
        ['queued', 'running', 'paused', 'waiting_user', 'waiting_permission'].includes(String(task?.status ?? '')),
      ) ?? tasks.at(-1);
      if (active?.task_id) {
        this.activeTaskId = String(active.task_id);
      }
      await this.post(event);
      return;
    }
    // Hai event này được xử lý ở extension host toàn cục, kể cả khi Eris Sidebar
    // chưa từng mở. Webview không được tạo một response thứ hai.
    if (type === 'ide.request' || type === 'editor.command') {
      return;
    }
    await this.post(event);
  }

  private async post(message: unknown): Promise<boolean> {
    if (!this.view) {
      return false;
    }
    try {
      return await this.view.webview.postMessage(message);
    } catch {
      return false;
    }
  }

  private clearViewDisposables(): void {
    while (this.viewDisposables.length) {
      this.viewDisposables.pop()?.dispose();
    }
  }

  private html(webview: vscode.Webview): string {
    // extensionUri cố ý được giữ trong constructor để sau này asset webview có thể
    // resolve bằng asWebviewUri mà không đổi public API của panel.
    void this.extensionUri;
    const nonce = crypto.randomBytes(16).toString('base64');
    const csp = [
      `default-src 'none'`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `script-src 'nonce-${nonce}'`,
      `img-src ${webview.cspSource} data:`,
    ].join('; ');

    return /* html */ `<!doctype html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="${csp}" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Eris</title>
  <style>
    :root { color-scheme: light dark; }
    * { box-sizing:border-box; }
    body { margin:0; color:var(--vscode-foreground); background:var(--vscode-editor-background); font:13px/1.5 var(--vscode-font-family); }
    .shell { height:100vh; display:grid; grid-template-rows:46px auto 1fr auto; }
    .top { display:flex; align-items:center; gap:9px; padding:0 16px; border-bottom:1px solid var(--vscode-panel-border); }
    .brand { font-weight:750; letter-spacing:.08em; }
    .dot { width:7px; height:7px; border-radius:50%; background:var(--vscode-descriptionForeground); }
    .dot.connected { background:var(--vscode-testing-iconPassed); box-shadow:0 0 9px color-mix(in srgb,var(--vscode-testing-iconPassed) 60%,transparent); }
    .meta { color:var(--vscode-descriptionForeground); font-size:11px; text-transform:uppercase; letter-spacing:.06em; }
    .spacer { flex:1; }
    button, select, input, textarea { font:inherit; }
    button { color:inherit; background:transparent; border:1px solid var(--vscode-button-border,var(--vscode-panel-border)); border-radius:7px; padding:5px 9px; cursor:pointer; }
    button:hover { background:var(--vscode-toolbar-hoverBackground); }
    button:disabled { opacity:.45; cursor:default; }
    .taskbar { display:none; max-width:960px; width:calc(100% - 32px); margin:12px auto 0; padding:10px 12px; border:1px solid var(--vscode-panel-border); border-radius:10px; background:var(--vscode-sideBar-background); }
    .taskbar.visible { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:5px 12px; }
    .task-title { font-weight:650; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .task-detail { color:var(--vscode-descriptionForeground); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .task-tests { align-self:center; grid-row:1 / span 2; grid-column:2; font-size:12px; color:var(--vscode-descriptionForeground); }
    .timeline { min-height:0; overflow:auto; padding:22px clamp(16px,5vw,68px) 34px; }
    .message, .activity-group, .artifact, .interrupt, .error { max-width:920px; margin-left:auto; margin-right:auto; }
    .message { margin-bottom:18px; white-space:pre-wrap; word-break:break-word; }
    .message.user { padding:11px 13px; border-radius:10px; background:var(--vscode-input-background); border:1px solid var(--vscode-input-border,transparent); }
    .message.assistant { font-size:14px; }
    .activity-group { margin-bottom:12px; }
    .activity { display:flex; gap:9px; padding:2px 0; color:var(--vscode-descriptionForeground); font-size:12px; }
    .activity .mark { width:14px; text-align:center; flex:none; }
    .artifact, .interrupt { margin-top:12px; margin-bottom:18px; border:1px solid var(--vscode-panel-border); border-radius:10px; padding:12px; background:var(--vscode-sideBar-background); }
    .artifact-head { display:flex; align-items:center; gap:8px; }
    .artifact code { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .artifact-actions { display:flex; gap:6px; margin-top:10px; }
    .interrupt h3 { margin:0 0 5px; font-size:13px; }
    .interrupt p { margin:0 0 10px; color:var(--vscode-descriptionForeground); }
    .choices { display:grid; gap:7px; }
    .choice { text-align:left; padding:9px 10px; border-color:var(--vscode-panel-border); }
    .choice:focus { outline:1px solid var(--vscode-focusBorder); outline-offset:1px; }
    .choice strong, .choice span { display:block; }
    .choice span { margin-top:2px; color:var(--vscode-descriptionForeground); font-size:12px; }
    .other-row { display:flex; gap:7px; margin-top:3px; }
    .other-row input { min-width:0; flex:1; color:var(--vscode-input-foreground); background:var(--vscode-input-background); border:1px solid var(--vscode-input-border,var(--vscode-panel-border)); border-radius:7px; padding:7px 9px; outline:0; }
    .composer-wrap { border-top:1px solid var(--vscode-panel-border); padding:12px clamp(16px,5vw,68px) 16px; background:var(--vscode-editor-background); }
    .composer { max-width:920px; margin:auto; border:1px solid var(--vscode-input-border,var(--vscode-panel-border)); border-radius:11px; background:var(--vscode-input-background); overflow:hidden; }
    textarea { width:100%; min-height:72px; max-height:220px; resize:vertical; padding:11px 12px 4px; color:var(--vscode-input-foreground); background:transparent; border:0; outline:0; }
    .composer-bar { display:flex; align-items:center; gap:6px; padding:6px 8px 8px; }
    select { color:var(--vscode-dropdown-foreground); background:var(--vscode-dropdown-background); border:1px solid var(--vscode-dropdown-border,var(--vscode-panel-border)); border-radius:6px; padding:4px 6px; }
    .send { margin-left:auto; color:var(--vscode-button-foreground); background:var(--vscode-button-background); border-color:transparent; }
    .send:hover { background:var(--vscode-button-hoverBackground); }
    .error { margin-bottom:12px; color:var(--vscode-errorForeground); }
    code { font-family:var(--vscode-editor-font-family); }
    /* Primary Sidebar thường hẹp 280-430px. UI co lại thay vì giả vờ đang ở editor rộng 900px. */
    @media (max-width: 520px) {
      .shell { grid-template-rows:42px auto 1fr auto; }
      .top { padding:0 10px; gap:6px; }
      .top button { padding:4px 7px; font-size:11px; }
      .taskbar { width:calc(100% - 16px); margin-top:8px; padding:9px 10px; }
      .taskbar.visible { grid-template-columns:1fr; gap:3px; }
      .task-tests { grid-row:auto; grid-column:auto; }
      .timeline { padding:14px 10px 22px; }
      .message, .activity-group, .artifact, .interrupt, .error { max-width:none; }
      .artifact-actions, .composer-bar { flex-wrap:wrap; }
      .artifact-actions button { flex:1 1 auto; }
      .composer-wrap { padding:9px 8px 10px; }
      .composer { max-width:none; border-radius:9px; }
      textarea { min-height:88px; max-height:180px; padding:10px 10px 4px; }
      .composer-bar { gap:5px; padding:5px 6px 7px; }
      .composer-bar select { flex:1 1 105px; min-width:0; }
      .composer-bar .spacer { display:none; }
      .send { margin-left:auto; }
      .other-row { flex-direction:column; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="top"><span id="statusDot" class="dot"></span><span class="brand">ERIS</span><span id="statusText" class="meta">disconnected</span><span class="spacer"></span><button id="source">Source</button><button id="newChat">New chat</button></header>
    <section id="taskbar" class="taskbar"><div id="taskTitle" class="task-title"></div><div id="taskDetail" class="task-detail"></div><div id="taskTests" class="task-tests"></div></section>
    <main id="timeline" class="timeline"></main>
    <footer class="composer-wrap">
      <div class="composer">
        <textarea id="input" placeholder="Giao task, hỏi về code, hoặc yêu cầu Eris kiểm tra workspace…"></textarea>
        <div class="composer-bar"><select id="mode"><option value="execute">Execute</option><option value="inspect">Inspect only</option></select><button id="pause">Pause</button><button id="resume">Resume</button><button id="rollback">Rollback</button><button id="stop">Stop</button><span class="spacer"></span><button id="send" class="send">Send</button></div>
      </div>
    </footer>
  </div>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const timeline = document.getElementById('timeline');
  const input = document.getElementById('input');
  const seenEvents = new Set();
  const activityNodes = new Map();
  const pendingInterrupts = new Set();
  let activeTaskId = '';
  let streamNode = null;
  let codingState = {};

  function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function scroll() { requestAnimationFrame(() => { timeline.scrollTop = timeline.scrollHeight; }); }
  function eventKey(event) { const id=String(event?.eventId ?? ''); return id ? (id+':'+String(event?.type??'')) : [event?.type,event?.taskId,event?.seq,event?.timestamp].join(':'); }
  function remember(event) { const key=eventKey(event); if (!key) return true; if (seenEvents.has(key)) return false; seenEvents.add(key); return true; }
  function resetTimeline() { timeline.innerHTML=''; streamNode=null; activityNodes.clear(); pendingInterrupts.clear(); seenEvents.clear(); codingState={}; updateTaskbar(); }
  function addMessage(role, content) {
    const node=document.createElement('section'); node.className='message '+role;
    node.innerHTML='<div class="meta">'+(role==='user'?'You':'Eris')+'</div><div>'+esc(content)+'</div>';
    timeline.appendChild(node); scroll(); return node;
  }
  function addActivity(event) {
    const payload=event?.payload ?? event ?? {}; const status=String(payload?.status ?? 'running');
    const semantic=String(payload?.data?.tool ?? payload?.kind ?? payload?.label ?? event?.type ?? 'activity');
    const key=String(event?.taskId ?? activeTaskId ?? '')+':'+semantic;
    let node=activityNodes.get(key);
    if (!node) { node=document.createElement('div'); node.className='activity'; timeline.appendChild(node); activityNodes.set(key,node); }
    const mark=status==='completed'?'✓':status==='failed'?'×':status==='paused'?'Ⅱ':status==='stopped'?'■':'·';
    node.innerHTML='<span class="mark">'+mark+'</span><span><strong>'+esc(payload?.label ?? 'Working')+'</strong>'+(payload?.detail?' · '+esc(payload.detail):'')+'</span>';
    scroll();
  }
  function mergeCoding(patch) {
    if (!patch || typeof patch!=='object') return;
    codingState={...codingState,...patch,test_state:{...(codingState.test_state??{}),...(patch.test_state??{})}};
    updateTaskbar();
  }
  function updateTaskbar(task) {
    const bar=document.getElementById('taskbar');
    if (task) {
      activeTaskId=String(task.task_id ?? activeTaskId ?? '');
      codingState={...(task.coding_state??codingState)};
      codingState.status=String(task.status ?? codingState.status ?? '');
      if (!codingState.objective) codingState.objective=String(task.clarified_goal ?? task.goal ?? '');
    }
    const title=String(codingState.objective ?? '');
    const action=String(codingState.current_action ?? codingState.phase ?? '');
    const file=String(codingState.current_file ?? '');
    const test=codingState.test_state ?? {};
    if (!title && !activeTaskId) { bar.classList.remove('visible'); return; }
    bar.classList.add('visible');
    document.getElementById('taskTitle').textContent=title || activeTaskId;
    document.getElementById('taskDetail').textContent=[action,file].filter(Boolean).join(' · ');
    document.getElementById('taskTests').textContent=test.status ? ('Tests: '+String(test.status)+(Number(test.passed||0)||Number(test.failed||0)?' · '+Number(test.passed||0)+'✓ '+Number(test.failed||0)+'×':'')) : String(codingState.status ?? '');
  }
  function disableChoices(node) { for (const control of node.querySelectorAll('button,input')) control.disabled=true; }
  function addInterrupt(event) {
    const interruptKey=String(event.taskId ?? activeTaskId ?? ''); if (interruptKey && pendingInterrupts.has(interruptKey)) return; if (interruptKey) pendingInterrupts.add(interruptKey);
    const payload=event.payload ?? {}; const node=document.createElement('section'); node.className='interrupt';
    node.innerHTML='<h3>'+esc(payload.question || 'Eris cần anh chọn')+'</h3><p>Task đã checkpoint. Chọn xong LangGraph tiếp tục đúng thread.</p><div class="choices" role="listbox" aria-label="Lựa chọn cho Eris"></div>';
    const choices=node.querySelector('.choices');
    for (const option of (payload.options ?? [])) {
      const button=document.createElement('button'); button.className='choice'; button.setAttribute('role','option'); button.tabIndex=0;
      button.innerHTML='<strong>'+esc(option.label ?? option.id)+'</strong>'+(option.description||option.desc?'<span>'+esc(option.description ?? option.desc)+'</span>':'');
      const choose=()=>{ disableChoices(node); if(interruptKey) pendingInterrupts.delete(interruptKey); vscode.postMessage({type:'interrupt.resolve',taskId:event.taskId,response:{choiceId:String(option.id??''),value:String(option.value??option.label??''),text:String(option.label??'')}}); };
      button.onclick=choose; button.onkeydown=(e)=>{ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); choose(); } }; choices.appendChild(button);
    }
    if (payload.allowOther !== false) {
      const row=document.createElement('div'); row.className='other-row'; const field=document.createElement('input'); field.placeholder='Nhập hướng khác…'; const button=document.createElement('button'); button.textContent='Gửi';
      const submit=()=>{ const value=field.value.trim(); if(!value)return; disableChoices(node); if(interruptKey)pendingInterrupts.delete(interruptKey); vscode.postMessage({type:'interrupt.resolve',taskId:event.taskId,response:{choiceId:'other',value,text:value}}); };
      button.onclick=submit; field.onkeydown=(e)=>{if(e.key==='Enter')submit();}; row.append(field,button); choices.appendChild(row);
    }
    timeline.appendChild(node); scroll();
  }
  function addArtifact(event) {
    const payload=event.payload ?? {}; const filePath=String(payload.path ?? ''); if(!filePath)return;
    const node=document.createElement('section'); node.className='artifact';
    node.innerHTML='<div class="artifact-head"><span class="meta">Modified</span><code>'+esc(filePath)+'</code></div><div class="artifact-actions"><button data-action="open">Open</button><button data-action="diff">Diff</button><button data-action="rollback">Rollback checkpoint</button></div>';
    node.querySelector('[data-action="open"]').onclick=()=>vscode.postMessage({type:'openArtifact',path:filePath});
    node.querySelector('[data-action="diff"]').onclick=()=>vscode.postMessage({type:'openDiff',path:filePath,diff:String(payload.diff??'')});
    node.querySelector('[data-action="rollback"]').onclick=()=>activeTaskId&&vscode.postMessage({type:'task.control',taskId:activeTaskId,action:'rollback'});
    timeline.appendChild(node); scroll();
  }
  function addChangeSet(event) {
    const payload=event.payload ?? {}; const id=String(payload.changeSetId ?? payload.operationId ?? ''); if(!id)return;
    const files=Array.isArray(payload.files)?payload.files:[]; const status=String(payload.status ?? 'pending');
    const node=document.createElement('section'); node.className='artifact'; node.dataset.changeSetId=id;
    node.innerHTML='<div class="artifact-head"><span class="meta">ChangeSet · '+esc(status)+'</span><code>'+esc(id)+'</code></div>'
      +'<p>'+esc(files.slice(0,5).join(' · '))+(files.length>5?' · +'+(files.length-5):'')+'</p>'
      +'<div class="artifact-actions"><button data-action="accept">Accept</button><button data-action="revert">Revert ChangeSet</button></div>';
    const accept=node.querySelector('[data-action="accept"]'); const revert=node.querySelector('[data-action="revert"]');
    if(status!=='pending'){accept.disabled=true;revert.disabled=true;}
    accept.onclick=()=>activeTaskId&&vscode.postMessage({type:'task.control',taskId:activeTaskId,action:'accept_changeset',changeSetId:id});
    revert.onclick=()=>activeTaskId&&vscode.postMessage({type:'task.control',taskId:activeTaskId,action:'revert_changeset',changeSetId:id});
    timeline.appendChild(node); scroll();
  }
  function updateChangeSet(event) {
    const payload=event.payload ?? {}; const id=String(payload.changeSetId ?? payload.operationId ?? ''); if(!id)return;
    const node=[...document.querySelectorAll('[data-change-set-id]')].reverse().find(n=>n.dataset.changeSetId===id);
    if(!node){addChangeSet(event);return;}
    const meta=node.querySelector('.meta'); if(meta)meta.textContent='ChangeSet · '+String(payload.status ?? 'updated');
    for(const button of node.querySelectorAll('button'))button.disabled=true;
  }
  function renderEvent(event) {
    if (!event || !remember(event)) return;
    if (event.taskId) activeTaskId=String(event.taskId);
    if (event.type==='message.user') { addMessage('user',event.payload?.content??''); return; }
    if (event.type==='message.assistant') { addMessage('assistant',event.payload?.content??''); streamNode=null; return; }
    if (event.type==='message.assistant.delta') { if(!streamNode)streamNode=addMessage('assistant',''); streamNode.lastElementChild.textContent+=String(event.payload?.delta??''); scroll(); return; }
    if (event.type==='coding.state') { mergeCoding(event.payload??{}); return; }
    if (String(event.type).startsWith('activity.')) { addActivity(event); return; }
    if (event.type==='interrupt.request') { addInterrupt(event); return; }
    if (event.type==='interrupt.resolved') { pendingInterrupts.delete(String(event.taskId??'')); return; }
    if (event.type==='artifact.modified'||event.type==='artifact.created') { addArtifact(event); return; }
    if (event.type==='changeset.created') { addChangeSet(event); return; }
    if (event.type==='changeset.updated') { updateChangeSet(event); return; }
    if (event.type==='artifact.diff') { addActivity({taskId:event.taskId,type:'activity.diff',payload:{label:event.payload?.summary??'Đã đọc Git diff',status:'completed'}}); return; }
    if (event.type==='editor.result') { addActivity({taskId:event.taskId,type:'activity.editor',payload:{label:event.payload?.message??event.payload?.command??'VS Code command',status:event.payload?.success?'completed':'failed'}}); }
  }
  function send() { const content=input.value.trim(); if(!content)return; input.value=''; streamNode=null; vscode.postMessage({type:'sendMessage',content,taskMode:document.getElementById('mode').value}); }
  function control(action) { if(activeTaskId)vscode.postMessage({type:'task.control',taskId:activeTaskId,action}); }
  document.getElementById('send').onclick=send;
  document.getElementById('newChat').onclick=()=>vscode.postMessage({type:'newChat'});
  document.getElementById('source').onclick=()=>vscode.postMessage({type:'showSourceControl'});
  document.getElementById('pause').onclick=()=>control('pause');
  document.getElementById('resume').onclick=()=>control('resume');
  document.getElementById('rollback').onclick=()=>control('rollback');
  document.getElementById('stop').onclick=()=>control('stop');
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send();}});

  window.addEventListener('message',({data:event})=>{
    if(event.type==='chat.reset'){resetTimeline();activeTaskId=String(event.preserveTask??'');return;}
    if(event.type==='connection'){document.getElementById('statusText').textContent=event.state;document.getElementById('statusDot').classList.toggle('connected',event.state==='connected');return;}
    if(event.type==='thread.history'){
      resetTimeline();
      const tasks=Array.isArray(event.tasks)?event.tasks:[]; const task=[...tasks].reverse().find(t=>['queued','running','paused','waiting_user','waiting_permission'].includes(String(t?.status??'')))??tasks.at(-1);
      if(task)updateTaskbar(task);
      for(const item of (event.events??[]))renderEvent(item);
      if(task&&(task.status==='waiting_user'||task.status==='waiting_permission')&&task.pending_interrupt){addInterrupt({taskId:task.task_id,payload:task.pending_interrupt,eventId:'restore:'+String(task.task_id)});}
      return;
    }
    if(event.type==='task.detail'){updateTaskbar(event.task??{});return;}
    if(event.type==='message.accepted'){activeTaskId=String(event.taskId??activeTaskId);updateTaskbar();return;}
    if(event.type==='client.error'||event.type==='error'){const n=document.createElement('div');n.className='error';n.textContent=event.message??event.code??'Eris service error';timeline.appendChild(n);scroll();return;}
    renderEvent(event);
  });
</script>
</body>
</html>`;
  }


  dispose(): void {
    this.clearViewDisposables();
    while (this.disposables.length) {
      this.disposables.pop()?.dispose();
    }
    this.view = undefined;
  }
}
