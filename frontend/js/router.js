let callback = () => {};

export function route() {
    const path = location.pathname === "/" ? "/" : location.pathname.replace(/\/+$/, "");
    return {path, params: new URLSearchParams(location.search), hash: location.hash};
}

export function safeReturn(value, fallback = "/") {
    if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//") || /[\\\r\n\t]/.test(value)) return fallback;
    let url;
    try { url = new URL(value, location.origin); } catch { return fallback; }
    if (url.origin !== location.origin || /^\/(api|internal)(?:\/|$)/.test(url.pathname)) return fallback;
    return `${url.pathname}${url.search}${url.hash}`;
}

export function go(path, {replace = false, scroll = true} = {}) {
    const destination = safeReturn(path);
    history[replace ? "replaceState" : "pushState"]({}, "", destination);
    callback({scroll});
}

export function refresh({scroll = false} = {}) {
    callback({scroll});
}

export function startRouter(render) {
    callback = render;
    window.addEventListener("popstate", () => callback({scroll: false}));
    document.addEventListener("click", event => {
        if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        const link = event.target.closest("a[data-route]");
        if (!link || link.download || link.target || link.origin !== location.origin) return;
        event.preventDefault();
        go(link.pathname + link.search + link.hash);
    });
}
