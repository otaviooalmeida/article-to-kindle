let capture;
const title = document.querySelector("#title");
const status = document.querySelector("#status");
const previewButton = document.querySelector("#preview");

function state(message, disabled = false) {
  status.textContent = message;
  previewButton.disabled = disabled || !capture;
}

document.querySelector("#options").addEventListener("click", () => chrome.runtime.openOptionsPage());

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

chrome.runtime.sendMessage({ type: "capture" }).then(result => {
  if (result.error || !result.capture) throw new Error(result.error || "Article content not detected.");
  capture = result.capture;
  title.textContent = capture.title;
  state("Review and edit the article before sending it.");
}).catch(error => {
  title.textContent = "No article detected";
  state(error.message, true);
});
