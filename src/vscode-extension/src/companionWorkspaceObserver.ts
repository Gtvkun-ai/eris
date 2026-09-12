import * as crypto from 'node:crypto';
import * as path from 'node:path';
import * as vscode from 'vscode';
import {
  createCodingObservation,
  type CodingActor,
  type CodingObservationType,
} from './codingObservation';
import { ErisObserverBridge } from './erisObserverBridge';

/**
 * V90: mắt/tai workspace độc lập với GitPilot.
 *
 * Observer chỉ phát metadata/evidence nhỏ: file path, diagnostics count, command
 * shell ngắn, editor focus. Không đọc source content và không suy đoán ai đã gõ
 * một thay đổi nếu VS Code không cung cấp provenance.
 */
export class CompanionWorkspaceObserver implements vscode.Disposable {
  private readonly disposables: vscode.Disposable[] = [];
  private readonly sessionId = `vscode_${crypto.randomUUID()}`;
  private readonly lastFocused = new Map<string, string>();
  private readonly lastDiagnostics = new Map<string, string>();
  private readonly diagTimers = new Map<string, NodeJS.Timeout>();

  constructor(private readonly bridge: ErisObserverBridge) {
    this.registerWorkspaceLifecycle();
    this.registerEditorFocus();
    this.registerFileLifecycle();
    this.registerDiagnostics();
    this.registerTerminalCommands();
  }

  private enabled(): boolean {
    return vscode.workspace.getConfiguration('erisCode.erisLink').get<boolean>('observeWorkspace', true);
  }

  private roots(): string[] {
    return (vscode.workspace.workspaceFolders ?? []).map((item) => item.uri.fsPath);
  }

  private taskId(root: string): string {
    const digest = crypto.createHash('sha1').update(root).digest('hex').slice(0, 10);
    return `workspace_${this.sessionId}_${digest}`;
  }

  private workspaceForUri(uri: vscode.Uri | undefined): string {
    if (uri?.scheme === 'file') {
      const folder = vscode.workspace.getWorkspaceFolder(uri);
      if (folder) return folder.uri.fsPath;
    }
    return this.roots()[0] ?? '';
  }

  private relativeFile(root: string, uri: vscode.Uri): string {
    if (uri.scheme !== 'file') return '';
    if (!root) return uri.fsPath.replaceAll('\\', '/');
    const relative = path.relative(root, uri.fsPath);
    if (relative.startsWith('..') || path.isAbsolute(relative)) return '';
    return relative.replaceAll('\\', '/');
  }

  private publish(root: string, args: {
    eventType: CodingObservationType;
    actor?: CodingActor;
    files?: string[];
    command?: string;
    status?: string;
    evidence?: string;
    metrics?: Record<string, number | string | boolean>;
  }): void {
    if (!this.enabled() || !root) return;
    this.bridge.publishCodingObservation(createCodingObservation({
      eventType: args.eventType,
      source: 'eris-code/workspace',
      taskId: this.taskId(root),
      sessionId: this.sessionId,
      workspace: root,
      actor: args.actor ?? 'vscode',
      files: args.files,
      command: args.command,
      status: args.status,
      evidence: args.evidence,
      metrics: args.metrics,
    }));
  }

  private registerWorkspaceLifecycle(): void {
    for (const root of this.roots()) {
      this.publish(root, { eventType: 'workspace_session_started', status: 'active' });
    }
    this.disposables.push(vscode.workspace.onDidChangeWorkspaceFolders((event) => {
      for (const folder of event.added) {
        this.publish(folder.uri.fsPath, { eventType: 'workspace_session_started', status: 'active' });
      }
      for (const folder of event.removed) {
        this.publish(folder.uri.fsPath, { eventType: 'workspace_session_ended', status: 'closed' });
      }
    }));
  }

