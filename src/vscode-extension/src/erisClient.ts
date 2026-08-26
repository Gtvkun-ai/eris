import * as crypto from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { DiscoveryRecord, ErisServiceManager } from './serviceManager';

type JsonRecord = Record<string, any>;

type DirectApiConfig = {
  provider: 'deepseek' | 'gemini';
  baseUrl: string;
  apiKey: string;
  model: string;
};

type DirectApiResult =
  | { status: 'sent' }
  | { status: 'unconfigured' }
  | { status: 'failed'; error: Error };

type ConnectionMode = 'auto' | 'service' | 'directApi';

export type ConnectionState = 'disconnected' | 'connecting' | 'connected';

/**
 * Socket nằm ở extension host, tuyệt đối không nằm trong Webview.
 * HTML chat vì thế không thể đọc token, file system hay VS Code API trực tiếp.
 */
export class ErisClient implements vscode.Disposable {
  private socket?: WebSocket;
  private state: ConnectionState = 'disconnected';
  private ready = false;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private intentionalClose = false;
  private connectPromise?: Promise<void>;
  private reconnectAttempts = 0;
  private readonly sessionId: string;
  private readonly eventEmitter = new vscode.EventEmitter<JsonRecord>();
  private readonly stateEmitter = new vscode.EventEmitter<ConnectionState>();

  readonly onEvent = this.eventEmitter.event;
  readonly onStateChanged = this.stateEmitter.event;

  constructor(
    private readonly extensionContext: vscode.ExtensionContext,
    private readonly serviceManager: ErisServiceManager,
  ) {
    // Session/cursor phải theo VS Code workspace window. Dùng globalState sẽ làm
    // hai cửa sổ repo khác nhau nhận chung event và còn có thể skip replay của nhau.
    const persisted = extensionContext.workspaceState.get<string>('eris.sessionId', '').trim();
    this.sessionId = persisted || `vscode_${crypto.randomUUID()}`;
    if (!persisted) {
      void extensionContext.workspaceState.update('eris.sessionId', this.sessionId);
    }
  }

  get connectionState(): ConnectionState {
    return this.state;
  }

  async connect(force = false): Promise<void> {
    if (this.ready && this.socket?.readyState === WebSocket.OPEN && !force) {
      return;
    }
    if (this.connectPromise && !force) {
      return this.connectPromise;
    }
    if (force) {
      this.closeSocket();
    }
    this.intentionalClose = false;
    this.connectPromise = this.doConnect().catch((error) => {
      // Không cứ reconnect vô hạn khi service chưa sẵn sàng, launcher sai, hoặc
      // autoStart bị tắt. Giới hạn thử lại để extension không biến thành loop vô tận.
      this.ready = false;
      this.setState('disconnected');
      if (!this.intentionalClose && this.reconnectAttempts < 3) {
        this.scheduleReconnect();
      }
      throw error;
    }).finally(() => {
      this.connectPromise = undefined;
    });
    return this.connectPromise;
  }

  private async connectExisting(force = false): Promise<void> {
    if (this.ready && this.socket?.readyState === WebSocket.OPEN && !force) {
      return;
    }
    if (force) {
      this.closeSocket();
    }
    const discovery = await this.serviceManager.readDiscovery();
    return this.doConnect(discovery, false);
  }

