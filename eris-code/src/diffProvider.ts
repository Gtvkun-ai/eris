import * as path from 'node:path';
import * as vscode from 'vscode';

const SCHEME = 'eris-before';

function isInside(root: string, candidate: string): boolean {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

/**
 * Provider cho phía "before" của native VS Code diff.
 *
 * File thật vẫn do VS Code mở. Baseline chỉ là document ảo read-only lấy từ HEAD,
 * nên Webview không được cấp thêm quyền file nào và nút Diff vẫn dùng editor chuẩn.
 */
export class WorkspaceDiffProvider implements vscode.TextDocumentContentProvider, vscode.Disposable {
  private readonly contents = new Map<string, string>();
  private readonly registration: vscode.Disposable;

  constructor() {
    this.registration = vscode.workspace.registerTextDocumentContentProvider(SCHEME, this);
  }

  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.contents.get(uri.toString()) ?? '';
  }

  async openDiff(filePath: string, patchText = ''): Promise<void> {
    const current = await resolveWorkspaceFile(filePath);
    if (!current) {
      throw new Error(`Không tìm thấy file trong workspace: ${filePath}`);
    }

    const git = await getGitApi();
    const repo = git?.getRepository?.(current)
      ?? git?.repositories?.find((item: any) => isInside(String(item?.rootUri?.fsPath ?? ''), current.fsPath))
      ?? git?.repositories?.[0];

    if (repo) {
      const root = String(repo.rootUri?.fsPath ?? '');
      const relative = root ? path.relative(root, current.fsPath).replaceAll('\\', '/') : filePath;
      try {
        const baseline = String(await repo.show('HEAD', relative));
        const beforeUri = vscode.Uri.from({
          scheme: SCHEME,
          path: `/${relative}`,
          query: `key=${encodeURIComponent(`${Date.now()}_${Math.random()}`)}`,
        });
        this.contents.set(beforeUri.toString(), baseline);
        await vscode.commands.executeCommand('vscode.diff', beforeUri, current, `Eris Diff: ${relative}`);
        return;
      } catch {
        // File mới/untracked sẽ không có HEAD baseline. Rơi xuống diff text nếu
        // backend đã gửi patch; nếu không thì baseline rỗng vẫn hữu ích hơn im lặng.
        const beforeUri = vscode.Uri.from({
          scheme: SCHEME,
          path: `/${relative}`,
          query: `key=${encodeURIComponent(`${Date.now()}_${Math.random()}`)}`,
        });
        this.contents.set(beforeUri.toString(), '');
        await vscode.commands.executeCommand('vscode.diff', beforeUri, current, `Eris Diff: ${relative}`);
        return;
      }
    }

    if (patchText.trim()) {
      const document = await vscode.workspace.openTextDocument({
        language: 'diff',
        content: patchText,
      });
      await vscode.window.showTextDocument(document, { preview: true, preserveFocus: false });
      return;
    }
    throw new Error('Workspace không có Git baseline để mở diff.');
  }

  dispose(): void {
    this.registration.dispose();
    this.contents.clear();
  }
}

async function getGitApi(): Promise<any | undefined> {
  try {
    const extension = vscode.extensions.getExtension('vscode.git');
    if (!extension) {
      return undefined;
    }
    if (!extension.isActive) {
      await extension.activate();
    }
    return extension.exports?.getAPI?.(1);
  } catch {
    return undefined;
  }
}

export async function resolveWorkspaceFile(filePath: string): Promise<vscode.Uri | undefined> {
  const clean = String(filePath ?? '').trim();
  if (!clean || !vscode.workspace.isTrusted) {
    return undefined;
  }
  const folders = vscode.workspace.workspaceFolders ?? [];
  if (!folders.length) {
    return undefined;
  }

  if (path.isAbsolute(clean)) {
    const absolute = path.resolve(clean);
    if (!folders.some((folder) => isInside(folder.uri.fsPath, absolute))) {
      throw new Error('Eris từ chối mở file nằm ngoài workspace đã Trust.');
    }
    const uri = vscode.Uri.file(absolute);
    try {
      await vscode.workspace.fs.stat(uri);
      return uri;
    } catch {
      return undefined;
    }
  }

  const normalized = clean.replaceAll('\\', '/').replace(/^\/+/, '');
  for (const folder of folders) {
    const candidatePath = path.resolve(folder.uri.fsPath, normalized);
    if (!isInside(folder.uri.fsPath, candidatePath)) {
      continue;
    }
    const uri = vscode.Uri.file(candidatePath);
    try {
      await vscode.workspace.fs.stat(uri);
      return uri;
    } catch {
      // Multi-root workspace: thử folder tiếp theo.
    }
  }
  return undefined;
}
