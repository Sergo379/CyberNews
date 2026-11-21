import {api, query} from "../api.js";
import {lock, unlock} from "../auth.js";
import {date, label, number, t} from "../i18n.js";
import {refresh} from "../router.js";
import {adminSession, clearAdmin, viewer} from "../session.js";
import {password} from "../pages/account.js";
import {button, dialog, div, el, form, guard, heading, link, state, text, toast} from "../components/dom.js";
import {icon} from "../components/icons.js";
import {adminApi, auditTable, badge, empty, eventName, listState, searchable, selectFilter, stamp, table} from "./shared.js";

const sections = [
    ["overview", "", "layers"], ["reports", "reports", "flag"], ["comments", "comments", "comments"],
    ["restrictions", "restrictions", "shield"], ["audit", "audit", "audit"], ["users", "users", "user", true],
    ["news", "articles", "article", true], ["rss", "sources", "rss", true],
];
const journals = [
    ["moderation", "audit_moderation"], ["auth", "audit_auth"], ["articles", "audit_article"], ["collector", "audit_collector"],
];

function gate(me) {
    if (!me) return div("narrow stack", heading(t("admin")), state(t("sign_in_required"), t("admin_required_help"),
        link(query("/login", {next: location.pathname}), t("login"), {class: "button primary"})));
    if (!["moderator", "super_admin"].includes(me.role)) {
        return div("narrow stack", heading(t("admin")), state(t("admin_required"), t("admin_required_help"),
            link("/", t("public_site"), {class: "button"})));
    }
    const setup = () => dialog(t("setup_admin"), panel => div("stack", text(t("setup_admin_help")),
        form("admin-password", [password("current_password", "current_password"),
            password("admin_password", "admin_password", 12, "new-password")], t("save"), async values => {
            await api("auth", "/admin/password", {method: "PUT", body: values, keepOn401: true});
            clearAdmin();
            panel.close();
            toast(t("admin_password_set"));
        }, {400: "password_rejected", 401: "password_rejected"})));
    return div("narrow stack", heading(t("admin")),
        div("panel stack", el("h2", {}, t("admin_unlock")), text(t("admin_unlock_help")),
            form("admin-unlock", [password("admin_password", "admin_password")], t("admin_unlock"), async values => {
                await unlock(values.admin_password);
                refresh();
            }, {403: "admin_denied"}),
            div("cluster", button(t("setup_admin"), setup, {variant: "quiet"}))));
}

async function overview(isSuper, signal) {
    async function pendingReports() {
        const size = 100;
        for (let offset = 0; offset <= 100000; offset += size) {
            const page = await adminApi("moderation", query("/reports", {status: "pending", limit: size, offset}), {signal});
            if (page.length < size) return number(offset + page.length);
        }
        return number(100100) + "+";
    }

    const visibleJournals = isSuper ? journals : journals.slice(0, 1);
    const jobs = [
        pendingReports(), adminApi("moderation", "/admin/stats", {signal}),
        Promise.all(visibleJournals.map(([service]) => adminApi(service, "/admin/audit?limit=5", {signal})))
            .then(all => all.flat().sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, 6)),
    ];
    if (isSuper) jobs.push(
        api("articles", "/?limit=1", {signal, anonymous: true}),
        adminApi("collector", "/status", {signal}));
    const [pending, stats, recent, articles, rss] = await Promise.allSettled(jobs);
    const value = result => result?.status === "fulfilled" ? result.value : null;
    const metric = (title, amount, extra = null) => div("panel stat-card",
        text(t(title), "muted"), el("strong", {}, amount ?? "—"), extra);
    const statsData = value(stats);
    const rssData = value(rss);
    const audits = value(recent);
    return div("stack",
        div("admin-metrics", metric("pending_reports", value(pending)),
            isSuper && metric("published_articles", value(articles) && number(value(articles).total)),
            isSuper && metric("active_sources", rssData && number(rssData.active_sources)),
            isSuper && div("panel stat-card", text(t("rss_status"), "muted"),
                rssData?.last_run ? badge(rssData.last_run.status) : "—",
                rssData && text(t("rss_interval", {count: Math.round(rssData.interval_seconds / 60)}), "small muted"))),
        div("panel stack", el("h3", {}, t("moderation_stats")), statsData
            ? Object.keys(statsData.actions).length ? table("moderation_stats", ["audit_action", "actions"],
                Object.entries(statsData.actions).map(([action, count]) => [eventName({action}), number(count)])) : empty()
            : text(t("error_503"), "notice")),
        div("panel stack", el("h3", {}, t("recent_audit")), audits
            ? audits.length ? auditTable(audits) : empty()
            : text(t("error_503"), "notice")));
}

async function audit(location, isSuper, signal) {
    const options = isSuper ? journals : journals.slice(0, 1);
    const source = options.find(([key]) => key === location.params.get("service"))?.[0] || options[0][0];
    const list = listState(location);
    const rows = await adminApi(source, query("/admin/audit", list.parameters), {signal});
    const [search, entries] = searchable(rows.slice(0, list.parameters.limit - 1),
        event => [eventName(event), event.reason, event.actor_id, event.target_id, event.request_id],
        auditTable);
    const select = selectFilter("source", "service", options.map(([key, caption]) => [key, t(caption)]), source,
        service => list.change({service}));
    return div("stack", div("cluster admin-tools", isSuper && select, search), entries, list.pagination(rows.length));
}

export async function adminPage(location, signal) {
    const me = viewer();
    const session = adminSession();
    if (!me || !["moderator", "super_admin"].includes(me.role) || !session) return gate(me);
    const isSuper = me.role === "super_admin";
    const nav = sections.filter(([, , , restricted]) => isSuper || !restricted);
    const current = location.path.slice("/admin".length).replace(/^\//, "");
    const section = nav.find(([, path]) => path === current);
    const sidebar = el("nav", {class: "panel sidebar-nav", "aria-label": t("admin")},
        nav.map(([key, path, glyph]) => link("/admin/" + path, [icon(glyph), t(key)],
            {"aria-current": current === path ? "page" : null})));
    let workspace;
    if (!section) workspace = state(t("admin_required"), t("not_found_help"), link("/admin/", t("overview"), {class: "button"}));
    else if (!current) workspace = await overview(isSuper, signal);
    else if (current === "audit") workspace = await audit(location, isSuper, signal);
    else {
        const area = ["reports", "comments", "restrictions"].includes(current) ? await import("./moderation.js")
            : current === "sources" ? await import("./sources.js") : await import("./editorial.js");
        workspace = await area[current](location, isSuper, signal);
    }
    const lockButton = button(t("admin_lock"), guard(async () => {
        try { await lock(); }
        finally { refresh(); }
        toast(t("admin_locked"));
    }), {variant: "quiet"});
    return [
        div("cluster-wide", heading(t("admin"), t("admin_help")),
            div("cluster admin-topline", el("span", {class: "pill"}, label("role", me.role)),
                el("span", {class: "small muted"}, t("admin_until", {date: date(session.expires_at, true)})),
                lockButton, link("/", t("public_site"), {class: "button quiet"}))),
        div("admin-grid", el("aside", {class: "admin-sidebar"}, sidebar),
            el("section", {class: "admin-work"}, el("h2", {}, t(section?.[0] ?? "admin")), workspace)),
    ];
}
