import * as crypto from 'node:crypto';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { captureIdeContext, currentWorkspaceRef } from './contextBridge';
import { WorkspaceDiffProvider } from './diffProvider';
import { openWorkspaceFile } from './editorBridge';
import { ErisClient } from './erisClient';
import { TerminalContextObserver } from './terminalObserver';

type SessionStatus = 'idle' | 'running' | 'waiting' | 'done' | 'failed';

type SessionTab = {
  threadId: string;
  title: string;
  updatedAt: number;
  status: SessionStatus;
  taskId?: string;
};

type AttachmentKind = 'file' | 'image';

type ComposerAttachment = {
  id: string;
  kind: AttachmentKind;
  name: string;
  mime: string;
  size: number;
  path: string;
  relativePath?: string;
  excerpt?: string;
};

const SESSION_KEY = 'eris.openSessions.v3';
const CURRENT_THREAD_KEY = 'eris.currentThreadId';
const MAX_OPEN_SESSIONS = 8;
const MAX_ATTACHMENTS = 8;
const MAX_PASTED_IMAGE_BYTES = 8 * 1024 * 1024;
const MAX_TEXT_ATTACHMENT_BYTES = 256 * 1024;
const MAX_ATTACHMENT_EXCERPT = 12_000;

/**
 * Một Webview duy nhất kiểu coding agent. Multi-chat, attachment và task progress
 * đều sống trong surface này; không dựng thêm TreeView/accordion phụ chỉ để UI
 * trông giống bảng quản trị. Socket/file I/O vẫn nằm ở Extension Host.
 */
export class ErisChatPanel implements vscode.WebviewViewProvider, vscode.Disposable {
  static readonly viewType = 'eris.mainView';

