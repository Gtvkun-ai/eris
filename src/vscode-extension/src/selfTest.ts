import * as vscode from 'vscode';
import { captureIdeContext } from './contextBridge';
import { ErisClient } from './erisClient';
import { ErisServiceManager } from './serviceManager';
import { TerminalContextObserver } from './terminalObserver';

type JsonRecord = Record<string, any>;

interface CheckResult {
  name: string;
  ok: boolean;
  detail: string;
}

/**
 * Smoke test chạy ngay trong extension host thật.
 * Không sửa file, không chạy lệnh destructive; mục tiêu là tách lỗi bootstrap,
 * WebSocket và Context Bridge trước khi ném một task coding thật cho Gemini.
 */
export async function runErisSelfTest(
  client: ErisClient,
  serviceManager: ErisServiceManager,
  terminalObserver: TerminalContextObserver,
): Promise<void> {
  const output = vscode.window.createOutputChannel('Eris Self Test', { log: true });
  const results: CheckResult[] = [];
  output.clear();
  output.show(true);
  output.appendLine('=== ERIS VS CODE SELF TEST ===');
  output.appendLine(`Time: ${new Date().toISOString()}`);

  const check = async (name: string, fn: () => Promise<string> | string): Promise<void> => {
    try {
      const detail = await fn();
      results.push({ name, ok: true, detail });
      output.appendLine(`✓ ${name}: ${detail}`);
    } catch (error) {
      const detail = String(error);
      results.push({ name, ok: false, detail });
      output.appendLine(`✗ ${name}: ${detail}`);
    }
  };

  await check('Workspace', () => {
    const folders = vscode.workspace.workspaceFolders ?? [];
    if (!folders.length) {
      throw new Error('Chưa mở folder/workspace trong VS Code.');
    }
    return `${folders.length} folder, trusted=${String(vscode.workspace.isTrusted)}`;
  });

  await check('Service discovery / auto-start', async () => {
    const record = await serviceManager.ensureStarted({ allowLaunch: true });
    // Không log token. Token tồn tại là đủ, đừng tự leak chìa khóa rồi gọi đó là diagnostics.
    return `${record.endpoint} pid=${String(record.pid ?? 'unknown')}`;
  });

  await check('WebSocket handshake', async () => {
    await client.connect(true);
    return client.connectionState;
  });

  await check('Task list round-trip', async () => {
    const reply = waitForEvent(client, (event) => event?.type === 'task.list', 4500);
    await client.requestTasks();
    const event = await reply;
    const tasks = Array.isArray(event.tasks) ? event.tasks.length : 0;
    return `${tasks} task`;
  });

  await check('IDE semantic context', async () => {
    const context = await captureIdeContext(terminalObserver);
    const workspace = context.workspace as JsonRecord | undefined;
    if (!workspace || !Array.isArray(workspace.folders)) {
      throw new Error('Context Bridge không trả workspace hợp lệ.');
    }
    const current = context.current as JsonRecord | undefined;
    const currentText = current?.available ? String(current.path ?? 'active file') : 'no active file';
    return `${workspace.folders.length} folder, ${currentText}`;
  });

  const passed = results.filter((item) => item.ok).length;
  const failed = results.length - passed;
  output.appendLine('');
  output.appendLine(`RESULT: ${passed}/${results.length} passed, ${failed} failed`);

  if (failed) {
    void vscode.window.showErrorMessage(`Eris Self Test: ${failed} check lỗi. Mở Output → Eris Self Test để xem chi tiết.`);
  } else {
    void vscode.window.showInformationMessage(`Eris Self Test: ${passed}/${results.length} passed.`);
  }
}

function waitForEvent(
  client: ErisClient,
  predicate: (event: JsonRecord) => boolean,
  timeoutMs: number,
): Promise<JsonRecord> {
  return new Promise<JsonRecord>((resolve, reject) => {
    let finished = false;
    const subscription = client.onEvent((event) => {
      if (finished || !predicate(event)) {
        return;
      }
      finished = true;
      clearTimeout(timer);
      subscription.dispose();
      resolve(event);
    });
    const timer = setTimeout(() => {
      if (finished) {
        return;
      }
      finished = true;
      subscription.dispose();
      reject(new Error(`timeout ${timeoutMs}ms`));
    }, timeoutMs);
  });
}
