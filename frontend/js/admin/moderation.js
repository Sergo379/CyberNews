import {InputError, query} from "../api.js";
import {t} from "../i18n.js";
import {link, button, div, el, failed, field, form, loading, state, text} from "../components/dom.js";
import {
    action, adminApi, badge, detail, empty, facts, identifier, listState, reasonDialog, selectFilter, stamp, table,
} from "./shared.js";

const statuses = values => values.map(status => [status, t("status_" + status)]);

function commentDetail(id, isSuper) {
    return detail("moderation_comment", async panel => {
        const comment = await adminApi("moderation", "/comments/" + id);
        const eligible = comment.status === "published" && (isSuper ||
            (await adminApi("auth", query("/admin/user-search", {user_id: comment.author_id}))).length > 0);
        function change(kind) {
            let key = crypto.randomUUID();
            let savedReason;
            return reasonDialog(kind + "_comment", text(comment.nickname), async reason => {
                if (savedReason !== reason) {
                    savedReason = reason;
                    key = crypto.randomUUID();
                }
                try {
                    await adminApi("moderation", "/comments/" + id + "/" + kind, {
                        method: "POST", body: {reason}, idempotencyKey: key,
                    });
                } catch (error) {
                    if (error.status !== 503) throw error;
                    key = error.idempotencyKey ?? key;
                    throw new InputError("comment_pending");
                }
            }, {success: "comment_moderated", danger: kind === "hide", reusePanel: panel});
        }
        const history = () => {
            panel.close();
            detail("comment_history", async () => {
                const items = await adminApi("moderation", "/comments/" + id + "/history");
                return items.length ? table("comment_history", ["audit_action", "issued_by", "reason", "audit_result", "sort_date"],
                    items.map(row => [t(row.action + "_comment"), identifier(row.actor_id), row.reason, badge(row.result), stamp(row.created_at)]))
                    : empty();
            });
        };
        return div("stack", facts([
            ["nickname", comment.nickname], ["article_id", identifier(comment.article_id)], ["status", badge(comment.status)],
            ["created", stamp(comment.created_at)], ["reason", comment.moderation_reason],
        ]),
        text(comment.body, "comment-text"),
        div("cluster", eligible && action("hide_comment", () => change("hide")),
            isSuper && comment.status === "hidden" && action("restore_comment", () => change("restore")),
            isSuper && action("comment_history", history)));
    });
}

export async function reports(location, isSuper, signal) {
    const values = ["pending", "reviewed", "rejected"];
    const list = listState(location);
    const requested = location.params.get("status");
    const status = values.includes(requested) ? requested : "";
    const rows = await adminApi("moderation", query("/reports", {status, ...list.parameters}), {signal});
    const filter = selectFilter("status", "status", [["", t("all_statuses")], ...statuses(values)], status,
        value => list.change({status: value}));
    function open(id) {
        detail("report_details", async panel => {
            const row = await adminApi("moderation", "/reports/" + id);
            function review(key, status) {
                reasonDialog(key, text(row.reason), reason => adminApi("moderation", "/reports/" + id, {
                    method: "PATCH", body: {status, reason},
                }), {required: false, success: "report_updated", danger: status === "rejected", reusePanel: panel});
            }
            const target = row.target_type === "article" ? link("/article/" + row.target_id, t("open_story")) : null;
            return div("stack", facts([
                ["status", badge(row.status)], ["target", t("target_" + row.target_type)], ["identifier", identifier(row.target_id)],
                ["author", identifier(row.author_id)], ["reason", row.reason], ["description", row.description],
                ["created", stamp(row.created_at)], ["reviewed_at", stamp(row.reviewed_at)], ["audit_actor", identifier(row.reviewed_by)],
            ]), div("cluster", target,
            row.target_type === "comment" && action("moderation_comment", () => { panel.close(); commentDetail(row.target_id, isSuper); }),
            row.target_type === "user" && action("restriction_history", () => { panel.close(); history(row.target_id); })),
            row.status === "pending" && div("cluster",
                action("mark_reviewed", () => review("mark_reviewed", "reviewed")),
                action("reject_report", () => review("reject_report", "rejected"))));
        });
    }
    return div("stack", div("cluster admin-tools", filter),
        rows.length ? table("reports", ["target", "reason", "status", "created", "actions"],
            rows.slice(0, list.parameters.limit - 1).map(row => [
                t("target_" + row.target_type), row.reason, badge(row.status), stamp(row.created_at),
                action("details", () => open(row.id)),
            ])) : empty(), list.pagination(rows.length));
}

