let capture;
const title = document.querySelector("#title");
const status = document.querySelector("#status");
const previewButton = document.querySelector("#preview");

function state(message, disabled = false) {
  status.textContent = message;
  previewButton.disabled = disabled || !capture;
}

document.querySelector("#options").addEventListener("click", () => chrome.runtime.openOptionsPage());

async function analyzeCapture(captured) {
  if (!captured.pageHtml) return captured;
  const { serverUrl, token } = await chrome.storage.local.get({ serverUrl: "http://127.0.0.1:8765", token: "" });
  if (!token) throw new Error("Configure the local companion token in Settings before analyzing this page.");
  const payload = {
    sourceUrl: captured.sourceUrl,
    html: captured.pageHtml,
    title: captured.title,
    author: captured.author === "Unknown author" ? undefined : captured.author,
  };
  let response;
  try {
    response = await fetch(`${serverUrl}/analyze`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-Article-To-Kindle-Origin": new URL(chrome.runtime.getURL("/")).origin,
      },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    if (error instanceof TypeError) throw new Error("Local companion unavailable. Start it with article-to-kindle serve.");
    throw error;
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.message || "Local article analysis failed.");
  return result;
}

previewButton.addEventListener("click", async () => {
  try {
    state("Opening preview…", true);
    const id = await ArticleCaptureStore.saveCapture(capture);
    await chrome.tabs.create({ url: chrome.runtime.getURL(`preview.html?id=${encodeURIComponent(id)}`) });
    window.close();
  } catch (error) {
    state(error.message || "Could not open the article preview.");
  }
});

chrome.runtime.sendMessage({ type: "capture" }).then(async result => {
  if (result.error || !result.capture) throw new Error(result.error || "Article content not detected.");
  title.textContent = result.capture.title;
  state("Analyzing article…", true);
  capture = await analyzeCapture(result.capture);
  title.textContent = capture.title;
  state("Review and edit the article before sending it.");
}).catch(error => {
  title.textContent = "No article detected";
  state(error.message, true);
});
