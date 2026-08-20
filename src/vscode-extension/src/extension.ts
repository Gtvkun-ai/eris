import * as vscode from 'vscode';
import { ErisChatPanel } from './chatPanel';
import { registerErisChatParticipant } from './chatParticipant';
import { captureIdeContext, resolveIdeContextRequest } from './contextBridge';
import { WorkspaceDiffProvider } from './diffProvider';
import { executeEditorCommand } from './editorBridge';
import { ErisClient } from './erisClient';
import { TerminalContextObserver } from './terminalObserver';
import { ErisServiceManager } from './serviceManager';
import { runErisSelfTest } from './selfTest';

/**
 * Eris chỉ có MỘT View Container và MỘT Webview trong Primary Sidebar.
 *
 * Không tách Chat / Plans / Skills thành nhiều TreeView nữa. VS Code sẽ tự biến
 * mỗi view thành một accordion độc lập, trông giống bảng quản trị hơn coding
 * agent. Mọi màn hình con của Eris được render bên trong ErisChatPanel.
 */
const ERIS_CONTAINER_ID = 'eris.agentSidebar';
const ERIS_CONTAINER_COMMAND = `workbench.view.extension.${ERIS_CONTAINER_ID}`;

/** Mở Primary Sidebar của Eris. Backend offline không được phép làm UI biến mất. */
async function revealErisSidebar(): Promise<void> {
  try {
    await vscode.commands.executeCommand(ERIS_CONTAINER_COMMAND);
  } catch {
    // Một vài build VS Code không expose command container ngay lập tức.
    // Focus view bên dưới vẫn khiến VS Code reveal đúng Activity Bar container.
  }
  await vscode.commands.executeCommand(`${ErisChatPanel.viewType}.focus`);
}

