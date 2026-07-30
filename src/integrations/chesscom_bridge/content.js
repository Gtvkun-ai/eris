(() => {
  "use strict";

  const DEFAULT_ENDPOINT = "http://127.0.0.1:8765/v1/chess/snapshot";
  const INITIAL_BOARD_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR";
  const PIECES = new Set(["wp", "wn", "wb", "wr", "wq", "wk", "bp", "bn", "bb", "br", "bq", "bk"]);
  const PIECE_FEN = {wp:"P",wn:"N",wb:"B",wr:"R",wq:"Q",wk:"K",bp:"p",bn:"n",bb:"b",br:"r",bq:"q",bk:"k"};
  let lastSignature = "";
  let timer = null;

  let hintTimer = null;

  function fastHintText(observation) {
    if (!observation || typeof observation !== "object") return "";
    const suggestion = observation.suggestion || {};
    const san = String(suggestion.san || observation.suggested_move_san || "").trim();
    const uci = String(suggestion.uci || observation.suggested_move_uci || "").trim();
    if (san || uci) return `ERIS gợi ý: ${san || uci}${san && uci ? `  (${uci})` : ""}`;
    const focus = String(observation.hint_focus || "").trim();
    const labels = {
      king_safety: "Ưu tiên an toàn vua.",
      forcing_check: "Có nước chiếu đáng xem.",
      forcing_capture: "Kiểm tra các nước bắt quân cưỡng bức.",
      develop_piece: "Phát triển quân còn kẹt.",
      central_control: "Tranh chấp trung tâm.",
      improve_piece_activity: "Cải thiện hoạt động của quân."
    };
    return labels[focus] ? `ERIS: ${labels[focus]}` : "";
  }

  function showFastHint(observation) {
    const text = fastHintText(observation);
    if (!text) return;
    let node = document.getElementById("eris-chess-fast-hint");
    if (!node) {
      node = document.createElement("div");
      node.id = "eris-chess-fast-hint";
      Object.assign(node.style, {
        position: "fixed",
        left: "50%",
        bottom: "28px",
        transform: "translateX(-50%)",
        zIndex: "2147483647",
        maxWidth: "min(720px, 86vw)",
        padding: "10px 14px",
        borderRadius: "10px",
        background: "rgba(18, 18, 20, 0.92)",
        color: "#fff",
        font: "600 15px/1.35 system-ui, sans-serif",
        boxShadow: "0 8px 30px rgba(0,0,0,.35)",
        pointerEvents: "none"
      });
      document.documentElement.appendChild(node);
    }
    node.textContent = text;
    node.style.display = "block";
    clearTimeout(hintTimer);
    hintTimer = setTimeout(() => { node.style.display = "none"; }, 2600);
  }

  function remember(update) {
    try {
      chrome.storage.local.set(Object.assign({lastStatusAt: Date.now()}, update));
    } catch (_error) {
      // Best-effort diagnostics only.
    }
  }

  function boardNode() {
    const selectors = [
      "wc-chess-board",
      "chess-board",
      "#board-single",
      ".board-layout-chessboard .board",
      ".board-player-container .board",
      "[data-board]"
    ];
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      if (node && node.getBoundingClientRect().width > 120) return node;
    }
    return null;
  }

  function tokenPiece(node) {
    const data = String(node.getAttribute("data-piece") || "").toLowerCase();
    if (PIECES.has(data)) return data;
    for (const token of node.classList || []) {
      const normalized = String(token).toLowerCase();
      if (PIECES.has(normalized)) return normalized;
    }
    const aria = String(node.getAttribute("aria-label") || "").toLowerCase();
    const color = aria.includes("white") ? "w" : aria.includes("black") ? "b" : "";
    const names = {pawn:"p", knight:"n", bishop:"b", rook:"r", queen:"q", king:"k"};
    for (const [name, code] of Object.entries(names)) {
      if (color && aria.includes(name)) return color + code;
    }
    return "";
  }

  function tokenSquare(node) {
    const data = String(node.getAttribute("data-square") || "").toLowerCase();
    if (/^[a-h][1-8]$/.test(data)) return data;
    for (const token of node.classList || []) {
      const match = /^square-([1-8])([1-8])$/.exec(String(token));
      if (match) return "abcdefgh"[Number(match[1]) - 1] + match[2];
    }
    return "";
  }

  function extractPieces(board) {
    const pieces = {};
    const nodes = board.querySelectorAll(".piece, [data-piece], [class*='square-']");
    for (const node of nodes) {
      const piece = tokenPiece(node);
      const square = tokenSquare(node);
      if (piece && square) pieces[square] = PIECE_FEN[piece];
    }
    return pieces;
  }

  function toBoardFen(pieces) {
    const rows = [];
    for (let rank = 8; rank >= 1; rank--) {
      let row = "";
      let empty = 0;
      for (const file of "abcdefgh") {
        const piece = pieces[file + rank];
        if (!piece) {
          empty++;
        } else {
          if (empty) row += String(empty);
          empty = 0;
          row += piece;
        }
      }
      if (empty) row += String(empty);
      rows.push(row);
    }
    return rows.join("/");
  }

  function orientation(board) {
    const cls = String(board.className || "").toLowerCase();
    if (cls.includes("flipped") || cls.includes("black")) return "black";
    const coords = board.querySelector(".coordinates, .board-coordinates, [class*='coordinate']");
    if (coords && /^8/.test(String(coords.textContent || "").trim())) return "black";
    return "white";
  }

  function plyCount() {
    let maxPly = -1;
    for (const node of document.querySelectorAll("[data-ply]")) {
      const value = Number(node.getAttribute("data-ply"));
      if (Number.isFinite(value)) maxPly = Math.max(maxPly, value);
    }
    if (maxPly >= 0) return maxPly + 1;
    const candidates = document.querySelectorAll(
      "wc-simple-move-list .node, vertical-move-list .node, .move-list .node, [class*='move-list'] [class*='node']"
    );
    return Array.from(candidates).filter(node => /[a-hKQRBNO0]/.test(String(node.textContent || ""))).length;
  }

  function gameId() {
    const match = location.pathname.match(/\/game\/(?:live|daily|computer)\/(\d+)/i);
    if (match) return match[1];
    const board = boardNode();
    const attr = board && (board.getAttribute("data-game-id") || board.getAttribute("game-id"));
    if (attr) return String(attr);
    return btoa(unescape(encodeURIComponent(location.pathname + location.search))).replace(/=+$/g, "").slice(0, 80);
  }

  function detectModeHint() {
    const path = location.pathname.toLowerCase();
    const query = location.search.toLowerCase();
    if (path.includes("/analysis") || path.includes("/game/analysis")) return "analysis";
    if (path.includes("/play/computer") || path.includes("/game/computer") || path.includes("/practice") || path.includes("/puzzles")) return "bot";
    if (query.includes("bot=") || query.includes("computer")) return "bot";
    if (path.includes("/game/live/") || path.includes("/game/daily/") || path.includes("/play/online")) return "live_restricted";
    return "unknown";
  }

  function gameResult() {
    const selectors = [
      "[data-cy='game-result']",
      ".game-over-modal-content",
      ".game-result",
      "[class*='result-component']",
      "[class*='game-over']"
    ];
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      const text = String(node && node.textContent || "").trim();
      const result = text.match(/(?:1-0|0-1|1\/2-1\/2|½-½)/);
      if (result) return result[0].replace("½-½", "1/2-1/2");
    }
    return "";
  }

  function clockRunning() {
    // Chess.com thay class theo từng layout, nên chỉ dùng các dấu hiệu tương đối
    // bảo thủ. Sai âm tính còn đỡ hơn tuyên bố ván bắt đầu khi người dùng mới
    // mở bàn và chưa bấm chơi.
    const selectors = [
      ".clock-component.clock-player-turn",
      "[class*='clock'][class*='player-turn']",
      "[class*='clock'][class*='active']",
      "[data-cy='clock-active']"
    ];
    return selectors.some(selector => Boolean(document.querySelector(selector)));
  }

  function loadSettings() {
    return new Promise(resolve => {
      chrome.storage.local.get(
        {endpoint: DEFAULT_ENDPOINT, token: "", modeOverride: "auto", enabled: true},
        resolve
      );
    });
  }

  async function capture() {
    const settings = await loadSettings();
    if (!settings.enabled) {
      remember({lastStatus: "Bridge disabled", lastError: ""});
      return;
    }
    const board = boardNode();
    if (!board) {
      remember({lastStatus: "No Chess.com board found in this tab", lastError: ""});
      return;
    }
    const pieces = extractPieces(board);
    const pieceCount = Object.keys(pieces).length;
    if (pieceCount < 2) {
      remember({
        lastStatus: "Board found, but pieces were not readable",
        lastError: `pieces=${pieceCount}`
      });
      return;
    }
    const boardFen = toBoardFen(pieces);
    const result = gameResult();
    const ply = plyCount();
    const running = clockRunning();
    const started = ply > 0 || running || boardFen !== INITIAL_BOARD_FEN;
    const payload = {
      platform: "chess.com",
      game_id: gameId(),
      board_fen: boardFen,
      page_url: location.href,
      orientation: orientation(board),
      ply,
      result,
      status: result ? "completed" : (started ? "active" : "ready"),
      mode_hint: detectModeHint(),
      mode_override: settings.modeOverride === "auto" ? "" : settings.modeOverride,
      captured_at: Date.now() / 1000,
      metadata: {
        title: document.title.slice(0, 180),
        // Hai cờ này giúp runtime phân biệt "đã thấy bàn" với "ván đã chạy".
        game_started: started,
        clock_running: running
      }
    };
    const signature = JSON.stringify([
      payload.game_id,
      payload.board_fen,
      payload.ply,
      payload.result,
      payload.status,
      payload.mode_override
    ]);
    if (signature === lastSignature) return;
    lastSignature = signature;
    try {
      remember({
        lastStatus: "Board captured; sending snapshot",
        lastError: "",
        lastBoardFen: boardFen,
        lastGameId: payload.game_id,
        lastModeHint: payload.mode_hint,
        lastPageUrl: payload.page_url
      });
      const response = await chrome.runtime.sendMessage({type: "eris_chess_snapshot", payload});
      if (!response || !response.ok) throw new Error(response && response.error || "bridge unavailable");
      showFastHint(response.observation || {});
      document.documentElement.dataset.erisChessBridge = "connected";
    } catch (error) {
      document.documentElement.dataset.erisChessBridge = "disconnected";
      remember({lastStatus: "Snapshot failed", lastError: String(error), lastBoardFen: boardFen});
      console.debug("[ERIS chess bridge]", error);
    }
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(capture, 140);
  }

  new MutationObserver(schedule).observe(document.documentElement, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ["class", "data-square", "data-piece", "data-ply"]
  });
  window.addEventListener("popstate", schedule);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) schedule(); });
  setInterval(schedule, 2500);
  schedule();
})();
