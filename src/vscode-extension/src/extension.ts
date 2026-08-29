import * as vscode from 'vscode';
import { ErisChatPanel } from './chatPanel';
import { registerErisChatParticipant } from './chatParticipant';
import { WorkspaceDiffProvider } from './diffProvider';
import { ErisObserverBridge } from './erisObserverBridge';
import { GitPilotClient } from './gitPilotClient';
import { GitPilotRuntimeManager } from './gitPilotRuntimeManager';
import { runErisCodeSelfTest } from './selfTest';
import { TerminalContextObserver } from './terminalObserver';

const CONTAINER_ID = 'erisCode.agentSidebar';
const CONTAINER_COMMAND = `workbench.view.extension.${CONTAINER_ID}`;

async function revealSidebar(): Promise<void> {
  try { await vscode.commands.executeCommand(CONTAINER_COMMAND); } catch {}
  await vscode.commands.executeCommand(`${ErisChatPanel.viewType}.focus`);
}

/**
 * V78: Eris Code độc lập hoàn toàn với Eris Desktop.
 * Runtime bắt buộc duy nhất là GitPilot; Desktop chỉ có thể cung cấp context
 * read-only nếu user chủ động bật Eris Link.
 */
export function activate(context: vscode.ExtensionContext): void {
  const runtime = new GitPilotRuntimeManager(context);
  const terminalObserver = new TerminalContextObserver();
  const erisBridge = new ErisObserverBridge();
  const client = new GitPilotClient(context, runtime, terminalObserver, erisBridge);
  const diffProvider = new WorkspaceDiffProvider();
  const chatPanel = new ErisChatPanel(context.extensionUri, client, context, terminalObserver, diffProvider);

  context.subscriptions.push(runtime, client, terminalObserver, diffProvider, chatPanel);
  context.subscriptions.push(vscode.window.registerWebviewViewProvider(
    ErisChatPanel.viewType,
    chatPanel,
    { webviewOptions: { retainContextWhenHidden: true } },
  ));

  // Native Chat is just another surface over the same GitPilot client.
  registerErisChatParticipant(context, client, terminalObserver);

  // LSP self-healing is deliberately passive: it only feeds an already-open
  // GitPilot session. Saving a file never starts GitPilot or Eris Desktop.
  const { recentlyModifiedFiles } = require('./editorBridge');
  const path = require('node:path');
  context.subscriptions.push(vscode.languages.onDidChangeDiagnostics((event) => {
    if (client.connectionState !== 'connected') return;
    for (const uri of event.uris) {
      if (uri.scheme !== 'file') continue;
      const modifiedAt = recentlyModifiedFiles.get(uri.fsPath);
      if (!modifiedAt || Date.now() - modifiedAt >= 15_000) continue;
      const errors = vscode.languages.getDiagnostics(uri).filter((item) => item.severity === vscode.DiagnosticSeverity.Error);
      if (!errors.length) continue;
      recentlyModifiedFiles.delete(uri.fsPath);
      const detail = errors.map((item) => `Dòng ${item.range.start.line + 1}: ${item.message}`).join('\n');
      void chatPanel.sendSystemFeedback(
        `VS Code phát hiện lỗi LSP sau patch ở \`${path.basename(uri.fsPath)}\`:\n\n${detail}\n\nHãy kiểm tra và sửa lại.`,
      );
    }
  }));

  const openChat = async () => { await revealSidebar(); await chatPanel.show(false); };
  context.subscriptions.push(vscode.commands.registerCommand('erisCode.openChat', openChat));
  context.subscriptions.push(vscode.commands.registerCommand('erisCode.newChat', async () => {
    await revealSidebar(); await chatPanel.show(false); chatPanel.newChat();
  }));
  context.subscriptions.push(vscode.commands.registerCommand('erisCode.openTask', async (taskId: string, threadId: string) => {
    await revealSidebar(); await chatPanel.selectTask(taskId, threadId);
  }));
  context.subscriptions.push(vscode.commands.registerCommand('erisCode.reconnect', async () => {
    try {
      await client.connect(true); await client.requestTasks();
      void vscode.window.showInformationMessage('Eris Code đã kết nối GitPilot.');
    } catch (error) { runtime.showLogs(); void vscode.window.showErrorMessage(String(error)); }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('erisCode.gitpilotStart', async () => {
    try { await runtime.ensureStarted({ allowLaunch: true }); await client.connect(true); void vscode.window.showInformationMessage('GitPilot đã sẵn sàng.'); }
    catch (error) { runtime.showLogs(); void vscode.window.showErrorMessage(String(error)); }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('erisCode.gitpilotRestart', async () => {
    try { await runtime.restart(); await client.connect(true); void vscode.window.showInformationMessage('GitPilot đã restart.'); }
    catch (error) { runtime.showLogs(); void vscode.window.showErrorMessage(String(error)); }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('erisCode.gitpilotStop', async () => {
    await runtime.stopOwned(); void vscode.window.showInformationMessage('Đã dừng GitPilot process do Eris Code launch.');
  }));
  context.subscriptions.push(vscode.commands.registerCommand('erisCode.gitpilotLogs', () => runtime.showLogs()));
  context.subscriptions.push(vscode.commands.registerCommand('erisCode.installGitPilot', () => runtime.openInstallTerminal()));
  context.subscriptions.push(vscode.commands.registerCommand('erisCode.selfTest', () => runErisCodeSelfTest(client, runtime, terminalObserver)));
}

export function deactivate(): void {}
