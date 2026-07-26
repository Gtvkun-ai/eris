const defaults = {
  enabled: true,
  modeOverride: "auto",
  endpoint: "http://127.0.0.1:8765/v1/chess/snapshot",
  token: ""
};
chrome.storage.local.get(defaults, values => {
  document.querySelector("#enabled").checked = values.enabled;
  document.querySelector("#mode").value = values.modeOverride;
  document.querySelector("#endpoint").value = values.endpoint;
  document.querySelector("#token").value = values.token;
});
document.querySelector("#save").addEventListener("click", () => {
  chrome.storage.local.set({
    enabled: document.querySelector("#enabled").checked,
    modeOverride: document.querySelector("#mode").value,
    endpoint: document.querySelector("#endpoint").value.trim(),
    token: document.querySelector("#token").value.trim()
  }, () => {
    const status = document.querySelector("#status");
    status.textContent = "Đã lưu.";
    setTimeout(() => status.textContent = "", 1200);
  });
});
