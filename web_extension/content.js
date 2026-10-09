(() => {
  const LOCAL_HOST_SUFFIXES = [".localhost", ".local", ".internal", ".lan", ".home", ".home.arpa"];
  const NOISE = "nav,footer,aside,form,button,[role=dialog],[class*='recommend'],[id*='recommend'],[data-testid*='recommend'],[class*='paywall'],[class*='newsletter']";
  const END_MARKERS = "[class*='related'],[id*='related'],[class*='recommended'],[id*='recommended'],[class*='read-next'],[id*='read-next'],[class*='readnext'],[id*='readnext'],[class*='comment'],[id*='comment'],[class*='tag-list'],[id*='tag-list']";
  const DECORATIVE = /avatar|logo|icon|profile|author|tracking|pixel/i;

  const CONTENT_SELECTORS = [
    "article", "[itemprop='articleBody']", "[role='main']", "main",
    ".article-body", ".article-content", ".post-content", ".entry-content",
  ];

  function scoreContent(root) {
    const text = root.textContent?.trim().length || 0;
    const paragraphs = root.querySelectorAll("p").length;
    const headings = root.querySelectorAll("h1,h2,h3,h4").length;
    const noise = root.querySelectorAll("nav,footer,aside,[class*='recommend'],[class*='newsletter'],[class*='subscribe']").length;
    return text + paragraphs * 80 + headings * 40 - noise * 250;
  }

  function readabilityRoot(doc, pageUrl) {
    if (typeof Readability === "undefined") return null;
    const nodes = [...doc.querySelectorAll("*")];
    if (nodes.length > 100000) return null;
    const analysis = doc.cloneNode(true);
    const sourceAttribute = "data-article-to-kindle-node";
    [...analysis.querySelectorAll("*")].forEach((node, index) => node.setAttribute(sourceAttribute, String(index)));
    try {
      const result = new Readability(analysis, { charThreshold: 100, maxElemsToParse: 100000 }).parse();
      if (!result) return null;
      // Parse into an inert template. Never display Readability's rewritten HTML.
      const template = doc.createElement("template");
      template.innerHTML = result.content;
      const retained = [...template.content.querySelectorAll("p,pre,blockquote")]
        .filter(node => node.textContent.trim().length >= 25 && node.hasAttribute(sourceAttribute))
        .map(node => nodes[Number(node.getAttribute(sourceAttribute))])
        .filter(node => node && !node.closest("a"));
      if (!retained.length) return null;
      let root = retained[0].parentElement;
      while (root && !retained.every(node => root.contains(node))) root = root.parentElement;
      if (!root || ["HTML", "BODY"].includes(root.tagName)) return null;
      // Include rich siblings/header material belonging to an explicit article.
      return root.closest("article") || root;
    } catch {
      return null;
    }
  }

  function findArticleRoot(doc, pageUrl) {
    const detected = readabilityRoot(doc, pageUrl);
    if (detected) return detected;
    const candidates = [...new Set(CONTENT_SELECTORS.flatMap(selector => [...doc.querySelectorAll(selector)]))];
    return candidates.sort((left, right) => scoreContent(right) - scoreContent(left))[0] || null;
  }

  function trimArticleEnd(root) {
    const candidates = [...root.querySelectorAll(END_MARKERS)];
    const marker = [...root.querySelectorAll("*")].find(node => candidates.includes(node));
    if (!marker) return;
    [...marker.parentElement.children].slice([...marker.parentElement.children].indexOf(marker)).forEach(node => node.remove());
  }

  function snapshotHtml(doc) {
    const snapshot = doc.documentElement.cloneNode(true);
    snapshot.querySelectorAll('script:not([type="application/ld+json"]),style,noscript,iframe,form,input,textarea,button,svg').forEach(node => node.remove());
    const sourceImages = [...doc.querySelectorAll("img")];
    [...snapshot.querySelectorAll("img")].forEach((image, index) => {
      const source = sourceImages[index];
      if (!source) { image.remove(); return; }
      const label = `${source.alt} ${source.className}`;
      const trackingPixel = source.naturalWidth > 0 && source.naturalWidth <= 2 && source.naturalHeight > 0 && source.naturalHeight <= 2;
      if (DECORATIVE.test(label) || trackingPixel) {
        (image.closest("picture") || image).remove();
        return;
      }
      image.setAttribute("data-article-to-kindle-src", source.currentSrc || source.src || source.getAttribute("data-src") || "");
      image.removeAttribute("src");
      image.removeAttribute("srcset");
      image.removeAttribute("data-src");
      image.removeAttribute("data-srcset");
    });
    snapshot.querySelectorAll("source").forEach(source => source.remove());
    snapshot.querySelectorAll("*").forEach(node => [...node.attributes]
      .filter(attribute => /^on/i.test(attribute.name))
      .forEach(attribute => node.removeAttribute(attribute.name)));
    return snapshot.outerHTML;
  }

  function captureArticle(doc = document, pageUrl = location.href) {
    const url = new URL(pageUrl);
    const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
    const ipv4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
    const privateIpv4 = ipv4 && (() => {
      const [first, second] = ipv4.slice(1).map(Number);
      return first === 0 || first === 10 || first === 127 || first >= 224 ||
        (first === 169 && second === 254) || (first === 172 && second >= 16 && second <= 31) ||
        (first === 192 && second === 168) || (first === 100 && second >= 64 && second <= 127);
    })();
    const privateIpv6 = /^(::1|fc[0-9a-f]{2}:|fd[0-9a-f]{2}:|fe[89ab][0-9a-f]:)/i.test(host);
    if (!['http:', 'https:'].includes(url.protocol) || !host || url.username || url.password || host === "localhost" ||
        LOCAL_HOST_SUFFIXES.some(suffix => host.endsWith(suffix)) || privateIpv4 || privateIpv6) {
      throw new Error("Use a public HTTP(S) webpage; local and private-network pages are not supported.");
    }
    const root = findArticleRoot(doc, url.href) || doc.body;
    if (!root) throw new Error("Article content not detected.");

    const clone = root.cloneNode(true);
    // Resolve image sources before pruning changes clone/source node positions.
    [...clone.querySelectorAll("img")].forEach((image, index) => {
      const source = root.querySelectorAll("img")[index];
      const label = `${source.alt} ${source.className}`;
      const trackingPixel = source.naturalWidth > 0 && source.naturalWidth <= 2 && source.naturalHeight > 0 && source.naturalHeight <= 2;
      const meaningful = !DECORATIVE.test(label) && !trackingPixel;
      if (!meaningful) {
        (image.closest("picture") || image).remove();
        return;
      }
      image.setAttribute("data-article-to-kindle-src", source.currentSrc || source.src);
      image.removeAttribute("src");
      image.removeAttribute("srcset");
      image.removeAttribute("data-src");
      image.removeAttribute("data-srcset");
    });
    clone.querySelectorAll("source").forEach(source => source.remove());
    trimArticleEnd(clone);
    clone.querySelectorAll(NOISE).forEach(node => node.remove());

    const title = doc.querySelector('meta[property="og:title"]')?.content || root.querySelector("h1")?.textContent?.trim() || doc.title?.trim();
    const author = doc.querySelector('meta[name="author"],meta[property="article:author"]')?.content || "Unknown author";
    if (!title || root.textContent.trim().length < 100) throw new Error("Article content not detected.");
    return { title, author, sourceUrl: url.href, html: clone.outerHTML, pageHtml: snapshotHtml(doc) };
  }

  globalThis.captureArticle = captureArticle;
  if (typeof module !== "undefined") module.exports = { captureArticle };
  return typeof chrome !== "undefined" && chrome.runtime?.id ? captureArticle() : undefined;
})();
