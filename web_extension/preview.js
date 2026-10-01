const params = new URLSearchParams(location.search);
const status = document.querySelector("#status");
const editor = document.querySelector("#editor");
const content = document.querySelector("#content");
const titleInput = document.querySelector("#title");
const authorInput = document.querySelector("#author");
const ignoreImagesInput = document.querySelector("#ignore-images");
const selectAllInput = document.querySelector("#select-all");
const downloadButton = document.querySelector("#download");
const sendButton = document.querySelector("#send");
let capture;
let busy = false;

function selectedBlocks() {
  return [...content.querySelectorAll(".include-block:checked")].length;
}

function updateSelection() {
  const checkboxes = [...content.querySelectorAll(".include-block")];
  const selected = checkboxes.filter(checkbox => checkbox.checked).length;
  selectAllInput.checked = checkboxes.length > 0 && selected === checkboxes.length;
  selectAllInput.indeterminate = selected > 0 && selected < checkboxes.length;
  document.querySelector("#selection-count").textContent = `${selected} of ${checkboxes.length} blocks selected`;
  downloadButton.disabled = busy || !selected || !titleInput.value.trim();
  sendButton.disabled = downloadButton.disabled;
  ArticlePreview.updateImagePreviews(content, ignoreImagesInput.checked);
  const images = [...content.querySelectorAll(".image-placeholder")]
    .filter(image => image.closest(".preview-block").querySelector(".include-block").checked).length;
  document.querySelector("#image-summary").textContent = images
    ? ignoreImagesInput.checked ? `${images} image${images === 1 ? "" : "s"} will be omitted.` : `${images} image${images === 1 ? "" : "s"} will be included.`
    : "No images in the selected content.";
}

function setStatus(message, isBusy = false) {
  busy = isBusy;
  status.textContent = message;
  editor.disabled = isBusy;
  updateSelection();
}

function extensionOrigin() {
  return new URL(chrome.runtime.getURL("/")).origin;
}

async function settings() {
  return chrome.storage.local.get({ serverUrl: "http://127.0.0.1:8765", token: "" });
}

async function call(path, payload) {
  const { serverUrl, token } = await settings();
  if (!token) throw new Error("Configure the bearer token in Settings.");
  try {
    const response = await fetch(`${serverUrl}${path}`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-Article-To-Kindle-Origin": extensionOrigin(),
      },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const failure = await response.json().catch(() => ({}));
      throw new Error(failure.message || "Local server request failed.");
    }
    return response;
  } catch (error) {
    if (error instanceof TypeError) throw new Error("Local server unavailable or not configured.");
    throw error;
  }
}

function currentCapture() {
  if (!capture) throw new Error("Article preview is not available.");
  const result = ArticlePreview.buildCapture(
    capture, content, titleInput.value, authorInput.value, ignoreImagesInput.checked,
  );
  if (!result.title) throw new Error("Enter a title for the Reading Copy.");
  if (!selectedBlocks()) throw new Error("Select at least one content block.");
  return result;
}

function filename(title) {
  return `${title.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase() || "article"}.epub`;
}

async function downloadEpub() {
  try {
    setStatus("Creating EPUB…", true);
    const response = await call("/epub", currentCapture());
    const objectUrl = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename(titleInput.value.trim());
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    const warnings = response.headers.get("X-Article-Warnings");
    setStatus(warnings ? `EPUB downloaded. ${warnings}.` : "EPUB downloaded.");
  } catch (error) {
    setStatus(error.message);
  }
}

async function sendToKindle() {
  try {
    setStatus("Submitting to Kindle…", true);
    const result = await (await call("/kindle", currentCapture())).json();
    setStatus(result.warnings?.length ? `${result.message} ${result.warnings.join("; ")}` : result.message);
  } catch (error) {
    setStatus(error.message);
  }
}

content.addEventListener("change", updateSelection);
content.addEventListener("click", event => {
  if (event.target.closest("a")) event.preventDefault();
});
selectAllInput.addEventListener("change", () => {
  content.querySelectorAll(".include-block").forEach(checkbox => checkbox.checked = selectAllInput.checked);
  updateSelection();
});
ignoreImagesInput.addEventListener("change", updateSelection);
titleInput.addEventListener("input", updateSelection);
downloadButton.addEventListener("click", downloadEpub);
sendButton.addEventListener("click", sendToKindle);
document.querySelector("#options").addEventListener("click", () => chrome.runtime.openOptionsPage());

(async () => {
  try {
    const id = params.get("id");
    if (!id) throw new Error("Article preview link is missing its capture.");
    capture = await ArticleCaptureStore.consumeCapture(id);
    if (!capture) throw new Error("Article preview expired. Reopen the extension on the article.");
    const count = ArticlePreview.renderArticle(capture, content);
    if (!count) throw new Error("No article content was available to preview.");
    titleInput.value = capture.title;
    authorInput.value = capture.author;
    document.querySelector("#source").textContent = capture.sourceUrl;
    editor.hidden = false;
    setStatus("Review the selected content, then create a Reading Copy.");
  } catch (error) {
    editor.hidden = true;
    downloadButton.disabled = true;
    sendButton.disabled = true;
    status.textContent = error.message || "Could not load the article preview.";
  }
})();
