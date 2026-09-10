let capture;
const title = document.querySelector("#title");
const status = document.querySelector("#status");
const actions = [document.querySelector("#download"), document.querySelector("#send")];

function state(message, disabled = false) {
  status.textContent = message;
  actions.forEach(button => button.disabled = disabled || !capture);
}

async function settings() {
  return chrome.storage.local.get({ serverUrl: "http://127.0.0.1:8765", token: "" });
}

async function call(path) {
  const { serverUrl, token } = await settings();
  if (!token) throw new Error("Configure the bearer token in Settings.");
  const response = await fetch(`${serverUrl}${path}`, {
    method: "POST",
    headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(capture),
  });
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    throw new Error(failure.message || "Local server request failed.");
  }
  return response;
}

async function checkServer() {
  const { serverUrl, token } = await settings();
  if (!token) throw new Error("Configure the bearer token in Settings.");
  try {
    const response = await fetch(`${serverUrl}/health`, { headers: { "Authorization": `Bearer ${token}` } });
    if (response.ok) return;
    const failure = await response.json().catch(() => ({}));
    throw new Error(failure.message || `Local server rejected the request (${response.status}).`);
  } catch (error) {
    if (error instanceof TypeError) throw new Error("Local server unavailable or not configured.");
    throw error;
  }
}

document.querySelector("#download").addEventListener("click", async () => {
  try {
    state("Creating EPUB…", true);
    const response = await call("/epub");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(await response.blob());
    link.download = `${capture.title.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase() || "article"}.epub`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    const warnings = response.headers.get("X-Article-Warnings");
    state(warnings ? `EPUB created: ${warnings}.` : "EPUB downloaded.");
  } catch (error) { state(error.message); }
});

document.querySelector("#send").addEventListener("click", async () => {
  try {
    state("Sending…", true);
    const result = await (await call("/kindle")).json();
    state(result.warnings?.length ? `${result.message} ${result.warnings.join("; ")}` : result.message);
  } catch (error) { state(error.message); }
});

document.querySelector("#options").addEventListener("click", () => chrome.runtime.openOptionsPage());

chrome.runtime.sendMessage({ type: "capture" }).then(async result => {
  if (result.error || !result.capture) throw new Error(result.error || "Article content not detected.");
  capture = result.capture;
  title.textContent = capture.title;
  await checkServer();
  state("Ready.");
}).catch(error => {
  if (!capture) title.textContent = "No article detected";
  state(error.message, true);
});
