import * as path from 'node:path';
import * as vscode from 'vscode';
import { TerminalContextObserver } from './terminalObserver';

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
 * Payload luôn bị giới hạn để log/diff lớn không nuốt sạch prompt của agent.
 */
export async function captureIdeContext(terminalObserver?: TerminalContextObserver): Promise<Record<string, unknown>> {
  const editor = vscode.window.activeTextEditor;
  const folders = vscode.workspace.workspaceFolders ?? [];
  const activeFolder = editor ? vscode.workspace.getWorkspaceFolder(editor.document.uri) : folders[0];

  const context: Record<string, unknown> = {
    capturedAt: Date.now(),
    workspace: {
      active: activeFolder?.uri.fsPath ?? '',
      trusted: vscode.workspace.isTrusted,
      folders: folders.map((folder) => ({ name: folder.name, path: folder.uri.fsPath })),
    },
    terminal: terminalObserver?.snapshot() ?? {
      active: vscode.window.activeTerminal?.name ?? '',
      terminals: vscode.window.terminals.map((terminal) => terminal.name),
      outputAvailable: false,
      recent: [],
    },
  };

  // Workspace Trust là boundary thật. Webview không được tự quyết định lúc nào
  // nó có quyền lấy source code, diagnostics hay Git diff.
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
  const counts = { error: 0, warning: 0, information: 0, hint: 0 };
  const diagnosticEntries = editor
    ? [[editor.document.uri, vscode.languages.getDiagnostics(editor.document.uri)] as const]
    : vscode.languages.getDiagnostics();
  for (const [uri, items] of diagnosticEntries) {
    for (const item of items) {
      const severityName = String(vscode.DiagnosticSeverity[item.severity] ?? 'Unknown');
      const key = severityName.toLowerCase() as keyof typeof counts;
      if (key in counts) {
        counts[key] += 1;
      }
      diagnostics.push({
        path: relativePath(uri),
        severity: severityName,
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
  context.problems = {
    counts,
    truncated: diagnostics.length >= DIAGNOSTIC_LIMIT,
    items: diagnostics,
  };

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

    let diff = '';
    try {
      if (typeof repo.diffWithHEAD === 'function') {
        const relativeActive = activeUri && root
          ? path.relative(root, activeUri.fsPath).replaceAll('\\', '/')
          : undefined;
        // File đang mở thường có signal tốt nhất; nếu không có thì lấy diff repo.
        diff = String(relativeActive ? await repo.diffWithHEAD(relativeActive) : await repo.diffWithHEAD());
        if (!diff.trim() && relativeActive) {
          diff = String(await repo.diffWithHEAD());
        }
      }
    } catch {
      diff = '';
    }

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
      diff: clip(diff, TEXT_LIMIT),
      diffTruncated: diff.length > TEXT_LIMIT,
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
