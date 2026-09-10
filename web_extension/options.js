const serverUrl = document.querySelector("#serverUrl");
const token = document.querySelector("#token");
const status = document.querySelector("#status");
document.querySelector("#origin").textContent = new URL(chrome.runtime.getURL("/")).origin;

chrome.storage.local.get({ serverUrl: "http://127.0.0.1:8765", token: "" }).then(values => {
  serverUrl.value = values.serverUrl;
  token.value = values.token;
});

document.querySelector("#save").addEventListener("click", async () => {
  const normalized = serverUrl.value.replace(/\/$/, "");
  if (normalized !== "http://127.0.0.1:8765" || !token.value) {
    status.textContent = "Use the fixed local server URL and enter a token.";
    return;
  }
  await chrome.storage.local.set({ serverUrl: normalized, token: token.value });
  status.textContent = "Saved.";
});
