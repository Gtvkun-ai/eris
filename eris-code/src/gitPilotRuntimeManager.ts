import { spawn, ChildProcessWithoutNullStreams } from 'node:child_process';
import * as vscode from 'vscode';

export type RuntimeState = 'stopped' | 'starting' | 'running' | 'external' | 'error';

export class GitPilotRuntimeManager implements vscode.Disposable {
  private child?: ChildProcessWithoutNullStreams;
  private readonly output = vscode.window.createOutputChannel('Eris Code · GitPilot', { log: true });
  private state: RuntimeState = 'stopped';
  private readonly stateEmitter = new vscode.EventEmitter<RuntimeState>();
  readonly onStateChanged = this.stateEmitter.event;

  get runtimeState(): RuntimeState { return this.state; }
  get serverUrl(): string {
    return String(vscode.workspace.getConfiguration('erisCode.gitpilot').get<string>('serverUrl', 'http://127.0.0.1:8000')).replace(/\/$/, '');
  }

  async probe(timeoutMs = 1200): Promise<boolean> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${this.serverUrl}/api/status`, { signal: controller.signal });
      return response.ok;
    } catch {
      return false;
    } finally {
      clearTimeout(timer);
    }
  }

  async ensureStarted(options: { allowLaunch?: boolean } = {}): Promise<void> {
    if (await this.probe()) {
      this.setState(this.child ? 'running' : 'external');
      return;
    }
    if (options.allowLaunch === false || !this.canAutoLaunch()) {
      throw new Error(`GitPilot backend không khả dụng tại ${this.serverUrl}.`);
    }
    if (this.child && !this.child.killed) {
      await this.waitReady();
      return;
    }
    this.startOwned();
    await this.waitReady();
  }

  private canAutoLaunch(): boolean {
    const config = vscode.workspace.getConfiguration('erisCode.gitpilot');
    if (!config.get<boolean>('autoStart', true)) return false;
    try {
      const url = new URL(this.serverUrl);
      return ['127.0.0.1', 'localhost', '::1'].includes(url.hostname);
    } catch {
      return false;
    }
  }

  private startOwned(): void {
    const config = vscode.workspace.getConfiguration('erisCode.gitpilot');
    const command = String(config.get<string>('command', 'gitpilot')).trim() || 'gitpilot';
    const url = new URL(this.serverUrl);
    const port = Number(url.port || (url.protocol === 'https:' ? 443 : 80));
    const args = ['serve', '--port', String(port)];
    this.output.appendLine(`Starting managed GitPilot: ${command} ${args.join(' ')}`);
    this.setState('starting');
    const child = spawn(command, args, {
      cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
      env: { ...process.env, GITPILOT_PORT: String(port) },
      shell: process.platform === 'win32',
      windowsHide: true,
    });
    this.child = child;
    child.stdout.on('data', (chunk) => this.output.append(String(chunk)));
    child.stderr.on('data', (chunk) => this.output.append(String(chunk)));
    child.on('error', (error) => {
      this.output.appendLine(`GitPilot process error: ${String(error)}`);
      this.setState('error');
    });
    child.on('exit', (code, signal) => {
      this.output.appendLine(`GitPilot exited code=${String(code)} signal=${String(signal)}`);
      if (this.child === child) this.child = undefined;
      if (this.state !== 'stopped') this.setState(code === 0 ? 'stopped' : 'error');
    });
  }

  private async waitReady(): Promise<void> {
    const deadline = Date.now() + 25_000;
    while (Date.now() < deadline) {
      if (await this.probe(1000)) {
        this.setState(this.child ? 'running' : 'external');
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 350));
    }
    this.showLogs();
    throw new Error('GitPilot không sẵn sàng sau khi launch. Chạy `gitpilot doctor` hoặc xem Output → Eris Code · GitPilot.');
  }

  async restart(): Promise<void> {
    await this.stopOwned();
    await this.ensureStarted({ allowLaunch: true });
  }

  async stopOwned(): Promise<void> {
    const child = this.child;
    this.child = undefined;
    if (!child || child.killed) {
      this.setState('stopped');
      return;
    }
    child.kill();
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => { try { child.kill('SIGKILL'); } catch {} resolve(); }, 1800);
      child.once('exit', () => { clearTimeout(timer); resolve(); });
    });
    this.setState('stopped');
  }

  showLogs(): void { this.output.show(true); }

  openInstallTerminal(): void {
    const terminal = vscode.window.createTerminal({ name: 'Install GitPilot' });
    terminal.show();
    const py = process.platform === 'win32' ? 'py -3.12' : 'python3.12';
    terminal.sendText(`${py} -m pip install --upgrade gitcopilot==0.2.7`, true);
  }

  private setState(state: RuntimeState): void {
    if (this.state === state) return;
    this.state = state;
    this.stateEmitter.fire(state);
  }

  dispose(): void {
    void this.stopOwned();
    this.stateEmitter.dispose();
    this.output.dispose();
  }
}
