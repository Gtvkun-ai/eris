import * as vscode from 'vscode';
import { captureIdeContext } from './contextBridge';
import { GitPilotClient } from './gitPilotClient';
import { GitPilotRuntimeManager } from './gitPilotRuntimeManager';
import { TerminalContextObserver } from './terminalObserver';

interface CheckResult { name: string; ok: boolean; detail: string }

export async function runErisCodeSelfTest(
  client: GitPilotClient,
  runtime: GitPilotRuntimeManager,
  terminalObserver: TerminalContextObserver,
): Promise<void> {
  const output = vscode.window.createOutputChannel('Eris Code Self Test', { log: true });
  const results: CheckResult[] = [];
  output.clear(); output.show(true);
  output.appendLine('=== ERIS CODE SELF TEST ===');
  output.appendLine('Invariant: Eris Desktop is not required and is never launched.');

  const check = async (name: string, fn: () => Promise<string> | string) => {
    try { const detail = await fn(); results.push({ name, ok: true, detail }); output.appendLine(`✓ ${name}: ${detail}`); }
    catch (error) { results.push({ name, ok: false, detail: String(error) }); output.appendLine(`✗ ${name}: ${String(error)}`); }
  };

  await check('Workspace', () => {
    const folders = vscode.workspace.workspaceFolders ?? [];
    if (!folders.length) throw new Error('Chưa mở folder/workspace.');
    return `${folders.length} folder, trusted=${String(vscode.workspace.isTrusted)}`;
  });
  await check('GitPilot backend', async () => {
    await runtime.ensureStarted({ allowLaunch: true });
    return `${runtime.serverUrl} (${runtime.runtimeState})`;
  });
  await check('GitPilot client', async () => { await client.connect(true); return client.connectionState; });
  await check('VS Code observer snapshot', async () => {
    const data = await captureIdeContext(terminalObserver);
    const workspace = data.workspace as Record<string, unknown> | undefined;
    return `${Array.isArray(workspace?.folders) ? workspace!.folders.length : 0} folder(s)`;
  });
  await check('Desktop decoupling', () => {
    const enabled = vscode.workspace.getConfiguration('erisCode.erisLink').get<boolean>('enabled', false);
    return enabled ? 'optional Eris Link enabled' : 'Eris Link disabled; coding remains fully available';
  });

  const failed = results.filter((item) => !item.ok).length;
  output.appendLine(`\nRESULT: ${results.length - failed}/${results.length} passed, ${failed} failed`);
  if (failed) void vscode.window.showErrorMessage(`Eris Code Self Test: ${failed} check lỗi.`);
  else void vscode.window.showInformationMessage(`Eris Code Self Test: ${results.length}/${results.length} passed.`);
}
