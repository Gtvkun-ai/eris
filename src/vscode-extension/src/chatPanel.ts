import * as crypto from 'node:crypto';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { captureIdeContext, currentWorkspaceRef } from './contextBridge';
import { ErisClient } from './erisClient';

/** Chat Panel chỉ render. Mọi quyền file/socket vẫn nằm ở extension host. */
export class ErisChatPanel implements vscode.Disposable {
  private static current?: ErisChatPanel;
  private readonly disposables: vscode.Disposable[] = [];
  private threadId: string;
  private activeTaskId = '';

  static show(extensionUri: vscode.Uri, client: ErisClient, context: vscode.ExtensionContext): ErisChatPanel {
    if (this.current) {
      this.current.panel.reveal(vscode.ViewColumn.Beside, true);
      return this.current;
    }
    const panel = vscode.window.createWebviewPanel(
      'eris.chat',
      'Eris',
      { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
      { enableScripts: true, retainContextWhenHidden: true },
    );
    this.current = new ErisChatPanel(panel, extensionUri, client, context);
    return this.current;
  }

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private readonly extensionUri: vscode.Uri,
    private readonly client: ErisClient,
    private readonly extensionContext: vscode.ExtensionContext,
  ) {
    const persisted = extensionContext.workspaceState.get<string>('eris.currentThreadId', '').trim();
    this.threadId = persisted || `thread_${crypto.randomUUID()}`;
    if (!persisted) {
      void extensionContext.workspaceState.update('eris.currentThreadId', this.threadId);
    }
    panel.webview.html = this.html(panel.webview);
    this.disposables.push(
      panel.onDidDispose(() => this.dispose()),
      panel.webview.onDidReceiveMessage((message) => void this.onWebviewMessage(message)),
      client.onEvent((event) => void this.onAgentEvent(event)),
      client.onStateChanged((state) => {
        void panel.webview.postMessage({ type: 'connection', state });
      }),
    );
    void this.client.connect().catch((error) => {
      void this.panel.webview.postMessage({ type: 'client.error', message: String(error) });
    });
  }

  newChat(): void {
    this.threadId = `thread_${crypto.randomUUID()}`;
    void this.extensionContext.workspaceState.update('eris.currentThreadId', this.threadId);
    this.activeTaskId = '';
    void this.panel.webview.postMessage({ type: 'chat.reset' });
  }

  private async onWebviewMessage(message: any): Promise<void> {
    const type = String(message?.type ?? '');
    if (type === 'sendMessage') {
      const content = String(message.content ?? '').trim();
      if (!content) {
        return;
      }
      try {
        if (!vscode.workspace.isTrusted) {
          throw new Error('Workspace chưa được Trust trong VS Code; Eris sẽ không đọc/chạy code ở đây.');
        }
        const context = await captureIdeContext();
        await this.client.sendUserMessage(content, {
          threadId: this.threadId,
          taskMode: message.taskMode === 'inspect' ? 'inspect' : 'execute',
          workspaceRef: currentWorkspaceRef(),
          context,
        });
      } catch (error) {
        await this.panel.webview.postMessage({ type: 'client.error', message: String(error) });
      }
      return;
    }
    if (type === 'interrupt.resolve') {
      const context = await captureIdeContext();
      const rawResponse = message.response && typeof message.response === 'object' ? message.response : {};
      // Choice Card chỉ gửi ý định của user. Extension host bổ sung context IDE
      // mới nhất để LangGraph resume trong đúng trạng thái editor hiện tại.
      await this.client.resolveInterrupt(String(message.taskId ?? this.activeTaskId), {
        ...rawResponse,
        ideContext: context,
      });
      return;
    }
    if (type === 'task.control') {
      const context = await captureIdeContext();
      await this.client.controlTask(
        String(message.taskId ?? this.activeTaskId),
        String(message.action ?? ''),
        String(message.text ?? ''),
        String(message.checkpointId ?? ''),
        context,
      );
      return;
    }
    if (type === 'openArtifact') {
      await openWorkspaceFile(String(message.path ?? ''), Number(message.line ?? 1));
      return;
    }
    if (type === 'newChat') {
      this.newChat();
    }
  }

  private async onAgentEvent(event: any): Promise<void> {
    const type = String(event?.type ?? '');
    if (event.taskId) {
      this.activeTaskId = String(event.taskId);
    }
    if (type === 'session.ready') {
      const tasks = Array.isArray(event.tasks) ? event.tasks : [];
      const restored = tasks.find((task: any) => String(task?.thread_id ?? '') === this.threadId);
      if (restored) {
        this.activeTaskId = String(restored.task_id ?? '');
        await this.panel.webview.postMessage({ type: 'session.restore', task: restored });
      }
      await this.panel.webview.postMessage({ type: 'connection', state: 'connected' });
      return;
    }
    if (type === 'editor.command') {
      await executeEditorCommand(event.payload ?? {});
      return;
    }
    await this.panel.webview.postMessage(event);
  }