  private async doConnect(discovery?: DiscoveryRecord, allowReconnect = true): Promise<void> {
    this.setState('connecting');
    const resolvedDiscovery = discovery ?? await this.serviceManager.ensureStarted();
    await new Promise<void>((resolve, reject) => {
      // VS Code 1.100+ chạy extension host trên Node hiện đại; dùng WebSocket
      // chuẩn của runtime để extension không phải kéo thêm package `ws` chỉ cho
      // một kết nối localhost. Ít dependency hơn = đóng gói/test đỡ khổ hơn.
      const socket = new WebSocket(resolvedDiscovery.endpoint);
      this.socket = socket;
      let settled = false;
      const fail = (error: Error) => {
        if (!settled) {
          settled = true;
          reject(error);
        }
      };
      const timeout = setTimeout(() => fail(new Error('eris_service_handshake_timeout')), 7000);

      socket.addEventListener('open', () => {
        this.resetReconnectState();
        const lastEventSeq = this.extensionContext.workspaceState.get<number>('eris.lastEventSeq', 0);
        socket.send(JSON.stringify({
          type: 'session.hello',
          protocol: 'eris.ide.v2',
          token: resolvedDiscovery.token,
          sessionId: this.sessionId,
          client: 'eris-vscode',
          lastEventSeq,
          capabilities: [
            'context.current',
            'context.selection',
            'context.problems',
            'context.git',
            'context.workspace',
            'context.openEditors',
            'context.terminal.recent',
            'context.attachments.file',
            'context.attachments.image',
            'editor.openFile',
            'editor.openDiff',
            'editor.focusProblems',
            'editor.showSourceControl',
          ],
        }));
      });

      socket.addEventListener('message', (event) => {
        try {
          const raw = typeof event.data === 'string' ? event.data : String(event.data ?? '');
          const message = JSON.parse(raw) as JsonRecord;
          if (message.type === 'session.ready') {
            clearTimeout(timeout);
            this.ready = true;
            this.setState('connected');
            if (!settled) {
              settled = true;
              resolve();
            }
          }
          const seq = Number(message.seq ?? message.lastEventSeq ?? 0);
          if (Number.isFinite(seq) && seq > 0) {
            const previous = this.extensionContext.workspaceState.get<number>('eris.lastEventSeq', 0);
            if (seq > previous) {
              void this.extensionContext.workspaceState.update('eris.lastEventSeq', seq);
            }
          }
          this.eventEmitter.fire(message);
        } catch (error) {
          this.eventEmitter.fire({ type: 'client.error', message: String(error) });
        }
      });

      socket.addEventListener('error', () => {
        clearTimeout(timeout);
        fail(new Error('eris_service_websocket_error'));
      });
      socket.addEventListener('close', () => {
        clearTimeout(timeout);
        this.ready = false;
        this.setState('disconnected');
        if (!settled) {
          fail(new Error('eris_service_disconnected_before_ready'));
        }
        if (allowReconnect && !this.intentionalClose) {
          this.scheduleReconnect();
        }
      });
    });
  }

  async createThread(threadId: string): Promise<void> {
    await this.connect();
    this.send({ type: 'session.create', protocol: 'eris.ide.v2', threadId });
  }

  async requestTasks(): Promise<void> {
    await this.connect();
    this.send({ type: 'task.list', protocol: 'eris.ide.v2' });
  }

  async requestTask(taskId: string): Promise<void> {
    await this.connect();
    this.send({ type: 'task.get', protocol: 'eris.ide.v2', taskId });
  }

  async requestThreadHistory(threadId: string): Promise<void> {
    await this.connect();
    this.send({ type: 'thread.history', protocol: 'eris.ide.v2', threadId });
  }

  async sendUserMessage(content: string, args: {
    threadId: string;
    taskMode?: 'auto' | 'plan' | 'execute' | 'inspect';
    autopilot?: boolean;
    workspaceRef?: string;
    context?: Record<string, unknown>;
  }): Promise<void> {
    const payload = {
      type: 'message.user',
      protocol: 'eris.ide.v2',
      content,
      threadId: args.threadId,
      taskMode: args.taskMode ?? 'auto',
      autopilot: args.autopilot !== false,
      workspaceRef: args.workspaceRef ?? '',
      context: args.context ?? {},
    };
    const mode = this.connectionMode();
    if (mode === 'directApi') {
      const direct = await this.sendDirectApiMessage(content, args, 'direct_api_mode');
      if (direct.status === 'sent') {
        return;
      }
      if (direct.status === 'failed') {
        throw direct.error;
      }
      throw new Error('Direct API mode is enabled but no direct API config was found.');
    }
    if (mode === 'auto') {
      try {
        await this.connectExisting();
        this.send(payload);
        return;
      } catch (error) {
        const direct = await this.sendDirectApiMessage(content, args, error);
        if (direct.status === 'sent') {
          return;
        }
      }
    }
    try {
      await this.connect();
      this.send(payload);
    } catch (error) {
      const direct = await this.sendDirectApiMessage(content, args, error);
      if (direct.status === 'sent') {
        return;
      }
      if (direct.status === 'failed') {
        throw direct.error;
      }
      throw error;
    }
  }

