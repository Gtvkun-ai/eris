// ERIS Browser Bridge — background.js v1.2 (HTTP server approach)
//
// Thay vì Native Messaging (registry + bat), extension POST JSON
// sang http://127.0.0.1:7422/update — đơn giản và đáng tin hơn.
//
// Server: native_host/eris_bridge_server.py (chạy độc lập)

const SERVER_URL   = "http://127.0.0.1:7422/update";
const HEALTH_URL   = "http://127.0.0.1:7422/health";
const ALARM_NAME   = "eris_tick";
const STALE_SEC    = 10;
const TICK_PERIOD  = 0.05; // phút = 3 giây (unpacked extension cho phép)

// Cache từng tab: tabId → {url, title, media, visibleText, ts}
const tabCache = new Map();

// --------------------------------------------------------------------------
// Message từ content script
// --------------------------------------------------------------------------
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "ERIS_TAB_DATA") {
    const id = sender.tab?.id;
    if (id) {
      tabCache.set(id, {
        url:         msg.url         || sender.tab?.url   || "",
        title:       msg.title       || sender.tab?.title || "",
        media:       msg.media       || null,
        visibleText: msg.visibleText || "",
        ts:          Date.now() / 1000,
      });
    }
    // Ghi ra server ngay lập tức để giữ timestamp < 12s cho ERIS
    tick(id).then(() => sendResponse({ ok: true })).catch(() => sendResponse({ ok: false }));
    return true;
  }
  if (msg?.type === "ERIS_HEARTBEAT") {
    const id = sender.tab?.id;
    tick(id).then(() => sendResponse({ ok: true })).catch(() => sendResponse({ ok: false }));
    return true;
  }
});

chrome.tabs.onRemoved.addListener((id) => tabCache.delete(id));

// --------------------------------------------------------------------------
// Alarm setup
// --------------------------------------------------------------------------
function setupAlarm() {
  chrome.alarms.get(ALARM_NAME, (a) => {
    if (!a) chrome.alarms.create(ALARM_NAME, { periodInMinutes: TICK_PERIOD });
  });
}

chrome.runtime.onInstalled.addListener(setupAlarm);
chrome.runtime.onStartup.addListener(setupAlarm);
chrome.alarms.onAlarm.addListener((a) => { if (a.name === ALARM_NAME) tick(); });
setupAlarm();

// --------------------------------------------------------------------------
// Build payload
// --------------------------------------------------------------------------
function buildPayload(tab, cached) {
  const now   = Date.now() / 1000;
  const url   = tab?.url   || "";
  const title = tab?.title || "";
  const fresh = cached && (now - cached.ts) < STALE_SEC ? cached : null;
  const media = fresh?.media || null;

  const allTabs = [...tabCache.values()].map(d => d.title).filter(Boolean).slice(0, 12);

  const p = {
    timestamp:        now,
    source:           media?.title ? "media_session" : "browser_dom",
    confidence:       fresh ? (media?.title ? 0.90 : 0.85) : 0.50,
    url,
    title,
    visible_text:     fresh?.visibleText || "",
    all_tabs:         allTabs,
    active_tab_title: title,
    page_kind:        inferPageKind(url),
  };
  if (media) {
    p.media_title = media.title  || "";
    p.creator     = media.artist || media.channel || "";
    p.media_state = media.state  || "unknown";
  }
  return p;
}

function inferPageKind(url) {
  const u = (url || "").toLowerCase();
  if (u.includes("music.youtube.com"))    return "youtube_music";
  if (u.includes("youtube.com/watch") || u.includes("youtu.be")) return "youtube_video";
  if (u.includes("tiktok.com"))           return "tiktok_video";
  if (u.includes("twitch.tv"))            return "stream";
  if (u.includes("spotify.com") || u.includes("soundcloud.com")) return "music";
  if (u.includes("github.com")  || u.includes("gitlab.com"))     return "repository";
  if (u.includes("discord.com") || u.includes("mail.google") || u.includes("outlook")) return "communication";
  return "unknown";
}

// --------------------------------------------------------------------------
// POST lên server
// --------------------------------------------------------------------------
async function postToServer(payload) {
  try {
    const resp = await fetch(SERVER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return resp.ok;
  } catch {
    return false; // Server chưa chạy
  }
}

async function checkServerHealth() {
  try {
    const r = await fetch(HEALTH_URL);
    return r.ok;
  } catch {
    return false;
  }
}

// --------------------------------------------------------------------------
// Tick chính
// --------------------------------------------------------------------------
async function tick(forcedTabId = null) {
  try {
    let tab = null;
    if (forcedTabId) {
      try { tab = await chrome.tabs.get(forcedTabId); } catch(e){}
    }
    if (!tab) {
      const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
      tab = tabs[0];
    }
    if (!tab?.id) return;

    const cached  = tabCache.get(tab.id) || null;
    const payload = buildPayload(tab, cached);

    // Ghi storage cho popup đọc (không phụ thuộc server)
    await chrome.storage.local.set({ eris_bridge_last: payload });

    const serverOk = await postToServer(payload);
    await chrome.storage.local.set({ eris_bridge_server_ok: serverOk });

  } catch (e) {
    console.error("[ERIS Bridge] tick:", e);
  }
}

// Chạy ngay
tick();
