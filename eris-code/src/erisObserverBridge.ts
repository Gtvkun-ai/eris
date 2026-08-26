import * as vscode from 'vscode';

/**
 * Optional, deliberately one-way bridge. Eris Desktop may contribute observation
 * and long-term project memory, but it never owns a coding task and is never launched
 * by the extension.
 */
export class ErisObserverBridge {
  async readProjectContext(workspaceRoot: string): Promise<Record<string, unknown> | undefined> {
    const config = vscode.workspace.getConfiguration('erisCode.erisLink');
    if (!config.get<boolean>('enabled', false)) return undefined;
    const endpoint = String(config.get<string>('endpoint', 'http://127.0.0.1:8767/v1/context')).trim();
    if (!endpoint) return undefined;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 900);
    try {
      const url = new URL(endpoint);
      url.searchParams.set('workspace', workspaceRoot);
      const response = await fetch(url, { signal: controller.signal, headers: { accept: 'application/json' } });
      if (!response.ok) return undefined;
      const body = await response.json();
      return body && typeof body === 'object' ? body as Record<string, unknown> : undefined;
    } catch {
      // Optional means optional: a closed Eris Desktop is a normal state.
      return undefined;
    } finally {
      clearTimeout(timer);
    }
  }
}
