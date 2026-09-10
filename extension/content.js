(() => {
  const SUPPORTED_HOSTS = ["medium.com", "towardsdatascience.com"];
  const NOISE = "nav,footer,aside,form,button,[role=dialog],[class*='recommend'],[id*='recommend'],[data-testid*='recommend'],[class*='paywall'],[class*='newsletter']";
  const DECORATIVE = /avatar|logo|icon|profile|author|tracking|pixel/i;

  function captureArticle(doc = document, pageUrl = location.href) {
    const url = new URL(pageUrl);
    if (!SUPPORTED_HOSTS.some(host => url.hostname === host || url.hostname.endsWith(`.${host}`))) {
      throw new Error("Unsupported article website.");
    }
    const root = doc.querySelector("article");
    if (!root) throw new Error("Article content not detected.");

    const clone = root.cloneNode(true);
    const sourceImages = [...root.querySelectorAll("img")];
    [...clone.querySelectorAll("img")].forEach((image, index) => {
      const source = sourceImages[index];
      const label = `${source.alt} ${source.className}`;
      const trackingPixel = source.naturalWidth > 0 && source.naturalWidth <= 2 && source.naturalHeight > 0 && source.naturalHeight <= 2;
      const meaningful = !DECORATIVE.test(label) && !trackingPixel;
      if (!meaningful) {
        (image.closest("picture") || image).remove();
        return;
      }
      image.src = source.currentSrc || source.src;
      image.removeAttribute("srcset");
      image.removeAttribute("data-src");
      image.removeAttribute("data-srcset");
    });
    clone.querySelectorAll("source").forEach(source => source.remove());
    clone.querySelectorAll(NOISE).forEach(node => node.remove());

    const title = doc.querySelector('meta[property="og:title"]')?.content || root.querySelector("h1")?.textContent?.trim();
    const author = doc.querySelector('meta[name="author"],meta[property="article:author"]')?.content || "Unknown author";
    if (!title || clone.textContent.trim().length < 100) throw new Error("Article content not detected.");
    return { title, author, sourceUrl: url.href, html: clone.outerHTML };
  }

  globalThis.captureArticle = captureArticle;
  if (typeof module !== "undefined") module.exports = { captureArticle };
  return typeof chrome !== "undefined" && chrome.runtime?.id ? captureArticle() : undefined;
})();
