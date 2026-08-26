import * as crypto from 'node:crypto';
import { execFile } from 'node:child_process';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { promisify } from 'node:util';
import { captureIdeContext } from './contextBridge';
import { recentlyModifiedFiles } from './editorBridge';
import { ErisObserverBridge } from './erisObserverBridge';
import { GitPilotRuntimeManager } from './gitPilotRuntimeManager';
import { TerminalContextObserver } from './terminalObserver';

const execFileAsync = promisify(execFile);
export type ConnectionState = 'disconnected' | 'connecting' | 'connected';
type JsonRecord = Record<string, any>;
type GitPilotSession = { sessionId: string; workspaceRoot: string; mode: 'github' | 'folder' };
type PendingApproval = { taskId: string; threadId: string; edits: ProposedEdit[]; answer: string };
type ProposedEdit = { path: string; content: string; kind?: string };
type ChangeSnapshot = { changeSetId: string; taskId: string; files: Array<{ path: string; existed: boolean; beforeBase64: string }> };

export class GitPilotClient implements vscode.Disposable {
  private state: ConnectionState = 'disconnected';
  private readonly eventEmitter = new vscode.EventEmitter<JsonRecord>();
  private readonly stateEmitter = new vscode.EventEmitter<ConnectionState>();
  private readonly sessions = new Map<string, GitPilotSession>();
  private readonly pending = new Map<string, PendingApproval>();
  private readonly taskThreads = new Map<string, string>();
  readonly onEvent = this.eventEmitter.event;
  readonly onStateChanged = this.stateEmitter.event;

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly runtime: GitPilotRuntimeManager,
    private readonly terminalObserver: TerminalContextObserver,
    private readonly erisBridge: ErisObserverBridge,
  ) {}

  get connectionState(): ConnectionState { return this.state; }

  async connect(force = false): Promise<void> {
    if (this.state === 'connected' && !force && await this.runtime.probe()) return;
    this.setState('connecting');
    try {
      await this.runtime.ensureStarted({ allowLaunch: true });
      if (!await this.runtime.probe()) throw new Error('GitPilot status probe failed.');
      this.setState('connected');
      this.eventEmitter.fire({ type: 'session.ready', sessionId: 'eris-code', tasks: this.readTasks() });
    } catch (error) {
      this.setState('disconnected');
      throw error;
    }
  }

  async createThread(threadId: string): Promise<void> {
    if (this.sessions.has(threadId)) return;
    await this.connect();
    const root = this.workspaceRoot();
    if (!root) throw new Error('Mở một workspace/folder trước khi dùng Eris Code.');
    const session = await this.startGitPilotSession(root);
    this.sessions.set(threadId, session);
  }

  async requestTasks(): Promise<void> {
    this.eventEmitter.fire({ type: 'task.list', tasks: this.readTasks() });
  }

  async requestTask(taskId: string): Promise<void> {
    const task = this.readTasks().find((item: any) => String(item.task_id) === taskId);
    if (task) this.eventEmitter.fire({ type: 'task.updated', taskId, threadId: task.thread_id, payload: task });
  }

  async requestThreadHistory(threadId: string): Promise<void> {
    const events = this.context.workspaceState.get<JsonRecord[]>(this.historyKey(threadId), []);
    const tasks = this.readTasks().filter((item: any) => String(item.thread_id) === threadId);
    this.eventEmitter.fire({ type: 'thread.history', threadId, events, messages: events, tasks });
  }

  async sendUserMessage(content: string, args: {
    threadId: string;
    taskMode?: 'auto' | 'plan' | 'execute' | 'inspect';
    autopilot?: boolean;
    workspaceRef?: string;
    context?: Record<string, unknown>;
  }): Promise<void> {
    await this.createThread(args.threadId);
    const session = this.sessions.get(args.threadId)!;
    const taskId = `gp_${crypto.randomUUID()}`;
    this.taskThreads.set(taskId, args.threadId);
    const permissionMode = this.permissionMode(args.taskMode ?? 'auto', args.autopilot !== false);
    const task = {
      task_id: taskId, thread_id: args.threadId, status: 'running', title: content.slice(0, 72),
      metadata: { source: 'vscode', engine: 'gitpilot', permission_mode: permissionMode, workspace: session.workspaceRoot },
      updated_at: Date.now(),
    };
    this.upsertTask(task);
    this.emitPersist(args.threadId, { type: 'message.user', threadId: args.threadId, taskId, payload: { content } });
    this.emitPersist(args.threadId, { type: 'message.accepted', threadId: args.threadId, taskId, payload: {} });
    this.emitPersist(args.threadId, { type: 'activity.start', threadId: args.threadId, taskId, payload: { title: 'GitPilot', detail: 'Preparing coding team…' } });

    try {
      await this.put('/api/permissions/mode', { mode: permissionMode });
      const topology = String(vscode.workspace.getConfiguration('erisCode.gitpilot').get<string>('topology', 'feature_builder')).trim();
      if (topology) {
        await this.post(`/api/flow/topology/${encodeURIComponent(topology)}`, {}).catch(() => undefined);
      }
      const ideContext = args.context ?? await captureIdeContext(this.terminalObserver);
      const erisContext = await this.erisBridge.readProjectContext(session.workspaceRoot);
      const message = this.composePrompt(content, ideContext, erisContext);
      this.emitPersist(args.threadId, { type: 'coding.state', threadId: args.threadId, taskId, payload: { phase: 'team', specialist: 'GitPilot Router', topology: topology || 'auto' } });
      const response = await this.post('/api/chat/send', {
        session_id: session.sessionId,
        message,
        topology_id: topology || undefined,
        intent: args.taskMode === 'plan' ? 'plan' : undefined,
        task_context: { source: 'eris-code', task_id: taskId },
      }, 45 * 60_000);
      const answer = String(response?.answer ?? response?.message ?? response?.content ?? '').trim();
      const edits = this.normalizeEdits(response?.edits);
      const plan = response?.plan;
      if (plan) {
        this.emitPersist(args.threadId, { type: 'plan.updated', threadId: args.threadId, taskId, payload: { plan } });
      }

      if (edits.length && permissionMode === 'normal') {
        this.pending.set(taskId, { taskId, threadId: args.threadId, edits, answer });
        task.status = 'waiting_permission'; task.updated_at = Date.now(); this.upsertTask(task);
        this.emitPersist(args.threadId, {
          type: 'interrupt.request', threadId: args.threadId, taskId,
          payload: {
            reason: 'tool_permission', question: `GitPilot đề xuất sửa ${edits.length} file. Áp dụng patch vào workspace?`,
            tool: 'apply_patch', args: { files: edits.map((edit) => edit.path) },
            options: [
              { id: 'allow', label: 'Apply Patch' },
              { id: 'deny', label: 'Reject' },
            ], allowOther: false,
          },
        });
        return;
      }

      if (edits.length && permissionMode === 'auto') {
        await this.applyEdits(taskId, args.threadId, edits);
      } else if (edits.length && permissionMode === 'plan') {
        for (const edit of edits) {
          this.emitPersist(args.threadId, { type: 'artifact.modified', threadId: args.threadId, taskId, payload: { path: edit.path, diff: this.previewOnlyDiff(edit) } });
        }
      }

      if (answer) this.emitPersist(args.threadId, { type: 'message.assistant', threadId: args.threadId, taskId, payload: { content: answer } });
      task.status = 'completed'; task.updated_at = Date.now(); this.upsertTask(task);
      this.emitPersist(args.threadId, { type: 'activity.end', threadId: args.threadId, taskId, payload: { status: 'completed', detail: 'GitPilot completed' } });
    } catch (error) {
      task.status = 'failed'; task.updated_at = Date.now(); this.upsertTask(task);
      this.emitPersist(args.threadId, { type: 'activity.end', threadId: args.threadId, taskId, payload: { status: 'failed', detail: String(error) } });
      this.emitPersist(args.threadId, { type: 'message.assistant', threadId: args.threadId, taskId, payload: { content: `GitPilot lỗi: ${String(error)}` } });
      throw error;
    }
  }

  async resolveInterrupt(taskId: string, response: unknown): Promise<void> {
    const pending = this.pending.get(taskId);
    if (!pending) return;
    const raw = response && typeof response === 'object' ? response as JsonRecord : {};
    const choice = String(raw.id ?? raw.choice ?? raw.value ?? raw.response ?? response ?? '').toLowerCase();
    this.pending.delete(taskId);
    if (choice.includes('allow') || choice.includes('apply') || choice === 'yes') {
      await this.applyEdits(taskId, pending.threadId, pending.edits);
      if (pending.answer) this.emitPersist(pending.threadId, { type: 'message.assistant', threadId: pending.threadId, taskId, payload: { content: pending.answer } });
      this.finishTask(taskId, 'completed');
      this.emitPersist(pending.threadId, { type: 'interrupt.resolved', threadId: pending.threadId, taskId, payload: { response: 'allow' } });
      return;
    }
    this.finishTask(taskId, 'completed');
    this.emitPersist(pending.threadId, { type: 'interrupt.resolved', threadId: pending.threadId, taskId, payload: { response: 'deny' } });
    if (pending.answer) this.emitPersist(pending.threadId, { type: 'message.assistant', threadId: pending.threadId, taskId, payload: { content: `${pending.answer}\n\nPatch chưa được áp dụng.` } });
  }

  async controlTask(taskId: string, action: string, _text = '', _checkpointId = '', _context: Record<string, unknown> = {}, changeSetId = ''): Promise<void> {
    const threadId = this.taskThreads.get(taskId) ?? this.readTasks().find((item: any) => item.task_id === taskId)?.thread_id ?? '';
    if (action === 'accept_changeset') {
      if (changeSetId) await this.deleteSnapshot(changeSetId);
      this.eventEmitter.fire({ type: 'task.control.ack', taskId, threadId, payload: { action, ok: true } });
      return;
    }
    if (action === 'revert_changeset') {
      await this.revertSnapshot(changeSetId);
      this.eventEmitter.fire({ type: 'changeset.updated', taskId, threadId, payload: { changeSetId, status: 'reverted' } });
      return;
    }
    if (['stop', 'cancel'].includes(action)) {
      this.pending.delete(taskId);
      this.finishTask(taskId, 'cancelled');
    }
    this.eventEmitter.fire({ type: 'task.control.ack', taskId, threadId, payload: { action, ok: true } });
  }

  async reportDocumentSaved(_fsPath: string, _content: string): Promise<void> { /* GitPilot owns repo refresh. */ }
  async reportEditorCommandResult(): Promise<void> { /* no Eris IDE RPC in GitPilot mode */ }
  async reportIdeResponse(): Promise<void> { /* no Eris IDE RPC in GitPilot mode */ }

  private async startGitPilotSession(root: string): Promise<GitPilotSession> {
    const git = await this.gitIdentity(root);
    let githubError: unknown;
    if (git.repoFullName) {
      try {
        const response = await this.post('/api/session/start', {
          mode: 'github', repo_root: root, repo_full_name: git.repoFullName, branch: git.branch || undefined,
        });
        const id = String(response?.session_id ?? response?.id ?? '');
        if (id) return { sessionId: id, workspaceRoot: root, mode: 'github' };
      } catch (error) {
        githubError = error;
      }
    }
    const allowFolderFallback = vscode.workspace.getConfiguration('erisCode.gitpilot').get<boolean>('allowFolderDirectFallback', false);
    if (!allowFolderFallback) {
      const reason = git.repoFullName
        ? `GitPilot GitHub session không khởi tạo được: ${String(githubError ?? 'unknown')}`
        : 'Workspace không có GitHub origin.';
      throw new Error(`${reason} Eris Code không âm thầm hạ xuống folder/direct-LLM vì bạn đã chọn GitPilot multi-agent làm coding brain. Kết nối repo với GitHub hoặc bật erisCode.gitpilot.allowFolderDirectFallback.`);
    }
    const response = await this.post('/api/session/start', { mode: 'folder', folder_path: root, repo_root: root });
    const id = String(response?.session_id ?? response?.id ?? '');
    if (!id) throw new Error('GitPilot không trả session_id.');
    return { sessionId: id, workspaceRoot: root, mode: 'folder' };
  }

  private async gitIdentity(root: string): Promise<{ repoFullName?: string; branch?: string }> {
    try {
      const [{ stdout: remote }, { stdout: branch }] = await Promise.all([
        execFileAsync('git', ['-C', root, 'remote', 'get-url', 'origin'], { timeout: 1800 }),
        execFileAsync('git', ['-C', root, 'branch', '--show-current'], { timeout: 1800 }),
      ]);
      const url = String(remote).trim();
      const match = /github\.com[/:]([^/]+)\/([^/]+?)(?:\.git)?$/i.exec(url);
      return { repoFullName: match ? `${match[1]}/${match[2]}` : undefined, branch: String(branch).trim() || undefined };
    } catch { return {}; }
  }

  private composePrompt(content: string, ide: Record<string, unknown>, eris?: Record<string, unknown>): string {
    const envelope = { source: 'eris-code', vscode_observation: ide, eris_observation: eris ?? null };
    const serialized = JSON.stringify(envelope);
    return `${content}\n\n<client_context>${serialized.slice(0, 24_000)}</client_context>`;
  }

  private permissionMode(taskMode: string, autopilot: boolean): 'normal' | 'auto' | 'plan' {
    if (taskMode === 'plan' || taskMode === 'inspect') return 'plan';
    return autopilot ? 'auto' : 'normal';
  }

  private normalizeEdits(raw: unknown): ProposedEdit[] {
    if (!Array.isArray(raw)) return [];
    const edits: ProposedEdit[] = [];
    for (const item of raw) {
      if (!item || typeof item !== 'object') continue;
      const record = item as JsonRecord;
      const filePath = String(record.path ?? record.file_path ?? record.filename ?? '').trim().replaceAll('\\', '/').replace(/^\/+/, '');
      const content = record.content ?? record.new_content ?? record.text;
      if (!filePath || typeof content !== 'string') continue;
      edits.push({ path: filePath, content, kind: String(record.kind ?? 'modified') });
    }
    return edits.slice(0, 100);
  }

  private async applyEdits(taskId: string, threadId: string, edits: ProposedEdit[]): Promise<void> {
    if (!vscode.workspace.isTrusted) throw new Error('Workspace chưa Trust; Eris Code từ chối áp dụng patch.');
    const root = this.workspaceRoot();
    if (!root) throw new Error('Không có workspace root.');
    const snapshot: ChangeSnapshot = { changeSetId: `cs_${crypto.randomUUID()}`, taskId, files: [] };
    const artifacts: Array<{ path: string; diff: string }> = [];
    for (const edit of edits) {
      const absolute = path.resolve(root, edit.path);
      const relative = path.relative(path.resolve(root), absolute);
      if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error(`Patch path vượt workspace: ${edit.path}`);
      const uri = vscode.Uri.file(absolute);
      let before = Buffer.alloc(0); let existed = true;
      try { before = Buffer.from(await vscode.workspace.fs.readFile(uri)); } catch { existed = false; }
      const beforeText = before.toString('utf8');
      snapshot.files.push({ path: edit.path, existed, beforeBase64: before.toString('base64') });
      await vscode.workspace.fs.createDirectory(vscode.Uri.file(path.dirname(absolute)));
      await vscode.workspace.fs.writeFile(uri, Buffer.from(edit.content, 'utf8'));
      recentlyModifiedFiles.set(uri.fsPath, Date.now());
      artifacts.push({ path: edit.path, diff: this.simpleDiff(edit.path, beforeText, edit.content) });
    }
    await this.saveSnapshot(snapshot);
    this.emitPersist(threadId, { type: 'changeset.created', threadId, taskId, payload: { changeSetId: snapshot.changeSetId, files: edits.map((e) => e.path), status: 'applied' } });
    for (const artifact of artifacts) this.emitPersist(threadId, { type: 'artifact.modified', threadId, taskId, payload: artifact });
  }

  private simpleDiff(filePath: string, before: string, after: string): string {
    if (before === after) return '';
    const oldLines = before.split('\n'); const newLines = after.split('\n');
    let prefix = 0;
    while (prefix < oldLines.length && prefix < newLines.length && oldLines[prefix] === newLines[prefix]) prefix++;
    let suffix = 0;
    while (suffix < oldLines.length - prefix && suffix < newLines.length - prefix && oldLines[oldLines.length - 1 - suffix] === newLines[newLines.length - 1 - suffix]) suffix++;
    const removed = oldLines.slice(prefix, oldLines.length - suffix).map((line) => `-${line}`);
    const added = newLines.slice(prefix, newLines.length - suffix).map((line) => `+${line}`);
    return [`--- a/${filePath}`, `+++ b/${filePath}`, `@@ -${prefix + 1},${removed.length} +${prefix + 1},${added.length} @@`, ...removed, ...added].join('\n');
  }

  private previewOnlyDiff(edit: ProposedEdit): string { return `--- a/${edit.path}\n+++ b/${edit.path}\n@@ proposed @@\n${edit.content.split('\n').slice(0, 300).map((line) => `+${line}`).join('\n')}`; }

  private snapshotUri(id: string): vscode.Uri { return vscode.Uri.joinPath(this.context.globalStorageUri, 'changesets', `${id}.json`); }
  private async saveSnapshot(snapshot: ChangeSnapshot): Promise<void> {
    const dir = vscode.Uri.joinPath(this.context.globalStorageUri, 'changesets');
    await vscode.workspace.fs.createDirectory(dir);
    await vscode.workspace.fs.writeFile(this.snapshotUri(snapshot.changeSetId), Buffer.from(JSON.stringify(snapshot), 'utf8'));
  }
  private async deleteSnapshot(id: string): Promise<void> { try { await vscode.workspace.fs.delete(this.snapshotUri(id)); } catch {} }
  private async revertSnapshot(id: string): Promise<void> {
    if (!id) throw new Error('Thiếu changeSetId.');
    const raw = await vscode.workspace.fs.readFile(this.snapshotUri(id));
    const snapshot = JSON.parse(Buffer.from(raw).toString('utf8')) as ChangeSnapshot;
    const root = this.workspaceRoot(); if (!root) throw new Error('Không có workspace root.');
    for (const file of snapshot.files) {
      const absolute = path.resolve(root, file.path); const relative = path.relative(path.resolve(root), absolute);
      if (relative.startsWith('..') || path.isAbsolute(relative)) continue;
      const uri = vscode.Uri.file(absolute);
      if (!file.existed) { try { await vscode.workspace.fs.delete(uri); } catch {} }
      else { await vscode.workspace.fs.createDirectory(vscode.Uri.file(path.dirname(absolute))); await vscode.workspace.fs.writeFile(uri, Buffer.from(file.beforeBase64, 'base64')); }
    }
    await this.deleteSnapshot(id);
  }

  private async post(endpoint: string, body: unknown, timeoutMs = 20_000): Promise<any> { return this.request('POST', endpoint, body, timeoutMs); }
  private async put(endpoint: string, body: unknown, timeoutMs = 10_000): Promise<any> { return this.request('PUT', endpoint, body, timeoutMs); }
  private async request(method: string, endpoint: string, body: unknown, timeoutMs: number): Promise<any> {
    await this.connectIfNeeded();
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${this.runtime.serverUrl}${endpoint}`, { method, headers: { 'content-type': 'application/json', accept: 'application/json' }, body: JSON.stringify(body), signal: controller.signal });
      const text = await response.text(); let data: any = {};
      try { data = text ? JSON.parse(text) : {}; } catch { data = { message: text }; }
      if (!response.ok) throw new Error(`GitPilot ${method} ${endpoint}: ${response.status} ${String(data?.detail ?? data?.message ?? text).slice(0, 500)}`);
      return data;
    } finally { clearTimeout(timer); }
  }
  private async connectIfNeeded(): Promise<void> { if (this.state !== 'connected' || !await this.runtime.probe()) await this.connect(); }
  private workspaceRoot(): string { return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? ''; }

  private historyKey(threadId: string): string { return `erisCode.history.${threadId}`; }
  private emitPersist(threadId: string, event: JsonRecord): void {
    const previous = this.context.workspaceState.get<JsonRecord[]>(this.historyKey(threadId), []);
    const history = [...previous, event].slice(-600);
    void this.context.workspaceState.update(this.historyKey(threadId), history);
    this.eventEmitter.fire(event);
  }
  private readTasks(): any[] { return this.context.workspaceState.get<any[]>('erisCode.tasks', []); }
  private upsertTask(task: any): void {
    const tasks = this.readTasks(); const index = tasks.findIndex((item) => item.task_id === task.task_id);
    if (index >= 0) tasks[index] = task; else tasks.push(task);
    void this.context.workspaceState.update('erisCode.tasks', tasks.slice(-80));
    this.eventEmitter.fire({ type: 'task.list', tasks: tasks.slice(-80) });
  }
  private finishTask(taskId: string, status: string): void {
    const tasks = this.readTasks(); const task = tasks.find((item) => item.task_id === taskId);
    if (task) { task.status = status; task.updated_at = Date.now(); this.upsertTask(task); }
  }
  private setState(state: ConnectionState): void { if (this.state !== state) { this.state = state; this.stateEmitter.fire(state); } }

  dispose(): void { this.eventEmitter.dispose(); this.stateEmitter.dispose(); this.pending.clear(); this.sessions.clear(); }
}
