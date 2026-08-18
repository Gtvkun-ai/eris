import * as crypto from 'node:crypto';
import * as vscode from 'vscode';
import WebSocket from 'ws';
import { ErisServiceManager } from './serviceManager';

type JsonRecord = Record<string, any>;


export type ConnectionState = 'disconnected' | 'connecting' | 'connected';

/**
 * Socket nằm ở extension host, tuyệt đối không nằm trong Webview.
 * HTML chat vì thế không thể đọc token, file system hay VS Code API trực tiếp.
 */
export class ErisClient implements vscode.Disposable {
  private socket?: WebSocket;
  private state: ConnectionState = 'disconnected';
  private ready = false;
  private reconnectTimer?: NodeJS.Timeout;
  private intentionalClose = false;
  private connectPromise?: Promise<void>;
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
      // Auto-start có thể fail trước khi WebSocket tồn tại. Nếu chỉ reconnect ở
      // socket.on('close'), lần lỗi bootstrap đầu tiên sẽ để sidebar kẹt Connecting.
      this.ready = false;
      this.setState('disconnected');
      if (!this.intentionalClose) {
        this.scheduleReconnect();
      }
      throw error;
    }).finally(() => {
      this.connectPromise = undefined;
    });
    return this.connectPromise;
  }

  private async doConnect(): Promise<void> {
    this.setState('connecting');
    const discovery = await this.serviceManager.ensureStarted();
    await new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(discovery.endpoint, { handshakeTimeout: 5000 });
      this.socket = socket;
      let settled = false;
      const fail = (error: Error) => {
        if (!settled) {
          settled = true;
          reject(error);
        }
      };
      const timeout = setTimeout(() => fail(new Error('eris_service_handshake_timeout')), 7000);

      socket.on('open', () => {
        const lastEventSeq = this.extensionContext.workspaceState.get<number>('eris.lastEventSeq', 0);
        socket.send(JSON.stringify({
          type: 'session.hello',
          protocol: 'eris.ide.v2',
          token: discovery.token,
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
            'editor.openFile',
            'editor.openDiff',
            'editor.focusProblems',
            'editor.showSourceControl',
          ],
        }));
      });

      socket.on('message', (raw) => {
        try {
          const message = JSON.parse(raw.toString()) as JsonRecord;
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

      socket.on('error', (error) => {
        clearTimeout(timeout);
        fail(error);
      });
      socket.on('close', () => {
        clearTimeout(timeout);
        this.ready = false;
        this.setState('disconnected');
        if (!settled) {
          fail(new Error('eris_service_disconnected_before_ready'));
        }
        if (!this.intentionalClose) {
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
    taskMode?: 'execute' | 'inspect';
    workspaceRef?: string;
    context?: Record<string, unknown>;
  }): Promise<void> {
    await this.connect();
    this.send({
      type: 'message.user',
      protocol: 'eris.ide.v2',
      content,
      threadId: args.threadId,
      taskMode: args.taskMode ?? 'execute',
      workspaceRef: args.workspaceRef ?? '',
      context: args.context ?? {},
    });
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

  private send(payload: JsonRecord): void {
    if (!this.ready || this.socket?.readyState !== WebSocket.OPEN) {
      throw new Error('eris_service_not_connected');
    }
    this.socket.send(JSON.stringify(payload));
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      void this.connect().catch(() => this.scheduleReconnect());
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
