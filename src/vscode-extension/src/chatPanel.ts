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

const SESSION_KEY = 'eris.openSessions.v4';
const LEGACY_SESSION_KEY = 'eris.openSessions.v3';
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
    const persisted = extensionContext.workspaceState.get<string>(CURRENT_THREAD_KEY, '').trim();
    this.sessions = this.loadSessions(persisted);
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
    // Khi user mở session mới, task terminal ở background chuyển về History thay
    // vì tiếp tục chiếm chỗ trên tab bar như các build 0.7.x.
    this.sessions = this.sessions.filter((item) => !['done', 'failed'].includes(item.status));
    const session = this.createLocalSession();
    this.threadId = session.threadId;
    this.activeTaskId = '';
    this.ensureSessionLimit();
    this.persistSessions();
    void this.extensionContext.workspaceState.update(CURRENT_THREAD_KEY, this.threadId);
    void this.postSessions();
    void this.post({ type: 'chat.reset', threadId: this.threadId, reason: 'new' });
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

  private loadSessions(preferredThreadId = ''): SessionTab[] {
    // Chỉ restore tab nền còn sống. Tab done/failed cũ được giữ trong backend/history
    // nhưng không dồn trở lại thanh tab mỗi lần reconnect/reload. Tab terminal đang
    // được user đứng ở đó vẫn được giữ để họ xem kết quả/lỗi nếu muốn.
    const current = this.extensionContext.workspaceState.get<any[]>(SESSION_KEY, []);
    const legacy = this.extensionContext.workspaceState.get<any[]>(LEGACY_SESSION_KEY, []);
    const raw = Array.isArray(current) && current.length ? current : legacy;
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
    const openSessions = sessions.filter((item) =>
      item.threadId === preferredThreadId || !['done', 'failed'].includes(item.status),
    );
    return openSessions.slice(-MAX_OPEN_SESSIONS);
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
    await this.post({ type: 'chat.reset', threadId: this.threadId, preserveTask: this.activeTaskId, reason: 'select' });
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
      await this.post({ type: 'chat.reset', threadId: this.threadId, reason: 'new' });
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
        const rawContent = String(message.content ?? '').trim();
        const attachmentIds: string[] = Array.isArray(message.attachmentIds) ? message.attachmentIds.map((value: unknown) => String(value)) : [];
        if (!rawContent && !attachmentIds.length) {
          return;
        }
        // Kiro-style composer cho phép gửi riêng ảnh/file. Backend vẫn cần một
        // user turn có text, nên dùng instruction trung tính thay vì chặn Send.
        const content = rawContent || 'Hãy xem các tệp hoặc ảnh đính kèm và phản hồi theo ngữ cảnh hiện tại.';
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

        context.webaiModel = String(message.model ?? '');
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
    :root {
      color-scheme: light dark;
      --accent: var(--vscode-focusBorder);
      --border: var(--vscode-widget-border, var(--vscode-panel-border));
      --muted: var(--vscode-descriptionForeground);
      --bg: var(--vscode-sideBar-background);
      --input-bg: var(--vscode-input-background);
      --fast: 120ms;
      --normal: 180ms;
      --ease: cubic-bezier(.2,.75,.25,1);
    }
    *, *::before, *::after { box-sizing: border-box; }
    html, body { width: 100%; height: 100%; margin: 0; }
    body { overflow: hidden; color: var(--vscode-foreground); background: var(--bg); font: 13px/1.5 var(--vscode-font-family); }
    button, select, input, textarea { font: inherit; color: inherit; }
    button { cursor: pointer; }
    .shell { height: 100vh; display: grid; grid-template-rows: auto auto minmax(0,1fr) auto; }

    /* Session tabs */
    .session-strip { display: flex; align-items: center; gap: 4px; padding: 4px 6px 3px; border-bottom: 1px solid var(--border); min-height: 36px; }
    .session-tabs-wrap { position: relative; min-width: 0; flex: 1; overflow: hidden; }
    .session-tabs { display: flex; gap: 3px; overflow: auto hidden; scrollbar-width: none; scroll-behavior: smooth; }
    .session-tabs::-webkit-scrollbar { display: none; }
    .session-indicator { position: absolute; bottom: 0; left: 0; height: 2px; width: 0; border-radius: 999px; background: var(--accent); transition: transform var(--normal) var(--ease), width var(--normal) var(--ease), opacity var(--fast) ease; opacity: 0; pointer-events: none; }
    .session-tab { position: relative; flex: none; max-width: 150px; height: 28px; display: flex; align-items: center; gap: 6px; padding: 0 7px; border: 0; border-radius: 6px; background: transparent; color: var(--muted); transition: background var(--fast) ease, color var(--fast) ease; }
    .session-tab:hover { background: var(--vscode-toolbar-hoverBackground); color: var(--vscode-foreground); }
    .session-tab.active { background: color-mix(in srgb, var(--vscode-toolbar-hoverBackground) 68%, transparent); color: var(--vscode-foreground); }
    .session-tab.tab-enter { animation: tabIn var(--normal) var(--ease) both; }
    .session-tab.tab-closing { pointer-events: none; opacity: 0; transform: scale(.94); transition: opacity var(--fast) ease, transform var(--fast) ease; }
    .session-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
    .session-state { width: 6px; height: 6px; flex: none; border-radius: 50%; background: var(--muted); opacity: .4; }
    .session-state.running { background: var(--vscode-progressBar-background); opacity: 1; animation: pulse 1.8s ease-in-out infinite; }
    .session-state.waiting { background: var(--vscode-editorWarning-foreground); opacity: 1; }
    .session-state.done { background: var(--vscode-testing-iconPassed); opacity: .9; }
    .session-state.failed { background: var(--vscode-testing-iconFailed); opacity: .9; }
    .close-tab { flex: none; border: 0; padding: 0; width: 15px; height: 15px; line-height: 13px; border-radius: 4px; background: transparent; color: var(--muted); opacity: 0; transition: opacity var(--fast) ease, background var(--fast) ease; }
    .session-tab:hover .close-tab, .session-tab.active .close-tab { opacity: .72; }
    .close-tab:hover { background: var(--vscode-toolbar-hoverBackground); opacity: 1; }
    .icon-btn { flex: none; width: 27px; height: 27px; display: grid; place-items: center; padding: 0; border: 0; border-radius: 6px; background: transparent; color: var(--muted); font-size: 15px; transition: background var(--fast) ease, color var(--fast) ease; }
    .icon-btn:hover { background: var(--vscode-toolbar-hoverBackground); color: var(--vscode-foreground); }

    /* Connection */
    .connection { max-height: 0; opacity: 0; overflow: hidden; display: flex; align-items: center; gap: 7px; padding: 0 9px; color: var(--muted); font-size: 11px; border-bottom: 0 solid transparent; transform: translateY(-3px); transition: max-height var(--normal) var(--ease), opacity var(--fast) ease, transform var(--normal) var(--ease), padding var(--normal) var(--ease); }
    .connection.visible { max-height: 32px; opacity: 1; padding: 4px 9px 5px; border-bottom-width: 1px; border-bottom-color: var(--border); transform: none; }
    .connection .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--vscode-testing-iconFailed); }
    .connection.connecting .dot { background: var(--vscode-progressBar-background); animation: pulse 1.4s ease-in-out infinite; }
    .connection button { margin-left: auto; border: 0; padding: 2px 4px; background: transparent; color: var(--vscode-textLink-foreground); }
    .connection button:hover { text-decoration: underline; }

    /* Layout */
    .viewport { min-height: 0; position: relative; overflow: hidden; }
    .chat { height: 100%; display: flex; flex-direction: column; min-height: 0; }
    .timeline { min-height: 0; flex: 1; overflow-y: auto; padding: 16px 12px 24px; }
    .timeline.anim-left { animation: slideInLeft var(--normal) var(--ease) both; }
    .timeline.anim-right { animation: slideInRight var(--normal) var(--ease) both; }

    /* Chat bubbles */
    .msg { display: flex; gap: 9px; margin-bottom: 16px; animation: msgIn var(--fast) var(--ease) both; }
    .msg-user { flex-direction: row-reverse; }
    .msg-assistant { flex-direction: row; align-items: flex-start; }
    .avatar { flex: none; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; font-size: 11px; font-weight: 700; background: color-mix(in srgb, var(--accent) 18%, transparent); color: var(--accent); border: 1px solid color-mix(in srgb, var(--accent) 28%, transparent); margin-top: 2px; }
    .avatar-spacer { flex: none; width: 26px; }
    .msg-body { min-width: 0; max-width: calc(100% - 40px); display: flex; flex-direction: column; gap: 5px; }
    .msg-user .msg-body { align-items: flex-end; }
    .msg-assistant .msg-body { align-items: flex-start; }
    .msg-role { font-size: 10px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); }
    .bubble { padding: 9px 12px; border-radius: 14px; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.55; font-size: 13px; }
    .msg-user .bubble { background: color-mix(in srgb, var(--accent) 12%, var(--input-bg)); border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--border)); border-bottom-right-radius: 4px; }
    .msg-assistant .bubble { background: var(--vscode-editor-background); border: 1px solid var(--border); border-bottom-left-radius: 4px; }
    .bubble:empty { display: none; }
    .bubble.streaming::after { content: '\u2588'; display: inline-block; margin-left: 1px; color: var(--accent); animation: blink 1s steps(2,end) infinite; }
    .msg-attachments { display: flex; flex-wrap: wrap; gap: 4px; }
    .attach-chip-sm { display: flex; align-items: center; gap: 4px; padding: 2px 7px; border: 1px solid var(--border); border-radius: 6px; background: var(--vscode-editor-background); font-size: 10px; color: var(--muted); }

    /* Activity feed (replaces work-card) */
    .activity-feed { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; background: color-mix(in srgb, var(--vscode-editor-background) 55%, transparent); font-size: 11px; width: 100%; }
    .feed-summary { display: flex; align-items: center; gap: 6px; padding: 6px 9px; cursor: pointer; color: var(--muted); list-style: none; user-select: none; }
    .feed-summary::-webkit-details-marker { display: none; }
    .feed-summary:hover { background: var(--vscode-toolbar-hoverBackground); color: var(--vscode-foreground); }
    .feed-dot { width: 6px; height: 6px; flex: none; border-radius: 50%; background: var(--vscode-progressBar-background); animation: pulse 1.6s ease-in-out infinite; }
    .activity-feed.done .feed-dot { background: var(--vscode-testing-iconPassed); animation: none; }
    .activity-feed.failed .feed-dot { background: var(--vscode-testing-iconFailed); animation: none; }
    .feed-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .feed-count { flex: none; min-width: 16px; padding: 0 3px; border-radius: 999px; background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); text-align: center; font-size: 9px; }
    .feed-count:empty { display: none; }
    .feed-rows { border-top: 1px solid var(--border); padding: 5px 8px 7px; display: flex; flex-direction: column; gap: 2px; }
    .feed-row { display: flex; gap: 6px; color: var(--muted); padding: 1px 2px; animation: rowIn var(--fast) var(--ease) both; }
    .feed-row .fmark { width: 12px; text-align: center; flex: none; font-size: 10px; }
    .feed-row .ftext { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }

    /* Reasoning strip */
    .reasoning-block { border-left: 2px solid color-mix(in srgb, var(--accent) 38%, transparent); padding: 5px 10px; background: color-mix(in srgb, var(--accent) 5%, transparent); border-radius: 0 6px 6px 0; font-size: 11px; color: var(--muted); animation: msgIn var(--fast) var(--ease) both; width: 100%; }
    .reasoning-label { font-size: 9px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; color: color-mix(in srgb, var(--accent) 65%, var(--muted)); margin-bottom: 2px; display: block; }
    .reasoning-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.4; }

    /* Task controls */
    .task-controls { display: flex; flex-wrap: wrap; gap: 3px; }
    .ctrl-btn { border: 0; border-radius: 5px; padding: 3px 7px; background: transparent; color: var(--muted); font-size: 10px; transition: background var(--fast) ease, color var(--fast) ease; }
    .ctrl-btn:hover { color: var(--vscode-foreground); background: var(--vscode-toolbar-hoverBackground); }

    /* Interrupt */
    .interrupt { margin: 2px 0 14px; border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; background: var(--vscode-editor-background); animation: msgIn var(--fast) var(--ease) both; }
    .interrupt h3 { margin: 0 0 4px; font-size: 12px; }
    .interrupt p { margin: 0 0 8px; color: var(--muted); font-size: 10px; }
    .choices { display: grid; gap: 5px; }
    .choice { text-align: left; border: 1px solid var(--border); background: transparent; border-radius: 7px; padding: 6px 8px; transition: background var(--fast) ease, border-color var(--fast) ease; }
    .choice:hover { background: var(--vscode-toolbar-hoverBackground); border-color: color-mix(in srgb, var(--accent) 50%, var(--border)); }
    .choice strong, .choice span { display: block; }
    .choice span { margin-top: 2px; color: var(--muted); font-size: 10px; }
    .other-row { display: flex; gap: 5px; margin-top: 4px; }
    .other-row input { min-width: 0; flex: 1; background: var(--input-bg); color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border, var(--border)); border-radius: 6px; padding: 5px 7px; outline: 0; }
    .ghost-btn { border: 0; padding: 4px 8px; border-radius: 5px; background: transparent; color: var(--muted); transition: background var(--fast) ease, color var(--fast) ease; }
    .ghost-btn:hover { background: var(--vscode-toolbar-hoverBackground); color: var(--vscode-foreground); }

    /* Artifact */
    .artifact { margin: 2px 0 10px; border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; background: var(--vscode-editor-background); animation: msgIn var(--fast) var(--ease) both; font-size: 11px; }
    .artifact-head { display: flex; align-items: center; gap: 6px; min-width: 0; margin-bottom: 6px; }
    .pill { flex: none; padding: 1px 5px; border: 1px solid var(--border); border-radius: 999px; color: var(--muted); font-size: 9px; }
    .artifact-head code { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--vscode-editor-font-family); }
    .artifact-actions { display: flex; gap: 4px; }
    .artifact-actions button { border: 1px solid var(--border); background: transparent; border-radius: 5px; padding: 4px 7px; font-size: 10px; transition: background var(--fast) ease; }
    .artifact-actions button:hover { background: var(--vscode-toolbar-hoverBackground); }

    /* Empty state */
    .empty { min-height: 100%; display: grid; place-items: center; padding: 20px 8px; }
    .empty-inner { width: 100%; max-width: 310px; text-align: center; animation: fadeUp 240ms var(--ease) both; }
    .spark { width: 30px; height: 30px; margin: 0 auto 10px; display: grid; place-items: center; font-size: 20px; color: var(--accent); filter: drop-shadow(0 0 8px color-mix(in srgb, var(--accent) 28%, transparent)); animation: float 2.8s ease-in-out infinite; }
    .empty h2 { margin: 0; font-size: 15px; font-weight: 650; }
    .empty p { max-width: 270px; margin: 5px auto 16px; color: var(--muted); font-size: 11px; }
    .mode-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .mode-card { position: relative; text-align: left; border: 1px solid var(--border); border-radius: 9px; padding: 10px; background: color-mix(in srgb, var(--vscode-editor-background) 80%, transparent); transition: border-color var(--fast) ease, transform var(--fast) ease; }
    .mode-card:hover { border-color: color-mix(in srgb, var(--accent) 60%, var(--border)); transform: translateY(-1px); }
    .mode-card.selected { border-color: var(--accent); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 22%, transparent); }
    .mode-card strong { display: block; font-size: 11px; }
    .mode-card span { display: block; margin-top: 3px; color: var(--muted); font-size: 10px; line-height: 1.35; }

    /* Notice */
    .notice { pointer-events: none; opacity: 0; transform: translateY(4px); margin: 0 12px 8px; max-height: 0; overflow: hidden; padding: 0 8px; border-radius: 7px; background: var(--vscode-inputValidation-errorBackground); border: 0 solid var(--vscode-inputValidation-errorBorder); color: var(--vscode-inputValidation-errorForeground); font-size: 10px; transition: opacity var(--fast) ease, transform var(--fast) ease, max-height var(--normal) var(--ease), padding var(--normal) var(--ease); }
    .notice.visible { pointer-events: auto; opacity: 1; transform: none; max-height: 72px; padding: 6px 8px; border-width: 1px; }

    /* Composer */
    .composer-wrap { position: relative; padding: 7px 8px 9px; border-top: 1px solid var(--border); background: var(--bg); }
    .attachments { display: flex; gap: 5px; overflow: auto hidden; max-height: 0; opacity: 0; padding: 0 1px; scrollbar-width: none; transition: max-height var(--normal) var(--ease), opacity var(--fast) ease, padding var(--normal) var(--ease); }
    .attachments.visible { max-height: 38px; opacity: 1; padding-bottom: 6px; }
    .attachments::-webkit-scrollbar { display: none; }
    .attach-chip { flex: none; max-width: 190px; display: flex; align-items: center; gap: 5px; padding: 3px 6px; border: 1px solid var(--border); border-radius: 6px; background: var(--vscode-editor-background); font-size: 10px; animation: chipIn var(--fast) var(--ease) both; }
    .attach-chip.removing { animation: chipOut 110ms ease forwards; }
    .attach-chip img { width: 18px; height: 18px; object-fit: cover; border-radius: 3px; }
    .attach-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .attach-remove { border: 0; padding: 0; background: transparent; color: var(--muted); }
    .composer-box { border: 1px solid var(--vscode-input-border, var(--border)); border-radius: 10px; background: var(--input-bg); overflow: hidden; transition: border-color var(--fast) ease, box-shadow var(--fast) ease; }
    .composer-box:focus-within { border-color: var(--vscode-focusBorder); box-shadow: 0 0 0 1px color-mix(in srgb, var(--vscode-focusBorder) 18%, transparent); }
    textarea { width: 100%; min-height: 40px; max-height: 140px; resize: none; overflow: auto; padding: 8px 9px 1px; color: var(--vscode-input-foreground); background: transparent; border: 0; outline: 0; }
    .composer-bar { display: flex; align-items: center; gap: 3px; padding: 3px 5px 5px; }
    .c-tool { height: 26px; min-width: 26px; border: 0; border-radius: 5px; padding: 0 6px; background: transparent; color: var(--muted); font-size: 11px; transition: background var(--fast) ease, color var(--fast) ease; }
    .c-tool:hover { color: var(--vscode-foreground); background: var(--vscode-toolbar-hoverBackground); }
    .bar-select { border: 0; border-radius: 5px; padding: 3px 5px; color: var(--muted); background: transparent; font-size: 10px; cursor: pointer; transition: background var(--fast) ease, color var(--fast) ease; }
    .bar-select:hover { background: var(--vscode-toolbar-hoverBackground); color: var(--vscode-foreground); }
    .send { margin-left: auto; width: 28px; height: 28px; display: grid; place-items: center; border: 0; border-radius: 8px; color: var(--vscode-disabledForeground); background: color-mix(in srgb, var(--vscode-button-background) 28%, transparent); font-size: 15px; transform: scale(.96); transition: background var(--fast) ease, color var(--fast) ease, transform var(--fast) ease, box-shadow var(--fast) ease; }
    .send.ready { color: var(--vscode-button-foreground); background: var(--vscode-button-background); transform: none; box-shadow: 0 2px 8px color-mix(in srgb, var(--vscode-button-background) 20%, transparent); }
    .send.ready:hover { background: var(--vscode-button-hoverBackground); transform: translateY(-1px); }

    /* Popovers */
    .context-popover, .menu-popover { visibility: hidden; pointer-events: none; opacity: 0; transform: translateY(5px) scale(.98); position: absolute; z-index: 20; left: 8px; bottom: 51px; width: min(275px, calc(100% - 16px)); border: 1px solid var(--border); border-radius: 8px; padding: 6px; background: var(--vscode-menu-background, var(--vscode-editor-background)); box-shadow: 0 8px 28px rgba(0,0,0,.25); transition: opacity var(--fast) ease, transform var(--fast) ease, visibility 0s linear var(--fast); }
    .context-popover.visible, .menu-popover.visible { visibility: visible; pointer-events: auto; opacity: 1; transform: none; transition-delay: 0s; }
    .context-row, .menu-row { width: 100%; display: flex; align-items: center; gap: 8px; border: 0; border-radius: 5px; padding: 6px; background: transparent; text-align: left; font-size: 11px; }
    .context-row:hover, .menu-row:hover { background: var(--vscode-list-hoverBackground); }
    .context-row input { margin: 0; }
    .menu-popover { left: auto; right: 7px; bottom: auto; top: 34px; width: 190px; transform-origin: top right; }
    .menu-sep { height: 1px; margin: 4px 2px; background: var(--border); }

    /* Drawer */
    .drawer { visibility: hidden; pointer-events: none; position: absolute; inset: 0; z-index: 15; display: flex; flex-direction: column; background: var(--bg); opacity: 0; transform: translateX(12px); transition: opacity var(--normal) ease, transform var(--normal) var(--ease), visibility 0s linear var(--normal); }
    .drawer.visible { visibility: visible; pointer-events: auto; opacity: 1; transform: none; transition-delay: 0s; }
    .drawer-head { display: flex; align-items: center; gap: 8px; min-height: 38px; padding: 5px 9px; border-bottom: 1px solid var(--border); }
    .drawer-head strong { flex: 1; }
    .drawer-body { min-height: 0; flex: 1; overflow: auto; padding: 7px; }
    .drawer-card { width: 100%; text-align: left; border: 1px solid transparent; border-radius: 7px; padding: 8px; margin-bottom: 2px; background: transparent; animation: rowIn var(--fast) var(--ease) both; }
    .drawer-card:hover { background: var(--vscode-list-hoverBackground); }
    .drawer-card strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
    .drawer-card span { display: block; margin-top: 2px; color: var(--muted); font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

    .drop-overlay { visibility: hidden; opacity: 0; transform: scale(.985); position: absolute; inset: 8px; z-index: 40; display: grid; place-items: center; border: 1px dashed var(--vscode-focusBorder); border-radius: 10px; background: color-mix(in srgb, var(--bg) 88%, transparent); font-size: 12px; pointer-events: none; transition: opacity var(--fast) ease, transform var(--fast) ease, visibility 0s linear var(--fast); }
    .drop-overlay.visible { visibility: visible; opacity: 1; transform: none; transition-delay: 0s; }

    @keyframes tabIn { from { opacity: 0; transform: translateY(-3px) scale(.97); } }
    @keyframes msgIn { from { opacity: 0; transform: translateY(5px); } }
    @keyframes rowIn { from { opacity: 0; transform: translateX(-4px); } }
    @keyframes chipIn { from { opacity: 0; transform: scale(.94); } }
    @keyframes chipOut { to { opacity: 0; transform: scale(.92); max-width: 0; padding-left: 0; padding-right: 0; margin: 0; } }
    @keyframes fadeUp { from { opacity: 0; transform: translateY(6px) scale(.99); } }
    @keyframes float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-3px); } }
    @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .45; } }
    @keyframes blink { 0%,45% { opacity: .8; } 46%,100% { opacity: .15; } }
    @keyframes slideInLeft { from { opacity: 0; transform: translateX(-10px); } }
    @keyframes slideInRight { from { opacity: 0; transform: translateX(10px); } }
    @media (max-width: 280px) { .mode-cards { grid-template-columns: 1fr; } .session-tab { max-width: 110px; } }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: .001ms !important; transition-duration: .001ms !important; } }
  </style>
