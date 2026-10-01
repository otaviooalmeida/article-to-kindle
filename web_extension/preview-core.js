(() => {
  const ALLOWED_TAGS = new Set([
    "a", "b", "blockquote", "br", "code", "em", "figcaption", "figure", "h1",
    "h2", "h3", "h4", "hr", "i", "img", "li", "ol", "p", "pre", "strong",
    "table", "tbody", "td", "th", "thead", "tr", "ul", "math", "mrow", "mi",
    "mn", "mo", "mfrac", "msqrt", "msup", "msub", "msubsup", "mtext", "mstyle",
    "semantics", "annotation", "menclose", "merror", "mfenced", "mmultiscripts",
    "mover", "mpadded", "mphantom", "mprescripts", "mroot", "mspace", "mtable",
    "mtd", "mtr", "munder", "munderover", "none",
  ]);
  const DROP_TAGS = new Set([
    "button", "embed", "form", "iframe", "input", "noscript", "object", "script",
    "style", "svg", "textarea", "param",
  ]);
  const IMAGE_TYPES = "gif|jpe?g|png|svg\\+xml|webp";
  const BLOCK_TAGS = new Set(["blockquote", "figure", "h1", "h2", "h3", "h4", "hr", "ol", "p", "pre", "table", "ul"]);
  const MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML";

  function safeWebUrl(value, baseUrl) {
    if (typeof value !== "string" || !value.trim()) return "";
    try {
      const url = new URL(value, baseUrl);
      return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
    } catch {
      return "";
    }
  }

  function safeImageUrl(value, baseUrl) {
    const source = String(value || "").trim();
    const dataImage = new RegExp(`^data:image/(?:${IMAGE_TYPES})(?:;[^,]*)?,`, "i");
    return dataImage.test(source) ? source : safeWebUrl(source, baseUrl);
  }

  function removeAttribute(tag, name) {
    const pattern = new RegExp(`\\s${name}\\s*=\\s*(?:"[^"]*"|'[^']*'|[^\\s>]+)`, "i");
    return tag.replace(pattern, "");
  }

  function inertResourceHtml(html) {
    const withoutActiveMarkup = html
      .replace(/<(script|style|svg)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, "")
      .replace(/<(?:script|style|svg|meta|base)\b[^>]*\/?\s*>/gi, "");
    return withoutActiveMarkup.replace(/<[a-z][^>]*>/gi, tag => {
      const name = /^<([a-z]+)/i.exec(tag)?.[1].toLowerCase();
      tag = removeAttribute(tag, "style");
      if (name === "img") {
        const hasStoredSource = /\sdata-article-to-kindle-src\s*=/i.test(tag);
        if (!hasStoredSource) {
          const source = /\ssrc(\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))/i.exec(tag);
          if (source) tag = tag.replace(source[0], ` data-article-to-kindle-src${source[1]}`);
        } else {
          tag = removeAttribute(tag, "src");
        }
      } else {
        tag = removeAttribute(tag, "src");
      }
      for (const attribute of ["srcset", "data-src", "data-srcset", "poster", "srcdoc", "background", "data", "action", "formaction"]) {
        tag = removeAttribute(tag, attribute);
      }
      if (name === "link") tag = removeAttribute(tag, "href");
      return tag;
    });
  }

  function appendSafeNode(source, target, baseUrl) {
    if (source.nodeType === Node.TEXT_NODE) {
      target.append(document.createTextNode(source.nodeValue));
      return;
    }
    if (source.nodeType !== Node.ELEMENT_NODE) return;

    const tag = source.localName.toLowerCase();
    if (DROP_TAGS.has(tag)) return;
    if (tag === "img") {
      const src = safeImageUrl(source.getAttribute("data-article-to-kindle-src") || source.getAttribute("src"), baseUrl);
      if (!src) return;
      const placeholder = document.createElement("span");
      placeholder.className = "image-placeholder";
      placeholder.contentEditable = "false";
      placeholder.dataset.imageSource = src;
      placeholder.dataset.imageAlt = source.getAttribute("alt") || "";
      placeholder.setAttribute("role", "img");
      placeholder.setAttribute("aria-label", placeholder.dataset.imageAlt || "Article image");
      const description = document.createElement("span");
      description.className = "image-description";
      description.textContent = placeholder.dataset.imageAlt || "Article image";
      const state = document.createElement("span");
      state.className = "image-state";
      placeholder.append(description, state);
      target.append(placeholder);
      return;
    }
    if (!ALLOWED_TAGS.has(tag)) {
      source.childNodes.forEach(child => appendSafeNode(child, target, baseUrl));
      return;
    }

    const namespace = source.namespaceURI === MATHML_NAMESPACE ? MATHML_NAMESPACE : "http://www.w3.org/1999/xhtml";
    const element = document.createElementNS(namespace, tag);
    if (tag === "a") {
      const href = safeWebUrl(source.getAttribute("href"), baseUrl);
      if (href) element.setAttribute("href", href);
    } else if (tag === "math") {
      element.setAttribute("xmlns", MATHML_NAMESPACE);
      if (["inline", "block"].includes(source.getAttribute("display"))) {
        element.setAttribute("display", source.getAttribute("display"));
      }
    }
    source.childNodes.forEach(child => appendSafeNode(child, element, baseUrl));
    target.append(element);
  }

  function collectContentBlocks(root) {
    const blocks = [];
    let inlineContent = [];
    const flushInline = () => {
      if (inlineContent.length) blocks.push(inlineContent);
      inlineContent = [];
    };
    const visit = node => {
      if (node.nodeType === Node.TEXT_NODE) {
        if (node.nodeValue.trim()) inlineContent.push(node);
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const tag = node.localName.toLowerCase();
      if (DROP_TAGS.has(tag)) return;
      if (BLOCK_TAGS.has(tag) || (tag === "math" && node.getAttribute("display") === "block")) {
        flushInline();
        blocks.push([node]);
        return;
      }
      if (!ALLOWED_TAGS.has(tag)) {
        node.childNodes.forEach(visit);
        return;
      }
      inlineContent.push(node);
    };
    root.childNodes.forEach(visit);
    flushInline();
    return blocks;
  }

  function renderArticle(capture, container) {
    const parsed = new DOMParser().parseFromString(inertResourceHtml(capture.html), "text/html");
    const root = parsed.body.firstElementChild || parsed.body;
    const sourceBlocks = collectContentBlocks(root);
    container.replaceChildren();

    sourceBlocks.forEach((sources, index) => {
      const block = document.createElement("section");
      block.className = "preview-block";
      block.dataset.included = "true";

      const label = document.createElement("label");
      label.className = "block-toggle";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "include-block";
      checkbox.checked = true;
      checkbox.setAttribute("aria-label", `Include section ${index + 1} in the Reading Copy`);
      const labelText = document.createElement("span");
      labelText.className = "visually-hidden";
      labelText.textContent = `Include section ${index + 1}`;
      label.append(checkbox, labelText);

      const content = document.createElement("div");
      content.className = "editable-content";
      content.contentEditable = "true";
      content.setAttribute("aria-label", `Editable article content, section ${index + 1}`);
      sources.forEach(source => appendSafeNode(source, content, capture.sourceUrl));

      block.append(label, content);
      container.append(block);
    });
    updateContentPreviews(container, false);
    return sourceBlocks.length;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
  }

  function serializeNode(node, baseUrl, ignoreImages) {
    if (node.nodeType === Node.TEXT_NODE) return escapeHtml(node.nodeValue);
    if (node.nodeType !== Node.ELEMENT_NODE) return "";

    const tag = node.localName.toLowerCase();
    if (tag === "span" && node.classList.contains("image-placeholder")) {
      if (ignoreImages) return "";
      const src = safeImageUrl(node.dataset.imageSource, baseUrl);
      if (!src) return "";
      return `<img src="${escapeHtml(src)}" alt="${escapeHtml(node.dataset.imageAlt || "")}">`;
    }
    if (DROP_TAGS.has(tag)) return "";
    if (tag === "img") {
      if (ignoreImages) return "";
      const src = safeImageUrl(node.getAttribute("src"), baseUrl);
      return src ? `<img src="${escapeHtml(src)}" alt="${escapeHtml(node.getAttribute("alt") || "")}">` : "";
    }

    const children = [...node.childNodes].map(child => serializeNode(child, baseUrl, ignoreImages)).join("");
    if (!ALLOWED_TAGS.has(tag)) return children;

    let attributes = "";
    if (tag === "a") {
      const href = safeWebUrl(node.getAttribute("href"), baseUrl);
      if (href) attributes += ` href="${escapeHtml(href)}"`;
    } else if (tag === "math") {
      attributes += ` xmlns="${MATHML_NAMESPACE}"`;
      if (["inline", "block"].includes(node.getAttribute("display"))) {
        attributes += ` display="${node.getAttribute("display")}"`;
      }
    }
    if (["br", "hr"].includes(tag)) return `<${tag}${attributes}>`;
    return `<${tag}${attributes}>${children}</${tag}>`;
  }

  function buildCapture(capture, container, title, author, ignoreImages) {
    const blocks = [...container.querySelectorAll(".preview-block")];
    const html = blocks
      .filter(block => block.querySelector(".include-block").checked)
      .map(block => [...block.querySelector(".editable-content").childNodes]
        .map(node => serializeNode(node, capture.sourceUrl, ignoreImages)).join(""))
      .join("");
    return {
      title: title.trim(),
      author: author.trim() || "Unknown author",
      sourceUrl: capture.sourceUrl,
      html: `<article>${html}</article>`,
    };
  }

  function updateContentPreviews(container, ignoreImages) {
    container.querySelectorAll(".preview-block").forEach(block => {
      block.dataset.included = String(block.querySelector(".include-block").checked);
    });
    container.querySelectorAll(".image-placeholder").forEach(image => {
      const block = image.closest(".preview-block");
      const included = block?.querySelector(".include-block").checked;
      const state = image.querySelector(".image-state");
      state.textContent = !included ? "Omitted with this section" : ignoreImages ? "Will be omitted" : "Will be included (thumbnail not loaded)";
      image.classList.toggle("image-ignored", ignoreImages || !included);
    });
  }

  globalThis.ArticlePreview = { buildCapture, renderArticle, updateContentPreviews };
})();
