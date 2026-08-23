import { ChildProcess, spawn } from 'node:child_process';
import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';
import * as vscode from 'vscode';

export interface DiscoveryRecord {
  protocol: string;
  endpoint: string;
  token: string;
  pid?: number;
}

interface DiscoveryMatch {
  path: string;
  record: DiscoveryRecord;
}

/**
 * Quản lý lifecycle Eris Service ở extension host.
 *
 * Extension ưu tiên attach vào Eris đang chạy. Chỉ khi discovery mất/stale và
 * autoStart bật nó mới launch full Eris bằng command/path người dùng cấu hình.
 * Như vậy VS Code không cần một nút bí mật ở ngoài IDE để "nhớ chạy backend".
 */
export class ErisServiceManager implements vscode.Disposable {
  private child?: ChildProcess;
  private startPromise?: Promise<DiscoveryRecord>;
  private readonly output = vscode.window.createOutputChannel('Eris Service', { log: true });

  constructor(private readonly context: vscode.ExtensionContext) {}

  async discoveryPath(): Promise<string> {
    const override = process.env.ERIS_AGENT_SERVICE_DISCOVERY?.trim();
    if (override) {
      return path.resolve(override);
    }
    try {
      const launch = await this.resolveLaunch();
      return path.join(launch.cwd, '.eris_state', 'agent_service.json');
    } catch {
      return path.join(os.homedir(), '.eris', 'agent_service.json');
    }
  }

  private async discoveryCandidates(): Promise<string[]> {
    const override = process.env.ERIS_AGENT_SERVICE_DISCOVERY?.trim();
    const candidates: string[] = [];
    if (override) {
      candidates.push(path.resolve(override));
    }
    for (const root of await this.erisRootCandidates()) {
      candidates.push(path.join(root, '.eris_state', 'agent_service.json'));
    }
    candidates.push(
      path.join(os.homedir(), 'Documents', 'GitHub', 'eris', '.eris_state', 'agent_service.json'),
      path.join(os.homedir(), 'Documents', 'eris', '.eris_state', 'agent_service.json'),
      path.join(os.homedir(), '.eris', 'agent_service.json'),
    );
    return unique(candidates.map((item) => path.resolve(item)));
  }

  async readDiscovery(): Promise<DiscoveryRecord> {
    return (await this.readDiscoveryMatch()).record;
  }

  private async readDiscoveryMatch(): Promise<DiscoveryMatch> {
    const candidates = await this.discoveryCandidates();
    let lastError: unknown;
    for (const discoveryPath of candidates) {
      try {
        const raw = await fs.readFile(discoveryPath, 'utf8');
        const payload = JSON.parse(raw) as DiscoveryRecord;
        if (payload.protocol !== 'eris.ide.v2' || !payload.endpoint || !payload.token) {
          throw new Error('Eris Service discovery file không hợp lệ.');
        }
        if (payload.pid && !processExists(payload.pid)) {
          await fs.unlink(discoveryPath).catch(() => undefined);
          lastError = new Error(`Stale Eris Service discovery file: ${discoveryPath}`);
          continue;
        }
        return { path: discoveryPath, record: payload };
      } catch (error) {
        lastError = error;
      }
    }
    throw new Error(`Không thấy Eris Service discovery file. Đã thử: ${candidates.join('; ')}. ${String(lastError ?? '')}`);
  }

  async ensureStarted(options: { allowLaunch?: boolean } = {}): Promise<DiscoveryRecord> {
    try {
      return (await this.readDiscoveryMatch()).record;
    } catch {
      // Không có discovery thì rơi xuống auto-start.
    }

    const config = vscode.workspace.getConfiguration('eris.service');
    if (!options.allowLaunch && !config.get<boolean>('autoStart', true)) {
      throw new Error('eris.service.autoStart is off; not launching Eris Service automatically.');
    }
    if (this.startPromise) {
      return this.startPromise;
    }
    this.startPromise = this.launchAndWait().finally(() => {
      this.startPromise = undefined;
    });
    return this.startPromise;
  }

  async restart(): Promise<DiscoveryRecord> {
    const ownedPid = this.context.globalState.get<number>('eris.serviceOwnedPid', 0);
    let discovery: DiscoveryRecord | undefined;
    try {
      discovery = await this.readDiscovery();
    } catch {
      discovery = undefined;
    }
    if (discovery?.pid && discovery.pid !== ownedPid && processExists(discovery.pid)) {
      throw new Error('Eris hiện do process bên ngoài VS Code quản lý; extension không tự giết process đó.');
    }
    await this.stopOwned();
    await fs.unlink(await this.discoveryPath()).catch(() => undefined);
    return this.launchAndWait();
  }

