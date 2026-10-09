"""Detect the article with Readability, but retain the original rich HTML.

Readability's rewritten HTML is only selection evidence: it can discard tables,
math, and captions. Map its prose back to the source and use their shared parent
as the article root. Existing normalization and sanitization remain mandatory.
"""

from copy import deepcopy

from bs4 import BeautifulSoup, Tag
from readability import Document


SOURCE_ATTRIBUTE = "data-article-to-kindle-node"
MAX_ANALYSIS_ELEMENTS = 100000


def select_article_root(soup: BeautifulSoup, source_url: str) -> Tag | None:
    """Return an original source container, or None for the legacy fallback.

    No network requests are made, and the caller's document is not modified.
    This is structural article detection, not a trained semantic classifier.
    """
    source_nodes = list(soup.find_all(True))
    if len(source_nodes) > MAX_ANALYSIS_ELEMENTS:
        return None
    analysis = deepcopy(soup)
    for index, node in enumerate(analysis.find_all(True)):
        node[SOURCE_ATTRIBUTE] = str(index)
    try:
        summary = Document(str(analysis), url=source_url).summary(
            html_partial=True, keep_all_images=True,
        )
    except (ValueError, TypeError):
        return None

    retained = []
    for node in BeautifulSoup(summary, "html.parser").find_all(["p", "pre", "blockquote"]):
        node_id = node.get(SOURCE_ATTRIBUTE, "")
        if not str(node_id).isdigit() or len(node.get_text(" ", strip=True)) < 25:
            continue
        index = int(node_id)
        if index >= len(source_nodes):
            continue
        original = source_nodes[index]
        # Linked cards should not widen the article root to the whole landing page.
        if original.find_parent("a") is None:
            retained.append(original)
    if not retained:
        return None

    ancestor_sets = [{id(node), *(id(parent) for parent in node.parents)} for node in retained]
    root = retained[0].parent
    while isinstance(root, Tag):
        if all(id(root) in ancestors for ancestors in ancestor_sets):
            if root.name not in {"html", "body", "[document]"} and len(root.get_text(" ", strip=True)) >= 100:
                # The prose may be nested separately from figures, tables, or math.
                return root if root.name == "article" else root.find_parent("article") or root
            return None
        root = root.parent
    return None