  async resolveInterrupt(taskId: string, response: unknown): Promise<void> {
    await this.connect();
    this.send({ type: 'interrupt.resolve', protocol: 'eris.ide.v2', taskId, response });
  }

  async controlTask(
    taskId: string,
    action: string,
    text = '',
    checkpointId = '',
    context: Record<string, unknown> = {},
    changeSetId = '',
  ): Promise<void> {
    await this.connect();
    this.send({
      type: 'task.control',
      protocol: 'eris.ide.v2',
      taskId,
      action,
      text,
      checkpointId,
      changeSetId,
      context,
    });
  }

  async reportEditorCommandResult(
    taskId: string,
    requestId: string,
    command: string,
    success: boolean,
    message = '',
  ): Promise<void> {
    await this.connect();
    this.send({
      type: 'editor.command.result',
      protocol: 'eris.ide.v2',
      taskId,
      requestId,
      command,
      success,
      message,
    });
  }

  async reportIdeResponse(
    taskId: string,
    requestId: string,
    method: string,
    success: boolean,
    data: unknown = {},
    error = '',
  ): Promise<void> {
    await this.connect();
    this.send({
      type: 'ide.response',
      protocol: 'eris.ide.v2',
      taskId,
      requestId,
      method,
      success,
      data,
      error,
    });
  }

  async reportDocumentSaved(path: string, content: string): Promise<void> {
    await this.connect();
    this.send({
      type: 'editor.document.saved',
      protocol: 'eris.ide.v2',
      path,
      content,
    });
  }

  private send(payload: JsonRecord): void {
    if (!this.ready || this.socket?.readyState !== WebSocket.OPEN) {
      throw new Error('eris_service_not_connected');
    }
    this.socket.send(JSON.stringify(payload));
  }

  private connectionMode(): ConnectionMode {
    const raw = String(vscode.workspace.getConfiguration('eris.service').get<string>('connectionMode', 'auto') ?? 'auto').trim();
    if (raw === 'service' || raw === 'directApi') {
      return raw;
    }
    return 'auto';
  }

  private async sendDirectApiMessage(
    content: string,
    args: {
      threadId: string;
      taskMode?: 'auto' | 'plan' | 'execute' | 'inspect';
      autopilot?: boolean;
      workspaceRef?: string;
      context?: Record<string, unknown>;
    },
    serviceError: unknown,
  ): Promise<DirectApiResult> {
    const config = await this.resolveDirectApiConfig(args.context ?? {});
    if (!config) {
      return { status: 'unconfigured' };
    }
    const taskId = `direct_${crypto.randomUUID().slice(0, 12)}`;
    this.setState('connected');
    this.eventEmitter.fire({
      type: 'message.accepted',
      protocol: 'eris.ide.v2',
      threadId: args.threadId,
      taskId,
      status: 'direct_api',
      reason: 'service_unavailable_direct_api_fallback',
      continued: false,
    });
    this.eventEmitter.fire({
      type: 'message.user',
      taskId,
      threadId: args.threadId,
      payload: { content, attachments: [] },
    });
    this.eventEmitter.fire({
      type: 'activity.start',
      taskId,
      threadId: args.threadId,
      payload: {
        summary: `Direct API: ${config.provider} / ${config.model}`,
        detail: directApiDetail(serviceError),
        status: 'running',
      },
    });

    try {
      const answer = await this.callDirectApi(config, content, args);
      this.eventEmitter.fire({
        type: 'message.assistant',
        taskId,
        threadId: args.threadId,
        payload: { content: answer },
      });
      this.eventEmitter.fire({
        type: 'activity.end',
        taskId,
        threadId: args.threadId,
        payload: { summary: 'Direct API complete', detail: 'Không dùng Eris Service/IDE bridge trong lượt này.', status: 'completed' },
      });
      return { status: 'sent' };
    } catch (error) {
      const directError = enrichDirectApiError(error, config);
      this.eventEmitter.fire({
        type: 'activity.end',
        taskId,
        threadId: args.threadId,
        payload: { summary: 'Direct API failed', detail: directError.message, status: 'failed' },
      });
      this.eventEmitter.fire({ type: 'client.error', message: `Direct API failed: ${directError.message}` });
      return { status: 'failed', error: directError };
    } finally {
      this.setState('disconnected');
    }
  }

