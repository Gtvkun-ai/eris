import * as crypto from 'node:crypto';
import * as vscode from 'vscode';

/**
 * Chỉ dựng shell HTML và CSP cho Webview.
 *
 * Toàn bộ presentation nằm ở media/eris-chat.css + media/eris-chat.js để
 * Extension Host không biến thành một file TypeScript chứa cả backend lẫn UI.
 */
export function renderChatWebviewHtml(webview: vscode.Webview, extensionUri: vscode.Uri): string {
  const nonce = crypto.randomBytes(16).toString('hex');
  const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', 'eris-chat.css'));
  const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', 'eris-chat.js'));

  return `<!doctype html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource} data: blob:; style-src ${webview.cspSource}; script-src 'nonce-${nonce}' ${webview.cspSource};" />
  <link rel="stylesheet" href="${styleUri}" />
  <title>Eris</title>
</head>
<body>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand" title="Eris coding agent">
        <span class="brand-mark" aria-hidden="true">✦</span>
        <div class="brand-copy">
          <strong>Eris</strong>
          <span id="sessionHeaderTitle">AI coding agent</span>
        </div>
      </div>
      <div class="top-actions">
        <button id="newChat" class="icon-btn" type="button" title="Phiên mới" aria-label="Phiên mới">＋</button>
        <button id="menuButton" class="icon-btn" type="button" title="Menu" aria-label="Menu">⋯</button>
      </div>
      <div class="session-shadow" aria-hidden="true">
        <div id="sessionTabs" class="session-tabs"></div>
        <span id="sessionIndicator" class="session-indicator"></span>
      </div>
    </header>

    <!-- Không coi backend chưa chạy là lỗi. Thanh này chỉ hiện lúc thực sự kết nối. -->
    <div id="connection" class="connection" role="status" aria-live="polite">
      <span class="connection-spinner" aria-hidden="true"></span>
      <span id="connectionText">Đang khởi động Eris…</span>
      <button id="reconnect" type="button">Thử lại</button>
    </div>

    <main class="workspace">
      <section class="conversation">
        <div id="timeline" class="timeline"></div>
        <div id="notice" class="notice" role="status" aria-live="polite"></div>
      </section>

      <section id="drawer" class="drawer" aria-label="Eris drawer">
        <div class="drawer-head">
          <button id="drawerBack" class="icon-btn" type="button" aria-label="Quay lại">‹</button>
          <strong id="drawerTitle">Lịch sử</strong>
        </div>
        <div id="drawerBody" class="drawer-body"></div>
      </section>

      <div id="menuPopover" class="menu-popover popover" role="menu">
        <button class="menu-row" type="button" data-menu="new"><span>＋</span><span>Phiên mới</span></button>
        <button class="menu-row" type="button" data-menu="history"><span>◷</span><span>Hội thoại gần đây</span></button>
        <button class="menu-row" type="button" data-menu="tasks"><span>✓</span><span>Tác vụ</span></button>
        <button class="menu-row" type="button" data-menu="skills"><span>⌘</span><span>Kỹ năng</span></button>
        <div class="menu-sep"></div>
        <button class="menu-row" type="button" data-menu="source"><span>⑂</span><span>Source Control</span></button>
        <button class="menu-row" type="button" data-menu="test"><span>⚗</span><span>Self test</span></button>
        <button class="menu-row" type="button" data-menu="reconnect"><span>↻</span><span>Kết nối lại</span></button>
        <button class="menu-row" type="button" data-menu="settings"><span>⚙</span><span>Cài đặt</span></button>
      </div>

      <div id="dropOverlay" class="drop-overlay">Thả file hoặc ảnh vào đây</div>
    </main>

    <footer class="composer-wrap">
      <div id="attachments" class="attachments"></div>
      <div id="contextSummary" class="context-summary"></div>

      <div class="composer-box">
        <textarea id="input" rows="1" placeholder="Giao việc cho Eris…" aria-label="Tin nhắn cho Eris"></textarea>
        <div class="composer-bar">
          <button id="attach" class="composer-action" type="button" title="Đính kèm file hoặc ảnh" aria-label="Đính kèm">＋</button>
          <button id="contextButton" class="composer-action context-button" type="button" title="Context" aria-label="Context">#</button>

          <div class="select-wrap">
            <button id="modeButton" class="composer-select" type="button" title="Chế độ tác vụ" aria-haspopup="listbox" aria-expanded="false">Tác vụ</button>
            <div id="modePopover" class="select-popover popover" role="listbox" aria-label="Chế độ tác vụ">
              <button class="select-option" type="button" data-mode-option="execute">
                <span class="select-icon">◈</span><span class="select-copy"><strong>Tác vụ</strong><small>Sửa code và kiểm chứng</small></span><span class="select-check">✓</span>
              </button>
              <button class="select-option" type="button" data-mode-option="inspect">
                <span class="select-icon">⌕</span><span class="select-copy"><strong>Chỉ xem</strong><small>Phân tích, không sửa file</small></span><span class="select-check">✓</span>
              </button>
            </div>
          </div>

          <div class="select-wrap model-wrap">
            <button id="modelButton" class="composer-select" type="button" title="Mô hình DeepSeek" aria-haspopup="listbox" aria-expanded="false">DS Flash</button>
            <div id="modelPopover" class="select-popover popover" role="listbox" aria-label="Mô hình DeepSeek">
              <button class="select-option" type="button" data-model-option="deepseek-v4-flash"><span class="select-icon">⚡</span><span class="select-copy"><strong>DS Flash</strong><small>Nhanh, mặc định</small></span><span class="select-check">✓</span></button>
              <button class="select-option" type="button" data-model-option="deepseek-v4-pro"><span class="select-icon">◆</span><span class="select-copy"><strong>DS Pro</strong><small>Task khó hơn</small></span><span class="select-check">✓</span></button>
              <button class="select-option" type="button" data-model-option="auto"><span class="select-icon">⌁</span><span class="select-copy"><strong>Auto</strong><small>Theo cấu hình backend</small></span><span class="select-check">✓</span></button>
            </div>
          </div>

          <button id="send" class="send" type="button" title="Gửi" aria-label="Gửi">↑</button>
        </div>
      </div>

      <div id="contextPopover" class="context-popover popover">
        <div class="popover-title">Context cho lượt này</div>
        <label class="context-row"><input type="checkbox" value="current" checked /><span>File hiện tại</span></label>
        <label class="context-row"><input type="checkbox" value="selection" checked /><span>Vùng chọn</span></label>
        <label class="context-row"><input type="checkbox" value="problems" checked /><span>Lỗi / cảnh báo</span></label>
        <label class="context-row"><input type="checkbox" value="git" checked /><span>Thay đổi Git</span></label>
        <label class="context-row"><input type="checkbox" value="terminal" /><span>Terminal gần đây</span></label>
        <label class="context-row"><input type="checkbox" value="openEditors" /><span>Tab đang mở</span></label>
      </div>
    </footer>
  </div>

  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
}
