(() => {
  "use strict";

  const DEFAULT_ENDPOINT = "http://127.0.0.1:8765/v1/chess/snapshot";
  const PIECES = new Set(["wp", "wn", "wb", "wr", "wq", "wk", "bp", "bn", "bb", "br", "bq", "bk"]);
  const PIECE_FEN = {wp:"P",wn:"N",wb:"B",wr:"R",wq:"Q",wk:"K",bp:"p",bn:"n",bb:"b",br:"r",bq:"q",bk:"k"};
  let lastSignature = "";
  let timer = null;

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
    if (!settings.enabled) return;
    const board = boardNode();
    if (!board) return;
    const pieces = extractPieces(board);
    if (Object.keys(pieces).length < 2) return;
    const boardFen = toBoardFen(pieces);
    const result = gameResult();
    const payload = {
      platform: "chess.com",
      game_id: gameId(),
      board_fen: boardFen,
      page_url: location.href,
      orientation: orientation(board),
      ply: plyCount(),
      result,
      status: result ? "completed" : "active",
      mode_hint: detectModeHint(),
      mode_override: settings.modeOverride === "auto" ? "" : settings.modeOverride,
      captured_at: Date.now() / 1000,
      metadata: {title: document.title.slice(0, 180)}
    };
    const signature = JSON.stringify([payload.game_id, payload.board_fen, payload.ply, payload.result, payload.mode_override]);
    if (signature === lastSignature) return;
    lastSignature = signature;
    try {
      const response = await chrome.runtime.sendMessage({type: "eris_chess_snapshot", payload});
      if (!response || !response.ok) throw new Error(response && response.error || "bridge unavailable");
      document.documentElement.dataset.erisChessBridge = "connected";
    } catch (error) {
      document.documentElement.dataset.erisChessBridge = "disconnected";
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
