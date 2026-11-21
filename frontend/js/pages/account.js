import {api, InputError, query} from "../api.js";
import {signIn, signOut} from "../auth.js";
import {category, date, label, t} from "../i18n.js";
import {go, refresh, safeReturn} from "../router.js";
import {clearSession, setProfile, viewer} from "../session.js";
import {refreshUnread} from "../components/chrome.js";
import {button, div, el, field, form, guard, heading, link, pagination, state, text, toast} from "../components/dom.js";
import {catalogMetadata} from "./catalog.js";

const PAGE_SIZE = 20;

export function password(caption, name, min = 1, autocomplete = "current-password") {
    return field(t(caption), name, {type: "password", required: true, minlength: min, maxlength: 128,
        autocomplete, reveal: true, help: min === 12 ? t("password_length") : null});
}

function email(value = "") {
    return field(t("email"), "email", {type: "email", required: true, maxlength: 254, value, autocomplete: "email"});
}

function nickname(value = "") {
    return field(t("nickname"), "nickname", {required: true, minlength: 3, maxlength: 32, value, autocomplete: "nickname"});
}

function loginOrRegister(register, params) {
    if (viewer()) return heading(t("signed_in"));
    const next = safeReturn(params.get("next"));
    const flow = register ? "register" : "login";
    const other = register ? "login" : "register";
    const controls = [email()];
    if (register) controls.push(nickname());
    controls.push(password("password", "password", register ? 12 : 1, register ? "new-password" : "current-password"));
    if (register) controls.push(password("confirm_password", "confirm_password", 12, "new-password"));
    return div("auth-panel panel stack",
        heading(t(flow + "_title"), t(flow + "_help")),
        form(flow, controls, t(flow), async data => {
            if (register) {
                if (data.password !== data.confirm_password) throw new InputError("password_mismatch");
                await api("auth", "/register", {method: "POST", anonymous: true,
                    body: {email: data.email.trim(), nickname: data.nickname.trim(), password: data.password}});
                go(query("/login", {next}), {replace: true});
                toast(t("registered"));
                return;
            }
            await signIn(data.email.trim(), data.password);
            go(next, {replace: true});
            toast(t("signed_in"));
        }, register ? {409: "register_conflict"} : {401: "login_invalid"}),
        div("cluster", t(register ? "have_account" : "need_account"), link(query("/" + other, {next}), t(other))));
}

function accountNav(selected) {
    return el("nav", {class: "cluster profile-nav", "aria-label": t("account")},
        ["profile", "bookmarks", "subscriptions", "notifications"].map(name =>
            link("/" + name, t(name), {class: "button " + (name === selected ? "primary" : "quiet"),
                "aria-current": name === selected ? "page" : null})));
}

function profile() {
    const me = viewer();
    return div("account-layout",
        div("panel stack",
            el("h2", {}, me.nickname),
            div("cluster meta-line", label("role", me.role),
                el("span", {}, t("registered_at") + " · " + date(me.created_at)),
                me.last_login_at && el("span", {}, t("last_login") + " · " + date(me.last_login_at, true))),
            form("profile", [nickname(me.nickname), email(me.email)], t("save"), async values => {
                const updated = await api("auth", "/me", {method: "PATCH",
                    body: {email: values.email.trim(), nickname: values.nickname.trim()}});
                setProfile(updated);
                refresh();
                toast(t("profile_saved"));
            }, {409: "profile_conflict"}),
            div("cluster", button(t("logout"), guard(signOut), {variant: "quiet"}))),
        div("panel stack", el("h2", {}, t("change_password")),
            form("password", [
                password("current_password", "current_password"),
                password("new_password", "new_password", 12, "new-password"),
                password("confirm_password", "confirm_password", 12, "new-password"),
            ], t("change_password"), async values => {
                if (values.new_password !== values.confirm_password) throw new InputError("password_mismatch");
                await api("auth", "/change-password", {method: "POST", body: {
                    current_password: values.current_password, new_password: values.new_password,
                }, keepOn401: true});
                clearSession("password_changed");
            }, {400: "password_rejected", 401: "password_rejected"})));
}

function offsetFrom(params) {
    const offset = Number(params.get("offset"));
    return Number.isSafeInteger(offset) && offset > 0 ? Math.min(offset, 100000) : 0;
}

