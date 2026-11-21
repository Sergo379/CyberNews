import {InputError, query} from "../api.js";
import {label, number, t} from "../i18n.js";
import {refresh} from "../router.js";
import {button, check, confirmAction, dialog, div, el, external, field, form, guard, text, toast} from "../components/dom.js";
import {languageField} from "./editorial.js";
import {action, adminApi, badge, detail, empty, facts, identifier, listState, stamp, table} from "./shared.js";

function editSource(row) {
    dialog(t(row ? "edit_source" : "new_source"), panel => div("stack",
        form("source-editor", [
            field(t("source_name"), "name", {value: row?.name ?? "", required: true, maxlength: 160}),
            field(t("feed_url"), "feed_url", {value: row?.feed_url ?? "", type: "url", required: true, maxlength: 2048}),
            field(t("site_url"), "website_url", {value: row?.website_url ?? "", type: "url", required: true, maxlength: 2048}),
            languageField(row?.language),
            field(t("source_policy"), "content_policy", {tag: "select", value: row?.content_policy ?? "external_source",
                choices: ["external_source", "full_article"].map(key => [key, t(key)])}),
            field(t("rights_reference"), "rights_reference", {value: row?.rights_reference ?? "", maxlength: 1000, help: t("rights_help")}),
            check(t("allow_images"), "allow_images", row?.allow_images ?? false),
            check(t("source_active"), "active", row?.active ?? true),
        ], t("save"), async values => {
            const body = {
                ...values, name: values.name.trim(), rights_reference: values.rights_reference.trim() || null,
                active: values.active === "on", allow_images: values.allow_images === "on",
            };
            if ((body.content_policy === "full_article" || body.allow_images) && (body.rights_reference?.length ?? 0) < 3) {
                throw new InputError("rights_required");
            }
            await adminApi("collector", row ? "/sources/" + row.id : "/sources", {method: row ? "PATCH" : "POST", body});
            panel.close();
            refresh();
            toast(t("source_saved"));
        })));
}

function rssError(value) {
    if (!value) return "—";
    if (value === "source_unavailable") return t("rss_error_disabled");
    if (value === "run_interrupted") return t("status_interrupted");
    if (value === "import_unavailable") return t("rss_error_broker");
    return t("rss_error_unavailable");
}

function openRun(id) {
    detail("run_details", async () => {
        const run = await adminApi("collector", "/runs/" + id);
        return div("stack", facts([
            ["identifier", identifier(run.id)], ["trigger", label("trigger", run.trigger)], ["status", badge(run.status)],
            ["created", stamp(run.created_at)], ["started", stamp(run.started_at)], ["finished", stamp(run.finished_at)],
        ]),
        run.sources.length ? table("run_details", ["source", "status", "seen", "created", "updated", "unchanged", "skipped", "conflicted", "last_error"],
            run.sources.map(row => [identifier(row.source_id), badge(row.status), row.seen, row.created, row.updated,
                row.unchanged, row.skipped, row.conflicted, rssError(row.error)])) : empty());
    });
}

export async function sources(location, isSuper, signal) {
    const list = listState(location);
    const history = location.params.get("view") === "runs";
    const [status, rows] = await Promise.all([
        adminApi("collector", "/status", {signal}),
        adminApi("collector", query(history ? "/runs" : "/sources", list.parameters), {signal}),
    ]);

    function sync(path) {
        return guard(async () => {
            await adminApi("collector", path, {method: "POST"});
            if (!history) list.change({view: "runs"});
            else refresh();
            toast(t("sync_queued"));
        });
    }
    function toggle(row) {
        const title = t(row.active ? "source_disable" : "source_enable");
        confirmAction(title, row.name, title, async () => {
            await adminApi("collector", "/sources/" + row.id, {method: "PATCH", body: {active: !row.active}});
            refresh();
            toast(t("source_saved"));
        });
    }

    const items = rows.slice(0, list.parameters.limit - 1);
    const data = history
        ? table("sync_history", ["trigger", "status", "created", "finished", "actions"], items.map(row => [
            label("trigger", row.trigger), badge(row.status), stamp(row.created_at), stamp(row.finished_at),
            action("details", () => openRun(row.id)),
        ]))
        : table("rss", ["source", "status", "last_update", "processed", "last_error", "actions"], items.map(row => [
            div("stack rss-row", el("strong", {}, row.name), external(row.feed_url, row.feed_url) || row.feed_url,
                text(t(row.content_policy), "small muted")),
            div("stack", badge(row.status), text(t(row.active ? "status_active" : "status_inactive"), "small muted")),
            stamp(row.last_success_at || row.last_attempt_at), number(row.processed_count), rssError(row.last_error),
            div("cluster admin-actions", action("edit_source", () => editSource(row)),
                action(row.active ? "source_disable" : "source_enable", () => toggle(row)),
                row.active && button(t("sync_one"), sync("/sources/" + row.id + "/sync"), {variant: "quiet"})),
        ]));

    return div("stack",
        div("panel cluster-wide", div("cluster", el("strong", {}, t("rss_status")),
            status.last_run && badge(status.last_run.status),
            text(t("active_sources") + " · " + number(status.active_sources), "small muted"),
            text(status.auto_sync ? t("rss_interval", {count: Math.round(status.interval_seconds / 60)}) : t("rss_manual"), "small muted")),
        action("reload", () => refresh())),
        div("cluster admin-tools",
            button(t("sync_all"), sync("/sync"), {variant: "primary"}),
            !history && button(t("new_source"), () => editSource(null)),
            button(t(history ? "sources" : "sync_history"), () => list.change({view: history ? null : "runs"}))),
        history && el("h3", {}, t("sync_history")), items.length ? data : empty(), list.pagination(rows.length));
}
