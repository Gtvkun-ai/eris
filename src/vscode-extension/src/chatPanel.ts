import * as crypto from 'node:crypto';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { captureIdeContext, currentWorkspaceRef } from './contextBridge';
import { WorkspaceDiffProvider } from './diffProvider';
import { openWorkspaceFile } from './editorBridge';
import { ErisClient } from './erisClient';
import { TerminalContextObserver } from './terminalObserver';
import { renderChatWebviewHtml } from './webviewHtml';

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
const NEW_SESSION_LABEL = 'Phiên mới';
const PREVIOUS_SESSION_LABEL = 'Phiên trước';

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
    view.description = 'Trợ lý lập trình Eris';

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
    void this.postComposerContext();

    // Mở Sidebar không được đánh thức full Eris. Nếu client đã connected từ một
    // tác vụ khác thì hydrate history bình thường; còn disconnected là trạng thái
    // dormant hợp lệ. Lần gửi message đầu tiên mới gọi connect() on-demand.
    if (this.client.connectionState === 'connected') {
      void this.hydrateRemoteState();
    }
  }

  private async hydrateRemoteState(): Promise<void> {
    try {
      await this.client.createThread(this.threadId);
      await this.client.requestThreadHistory(this.threadId);
      await this.client.requestTasks();
    } catch (error) {
      // Hydrate chỉ là tiện ích khi backend đã sẵn sàng. UI local vẫn phải mở
      // được kể cả service vừa tắt giữa chừng.
      await this.post({ type: 'service.error', message: String(error) });
    }
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
    if (this.client.connectionState === 'connected') {
      void this.client.createThread(this.threadId).catch(() => undefined);
    }
  }

  /**
   * Gửi feedback ẩn danh từ hệ thống (LSP diagnostics self-healing) về agent.
   */
  async sendSystemFeedback(content: string): Promise<void> {
    if (!content.trim()) return;
    // LSP self-healing là background assist. Nó không có quyền tự bật Eris chỉ
    // vì user vừa gõ/sửa một file khi chưa dùng coding agent.
    if (this.client.connectionState !== 'connected') return;
    try {
      const ideContext = await captureIdeContext(this.terminalObserver);
      await this.client.sendUserMessage(content, {
        threadId: this.threadId,
        taskMode: 'execute',
        context: ideContext,
      });
    } catch (error) {
      console.error('Lỗi khi gửi system feedback:', error);
    }
  }

  async selectTask(taskId: string, threadId: string): Promise<void> {
    const resolvedThread = String(threadId ?? '').trim();
    if (!resolvedThread) {
      return;
    }
    this.ensureSession(resolvedThread, PREVIOUS_SESSION_LABEL);
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
        title: String(item?.title ?? NEW_SESSION_LABEL).trim() || NEW_SESSION_LABEL,
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

  private createLocalSession(title = NEW_SESSION_LABEL): SessionTab {
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
    this.ensureSession(this.threadId, NEW_SESSION_LABEL);
  }

  private ensureSession(threadId: string, title = NEW_SESSION_LABEL): SessionTab {
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
      return NEW_SESSION_LABEL;
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
      if (this.client.connectionState === 'connected') {
        await this.client.createThread(this.threadId).catch(() => undefined);
      }
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

  /**
   * Composer chỉ cần biết "đang gắn context gì", không cần nhận nguyên source/diff.
   * Giữ dữ liệu nhạy cảm và payload lớn ở Extension Host; Webview chỉ thấy metadata.
   */
  private async postComposerContext(): Promise<void> {
    try {
      const raw = await captureIdeContext(this.terminalObserver);
      const current = raw.current && typeof raw.current === 'object' ? raw.current as Record<string, any> : {};
      const selection = raw.selection && typeof raw.selection === 'object' ? raw.selection as Record<string, any> : {};
      const problems = raw.problems && typeof raw.problems === 'object' ? raw.problems as Record<string, any> : {};
      const git = raw.git && typeof raw.git === 'object' ? raw.git as Record<string, any> : {};
      const openEditors = raw.openEditors && typeof raw.openEditors === 'object' ? raw.openEditors as Record<string, any> : {};
      const terminal = raw.terminal && typeof raw.terminal === 'object' ? raw.terminal as Record<string, any> : {};
      const workspace = raw.workspace && typeof raw.workspace === 'object' ? raw.workspace as Record<string, any> : {};
      const startLine = Number(selection?.start?.line ?? 0) || 0;
      const endLine = Number(selection?.end?.line ?? 0) || 0;
      const counts = problems.counts && typeof problems.counts === 'object' ? problems.counts as Record<string, any> : {};
      const folders = Array.isArray(workspace.folders) ? workspace.folders : [];

      await this.post({
        type: 'composer.context',
        context: {
          workspace: { names: folders.map((item: any) => String(item?.name ?? '')).filter(Boolean).slice(0, 4) },
          current: {
            available: Boolean(current.available),
            path: String(current.path ?? ''),
            languageId: String(current.languageId ?? ''),
            dirty: Boolean(current.dirty),
            cursor: current.cursor ?? {},
          },
          selection: {
            available: Boolean(selection.available),
            empty: selection.empty !== false,
            path: String(selection.path ?? ''),
            startLine,
            endLine,
            lineCount: startLine && endLine ? Math.max(1, endLine - startLine + 1) : 0,
          },
          problems: {
            error: Number(counts.error ?? 0) || 0,
            warning: Number(counts.warning ?? 0) || 0,
          },
          git: {
            available: Boolean(git.available),
            branch: String(git.branch ?? ''),
            changeCount: Array.isArray(git.changes) ? git.changes.length : 0,
          },
          terminal: { active: String(terminal.active ?? '') },
          openEditors: { count: Number(openEditors.count ?? 0) || 0 },
        },
      });
    } catch {
      // Context chip là affordance, không được phép làm hỏng chat khi Git/LSP lỗi.
      await this.post({ type: 'composer.context', context: {} });
    }
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
        if (session.title === NEW_SESSION_LABEL) {
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
        const autopilot = message.autopilot !== false;
        const requestedTaskMode = String(message.taskMode ?? 'auto');
        const taskMode: 'auto' | 'plan' | 'inspect' | 'execute' =
          requestedTaskMode === 'plan' ? 'plan'
          : requestedTaskMode === 'inspect' ? 'inspect'
          : requestedTaskMode === 'execute' ? 'execute'
          : 'auto';
        await this.client.sendUserMessage(content, {
          threadId: this.threadId,
          taskMode,
          autopilot,
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
      if (type === 'context.refresh') {
        await this.postComposerContext();
        return;
      }
      if (type === 'clipboard.write') {
        await vscode.env.clipboard.writeText(String(message.text ?? ''));
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
      openLabel: 'Đính kèm vào Eris',
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

    const targetThread = eventThread
      || (eventTaskId && eventTaskId === this.activeTaskId ? this.threadId : '')
      || (eventTaskId ? this.sessions.find((item) => item.taskId === eventTaskId)?.threadId ?? '' : '');

    if (targetThread) {
      const patch: Partial<SessionTab> = {};
      if (eventTaskId) {
        patch.taskId = eventTaskId;
      }
      if (type === 'message.user') {
        const content = String(event.payload?.content ?? '').trim();
        const current = this.ensureSession(targetThread);
        if (current.title === NEW_SESSION_LABEL && content) {
          patch.title = this.titleFromContent(content);
        }
        patch.status = 'running';
      } else if (type === 'interrupt.request') {
        patch.status = 'waiting';
      } else if (type === 'activity.end' || type === 'activity.update') {
        const status = String(event.payload?.status ?? '');
        if (status === 'failed' || status === 'stopped') {
          patch.status = 'failed';
        } else if (status === 'completed' || status === 'done') {
          patch.status = 'done';
        } else if (type === 'activity.end') {
          patch.status = 'idle';
        } else {
          patch.status = 'running';
        }
      } else if (type === 'activity.start' || type === 'coding.state') {
        patch.status = 'running';
      }
      if (Object.keys(patch).length) {
        this.touchSession(targetThread, patch);
      }
      if (targetThread !== this.threadId) {
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
    if (fallback && fallback !== NEW_SESSION_LABEL && fallback !== PREVIOUS_SESSION_LABEL) {
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
    // Presentation đã được tách khỏi Extension Host. chatPanel.ts chỉ còn
    // orchestration/protocol, không chứa hàng nghìn dòng CSS/DOM runtime nữa.
    return renderChatWebviewHtml(webview, this.extensionUri);
  }

  dispose(): void {
    this.clearViewDisposables();
    while (this.disposables.length) {
      this.disposables.pop()?.dispose();
    }
    this.view = undefined;
  }
}