  private async resolveDirectApiConfig(context: Record<string, unknown>): Promise<DirectApiConfig | null> {
    const values = await this.loadRuntimeConfig();
    const requestedModel = String(context.webaiModel ?? context.model ?? '').trim();
    const remoteProvider = (values.ERIS_REMOTE_PROVIDER || 'deepseek').toLowerCase();
    const wantsDeepSeekWeb = remoteProvider.includes('deepseek_web') || remoteProvider.includes('ds2api') || remoteProvider.includes('whale');
    const officialDeepSeekKey = values.DEEPSEEK_API_KEY || values.ERIS_REMOTE_API_KEY;
    const localDeepSeekKey = values.ERIS_DS_COMPANION_API_KEY || values.ERIS_DS2API_API_KEY || values.ERIS_DS_API_KEY;
    const geminiKey = values.GEMINI_API_KEY || values.ERIS_SPEECH_API_KEY;

    if ((remoteProvider.includes('gemini') || requestedModel.startsWith('gemini-')) && geminiKey) {
      return {
        provider: 'gemini',
        baseUrl: values.ERIS_SPEECH_BASE_URL || 'https://generativelanguage.googleapis.com/v1beta',
        apiKey: geminiKey,
        model: requestedModel && requestedModel !== 'auto' ? requestedModel : (values.ERIS_SPEECH_MODEL || 'gemini-2.5-flash'),
      };
    }
    if (officialDeepSeekKey) {
      const rawModel = requestedModel && requestedModel !== 'auto' ? requestedModel : (values.ERIS_REMOTE_MODEL || values.ERIS_DS_MODEL || 'deepseek-v4-flash');
      const baseUrl = normalizeOpenAiBaseUrl(hostedDeepSeekBaseUrl(values));
      return {
        provider: 'deepseek',
        baseUrl,
        apiKey: officialDeepSeekKey,
        model: normalizeDeepSeekModelForBase(rawModel, baseUrl),
      };
    }
    if (localDeepSeekKey) {
      const rawModel = requestedModel && requestedModel !== 'auto' ? requestedModel : (values.ERIS_REMOTE_MODEL || values.ERIS_DS_MODEL || 'deepseek-v4-flash');
      const configuredBaseUrl = wantsDeepSeekWeb
        ? (values.ERIS_DS_COMPANION_BASE_URL || values.ERIS_DS2API_BASE_URL || values.ERIS_DS_BASE_URL)
        : values.ERIS_REMOTE_BASE_URL;
      const baseUrl = normalizeOpenAiBaseUrl(configuredBaseUrl || 'https://api.deepseek.com/v1');
      return {
        provider: 'deepseek',
        baseUrl,
        apiKey: localDeepSeekKey,
        model: normalizeDeepSeekModelForBase(rawModel, baseUrl),
      };
    }
    if (geminiKey) {
      return {
        provider: 'gemini',
        baseUrl: values.ERIS_SPEECH_BASE_URL || 'https://generativelanguage.googleapis.com/v1beta',
        apiKey: geminiKey,
        model: values.ERIS_SPEECH_MODEL || 'gemini-2.5-flash',
      };
    }
    return null;
  }

