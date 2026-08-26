import * as vscode from 'vscode';
import { WorkspaceDiffProvider, resolveWorkspaceFile } from './diffProvider';

const addedLineDecoration = vscode.window.createTextEditorDecorationType({
  backgroundColor: 'rgba(46, 160, 67, 0.2)',
  isWholeLine: true,
});

export const recentlyModifiedFiles = new Map<string, number>();

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
  if (command === 'editor.applyNewContent') {
    const filePath = String(payload.path ?? '');
    const newContent = String(payload.content ?? '');
    const uri = await resolveWorkspaceFile(filePath);
    if (!uri) throw new Error(`Eris không tìm thấy file: ${filePath}`);
    const document = await vscode.workspace.openTextDocument(uri);
    const edit = new vscode.WorkspaceEdit();
    const fullRange = new vscode.Range(
      document.positionAt(0),
      document.positionAt(document.getText().length)
    );
    edit.replace(uri, fullRange, newContent);
    await vscode.workspace.applyEdit(edit);
    
    // Lưu file để giữ sync với Python backend, 
    // user vẫn có thể Undo (Ctrl+Z) sau khi save.
    await document.save();
    
    // Lưu vết để self-healing bằng LSP (nếu có lỗi ngay sau khi sửa)
    recentlyModifiedFiles.set(document.uri.fsPath, Date.now());
    
    // Mở file ra cho user thấy thay đổi
    const editor = await vscode.window.showTextDocument(document, { preview: true, preserveFocus: false });
    
    // Highlight file đã sửa (Composer-like inline view)
    const endLine = document.lineCount - 1;
    const range = new vscode.Range(0, 0, endLine, document.lineAt(endLine).text.length);
    editor.setDecorations(addedLineDecoration, [range]);
    
    // Xoá highlight sau 5 giây để không làm phiền
    setTimeout(() => {
      editor.setDecorations(addedLineDecoration, []);
    }, 5000);

    return `Đã apply và lưu ${filePath}`;
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
