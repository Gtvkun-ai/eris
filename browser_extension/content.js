// ERIS Browser Bridge — content.js
// Chạy trong context của mỗi trang (không phải extension context).
// Nhiệm vụ: đọc media state, visible text, rồi gửi về background.js khi có thay đổi.

(function () {
  "use strict";

  // Guard: chỉ chạy 1 lần duy nhất trên mỗi trang
  if (window.__ERIS_BRIDGE_LOADED) return;
  window.__ERIS_BRIDGE_LOADED = true;

  const MAX_VISIBLE_TEXT = 600;

  // -------------------------------------------------------------------------
  // Đọc Media Session API (Chrome/Brave hỗ trợ)
  // -------------------------------------------------------------------------
  function getMediaSession() {
    if (typeof navigator.mediaSession === "undefined") return null;
    const ms = navigator.mediaSession;
    const meta = ms.metadata;
    if (!meta && ms.playbackState === "none") return null;
    return {
      title: meta?.title || "",
      artist: meta?.artist || "",
      album: meta?.album || "",
      channel: meta?.album || "",  // YouTube dùng album cho channel
      artwork: (meta?.artwork || [])[0]?.src || "",
      state: ms.playbackState || "none", // "playing" | "paused" | "none"
    };
  }

  // -------------------------------------------------------------------------
  // Đọc YouTube cụ thể
  // -------------------------------------------------------------------------
  function getYouTubeData() {
    const titleEl = document.querySelector(
      "yt-formatted-string.ytd-video-primary-info-renderer, " +
      ".title.style-scope.ytd-video-primary-info-renderer, " +
      "h1.ytd-video-primary-info-renderer .yt-formatted-string, " +
      ".content-info-wrapper .title, " +
      "[title][class*='song-title']"
    );
    const channelEl = document.querySelector(
      "#owner-name a, .ytd-channel-name a, " +
      ".content-info-wrapper .subtitle a"
    );
    const playerEl = document.querySelector("video");
    if (!titleEl && !playerEl) return null;
    const state = playerEl
      ? (playerEl.paused ? "paused" : "playing")
      : "unknown";
    return {
      title: titleEl?.textContent?.trim() || document.title?.split(" - YouTube")[0]?.trim() || "",
      artist: channelEl?.textContent?.trim() || "",
      channel: channelEl?.textContent?.trim() || "",
      state,
    };
  }

  // -------------------------------------------------------------------------
  // Đọc Spotify Web Player
  // -------------------------------------------------------------------------
  function getSpotifyData() {
    const titleEl = document.querySelector(
      "[data-testid='context-item-info-title'], " +
      "[data-testid='track-info-name'], " +
      ".encore-text[class*='track-name']"
    );
    const artistEl = document.querySelector(
      "[data-testid='context-item-info-subtitles'] a, " +
      "[data-testid='track-info-artists'] a"
    );
    const pauseBtn = document.querySelector("[data-testid='control-button-pause']");
    if (!titleEl) return null;
    return {
      title: titleEl?.textContent?.trim() || "",
      artist: artistEl?.textContent?.trim() || "",
      state: pauseBtn ? "playing" : "paused",
    };
  }

  // -------------------------------------------------------------------------
  // Visible text từ body (chỉ gọi 1 lần khi load trang để tránh lag)
  // -------------------------------------------------------------------------
  let cachedVisibleText = "";
  let lastTextUpdate = 0;

  function getVisibleText(force = false) {
    const now = Date.now();
    // Update text at most once every 10 seconds to absolutely avoid lagging the browser
    if (!force && cachedVisibleText && (now - lastTextUpdate < 10000)) {
      return cachedVisibleText;
    }
    try {
      const body = document.body;
      if (!body) return "";
      const clone = body.cloneNode(true);
      clone.querySelectorAll("script, style, noscript, nav, footer, aside, [aria-hidden='true']").forEach(el => el.remove());
      cachedVisibleText = (clone.innerText || clone.textContent || "")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, MAX_VISIBLE_TEXT);
      lastTextUpdate = now;
      return cachedVisibleText;
    } catch {
      return cachedVisibleText;
    }
  }

  // -------------------------------------------------------------------------
  // Tổng hợp và gửi
  // -------------------------------------------------------------------------
  let lastSentHash = "";

  function collectAndSend(force = false) {
    const url = location.href;
    const title = document.title;

    let media = null;
    const host = location.hostname;
    if (host.includes("youtube.com") || host.includes("youtu.be")) {
      media = getYouTubeData() || getMediaSession();
    } else if (host.includes("spotify.com")) {
      media = getSpotifyData() || getMediaSession();
    } else {
      media = getMediaSession();
    }

    const visibleText = getVisibleText(force);

    const hash = `${url}|${title}|${media?.title}|${media?.state}`;
    const changed = force || (hash !== lastSentHash);
    lastSentHash = hash;

    if (changed) {
      chrome.runtime.sendMessage({
        type: "ERIS_TAB_DATA",
        url,
        title,
        media,
        visibleText,
      }).catch(() => {});
    }
  }

  // Chạy lần đầu
  collectAndSend(true);

  // Theo dõi media state (nhanh, không lag)
  setInterval(() => collectAndSend(false), 2000);

  // HEARTBEAT SIÊU NHẸ: Giữ Service Worker sống và đẩy fresh timestamp cho ERIS
  // Không đụng vào DOM, chi phí CPU = 0.
  setInterval(() => {
    chrome.runtime.sendMessage({ type: "ERIS_HEARTBEAT" }).catch(() => {});
  }, 3000);

  // Theo dõi thay đổi URL (SPA)
  let lastHref = location.href;
  const observer = new MutationObserver(() => {
    if (location.href !== lastHref) {
      lastHref = location.href;
      lastSentHash = ""; 
      setTimeout(() => collectAndSend(true), 1000);
    }
  });
  observer.observe(document.body || document.documentElement, { childList: true, subtree: true });
})();