  private async callDirectApi(
    config: DirectApiConfig,
    content: string,
    args: { taskMode?: 'auto' | 'plan' | 'execute' | 'inspect'; context?: Record<string, unknown> },
  ): Promise<string> {
    const mode = args.taskMode === 'plan' ? 'planning-only' : args.taskMode === 'inspect' ? 'inspect-only' : 'auto-intent';
    const contextSummary = compactContext(args.context ?? {});
    const system = [
      'You are Eris inside a VS Code sidebar.',
      'Answer in Vietnamese by default.',
      'You are running in direct external API mode because the local Eris Service/IDE bridge is unavailable.',
      'Do not claim you edited files, ran commands, opened diffs, or inspected live IDE state unless the user provided that content directly.',
      `Mode: ${mode}.`,
      mode === 'planning-only' ? 'Planning-only: analyze the supplied context and return a concrete implementation plan. Do not claim file edits or execution.' : '',
      mode === 'auto-intent' ? 'Infer intent yourself: answer analysis/review questions without pretending to edit; when the user clearly requests a change, explain what the local agent would need to execute.' : '',
      contextSummary ? `Available lightweight IDE context:\n${contextSummary}` : '',
    ].filter(Boolean).join('\n');

    if (config.provider === 'gemini') {
      return this.callGeminiDirect(config, system, content);
    }
    return this.callOpenAiCompatibleDirect(config, system, content);
  }

