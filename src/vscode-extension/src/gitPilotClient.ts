import * as crypto from 'node:crypto';
import { execFile } from 'node:child_process';
import * as vscode from 'vscode';
import { promisify } from 'node:util';
import { captureIdeContext } from './contextBridge';
import { ErisObserverBridge } from './erisObserverBridge';
import { GitPilotRuntimeManager } from './gitPilotRuntimeManager';
import { TerminalContextObserver } from './terminalObserver';

const execFileAsync = promisify(execFile);
export type ConnectionState = 'disconnected' | 'connecting' | 'connected';
type JsonRecord = Record<string, any>;
type PermissionMode = 'normal' | 'auto' | 'plan';
type GitPilotSession = { sessionId: string; workspaceRoot: string; mode: 'local_git' | 'folder' };
type PendingApproval = { taskId: string; threadId: string; sessionId: string; requestId: string };

/**
 * Adapter mỏng giữa UI Eris Code và backend GitPilot.
 *
 * V78 cố ý KHÔNG chứa patch engine/coder/planner riêng. GitPilot tự đọc file,
 * sửa file, chạy test và review. Extension chỉ:
 * 1) tạo local session,
 * 2) gửi context VS Code,
 * 3) render SSE event,
 * 4) chuyển approval/cancel của user về GitPilot.
 */
export class GitPilotClient implements vscode.Disposable {
  private state: ConnectionState = 'disconnected';
  private readonly eventEmitter = new vscode.EventEmitter<JsonRecord>();
  private readonly stateEmitter = new vscode.EventEmitter<ConnectionState>();
  private readonly sessions = new Map<string, GitPilotSession>();
  private readonly pending = new Map<string, PendingApproval>();
  private readonly taskThreads = new Map<string, string>();
  private readonly taskSessions = new Map<string, string>();
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
    const session = await this.startLocalSession(root);
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
    if (!vscode.workspace.isTrusted && args.taskMode !== 'plan' && args.taskMode !== 'inspect') {
      throw new Error('Workspace chưa Trust; Eris Code chỉ cho phép thao tác read-only trước khi Trust workspace.');
    }

    await this.createThread(args.threadId);
    const session = this.sessions.get(args.threadId)!;
    const taskId = `gp_${crypto.randomUUID()}`;
    this.taskThreads.set(taskId, args.threadId);
    this.taskSessions.set(taskId, session.sessionId);

    const permissionMode = this.permissionMode(args.taskMode ?? 'auto', args.autopilot !== false);
    const task = {
      task_id: taskId,
      thread_id: args.threadId,
      status: 'running',
      title: content.slice(0, 72),
      metadata: {
        source: 'vscode', engine: 'gitpilot', permission_mode: permissionMode,
        workspace: session.workspaceRoot, session_id: session.sessionId,
      },
      updated_at: Date.now(),
    };
    this.upsertTask(task);
    this.emitPersist(args.threadId, { type: 'message.user', threadId: args.threadId, taskId, payload: { content } });
    this.emitPersist(args.threadId, { type: 'message.accepted', threadId: args.threadId, taskId, payload: {} });
    this.emitPersist(args.threadId, {
      type: 'activity.start', threadId: args.threadId, taskId,
      payload: { title: 'GitPilot', detail: 'Đang khởi động coding team…', status: 'running' },
    });