</head>
<body>
<div class="shell">
  <div class="session-strip">
    <div class="session-tabs-wrap">
      <div id="sessionTabs" class="session-tabs"></div>
      <span id="sessionIndicator" class="session-indicator"></span>
    </div>
    <button id="newChat" class="icon-btn" title="New Session">\uFF0B</button>
    <button id="menuButton" class="icon-btn" title="More">\u22EF</button>
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
      <div class="drawer-head"><button id="drawerBack" class="icon-btn">\u2039</button><strong id="drawerTitle">History</strong></div>
      <div id="drawerBody" class="drawer-body"></div>
    </section>
    <div id="menuPopover" class="menu-popover">
      <button class="menu-row" data-menu="new">\uFF0B New Session</button>
      <button class="menu-row" data-menu="history">\u25F7 Recent chats</button>
      <button class="menu-row" data-menu="tasks">\u2713 Tasks</button>
      <button class="menu-row" data-menu="skills">\u2318 Skills</button>
      <div class="menu-sep"></div>
      <button class="menu-row" data-menu="source">\u2341 Source Control</button>
      <button class="menu-row" data-menu="test">\u2697 Run Self Test</button>
      <button class="menu-row" data-menu="reconnect">\u21BB Reconnect</button>
      <button class="menu-row" data-menu="settings">\u2699 Settings</button>
    </div>
    <div id="dropOverlay" class="drop-overlay">Drop files or images to attach</div>
  </main>
  <footer class="composer-wrap">
    <div id="attachments" class="attachments"></div>
    <div class="composer-box">
      <textarea id="input" rows="1" placeholder="Ask Eris about your code\u2026"></textarea>
      <div class="composer-bar">
        <button id="attach" class="c-tool" title="Attach files or images">\uFF0B</button>
        <button id="contextButton" class="c-tool" title="Context">#</button>
        <select id="mode" class="bar-select" title="Agent mode"><option value="execute">Agent</option><option value="inspect">Inspect only</option></select>
        <select id="modelSelect" class="bar-select" title="WebAI model">
          <option value="gemini-3-flash">Flash</option>
          <option value="gemini-3-pro">Pro</option>
          <option value="gemini-3-flash-thinking">Thinking</option>
        </select>
        <button id="send" class="send" title="Send">\u2191</button>
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

