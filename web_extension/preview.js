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
const articleMetadata = document.querySelector(".article-metadata");
const articleTitle = document.querySelector("#article-title");
const articleAuthor = document.querySelector("#article-author");
const articleDate = document.querySelector("#article-date");
const downloadButton = document.querySelector("#download");
const sendButton = document.querySelector("#send");
const analysisStatus = document.querySelector("#analysis-status");
const analysisProgress = document.querySelector("#analysis-progress");
const analysisWarning = document.querySelector("#analysis-warning");
const analysisModeLabel = document.querySelector("#analysis-mode-label");
const compareButton = document.querySelector("#compare-analysis");
const useStandardButton = document.querySelector("#use-standard");
const excludedContent = document.querySelector("#excluded-content");
const excludedCount = document.querySelector("#excluded-count");
const excludedList = document.querySelector("#excluded-list");
let capture;
let rawCapture;
let busy = false;
let editing = false;
let requestedMode = "standard";
let activeJobId = null;
let runGeneration = 0;

function updateExcludedContent() {
  const blocks = [...content.querySelectorAll(".preview-block")];
  const excluded = blocks.filter(block => !block.querySelector(".include-block").checked);
  excludedList.replaceChildren();
  excludedCount.textContent = excluded.length ? `(${excluded.length})` : "(none)";
  excludedContent.hidden = excluded.length === 0;
  excluded.forEach(block => {
    const item = document.createElement("li");
    const excerpt = document.createElement("span");
    const text = block.querySelector(".editable-content").textContent.trim().replace(/\s+/g, " ");
    excerpt.textContent = text.length > 180 ? `${text.slice(0, 177)}…` : text || "Image or other article element";
    const restore = document.createElement("button");
    restore.type = "button";
    restore.textContent = "Restore";
    restore.setAttribute("aria-label", `Restore excluded section ${blocks.indexOf(block) + 1}`);
    restore.addEventListener("click", () => {
      block.querySelector(".include-block").checked = true;
      updateArticleHeading();
      updateSelection();
      setStatus("Restored the section to its original position in the Reading Copy.");
    });
    item.append(excerpt, restore);
    excludedList.append(item);
  });
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
  updateExcludedContent();
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

function setAnalysisProgress(message, { busy: isBusy = true, warning = "" } = {}) {
  analysisStatus.hidden = !message && !warning;
  analysisProgress.textContent = message;
  analysisWarning.textContent = warning;
  analysisWarning.hidden = !warning;
  useStandardButton.hidden = !isBusy || requestedMode !== "ai";
  compareButton.disabled = isBusy;
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

async function call(path, payload, method = "POST") {
  const { serverUrl, token } = await chrome.storage.local.get({ serverUrl: "http://127.0.0.1:8765", token: "" });
  if (!token) throw new Error("Configure the bearer token in Settings.");
  try {
    const response = await fetch(`${serverUrl}${path}`, {
      method,
      cache: method === "GET" ? "no-store" : "default",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-Article-To-Kindle-Origin": new URL(chrome.runtime.getURL("/")).origin,
      },
      ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
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
  if (!content.querySelector(".include-block:checked")) throw new Error("Select at least one content block.");
  return result;
}

function renderAnalysis(result, mode, clickStartedAt) {
  capture = { ...rawCapture, ...result, requestedMode: mode };
  const count = ArticlePreview.renderArticle(capture, content, !includeImagesInput.checked);
  if (!count) throw new Error("No article content was available to preview.");
  titleInput.value = capture.title;
  authorInput.value = capture.author;
  updateArticleHeading();
  setEditing(false);
  const elapsed = Math.max(0, Date.now() - clickStartedAt);
  const resultMode = capture.analysisMode || mode;
  const label = resultMode === "ai" ? "AI analysis" : "Standard extraction";
  const timing = capture.analysisTimeMs ? `${(capture.analysisTimeMs / 1000).toFixed(1)}s analysis` : "";
  const clickTiming = `${(elapsed / 1000).toFixed(1)}s click-to-ready`;
  analysisModeLabel.textContent = `${label}${timing ? ` · ${timing}` : ""} · ${clickTiming}`;
  analysisModeLabel.hidden = false;
  const comparisonMode = mode === "ai" ? "standard" : "ai";
  compareButton.textContent = `Compare with ${comparisonMode === "ai" ? "AI" : "standard"}`;
  compareButton.hidden = !rawCapture.pageHtml;
  compareButton.disabled = false;
  const warnings = [...(capture.warnings || [])];
  if (capture.fallbackReason) {
    setAnalysisProgress(`AI analysis failed. Standard extraction is shown instead. ${capture.fallbackReason}`, {
      busy: false,
      warning: "This preview is labeled as standard extraction. Compare again with AI or edit and restore sections before exporting.",
    });
  } else if (warnings.length) {
    setAnalysisProgress("Review the analysis notes before exporting.", { busy: false, warning: warnings.join("; ") });
  } else {
    setAnalysisProgress(`${label} complete.`, { busy: false });
  }
  setStatus("Previewing the Reading Copy.");
}

function formatJobPayload(mode) {
  return {
    sourceUrl: rawCapture.sourceUrl,
    html: rawCapture.pageHtml,
    title: rawCapture.title,
    author: rawCapture.author === "Unknown author" ? undefined : rawCapture.author,
    mode,
  };
}

function delay(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

async function runAnalysis(mode) {
  const generation = ++runGeneration;
  requestedMode = mode;
  activeJobId = null;
  const clickStartedAt = rawCapture.analysisRequestedAt || Date.now();
  const longArticle = (rawCapture.estimatedTextLength || rawCapture.pageHtml?.length || 0) > 100000;
  const warning = mode === "ai" && longArticle
    ? "This article is long and may take a while to process using AI. You can use standard extraction if you're in a hurry."
    : "";
  setAnalysisProgress(mode === "ai" ? "Preparing AI analysis…" : "Preparing standard extraction…", { warning });
  setStatus(mode === "ai" ? "AI analysis is running…" : "Selecting the article…", true);

  if (!rawCapture.pageHtml) {
    if (mode === "ai") {
      renderAnalysis({
        ...rawCapture,
        analysisMode: "standard",
        fallbackReason: "The original page snapshot is unavailable; AI analysis could not run.",
        warnings: ["AI analysis unavailable; the existing standard capture is shown."],
      }, mode, clickStartedAt);
      return;
    }
    renderAnalysis({ ...rawCapture, analysisMode: "standard" }, mode, clickStartedAt);
    return;
  }

  let longWaitTimer;
  try {
    const created = await (await call("/analysis-jobs", formatJobPayload(mode))).json();
    if (generation !== runGeneration) {
      call(`/analysis-jobs/${encodeURIComponent(created.jobId)}`, undefined, "DELETE").catch(() => {});
      return;
    }
    activeJobId = created.jobId;
    if (mode === "ai") {
      longWaitTimer = setTimeout(() => {
        if (generation === runGeneration) {
          setAnalysisProgress("AI analysis is taking longer than usual. Keep waiting or switch to standard extraction.", { warning });
        }
      }, Math.max(0, 15000 - (Date.now() - clickStartedAt)));
    }

    while (generation === runGeneration) {
      const job = await (await call(`/analysis-jobs/${encodeURIComponent(activeJobId)}`, undefined, "GET")).json();
      if (generation !== runGeneration) return;
      if (job.status === "completed" && job.result) {
        renderAnalysis(job.result, mode, clickStartedAt);
        return;
      }
      if (job.status === "failed") throw new Error(job.error || "Article analysis failed.");
      if (job.status === "cancelled") return;
      const progress = job.progress?.message || (mode === "ai" ? "AI analysis is running…" : "Selecting article content…");
      setAnalysisProgress(progress, { warning });
      await delay(450);
    }
  } catch (error) {
    if (generation !== runGeneration) return;
    setAnalysisProgress("Article analysis could not be completed.", {
      busy: false,
      warning: error.message || "Check the local companion and try again.",
    });
    setStatus(error.message || "Article analysis failed.");
  } finally {
    clearTimeout(longWaitTimer);
    if (generation === runGeneration) activeJobId = null;
  }
}

async function useStandardExtraction() {
  const oldJobId = activeJobId;
  runGeneration += 1;
  activeJobId = null;
  if (oldJobId) {
    call(`/analysis-jobs/${encodeURIComponent(oldJobId)}`, undefined, "DELETE").catch(() => {});
  }
  rawCapture.analysisRequestedAt = Date.now();
  await runAnalysis("standard");
}

async function compareAnalysis() {
  const mode = requestedMode === "ai" ? "standard" : "ai";
  try {
    compareButton.disabled = true;
    const id = await ArticleCaptureStore.saveCapture({
      ...rawCapture,
      analysisMode: mode,
      analysisRequestedAt: Date.now(),
    });
    await chrome.tabs.create({ url: chrome.runtime.getURL(`preview.html?id=${encodeURIComponent(id)}`) });
  } catch (error) {
    setAnalysisProgress("Could not open the comparison preview.", { busy: false, warning: error.message });
  } finally {
    compareButton.disabled = false;
  }
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
useStandardButton.addEventListener("click", useStandardExtraction);
compareButton.addEventListener("click", compareAnalysis);
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
    rawCapture = storedCapture;
    if (!rawCapture) throw new Error("Article preview expired. Reopen the extension on the article.");
    requestedMode = rawCapture.analysisMode === "ai" ? "ai" : "standard";
    const originalArticleLink = document.querySelector("#original-article");
    originalArticleLink.href = rawCapture.sourceUrl;
    originalArticleLink.hidden = false;
    await runAnalysis(requestedMode);
  } catch (error) {
    editor.hidden = true;
    readerArticle.hidden = true;
    editModeButton.disabled = true;
    downloadButton.disabled = true;
    sendButton.disabled = true;
    status.textContent = error.message || "Could not load the article preview.";
  }
})();