export function activate(context: vscode.ExtensionContext): void {
  const serviceManager = new ErisServiceManager(context);
  const client = new ErisClient(context, serviceManager);
  const terminalObserver = new TerminalContextObserver();
  const diffProvider = new WorkspaceDiffProvider();
  const chatPanel = new ErisChatPanel(
    context.extensionUri,
    client,
    context,
    terminalObserver,
    diffProvider,
  );

  context.subscriptions.push(serviceManager, client, terminalObserver, diffProvider, chatPanel);
  context.subscriptions.push(vscode.window.registerWebviewViewProvider(
    ErisChatPanel.viewType,
    chatPanel,
    { webviewOptions: { retainContextWhenHidden: true } },
  ));

  // Gửi file update xuống backend khi user lưu file (cho Codebase Indexing)
  context.subscriptions.push(vscode.workspace.onDidSaveTextDocument((document) => {
    if (!vscode.workspace.isTrusted || document.uri.scheme !== 'file') return;
    const fsPath = document.uri.fsPath;
    if (fsPath.includes('.eris') || fsPath.includes('.git') || fsPath.includes('node_modules') || fsPath.includes('__pycache__')) return;
    
    // Gửi nội dung mới xuống backend
    client.reportDocumentSaved(fsPath, document.getText()).catch(() => {});
  }));

  // Lắng nghe LSP Diagnostics (Self-Healing Phase 3)
  const { recentlyModifiedFiles } = require('./editorBridge');
  const path = require('node:path');
  
  context.subscriptions.push(vscode.languages.onDidChangeDiagnostics((e) => {
    for (const uri of e.uris) {
      if (uri.scheme !== 'file') continue;
      const lastModified = recentlyModifiedFiles.get(uri.fsPath);
      // Nếu file vừa được AI sửa trong vòng 15 giây qua
      if (lastModified && Date.now() - lastModified < 15000) {
        const diagnostics = vscode.languages.getDiagnostics(uri)
          .filter(d => d.severity === vscode.DiagnosticSeverity.Error); // Chỉ lấy Error, bỏ qua Warning
        
        if (diagnostics.length > 0) {
          // Xóa ngay lập tức để tránh loop gửi liên tục khi typing
          recentlyModifiedFiles.delete(uri.fsPath);
          
          const errorText = diagnostics.map(d => `Dòng ${d.range.start.line + 1}: ${d.message}`).join('\\n');
          const prompt = `Hệ thống phát hiện lỗi LSP sau khi bạn chỉnh sửa file \`${path.basename(uri.fsPath)}\`:\\n\\n${errorText}\\n\\nHãy kiểm tra và sửa lại lỗi này ngay nhé.`;
          
          // Gửi ẩn danh về cho Eris
          chatPanel.sendSystemFeedback(prompt).catch(() => {});
        }
      }
    }
  }));

  // @eris trong native Chat vẫn là đường tắt nhẹ; full task UI nằm ở Sidebar.
  registerErisChatParticipant(context, client, terminalObserver);

  context.subscriptions.push(client.onEvent((event) => {
    // Live IDE RPC/editor actions phải sống ở extension host, không nằm trong
    // iframe. Như vậy đóng Sidebar giữa task cũng không làm Gemini mất tool.
    if (event?.type === 'ide.request') {
      const payload = event.payload ?? {};
      const requestId = String(payload.requestId ?? '');
      const method = String(payload.method ?? '');
      void resolveIdeContextRequest(
        method,
        payload.params && typeof payload.params === 'object' ? payload.params : {},
        terminalObserver,
      ).then((data) => client.reportIdeResponse(
        String(event.taskId ?? ''), requestId, method, true, data, '',
      )).catch((error) => client.reportIdeResponse(
        String(event.taskId ?? ''), requestId, method, false, {}, String(error),
      ).catch(() => undefined));
      return;
    }

    if (event?.type === 'editor.command') {
      const payload = event.payload ?? {};
      const requestId = String(payload.requestId ?? '');
      const command = String(payload.command ?? '');
      void executeEditorCommand(payload, diffProvider).then((message) => client.reportEditorCommandResult(
        String(event.taskId ?? ''), requestId, command, true, message,
      )).catch((error) => client.reportEditorCommandResult(
        String(event.taskId ?? ''), requestId, command, false, String(error),
      ).catch(() => undefined));
      return;
    }

    if (event?.type === 'session.ready') {
      // Sau Python restart, phục hồi worker đang chạy đúng session VS Code.
      // Backend xử lý resume idempotent nên worker còn sống không bị nhân đôi.
      const tasks = Array.isArray(event.tasks) ? event.tasks : [];
      const recoverable = tasks.filter((task: any) =>
        String(task?.status ?? '') === 'running'
        && String(task?.session_id ?? '') === String(event.sessionId ?? '')
        && String(task?.metadata?.source ?? '') === 'vscode',
      );
      if (recoverable.length) {
        void captureIdeContext(terminalObserver).then(async (ideContext) => {
          for (const task of recoverable) {
            await client.controlTask(String(task.task_id ?? ''), 'resume', '', '', ideContext);
          }
        }).catch(() => undefined);
      }
    }
  }));

  const openChat = async () => {
    await revealErisSidebar();
    await chatPanel.show(false);
  };

  context.subscriptions.push(vscode.commands.registerCommand('eris.openChat', openChat));
  context.subscriptions.push(vscode.commands.registerCommand('eris.newChat', async () => {
    await revealErisSidebar();
    await chatPanel.show(false);
    chatPanel.newChat();
  }));
  context.subscriptions.push(vscode.commands.registerCommand('eris.openTask', async (taskId: string, threadId: string) => {
    await revealErisSidebar();
    await chatPanel.selectTask(taskId, threadId);
  }));
  context.subscriptions.push(vscode.commands.registerCommand('eris.reconnect', async () => {
    try {
      await client.connect(true);
      await client.requestTasks();
      void vscode.window.showInformationMessage('Eris Service đã kết nối lại.');
    } catch (error) {
      void vscode.window.showErrorMessage(String(error));
    }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('eris.selfTest', () => runErisSelfTest(
    client, serviceManager, terminalObserver,
  )));

  context.subscriptions.push(vscode.commands.registerCommand('eris.serviceStart', async () => {
    try {
      await serviceManager.ensureStarted();
      await client.connect(true);
      await client.requestTasks();
      void vscode.window.showInformationMessage('Eris Service đã sẵn sàng.');
    } catch (error) {
      serviceManager.showLogs();
      void vscode.window.showErrorMessage(String(error));
    }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('eris.serviceRestart', async () => {
    try {
      await serviceManager.restart();
      await client.connect(true);
      await client.requestTasks();
      void vscode.window.showInformationMessage('Eris Service đã restart.');
    } catch (error) {
      serviceManager.showLogs();
      void vscode.window.showErrorMessage(String(error));
    }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('eris.serviceStop', async () => {
    await serviceManager.stopOwned();
    void vscode.window.showInformationMessage('Đã dừng Eris process do VS Code launch.');
  }));
  context.subscriptions.push(vscode.commands.registerCommand('eris.serviceLogs', () => serviceManager.showLogs()));

  // Auto-start chỉ lo backend. Activity Bar icon/Webview do manifest đóng góp nên
  // dù Python hỏng, user vẫn luôn mở được Eris để thấy trạng thái và self-test.
  const autoStart = vscode.workspace.getConfiguration('eris.service').get<boolean>('autoStart', true);
  if (autoStart) {
    void client.connect().then(() => client.requestTasks()).catch(() => undefined);
  }
}

export function deactivate(): void {
  // Disposable được VS Code thu dọn qua ExtensionContext.
}