async function bookmarks(params, signal) {
    const offset = offsetFrom(params);
    const records = await api("community", query("/bookmarks", {offset, limit: PAGE_SIZE + 1}), {signal});
    const pages = pagination(offset, PAGE_SIZE, records.length > PAGE_SIZE, next => go(query("/bookmarks", {offset: next || null}), {scroll: false}));
    return div("stack", records.length ? records.slice(0, PAGE_SIZE).map(saved => div("panel bookmark-row",
        el("h2", {}, saved.available && saved.article ?
            link("/article/" + saved.article_id, saved.article.title) : t("article_missing")),
        div("cluster-wide", text(date(saved.created_at, true), "small muted"),
            button(t("remove_bookmark"), guard(async () => {
                await api("community", "/articles/" + saved.article_id + "/bookmark", {method: "DELETE"});
                if (records.length === 1 && offset) go(query("/bookmarks", {offset: Math.max(0, offset - PAGE_SIZE) || null}), {replace: true, scroll: false});
                else refresh();
                toast(t("bookmark_removed"));
            }), {variant: "quiet"}))))
        : state(t("no_bookmarks"), t("no_bookmarks_help"), link("/", t("back_feed"), {class: "button"})), pages);
}

async function subscriptions(signal) {
    const [[categories], existing] = await Promise.all([catalogMetadata(signal), api("notifications", "/subscriptions", {signal})]);
    const selected = new Set(existing.map(item => item.category));
    return div("stack", text(t("subscription_intro"), "muted"), categories.map(item => {
        let subscribed = selected.has(item.id);
        const badge = el("span", {class: "pill"});
        const control = button("", guard(async () => {
            await api("notifications", "/subscriptions/" + item.id, {method: subscribed ? "DELETE" : "PUT"});
            subscribed = !subscribed;
            update();
            toast(t("subscription_updated"));
        }));
        function update() {
            badge.textContent = t(subscribed ? "subscribed" : "not_subscribed");
            control.textContent = t(subscribed ? "unsubscribe" : "subscribe");
            control.setAttribute("aria-label", control.textContent + " · " + category(item.id));
        }
        update();
        return div("panel subscription-row",
            div("cluster-wide", el("h2", {}, category(item.id)), badge),
            text(t("category_desc_" + item.id), "muted"), div("cluster", control));
    }));
}

async function notifications(params, signal) {
    const offset = offsetFrom(params);
    const unread = params.get("unread") === "true";
    const address = next => query("/notifications", {unread: unread ? "true" : null, offset: next || null});
    const result = await api("notifications", query("/", {unread, offset, limit: PAGE_SIZE}), {signal});
    const filter = field(t("filter"), "unread", {tag: "select", value: String(unread),
        choices: [["false", t("all_statuses")], ["true", t("unread_filter")]]});
    filter.addEventListener("change", event => go(query("/notifications", {
        unread: event.target.value === "true" ? "true" : null,
    }), {scroll: false}));

    function reload() {
        refreshUnread();
        if (unread && offset && result.items.length === 1) go(address(Math.max(0, offset - PAGE_SIZE)), {replace: true, scroll: false});
        else refresh();
    }
    async function mark(item) {
        if (!item.read) await api("notifications", "/" + item.id + "/read", {method: "PATCH"});
    }
    return div("stack", div("cluster admin-tools", filter,
        button(t("mark_all_read"), guard(async () => {
            await api("notifications", "/read-all", {method: "POST"});
            refreshUnread();
            if (unread && offset) go(address(0), {replace: true, scroll: false});
            else refresh();
            toast(t("notifications_read"));
        }))),
    result.items.length ? result.items.map(item => {
        const available = item.available && item.article_id && item.title;
        return div("panel notification-row" + (item.read ? "" : " unread"),
            div("cluster-wide", el("h2", {}, available ? item.title : t("article_missing")),
                el("span", {class: "pill"}, t(item.read ? "read" : "unread"))),
            div("cluster meta-line", available && el("span", {}, category(item.category)),
                el("time", {datetime: item.created_at}, date(item.created_at, true))),
            div("cluster", available && button(t("open_story"), guard(async () => {
                await mark(item);
                refreshUnread();
                go("/article/" + item.article_id);
            })), !item.read && button(t("mark_read"), guard(async () => { await mark(item); reload(); }), {variant: "quiet"})));
    }) : state(t(unread ? "no_unread" : "no_notifications"), unread ? null : t("no_notifications_help")),
    pagination(offset, PAGE_SIZE, offset + PAGE_SIZE < result.total, next => go(address(next), {scroll: false})));
}

export async function accountPage(name, location, signal) {
    if (name === "register" || name === "login") return loginOrRegister(name === "register", location.params);
    const body = await ({
        profile, bookmarks: () => bookmarks(location.params, signal), subscriptions: () => subscriptions(signal),
        notifications: () => notifications(location.params, signal),
    })[name]();
    return div("stack reading", heading(t(name)), accountNav(name), body);
}