  async stopOwned(): Promise<void> {
    // Launcher (.bat/cmd) và Python service có thể là hai PID khác nhau. Lưu cả
    // hai để Restart không nhầm service do chính extension bật là "process ngoài".
    const servicePid = this.context.globalState.get<number>('eris.serviceOwnedPid', 0);
    const launcherPid = this.context.globalState.get<number>('eris.serviceLauncherPid', 0);
    const pids = uniqueNumbers([this.child?.pid ?? 0, servicePid, launcherPid]);
    for (const pid of pids) {
      try {
        if (process.platform === 'win32') {
          const killer = spawn('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
          await new Promise<void>((resolve) => killer.once('exit', () => resolve()));
        } else {
          process.kill(pid, 'SIGTERM');
        }
      } catch {
        // Process đã chết thì lifecycle coi như hoàn tất.
      }
    }
    this.child = undefined;
    await this.context.globalState.update('eris.serviceOwnedPid', undefined);
    await this.context.globalState.update('eris.serviceLauncherPid', undefined);
  }

  showLogs(): void {
    this.output.show(true);
  }

  private async launchAndWait(): Promise<DiscoveryRecord> {
    const launch = await this.resolveLaunch();
    this.output.appendLine(`[manager] starting Eris: ${launch.display}`);
    this.output.appendLine(`[manager] cwd: ${launch.cwd}`);

    const env = {
      ...process.env,
      ERIS_LAUNCHED_BY_VSCODE: '1',
      ERIS_AGENT_SERVICE_DISCOVERY: await this.discoveryPath(),
    };
    const child = spawn(launch.command, launch.args, {
      cwd: launch.cwd,
      env,
      shell: launch.shell,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    this.child = child;
    if (child.pid) {
      await this.context.globalState.update('eris.serviceLauncherPid', child.pid);
    }
    child.stdout?.on('data', (chunk) => this.output.append(String(chunk)));
    child.stderr?.on('data', (chunk) => this.output.append(String(chunk)));
    child.on('exit', (code, signal) => {
      this.output.appendLine(`[manager] Eris process exited code=${String(code)} signal=${String(signal)}`);
      if (this.child === child) {
        this.child = undefined;
      }
    });
    child.on('error', (error) => this.output.appendLine(`[manager] launch error: ${String(error)}`));

    const deadline = Date.now() + 60_000;
    let lastError: unknown;
    while (Date.now() < deadline) {
      try {
        const record = await this.readDiscovery();
        if (record.pid) {
          await this.context.globalState.update('eris.serviceOwnedPid', record.pid);
        }
        this.output.appendLine(`[manager] service ready: ${record.endpoint}`);
        return record;
      } catch (error) {
        lastError = error;
      }
      // run_eris.bat có thể chỉ bootstrap rồi thoát trong khi Python runtime còn
      // đang khởi động. Không coi launcher exit là service chết; discovery file
      // mới là source of truth. Nếu launch thật sự lỗi, timeout sẽ trả log rõ ràng.
      await delay(250);
    }
    await this.stopOwned();
    throw new Error(`Eris đã được launch nhưng service chưa ready: ${String(lastError ?? '')}`);
  }

  private async resolveLaunch(): Promise<{ command: string; args: string[]; cwd: string; shell: boolean; display: string }> {
    const config = vscode.workspace.getConfiguration('eris.service');
    const configuredCommand = (process.env.ERIS_SERVICE_COMMAND ?? config.get<string>('launchCommand', '')).trim();
    const configuredRoot = (process.env.ERIS_HOME ?? config.get<string>('installRoot', '')).trim();
    const firstWorkspace = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '';
    const cwd = configuredRoot || firstWorkspace || os.homedir();

    if (configuredCommand) {
      return {
        command: configuredCommand,
        args: [],
        cwd,
        shell: true,
        display: configuredCommand,
      };
    }

    const launcherName = process.platform === 'win32' ? 'run_eris.bat' : 'run_eris.sh';
    const candidates = unique([
      ...(await this.erisRootCandidates()).map((root) => path.join(root, launcherName)),
    ]);
    for (const candidate of candidates) {
      if (await exists(candidate)) {
        if (process.platform === 'win32' && candidate.toLowerCase().endsWith('.bat')) {
          return {
            command: process.env.ComSpec || 'cmd.exe',
            args: ['/d', '/s', '/c', candidate],
            cwd: path.dirname(candidate),
            shell: false,
            display: candidate,
          };
        }
        return {
          command: candidate,
          args: [],
          cwd: path.dirname(candidate),
          shell: false,
          display: candidate,
        };
      }
    }
    throw new Error('Không tìm thấy launcher Eris. Đặt eris.service.installRoot hoặc eris.service.launchCommand một lần.');
  }

  private async erisRootCandidates(): Promise<string[]> {
    const config = vscode.workspace.getConfiguration('eris.service');
    const configuredRoot = (process.env.ERIS_HOME ?? config.get<string>('installRoot', '') ?? '').trim();
    const firstWorkspace = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '';
    const workspaceRoots: string[] = [];
    if (firstWorkspace) {
      let current = path.resolve(firstWorkspace);
      for (let depth = 0; depth < 6; depth += 1) {
        workspaceRoots.push(current);
        const parent = path.dirname(current);
        if (parent === current) {
          break;
        }
        current = parent;
      }
    }
    return unique([
      ...workspaceRoots,
      configuredRoot,
      path.join(os.homedir(), 'Documents', 'GitHub', 'eris'),
      path.join(os.homedir(), 'Documents', 'eris'),
      path.join(os.homedir(), 'eris'),
    ].filter(Boolean).map((item) => path.resolve(item)));
  }

  dispose(): void {
    // Không tự kill Eris khi extension reload/đóng panel. Eris là companion process
    // độc lập; chỉ command Stop/Restart mới có quyền kết thúc process extension đã launch.
    this.output.dispose();
  }
}

function processExists(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function exists(value: string): Promise<boolean> {
  if (!value) {
    return false;
  }
  try {
    await fs.stat(value);
    return true;
  } catch {
    return false;
  }
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function uniqueNumbers(values: number[]): number[] {
  return [...new Set(values.filter((value) => Number.isInteger(value) && value > 0))];
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
