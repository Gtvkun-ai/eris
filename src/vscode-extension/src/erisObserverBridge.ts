import * as vscode from 'vscode';
import type { CodingObservation } from './codingObservation';

/**
 * Optional Eris Link.
 *
 * Desktop -> Code: GET project/environment context (read-only).
 * Code -> Desktop: POST observation append-only.
 *
 * V90 mở observation ra workspace/user/external-agent nhưng boundary authority giữ
 * nguyên: Desktop không điều khiển GitPilot, approve tool, chạy terminal hay sửa file.
 */
export class ErisObserverBridge {
  private readonly queue: CodingObservation[] = [];
  private draining = false;
  private static readonly MAX_QUEUE = 160;

  async readProjectContext(workspaceRoot: string): Promise<Record<string, unknown> | undefined> {
    if (!this.enabled()) return undefined;
    const endpoint = this.contextEndpoint();
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
      return undefined;
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * V90 bounded telemetry queue. Companion observation tuyệt đối không được tạo
   * backpressure lên coding path khi Desktop đóng/mất port.
   */
  publishCodingObservation(observation: CodingObservation): void {
    if (!this.enabled()) return;
    if (this.queue.length >= ErisObserverBridge.MAX_QUEUE) {
      // Ưu tiên giữ user intent + coding-agent lifecycle. Drop metadata workspace
      // dễ tái tạo trước (focus/diagnostics/save) khi queue nghẽn.
      const index = this.queue.findIndex((item) =>
        item.source === 'eris-code/workspace'
        && ['editor_focus', 'diagnostics', 'file_saved'].includes(item.event_type),
      );
      if (index >= 0) this.queue.splice(index, 1);
      else this.queue.shift();
    }
    this.queue.push(observation);
    void this.drain();
  }

  private async drain(): Promise<void> {
    if (this.draining) return;
    this.draining = true;
    try {
      while (this.queue.length) {
        const observation = this.queue.shift();
        if (!observation) continue;
        await this.postObservation(observation);
      }
    } finally {
      this.draining = false;
    }
  }

  private async postObservation(observation: CodingObservation): Promise<void> {
    const contextEndpoint = this.contextEndpoint();
    if (!contextEndpoint) return;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 700);
    try {
      const url = new URL(contextEndpoint);
      url.pathname = '/v1/coding/observations';
      url.search = '';
      await fetch(url, {
        method: 'POST',
        signal: controller.signal,
        headers: { 'content-type': 'application/json', accept: 'application/json' },
        body: JSON.stringify(observation),
      });
    } catch {
      // Telemetry không bao giờ được biến thành dependency của coding path.
    } finally {
      clearTimeout(timer);
    }
  }

  private enabled(): boolean {
    return vscode.workspace.getConfiguration('erisCode.erisLink').get<boolean>('enabled', false);
  }

  private contextEndpoint(): string {
    return String(
      vscode.workspace.getConfiguration('erisCode.erisLink')
        .get<string>('endpoint', 'http://127.0.0.1:8767/v1/context'),
    ).trim();
  }
}