  private async callOpenAiCompatibleDirect(config: DirectApiConfig, system: string, content: string): Promise<string> {
    const base = config.baseUrl.replace(/\/+$/, '');
    const response = await fetch(`${base}/chat/completions`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${config.apiKey}`,
      },
      body: JSON.stringify({
        model: config.model,
        messages: [
          { role: 'system', content: system },
          { role: 'user', content },
        ],
        temperature: 0.35,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${JSON.stringify(data).slice(0, 900)}`);
    }
    return extractOpenAiCompatibleText(data);
  }

  private async callGeminiDirect(config: DirectApiConfig, system: string, content: string): Promise<string> {
    const base = config.baseUrl.replace(/\/+$/, '');
    const url = `${base}/models/${encodeURIComponent(config.model)}:generateContent?key=${encodeURIComponent(config.apiKey)}`;
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: system }] },
        contents: [{ role: 'user', parts: [{ text: content }] }],
        generationConfig: { temperature: 0.35 },
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${JSON.stringify(data).slice(0, 900)}`);
    }
    const parts = data?.candidates?.[0]?.content?.parts;
    if (Array.isArray(parts)) {
      const text = parts.map((part) => String(part?.text ?? '')).join('').trim();
      if (text) {
        return text;
      }
    }
    const finishReason = String(data?.candidates?.[0]?.finishReason ?? '').trim();
    const blockReason = String(data?.promptFeedback?.blockReason ?? '').trim();
    const detail = [finishReason ? `finishReason=${finishReason}` : '', blockReason ? `blockReason=${blockReason}` : '']
      .filter(Boolean)
      .join(', ');
    throw new Error(`Direct API returned empty Gemini content${detail ? ` (${detail})` : ''}: ${JSON.stringify(summarizeResponseShape(data)).slice(0, 500)}`);
  }

  private async loadRuntimeConfig(): Promise<Record<string, string>> {
    const roots = unique([
      ...(vscode.workspace.workspaceFolders ?? []).map((folder) => folder.uri.fsPath),
      path.join(os.homedir(), 'Documents', 'eris'),
    ]);
    const output: Record<string, string> = {};
    for (const [key, value] of Object.entries(process.env)) {
      if (typeof value === 'string') output[key] = value;
    }
    for (const root of roots) {
      Object.assign(output, await readEnvFile(path.join(root, '.env')));
      Object.assign(output, await readSecretsFile(path.join(root, 'config', 'secrets.json')));
    }
    return output;
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= 3) {
      return;
    }
    this.reconnectAttempts += 1;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      void this.connect().catch(() => undefined);
    }, 1500);
  }

  private closeSocket(): void {
    this.ready = false;
    if (this.socket) {
      try {
        this.socket.close();
      } catch {
        // Socket đã chết thì thôi, shutdown không cần thêm một nghi lễ nữa.
      }
    }
    this.socket = undefined;
  }

  private resetReconnectState(): void {
    this.reconnectAttempts = 0;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = undefined;
    }
  }

  private setState(state: ConnectionState): void {
    if (this.state === state) {
      return;
    }
    this.state = state;
    this.stateEmitter.fire(state);
  }

  dispose(): void {
    this.intentionalClose = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = undefined;
    }
    this.closeSocket();
    this.eventEmitter.dispose();
    this.stateEmitter.dispose();
  }
}

async function readEnvFile(filePath: string): Promise<Record<string, string>> {
  try {
    const raw = await fs.readFile(filePath, 'utf8');
    const result: Record<string, string> = {};
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const index = trimmed.indexOf('=');
      if (index <= 0) continue;
      const key = trimmed.slice(0, index).trim();
      let value = trimmed.slice(index + 1).trim();
      if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
        value = value.slice(1, -1);
      }
      if (key && value && !value.startsWith('PASTE_')) {
        result[key] = value;
      }
    }
    return result;
  } catch {
    return {};
  }
}

async function readSecretsFile(filePath: string): Promise<Record<string, string>> {
  try {
    const payload = JSON.parse(await fs.readFile(filePath, 'utf8')) as unknown;
    if (!payload || typeof payload !== 'object') return {};
    const root = payload as Record<string, unknown>;
    const result: Record<string, string> = {};
    collectStringMap(result, root.env);
    collectStringMap(result, root.api_keys);
    collectProviders(result, root.providers);
    return result;
  } catch {
    return {};
  }
}

function collectStringMap(target: Record<string, string>, value: unknown): void {
  if (!value || typeof value !== 'object') return;
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    if (typeof raw === 'string' && raw.trim() && !raw.trim().startsWith('PASTE_')) {
      target[key] = raw.trim();
    }
  }
}

function collectProviders(target: Record<string, string>, providers: unknown): void {
  if (!providers || typeof providers !== 'object') return;
  const root = providers as Record<string, unknown>;
  const deepseek = nestedRecord(root.deepseek, 'remote_main') ?? nestedRecord(root.deepseek, 'default');
  if (deepseek) {
    if (typeof deepseek.base_url === 'string') target.ERIS_REMOTE_BASE_URL = deepseek.base_url;
    if (typeof deepseek.model === 'string') target.ERIS_REMOTE_MODEL = deepseek.model;
    if (typeof deepseek.api_key === 'string' && deepseek.api_key.trim()) target.ERIS_REMOTE_API_KEY = deepseek.api_key.trim();
  }
  const gemini = nestedRecord(root.gemini, 'speech') ?? nestedRecord(root.gemini, 'default');
  if (gemini) {
    if (typeof gemini.base_url === 'string') target.ERIS_SPEECH_BASE_URL = gemini.base_url;
    if (typeof gemini.model === 'string') target.ERIS_SPEECH_MODEL = gemini.model;
  }
}

function nestedRecord(value: unknown, key: string): Record<string, unknown> | null {
  if (!value || typeof value !== 'object') return null;
  const child = (value as Record<string, unknown>)[key];
  return child && typeof child === 'object' ? child as Record<string, unknown> : null;
}

function normalizeOpenAiBaseUrl(value: string): string {
  const clean = String(value || '').trim().replace(/\/+$/, '');
  if (!clean) return 'https://api.deepseek.com/v1';
  if (/api\.deepseek\.com$/i.test(clean)) return `${clean}/v1`;
  return clean;
}

function hostedDeepSeekBaseUrl(values: Record<string, string>): string {
  const candidates = [
    values.ERIS_EXTENSION_DEEPSEEK_BASE_URL,
    values.ERIS_REMOTE_BASE_URL,
  ];
  for (const candidate of candidates) {
    const clean = String(candidate || '').trim();
    if (clean && !/^https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?(?:\/|$)/i.test(clean)) {
      return clean;
    }
  }
  return 'https://api.deepseek.com/v1';
}

function enrichDirectApiError(error: unknown, config: DirectApiConfig): Error {
  const raw = error instanceof Error ? error : new Error(String(error));
  const endpoint = config.provider === 'gemini'
    ? `${config.baseUrl.replace(/\/+$/, '')}/models/${config.model}:generateContent`
    : `${config.baseUrl.replace(/\/+$/, '')}/chat/completions`;
  const localHint = /^https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?(?:\/|$)/i.test(config.baseUrl)
    ? ' Local endpoint is not reachable; start the matching local pool/service or switch Eris to the hosted API/provider.'
    : '';
  return new Error(`${raw.message || String(raw)} while calling ${endpoint}.${localHint}`);
}

function directApiDetail(reason: unknown): string {
  if (String(reason) === 'direct_api_mode') {
    return 'Direct API mode; local Eris Service/IDE bridge is not required for this turn.';
  }
  return `Local Eris Service/IDE bridge unavailable; using external API only. ${String(reason).slice(0, 220)}`;
}

function normalizeDeepSeekModelForBase(model: string, baseUrl: string): string {
  const clean = String(model || '').trim();
  if (!/api\.deepseek\.com/i.test(baseUrl)) return clean || 'deepseek-v4-flash';
  if (/^deepseek-v4-flash$/i.test(clean)) return 'deepseek-chat';
  if (/^deepseek-v4-pro$/i.test(clean)) return 'deepseek-reasoner';
  return clean || 'deepseek-chat';
}

function extractOpenAiCompatibleText(data: any): string {
  const choice = data?.choices?.[0];
  const message = choice?.message;
  const content = message?.content;
  if (typeof content === 'string' && content.trim()) {
    return content.trim();
  }
  if (Array.isArray(content)) {
    const text = content.map((part) => {
      if (typeof part === 'string') return part;
      return String(part?.text ?? part?.content ?? '');
    }).join('').trim();
    if (text) {
      return text;
    }
  }
  const fallback = String(data?.output_text ?? data?.text ?? '').trim();
  if (fallback) {
    return fallback;
  }
  const finishReason = String(choice?.finish_reason ?? choice?.finishReason ?? '').trim();
  throw new Error(`Direct API returned empty chat content${finishReason ? ` (finish_reason=${finishReason})` : ''}: ${JSON.stringify(summarizeResponseShape(data)).slice(0, 500)}`);
}

function summarizeResponseShape(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.slice(0, 3).map(summarizeResponseShape);
  }
  if (!value || typeof value !== 'object') {
    return typeof value;
  }
  const output: Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    if (key.toLowerCase().includes('key') || key.toLowerCase().includes('token')) continue;
    if (typeof raw === 'string') {
      output[key] = raw.slice(0, 120);
    } else if (Array.isArray(raw)) {
      output[key] = raw.slice(0, 2).map(summarizeResponseShape);
    } else if (raw && typeof raw === 'object') {
      output[key] = summarizeResponseShape(raw);
    } else {
      output[key] = raw;
    }
  }
  return output;
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function compactContext(context: Record<string, unknown>): string {
  const parts: string[] = [];
  const workspace = context.workspace;
  const current = context.current;
  const selection = context.selection;
  const git = context.git;
  if (workspace && typeof workspace === 'object') {
    const value = workspace as Record<string, unknown>;
    parts.push(`workspace=${String(value.name ?? value.path ?? '').slice(0, 180)}`);
  }
  if (current && typeof current === 'object') {
    const value = current as Record<string, unknown>;
    parts.push(`current_file=${String(value.path ?? value.file ?? '').slice(0, 240)}`);
  }
  if (selection && typeof selection === 'object') {
    const value = selection as Record<string, unknown>;
    const text = String(value.text ?? '').trim();
    if (text) parts.push(`selection=${text.slice(0, 1200)}`);
  }
  if (git && typeof git === 'object') {
    const value = git as Record<string, unknown>;
    parts.push(`git_changes=${String(value.changeCount ?? value.changes ?? '').slice(0, 120)}`);
  }
  return parts.filter(Boolean).join('\n').slice(0, 2400);
}
