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

function workspaceInfo(): Record<string, unknown> {
  const editor = vscode.window.activeTextEditor;
  const folders = vscode.workspace.workspaceFolders ?? [];
  const activeFolder = editor ? vscode.workspace.getWorkspaceFolder(editor.document.uri) : folders[0];
  return {
    active: activeFolder?.uri.fsPath ?? '',
    trusted: vscode.workspace.isTrusted,
    folders: folders.map((folder) => ({ name: folder.name, path: folder.uri.fsPath })),
  };
}

function currentFileContext(includeExcerpt = true): Record<string, unknown> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    return { available: false };
  }
  const document = editor.document;
  const selection = editor.selection;
  const cursor = selection.active;
  const radius = 120;
  const startLine = Math.max(0, cursor.line - radius);
  const endLine = Math.min(document.lineCount - 1, cursor.line + radius);
  const excerpt = includeExcerpt
    ? document.getText(new vscode.Range(
      new vscode.Position(startLine, 0),
      document.lineAt(endLine).range.end,
    ))
    : '';
  return {
    available: true,
    path: relativePath(document.uri),
    absolutePath: document.uri.fsPath,
    languageId: document.languageId,
    version: document.version,
    dirty: document.isDirty,
    cursor: { line: cursor.line + 1, column: cursor.character + 1 },
    excerptStartLine: startLine + 1,
    excerpt: clip(excerpt),
  };
}

function selectionContext(): Record<string, unknown> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    return { available: false, empty: true, text: '' };
  }
  const selection = editor.selection;
  return {
    available: true,
    path: relativePath(editor.document.uri),
    empty: selection.isEmpty,
    start: { line: selection.start.line + 1, column: selection.start.character + 1 },
    end: { line: selection.end.line + 1, column: selection.end.character + 1 },
    text: clip(editor.document.getText(selection), 12_000),
  };
}

function problemsContext(scope: 'current' | 'workspace' = 'current'): Record<string, unknown> {
  const editor = vscode.window.activeTextEditor;
  const diagnostics: Array<Record<string, unknown>> = [];
  const counts = { error: 0, warning: 0, information: 0, hint: 0 };
  const diagnosticEntries = scope === 'current' && editor
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
  return { scope, counts, truncated: diagnostics.length >= DIAGNOSTIC_LIMIT, items: diagnostics };
}

function openEditorsContext(): Record<string, unknown> {
  const active = vscode.window.activeTextEditor?.document.uri;
  const seen = new Set<string>();
  const editors: Array<Record<string, unknown>> = [];
  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) {
      const input = tab.input as any;
      const uri: vscode.Uri | undefined = input?.uri ?? input?.modified ?? input?.original;
      if (!uri || uri.scheme !== 'file') {
        continue;
      }
      const key = uri.toString();
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      editors.push({
        path: relativePath(uri),
        active: Boolean(active && active.toString() === key),
        preview: Boolean(tab.isPreview),
        dirty: Boolean(tab.isDirty),
        pinned: Boolean(tab.isPinned),
      });
      if (editors.length >= 60) {
        return { count: editors.length, truncated: true, editors };
      }
    }
  }
  return { count: editors.length, truncated: false, editors };
}

/**
 * Lấy context semantic trực tiếp từ VS Code thay vì OCR giao diện IDE.
 * Payload luôn bị giới hạn để log/diff lớn không nuốt sạch prompt của agent.
 */
export async function captureIdeContext(terminalObserver?: TerminalContextObserver): Promise<Record<string, unknown>> {
  const context: Record<string, unknown> = {
    capturedAt: Date.now(),
    workspace: workspaceInfo(),
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

  const current = currentFileContext(true);
  if (current.available) {
    context.current = current;
    context.selection = selectionContext();
  }
  context.problems = problemsContext('current');
  context.git = await captureGitContext(vscode.window.activeTextEditor?.document.uri);
  context.openEditors = openEditorsContext();
  return context;
}

/**
 * Resolve một live IDE RPC từ Python. Đây là đường hai chiều: Gemini có thể hỏi
 * VS Code lại ở phút thứ 5 của task thay vì sống bằng snapshot từ lúc user bấm Send.
 */
export async function resolveIdeContextRequest(
  method: string,
  params: Record<string, unknown> = {},
  terminalObserver?: TerminalContextObserver,
): Promise<Record<string, unknown>> {
  if (!vscode.workspace.isTrusted && method !== 'ide.getWorkspaceInfo') {
    throw new Error('workspace_untrusted');
  }
  switch (method) {
    case 'ide.getCurrentFile':
      return currentFileContext(params.include_excerpt !== false && params.includeExcerpt !== false);
    case 'ide.getSelection':
      return selectionContext();
    case 'ide.getProblems':
      return problemsContext(String(params.scope ?? 'current') === 'workspace' ? 'workspace' : 'current');
    case 'ide.getGitState':
      return captureGitContext(vscode.window.activeTextEditor?.document.uri);
    case 'ide.getTerminalRecent':
      return terminalObserver?.snapshot() ?? { outputAvailable: false, recent: [] };
    case 'ide.getOpenEditors':
      return openEditorsContext();
    case 'ide.getWorkspaceInfo':
      return workspaceInfo();
    default:
      throw new Error(`IDE RPC không được hỗ trợ: ${method}`);
  }
}

export async function captureGitContext(activeUri?: vscode.Uri): Promise<Record<string, unknown>> {
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
