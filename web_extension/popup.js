let capture;
const openedAt = Date.now();
const title = document.querySelector("#title");
const status = document.querySelector("#status");
const previewButton = document.querySelector("#preview");
const modeFieldset = document.querySelector("#analysis-mode");

function selectedMode() {
  return document.querySelector('input[name="analysis-mode"]:checked')?.value || "standard";
}

function state(message, disabled = false) {
  status.textContent = message;
  previewButton.disabled = disabled || !capture;
  modeFieldset.disabled = disabled || !capture;
}

document.querySelector("#options").addEventListener("click", () => chrome.runtime.openOptionsPage());

modeFieldset.addEventListener("change", () => {
  chrome.storage.local.set({ analysisMode: selectedMode() });
});

previewButton.addEventListener("click", async () => {
  try {
    state("Opening article review…", true);
    capture.analysisMode = selectedMode();
    capture.analysisRequestedAt = openedAt;
    capture.estimatedTextLength = capture.pageHtml
      ? capture.pageHtml.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").length
      : 0;
    const id = await ArticleCaptureStore.saveCapture(capture);
    await chrome.tabs.create({
      url: chrome.runtime.getURL(`preview.html?id=${encodeURIComponent(id)}`),
    });
    window.close();
  } catch (error) {
    state(error.message || "Could not open the article preview.");
  }
});

(async () => {
  try {
    const [preferences, result] = await Promise.all([
      chrome.storage.local.get({ analysisMode: "standard" }),
      chrome.runtime.sendMessage({ type: "capture" }),
    ]);
    document.querySelectorAll('input[name="analysis-mode"]').forEach(option => {
      option.checked = option.value === (preferences.analysisMode === "ai" ? "ai" : "standard");
    });
    if (result.error || !result.capture) throw new Error(result.error || "Article content not detected.");
    capture = result.capture;
    title.textContent = capture.title;
    state("Choose Standard or AI-assisted extraction, then review the article.");
  } catch (error) {
    title.textContent = "No article detected";
    state(error.message || "Could not capture this article.", true);
  }
})();
