"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.ErisObserverBridge = void 0;
const vscode = __importStar(require("vscode"));
/**
 * Optional Eris Link.
 *
 * Desktop -> Code: GET project/environment context (read-only).
 * Code -> Desktop: POST observation append-only.
 *
 * V90 mở observation ra workspace/user/external-agent nhưng boundary authority giữ
 * nguyên: Desktop không điều khiển GitPilot, approve tool, chạy terminal hay sửa file.
 */
class ErisObserverBridge {
    queue = [];
    draining = false;
    static MAX_QUEUE = 160;
    async readProjectContext(workspaceRoot) {
        if (!this.enabled())
            return undefined;
        const endpoint = this.contextEndpoint();
        if (!endpoint)
            return undefined;
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 900);
        try {
            const url = new URL(endpoint);
            url.searchParams.set('workspace', workspaceRoot);
            const response = await fetch(url, { signal: controller.signal, headers: { accept: 'application/json' } });
            if (!response.ok)
                return undefined;
            const body = await response.json();
            return body && typeof body === 'object' ? body : undefined;
        }
        catch {
            return undefined;
        }
        finally {
            clearTimeout(timer);
        }
    }
    /**
     * V90 bounded telemetry queue. Companion observation tuyệt đối không được tạo
     * backpressure lên coding path khi Desktop đóng/mất port.
     */
    publishCodingObservation(observation) {
        if (!this.enabled())
            return;
        if (this.queue.length >= ErisObserverBridge.MAX_QUEUE) {
            // Ưu tiên giữ user intent + coding-agent lifecycle. Drop metadata workspace
            // dễ tái tạo trước (focus/diagnostics/save) khi queue nghẽn.
            const index = this.queue.findIndex((item) => item.source === 'eris-code/workspace'
                && ['editor_focus', 'diagnostics', 'file_saved'].includes(item.event_type));
            if (index >= 0)
                this.queue.splice(index, 1);
            else
                this.queue.shift();
        }
        this.queue.push(observation);
        void this.drain();
    }
    async drain() {
        if (this.draining)
            return;
        this.draining = true;
        try {
            while (this.queue.length) {
                const observation = this.queue.shift();
                if (!observation)
                    continue;
                await this.postObservation(observation);
            }
        }
        finally {
            this.draining = false;
        }
    }
    async postObservation(observation) {
        const contextEndpoint = this.contextEndpoint();
        if (!contextEndpoint)
            return;
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
        }
        catch {
            // Telemetry không bao giờ được biến thành dependency của coding path.
        }
        finally {
            clearTimeout(timer);
        }
    }
    enabled() {
        return vscode.workspace.getConfiguration('erisCode.erisLink').get('enabled', false);
    }
    contextEndpoint() {
        return String(vscode.workspace.getConfiguration('erisCode.erisLink')
            .get('endpoint', 'http://127.0.0.1:8767/v1/context')).trim();
    }
}
exports.ErisObserverBridge = ErisObserverBridge;
//# sourceMappingURL=erisObserverBridge.js.map