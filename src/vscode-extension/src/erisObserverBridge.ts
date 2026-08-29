import * as vscode from 'vscode';
import type { CodingObservation } from './codingObservation';

/**
 * Optional Eris Link.
 *
 * V79 có hai luồng rất hẹp:
 * - Desktop -> Code: GET project/environment context (read-only).
 * - Code -> Desktop: POST coding telemetry append-only.
 *
 * Không có endpoint nào để Desktop điều khiển GitPilot, approve tool, chạy
 * terminal hay sửa workspace. Desktop tắt thì extension vẫn hoạt động bình thường.
 */
export class ErisObserverBridge {
  private publishTail: Promise<void> = Promise.resolve();

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
      // Optional means optional: Eris Desktop đóng là trạng thái bình thường.
      return undefined;
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * Đẩy observation theo thứ tự nhưng không block coding stream.
   * Nếu Desktop tắt hoặc port bận, telemetry bị bỏ qua thay vì làm task fail.
   */
  publishCodingObservation(observation: CodingObservation): void {
    if (!this.enabled()) return;
    this.publishTail = this.publishTail
      .catch(() => undefined)
      .then(() => this.postObservation(observation));
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
