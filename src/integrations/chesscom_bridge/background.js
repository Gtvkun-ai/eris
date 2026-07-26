"use strict";

const DEFAULTS = {
  endpoint: "http://127.0.0.1:8765/v1/chess/snapshot",
  token: "",
  enabled: true
};

function settings() {
  return new Promise(resolve => chrome.storage.local.get(DEFAULTS, resolve));
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "eris_chess_snapshot") return false;
  (async () => {
    const config = await settings();
    if (!config.enabled) return {ok: false, error: "disabled"};
    const headers = {"Content-Type": "application/json"};
    if (config.token) headers["X-Eris-Bridge-Token"] = config.token;
    const response = await fetch(config.endpoint || DEFAULTS.endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify(message.payload || {}),
      cache: "no-store"
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) return {ok: false, error: body.error || `HTTP ${response.status}`};
    return {ok: true, observation: body.observation || {}};
  })().then(sendResponse).catch(error => sendResponse({ok: false, error: String(error)}));
  return true;
});
