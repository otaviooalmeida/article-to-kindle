const params = new URLSearchParams(location.search);
const status = document.querySelector("#status");
const editor = document.querySelector("#editor");
const content = document.querySelector("#content");
const titleInput = document.querySelector("#title");
const authorInput = document.querySelector("#author");
const kindleEmailInput = document.querySelector("#kindle-email");
const includeImagesInput = document.querySelector("#include-images");
const permitLinksInput = document.querySelector("#permit-links");
const selectAllInput = document.querySelector("#select-all");
const editModeButton = document.querySelector("#edit-mode");
const modeLabel = document.querySelector(".preview-label");
const readerArticle = document.querySelector(".reader-article");
const MIN_PREVIEW_TEXT_CHARS = 100;
const articleMetadata = document.querySelector(".article-metadata");
const articleTitle = document.querySelector("#article-title");
const articleAuthor = document.querySelector("#article-author");
const articleDate = document.querySelector("#article-date");
const downloadButton = document.querySelector("#download");
const sendButton = document.querySelector("#send");
let capture;
let busy = false;
let editing = false;

function selectedBlocks() {
  return [...content.querySelectorAll(".include-block:checked")].length;
}

function selectionIsTooSmall() {
  const blocks = [...content.querySelectorAll(".preview-block")];
  const selectedTextLength = blocks
    .filter(block => block.querySelector(".include-block").checked)
    .reduce((length, block) => length + block.querySelector(".editable-content").textContent.trim().length, 0);
  return blocks.length > 0 && selectedTextLength < MIN_PREVIEW_TEXT_CHARS;
}

function updateSelection() {
  const checkboxes = [...content.querySelectorAll(".include-block")];
  const selected = checkboxes.filter(checkbox => checkbox.checked).length;
  selectAllInput.checked = checkboxes.length > 0 && selected === checkboxes.length;
  selectAllInput.indeterminate = selected > 0 && selected < checkboxes.length;
  document.querySelector("#selection-count").textContent = `${selected} of ${checkboxes.length} sections included`;
  downloadButton.disabled = busy || !selected || !titleInput.value.trim();
  sendButton.disabled = downloadButton.disabled || !kindleEmailInput.checkValidity();
  const ignoreImages = !includeImagesInput.checked;
  document.body.classList.toggle("links-disabled", !permitLinksInput.checked);
  ArticlePreview.updateContentPreviews(content, ignoreImages);
  const selectedSections = [...content.querySelectorAll(".preview-block")]
    .filter(block => block.querySelector(".include-block").checked);
  const images = selectedSections.reduce((count, block) => count + block.querySelectorAll(".image-placeholder").length, 0);
  const links = selectedSections.reduce((count, block) => count + block.querySelectorAll(".editable-content a[href]").length, 0);
  document.querySelector("#image-summary").textContent = images
    ? includeImagesInput.checked ? `${images} image${images === 1 ? "" : "s"} included` : `${images} image${images === 1 ? "" : "s"} omitted`
    : "No images";
  document.querySelector("#link-summary").textContent = permitLinksInput.checked
    ? `${links} link${links === 1 ? "" : "s"} permitted`
    : `${links} link${links === 1 ? "" : "s"} removed`;
}

function setStatus(message, isBusy = false) {
  busy = isBusy;
  status.textContent = message;
  status.classList.toggle("visually-hidden", !isBusy && [
    "Previewing the Reading Copy.",
    "Edit text or choose sections to include in the Reading Copy.",
  ].includes(message));
  editor.disabled = isBusy;
  kindleEmailInput.disabled = isBusy;
  includeImagesInput.disabled = isBusy;
  permitLinksInput.disabled = isBusy;
  editModeButton.disabled = isBusy || !capture;
  updateSelection();
}

function normalizeText(value) {
  return value.trim().replace(/\s+/g, " ").toLowerCase();
}

function updateArticleHeading() {
  const title = titleInput.value.trim();
  articleTitle.textContent = title;
  const existingHeading = content.querySelector(".editable-content h1, .editable-content h2");
  const titleAlreadyInArticle = Boolean(title && existingHeading &&
    normalizeText(existingHeading.textContent) === normalizeText(title) &&
    existingHeading.closest(".preview-block").querySelector(".include-block").checked);
  articleTitle.hidden = titleAlreadyInArticle;
  articleAuthor.textContent = authorInput.value.trim();
  articleAuthor.hidden = !articleAuthor.textContent;
  articleDate.textContent = capture?.publishedDate ? `Published: ${capture.publishedDate}` : "";
  articleDate.hidden = !articleDate.textContent;
  articleMetadata.hidden = titleAlreadyInArticle && !articleAuthor.textContent && !articleDate.textContent;
}

