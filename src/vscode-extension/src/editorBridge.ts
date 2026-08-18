import * as vscode from 'vscode';
import { WorkspaceDiffProvider, resolveWorkspaceFile } from './diffProvider';

/**
 * Thực thi editor action ở extension host, không ở Webview.
 * Agent chỉ gửi intent typed; quyền file/editor vẫn nằm trong VS Code boundary.
 */
export async function executeEditorCommand(
  payload: Record<string, unknown>,
  diffProvider: WorkspaceDiffProvider,
): Promise<string> {
  const command = String(payload.command ?? payload.type ?? '');
  if (command === 'editor.openFile') {
    await openWorkspaceFile(String(payload.path ?? ''), Number(payload.line ?? 1), Number(payload.column ?? 1));
    return `Đã mở ${String(payload.path ?? '')}`;
  }
  if (command === 'editor.openDiff') {
    await diffProvider.openDiff(String(payload.path ?? ''), String(payload.diff ?? ''));
    return `Đã mở diff ${String(payload.path ?? '')}`;
  }
  if (command === 'editor.focusProblems') {
    await vscode.commands.executeCommand('workbench.actions.view.problems');
    return 'Đã focus Problems';
  }
  if (command === 'editor.showSourceControl') {
    await vscode.commands.executeCommand('workbench.view.scm');
    return 'Đã mở Source Control';
  }
  throw new Error(`Editor command không được hỗ trợ: ${command}`);
}

export async function openWorkspaceFile(filePath: string, line = 1, column = 1): Promise<void> {
  if (!vscode.workspace.isTrusted) {
    throw new Error('workspace_untrusted');
  }
  const uri = await resolveWorkspaceFile(filePath);
  if (!uri) {
    throw new Error(`Eris không tìm thấy file trong workspace: ${filePath}`);
  }
  const document = await vscode.workspace.openTextDocument(uri);
  const editor = await vscode.window.showTextDocument(document, { preview: true, preserveFocus: false });
  const position = new vscode.Position(Math.max(0, line - 1), Math.max(0, column - 1));
  editor.selection = new vscode.Selection(position, position);
  editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
}
