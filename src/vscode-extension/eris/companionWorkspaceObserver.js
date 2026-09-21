"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.CompanionWorkspaceObserver = void 0;
exports.registerExternalAgentObservationBridge = registerExternalAgentObservationBridge;
const crypto = __importStar(require("node:crypto"));
const path = __importStar(require("node:path"));
const vscode = __importStar(require("vscode"));
const codingObservation_1 = require("./codingObservation");
/**
 * V90: mắt/tai workspace độc lập với GitPilot.
 *
 * Observer chỉ phát metadata/evidence nhỏ: file path, diagnostics count, command
 * shell ngắn, editor focus. Không đọc source content và không suy đoán ai đã gõ
 * một thay đổi nếu VS Code không cung cấp provenance.
 */
class CompanionWorkspaceObserver {
    bridge;
    disposables = [];
    sessionId = `vscode_${crypto.randomUUID()}`;
    lastFocused = new Map();
    lastDiagnostics = new Map();
    diagTimers = new Map();
    constructor(bridge) {
        this.bridge = bridge;
        this.registerWorkspaceLifecycle();
        this.registerEditorFocus();
        this.registerFileLifecycle();
        this.registerDiagnostics();
        this.registerTerminalCommands();
    }
    enabled() {
        return vscode.workspace.getConfiguration('erisCode.erisLink').get('observeWorkspace', true);
    }
    roots() {
        return (vscode.workspace.workspaceFolders ?? []).map((item) => item.uri.fsPath);
    }
    taskId(root) {
        const digest = crypto.createHash('sha1').update(root).digest('hex').slice(0, 10);
        return `workspace_${this.sessionId}_${digest}`;
    }
    workspaceForUri(uri) {
        if (uri?.scheme === 'file') {
            const folder = vscode.workspace.getWorkspaceFolder(uri);
            if (folder)
                return folder.uri.fsPath;
        }
        return this.roots()[0] ?? '';
    }
    relativeFile(root, uri) {
        if (uri.scheme !== 'file')
            return '';
        if (!root)
            return uri.fsPath.replaceAll('\\', '/');
        const relative = path.relative(root, uri.fsPath);
        if (relative.startsWith('..') || path.isAbsolute(relative))
            return '';
        return relative.replaceAll('\\', '/');
    }
    publish(root, args) {
        if (!this.enabled() || !root)
            return;
        this.bridge.publishCodingObservation((0, codingObservation_1.createCodingObservation)({
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
    registerWorkspaceLifecycle() {
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
    registerEditorFocus() {
        this.disposables.push(vscode.window.onDidChangeActiveTextEditor((editor) => {
            if (!editor || editor.document.uri.scheme !== 'file')
                return;
            const root = this.workspaceForUri(editor.document.uri);
            const file = this.relativeFile(root, editor.document.uri);
            if (!file || this.lastFocused.get(root) === file)
                return;
            this.lastFocused.set(root, file);
            this.publish(root, { eventType: 'editor_focus', files: [file], status: 'focused' });
        }));
    }
    registerFileLifecycle() {
        this.disposables.push(vscode.workspace.onDidSaveTextDocument((document) => {
            if (document.uri.scheme !== 'file')
                return;
            const root = this.workspaceForUri(document.uri);
            const file = this.relativeFile(root, document.uri);
            if (file)
                this.publish(root, { eventType: 'file_saved', files: [file], status: 'saved' });
        }));
        this.disposables.push(vscode.workspace.onDidCreateFiles((event) => {
            for (const uri of event.files) {
                const root = this.workspaceForUri(uri);
                const file = this.relativeFile(root, uri);
                if (file)
                    this.publish(root, { eventType: 'file_created', files: [file], status: 'created' });
            }
        }));
        this.disposables.push(vscode.workspace.onDidDeleteFiles((event) => {
            for (const uri of event.files) {
                const root = this.workspaceForUri(uri);
                const file = this.relativeFile(root, uri);
                if (file)
                    this.publish(root, { eventType: 'file_deleted', files: [file], status: 'deleted' });
            }
        }));
        this.disposables.push(vscode.workspace.onDidRenameFiles((event) => {
            for (const item of event.files) {
                const root = this.workspaceForUri(item.newUri);
                const oldFile = this.relativeFile(root, item.oldUri);
                const newFile = this.relativeFile(root, item.newUri);
                const files = [oldFile, newFile].filter(Boolean);
                if (files.length)
                    this.publish(root, { eventType: 'file_renamed', files, status: 'renamed' });
            }
        }));
    }
    registerDiagnostics() {
        this.disposables.push(vscode.languages.onDidChangeDiagnostics((event) => {
            for (const uri of event.uris) {
                if (uri.scheme !== 'file')
                    continue;
                const key = uri.toString();
                const prior = this.diagTimers.get(key);
                if (prior)
                    clearTimeout(prior);
                this.diagTimers.set(key, setTimeout(() => {
                    this.diagTimers.delete(key);
                    const root = this.workspaceForUri(uri);
                    const file = this.relativeFile(root, uri);
                    if (!file)
                        return;
                    const diagnostics = vscode.languages.getDiagnostics(uri);
                    const errors = diagnostics.filter((item) => item.severity === vscode.DiagnosticSeverity.Error).length;
                    const warnings = diagnostics.filter((item) => item.severity === vscode.DiagnosticSeverity.Warning).length;
                    const signature = `${errors}:${warnings}`;
                    if (this.lastDiagnostics.get(key) === signature)
                        return;
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
    registerTerminalCommands() {
        const windowApi = vscode.window;
        if (typeof windowApi.onDidEndTerminalShellExecution !== 'function')
            return;
        this.disposables.push(windowApi.onDidEndTerminalShellExecution((event) => {
            const execution = event?.execution;
            const shellIntegration = event?.terminal?.shellIntegration;
            const commandLine = execution?.commandLine;
            const cwd = String(shellIntegration?.cwd?.fsPath ?? shellIntegration?.cwd?.path ?? '');
            let root = this.roots()[0] ?? '';
            if (cwd) {
                const folder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(cwd));
                if (folder)
                    root = folder.uri.fsPath;
            }
            const command = String(commandLine?.value ?? commandLine ?? '');
            if (!root || !command.trim())
                return;
            this.publish(root, {
                eventType: 'terminal_command',
                command,
                status: typeof event?.exitCode === 'number' ? (event.exitCode === 0 ? 'passed' : 'failed') : 'finished',
                metrics: typeof event?.exitCode === 'number' ? { exit_code: event.exitCode } : undefined,
            });
        }));
    }
    dispose() {
        for (const timer of this.diagTimers.values())
            clearTimeout(timer);
        this.diagTimers.clear();
        for (const root of this.roots()) {
            this.publish(root, { eventType: 'workspace_session_ended', status: 'closed' });
        }
        while (this.disposables.length)
            this.disposables.pop()?.dispose();
    }
}
exports.CompanionWorkspaceObserver = CompanionWorkspaceObserver;
const EXTERNAL_EVENT_TYPES = new Set([
    'user_intent', 'task_started', 'phase_changed', 'plan_step', 'phase_summary',
    'tool_started', 'tool_finished', 'file_changed', 'test_result', 'diagnostics',
    'task_completed', 'task_failed', 'task_cancelled',
]);
/**
 * Adapter nhỏ cho coding extension khác. Adapter bên kia có thể gọi:
 * vscode.commands.executeCommand('erisCode.companion.observeExternalAgent', payload)
 * mà không cần Eris sở hữu/control agent đó.
 */
function registerExternalAgentObservationBridge(context, bridge) {
    context.subscriptions.push(vscode.commands.registerCommand('erisCode.companion.observeExternalAgent', (raw) => {
        if (!raw || typeof raw !== 'object')
            return false;
        const payload = raw;
        const eventType = String(payload.event_type ?? payload.eventType ?? '');
        if (!EXTERNAL_EVENT_TYPES.has(eventType))
            return false;
        const roots = (vscode.workspace.workspaceFolders ?? []).map((item) => item.uri.fsPath);
        if (!roots.length)
            return false;
        const requested = String(payload.workspace ?? '');
        const workspace = roots.find((root) => path.resolve(root) === path.resolve(requested)) ?? roots[0];
        const actorRaw = String(payload.actor ?? 'external_agent');
        const actor = ['explorer', 'planner', 'coder', 'reviewer', 'validation', 'external_agent'].includes(actorRaw)
            ? actorRaw
            : 'external_agent';
        bridge.publishCodingObservation((0, codingObservation_1.createCodingObservation)({
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
                ? payload.metrics
                : undefined,
        }));
        return true;
    }));
}
//# sourceMappingURL=companionWorkspaceObserver.js.map