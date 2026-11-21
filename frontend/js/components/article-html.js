import {safeUrl} from "./dom.js";

const allowed = new Set(["a", "blockquote", "br", "code", "em", "figure", "figcaption", "h2", "h3", "h4",
    "hr", "img", "li", "ol", "p", "pre", "strong", "ul"]);
const discarded = new Set(["script", "style", "template", "iframe", "object", "svg", "math", "link", "meta"]);

function appendClean(current, parent, images) {
    if (current.nodeType === Node.TEXT_NODE) {
        parent.append(document.createTextNode(current.data));
        return;
    }
    if (current.nodeType !== Node.ELEMENT_NODE || discarded.has(current.localName)) return;
    if (!allowed.has(current.localName) || current.namespaceURI !== "http://www.w3.org/1999/xhtml") {
        for (const child of current.childNodes) appendClean(child, parent, images);
        return;
    }
    const node = document.createElement(current.localName);
    if (current.localName === "a") {
        const href = safeUrl(current.getAttribute("href"));
        if (href) {
            node.href = href;
            node.target = "_blank";
            node.rel = "noopener noreferrer";
        }
    }
    if (current.localName === "img") {
        const src = safeUrl(current.getAttribute("src"));
        if (!src || !images) return;
        node.src = src;
        node.alt = current.getAttribute("alt") || "";
        node.loading = "lazy";
        node.referrerPolicy = "no-referrer";
        node.addEventListener("error", () => node.remove(), {once: true});
    }
    for (const child of current.childNodes) appendClean(child, node, images);
    parent.append(node);
}

export function articleContent(backendHtml, {images = true} = {}) {
    const clean = document.createDocumentFragment();
    const inert = new DOMParser().parseFromString(backendHtml || "", "text/html");
    for (const child of inert.body.childNodes) appendClean(child, clean, images);
    return clean;
}