  private html(webview: vscode.Webview): string {
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
    * { box-sizing: border-box; }
    body { margin: 0; color: var(--vscode-foreground); background: var(--vscode-editor-background); font: 13px/1.55 var(--vscode-font-family); }
    .shell { height: 100vh; display: grid; grid-template-rows: 46px 1fr auto; }
    .top { display:flex; align-items:center; gap:10px; padding:0 16px; border-bottom:1px solid var(--vscode-panel-border); }
    .brand { font-weight:700; letter-spacing:.04em; }
    .dot { width:7px; height:7px; border-radius:50%; background:var(--vscode-descriptionForeground); }
    .dot.connected { background:var(--vscode-testing-iconPassed); box-shadow:0 0 10px color-mix(in srgb, var(--vscode-testing-iconPassed) 60%, transparent); }
    .spacer { flex:1; }
    button { color:inherit; background:transparent; border:1px solid var(--vscode-button-border, var(--vscode-panel-border)); border-radius:7px; padding:5px 9px; cursor:pointer; }
    button:hover { background:var(--vscode-toolbar-hoverBackground); }
    .timeline { min-height:0; overflow:auto; padding:22px clamp(16px, 5vw, 68px) 34px; }
    .message { max-width:920px; margin:0 auto 18px; white-space:pre-wrap; word-break:break-word; }
    .message.user { padding:11px 13px; border-radius:10px; background:var(--vscode-input-background); border:1px solid var(--vscode-input-border, transparent); }
    .message.assistant { font-size:14px; }
    .meta { color:var(--vscode-descriptionForeground); font-size:11px; margin-bottom:5px; text-transform:uppercase; letter-spacing:.07em; }
    .activity { max-width:920px; margin:0 auto 7px; display:flex; gap:9px; color:var(--vscode-descriptionForeground); font-size:12px; }
    .activity .mark { width:14px; text-align:center; }
    .artifact, .interrupt { max-width:920px; margin:12px auto 18px; border:1px solid var(--vscode-panel-border); border-radius:10px; padding:12px; background:var(--vscode-sideBar-background); }
    .artifact { cursor:pointer; }
    .interrupt h3 { margin:0 0 5px; font-size:13px; }
    .interrupt p { margin:0 0 10px; color:var(--vscode-descriptionForeground); }
    .choices { display:grid; gap:7px; }
    .choice { text-align:left; padding:9px 10px; border-color:var(--vscode-panel-border); }
    .other-row { display:flex; gap:7px; margin-top:3px; }
    .other-row input { min-width:0; flex:1; color:var(--vscode-input-foreground); background:var(--vscode-input-background); border:1px solid var(--vscode-input-border, var(--vscode-panel-border)); border-radius:7px; padding:7px 9px; outline:0; }
    .choice strong, .choice span { display:block; }
    .choice span { margin-top:2px; color:var(--vscode-descriptionForeground); font-size:12px; }
    .composer-wrap { border-top:1px solid var(--vscode-panel-border); padding:12px clamp(16px, 5vw, 68px) 16px; background:var(--vscode-editor-background); }
    .composer { max-width:920px; margin:auto; border:1px solid var(--vscode-input-border, var(--vscode-panel-border)); border-radius:10px; overflow:hidden; background:var(--vscode-input-background); }
    textarea { width:100%; min-height:76px; max-height:220px; resize:vertical; border:0; outline:0; padding:12px; color:var(--vscode-input-foreground); background:transparent; font:inherit; }
    .composer-bar { display:flex; align-items:center; gap:8px; padding:7px 8px; border-top:1px solid color-mix(in srgb, var(--vscode-panel-border) 75%, transparent); }
    select { color:var(--vscode-dropdown-foreground); background:var(--vscode-dropdown-background); border:1px solid var(--vscode-dropdown-border); padding:4px 7px; border-radius:6px; }
    .send { margin-left:auto; color:var(--vscode-button-foreground); background:var(--vscode-button-background); border-color:transparent; }
    .send:hover { background:var(--vscode-button-hoverBackground); }
    .error { max-width:920px; margin:0 auto 12px; color:var(--vscode-errorForeground); }
    code { font-family:var(--vscode-editor-font-family); }
  </style>
</head>
<body>
  <div class="shell">
    <header class="top"><span id="statusDot" class="dot"></span><span class="brand">ERIS</span><span id="statusText" class="meta">disconnected</span><span class="spacer"></span><button id="newChat">New chat</button></header>
    <main id="timeline" class="timeline"></main>
    <footer class="composer-wrap">
      <div class="composer">
        <textarea id="input" placeholder="Giao task, hỏi về code, hoặc yêu cầu Eris kiểm tra workspace…"></textarea>
        <div class="composer-bar"><select id="mode"><option value="execute">Execute</option><option value="inspect">Inspect only</option></select><span class="spacer"></span><button id="stop" title="Dừng task hiện tại">Stop</button><button id="send" class="send">Send</button></div>
      </div>
    </footer>
  </div>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const timeline = document.getElementById('timeline');
  const input = document.getElementById('input');
  let activeTaskId = '';
  let streamNode = null;
  const activityNodes = new Map();
  const pendingInterrupts = new Set();

  function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function scroll() { requestAnimationFrame(() => timeline.scrollTop = timeline.scrollHeight); }
  function addMessage(role, content) {
    const node = document.createElement('section');
    node.className = 'message ' + role;
    node.innerHTML = '<div class="meta">' + (role === 'user' ? 'You' : 'Eris') + '</div><div>' + esc(content) + '</div>';
    timeline.appendChild(node); scroll(); return node;
  }
  function addActivity(event) {
    const payload = event?.payload ?? event ?? {};
    const status = String(payload?.status ?? 'running');
    const semantic = String(payload?.data?.tool ?? payload?.kind ?? payload?.label ?? event?.type ?? 'activity');
    const key = String(event?.taskId ?? activeTaskId ?? '') + ':' + semantic;
    let node = activityNodes.get(key);
    if (!node) { node = document.createElement('div'); node.className = 'activity'; timeline.appendChild(node); activityNodes.set(key, node); }
    const mark = status === 'completed' ? '✓' : status === 'failed' ? '×' : status === 'paused' ? 'Ⅱ' : '·';
    node.innerHTML = '<span class="mark">' + mark + '</span><span><strong>' + esc(payload?.label ?? 'Working') + '</strong>' + (payload?.detail ? ' · ' + esc(payload.detail) : '') + '</span>';
    scroll();
  }
  function addInterrupt(event) {
    const interruptKey = String(event.taskId ?? activeTaskId ?? '');
    if (interruptKey && pendingInterrupts.has(interruptKey)) return;
    if (interruptKey) pendingInterrupts.add(interruptKey);
    const payload = event.payload ?? {}; const node = document.createElement('section'); node.className = 'interrupt';
    node.innerHTML = '<h3>' + esc(payload.question || 'Eris cần anh chọn') + '</h3><p>Task đã checkpoint. Chọn xong nó sẽ resume đúng thread.</p><div class="choices"></div>';
    const choices = node.querySelector('.choices');
    for (const option of (payload.options ?? [])) {
      const button = document.createElement('button'); button.className = 'choice';
      button.innerHTML = '<strong>' + esc(option.label ?? option.id) + '</strong>' + (option.description || option.desc ? '<span>' + esc(option.description ?? option.desc) + '</span>' : '');
      button.onclick = () => { disableChoices(node); if (interruptKey) pendingInterrupts.delete(interruptKey); vscode.postMessage({ type:'interrupt.resolve', taskId:event.taskId, response:{ choiceId:String(option.id ?? ''), value:String(option.value ?? option.label ?? ''), text:String(option.label ?? '') } }); };
      choices.appendChild(button);
    }
    if (payload.allowOther !== false) {
      const row = document.createElement('div'); row.className = 'other-row';
      const field = document.createElement('input'); field.placeholder = 'Nhập hướng khác…';
      const button = document.createElement('button'); button.textContent = 'Gửi';
      const submit = () => { const value = field.value.trim(); if (!value) return; disableChoices(node); if (interruptKey) pendingInterrupts.delete(interruptKey); vscode.postMessage({ type:'interrupt.resolve', taskId:event.taskId, response:{ choiceId:'other', value, text:value } }); };
      button.onclick = submit; field.onkeydown = (e) => { if (e.key === 'Enter') submit(); };
      row.append(field, button); choices.appendChild(row);
    }
    timeline.appendChild(node); scroll();
  }
  function disableChoices(node) { for (const control of node.querySelectorAll('button,input')) control.disabled = true; }
  function addArtifact(event) {
    const path = String(event.payload?.path ?? ''); const node = document.createElement('section'); node.className = 'artifact';
    node.innerHTML = '<div class="meta">Modified</div><code>' + esc(path) + '</code>';
    node.onclick = () => vscode.postMessage({ type:'openArtifact', path }); timeline.appendChild(node); scroll();
  }
  function send() {
    const content = input.value.trim(); if (!content) return;
    addMessage('user', content); input.value = ''; streamNode = null;
    vscode.postMessage({ type:'sendMessage', content, taskMode:document.getElementById('mode').value });
  }
  document.getElementById('send').onclick = send;
  document.getElementById('newChat').onclick = () => vscode.postMessage({ type:'newChat' });
  document.getElementById('stop').onclick = () => activeTaskId && vscode.postMessage({ type:'task.control', taskId:activeTaskId, action:'stop' });
  input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } });

  window.addEventListener('message', ({data:event}) => {
    if (event.taskId) activeTaskId = String(event.taskId);
    if (event.type === 'chat.reset') { timeline.innerHTML = ''; activeTaskId = ''; streamNode = null; activityNodes.clear(); pendingInterrupts.clear(); return; }
    if (event.type === 'connection') {
      document.getElementById('statusText').textContent = event.state;
      document.getElementById('statusDot').classList.toggle('connected', event.state === 'connected'); return;
    }
    if (event.type === 'session.restore') {
      const task = event.task ?? {}; activeTaskId = String(task.task_id ?? '');
      const status = String(task.status ?? '');
      addActivity({ taskId:activeTaskId, type:'activity.restore', payload:{ label:'Khôi phục task: ' + String(task.goal ?? ''), detail:status, status:status === 'completed' ? 'completed' : status } });
      if ((status === 'waiting_user' || status === 'waiting_permission') && task.pending_interrupt) {
        addInterrupt({ taskId:activeTaskId, payload:task.pending_interrupt });
      }
      return;
    }
    if (event.type === 'message.assistant') { addMessage('assistant', event.payload?.content ?? ''); streamNode = null; return; }
    if (event.type === 'message.assistant.delta') {
      if (!streamNode) streamNode = addMessage('assistant', '');
      streamNode.lastElementChild.textContent += String(event.payload?.delta ?? ''); scroll(); return;
    }
    if (String(event.type).startsWith('activity.')) { addActivity(event); return; }
    if (event.type === 'interrupt.request') { addInterrupt(event); return; }
    if (event.type === 'interrupt.resolved') { pendingInterrupts.delete(String(event.taskId ?? '')); return; }
    if (event.type === 'artifact.modified' || event.type === 'artifact.created') { addArtifact(event); return; }
    if (event.type === 'client.error' || event.type === 'error') { const n=document.createElement('div'); n.className='error'; n.textContent=event.message ?? event.code ?? 'Eris service error'; timeline.appendChild(n); scroll(); }
  });
