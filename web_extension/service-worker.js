chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "capture") return;
  chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => {
    if (!tab?.id) throw new Error("No active tab.");
    return chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
  }).then(([result]) => sendResponse({ capture: result.result }))
    .catch(error => sendResponse({ error: error.message }));
  return true;
});