  private readonly disposables: vscode.Disposable[] = [];
  private readonly viewDisposables: vscode.Disposable[] = [];
  private readonly attachments = new Map<string, ComposerAttachment>();
  private view?: vscode.WebviewView;
  private threadId: string;
  private activeTaskId = '';
  private sessions: SessionTab[];

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly client: ErisClient,
    private readonly extensionContext: vscode.ExtensionContext,
    private readonly terminalObserver: TerminalContextObserver,
    private readonly diffProvider: WorkspaceDiffProvider,
  ) {
    this.sessions = this.loadSessions();
    const persisted = extensionContext.workspaceState.get<string>(CURRENT_THREAD_KEY, '').trim();
    const existing = this.sessions.find((item) => item.threadId === persisted);
    if (existing) {
      this.threadId = existing.threadId;
    } else if (this.sessions.length) {
      this.threadId = this.sessions[this.sessions.length - 1].threadId;
    } else {
      this.threadId = this.createLocalSession().threadId;
    }
    this.ensureCurrentSession();
    this.persistSessions();

    // Listener backend sống ngoài iframe. Chuyển tab/ẩn Sidebar không làm task mất
    // event, và event của thread B không được chảy nhầm vào conversation thread A.
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
      localResourceRoots: [this.extensionUri, this.extensionContext.globalStorageUri],
    };
    view.webview.html = this.html(view.webview);
    view.description = 'Eris coding agent';

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
    void this.postSessions();
    void this.client.connect().then(async () => {
      await this.client.createThread(this.threadId);
      await this.client.requestThreadHistory(this.threadId);
      await this.client.requestTasks();
    }).catch((error) => {
      // Connection lỗi là trạng thái service, không phải một message chat. Đừng
      // biến conversation thành bãi log chỉ vì backend chưa bật.
      void this.post({ type: 'service.error', message: String(error) });
    });
  }

  async show(preserveFocus = false): Promise<void> {
    if (this.view) {
      this.view.show(preserveFocus);
      return;
    }
    await vscode.commands.executeCommand(`${ErisChatPanel.viewType}.focus`);
    (this.view as vscode.WebviewView | undefined)?.show(preserveFocus);
  }

  newChat(): void {
    const session = this.createLocalSession();
    this.threadId = session.threadId;
    this.activeTaskId = '';
    this.ensureSessionLimit();
    this.persistSessions();
    void this.extensionContext.workspaceState.update(CURRENT_THREAD_KEY, this.threadId);
    void this.postSessions();
    void this.post({ type: 'chat.reset', threadId: this.threadId });
    void this.client.createThread(this.threadId).catch(() => undefined);
  }

  async selectTask(taskId: string, threadId: string): Promise<void> {
    const resolvedThread = String(threadId ?? '').trim();
    if (!resolvedThread) {
      return;
    }
    this.ensureSession(resolvedThread, 'Previous session');
    await this.selectThread(resolvedThread, String(taskId ?? '').trim());
  }

  private loadSessions(): SessionTab[] {
    const raw = this.extensionContext.workspaceState.get<any[]>(SESSION_KEY, []);
    if (!Array.isArray(raw)) {
      return [];
    }
    const seen = new Set<string>();
    const sessions: SessionTab[] = [];
    for (const item of raw) {
      const threadId = String(item?.threadId ?? '').trim();
      if (!threadId || seen.has(threadId)) {
        continue;
      }
      seen.add(threadId);
      const status = String(item?.status ?? 'idle') as SessionStatus;
      sessions.push({
        threadId,
        title: String(item?.title ?? 'New Session').trim() || 'New Session',
        updatedAt: Number(item?.updatedAt ?? Date.now()) || Date.now(),
        status: ['idle', 'running', 'waiting', 'done', 'failed'].includes(status) ? status : 'idle',
        taskId: String(item?.taskId ?? '').trim() || undefined,
      });
    }
    return sessions.slice(-MAX_OPEN_SESSIONS);
  }

  private createLocalSession(title = 'New Session'): SessionTab {
    const session: SessionTab = {
      threadId: `thread_${crypto.randomUUID()}`,
      title,
      updatedAt: Date.now(),
      status: 'idle',
    };
    this.sessions.push(session);
    return session;
  }

  private ensureCurrentSession(): void {
    this.ensureSession(this.threadId, 'New Session');
  }

  private ensureSession(threadId: string, title = 'New Session'): SessionTab {
    let session = this.sessions.find((item) => item.threadId === threadId);
    if (!session) {
      session = { threadId, title, updatedAt: Date.now(), status: 'idle' };
      this.sessions.push(session);
      this.ensureSessionLimit();
    }
    return session;
  }

  private ensureSessionLimit(): void {
    if (this.sessions.length <= MAX_OPEN_SESSIONS) {
      return;
    }
    const active = this.threadId;
    const removable = this.sessions
      .filter((item) => item.threadId !== active && item.status !== 'running' && item.status !== 'waiting')
      .sort((a, b) => a.updatedAt - b.updatedAt);
    while (this.sessions.length > MAX_OPEN_SESSIONS && removable.length) {
      const next = removable.shift();
      if (next) {
        this.sessions = this.sessions.filter((item) => item.threadId !== next.threadId);
      }
    }
    this.sessions = this.sessions.slice(-MAX_OPEN_SESSIONS);
  }

  private persistSessions(): void {
    void this.extensionContext.workspaceState.update(SESSION_KEY, this.sessions);
  }

  private async postSessions(): Promise<void> {
    await this.post({
      type: 'session.tabs',
      activeThreadId: this.threadId,
      sessions: this.sessions,
    });
  }

  private touchSession(threadId: string, patch: Partial<SessionTab>): void {
    const session = this.ensureSession(threadId);
    Object.assign(session, patch, { updatedAt: Date.now() });
    this.persistSessions();
    void this.postSessions();
  }

  private titleFromContent(content: string): string {
    const oneLine = content.replace(/\s+/g, ' ').trim();
    if (!oneLine) {
      return 'New Session';
    }
    return oneLine.length <= 34 ? oneLine : `${oneLine.slice(0, 33).trimEnd()}…`;
  }

  private async selectThread(threadId: string, taskId = ''): Promise<void> {
    const resolved = String(threadId ?? '').trim();
    if (!resolved || resolved === this.threadId && !taskId) {
      return;
    }
    const session = this.ensureSession(resolved);
    this.threadId = resolved;
    this.activeTaskId = taskId || session.taskId || '';
    session.updatedAt = Date.now();
    this.persistSessions();
    await this.extensionContext.workspaceState.update(CURRENT_THREAD_KEY, this.threadId);
    await this.postSessions();
    await this.post({ type: 'chat.reset', threadId: this.threadId, preserveTask: this.activeTaskId });
    await this.client.createThread(this.threadId).catch(() => undefined);
    await this.client.requestThreadHistory(this.threadId).catch((error) => {
      void this.post({ type: 'service.error', message: String(error) });
    });
  }

  private async closeThread(threadId: string): Promise<void> {
    const index = this.sessions.findIndex((item) => item.threadId === threadId);
    if (index < 0) {
      return;
    }
    const closingCurrent = threadId === this.threadId;
    this.sessions.splice(index, 1);
    if (!this.sessions.length) {
      const created = this.createLocalSession();
      this.threadId = created.threadId;
      this.activeTaskId = '';
      this.persistSessions();
      await this.extensionContext.workspaceState.update(CURRENT_THREAD_KEY, this.threadId);
      await this.postSessions();
      await this.post({ type: 'chat.reset', threadId: this.threadId });
      await this.client.createThread(this.threadId).catch(() => undefined);
      return;
    }
    this.persistSessions();
    if (closingCurrent) {
      const next = this.sessions[Math.min(index, this.sessions.length - 1)];
      await this.selectThread(next.threadId, next.taskId ?? '');
    } else {
      await this.postSessions();
    }
  }

  private async ideContext(keys?: string[]): Promise<Record<string, unknown>> {
    const raw = await captureIdeContext(this.terminalObserver);
    const requested = Array.isArray(keys) ? keys.map((item) => String(item)) : [];
    if (!requested.length) {
      return raw;
    }
    const result: Record<string, unknown> = {
      capturedAt: raw.capturedAt,
      workspace: raw.workspace,
    };
    for (const key of requested) {
      if (key in raw) {
        result[key] = raw[key];
      }
    }
    return result;
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
        const session = this.ensureSession(this.threadId);
        if (session.title === 'New Session') {
          session.title = this.titleFromContent(content);
        }
        session.status = 'running';
        session.updatedAt = Date.now();
        this.persistSessions();
        await this.postSessions();

        const context = await this.ideContext(Array.isArray(message.contextKeys) ? message.contextKeys : undefined);
        const attachmentIds: string[] = Array.isArray(message.attachmentIds) ? message.attachmentIds.map((value: unknown) => String(value)) : [];
        const resolvedAttachments: ComposerAttachment[] = attachmentIds
          .map((id: string) => this.attachments.get(id))
          .filter((item: ComposerAttachment | undefined): item is ComposerAttachment => Boolean(item));
        if (resolvedAttachments.length) {
          context.attachments = resolvedAttachments.map((item: ComposerAttachment) => ({
            id: item.id,
            kind: item.kind,
            name: item.name,
            mime: item.mime,
            size: item.size,
            path: item.path,
            relativePath: item.relativePath ?? '',
            excerpt: item.excerpt ?? '',
          }));
        }

        await this.client.sendUserMessage(content, {
          threadId: this.threadId,
          taskMode: message.taskMode === 'inspect' ? 'inspect' : 'execute',
          workspaceRef: currentWorkspaceRef(),
          context,
        });
        for (const id of attachmentIds) {
          this.attachments.delete(id);
        }
        await this.post({ type: 'attachments.clear' });
        return;
      }
      if (type === 'session.select') {
        await this.selectThread(String(message.threadId ?? ''));
        return;
      }
      if (type === 'session.close') {
        await this.closeThread(String(message.threadId ?? ''));
        return;
      }
      if (type === 'attachment.pick') {
        await this.pickAttachments();
        return;
      }
      if (type === 'attachment.image') {
        await this.storePastedImage(String(message.name ?? 'image.png'), String(message.dataUrl ?? ''));
        return;
      }
      if (type === 'attachment.remove') {
        this.attachments.delete(String(message.id ?? ''));
        return;
      }
      if (type === 'interrupt.resolve') {
        const rawResponse = message.response && typeof message.response === 'object' ? message.response : {};
        await this.client.resolveInterrupt(String(message.taskId ?? this.activeTaskId), {
          ...rawResponse,
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
      if (type === 'reconnect') {
        await vscode.commands.executeCommand('eris.reconnect');
        return;
      }
      if (type === 'selfTest') {
        await vscode.commands.executeCommand('eris.selfTest');
        return;
      }
      if (type === 'settings') {
        await vscode.commands.executeCommand('workbench.action.openSettings', '@ext:gtvk.eris-vscode');
        return;
      }
      if (type === 'newChat') {
        this.newChat();
      }
    } catch (error) {
      await this.post({ type: 'client.error', message: String(error) });
    }
  }

  private async pickAttachments(): Promise<void> {
    const uris = await vscode.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: true,
      openLabel: 'Attach to Eris',
    });
    if (!uris?.length) {
      return;
    }
    const available = Math.max(0, MAX_ATTACHMENTS - this.attachments.size);
    for (const uri of uris.slice(0, available)) {
      const attachment = await this.attachmentFromUri(uri);
      this.attachments.set(attachment.id, attachment);
      await this.post({ type: 'attachment.add', attachment: this.publicAttachment(attachment) });
    }
  }

  private async attachmentFromUri(uri: vscode.Uri): Promise<ComposerAttachment> {
    const stat = await vscode.workspace.fs.stat(uri);
    const mime = this.guessMime(uri.path);
    const kind: AttachmentKind = mime.startsWith('image/') ? 'image' : 'file';
    let excerpt = '';
    if (kind === 'file' && stat.size <= MAX_TEXT_ATTACHMENT_BYTES && this.looksTextual(uri.path, mime)) {
      try {
        const bytes = await vscode.workspace.fs.readFile(uri);
        excerpt = Buffer.from(bytes).toString('utf8').slice(0, MAX_ATTACHMENT_EXCERPT);
      } catch {
        excerpt = '';
      }
    }
    const folder = vscode.workspace.getWorkspaceFolder(uri);
    return {
      id: `att_${crypto.randomUUID()}`,
      kind,
      name: path.basename(uri.fsPath),
      mime,
      size: stat.size,
      path: uri.fsPath,
      relativePath: folder ? path.relative(folder.uri.fsPath, uri.fsPath).replaceAll('\\', '/') : '',
      excerpt,
    };
  }

  private async storePastedImage(name: string, dataUrl: string): Promise<void> {
    if (this.attachments.size >= MAX_ATTACHMENTS) {
      throw new Error(`Tối đa ${MAX_ATTACHMENTS} attachment mỗi message.`);
    }
    const match = /^data:(image\/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=\r\n]+)$/i.exec(dataUrl.trim());
    if (!match) {
      throw new Error('Định dạng ảnh paste/drop không được hỗ trợ.');
    }
    const bytes = Buffer.from(match[2], 'base64');
    if (!bytes.length || bytes.length > MAX_PASTED_IMAGE_BYTES) {
      throw new Error('Ảnh attachment phải nhỏ hơn 8 MB.');
    }
    const safeName = path.basename(name || 'image.png').replace(/[^a-zA-Z0-9._-]+/g, '_').slice(-80) || 'image.png';
    const dir = vscode.Uri.joinPath(this.extensionContext.globalStorageUri, 'attachments', this.threadId);
    await vscode.workspace.fs.createDirectory(dir);
    const uri = vscode.Uri.joinPath(dir, `${Date.now()}_${crypto.randomUUID().slice(0, 8)}_${safeName}`);
    await vscode.workspace.fs.writeFile(uri, bytes);
    const attachment: ComposerAttachment = {
      id: `att_${crypto.randomUUID()}`,
      kind: 'image',
      name: safeName,
      mime: match[1].toLowerCase(),
      size: bytes.length,
      path: uri.fsPath,
    };
    this.attachments.set(attachment.id, attachment);
    await this.post({ type: 'attachment.add', attachment: this.publicAttachment(attachment), preview: dataUrl });
  }

  private publicAttachment(item: ComposerAttachment): Record<string, unknown> {
    return {
      id: item.id,
      kind: item.kind,
      name: item.name,
      mime: item.mime,
      size: item.size,
      relativePath: item.relativePath ?? '',
    };
  }

  private looksTextual(filePath: string, mime: string): boolean {
    if (mime.startsWith('text/')) {
      return true;
    }
    const ext = path.extname(filePath).toLowerCase();
    return new Set([
      '.py', '.ts', '.tsx', '.js', '.jsx', '.json', '.md', '.txt', '.yaml', '.yml', '.toml', '.ini',
      '.cs', '.cpp', '.c', '.h', '.hpp', '.java', '.kt', '.rs', '.go', '.rb', '.php', '.html', '.css',
      '.scss', '.sql', '.sh', '.ps1', '.bat', '.xml', '.gd', '.tres', '.tscn',
    ]).has(ext);
  }

  private guessMime(filePath: string): string {
    const ext = path.extname(filePath).toLowerCase();
    const imageTypes: Record<string, string> = {
      '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif',
    };
    if (imageTypes[ext]) {
      return imageTypes[ext];
    }
    const textual = new Set(['.py', '.ts', '.tsx', '.js', '.jsx', '.json', '.md', '.txt', '.yaml', '.yml', '.toml', '.ini', '.cs', '.cpp', '.c', '.h', '.hpp', '.java', '.kt', '.rs', '.go', '.rb', '.php', '.html', '.css', '.scss', '.sql', '.sh', '.ps1', '.bat', '.xml', '.gd', '.tres', '.tscn']);
    return textual.has(ext) ? 'text/plain' : 'application/octet-stream';
  }

  private async onAgentEvent(event: any): Promise<void> {
    const type = String(event?.type ?? '');
    const eventThread = String(event?.threadId ?? event?.thread_id ?? '').trim();
    const eventTaskId = String(event?.taskId ?? event?.task_id ?? '').trim();

    if (type === 'session.ready') {
      await this.post({ type: 'connection', state: 'connected' });
      await this.post(event);
      await this.client.createThread(this.threadId);
      if (this.view) {
        await this.client.requestThreadHistory(this.threadId);
        await this.client.requestTasks();
      }
      return;
    }

    if (type === 'task.list') {
      const tasks = Array.isArray(event.tasks) ? event.tasks : [];
      this.syncSessionsFromTasks(tasks);
      await this.post(event);
      return;
    }

    if (type === 'thread.history') {
      const historyThread = String(event.threadId ?? '').trim();
      if (historyThread !== this.threadId) {
        return;
      }
      const tasks = Array.isArray(event.tasks) ? event.tasks : [];
      const active = [...tasks].reverse().find((task: any) =>
        ['queued', 'running', 'paused', 'waiting_user', 'waiting_permission'].includes(String(task?.status ?? '')),
      ) ?? tasks.at(-1);
      if (active?.task_id) {
        this.activeTaskId = String(active.task_id);
        this.touchSession(this.threadId, {
          taskId: this.activeTaskId,
          status: this.mapTaskStatus(String(active.status ?? '')),
          title: this.sessionTitleFromTask(active, this.ensureSession(this.threadId).title),
        });
      }
      await this.post(event);
      return;
    }

    // Live RPC/editor command đã được extension.ts xử lý toàn cục.
    if (type === 'ide.request' || type === 'editor.command') {
      return;
    }

    if (eventThread) {
      const patch: Partial<SessionTab> = {};
      if (eventTaskId) {
        patch.taskId = eventTaskId;
      }
      if (type === 'message.user') {
        const content = String(event.payload?.content ?? '').trim();
        const current = this.ensureSession(eventThread);
        if (current.title === 'New Session' && content) {
          patch.title = this.titleFromContent(content);
        }
        patch.status = 'running';
      } else if (type === 'interrupt.request') {
        patch.status = 'waiting';
      } else if (type === 'activity.end') {
        const status = String(event.payload?.status ?? '');
        patch.status = status === 'failed' ? 'failed' : status === 'completed' ? 'done' : 'idle';
      } else if (type === 'activity.start' || type === 'activity.update' || type === 'coding.state') {
        patch.status = 'running';
      }
      if (Object.keys(patch).length) {
        this.touchSession(eventThread, patch);
      }
      if (eventThread !== this.threadId) {
        return;
      }
    }

    if (eventTaskId) {
      this.activeTaskId = eventTaskId;
    }
    await this.post(event);
  }

  private syncSessionsFromTasks(tasks: any[]): void {
    let changed = false;
    for (const task of tasks) {
      const threadId = String(task?.thread_id ?? task?.threadId ?? '').trim();
      if (!threadId) {
        continue;
      }
      const existing = this.sessions.find((item) => item.threadId === threadId);
      if (!existing) {
        continue;
      }
      existing.status = this.mapTaskStatus(String(task?.status ?? ''));
      existing.taskId = String(task?.task_id ?? existing.taskId ?? '').trim() || existing.taskId;
      existing.title = this.sessionTitleFromTask(task, existing.title);
      existing.updatedAt = Number(task?.updated_at ?? Date.now()) * (Number(task?.updated_at ?? 0) < 10_000_000_000 ? 1000 : 1) || Date.now();
      changed = true;
    }
    if (changed) {
      this.persistSessions();
      void this.postSessions();
    }
  }

  private sessionTitleFromTask(task: any, fallback: string): string {
    if (fallback && fallback !== 'New Session' && fallback !== 'Previous session') {
      return fallback;
    }
    const goal = String(task?.clarified_goal ?? task?.goal ?? '').trim();
    return goal ? this.titleFromContent(goal) : fallback;
  }

  private mapTaskStatus(status: string): SessionStatus {
    const value = status.trim().toLowerCase();
    if (value === 'waiting_user' || value === 'waiting_permission' || value === 'paused') {
      return 'waiting';
    }
    if (value === 'queued' || value === 'running') {
      return 'running';
    }
    if (value === 'failed' || value === 'stopped') {
      return 'failed';
    }
    if (value === 'completed' || value === 'done') {
      return 'done';
    }
    return 'idle';
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
    :root { color-scheme: light dark; --eris-accent: var(--vscode-focusBorder); }
    * { box-sizing:border-box; }
    html,body { width:100%; height:100%; }
    body { margin:0; overflow:hidden; color:var(--vscode-foreground); background:var(--vscode-sideBar-background); font:13px/1.45 var(--vscode-font-family); }
    button,select,input,textarea { font:inherit; color:inherit; }
    button { cursor:pointer; }
    .shell { height:100vh; display:grid; grid-template-rows:36px auto minmax(0,1fr) auto; }
    .session-strip { display:flex; align-items:center; gap:4px; min-width:0; padding:5px 6px; border-bottom:1px solid var(--vscode-sideBar-border,var(--vscode-panel-border)); }
    .session-tabs { min-width:0; flex:1; display:flex; gap:4px; overflow:auto hidden; scrollbar-width:none; }
    .session-tabs::-webkit-scrollbar { display:none; }
    .session-tab { flex:none; max-width:150px; height:26px; display:flex; align-items:center; gap:5px; padding:0 7px; border:1px solid transparent; border-radius:6px; background:transparent; color:var(--vscode-descriptionForeground); }
    .session-tab:hover { background:var(--vscode-toolbar-hoverBackground); color:var(--vscode-foreground); }
    .session-tab.active { border-color:var(--vscode-widget-border,var(--vscode-panel-border)); background:var(--vscode-editor-background); color:var(--vscode-foreground); }
    .session-title { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .session-state { width:6px; height:6px; flex:none; border-radius:50%; background:var(--vscode-descriptionForeground); opacity:.55; }
    .session-state.running { background:var(--vscode-progressBar-background); opacity:1; box-shadow:0 0 0 2px color-mix(in srgb,var(--vscode-progressBar-background) 20%,transparent); }
    .session-state.waiting { background:var(--vscode-editorWarning-foreground); opacity:1; }
    .session-state.done { background:var(--vscode-testing-iconPassed); opacity:1; }
    .session-state.failed { background:var(--vscode-testing-iconFailed); opacity:1; }
    .close-tab { flex:none; border:0; padding:0; width:14px; height:14px; line-height:12px; border-radius:3px; background:transparent; color:var(--vscode-descriptionForeground); opacity:0; }
    .session-tab:hover .close-tab,.session-tab.active .close-tab { opacity:.75; }
    .close-tab:hover { background:var(--vscode-toolbar-hoverBackground); opacity:1; }
    .icon-btn { flex:none; width:26px; height:26px; display:grid; place-items:center; padding:0; border:0; border-radius:5px; background:transparent; font-size:15px; }
    .icon-btn:hover { background:var(--vscode-toolbar-hoverBackground); }
    .connection { display:none; align-items:center; gap:7px; padding:4px 9px 5px; color:var(--vscode-descriptionForeground); font-size:11px; border-bottom:1px solid var(--vscode-sideBar-border,var(--vscode-panel-border)); }
    .connection.visible { display:flex; }
    .connection .dot { width:6px; height:6px; border-radius:50%; background:var(--vscode-testing-iconFailed); }
    .connection button { margin-left:auto; border:0; padding:2px 4px; background:transparent; color:var(--vscode-textLink-foreground); }
    .connection button:hover { text-decoration:underline; }
    .viewport { min-height:0; position:relative; overflow:hidden; }
    .chat { height:100%; display:flex; flex-direction:column; min-height:0; }
    .timeline { min-height:0; flex:1; overflow:auto; padding:14px 12px 28px; }
    .empty { min-height:100%; display:grid; place-items:center; padding:20px 8px; }
    .empty-inner { width:100%; max-width:330px; text-align:center; }
    .spark { font-size:20px; line-height:1; color:var(--eris-accent); margin-bottom:9px; }
    .empty h2 { margin:0; font-size:16px; font-weight:650; }
    .empty p { max-width:290px; margin:5px auto 16px; color:var(--vscode-descriptionForeground); font-size:11px; }
    .mode-cards { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    .mode-card { min-width:0; text-align:left; border:1px solid var(--vscode-widget-border,var(--vscode-panel-border)); border-radius:8px; padding:10px; background:var(--vscode-editor-background); }
    .mode-card:hover { border-color:var(--vscode-focusBorder); }
    .mode-card.selected { border-color:var(--eris-accent); box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--eris-accent) 45%,transparent); }
    .mode-card strong { display:block; font-size:11px; }
    .mode-card span { display:block; margin-top:3px; color:var(--vscode-descriptionForeground); font-size:10px; line-height:1.35; }
    .message { margin:0 0 17px; white-space:pre-wrap; overflow-wrap:anywhere; }
    .message .role { margin-bottom:4px; color:var(--vscode-descriptionForeground); font-size:10px; font-weight:600; letter-spacing:.04em; text-transform:uppercase; }
    .message.user { margin-left:18px; padding:8px 10px; border-radius:8px; background:var(--vscode-input-background); border:1px solid var(--vscode-input-border,var(--vscode-panel-border)); }
    .message.assistant { margin-right:8px; }
    .work-card { margin:5px 0 14px; border:1px solid var(--vscode-widget-border,var(--vscode-panel-border)); border-radius:8px; background:color-mix(in srgb,var(--vscode-editor-background) 72%,transparent); overflow:hidden; }
    .work-card summary { list-style:none; display:flex; align-items:center; gap:7px; min-height:34px; padding:7px 9px; cursor:pointer; color:var(--vscode-descriptionForeground); font-size:11px; }
    .work-card summary::-webkit-details-marker { display:none; }
    .work-card summary:hover { color:var(--vscode-foreground); background:var(--vscode-toolbar-hoverBackground); }
    .work-dot { width:7px; height:7px; flex:none; border-radius:50%; background:var(--vscode-progressBar-background); }
    .work-card.done .work-dot { background:var(--vscode-testing-iconPassed); }
    .work-card.failed .work-dot { background:var(--vscode-testing-iconFailed); }
    .work-label { min-width:0; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .work-count { flex:none; font-size:10px; opacity:.8; }
    .work-body { border-top:1px solid var(--vscode-widget-border,var(--vscode-panel-border)); padding:6px 9px 8px; }
    .activity { display:flex; gap:7px; padding:2px 0; color:var(--vscode-descriptionForeground); font-size:10px; }
    .activity .mark { width:12px; text-align:center; flex:none; }
    .task-actions { display:flex; flex-wrap:wrap; gap:3px; margin-top:6px; }
    .ghost-btn { border:0; border-radius:5px; padding:3px 6px; background:transparent; color:var(--vscode-descriptionForeground); font-size:10px; }
    .ghost-btn:hover { color:var(--vscode-foreground); background:var(--vscode-toolbar-hoverBackground); }
    .artifact,.interrupt { margin:7px 0 14px; border:1px solid var(--vscode-widget-border,var(--vscode-panel-border)); border-radius:8px; padding:9px; background:var(--vscode-editor-background); }
    .artifact-head { display:flex; align-items:center; gap:7px; min-width:0; }
    .artifact-head code { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:10px; }
    .pill { flex:none; padding:1px 5px; border:1px solid var(--vscode-widget-border,var(--vscode-panel-border)); border-radius:999px; color:var(--vscode-descriptionForeground); font-size:9px; }
    .artifact-actions { display:flex; flex-wrap:wrap; gap:4px; margin-top:7px; }
    .artifact-actions button,.choice { border:1px solid var(--vscode-widget-border,var(--vscode-panel-border)); background:transparent; border-radius:6px; padding:5px 7px; }
    .artifact-actions button:hover,.choice:hover { background:var(--vscode-toolbar-hoverBackground); }
    .interrupt h3 { margin:0 0 4px; font-size:12px; }
    .interrupt p { margin:0 0 8px; color:var(--vscode-descriptionForeground); font-size:10px; }
    .choices { display:grid; gap:6px; }
    .choice { text-align:left; }
    .choice strong,.choice span { display:block; }
    .choice span { margin-top:2px; color:var(--vscode-descriptionForeground); font-size:10px; }
    .other-row { display:flex; gap:5px; margin-top:2px; }
    .other-row input { min-width:0; flex:1; color:var(--vscode-input-foreground); background:var(--vscode-input-background); border:1px solid var(--vscode-input-border,var(--vscode-panel-border)); border-radius:6px; padding:6px; outline:0; }
    .notice { display:none; margin:0 12px 8px; padding:6px 8px; border-radius:6px; background:var(--vscode-inputValidation-errorBackground); border:1px solid var(--vscode-inputValidation-errorBorder); color:var(--vscode-inputValidation-errorForeground); font-size:10px; }
    .notice.visible { display:block; }
    .composer-wrap { position:relative; padding:7px 8px 9px; border-top:1px solid var(--vscode-sideBar-border,var(--vscode-panel-border)); background:var(--vscode-sideBar-background); }
    .attachments { display:none; gap:5px; overflow:auto hidden; padding:0 1px 6px; scrollbar-width:none; }
    .attachments.visible { display:flex; }
    .attachments::-webkit-scrollbar { display:none; }
    .attach-chip { flex:none; max-width:190px; display:flex; align-items:center; gap:5px; padding:3px 6px; border:1px solid var(--vscode-widget-border,var(--vscode-panel-border)); border-radius:6px; background:var(--vscode-editor-background); font-size:10px; }
    .attach-chip img { width:18px; height:18px; object-fit:cover; border-radius:3px; }
    .attach-name { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .attach-remove { border:0; padding:0; background:transparent; color:var(--vscode-descriptionForeground); }
    .composer { border:1px solid var(--vscode-input-border,var(--vscode-widget-border,var(--vscode-panel-border))); border-radius:9px; background:var(--vscode-input-background); overflow:hidden; transition:border-color .12s ease; }
    .composer:focus-within { border-color:var(--vscode-focusBorder); }
    textarea { width:100%; min-height:44px; max-height:140px; resize:none; overflow:auto; padding:8px 9px 2px; color:var(--vscode-input-foreground); background:transparent; border:0; outline:0; }
    .composer-bar { display:flex; align-items:center; gap:3px; padding:3px 5px 5px; }
    .composer-tool { height:26px; min-width:26px; border:0; border-radius:5px; padding:0 6px; background:transparent; color:var(--vscode-descriptionForeground); font-size:11px; }
    .composer-tool:hover { color:var(--vscode-foreground); background:var(--vscode-toolbar-hoverBackground); }
    .mode-select { border:0; border-radius:5px; padding:3px 4px; color:var(--vscode-descriptionForeground); background:transparent; font-size:10px; }
    .send { margin-left:auto; width:27px; height:27px; display:grid; place-items:center; border:0; border-radius:7px; color:var(--vscode-button-foreground); background:var(--vscode-button-background); font-size:15px; }
    .send:hover { background:var(--vscode-button-hoverBackground); }
    .context-popover,.menu-popover { display:none; position:absolute; z-index:20; left:8px; bottom:51px; width:min(275px,calc(100% - 16px)); border:1px solid var(--vscode-widget-border,var(--vscode-panel-border)); border-radius:8px; padding:6px; background:var(--vscode-menu-background,var(--vscode-editor-background)); box-shadow:0 8px 28px rgba(0,0,0,.25); }
    .context-popover.visible,.menu-popover.visible { display:block; }
    .context-row,.menu-row { width:100%; display:flex; align-items:center; gap:8px; border:0; border-radius:5px; padding:6px; background:transparent; text-align:left; font-size:11px; }
    .context-row:hover,.menu-row:hover { background:var(--vscode-list-hoverBackground); }
    .context-row input { margin:0; }
    .menu-popover { left:auto; right:7px; bottom:auto; top:34px; width:190px; }
    .menu-sep { height:1px; margin:4px 2px; background:var(--vscode-widget-border,var(--vscode-panel-border)); }
    .drawer { display:none; position:absolute; inset:0; z-index:15; flex-direction:column; background:var(--vscode-sideBar-background); }
    .drawer.visible { display:flex; }
    .drawer-head { display:flex; align-items:center; gap:8px; min-height:38px; padding:5px 9px; border-bottom:1px solid var(--vscode-sideBar-border,var(--vscode-panel-border)); }
    .drawer-head strong { flex:1; }
    .drawer-body { min-height:0; flex:1; overflow:auto; padding:7px; }
    .drawer-card { width:100%; text-align:left; border:1px solid transparent; border-radius:7px; padding:8px; margin-bottom:2px; background:transparent; }
    .drawer-card:hover { background:var(--vscode-list-hoverBackground); }
    .drawer-card strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:600; }
    .drawer-card span { display:block; margin-top:2px; color:var(--vscode-descriptionForeground); font-size:10px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .drop-overlay { display:none; position:absolute; inset:8px; z-index:40; place-items:center; border:1px dashed var(--vscode-focusBorder); border-radius:10px; background:color-mix(in srgb,var(--vscode-sideBar-background) 88%,transparent); color:var(--vscode-foreground); font-size:12px; pointer-events:none; }
    .drop-overlay.visible { display:grid; }
    code { font-family:var(--vscode-editor-font-family); }
    @media (max-width:300px) { .mode-cards { grid-template-columns:1fr; } .session-tab { max-width:120px; } }
  </style>
</head>
<body>
  <div class="shell">
    <div class="session-strip">
      <div id="sessionTabs" class="session-tabs"></div>
      <button id="newChat" class="icon-btn" title="New Session">＋</button>
      <button id="menuButton" class="icon-btn" title="More">⋯</button>
    </div>

    <div id="connection" class="connection">
      <span class="dot"></span><span id="connectionText">Service offline</span>
      <button id="reconnect">Reconnect</button>
    </div>

    <main class="viewport">
      <section class="chat">
        <div id="timeline" class="timeline"></div>
        <div id="notice" class="notice"></div>
      </section>

      <section id="drawer" class="drawer">
        <div class="drawer-head"><button id="drawerBack" class="icon-btn">‹</button><strong id="drawerTitle">History</strong></div>
        <div id="drawerBody" class="drawer-body"></div>
      </section>

      <div id="menuPopover" class="menu-popover">
        <button class="menu-row" data-menu="new">＋ New Session</button>
        <button class="menu-row" data-menu="history">◷ Recent chats</button>
        <button class="menu-row" data-menu="tasks">✓ Tasks</button>
        <button class="menu-row" data-menu="skills">⌘ Skills</button>
        <div class="menu-sep"></div>
        <button class="menu-row" data-menu="source">⌁ Source Control</button>
        <button class="menu-row" data-menu="test">⚗ Run Self Test</button>
        <button class="menu-row" data-menu="reconnect">↻ Reconnect</button>
        <button class="menu-row" data-menu="settings">⚙ Settings</button>
      </div>

      <div id="dropOverlay" class="drop-overlay">Drop files or images to attach</div>
    </main>

    <footer class="composer-wrap">
      <div id="attachments" class="attachments"></div>
      <div class="composer">
        <textarea id="input" rows="1" placeholder="Ask Eris about your code…"></textarea>
        <div class="composer-bar">
          <button id="attach" class="composer-tool" title="Attach files or images">＋</button>
          <button id="contextButton" class="composer-tool" title="Context">#</button>
          <select id="mode" class="mode-select" title="Agent mode"><option value="execute">Agent</option><option value="inspect">Inspect only</option></select>
          <button id="send" class="send" title="Send">↑</button>
        </div>
      </div>
      <div id="contextPopover" class="context-popover">
        <label class="context-row"><input type="checkbox" value="current" checked /> Current file</label>
        <label class="context-row"><input type="checkbox" value="selection" checked /> Selection</label>
        <label class="context-row"><input type="checkbox" value="problems" checked /> Problems</label>
        <label class="context-row"><input type="checkbox" value="git" checked /> Git changes</label>
        <label class="context-row"><input type="checkbox" value="terminal" /> Terminal recent</label>
        <label class="context-row"><input type="checkbox" value="openEditors" /> Open editors</label>
      </div>
    </footer>
  </div>

<script nonce="${nonce}">
  const vscode=acquireVsCodeApi();
  const timeline=document.getElementById('timeline');
  const input=document.getElementById('input');
  const sessionTabs=document.getElementById('sessionTabs');
  const attachmentBox=document.getElementById('attachments');
  const notice=document.getElementById('notice');
  const drawer=document.getElementById('drawer');
  const drawerBody=document.getElementById('drawerBody');
  const drawerTitle=document.getElementById('drawerTitle');
  const menuPopover=document.getElementById('menuPopover');
  const contextPopover=document.getElementById('contextPopover');
  let activeThreadId='';
  let activeTaskId='';
  let sessions=[];
  let catalogTasks=[];
  let catalogSkills=[];
  let streamNode=null;
  let selectedMode='execute';
  const rendered=new Set();
  const pendingInterrupts=new Set();
  const attachmentState=new Map();
  const workCards=new Map();

  const esc=(value)=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const clip=(value,n=80)=>{const text=String(value??'').replace(/\s+/g,' ').trim();return text.length>n?text.slice(0,n-1)+'…':text;};
  const scroll=()=>{requestAnimationFrame(()=>{timeline.scrollTop=timeline.scrollHeight;});};
  const fmtBytes=(n)=>{const v=Number(n||0);if(v<1024)return v+' B';if(v<1048576)return Math.round(v/102.4)/10+' KB';return Math.round(v/104857.6)/10+' MB';};
  const eventKey=(e)=>String(e?.eventId??e?.event_id??'')||[e?.type,e?.taskId,e?.seq,e?.timestamp].join(':');
  function remember(e){const k=eventKey(e);if(!k)return true;if(rendered.has(k))return false;rendered.add(k);if(rendered.size>2500){const first=rendered.values().next().value;rendered.delete(first);}return true;}

  function renderSessions(){
    sessionTabs.innerHTML='';
    for(const session of sessions){
      const tab=document.createElement('button');tab.className='session-tab'+(session.threadId===activeThreadId?' active':'');tab.title=session.title||'New Session';
      const dot=document.createElement('span');dot.className='session-state '+String(session.status||'idle');
      const title=document.createElement('span');title.className='session-title';title.textContent=session.title||'New Session';
      const close=document.createElement('button');close.className='close-tab';close.textContent='×';close.title='Close';close.onclick=(ev)=>{ev.stopPropagation();vscode.postMessage({type:'session.close',threadId:session.threadId});};
      tab.append(dot,title,close);tab.onclick=()=>vscode.postMessage({type:'session.select',threadId:session.threadId});sessionTabs.appendChild(tab);
    }
    requestAnimationFrame(()=>sessionTabs.querySelector('.active')?.scrollIntoView({block:'nearest',inline:'nearest'}));
  }

  function emptyHtml(){return '<div class="empty" id="chatEmpty"><div class="empty-inner"><div class="spark">✦</div><h2>What are we building today?</h2><p>Chat about code, inspect a problem, or let Eris work through a task with your IDE context.</p><div class="mode-cards"><button class="mode-card" data-empty-mode="inspect"><strong>Quick Chat</strong><span>Explore, explain and inspect without changing files.</span></button><button class="mode-card selected" data-empty-mode="execute"><strong>Agent Task</strong><span>Plan, edit, run tests and iterate autonomously.</span></button></div></div></div>';}
  function ensureEmpty(){if(!timeline.children.length){timeline.innerHTML=emptyHtml();bindEmptyModes();}}
  function removeEmpty(){document.getElementById('chatEmpty')?.remove();}
  function bindEmptyModes(){for(const card of timeline.querySelectorAll('[data-empty-mode]'))card.onclick=()=>{selectedMode=card.dataset.emptyMode||'execute';document.getElementById('mode').value=selectedMode;for(const c of timeline.querySelectorAll('[data-empty-mode]'))c.classList.toggle('selected',c===card);input.focus();};}
  function resetTimeline(){timeline.innerHTML='';rendered.clear();pendingInterrupts.clear();workCards.clear();streamNode=null;activeTaskId='';ensureEmpty();}

  function addMessage(role,content,attachments=[]){
    removeEmpty();const node=document.createElement('article');node.className='message '+role;const roleNode=document.createElement('div');roleNode.className='role';roleNode.textContent=role==='user'?'You':'Eris';const body=document.createElement('div');body.textContent=String(content??'');node.append(roleNode,body);
    if(Array.isArray(attachments)&&attachments.length){const row=document.createElement('div');row.className='attachments visible';row.style.padding='7px 0 0';for(const item of attachments.slice(0,8)){const chip=document.createElement('div');chip.className='attach-chip';chip.innerHTML='<span>'+(String(item.kind||'')==='image'?'▧':'▤')+'</span><span class="attach-name">'+esc(item.name||item.relativePath||'attachment')+'</span>';chip.title=(item.relativePath||item.name||'attachment')+' · '+fmtBytes(item.size);row.appendChild(chip);}node.appendChild(row);}
    timeline.appendChild(node);scroll();return node;
  }

  function getWorkCard(taskId){
    const key=String(taskId||activeTaskId||'task');if(workCards.has(key))return workCards.get(key);
    removeEmpty();const card=document.createElement('details');card.className='work-card';card.dataset.taskId=key;card.innerHTML='<summary><span class="work-dot"></span><span class="work-label">Working…</span><span class="work-count"></span></summary><div class="work-body"><div class="work-events"></div><div class="task-actions"><button class="ghost-btn" data-control="pause">Pause</button><button class="ghost-btn" data-control="resume">Resume</button><button class="ghost-btn" data-control="rollback">Rollback</button><button class="ghost-btn" data-control="stop">Stop</button></div></div>';
    for(const button of card.querySelectorAll('[data-control]'))button.onclick=()=>vscode.postMessage({type:'task.control',taskId:key,action:button.dataset.control});
    timeline.appendChild(card);workCards.set(key,card);scroll();return card;
  }

  function updateWork(taskId,label,status,detail){
    const card=getWorkCard(taskId);const clean=String(status||'running');card.classList.toggle('done',clean==='completed'||clean==='done');card.classList.toggle('failed',clean==='failed'||clean==='stopped');
    if(label)card.querySelector('.work-label').textContent=clip(label,90);
    if(detail){const list=card.querySelector('.work-events');const row=document.createElement('div');row.className='activity';row.innerHTML='<span class="mark">'+(clean==='failed'?'×':clean==='completed'?'✓':'·')+'</span><span>'+esc(detail)+'</span>';list.appendChild(row);while(list.children.length>14)list.firstChild.remove();card.querySelector('.work-count').textContent=list.children.length?String(list.children.length):'';}
    if(clean==='completed'||clean==='failed'||clean==='stopped')card.open=false;
  }

  function addActivity(event){const p=event.payload??{};const label=String(p.label??p.detail??event.type??'Working');const detail=String(p.detail??p.label??'');updateWork(event.taskId,label,p.status??(event.type==='activity.end'?'completed':'running'),detail);}
  function mergeCoding(payload){const title=payload.current_action||payload.next_action||payload.phase||'Working';const file=payload.current_file?(' · '+payload.current_file):'';updateWork(activeTaskId,String(title)+file,payload.status||'running','');}

  function disableChoices(node){for(const control of node.querySelectorAll('button,input'))control.disabled=true;}
  function addInterrupt(event){
    removeEmpty();const key=String(event.taskId??activeTaskId??'');if(key&&pendingInterrupts.has(key))return;if(key)pendingInterrupts.add(key);
    const p=event.payload??{};const node=document.createElement('section');node.className='interrupt';node.innerHTML='<h3>'+esc(p.question||'Eris needs a decision')+'</h3><p>The task is checkpointed and will resume from here.</p><div class="choices" role="listbox"></div>';const choices=node.querySelector('.choices');
    for(const option of(p.options??[])){const b=document.createElement('button');b.className='choice';b.innerHTML='<strong>'+esc(option.label??option.id)+'</strong>'+(option.description||option.desc?'<span>'+esc(option.description??option.desc)+'</span>':'');b.onclick=()=>{disableChoices(node);if(key)pendingInterrupts.delete(key);vscode.postMessage({type:'interrupt.resolve',taskId:event.taskId,response:{choiceId:String(option.id??''),value:String(option.value??option.label??''),text:String(option.label??'')}});};choices.appendChild(b);}
    if(p.allowOther!==false){const row=document.createElement('div');row.className='other-row';const field=document.createElement('input');field.placeholder='Other direction…';const b=document.createElement('button');b.className='ghost-btn';b.textContent='Send';const submit=()=>{const value=field.value.trim();if(!value)return;disableChoices(node);if(key)pendingInterrupts.delete(key);vscode.postMessage({type:'interrupt.resolve',taskId:event.taskId,response:{choiceId:'other',value,text:value}});};b.onclick=submit;field.onkeydown=e=>{if(e.key==='Enter')submit();};row.append(field,b);choices.appendChild(row);}
    timeline.appendChild(node);scroll();
  }

  function addArtifact(event){const p=event.payload??{};const filePath=String(p.path??'');if(!filePath)return;removeEmpty();const node=document.createElement('section');node.className='artifact';node.innerHTML='<div class="artifact-head"><span class="pill">Modified</span><code>'+esc(filePath)+'</code></div><div class="artifact-actions"><button data-action="open">Open</button><button data-action="diff">Diff</button></div>';node.querySelector('[data-action="open"]').onclick=()=>vscode.postMessage({type:'openArtifact',path:filePath});node.querySelector('[data-action="diff"]').onclick=()=>vscode.postMessage({type:'openDiff',path:filePath,diff:String(p.diff??'')});timeline.appendChild(node);scroll();}
  function addChangeSet(event){const p=event.payload??{};const id=String(p.changeSetId??p.operationId??'');if(!id)return;removeEmpty();const files=Array.isArray(p.files)?p.files:[];const status=String(p.status??'pending');const node=document.createElement('section');node.className='artifact';node.dataset.changeSetId=id;node.innerHTML='<div class="artifact-head"><span class="pill">ChangeSet · '+esc(status)+'</span><code>'+esc(files.slice(0,3).join(' · ')||id)+'</code></div><div class="artifact-actions"><button data-action="accept">Accept</button><button data-action="revert">Revert</button></div>';const accept=node.querySelector('[data-action="accept"]');const revert=node.querySelector('[data-action="revert"]');if(status!=='pending'){accept.disabled=true;revert.disabled=true;}accept.onclick=()=>activeTaskId&&vscode.postMessage({type:'task.control',taskId:activeTaskId,action:'accept_changeset',changeSetId:id});revert.onclick=()=>activeTaskId&&vscode.postMessage({type:'task.control',taskId:activeTaskId,action:'revert_changeset',changeSetId:id});timeline.appendChild(node);scroll();}
  function updateChangeSet(event){const p=event.payload??{};const id=String(p.changeSetId??p.operationId??'');const node=[...document.querySelectorAll('[data-change-set-id]')].reverse().find(n=>n.dataset.changeSetId===id);if(!node){addChangeSet(event);return;}const pill=node.querySelector('.pill');if(pill)pill.textContent='ChangeSet · '+String(p.status??'updated');for(const b of node.querySelectorAll('button'))b.disabled=true;}

  function renderEvent(event){
    if(!event||!remember(event))return;if(event.taskId)activeTaskId=String(event.taskId);
    if(event.type==='message.user'){addMessage('user',event.payload?.content??'',event.payload?.attachments??[]);return;}
    if(event.type==='message.assistant'){addMessage('assistant',event.payload?.content??'');streamNode=null;return;}
    if(event.type==='message.assistant.delta'){removeEmpty();if(!streamNode)streamNode=addMessage('assistant','');streamNode.lastElementChild.textContent+=String(event.payload?.delta??'');scroll();return;}
    if(event.type==='coding.state'){mergeCoding(event.payload??{});return;}
    if(String(event.type).startsWith('activity.')){addActivity(event);return;}
    if(event.type==='interrupt.request'){addInterrupt(event);return;}
    if(event.type==='interrupt.resolved'){pendingInterrupts.delete(String(event.taskId??''));return;}
    if(event.type==='artifact.modified'||event.type==='artifact.created'){addArtifact(event);return;}
    if(event.type==='changeset.created'){addChangeSet(event);return;}
    if(event.type==='changeset.updated'){updateChangeSet(event);return;}
    if(event.type==='editor.result'){updateWork(event.taskId,event.payload?.message??event.payload?.command??'VS Code',event.payload?.success?'completed':'failed',event.payload?.message??'');}
  }

  function renderAttachments(){
    attachmentBox.innerHTML='';attachmentBox.classList.toggle('visible',attachmentState.size>0);
    for(const item of attachmentState.values()){
      const chip=document.createElement('div');chip.className='attach-chip';if(item.preview){const img=document.createElement('img');img.src=item.preview;chip.appendChild(img);}const icon=document.createElement('span');icon.textContent=item.kind==='image'?'▧':'▤';const name=document.createElement('span');name.className='attach-name';name.textContent=item.name;name.title=(item.relativePath||item.name)+' · '+fmtBytes(item.size);const remove=document.createElement('button');remove.className='attach-remove';remove.textContent='×';remove.onclick=()=>{attachmentState.delete(item.id);renderAttachments();vscode.postMessage({type:'attachment.remove',id:item.id});};chip.append(icon,name,remove);attachmentBox.appendChild(chip);
    }
  }

  function contextKeys(){return [...contextPopover.querySelectorAll('input:checked')].map(n=>n.value);}
  function resizeInput(){input.style.height='auto';input.style.height=Math.min(140,Math.max(44,input.scrollHeight))+'px';}
  function send(){const content=input.value.trim();if(!content)return;const ids=[...attachmentState.keys()];input.value='';resizeInput();streamNode=null;hidePopovers();vscode.postMessage({type:'sendMessage',content,taskMode:document.getElementById('mode').value,attachmentIds:ids,contextKeys:contextKeys()});}
  function hidePopovers(){menuPopover.classList.remove('visible');contextPopover.classList.remove('visible');}
  function showNotice(message){notice.textContent=String(message||'');notice.classList.toggle('visible',Boolean(message));if(message)setTimeout(()=>notice.classList.remove('visible'),7000);}

  function renderDrawer(kind){
    drawer.classList.add('visible');menuPopover.classList.remove('visible');drawerBody.innerHTML='';
    if(kind==='history'){
      drawerTitle.textContent='Recent chats';for(const session of [...sessions].sort((a,b)=>b.updatedAt-a.updatedAt)){const b=document.createElement('button');b.className='drawer-card';b.innerHTML='<strong>'+esc(session.title||'New Session')+'</strong><span>'+esc(session.status||'idle')+'</span>';b.onclick=()=>{drawer.classList.remove('visible');vscode.postMessage({type:'session.select',threadId:session.threadId});};drawerBody.appendChild(b);}return;
    }
    if(kind==='tasks'){
      drawerTitle.textContent='Tasks';if(!catalogTasks.length){drawerBody.innerHTML='<div class="empty"><div class="empty-inner"><p>No tasks yet.</p></div></div>';return;}for(const task of [...catalogTasks].reverse()){const b=document.createElement('button');b.className='drawer-card';b.innerHTML='<strong>'+esc(task.clarified_goal||task.goal||task.task_id||'Task')+'</strong><span>'+esc(String(task.status||'idle')+(task.coding_state?.current_file?' · '+task.coding_state.current_file:''))+'</span>';b.onclick=()=>{drawer.classList.remove('visible');vscode.postMessage({type:'session.select',threadId:String(task.thread_id||'')});};drawerBody.appendChild(b);}return;
    }
    drawerTitle.textContent='Skills';if(!catalogSkills.length){drawerBody.innerHTML='<div class="empty"><div class="empty-inner"><p>No skill catalog from service.</p></div></div>';return;}for(const skill of catalogSkills){const b=document.createElement('div');b.className='drawer-card';b.innerHTML='<strong>'+esc(skill.label||skill.name||skill.id||'Skill')+'</strong><span>'+esc(skill.description||skill.summary||'')+'</span>';drawerBody.appendChild(b);}
  }

  document.getElementById('newChat').onclick=()=>vscode.postMessage({type:'newChat'});
  document.getElementById('menuButton').onclick=(e)=>{e.stopPropagation();contextPopover.classList.remove('visible');menuPopover.classList.toggle('visible');};
  document.getElementById('reconnect').onclick=()=>vscode.postMessage({type:'reconnect'});
  document.getElementById('attach').onclick=()=>vscode.postMessage({type:'attachment.pick'});
  document.getElementById('contextButton').onclick=(e)=>{e.stopPropagation();menuPopover.classList.remove('visible');contextPopover.classList.toggle('visible');};
  document.getElementById('send').onclick=send;
  document.getElementById('mode').onchange=(e)=>{selectedMode=e.target.value;for(const c of timeline.querySelectorAll('[data-empty-mode]'))c.classList.toggle('selected',c.dataset.emptyMode===selectedMode);};
  document.getElementById('drawerBack').onclick=()=>drawer.classList.remove('visible');
  for(const row of document.querySelectorAll('[data-menu]'))row.onclick=()=>{const action=row.dataset.menu;hidePopovers();if(action==='new')vscode.postMessage({type:'newChat'});else if(['history','tasks','skills'].includes(action))renderDrawer(action);else if(action==='source')vscode.postMessage({type:'showSourceControl'});else if(action==='test')vscode.postMessage({type:'selfTest'});else if(action==='reconnect')vscode.postMessage({type:'reconnect'});else if(action==='settings')vscode.postMessage({type:'settings'});};
  input.addEventListener('input',resizeInput);input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});
  document.addEventListener('click',()=>hidePopovers());menuPopover.onclick=e=>e.stopPropagation();contextPopover.onclick=e=>e.stopPropagation();

  // Paste/drop image trực tiếp vào composer. File picker native vẫn là đường chuẩn
  // cho source files; webview chỉ gửi bytes khi user chủ động paste/drop.
  async function ingestFiles(files){for(const file of [...files].slice(0,8)){if(file.type.startsWith('image/')){const reader=new FileReader();reader.onload=()=>vscode.postMessage({type:'attachment.image',name:file.name||'image.png',dataUrl:String(reader.result||'')});reader.readAsDataURL(file);}}}
  input.addEventListener('paste',e=>{const files=[...(e.clipboardData?.files||[])];if(files.some(f=>f.type.startsWith('image/'))){e.preventDefault();void ingestFiles(files);}});
  let dragDepth=0;document.addEventListener('dragenter',e=>{if(e.dataTransfer?.types?.includes('Files')){dragDepth++;document.getElementById('dropOverlay').classList.add('visible');}});document.addEventListener('dragleave',()=>{dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)document.getElementById('dropOverlay').classList.remove('visible');});document.addEventListener('dragover',e=>{if(e.dataTransfer?.types?.includes('Files'))e.preventDefault();});document.addEventListener('drop',e=>{dragDepth=0;document.getElementById('dropOverlay').classList.remove('visible');if(e.dataTransfer?.files?.length){e.preventDefault();void ingestFiles(e.dataTransfer.files);}});

  window.addEventListener('message',({data:event})=>{
    if(event.type==='session.tabs'){sessions=Array.isArray(event.sessions)?event.sessions:[];activeThreadId=String(event.activeThreadId||'');renderSessions();return;}
    if(event.type==='chat.reset'){resetTimeline();activeThreadId=String(event.threadId||activeThreadId);activeTaskId=String(event.preserveTask||'');drawer.classList.remove('visible');return;}
    if(event.type==='connection'){
      const connected=event.state==='connected';const connecting=event.state==='connecting';document.getElementById('connection').classList.toggle('visible',!connected);document.getElementById('connectionText').textContent=connecting?'Connecting to Eris Service…':'Service offline';return;
    }
    if(event.type==='service.error'){return;}
    if(event.type==='attachment.add'){const item={...(event.attachment||{}),preview:event.preview||''};if(item.id){attachmentState.set(item.id,item);renderAttachments();}return;}
    if(event.type==='attachments.clear'){attachmentState.clear();renderAttachments();return;}
    if(event.type==='session.ready'){catalogTasks=Array.isArray(event.tasks)?event.tasks:catalogTasks;catalogSkills=Array.isArray(event.capabilities?.brain?.skills)?event.capabilities.brain.skills:catalogSkills;return;}
    if(event.type==='task.list'){catalogTasks=Array.isArray(event.tasks)?event.tasks:[];return;}
    if(event.type==='thread.history'){
      resetTimeline();const tasks=Array.isArray(event.tasks)?event.tasks:[];catalogTasks=[...new Map([...catalogTasks,...tasks].map(t=>[String(t?.task_id||''),t])).values()];const task=[...tasks].reverse().find(t=>['queued','running','paused','waiting_user','waiting_permission'].includes(String(t?.status||'')))??tasks.at(-1);if(task?.task_id)activeTaskId=String(task.task_id);for(const item of(event.events||[]))renderEvent(item);if(task&&(task.status==='waiting_user'||task.status==='waiting_permission')&&task.pending_interrupt)addInterrupt({taskId:task.task_id,payload:task.pending_interrupt,eventId:'restore:'+String(task.task_id)});ensureEmpty();return;
    }
    if(event.type==='task.detail'){if(event.task){catalogTasks=[...new Map([...catalogTasks,event.task].map(t=>[String(t?.task_id||''),t])).values()];}return;}
    if(event.type==='message.accepted'){activeTaskId=String(event.taskId||activeTaskId);return;}
    if(event.type==='client.error'||event.type==='error'){showNotice(event.message||event.code||'Eris service error');return;}
    renderEvent(event);
  });

  ensureEmpty();resizeInput();
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