let activeThreadId='';
let activeTaskId='';
let sessions=[];
let catalogTasks=[];
let catalogSkills=[];
let selectedMode='execute';
let selectedModel=(vscode.getState()&&vscode.getState().model)||'gemini-3-flash';
const rendered=new Set();
const pendingInterrupts=new Set();
const attachmentState=new Map();
const taskGroups=new Map();
const knownTabs=new Set();
let pendingSwitchDirection=0;
let awaitingThreadHistory=false;
let deferredEvents=[];

modelSelect.value=selectedModel;
modelSelect.onchange=function(e){selectedModel=e.target.value;vscode.setState(Object.assign({},vscode.getState(),{model:selectedModel}));};

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
  sessionTabs.innerHTML='';
  var liveIds=new Set(sessions.map(function(s){return String(s.threadId||'');}));
  for(var k of [...knownTabs])if(!liveIds.has(k))knownTabs.delete(k);
  for(var session of sessions){
    var tab=document.createElement('button');
    var isFresh=!knownTabs.has(session.threadId);
    tab.className='session-tab'+(session.threadId===activeThreadId?' active':'')+(isFresh?' tab-enter':'');
    tab.dataset.threadId=session.threadId;
    tab.title=session.title||'New Session';
    var dot=document.createElement('span');dot.className='session-state '+String(session.status||'idle');
    var title=document.createElement('span');title.className='session-title';title.textContent=session.title||'New Session';
    var close=document.createElement('button');close.className='close-tab';close.textContent='\xD7';close.title='Close';
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

function emptyHtml(){return '<div class="empty" id="chatEmpty"><div class="empty-inner"><div class="spark">\u2726</div><h2>What are we building today?</h2><p>Chat about code, inspect a problem, or let Eris work through a task.</p><div class="mode-cards"><button class="mode-card" data-empty-mode="inspect"><strong>Quick Chat</strong><span>Explore and inspect without changing files.</span></button><button class="mode-card selected" data-empty-mode="execute"><strong>Agent Task</strong><span>Plan, edit, run tests and iterate autonomously.</span></button></div></div></div>';}
function ensureEmpty(){if(!timeline.children.length){timeline.innerHTML=emptyHtml();bindEmptyModes();}}
function removeEmpty(){var e=document.getElementById('chatEmpty');if(e)e.remove();}
function bindEmptyModes(){for(var card of timeline.querySelectorAll('[data-empty-mode]'))(function(c){c.onclick=function(){selectedMode=c.dataset.emptyMode||'execute';document.getElementById('mode').value=selectedMode;for(var x of timeline.querySelectorAll('[data-empty-mode]'))x.classList.toggle('selected',x===c);input.focus();};})(card);}
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
  var role=document.createElement('div');role.className='msg-role';role.textContent='You';
  var bubble=document.createElement('div');bubble.className='bubble';bubble.textContent=String(content==null?'':content);
  body.append(role,bubble);
  if(Array.isArray(attachments)&&attachments.length){
    var row=document.createElement('div');row.className='msg-attachments';
    for(var item of attachments.slice(0,8)){
      var chip=document.createElement('div');chip.className='attach-chip-sm';
      chip.textContent=(String(item.kind||'')==='image'?'\u25A7 ':'\u25A4 ')+(item.name||item.relativePath||'attachment');
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
  var avatar=document.createElement('div');avatar.className='avatar';avatar.textContent='E';
  var body=document.createElement('div');body.className='msg-body';
  var role=document.createElement('div');role.className='msg-role';role.textContent='Eris';
  /* reasoning */
  var reasoning=document.createElement('div');reasoning.className='reasoning-block';reasoning.style.display='none';
  var rLabel=document.createElement('span');rLabel.className='reasoning-label';rLabel.textContent='Thinking';
  var rText=document.createElement('div');rText.className='reasoning-text';
  reasoning.append(rLabel,rText);
  /* bubble — hidden until text arrives (no empty black square) */
  var bubble=document.createElement('div');bubble.className='bubble';
  /* activity feed */
  var feed=document.createElement('details');feed.className='activity-feed';feed.style.display='none';feed.open=true;
  var feedSum=document.createElement('summary');feedSum.className='feed-summary';
  feedSum.innerHTML='<span class="feed-dot"></span><span class="feed-label">Working\u2026</span><span class="feed-count"></span>';
  var feedRows=document.createElement('div');feedRows.className='feed-rows';
  feed.append(feedSum,feedRows);
  /* controls — hidden by default, shown only when task is running */
  var controls=document.createElement('div');controls.className='task-controls';controls.style.display='none';
  controls.innerHTML='<button class="ctrl-btn" data-control="pause">Pause</button><button class="ctrl-btn" data-control="resume">Resume</button><button class="ctrl-btn" data-control="rollback">Rollback</button><button class="ctrl-btn" data-control="stop">Stop</button>';
  for(var btn of controls.querySelectorAll('[data-control]'))(function(b,k){b.onclick=function(){vscode.postMessage({type:'task.control',taskId:k,action:b.dataset.control});};})(btn,key);
  body.append(role,reasoning,bubble,feed,controls);
  group.append(avatar,body);
  timeline.appendChild(group);
  var entry={groupEl:group,bubbleEl:bubble,feedEl:feed,feedRowsEl:feedRows,feedLabelEl:feedSum.querySelector('.feed-label'),feedCountEl:feedSum.querySelector('.feed-count'),reasoningEl:reasoning,reasoningTextEl:rText,controlsEl:controls,rowCount:0};
  taskGroups.set(key,entry);
  scroll();
  return entry;
}

function addActivity(event){
  var p=event.payload||{};
  var taskId=String(event.taskId||activeTaskId||'');
  var label=String(p.label!=null?p.label:p.detail!=null?p.detail:event.type||'Working');
  var detail=String(p.detail!=null?p.detail:p.label!=null?p.label:'');
  var status=String(p.status!=null?p.status:(event.type==='activity.end'?'completed':'running'));
  var entry=getTaskGroup(taskId);
  entry.feedEl.style.display='';
  if(label)entry.feedLabelEl.textContent=clip(label,60);
  var done=status==='completed'||status==='done';
  var failed=status==='failed'||status==='stopped';
  entry.feedEl.classList.toggle('done',done);
  entry.feedEl.classList.toggle('failed',failed);
  entry.controlsEl.style.display=(done||failed)?'none':'flex';
  if(done||failed)entry.feedEl.open=false;
  if(detail){
    var row=document.createElement('div');row.className='feed-row';
    var mark=done?'\u2713':failed?'\xD7':'\xB7';
    row.innerHTML='<span class="fmark">'+mark+'</span><span class="ftext">'+esc(detail)+'</span>';
    entry.feedRowsEl.appendChild(row);
    while(entry.feedRowsEl.children.length>20)entry.feedRowsEl.firstChild.remove();
    entry.rowCount=entry.feedRowsEl.children.length;
    entry.feedCountEl.textContent=entry.rowCount?String(entry.rowCount):'';
  }
  scroll();
}

function mergeCoding(event){
  var p=event.payload||{};
  var taskId=String(event.taskId||activeTaskId||'');
  var title=p.current_action||p.next_action||p.phase||'Working';
  var file=p.current_file?(' \xB7 '+p.current_file):'';
  var status=p.status||'running';
  var entry=getTaskGroup(taskId);
  entry.feedEl.style.display='';
  entry.feedLabelEl.textContent=clip(String(title)+file,60);
  if(p.current_action||p.next_action){
    var parts=[p.current_action,p.next_action].filter(Boolean).join(' \u2192 ');
    entry.reasoningEl.style.display='';
    entry.reasoningTextEl.textContent=parts;
  }
  var done=status==='completed'||status==='done';
  var failed=status==='failed'||status==='stopped';
  entry.feedEl.classList.toggle('done',done);
  entry.feedEl.classList.toggle('failed',failed);
  entry.controlsEl.style.display=(done||failed)?'none':'flex';
}

function disableChoices(node){for(var c of node.querySelectorAll('button,input'))c.disabled=true;}
function addInterrupt(event){
  removeEmpty();
  var key=String(event.taskId!=null?event.taskId:activeTaskId!=null?activeTaskId:'');
  if(key&&pendingInterrupts.has(key))return;if(key)pendingInterrupts.add(key);
  var p=event.payload||{};
  var node=document.createElement('div');node.className='interrupt';
  node.innerHTML='<h3>'+esc(p.question||'Eris needs a decision')+'</h3><p>The task is checkpointed and will resume from here.</p><div class="choices" role="listbox"></div>';
  var choices=node.querySelector('.choices');
  for(var option of(p.options||[]))(function(opt){
    var b=document.createElement('button');b.className='choice';
    b.innerHTML='<strong>'+esc(opt.label!=null?opt.label:opt.id)+'</strong>'+(opt.description||opt.desc?'<span>'+esc(opt.description!=null?opt.description:opt.desc)+'</span>':'');
    b.onclick=function(){disableChoices(node);if(key)pendingInterrupts.delete(key);vscode.postMessage({type:'interrupt.resolve',taskId:event.taskId,response:{choiceId:String(opt.id!=null?opt.id:''),value:String(opt.value!=null?opt.value:opt.label!=null?opt.label:''),text:String(opt.label!=null?opt.label:'')}});};
    choices.appendChild(b);
  })(option);
  if(p.allowOther!==false){
    var row=document.createElement('div');row.className='other-row';
    var field=document.createElement('input');field.placeholder='Other direction\u2026';
    var sb=document.createElement('button');sb.className='ghost-btn';sb.textContent='Send';
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
  node.innerHTML='<div class="artifact-head"><span class="pill">Modified</span><code>'+esc(filePath)+'</code></div><div class="artifact-actions"><button data-action="open">Open</button><button data-action="diff">Diff</button></div>';
  node.querySelector('[data-action="open"]').onclick=function(){vscode.postMessage({type:'openArtifact',path:filePath});};
  node.querySelector('[data-action="diff"]').onclick=function(){vscode.postMessage({type:'openDiff',path:filePath,diff:String(p.diff!=null?p.diff:'')});};
  timeline.appendChild(node);scroll();
}
function addChangeSet(event){
  var p=event.payload||{};var id=String(p.changeSetId!=null?p.changeSetId:p.operationId!=null?p.operationId:'');if(!id)return;
  removeEmpty();var files=Array.isArray(p.files)?p.files:[];var status=String(p.status!=null?p.status:'pending');
  var node=document.createElement('div');node.className='artifact';node.dataset.changeSetId=id;
  node.innerHTML='<div class="artifact-head"><span class="pill">ChangeSet \xB7 '+esc(status)+'</span><code>'+esc(files.slice(0,3).join(' \xB7 ')||id)+'</code></div><div class="artifact-actions"><button data-action="accept">Accept</button><button data-action="revert">Revert</button></div>';
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
  var pill=node.querySelector('.pill');if(pill)pill.textContent='ChangeSet \xB7 '+String(p.status!=null?p.status:'updated');
  for(var b of node.querySelectorAll('button'))b.disabled=true;
}

function renderEvent(event){
  if(!event||!remember(event))return;
  if(event.taskId)activeTaskId=String(event.taskId);
  if(event.type==='message.user'){addUserMessage(event.payload&&event.payload.content!=null?event.payload.content:'',event.payload&&event.payload.attachments?event.payload.attachments:[]);return;}
  if(event.type==='message.assistant'){
    var entry=getTaskGroup(String(event.taskId||activeTaskId||'main'));
    entry.bubbleEl.textContent=String(event.payload&&event.payload.content!=null?event.payload.content:'');
    entry.bubbleEl.classList.remove('streaming');
    if(!entry.reasoningTextEl.textContent)entry.reasoningEl.style.display='none';
    return;
  }
  if(event.type==='message.assistant.delta'){
    removeEmpty();
    var dEntry=getTaskGroup(String(event.taskId||activeTaskId||'main'));
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
function send(){var content=input.value.trim();var ids=[...attachmentState.keys()];if(!content&&!ids.length)return;input.value='';resizeInput();hidePopovers();vscode.postMessage({type:'sendMessage',content:content,taskMode:document.getElementById('mode').value,model:selectedModel,attachmentIds:ids,contextKeys:contextKeys()});}
function hidePopovers(){menuPopover.classList.remove('visible');contextPopover.classList.remove('visible');}
function showNotice(message){notice.textContent=String(message||'');notice.classList.toggle('visible',Boolean(message));if(message)setTimeout(function(){notice.classList.remove('visible');},7000);}

function renderDrawer(kind){
  drawer.classList.add('visible');menuPopover.classList.remove('visible');drawerBody.innerHTML='';
  if(kind==='history'){
    drawerTitle.textContent='Recent chats';
    var byThread=new Map();
    for(var session of sessions)byThread.set(String(session.threadId||''),{threadId:String(session.threadId||''),title:session.title||'New Session',status:session.status||'idle',updatedAt:Number(session.updatedAt||0)});
    for(var task of catalogTasks){var tid=String(task.thread_id||task.threadId||'');if(!tid)continue;var ex=byThread.get(tid)||{};byThread.set(tid,{threadId:tid,title:ex.title||task.clarified_goal||task.goal||'Previous session',status:String(task.status||ex.status||'idle'),updatedAt:Math.max(Number(ex.updatedAt||0),Number(task.updated_at||0)*(Number(task.updated_at||0)<10000000000?1000:1))});}
    var history=[...byThread.values()].sort(function(a,b){return b.updatedAt-a.updatedAt;});
    if(!history.length){drawerBody.innerHTML='<div class="empty"><div class="empty-inner"><p>No previous chats.</p></div></div>';return;}
    for(var item of history)(function(i){var b=document.createElement('button');b.className='drawer-card';b.innerHTML='<strong>'+esc(i.title||'Previous session')+'</strong><span>'+esc(i.status||'idle')+'</span>';b.onclick=function(){drawer.classList.remove('visible');selectSessionFromUi(i.threadId);};drawerBody.appendChild(b);})(item);
    return;
  }
  if(kind==='tasks'){
    drawerTitle.textContent='Tasks';if(!catalogTasks.length){drawerBody.innerHTML='<div class="empty"><div class="empty-inner"><p>No tasks yet.</p></div></div>';return;}
    for(var t of [...catalogTasks].reverse())(function(task){var b=document.createElement('button');b.className='drawer-card';b.innerHTML='<strong>'+esc(task.clarified_goal||task.goal||task.task_id||'Task')+'</strong><span>'+esc(String(task.status||'idle')+(task.coding_state&&task.coding_state.current_file?' \xB7 '+task.coding_state.current_file:''))+'</span>';b.onclick=function(){drawer.classList.remove('visible');selectSessionFromUi(String(task.thread_id||''));};drawerBody.appendChild(b);})(t);
    return;
  }
  drawerTitle.textContent='Skills';if(!catalogSkills.length){drawerBody.innerHTML='<div class="empty"><div class="empty-inner"><p>No skill catalog from service.</p></div></div>';return;}
  for(var skill of catalogSkills){var b=document.createElement('div');b.className='drawer-card';b.innerHTML='<strong>'+esc(skill.label||skill.name||skill.id||'Skill')+'</strong><span>'+esc(skill.description||skill.summary||'')+'</span>';drawerBody.appendChild(b);}
}

document.getElementById('newChat').onclick=function(){vscode.postMessage({type:'newChat'});}
document.getElementById('menuButton').onclick=function(e){e.stopPropagation();contextPopover.classList.remove('visible');menuPopover.classList.toggle('visible');};
document.getElementById('reconnect').onclick=function(){vscode.postMessage({type:'reconnect'});};
document.getElementById('attach').onclick=function(){vscode.postMessage({type:'attachment.pick'});};
document.getElementById('contextButton').onclick=function(e){e.stopPropagation();menuPopover.classList.remove('visible');contextPopover.classList.toggle('visible');};
document.getElementById('send').onclick=send;
document.getElementById('mode').onchange=function(e){selectedMode=e.target.value;for(var c of timeline.querySelectorAll('[data-empty-mode]'))c.classList.toggle('selected',c.dataset.emptyMode===selectedMode);};
document.getElementById('drawerBack').onclick=function(){drawer.classList.remove('visible');};
for(var dmrow of document.querySelectorAll('[data-menu]'))(function(row){row.onclick=function(){var a=row.dataset.menu;hidePopovers();if(a==='new')vscode.postMessage({type:'newChat'});else if(a==='history'||a==='tasks'||a==='skills')renderDrawer(a);else if(a==='source')vscode.postMessage({type:'showSourceControl'});else if(a==='test')vscode.postMessage({type:'selfTest'});else if(a==='reconnect')vscode.postMessage({type:'reconnect'});else if(a==='settings')vscode.postMessage({type:'settings'});};})(dmrow);
input.addEventListener('input',resizeInput);
input.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});
document.addEventListener('click',function(){hidePopovers();});
menuPopover.onclick=function(e){e.stopPropagation();};
contextPopover.onclick=function(e){e.stopPropagation();};
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
  if(event.type==='connection'){var connected=event.state==='connected';var connecting=event.state==='connecting';connection.classList.toggle('visible',!connected);connection.classList.toggle('connecting',connecting);document.getElementById('connectionText').textContent=connecting?'Connecting to Eris Service\u2026':'Service offline';return;}
  if(event.type==='service.error'){return;}
  if(event.type==='attachment.add'){var att=Object.assign({},event.attachment||{},{preview:event.preview||''});if(att.id){attachmentState.set(att.id,att);renderAttachments();}return;}
  if(event.type==='attachments.clear'){attachmentState.clear();renderAttachments();return;}
  if(event.type==='session.ready'){catalogTasks=Array.isArray(event.tasks)?event.tasks:catalogTasks;catalogSkills=Array.isArray(event.capabilities&&event.capabilities.brain&&event.capabilities.brain.skills?event.capabilities.brain.skills:null)?event.capabilities.brain.skills:catalogSkills;return;}
  if(event.type==='task.list'){catalogTasks=Array.isArray(event.tasks)?event.tasks:[];return;}
  if(event.type==='thread.history'){renderHistory(event);return;}
  if(event.type==='task.detail'){if(event.task){catalogTasks=[...new Map([...catalogTasks,event.task].map(function(t){return[String(t&&t.task_id?t.task_id:''),t];})).values()];}return;}
  if(event.type==='message.accepted'){activeTaskId=String(event.taskId||activeTaskId);return;}
  if(event.type==='client.error'||event.type==='error'){showNotice(event.message||event.code||'Eris service error');return;}
  if(awaitingThreadHistory){deferredEvents.push(event);return;}
  renderEvent(event);
});

ensureEmpty();
resizeInput();
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