    try {
      const topology = String(vscode.workspace.getConfiguration('erisCode.gitpilot').get<string>('topology', 'feature_builder')).trim() || 'feature_builder';
      const ideContext = args.context ?? await captureIdeContext(this.terminalObserver);
      const erisContext = await this.erisBridge.readProjectContext(session.workspaceRoot);
      const message = this.composePrompt(content, ideContext, erisContext);

      await this.streamTask({
        taskId,
        threadId: args.threadId,
        session,
        message,
        permissionMode,
        topology,
        intent: args.taskMode === 'plan' ? 'plan' : args.taskMode === 'inspect' ? 'inspect' : 'execute',
      });

      task.status = 'completed';
      task.updated_at = Date.now();
      this.upsertTask(task);
      this.emitPersist(args.threadId, {
        type: 'activity.end', threadId: args.threadId, taskId,
        payload: { status: 'completed', detail: 'GitPilot completed' },
      });
    } catch (error) {
      task.status = 'failed';
      task.updated_at = Date.now();
      this.upsertTask(task);
      this.emitPersist(args.threadId, {
        type: 'activity.end', threadId: args.threadId, taskId,
        payload: { status: 'failed', detail: String(error) },
      });
      this.emitPersist(args.threadId, {
        type: 'message.assistant', threadId: args.threadId, taskId,
        payload: { content: `GitPilot lỗi: ${String(error)}` },
      });
      throw error;
    } finally {
      this.pending.delete(taskId);
    }
  }

  async resolveInterrupt(taskId: string, response: unknown): Promise<void> {
    const pending = this.pending.get(taskId);
    if (!pending) return;

    const raw = response && typeof response === 'object' ? response as JsonRecord : {};
    const choice = String(raw.id ?? raw.choice ?? raw.value ?? raw.response ?? response ?? '').toLowerCase();
    const approved = choice.includes('allow') || choice.includes('approve') || choice === 'yes';
    const scope = choice.includes('session') ? 'session' : 'once';

    await this.post('/api/v2/approval/respond', {
      session_id: pending.sessionId,
      request_id: pending.requestId,
      approved,
      scope,
    });

    this.emitPersist(pending.threadId, {
      type: 'interrupt.resolved', threadId: pending.threadId, taskId,
      payload: { response: approved ? scope : 'deny', requestId: pending.requestId },
    });
    this.pending.delete(taskId);
  }

  async controlTask(
    taskId: string,
    action: string,
    _text = '',
    _checkpointId = '',
    _context: Record<string, unknown> = {},
    _changeSetId = '',
  ): Promise<void> {
    const threadId = this.taskThreads.get(taskId) ?? this.readTasks().find((item: any) => item.task_id === taskId)?.thread_id ?? '';
    if (['stop', 'cancel'].includes(action)) {
      const sessionId = this.taskSessions.get(taskId);
      if (sessionId) {
        await this.post('/api/v2/agent/cancel', { session_id: sessionId }).catch(() => undefined);
      }
      this.pending.delete(taskId);
      this.finishTask(taskId, 'cancelled');
    }
    // V78 không tự quản lý changeset: workspace/checkpoint là trách nhiệm GitPilot.
    this.eventEmitter.fire({ type: 'task.control.ack', taskId, threadId, payload: { action, ok: true } });
  }

  async reportDocumentSaved(_fsPath: string, _content: string): Promise<void> { /* GitPilot đọc workspace trực tiếp. */ }
  async reportEditorCommandResult(): Promise<void> { /* Không còn Eris IDE RPC. */ }
  async reportIdeResponse(): Promise<void> { /* Không còn Eris IDE RPC. */ }

  private async streamTask(args: {
    taskId: string;
    threadId: string;
    session: GitPilotSession;
    message: string;
    permissionMode: PermissionMode;
    topology: string;
    intent: 'execute' | 'plan' | 'inspect';
  }): Promise<void> {
    await this.connectIfNeeded();
    const controller = new AbortController();
    const response = await fetch(`${this.runtime.serverUrl}/api/v2/chat/stream`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'text/event-stream' },
      body: JSON.stringify({
        session_id: args.session.sessionId,
        message: args.message,
        permission_mode: args.permissionMode,
        topology_id: args.topology,
        intent: args.intent,
        task_context: { source: 'eris-code', task_id: args.taskId },
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`GitPilot stream: ${response.status} ${text.slice(0, 700)}`);
    }
    if (!response.body) throw new Error('GitPilot stream không có response body.');

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let assistantText = '';
    let terminalError = '';
    let doneSummary = '';

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      const frames = buffer.split('\n\n');
      buffer = frames.pop() ?? '';

      for (const frame of frames) {
        for (const line of frame.split('\n')) {
          if (!line.startsWith('data:')) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;
          const event = JSON.parse(raw) as JsonRecord;
          const mapped = this.handleStreamEvent(args, event);
          if (mapped.delta) assistantText += mapped.delta;
          if (mapped.error) terminalError = mapped.error;
          if (mapped.summary) doneSummary = mapped.summary;
        }
      }
      if (done) break;
    }

    if (buffer.trim().startsWith('data:')) {
      try {
        const event = JSON.parse(buffer.trim().slice(5).trim()) as JsonRecord;
        const mapped = this.handleStreamEvent(args, event);
        if (mapped.delta) assistantText += mapped.delta;
        if (mapped.error) terminalError = mapped.error;
      } catch { /* frame cuối không hoàn chỉnh thì bỏ qua */ }
    }

    if (terminalError) throw new Error(terminalError);
    if (!assistantText.trim()) {
      this.emitPersist(args.threadId, {
        type: 'message.assistant', threadId: args.threadId, taskId: args.taskId,
        payload: { content: doneSummary || 'GitPilot đã hoàn tất task. Xem diff/test/review trong activity.' },
      });
    }
  }

  private handleStreamEvent(args: {
    taskId: string; threadId: string; session: GitPilotSession; topology: string;
  }, event: JsonRecord): { delta?: string; error?: string; summary?: string } {
    const type = String(event.type ?? '');

    if (type === 'text_delta') {
      const text = String(event.text ?? '');
      if (text) this.emitPersist(args.threadId, { type: 'message.assistant.delta', threadId: args.threadId, taskId: args.taskId, payload: { content: text, delta: text } });
      return { delta: text };
    }

    if (type === 'status_change') {
      const status = String(event.status ?? 'running');
      const message = String(event.message ?? '');
      if (status !== 'keepalive') {
        this.emitPersist(args.threadId, {
          type: 'coding.state', threadId: args.threadId, taskId: args.taskId,
          payload: { phase: status, specialist: message || 'GitPilot', topology: args.topology },
        });
      }
      return {};
    }

    if (type === 'plan_step') {
      this.emitPersist(args.threadId, {
        type: 'plan.updated', threadId: args.threadId, taskId: args.taskId,
        payload: { plan: { step_index: event.step_index, title: event.title, status: event.status, action: event.action } },
      });
      return {};
    }

    if (type === 'tool_start') {
      this.emitPersist(args.threadId, {
        type: 'activity.update', threadId: args.threadId, taskId: args.taskId,
        payload: { status: 'running', title: String(event.name ?? 'tool'), detail: this.safeJson(event.arguments) },
      });
      return {};
    }

    if (type === 'tool_result') {
      this.emitPersist(args.threadId, {
        type: 'activity.update', threadId: args.threadId, taskId: args.taskId,
        payload: {
          status: event.is_error ? 'failed' : 'running',
          title: String(event.name ?? 'tool'), detail: String(event.result ?? '').slice(0, 4000),
        },
      });
      return {};
    }

    if (type === 'file_write') {
      this.emitPersist(args.threadId, {
        type: 'artifact.modified', threadId: args.threadId, taskId: args.taskId,
        payload: { path: String(event.path ?? ''), action: String(event.action ?? 'modify'), diff: '' },
      });
      return {};
    }

    if (type === 'approval_needed') {
      const requestId = String(event.request_id ?? '');
      this.pending.set(args.taskId, {
        taskId: args.taskId, threadId: args.threadId,
        sessionId: args.session.sessionId, requestId,
      });
      this.finishTask(args.taskId, 'waiting_permission');
      this.emitPersist(args.threadId, {
        type: 'interrupt.request', threadId: args.threadId, taskId: args.taskId,
        payload: {
          reason: 'tool_permission',
          question: String(event.summary ?? `GitPilot muốn chạy ${String(event.tool ?? 'tool')}`),
          tool: String(event.tool ?? ''),
          args: event.arguments ?? {},
          diff: event.diff_preview ?? '',
          risk: event.risk_level ?? 'medium',
          options: [
            { id: 'allow_once', label: 'Cho phép lần này' },
            { id: 'allow_session', label: 'Cho phép trong session' },
            { id: 'deny', label: 'Từ chối' },
          ],
          allowOther: false,
        },
      });
      return {};
    }

    if (type === 'approval_resolved') {
      this.pending.delete(args.taskId);
      this.finishTask(args.taskId, 'running');
      return {};
    }

    if (type === 'test_result') {
      const detail = `${String(event.framework ?? 'tests')}: ${Number(event.passed ?? 0)} passed, ${Number(event.failed ?? 0)} failed, ${Number(event.skipped ?? 0)} skipped`;
      this.emitPersist(args.threadId, {
        type: 'activity.update', threadId: args.threadId, taskId: args.taskId,
        payload: { title: 'Tests', detail, status: Number(event.failed ?? 0) > 0 ? 'failed' : 'running' },
      });
      return {};
    }

    if (type === 'diagnostics') {
      this.emitPersist(args.threadId, {
        type: 'activity.update', threadId: args.threadId, taskId: args.taskId,
        payload: { title: 'Diagnostics', detail: `${event.errors ?? 0} errors · ${event.warnings ?? 0} warnings`, status: Number(event.errors ?? 0) ? 'failed' : 'running' },
      });
      return {};
    }

    if (type === 'error') {
      return { error: String(event.error ?? 'GitPilot agent error') };
    }

    if (type === 'done') {
      // `text_delta` đã được render theo thời gian thực. Chỉ trả summary cho
      // streamTask dùng làm fallback, tránh tạo thêm một message trùng nội dung.
      return { summary: String(event.summary ?? '').trim() };
    }
    return {};
  }

  private async startLocalSession(root: string): Promise<GitPilotSession> {
    const branch = await this.gitBranch(root);
    if (branch !== undefined) {
      const response = await this.post('/api/session/start', { mode: 'local_git', repo_root: root, folder_path: root, branch: branch || undefined });
      const id = String(response?.session_id ?? response?.id ?? '');
      if (!id) throw new Error('GitPilot không trả session_id cho local_git session.');
      return { sessionId: id, workspaceRoot: root, mode: 'local_git' };
    }

    const response = await this.post('/api/session/start', { mode: 'folder', folder_path: root });
    const id = String(response?.session_id ?? response?.id ?? '');
    if (!id) throw new Error('GitPilot không trả session_id cho folder session.');
    return { sessionId: id, workspaceRoot: root, mode: 'folder' };
  }

  private async gitBranch(root: string): Promise<string | undefined> {
    try {
      const { stdout } = await execFileAsync('git', ['-C', root, 'rev-parse', '--is-inside-work-tree'], { timeout: 1800 });
      if (String(stdout).trim() !== 'true') return undefined;
      const branch = await execFileAsync('git', ['-C', root, 'branch', '--show-current'], { timeout: 1800 });
      return String(branch.stdout).trim();
    } catch { return undefined; }
  }

  private composePrompt(content: string, ide: Record<string, unknown>, eris?: Record<string, unknown>): string {
    // Chỉ đưa observation/project context cần cho task. Private user model của
    // Eris Desktop không được đẩy sang coding provider mặc định.
    const envelope = { source: 'eris-code', vscode_observation: ide, eris_observation: eris ?? null };
    const serialized = JSON.stringify(envelope);
    return `${content}\n\n<ide_observation>${serialized.slice(0, 24_000)}</ide_observation>`;
  }

  private permissionMode(taskMode: string, autopilot: boolean): PermissionMode {
    if (taskMode === 'plan' || taskMode === 'inspect') return 'plan';
    return autopilot ? 'auto' : 'normal';
  }

  private async post(endpoint: string, body: unknown, timeoutMs = 20_000): Promise<any> {
    await this.connectIfNeeded();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${this.runtime.serverUrl}${endpoint}`, {
        method: 'POST', headers: { 'content-type': 'application/json', accept: 'application/json' },
        body: JSON.stringify(body), signal: controller.signal,
      });
      const text = await response.text();
      let data: any = {};
      try { data = text ? JSON.parse(text) : {}; } catch { data = { message: text }; }
      if (!response.ok) throw new Error(`GitPilot POST ${endpoint}: ${response.status} ${String(data?.detail ?? data?.message ?? text).slice(0, 500)}`);
      return data;
    } finally { clearTimeout(timer); }
  }

  private async connectIfNeeded(): Promise<void> {
    if (this.state !== 'connected' || !await this.runtime.probe()) await this.connect();
  }

  private workspaceRoot(): string { return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? ''; }
  private historyKey(threadId: string): string { return `erisCode.history.${threadId}`; }
  private safeJson(value: unknown): string { try { return JSON.stringify(value ?? {}).slice(0, 3000); } catch { return String(value ?? ''); } }

  private emitPersist(threadId: string, event: JsonRecord): void {
    const previous = this.context.workspaceState.get<JsonRecord[]>(this.historyKey(threadId), []);
    const history = [...previous, event].slice(-600);
    void this.context.workspaceState.update(this.historyKey(threadId), history);
    this.eventEmitter.fire(event);
  }

  private readTasks(): any[] { return this.context.workspaceState.get<any[]>('erisCode.tasks', []); }

  private upsertTask(task: any): void {
    const tasks = this.readTasks();
    const index = tasks.findIndex((item) => item.task_id === task.task_id);
    if (index >= 0) tasks[index] = task; else tasks.push(task);
    void this.context.workspaceState.update('erisCode.tasks', tasks.slice(-80));
    this.eventEmitter.fire({ type: 'task.list', tasks: tasks.slice(-80) });
  }

  private finishTask(taskId: string, status: string): void {
    const tasks = this.readTasks();
    const task = tasks.find((item) => item.task_id === taskId);
    if (task) { task.status = status; task.updated_at = Date.now(); this.upsertTask(task); }
  }

  private setState(state: ConnectionState): void {
    if (this.state !== state) { this.state = state; this.stateEmitter.fire(state); }
  }

  dispose(): void {
    this.eventEmitter.dispose();
    this.stateEmitter.dispose();
    this.pending.clear();
    this.sessions.clear();
    this.taskSessions.clear();
  }
}
