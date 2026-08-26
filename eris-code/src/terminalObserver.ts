import * as vscode from 'vscode';

const OUTPUT_LIMIT = 12_000;
const RECENT_LIMIT = 6;

interface TerminalExecutionRecord {
  id: string;
  terminal: string;
  command: string;
  cwd: string;
  startedAt: number;
  finishedAt?: number;
  exitCode?: number;
  output: string;
  outputTruncated: boolean;
}

function stripAnsi(value: string): string {
  // ANSI/OSC chỉ làm prompt bẩn và không mang thêm nghĩa cho coding agent.
  return value
    .replace(/\u001B\][^\u0007]*(?:\u0007|\u001B\\)/g, '')
    .replace(/\u001B\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/\r/g, '');
}

function appendLimited(record: TerminalExecutionRecord, chunk: string): void {
  const clean = stripAnsi(chunk);
  if (!clean) {
    return;
  }
  record.output += clean;
  if (record.output.length > OUTPUT_LIMIT) {
    record.output = record.output.slice(-OUTPUT_LIMIT);
    record.outputTruncated = true;
  }
}

/**
 * Thu context terminal bằng Shell Integration event của VS Code.
 *
 * Observer đọc stream ngay khi execution bắt đầu rồi chỉ giữ một cửa sổ nhỏ gần
 * nhất. Như vậy Eris nhận được lỗi build/test thật thay vì OCR cái terminal như
 * một sinh vật thời đồ đá, nhưng cũng không biến toàn bộ shell history thành prompt.
 */
export class TerminalContextObserver implements vscode.Disposable {
  private readonly disposables: vscode.Disposable[] = [];
  private readonly active = new Map<any, TerminalExecutionRecord>();
  private readonly recent: TerminalExecutionRecord[] = [];
  private sequence = 0;

  constructor() {
    // Cast qua any để extension vẫn load trên build VS Code thiếu Shell Integration
    // event. Capability sẽ tự degrade thành outputAvailable=false.
    const windowApi = vscode.window as any;
    if (typeof windowApi.onDidStartTerminalShellExecution === 'function') {
      this.disposables.push(windowApi.onDidStartTerminalShellExecution((event: any) => {
        this.onStart(event);
      }));
    }
    if (typeof windowApi.onDidEndTerminalShellExecution === 'function') {
      this.disposables.push(windowApi.onDidEndTerminalShellExecution((event: any) => {
        this.onEnd(event);
      }));
    }
  }

  private onStart(event: any): void {
    const execution = event?.execution;
    if (!execution) {
      return;
    }
    const shellIntegration = event?.terminal?.shellIntegration;
    const commandLine = execution?.commandLine;
    const record: TerminalExecutionRecord = {
      id: `term_${Date.now()}_${++this.sequence}`,
      terminal: String(event?.terminal?.name ?? ''),
      command: String(commandLine?.value ?? commandLine ?? ''),
      cwd: String(shellIntegration?.cwd?.fsPath ?? shellIntegration?.cwd?.path ?? ''),
      startedAt: Date.now(),
      output: '',
      outputTruncated: false,
    };
    this.active.set(execution, record);

    // read() phải được lấy ngay lúc start. Consumer chạy async, nhưng iterator đã
    // được đăng ký ở callback này nên không bỏ mất đoạn output đầu tiên.
    try {
      const stream = execution.read?.();
      if (stream && typeof stream[Symbol.asyncIterator] === 'function') {
        void this.consume(stream, record);
      }
    } catch {
      // Shell integration có thể biến mất giữa lifecycle terminal. Context này
      // là best-effort, không được phép làm hỏng chat.
    }
  }

  private async consume(stream: AsyncIterable<string>, record: TerminalExecutionRecord): Promise<void> {
    try {
      for await (const chunk of stream) {
        appendLimited(record, String(chunk ?? ''));
      }
    } catch {
      // Terminal đóng giữa command là chuyện bình thường; giữ phần đã đọc được.
    }
  }

  private onEnd(event: any): void {
    const execution = event?.execution;
    const record = this.active.get(execution);
    if (!record) {
      return;
    }
    this.active.delete(execution);
    record.finishedAt = Date.now();
    if (typeof event?.exitCode === 'number') {
      record.exitCode = event.exitCode;
    }
    this.recent.unshift(record);
    if (this.recent.length > RECENT_LIMIT) {
      this.recent.length = RECENT_LIMIT;
    }
  }

  snapshot(): Record<string, unknown> {
    const activeRecords = [...this.active.values()];
    const combined = [...activeRecords, ...this.recent]
      .sort((a, b) => b.startedAt - a.startedAt)
      .slice(0, RECENT_LIMIT)
      .map((record) => ({ ...record }));
    return {
      active: vscode.window.activeTerminal?.name ?? '',
      terminals: vscode.window.terminals.map((terminal) => terminal.name),
      outputAvailable: this.disposables.length > 0,
      recent: combined,
    };
  }

  dispose(): void {
    while (this.disposables.length) {
      this.disposables.pop()?.dispose();
    }
    this.active.clear();
    this.recent.length = 0;
  }
}
