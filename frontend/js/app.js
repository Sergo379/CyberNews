import "./theme.js";
import {accessToken, listen, viewer} from "./session.js";
import {verifyProfile} from "./auth.js";
import {go, refresh, route, startRouter} from "./router.js";
import {setLanguage, t} from "./i18n.js";
import {failed, heading, link, loading, state, toast} from "./components/dom.js";
import {clearUnread, mountChrome, refreshUnread} from "./components/chrome.js";

const main = document.querySelector("#main");
let navigation;
let languageDraft;
let activePath;
const room = {
    "/login": "login", "/register": "register", "/profile": "profile",
    "/bookmarks": "bookmarks", "/subscriptions": "subscriptions", "/notifications": "notifications",
};
const requireAccount = new Set(["/profile", "/bookmarks", "/subscriptions", "/notifications"]);
const uuidPath = /^\/article\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;

function snapshotForms() {
    return Array.from(main.querySelectorAll("[data-form]"), node => [
        node.dataset.form,
        Array.from(node.elements)
            .filter(field => field.name && !["password", "current_password", "new_password", "confirm_password", "admin_password"].includes(field.name))
            .filter(field => ["INPUT", "SELECT", "TEXTAREA"].includes(field.tagName))
            .map(field => [field.name, field.type === "checkbox" ? field.checked : field.value]),
    ]);
}

function restoreForms(snapshot) {
    for (const [key, entries] of snapshot) {
        const form = Array.from(main.querySelectorAll("[data-form]")).find(node => node.dataset.form === key);
        if (!form) continue;
        for (const [name, value] of entries) {
            const field = form.elements.namedItem(name);
            if (!field) continue;
            if (typeof value === "boolean") field.checked = value;
            else field.value = value;
        }
    }
}

async function changeLanguage(value) {
    languageDraft = snapshotForms();
    await setLanguage(value);
    return render({scroll: false});
}

function notFound() {
    return [heading(t("not_found")), state(t("not_found"), t("not_found_help"),
        link("/", t("back_feed"), {class: "button primary"}))];
}

async function render({scroll = false} = {}) {
    navigation?.abort();
    navigation = new AbortController();
    const {signal} = navigation;
    for (const panel of document.querySelectorAll("dialog[open]")) panel.close();
    mountChrome(changeLanguage);
    const location = route();
    activePath = location.path;
    if (requireAccount.has(location.path) && !viewer()) {
        go(`/login?next=${encodeURIComponent(location.path + window.location.search)}`, {replace: true});
        return;
    }
    if (scroll) {
        window.scrollTo(0, 0);
        main.focus({preventScroll: true});
    }

    const draft = languageDraft;
    languageDraft = null;
    main.className = "site-main wrap page";
    main.replaceChildren(loading());
    const article = uuidPath.exec(location.path);
    try {
        let page;
        if (location.path === "/") {
            const module = await import("./pages/catalog.js");
            if (!signal.aborted) page = await module.catalog(location, signal);
        } else if (article) {
            const module = await import("./pages/article.js");
            if (!signal.aborted) page = await module.article(article[1], signal);
        } else if (location.path === "/admin" || location.path.startsWith("/admin/")) {
            const module = await import("./admin/index.js");
            if (!signal.aborted) page = await module.adminPage(location, signal);
        } else if (room[location.path]) {
            const module = await import("./pages/account.js");
            if (!signal.aborted) page = await module.accountPage(room[location.path], location, signal);
        } else {
            page = notFound();
        }
        if (signal.aborted) return;
        main.replaceChildren(...(Array.isArray(page) ? page : [page]));
        if (draft) restoreForms(draft);
        const heading = main.querySelector("h1");
        document.title = heading ? `${heading.textContent} · CyberNews` : "CyberNews";
        if (location.hash && /^#[a-z-]+$/.test(location.hash)) {
            const mobileCategories = location.hash === "#categories" ? document.getElementById("categories-mobile") : null;
            const target = mobileCategories?.getClientRects().length ? mobileCategories : document.getElementById(location.hash.slice(1));
            target?.scrollIntoView({block: "start"});
        }
    } catch (error) {
        if (signal.aborted || error.name === "AbortError") return;
        main.replaceChildren(failed(error, () => refresh()));
    }
}

async function boot() {
    try {
        await setLanguage();
    } catch {
        main.replaceChildren("CyberNews · Unable to load interface");
        return;
    }

    if (accessToken()) {
        try { await verifyProfile(); }
        catch (error) {
            if (error.status !== 401) toast(t("error_503"), true);
        }
    }
    listen("profile", () => { mountChrome(changeLanguage); refreshUnread(); });
    listen("session", event => {
        clearUnread();
        document.querySelector("#toasts").replaceChildren();
        queueMicrotask(() => {
            if (event.detail === "logout") {
                go("/", {replace: true});
                toast(t("signed_out"));
            } else if (event.detail === "password_changed") {
                go("/login", {replace: true});
                toast(t("password_changed"));
            } else {
                if (requireAccount.has(activePath) || activePath?.startsWith("/admin")) {
                    go(`/login?next=${encodeURIComponent(location.pathname + location.search)}`, {replace: true});
                } else refresh();
                if (event.detail === "expired") toast(t("error_401"), true);
            }
        });
    });
    listen("admin", event => {
        if (event.detail === "expired" && route().path.startsWith("/admin")) {
            toast(t("admin_expired"), true);
            queueMicrotask(() => refresh());
        }
    });
    startRouter(render);
    await render();
    refreshUnread();
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshUnread(); });
    setInterval(refreshUnread, 60_000);
}

boot();