export async function comments(location, isSuper, signal) {
    const list = listState(location);
    const uuid = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
    const requested = location.params.get("article_id") || "";
    const articleId = new RegExp("^" + uuid + "$").test(requested) ? requested : "";
    const rows = await adminApi("moderation", query("/comments", {article_id: articleId, ...list.parameters}), {signal});
    const filter = form("comment-filter", [field(t("article_id"), "article_id", {pattern: uuid, value: articleId})],
        t("filter_by_article"), values => list.change({article_id: values.article_id}));
    return div("stack", div("panel", filter),
        rows.length ? table("comments", ["nickname", "moderation_comment", "status", "created", "actions"],
            rows.slice(0, list.parameters.limit - 1).map(row => [
                row.nickname, row.body.length > 150 ? row.body.slice(0, 150) + "…" : row.body,
                badge(row.status), stamp(row.created_at), action("details", () => commentDetail(row.id, isSuper)),
            ])) : empty(), list.pagination(rows.length));
}

function restrictionRows(rows, isSuper, showHistory) {
    return table("restrictions", ["target_user", "reason", "status", "issued_by", "created", "lifted_by", "lifted_at", "actions"],
        rows.map(row => [
            identifier(row.user_id), row.reason, badge(row.active ? "active" : "lifted"), identifier(row.created_by), stamp(row.created_at),
            identifier(row.lifted_by), stamp(row.lifted_at), div("cluster admin-actions",
                showHistory && action("restriction_history", () => history(row.user_id)),
                isSuper && row.active && action("restriction_lift", () => reasonDialog("restriction_lift", identifier(row.user_id),
                    reason => adminApi("moderation", "/restrictions/" + row.id + "/lift", {method: "POST", body: {reason}}),
                    {success: "restriction_lifted", danger: true}))),
        ]));
}

function history(userId) {
    detail("restriction_history", async () => {
        const root = div("stack");
        const size = 20;
        async function show(offset) {
            root.replaceChildren(loading());
            try {
                const rows = await adminApi("moderation", query("/users/" + userId + "/restrictions", {offset, limit: size + 1}));
                root.replaceChildren(rows.length ? restrictionRows(rows.slice(0, size), false, false) : empty(),
                    div("cluster",
                        offset > 0 && button(t("previous"), () => show(Math.max(0, offset - size))),
                        rows.length > size && button(t("next"), () => show(offset + size))));
            } catch (error) { root.replaceChildren(failed(error, () => show(offset))); }
        }
        await show(0);
        return root;
    });
}

export async function restrictions(location, isSuper, signal) {
    const list = listState(location);
    const active = ["true", "false"].includes(location.params.get("active")) ? location.params.get("active") : "";
    const rows = await adminApi("moderation", query("/restrictions", {active, ...list.parameters}), {signal});
    const searchResult = div("stack");
    const search = form("find-user", [field(t("user_prefix"), "q", {minlength: 2, maxlength: 32, required: true, type: "search"})],
        t("find_user"), async ({q}) => {
            searchResult.replaceChildren();
            if (q.trim().length < 2) throw new InputError("error_422");
            const users = await adminApi("auth", query("/admin/user-search", {q: q.trim()}), {signal});
            searchResult.replaceChildren(users.length ? table("find_user", ["nickname", "actions"], users.map(user => [
                user.nickname, div("cluster admin-actions", action("restriction_place", () =>
                    reasonDialog("restriction_place", text(user.nickname),
                        reason => adminApi("moderation", "/restrictions", {method: "POST", body: {user_id: user.id, reason}}),
                        {success: "restriction_created", danger: true})),
                action("restriction_history", () => history(user.id))),
            ])) : state(t("restriction_targets_empty")));
        });
    const filter = selectFilter("status", "active",
        [["", t("all_statuses")], ["true", t("status_active")], ["false", t("status_lifted")]], active,
        value => list.change({active: value}));
    return div("stack", div("panel stack", search, searchResult), div("cluster admin-tools", filter),
        rows.length ? restrictionRows(rows.slice(0, list.parameters.limit - 1), isSuper, true) : empty(), list.pagination(rows.length));
}
