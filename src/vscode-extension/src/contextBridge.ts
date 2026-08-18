import * as path from 'node:path';
import * as vscode from 'vscode';

const TEXT_LIMIT = 16_000;
const DIAGNOSTIC_LIMIT = 80;

function clip(value: string, limit = TEXT_LIMIT): string {
  if (value.length <= limit) {
    return value;
  }
  return `${value.slice(0, Math.max(0, limit - 1))}…`;
}

function relativePath(uri: vscode.Uri): string {
  const folder = vscode.workspace.getWorkspaceFolder(uri);
  if (!folder) {
    return uri.fsPath;
  }
  return path.relative(folder.uri.fsPath, uri.fsPath).replaceAll('\\', '/');
}

/**
 * Lấy context semantic trực tiếp từ VS Code thay vì OCR giao diện IDE.
 * Payload luôn có giới hạn kích thước để một file/log khổng lồ không nhấn chìm prompt.
 */
export async function captureIdeContext(): Promise<Record<string, unknown>> {
  const editor = vscode.window.activeTextEditor;
  const folders = vscode.workspace.workspaceFolders ?? [];
  const activeFolder = editor ? vscode.workspace.getWorkspaceFolder(editor.document.uri) : folders[0];

  const context: Record<string, unknown> = {
    capturedAt: Date.now(),
    workspace: {
      active: activeFolder?.uri.fsPath ?? '',
      trusted: vscode.workspace.isTrusted,
      folders: folders.map((folder) => ({
        name: folder.name,
        path: folder.uri.fsPath,
      })),
    },
    terminal: {
      active: vscode.window.activeTerminal?.name ?? '',
      terminals: vscode.window.terminals.map((terminal) => terminal.name),
      // VS Code API không cho extension đọc lịch sử buffer terminal một cách chuẩn.
      // Không bịa output; backend chỉ biết terminal nào đang tồn tại.
      outputAvailable: false,
    },
  };

  // Không trích code/diagnostics/Git từ workspace chưa được VS Code trust.
  // Boundary này nằm ở extension API, không dựa vào việc Webview "ngoan".
  if (!vscode.workspace.isTrusted) {
    context.restricted = 'workspace_untrusted';
    return context;
  }

  if (editor) {
    const document = editor.document;
    const selection = editor.selection;
    const cursor = selection.active;
    const selectedText = document.getText(selection);
    const radius = 120;
    const startLine = Math.max(0, cursor.line - radius);
    const endLine = Math.min(document.lineCount - 1, cursor.line + radius);
    const excerpt = document.getText(new vscode.Range(
      new vscode.Position(startLine, 0),
      document.lineAt(endLine).range.end,
    ));

    context.current = {
      path: relativePath(document.uri),
      absolutePath: document.uri.fsPath,
      languageId: document.languageId,
      version: document.version,
      dirty: document.isDirty,
      cursor: { line: cursor.line + 1, column: cursor.character + 1 },
      excerptStartLine: startLine + 1,
      excerpt: clip(excerpt),
    };
    context.selection = {
      empty: selection.isEmpty,
      start: { line: selection.start.line + 1, column: selection.start.character + 1 },
      end: { line: selection.end.line + 1, column: selection.end.character + 1 },
      text: clip(selectedText, 12_000),
    };
  }

  const diagnostics: Array<Record<string, unknown>> = [];
  const diagnosticEntries = editor
    ? [[editor.document.uri, vscode.languages.getDiagnostics(editor.document.uri)] as const]
    : vscode.languages.getDiagnostics();
  for (const [uri, items] of diagnosticEntries) {
    for (const item of items) {
      diagnostics.push({
        path: relativePath(uri),
        severity: vscode.DiagnosticSeverity[item.severity],
        message: clip(item.message, 1200),
        source: item.source ?? '',
        code: typeof item.code === 'object' ? item.code.value : (item.code ?? ''),
        line: item.range.start.line + 1,
        column: item.range.start.character + 1,
      });
      if (diagnostics.length >= DIAGNOSTIC_LIMIT) {
        break;
      }
    }
    if (diagnostics.length >= DIAGNOSTIC_LIMIT) {
      break;
    }
  }
  context.problems = diagnostics;

  context.git = await captureGitContext(editor?.document.uri);
  return context;
}

async function captureGitContext(activeUri?: vscode.Uri): Promise<Record<string, unknown>> {
  try {
    const extension = vscode.extensions.getExtension('vscode.git');
    if (!extension) {
      return { available: false };
    }
    if (!extension.isActive) {
      await extension.activate();
    }
    const api = extension.exports?.getAPI?.(1);
    const repositories: any[] = Array.isArray(api?.repositories) ? api.repositories : [];
    let repo = activeUri && api?.getRepository ? api.getRepository(activeUri) : undefined;
    repo = repo ?? repositories[0];
    if (!repo) {
      return { available: true, repository: null };
    }

    const root = String(repo.rootUri?.fsPath ?? '');
    const state = repo.state ?? {};
    const allChanges = [
      ...(state.workingTreeChanges ?? []),
      ...(state.indexChanges ?? []),
      ...(state.mergeChanges ?? []),
    ];
    return {
      available: true,
      root,
      branch: state.HEAD?.name ?? '',
      detached: !state.HEAD?.name,
      changes: allChanges.slice(0, 120).map((change: any) => ({
        path: root
          ? path.relative(root, String(change.uri?.fsPath ?? '')).replaceAll('\\', '/')
          : String(change.uri?.fsPath ?? ''),
        status: change.status,
      })),
    };
  } catch (error) {
    return { available: false, error: String(error) };
  }
}

export function currentWorkspaceRef(): string {
  if (!vscode.workspace.isTrusted) {
    return '';
  }
  const editor = vscode.window.activeTextEditor;
  return (
    (editor && vscode.workspace.getWorkspaceFolder(editor.document.uri)?.uri.fsPath)
    ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    ?? ''
  );
}