function setEditing(isEditing) {
  editing = isEditing;
  document.body.classList.toggle("edit-mode", editing);
  document.body.classList.toggle("preview-mode", !editing);
  editor.hidden = !editing;
  content.querySelectorAll(".editable-content").forEach(section => {
    section.contentEditable = String(editing);
  });
  modeLabel.textContent = editing ? "Edit" : "Preview";
  editModeButton.textContent = editing ? "Preview" : "Edit";
  editModeButton.setAttribute("aria-pressed", String(editing));
  editModeButton.setAttribute("aria-label", editing ? "Return to preview mode" : "Enter edit mode");
  setStatus(editing ? "Edit text or choose sections to include in the Reading Copy." : "Previewing the Reading Copy.");
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
    capture, content, titleInput.value, authorInput.value, !includeImagesInput.checked, permitLinksInput.checked,
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
    if (!kindleEmailInput.checkValidity()) throw new Error("Enter a valid Kindle email address.");
    setStatus("Submitting to Kindle…", true);
    const payload = { ...currentCapture(), kindleEmail: kindleEmailInput.value.trim() };
    const result = await (await call("/kindle", payload)).json();
    setStatus(result.warnings?.length ? `${result.message} ${result.warnings.join("; ")}` : result.message);
  } catch (error) {
    setStatus(error.message);
  }
}

content.addEventListener("change", () => {
  updateArticleHeading();
  updateSelection();
});
content.addEventListener("input", updateArticleHeading);
editModeButton.addEventListener("click", () => setEditing(!editing));
content.addEventListener("click", event => {
  if (event.target.closest("a")) event.preventDefault();
});
selectAllInput.addEventListener("change", () => {
  content.querySelectorAll(".include-block").forEach(checkbox => checkbox.checked = selectAllInput.checked);
  updateArticleHeading();
  updateSelection();
});
kindleEmailInput.addEventListener("input", updateSelection);
kindleEmailInput.addEventListener("change", () => {
  chrome.storage.local.set({ kindleEmail: kindleEmailInput.value.trim() });
});
includeImagesInput.addEventListener("change", () => {
  updateSelection();
  chrome.storage.local.set({ includeImages: includeImagesInput.checked });
});
permitLinksInput.addEventListener("change", () => {
  updateSelection();
  chrome.storage.local.set({ permitLinks: permitLinksInput.checked });
});
titleInput.addEventListener("input", () => {
  updateArticleHeading();
  updateSelection();
});
authorInput.addEventListener("input", updateArticleHeading);
downloadButton.addEventListener("click", downloadEpub);
sendButton.addEventListener("click", sendToKindle);
document.querySelector("#options").addEventListener("click", () => chrome.runtime.openOptionsPage());

(async () => {
  try {
    const id = params.get("id");
    if (!id) throw new Error("Article preview link is missing its capture.");
    const [preferences, storedCapture] = await Promise.all([
      chrome.storage.local.get({ kindleEmail: "", includeImages: true, permitLinks: true }),
      ArticleCaptureStore.consumeCapture(id),
    ]);
    kindleEmailInput.value = preferences.kindleEmail || "";
    includeImagesInput.checked = preferences.includeImages !== false;
    permitLinksInput.checked = preferences.permitLinks !== false;
    capture = storedCapture;
    if (!capture) throw new Error("Article preview expired. Reopen the extension on the article.");
    const count = ArticlePreview.renderArticle(capture, content, !includeImagesInput.checked);
    if (!count) throw new Error("No article content was available to preview.");
    titleInput.value = capture.title;
    authorInput.value = capture.author;
    const smallSelection = selectionIsTooSmall();
    const originalArticleLink = document.querySelector("#original-article");
    originalArticleLink.href = capture.sourceUrl;
    originalArticleLink.hidden = false;
    updateArticleHeading();
    setEditing(false);
    let warnings = [...(capture.warnings || [])];
    if (smallSelection) {
      warnings.unshift("The model selected less than 100 characters; excluded blocks remain unchecked for review.");
    }
    if (warnings.length) {
      setStatus(`Review these analysis notes before exporting: ${warnings.join("; ")}.`);
    }
  } catch (error) {
    editor.hidden = true;
    readerArticle.hidden = true;
    editModeButton.disabled = true;
    downloadButton.disabled = true;
    sendButton.disabled = true;
    status.textContent = error.message || "Could not load the article preview.";
  }
})();
