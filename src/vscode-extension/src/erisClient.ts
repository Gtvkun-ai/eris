import * as crypto from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';
import * as vscode from 'vscode';
import WebSocket from 'ws';

type JsonRecord = Record<string, any>;

interface DiscoveryRecord {
  protocol: string;
  endpoint: string;
  token: string;
  pid?: number;
}

export type ConnectionState = 'disconnected' | 'connecting' | 'connected';

/**
 * Socket nằm ở extension host, tuyệt đối không nằm trong Webview.
 * Nhờ vậy HTML chat không có quyền đọc token, file system hay workspace API.
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

  constructor(private readonly extensionContext: vscode.ExtensionContext) {
    const persisted = extensionContext.globalState.get<string>('eris.sessionId', '').trim();
    this.sessionId = persisted || `vscode_${crypto.randomUUID()}`;
    if (!persisted) {
      void extensionContext.globalState.update('eris.sessionId', this.sessionId);
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
    this.connectPromise = this.doConnect().finally(() => {
      this.connectPromise = undefined;
    });
    return this.connectPromise;
  }

  private async doConnect(): Promise<void> {
    this.setState('connecting');
    const discovery = await this.readDiscovery();
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
        const lastEventSeq = this.extensionContext.globalState.get<number>('eris.lastEventSeq', 0);
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
            'context.terminal',
            'editor.openFile',
            'editor.focusProblems',
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
          const seq = Number(message.seq ?? 0);
          if (Number.isFinite(seq) && seq > 0) {
            void this.extensionContext.globalState.update('eris.lastEventSeq', seq);
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
  ): Promise<void> {
    await this.connect();
    this.send({
      type: 'task.control',
      protocol: 'eris.ide.v2',
      taskId,
      action,
      text,
      checkpointId,
      context,
    });
  }

  private send(payload: JsonRecord): void {
    if (!this.ready || this.socket?.readyState !== WebSocket.OPEN) {
      throw new Error('eris_service_not_connected');
    }
    this.socket.send(JSON.stringify(payload));
  }

  private async readDiscovery(): Promise<DiscoveryRecord> {
    const override = process.env.ERIS_AGENT_SERVICE_DISCOVERY?.trim();
    const discoveryPath = override
      ? path.resolve(override)
      : path.join(os.homedir(), '.eris', 'agent_service.json');
    let raw: string;
    try {
      raw = await fs.readFile(discoveryPath, 'utf8');
    } catch {
      throw new Error(`Không thấy Eris Service discovery file: ${discoveryPath}`);
    }
    const payload = JSON.parse(raw) as DiscoveryRecord;
    if (payload.protocol !== 'eris.ide.v2' || !payload.endpoint || !payload.token) {
      throw new Error('Eris Service discovery file không hợp lệ.');
    }
    return payload;
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
        // Socket đang chết thì thôi, không cần biến shutdown thành một nghi lễ.
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
