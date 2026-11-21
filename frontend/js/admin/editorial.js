import {InputError, query} from "../api.js";
import {category, label, t} from "../i18n.js";
import {refresh} from "../router.js";
import {viewer} from "../session.js";
import {articleContent} from "../components/article-html.js";
import {button, confirmAction, dialog, div, el, field, form, link, text, toast} from "../components/dom.js";
import {catalogMetadata} from "../pages/catalog.js";
import {
    action, adminApi, badge, empty, listState, reasonDialog, reasonField, searchable, selectFilter, stamp, table,
} from "./shared.js";

const roles = ["user", "moderator", "super_admin"];
const languagePattern = "[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8}){0,3}";
const articleStatus = ["draft", "published"];

export function languageField(value) {
    return field(t("article_language"), "language", {value: value || "en", required: true, pattern: languagePattern,
        maxlength: 35, spellcheck: "false", help: t("language_hint")});
}

export async function users(location, isSuper, signal) {
    const list = listState(location);
    const own = viewer().id;
    const rows = await adminApi("auth", query("/admin/users", list.parameters), {signal});

    function editRole(user) {
        dialog(t("user_role"), panel => div("stack", text(user.nickname), text(t("user_role_notice"), "notice"),
            form("change-role", [field(t("role"), "role", {tag: "select", value: user.role,
                choices: roles.map(role => [role, label("role", role)])}), reasonField(false)], t("save"), async values => {
                await adminApi("auth", "/admin/users/" + user.id + "/role", {method: "PATCH",
                    body: {role: values.role, reason: values.reason.trim() || null}});
                panel.close();
                refresh();
                toast(t("user_updated"));
            })));
    }

    function changeStatus(user) {
        const suspend = user.status === "active";
        reasonDialog(suspend ? "suspend" : "restore_account", text(user.nickname),
            reason => adminApi("auth", "/admin/users/" + user.id + (suspend ? "/suspend" : "/restore"),
                {method: "POST", body: {reason}}),
            {success: "user_updated", danger: suspend});
    }

    const [search, result] = searchable(rows.slice(0, list.parameters.limit - 1),
        user => [user.nickname, user.email, label("role", user.role), label("status", user.status)],
        users => table("users", ["nickname", "email", "role", "status", "registered_at", "actions"], users.map(user => [
            user.nickname, user.email, label("role", user.role), badge(user.status), stamp(user.created_at),
            div("cluster admin-actions", own !== user.id && user.status === "active" && action("user_role", () => editRole(user)),
                own !== user.id && user.role === "user" && action(user.status === "active" ? "suspend" : "restore_account", () => changeStatus(user))),
        ])));
    return div("stack", div("cluster admin-tools", search), result, list.pagination(rows.length));
}

function contentField(value = "") {
    const input = field(t("article_body"), "content", {
        tag: "textarea", value, class: "editor", required: true, maxlength: 100000, rows: 10, help: t("format_hint"),
    });
    const editor = input.querySelector("textarea");
    const formats = [
        ["paragraph", "<p>", "</p>"], ["heading", "<h2>", "</h2>"], ["quote", "<blockquote>", "</blockquote>"],
        ["list", "<ul>\n<li>", "</li>\n</ul>"],
    ];
    function insert(start, end) {
        const from = editor.selectionStart;
        const to = editor.selectionEnd;
        editor.setRangeText(start + editor.value.slice(from, to) + end, from, to, "select");
        editor.setSelectionRange(from + start.length, to + start.length);
        editor.focus();
    }
    const preview = el("details", {}, el("summary", {}, t("preview")), div("prose"));
    function updatePreview() {
        if (preview.open) preview.lastChild.replaceChildren(articleContent(editor.value, {images: false}));
    }
    editor.addEventListener("input", updatePreview);
    preview.addEventListener("toggle", updatePreview);
    return div("stack", div("cluster", formats.map(([name, start, end]) => action(name, () => { insert(start, end); updatePreview(); }))),
        input, preview);
}

function editArticle(row, categories) {
    const original = !row || row.source_id === null;
    const editableStatus = row?.status !== "hidden";
    dialog(t(row ? "edit_article" : "new_article"), panel => form("editor", [
        field(t("article_title"), "title", {required: true, value: row?.title ?? "", maxlength: 500}),
        field(t("article_summary"), "summary", {tag: "textarea", rows: 3, value: row?.summary ?? "", maxlength: 1200}),
        div("split", field(t("categories"), "category", {tag: "select", required: true, value: row?.category ?? "other",
            choices: categories.map(cat => [cat.id, category(cat.id)])}),
        languageField(row?.language)),
        field(t("author"), "author", {value: row?.author ?? "", maxlength: 160}),
        original && field(t("image_url"), "image_url", {type: "url", value: row?.image_url ?? "", maxlength: 2048}),
        original && contentField(row?.content),
        editableStatus && field(t("status"), "status", {tag: "select", value: row?.status ?? "draft",
            choices: articleStatus.map(status => [status, label("status", status)])}),
    ], t("save"), async values => {
        const data = {...values, title: values.title.trim(), author: values.author.trim() || null, summary: values.summary.trim() || null};
        if (!data.title || (original && !data.content.trim())) throw new InputError("error_422");
        if (original) data.image_url = values.image_url.trim() || null;
        await adminApi("articles", "/admin/articles" + (row ? "/" + row.id : ""), {
            method: row ? "PATCH" : "POST", body: data,
        });
        panel.close();
        refresh();
        toast(t("article_saved"));
    }), "wide-dialog");
}

export async function articles(location, isSuper, signal) {
    const list = listState(location);
    const allowed = [...articleStatus, "hidden"];
    const status = allowed.includes(location.params.get("status")) ? location.params.get("status") : "";
    const [rows, [categories]] = await Promise.all([
        adminApi("articles", query("/admin/articles", {status, ...list.parameters}), {signal}), catalogMetadata(signal),
    ]);
    const filter = selectFilter("status", "status", [["", t("all_statuses")], ...allowed.map(value => [value, label("status", value)])],
        status, value => list.change({status: value}));
    function change(row, type) {
        const path = "/admin/articles/" + row.id;
        const caption = type === "publish" ? "publish_article" : type + "_article";
        return confirmAction(t(caption), row.title, t(caption), async () => {
            await adminApi("articles", path + (type === "publish" ? "" : "/" + type), type === "publish"
                ? {method: "PATCH", body: {status: "published"}} : {method: "POST"});
            refresh();
            toast(t("article_updated"));
        });
    }

    return div("stack", div("cluster admin-tools", filter, button(t("new_article"), () => editArticle(null, categories), {variant: "primary"})),
        rows.length ? table("news", ["article_title", "categories", "status", "publication_date", "actions"],
            rows.slice(0, list.parameters.limit - 1).map(row => [
                row.status === "published" ? link("/article/" + row.id, row.title) : row.title,
                category(row.category), badge(row.status), stamp(row.published_at),
                div("cluster admin-actions", action("edit_article", () => editArticle(row, categories)),
                    row.status === "draft" && action("publish_article", () => change(row, "publish")),
                    row.status === "hidden" ? action("restore_article", () => change(row, "restore"))
                        : action("hide_article", () => change(row, "hide"))),
            ])) : empty(), list.pagination(rows.length));
}
