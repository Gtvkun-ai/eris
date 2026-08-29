import { spawn, ChildProcessWithoutNullStreams } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';

export type RuntimeState = 'stopped' | 'starting' | 'running' | 'external' | 'error';

/**
 * Quản lý duy nhất process GitPilot mà Eris Code tự khởi động.
 *
 * V78 invariant:
 * - Extension KHÔNG khởi động Eris Desktop.
 * - Nếu user tự chạy GitPilot thì extension chỉ kết nối, không kill process đó.
 * - Trong monorepo Eris, ưu tiên venv local của services/gitpilot để source đang
 *   sửa chính là source được chạy; tránh vô tình gọi một bản PyPI khác trên PATH.
 */
export class GitPilotRuntimeManager implements vscode.Disposable {
  private child?: ChildProcessWithoutNullStreams;
  private readonly output = vscode.window.createOutputChannel('Eris Code · GitPilot', { log: true });
  private state: RuntimeState = 'stopped';
  private readonly stateEmitter = new vscode.EventEmitter<RuntimeState>();
  readonly onStateChanged = this.stateEmitter.event;

  constructor(private readonly context: vscode.ExtensionContext) {}

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
    if (!vscode.workspace.isTrusted) {
      throw new Error('Workspace chưa được Trust; Eris Code không tự launch GitPilot vì backend có quyền chạy tool trong workspace.');
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
    const resolved = this.resolveCommand();
    const url = new URL(this.serverUrl);
    const port = Number(url.port || (url.protocol === 'https:' ? 443 : 80));
    const args = ['serve', '--port', String(port)];
    this.output.appendLine(`Starting managed GitPilot: ${resolved.command} ${args.join(' ')}`);
    if (resolved.reason) this.output.appendLine(`Resolved command: ${resolved.reason}`);
    this.setState('starting');

    const child = spawn(resolved.command, args, {
      cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
      env: { ...process.env, GITPILOT_PORT: String(port) },
      // Với executable tuyệt đối trong .venv không cần shell. Khi fallback sang
      // command trên PATH ở Windows thì shell giúp resolve gitpilot.cmd/exe.
      shell: resolved.useShell,
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

  private resolveCommand(): { command: string; useShell: boolean; reason: string } {
    const configured = String(vscode.workspace.getConfiguration('erisCode.gitpilot').get<string>('command', '') ?? '').trim();
    if (configured) {
      return { command: configured, useShell: process.platform === 'win32', reason: 'erisCode.gitpilot.command' };
    }

    const vendored = this.findVendoredGitPilot();
    if (vendored) {
      return { command: vendored, useShell: false, reason: 'services/gitpilot/.venv trong monorepo' };
    }

    return { command: 'gitpilot', useShell: process.platform === 'win32', reason: 'gitpilot trên PATH' };
  }

  private findVendoredGitPilot(): string | undefined {
    const candidates: string[] = [];
    const extensionRoot = this.context.extensionUri.fsPath;
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

    // Khi chạy Extension Development Host, extension nằm ở src/vscode-extension.
    // Khi cài VSIX, candidate này đơn giản không tồn tại và ta fallback sang PATH.
    candidates.push(path.resolve(extensionRoot, '..', '..', 'services', 'gitpilot'));

    if (workspaceRoot) {
      let cursor = path.resolve(workspaceRoot);
      for (let i = 0; i < 6; i += 1) {
        candidates.push(path.join(cursor, 'services', 'gitpilot'));
        const parent = path.dirname(cursor);
        if (parent === cursor) break;
        cursor = parent;
      }
    }

    const exeName = process.platform === 'win32' ? 'gitpilot.exe' : 'gitpilot';
    const relative = process.platform === 'win32'
      ? path.join('.venv', 'Scripts', exeName)
      : path.join('.venv', 'bin', exeName);

    for (const root of candidates) {
      const executable = path.join(root, relative);
      if (fs.existsSync(executable)) return executable;
    }
    return undefined;
  }

  private async waitReady(): Promise<void> {
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      if (await this.probe(1000)) {
        this.setState(this.child ? 'running' : 'external');
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 350));
    }
    this.showLogs();
    throw new Error('GitPilot không sẵn sàng sau khi launch. Xem Output → Eris Code · GitPilot hoặc chạy setup backend V79.');
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
    const terminal = vscode.window.createTerminal({ name: 'Setup GitPilot V79' });
    terminal.show();
    const script = this.findSetupScript();
    if (script && process.platform === 'win32') {
      terminal.sendText(`powershell -ExecutionPolicy Bypass -File "${script}"`, true);
      return;
    }
    const py = process.platform === 'win32' ? 'py -3.12' : 'python3.12';
    terminal.sendText(`${py} -m pip install --upgrade gitcopilot==0.2.8`, true);
  }

  private findSetupScript(): string | undefined {
    const candidates = [
      path.resolve(this.context.extensionUri.fsPath, '..', '..', 'services', 'gitpilot', 'setup_eris_code_backend.ps1'),
    ];
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (workspaceRoot) candidates.push(path.join(workspaceRoot, 'services', 'gitpilot', 'setup_eris_code_backend.ps1'));
    return candidates.find((candidate) => fs.existsSync(candidate));
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