</script>
</body>
</html>`;
  }

  dispose(): void {
    if (ErisChatPanel.current === this) {
      ErisChatPanel.current = undefined;
    }
    while (this.disposables.length) {
      this.disposables.pop()?.dispose();
    }
  }
}

async function executeEditorCommand(payload: Record<string, unknown>): Promise<void> {
  const command = String(payload.command ?? payload.type ?? '');
  if (command === 'editor.openFile') {
    await openWorkspaceFile(String(payload.path ?? ''), Number(payload.line ?? 1), Number(payload.column ?? 1));
    return;
  }
  if (command === 'editor.focusProblems') {
    await vscode.commands.executeCommand('workbench.actions.view.problems');
  }
}

async function openWorkspaceFile(filePath: string, line = 1, column = 1): Promise<void> {
  if (!filePath.trim()) {
    return;
  }
  const folders = vscode.workspace.workspaceFolders ?? [];
  let uri: vscode.Uri | undefined;
  if (path.isAbsolute(filePath)) {
    uri = vscode.Uri.file(filePath);
  } else {
    for (const folder of folders) {
      const candidate = vscode.Uri.joinPath(folder.uri, ...filePath.replaceAll('\\', '/').split('/'));
      try {
        await vscode.workspace.fs.stat(candidate);
        uri = candidate;
        break;
      } catch {
        // Thử workspace folder kế tiếp.
      }
    }
  }
  if (!uri) {
    void vscode.window.showWarningMessage(`Eris không tìm thấy file: ${filePath}`);
    return;
  }
  const document = await vscode.workspace.openTextDocument(uri);
  const editor = await vscode.window.showTextDocument(document, { preview: true, preserveFocus: false });
  const position = new vscode.Position(Math.max(0, line - 1), Math.max(0, column - 1));
  editor.selection = new vscode.Selection(position, position);
  editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
}
