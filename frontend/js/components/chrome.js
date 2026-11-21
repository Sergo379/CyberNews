import {api} from "../api.js";
import {signOut} from "../auth.js";
import {language, t} from "../i18n.js";
import {go, route} from "../router.js";
import {viewer} from "../session.js";
import {setTheme, theme} from "../theme.js";
import {button, dialog, div, el, external, field, form, guard, iconButton, link, text} from "./dom.js";
import {icon} from "./icons.js";

let unread = 0;
let badge;
let requestOwner = null;

function brand() {
    return link("/", [el("img", {src: "/favicon.svg", alt: "", width: 32, height: 32}), "CyberNews"], {class: "cluster brand"});
}

function navItem(url, label, selected) {
    return link(url, label, selected ? {"aria-current": "page"} : {});
}

function preferredTheme() {
    const themes = ["system", "light", "dark"];
    return field(t("theme"), "theme", {
        tag: "select", value: theme(), choices: themes.map(key => [key, t(key)]),
        on: {change: event => setTheme(event.currentTarget.value)},
    });
}

function localControl(changeLanguage, compact = false) {
    const other = language() === "ru" ? "en" : "ru";
    return button(compact ? other.toUpperCase() : t("language") + " · " + other.toUpperCase(),
        guard(() => changeLanguage(other)), {variant: "quiet", title: t("language"),
            "aria-label": `${t("language")} · ${other.toUpperCase()}`});
}

function searchDialog() {
    const initial = route().params.get("q") || "";
    dialog(t("search_news"), panel => form("header-search", [
        field(t("search_news"), "q", {type: "search", maxlength: 160, placeholder: t("search_placeholder"), value: initial}),
    ], t("search"), async data => {
        panel.close();
        const value = data.q.trim();
        go(value ? `/?q=${encodeURIComponent(value)}#feed` : "/#feed");
    }));
}

function choicesDialog(changeLanguage) {
    const user = viewer();
    dialog(t("menu"), panel => {
        const items = [
            ["/", t("news")], ["/#categories", t("categories")],
            ...(user ? [["/profile", t("profile")], ["/bookmarks", t("bookmarks")],
                ["/subscriptions", t("subscriptions")], ["/notifications", t("notifications")]] :
                [["/login", t("login")], ["/register", t("register")]]),
            ...(user && user.role !== "user" ? [["/admin/", t("admin")]] : []),
        ];
        return div("stack", div("mobile-links", items.map(([href, name]) => link(href, name, {
            class: "button quiet", on: {click: () => panel.close()},
        }))), preferredTheme(), div("cluster",
            localControl(value => { panel.close(); return changeLanguage(value); }),
            user ? button(t("logout"), guard(async () => { panel.close(); await signOut(); })) : null));
    }, "dialog-mobile");
}

function accountDialog() {
    dialog(t("account"), panel => div("mobile-links", [
        ["/profile", t("profile")], ["/bookmarks", t("bookmarks")], ["/subscriptions", t("subscriptions")],
    ].map(([url, label]) => link(url, label, {class: "button quiet", on: {click: () => panel.close()}})),
    button(t("logout"), guard(async () => { panel.close(); await signOut(); }), {variant: "quiet"})));
}

function renderBadge() {
    if (!badge) return;
    badge.hidden = unread === 0;
    badge.textContent = unread > 99 ? "99+" : String(unread);
    badge.parentElement.setAttribute("aria-label", unread ? `${t("notifications")} · ${unread}` : t("notifications"));
}

export async function refreshUnread() {
    const user = viewer();
    if (!user || document.hidden) return;
    const current = user.id;
    if (requestOwner === current) return;
    requestOwner = current;
    try {
        const result = await api("notifications", "/unread-count");
        if (viewer()?.id !== current) return;
        unread = result.count;
        renderBadge();
    } catch {
        // Unread metadata should not block navigation.
    } finally {
        if (requestOwner === current) requestOwner = null;
    }
}

export function clearUnread() {
    unread = 0;
    renderBadge();
}

export function mountChrome(changeLanguage) {
    const user = viewer();
    const path = route().path;
    const skip = el("a", {class: "skip", href: "#main", tabindex: 0, on: {click: event => {
        event.preventDefault();
        document.querySelector("#main").focus();
    }}}, t("skip"));
    const settings = div("settings", localControl(changeLanguage, true),
        iconButton("sun", t("theme"), () => dialog(t("theme"), preferredTheme())));
    badge = user ? el("span", {class: "notif-count", hidden: true, "aria-hidden": "true"}) : null;
    const notifications = user ? link("/notifications", [icon("bell"), badge], {class: "icon-button quiet",
        "aria-label": t("notifications"), title: t("notifications")}) : null;
    const account = user ? iconButton("user", t("account"), accountDialog, {class: "icon-button quiet account-link"})
        : link("/login", t("login"), {class: "button primary account-link"});
    const nav = el("nav", {class: "cluster header-nav", "aria-label": t("news")},
        navItem("/", t("news"), path === "/" && !route().hash),
        navItem("/#categories", t("categories"), route().hash === "#categories"),
        user ? navItem("/bookmarks", t("bookmarks"), path === "/bookmarks") : null,
        user && user.role !== "user" ? navItem("/admin/", t("admin"), path.startsWith("/admin")) : null);
    document.querySelector("#chrome").replaceChildren(skip,
        el("header", {class: "site-header"}, div("wrap header-inner",
            brand(), nav, div("cluster header-tools",
                iconButton("search", t("search_news"), searchDialog), settings,
                notifications, el("span", {class: "vertical-rule", "aria-hidden": "true"}), account,
                iconButton("menu", t("menu"), () => choicesDialog(changeLanguage), {class: "icon-button quiet mobile-menu"})))));
    renderBadge();
    document.querySelector("#footer").className = "site-footer";
    document.querySelector("#footer").replaceChildren(div("wrap cluster-wide footer-inner", brand(),
        el("nav", {class: "cluster footer-links", "aria-label": t("news")},
            link("/", t("news")), link("/#categories", t("categories")),
            external("https://github.com/Sergo379/CyberNews", "GitHub"))));
}