  private registerEditorFocus(): void {
    this.disposables.push(vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (!editor || editor.document.uri.scheme !== 'file') return;
      const root = this.workspaceForUri(editor.document.uri);
      const file = this.relativeFile(root, editor.document.uri);
      if (!file || this.lastFocused.get(root) === file) return;
      this.lastFocused.set(root, file);
      this.publish(root, { eventType: 'editor_focus', files: [file], status: 'focused' });
    }));
  }

  private registerFileLifecycle(): void {
    this.disposables.push(vscode.workspace.onDidSaveTextDocument((document) => {
      if (document.uri.scheme !== 'file') return;
      const root = this.workspaceForUri(document.uri);
      const file = this.relativeFile(root, document.uri);
      if (file) this.publish(root, { eventType: 'file_saved', files: [file], status: 'saved' });
    }));

    this.disposables.push(vscode.workspace.onDidCreateFiles((event) => {
      for (const uri of event.files) {
        const root = this.workspaceForUri(uri);
        const file = this.relativeFile(root, uri);
        if (file) this.publish(root, { eventType: 'file_created', files: [file], status: 'created' });
      }
    }));

    this.disposables.push(vscode.workspace.onDidDeleteFiles((event) => {
      for (const uri of event.files) {
        const root = this.workspaceForUri(uri);
        const file = this.relativeFile(root, uri);
        if (file) this.publish(root, { eventType: 'file_deleted', files: [file], status: 'deleted' });
      }
    }));

    this.disposables.push(vscode.workspace.onDidRenameFiles((event) => {
      for (const item of event.files) {
        const root = this.workspaceForUri(item.newUri);
        const oldFile = this.relativeFile(root, item.oldUri);
        const newFile = this.relativeFile(root, item.newUri);
        const files = [oldFile, newFile].filter(Boolean);
        if (files.length) this.publish(root, { eventType: 'file_renamed', files, status: 'renamed' });
      }
    }));
  }

  private registerDiagnostics(): void {
    this.disposables.push(vscode.languages.onDidChangeDiagnostics((event) => {
      for (const uri of event.uris) {
        if (uri.scheme !== 'file') continue;
        const key = uri.toString();
        const prior = this.diagTimers.get(key);
        if (prior) clearTimeout(prior);
        this.diagTimers.set(key, setTimeout(() => {
          this.diagTimers.delete(key);
          const root = this.workspaceForUri(uri);
          const file = this.relativeFile(root, uri);
          if (!file) return;
          const diagnostics = vscode.languages.getDiagnostics(uri);
          const errors = diagnostics.filter((item) => item.severity === vscode.DiagnosticSeverity.Error).length;
          const warnings = diagnostics.filter((item) => item.severity === vscode.DiagnosticSeverity.Warning).length;
          const signature = `${errors}:${warnings}`;
          if (this.lastDiagnostics.get(key) === signature) return;
          this.lastDiagnostics.set(key, signature);
          this.publish(root, {
            eventType: 'diagnostics',
            files: [file],
            status: errors > 0 ? 'failed' : 'passed',
            metrics: { errors, warnings, origin: 'vscode' },
          });
        }, 350));
      }
    }));
  }

  private registerTerminalCommands(): void {
    const windowApi = vscode.window as any;
    if (typeof windowApi.onDidEndTerminalShellExecution !== 'function') return;
    this.disposables.push(windowApi.onDidEndTerminalShellExecution((event: any) => {
      const execution = event?.execution;
      const shellIntegration = event?.terminal?.shellIntegration;
      const commandLine = execution?.commandLine;
      const cwd = String(shellIntegration?.cwd?.fsPath ?? shellIntegration?.cwd?.path ?? '');
      let root = this.roots()[0] ?? '';
      if (cwd) {
        const folder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(cwd));
        if (folder) root = folder.uri.fsPath;
      }
      const command = String(commandLine?.value ?? commandLine ?? '');
      if (!root || !command.trim()) return;
      this.publish(root, {
        eventType: 'terminal_command',
        command,
        status: typeof event?.exitCode === 'number' ? (event.exitCode === 0 ? 'passed' : 'failed') : 'finished',
        metrics: typeof event?.exitCode === 'number' ? { exit_code: event.exitCode } : undefined,
      });
    }));
  }

  dispose(): void {
    for (const timer of this.diagTimers.values()) clearTimeout(timer);
    this.diagTimers.clear();
    for (const root of this.roots()) {
      this.publish(root, { eventType: 'workspace_session_ended', status: 'closed' });
    }
    while (this.disposables.length) this.disposables.pop()?.dispose();
  }
}

const EXTERNAL_EVENT_TYPES = new Set<CodingObservationType>([
  'user_intent', 'task_started', 'phase_changed', 'plan_step', 'phase_summary',
  'tool_started', 'tool_finished', 'file_changed', 'test_result', 'diagnostics',
  'task_completed', 'task_failed', 'task_cancelled',
]);

/**
 * Adapter nhỏ cho coding extension khác. Adapter bên kia có thể gọi:
 * vscode.commands.executeCommand('erisCode.companion.observeExternalAgent', payload)
 * mà không cần Eris sở hữu/control agent đó.
 */
export function registerExternalAgentObservationBridge(
  context: vscode.ExtensionContext,
  bridge: ErisObserverBridge,
): void {
  context.subscriptions.push(vscode.commands.registerCommand(
    'erisCode.companion.observeExternalAgent',
    (raw: unknown) => {
      if (!raw || typeof raw !== 'object') return false;
      const payload = raw as Record<string, unknown>;
      const eventType = String(payload.event_type ?? payload.eventType ?? '') as CodingObservationType;
      if (!EXTERNAL_EVENT_TYPES.has(eventType)) return false;
      const roots = (vscode.workspace.workspaceFolders ?? []).map((item) => item.uri.fsPath);
      if (!roots.length) return false;
      const requested = String(payload.workspace ?? '');
      const workspace = roots.find((root) => path.resolve(root) === path.resolve(requested)) ?? roots[0];
      const actorRaw = String(payload.actor ?? 'external_agent');
      const actor: CodingActor = ['explorer', 'planner', 'coder', 'reviewer', 'validation', 'external_agent'].includes(actorRaw)
        ? actorRaw as CodingActor
        : 'external_agent';
      bridge.publishCodingObservation(createCodingObservation({
        eventType,
        source: 'eris-code/external-agent',
        taskId: String(payload.task_id ?? payload.taskId ?? `external_${crypto.randomUUID()}`),
        sessionId: String(payload.session_id ?? payload.sessionId ?? 'external-agent'),
        threadId: String(payload.thread_id ?? payload.threadId ?? ''),
        workspace,
        actor,
        files: Array.isArray(payload.files) ? payload.files.map(String) : undefined,
        command: String(payload.command ?? ''),
        status: String(payload.status ?? ''),
        evidence: String(payload.evidence ?? ''),
        metrics: payload.metrics && typeof payload.metrics === 'object'
          ? payload.metrics as Record<string, number | string | boolean>
          : undefined,
      }));
      return true;
    },
  ));
}
