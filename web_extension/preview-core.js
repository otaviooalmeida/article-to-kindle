(() => {
  const ALLOWED_TAGS = new Set([
    "a", "b", "blockquote", "br", "code", "em", "figcaption", "figure", "h1",
    "h2", "h3", "h4", "hr", "i", "img", "li", "ol", "p", "pre", "strong",
    "table", "tbody", "td", "th", "thead", "tr", "ul", "math", "mrow", "mi",
    "mn", "mo", "mfrac", "msqrt", "msup", "msub", "msubsup", "mtext", "mstyle",
    "semantics", "annotation", "annotation-xml", "maction", "maligngroup", "malignmark",
    "menclose", "merror", "mfenced", "mglyph", "mlabeledtr", "mlongdiv", "mmultiscripts",
    "mover", "mpadded", "mphantom", "mprescripts", "mroot", "mspace", "ms", "msgroup",
    "msline", "msqrt", "msrow", "mstack", "mtable", "mtd", "mtr", "munder",
    "munderover", "none",
  ]);
  const DROP_TAGS = new Set([
    "button", "embed", "form", "iframe", "input", "noscript", "object", "script",
    "style", "svg", "textarea", "param",
  ]);
  const IMAGE_TYPES = "gif|jpe?g|png|svg\\+xml|webp";
  const BLOCK_TAGS = new Set(["blockquote", "figure", "h1", "h2", "h3", "h4", "hr", "ol", "p", "pre", "table", "ul"]);
  const MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML";
  const MATHML_ATTRIBUTES = new Set([
    "accent", "accentunder", "align", "alttext", "bevelled", "charalign", "close",
    "columnalign", "columnlines", "columnspacing", "columnspan", "denomalign", "depth",
    "dir", "display", "displaystyle", "encoding", "equalcolumns", "equalrows", "fence",
    "form", "frame", "framespacing", "groupalign", "height", "indentalign", "indentshift",
    "infixlinebreakstyle", "largeop", "length", "linebreak", "linethickness", "location",
    "longdivstyle", "lspace", "mathbackground", "mathcolor", "mathsize", "mathvariant",
    "maxsize", "minlabelspacing", "minsize", "movablelimits", "notation", "numalign", "open",
    "overflow", "position", "rowalign", "rowlines", "rowspacing", "rowspan", "rspace",
    "scriptlevel", "selection", "separator", "separators", "side", "stackalign", "stretchy",
    "subscriptshift", "superscriptshift", "symmetric", "voffset", "width", "xmlns", "xml:lang",
  ]);

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

  function isMathRenderer(source) {
    if (source.localName.toLowerCase() === "mjx-container") return true;
    return [...source.classList].some(name => /^(?:katex(?:-|$)|mathjax(?:[_-]|$)|mjx-)/i.test(name));
  }

  function isDisplayMathRenderer(source, math) {
    return source.getAttribute("display") === "true" ||
      math.getAttribute("display") === "block" ||
      [...source.classList].some(name => /(?:^|[-_])display(?:$|[-_])/i.test(name));
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
      const thumbnail = document.createElement("img");
      thumbnail.className = "image-thumbnail";
      thumbnail.dataset.previewSource = src;
      thumbnail.alt = placeholder.dataset.imageAlt || "Article image";
      thumbnail.loading = "lazy";
      thumbnail.decoding = "async";
      thumbnail.referrerPolicy = "no-referrer";
      const state = document.createElement("span");
      state.className = "image-state";
      thumbnail.addEventListener("error", () => {
        placeholder.classList.add("image-unavailable");
        state.textContent = "Image preview unavailable";
      });
      placeholder.append(thumbnail, state);
      target.append(placeholder);
      return;
    }
    if (tag !== "math" && isMathRenderer(source)) {
      const semanticMath = source.querySelector("math");
      if (semanticMath) {
        appendSafeNode(semanticMath, target, baseUrl);
        return;
      }
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
    } else if (source.namespaceURI === MATHML_NAMESPACE) {
      for (const attribute of source.attributes) {
        if (MATHML_ATTRIBUTES.has(attribute.name.toLowerCase())) {
          element.setAttribute(attribute.name, attribute.value);
        }
      }
      if (tag === "math" && !element.hasAttribute("xmlns")) {
        element.setAttribute("xmlns", MATHML_NAMESPACE);
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
      if (isMathRenderer(node)) {
        const math = node.querySelector("math");
        if (math) {
          if (isDisplayMathRenderer(node, math)) {
            flushInline();
            blocks.push([node]);
          } else {
            inlineContent.push(node);
          }
          return;
        }
      }
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

  function renderArticle(capture, container, ignoreImages = false) {
    const parsed = new DOMParser().parseFromString(inertResourceHtml(capture.html), "text/html");
    const root = parsed.body.firstElementChild || parsed.body;
    const sourceBlocks = collectContentBlocks(root);
    container.replaceChildren();

    sourceBlocks.forEach((sources, index) => {
      const block = document.createElement("section");
      block.className = "preview-block";

      const label = document.createElement("label");
      label.className = "block-toggle";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "include-block";
      checkbox.checked = !sources.some(source => source.getAttribute("data-article-to-kindle-excluded") === "true");
      block.dataset.included = String(checkbox.checked);
      checkbox.setAttribute("aria-label", `Include section ${index + 1} in the Reading Copy`);
      const labelText = document.createElement("span");
      labelText.className = "visually-hidden";
      labelText.textContent = `Include section ${index + 1}`;
      label.append(checkbox, labelText);

      const content = document.createElement("div");
      content.className = "editable-content";
      content.contentEditable = "false";
      content.setAttribute("aria-label", `Editable article content, section ${index + 1}`);
      sources.forEach(source => appendSafeNode(source, content, capture.sourceUrl));

      block.append(label, content);
      container.append(block);
    });
    updateContentPreviews(container, ignoreImages);
    return sourceBlocks.length;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
  }

  function serializeNode(node, baseUrl, ignoreImages, permitLinks) {
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

    const children = [...node.childNodes].map(child => serializeNode(child, baseUrl, ignoreImages, permitLinks)).join("");
    if (!ALLOWED_TAGS.has(tag) || (tag === "a" && !permitLinks)) return children;

    let attributes = "";
    if (tag === "a") {
      const href = safeWebUrl(node.getAttribute("href"), baseUrl);
      if (href) attributes += ` href="${escapeHtml(href)}"`;
    } else if (node.namespaceURI === MATHML_NAMESPACE) {
      for (const attribute of node.attributes) {
        if (MATHML_ATTRIBUTES.has(attribute.name.toLowerCase())) {
          attributes += ` ${attribute.name}="${escapeHtml(attribute.value)}"`;
        }
      }
      if (tag === "math" && !node.hasAttribute("xmlns")) {
        attributes += ` xmlns="${MATHML_NAMESPACE}"`;
      }
    }
    if (["br", "hr"].includes(tag)) return `<${tag}${attributes}>`;
    return `<${tag}${attributes}>${children}</${tag}>`;
  }

  function buildCapture(capture, container, title, author, ignoreImages, permitLinks = true) {
    const blocks = [...container.querySelectorAll(".preview-block")];
    const html = blocks
      .filter(block => block.querySelector(".include-block").checked)
      .map(block => [...block.querySelector(".editable-content").childNodes]
        .map(node => serializeNode(node, capture.sourceUrl, ignoreImages, permitLinks)).join(""))
      .join("");
    return {
      title: title.trim(),
      author: author.trim() || "Unknown author",
      sourceUrl: capture.sourceUrl,
      publishedDate: capture.publishedDate || null,
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
      const thumbnail = image.querySelector(".image-thumbnail");
      if (included && !ignoreImages && !thumbnail.hasAttribute("src")) {
        thumbnail.src = thumbnail.dataset.previewSource;
      }
      if (!image.classList.contains("image-unavailable")) {
        state.textContent = !included ? "Omitted with this section" : ignoreImages ? "Will be omitted" : "Will be included";
      }
      image.classList.toggle("image-ignored", ignoreImages || !included);
    });
  }

  globalThis.ArticlePreview = { buildCapture, renderArticle, updateContentPreviews };
})();
