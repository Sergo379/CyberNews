import {api, InputError, query} from "../api.js";
import {category, date, number, t} from "../i18n.js";
import {viewer} from "../session.js";
import {articleContent} from "../components/article-html.js";
import {
    button, confirmAction, dialog, div, el, external, failed, field, form, guard, heading, image,
    link, loading, pagination, signInDialog, state, text, toast,
} from "../components/dom.js";
import {icon} from "../components/icons.js";
import {bookmarkButton} from "./catalog.js";

const PAGE_SIZE = 20;

function reactions(path, initial) {
    let stats = initial;
    let busy = false;
    const root = div("cluster");
    const controls = ["like", "dislike"].map(reaction => {
        const value = el("span");
        const control = button([icon(reaction), value], guard(async () => {
            if (!viewer()) return signInDialog();
            if (busy) return;
            busy = true;
            try {
                const remove = reaction === stats.my_reaction;
                stats = await api("community", path + "/reaction", {
                    method: remove ? "DELETE" : "PUT", body: remove ? undefined : {reaction},
                });
                render();
            } finally { busy = false; }
        }), {class: "button quiet reaction", "aria-label": t(reaction)});
        control.title = t(reaction);
        root.append(control);
        return {control, value, reaction};
    });
    function render() {
        for (const {control, value, reaction} of controls) {
            value.textContent = number(stats[reaction + "s"]);
            control.setAttribute("aria-pressed", String(stats.my_reaction === reaction));
        }
    }
    render();
    return root;
}

function report(target, id) {
    if (!viewer()) return signInDialog();
    dialog(t("report_" + target), panel => form("report", [
        field(t("reason"), "reason", {required: true, maxlength: 500}),
        field(t("details_optional"), "description", {tag: "textarea", maxlength: 4000, rows: 4}),
    ], t("send_report"), async values => {
        const reason = values.reason.trim();
        if (!reason) throw new InputError("error_422");
        await api("moderation", "/reports", {
            method: "POST", body: {target_type: target, target_id: id, reason, description: values.description.trim() || null},
        });
        panel.close();
        toast(t("report_sent"));
    }));
}

function commentField(name, value = "") {
    return field(t(name), "body", {tag: "textarea", required: true, maxlength: 5000, rows: 4, value});
}

function discussion(id, count, signal) {
    let offset = 0;
    let sort = "oldest";
    let allowed = false;
    let requestNumber = 0;
    const write = div("stack");
    const content = div("stack", loading());
    const countNode = el("span", {class: "pill", "aria-live": "polite"});
    const select = field(t("sort"), "comment_sort", {
        tag: "select", choices: [["oldest", t("oldest")], ["newest", t("newest")]],
    });
    select.addEventListener("change", event => {
        sort = event.target.value;
        offset = 0;
        load();
    });

    async function load() {
        const current = ++requestNumber;
        try {
            const data = await api("community", query("/articles/" + id + "/comments", {limit: PAGE_SIZE, offset, sort}), {signal});
            if (signal.aborted || requestNumber !== current) return;
            if (!data.items.length && offset > 0) {
                offset = Math.max(0, offset - PAGE_SIZE);
                return load();
            }
            countNode.textContent = number(data.total);
            if (count) count.textContent = number(data.total);
            content.replaceChildren(...(data.items.length
                ? data.items.map(comment => commentRow(comment))
                : [state(t("no_comments"), t("no_comments_help"))]));
            const nav = pagination(offset, PAGE_SIZE, offset + PAGE_SIZE < data.total, next => { offset = next; load(); });
            if (nav) content.append(nav);
        } catch (error) {
            if (!signal.aborted && requestNumber === current) content.replaceChildren(failed(error, load));
        }
    }

    function commentRow(comment) {
        const mine = viewer()?.id === comment.author_id;
        const row = el("article", {class: "comment-item stack"},
            div("cluster", el("strong", {}, comment.nickname),
                el("time", {datetime: comment.created_at, class: "small muted"}, date(comment.created_at, true)),
                comment.edited && el("span", {class: "pill"}, t("edited"))),
            text(comment.body, "comment-text"),
            div("cluster", reactions("/comments/" + comment.id, comment),
                mine && allowed && button(t("edit"), () => editComment(comment), {variant: "quiet"}),
                mine && button(t("delete"), () => confirmAction(t("delete_comment_title"), t("delete_comment_help"),
                    t("delete"), async () => {
                        await api("community", "/comments/" + comment.id, {method: "DELETE"});
                        toast(t("comment_deleted"));
                        await load();
                    }), {variant: "quiet"}),
                !mine && button(t("report_comment"), () => report("comment", comment.id), {variant: "quiet"}),
                !mine && button(t("report_user"), () => report("user", comment.author_id), {variant: "quiet"})));
        return row;
    }

    function editComment(comment) {
        dialog(t("edit"), panel => form("edit-comment", [commentField("write_comment", comment.body)], t("save"), async ({body}) => {
            if (!body.trim()) throw new InputError("error_422");
            await api("community", "/comments/" + comment.id, {method: "PATCH", body: {body}});
            panel.close();
            toast(t("comment_edited"));
            await load();
        }, {403: "comment_denied", 503: "comment_unavailable"}));
    }

    async function mountComposer() {
        if (!viewer()) {
            write.replaceChildren(div("panel cluster", text(t("comment_login")),
                button(t("login"), signInDialog, {variant: "quiet"})));
            return;
        }
        try {
            const permission = await api("moderation", "/comment-permission", {signal});
            if (signal.aborted) return;
            allowed = permission.allowed;
            if (!allowed) {
                write.replaceChildren(text(t("comment_denied"), "notice"));
                return;
            }
            write.replaceChildren(form("comment", [commentField("write_comment")], t("send_comment"), async ({body}, node) => {
                if (!body.trim()) throw new InputError("error_422");
                await api("community", "/articles/" + id + "/comments", {method: "POST", body: {body}});
                node.reset();
                toast(t("comment_created"));
                sort = "newest";
                select.querySelector("select").value = sort;
                offset = 0;
                await load();
            }, {403: "comment_denied", 503: "comment_unavailable"}));
        } catch {
            if (!signal.aborted) write.replaceChildren(div("cluster notice", text(t("comment_unavailable")),
                button(t("retry"), mountComposer, {variant: "quiet"})));
        }
    }

    load();
    mountComposer().then(() => { if (allowed && !signal.aborted) load(); });
    return el("section", {class: "comments-section stack", id: "comments", "aria-labelledby": "comments-title"},
        div("cluster-wide", div("cluster", el("h2", {id: "comments-title"}, t("comments")), countNode), select), write, content);
}

export async function article(id, signal) {
    let story;
    try { story = await api("articles", "/" + id, {signal, anonymous: true}); }
    catch (error) {
        if (error.status !== 404) throw error;
        return [heading(t("article_missing")), state(t("article_missing"), t("not_found_help"),
            link("/", t("back_feed"), {class: "button primary"}))];
    }

    const root = el("article", {class: "article-page reading stack"}, link("/", "← " + t("back_feed")));
    const original = external(story.original_url, t("original_link"), "button");
    const source = external(story.source_url, story.source_name) || story.source_name;
    root.append(
        div("article-heading", div("cluster", link("/?category=" + encodeURIComponent(story.category), category(story.category), {class: "pill category"})),
            el("h1", {}, story.title), story.summary && text(story.summary, "standfirst"),
            div("cluster meta-line", source, story.author && el("span", {}, t("author") + " · " + story.author),
                el("time", {datetime: story.published_at}, date(story.published_at)))),
    );
    const cover = image(story.image_url, "lead-image", true);
    if (cover) root.append(cover);
    const count = el("span");
    const tools = div("cluster article-tools", link("#comments", [icon("comments"), t("comments"), count],
        {class: "button quiet", "data-route": null}), button([icon("flag"), t("report_article")], () => report("article", id), {variant: "quiet"}));
    root.append(tools);
    api("community", "/articles/" + id + "/reactions", {signal}).then(stats => {
        if (!signal.aborted) tools.prepend(reactions("/articles/" + id, stats));
    }).catch(() => {
        if (!signal.aborted) tools.prepend(text(t("reactions_unavailable"), "small muted"));
    });
    if (viewer()) {
        api("community", "/articles/" + id + "/bookmark", {signal}).then(saved => {
            if (!signal.aborted) tools.append(bookmarkButton(id, saved.bookmarked));
        }).catch(() => {
            if (!signal.aborted) tools.append(text(t("actions_unavailable"), "small muted"));
        });
    }
    if (story.content_mode === "full_article" && story.content) {
        root.append(div("prose", articleContent(story.content)));
        if (original) root.append(original);
    } else {
        root.append(div("original-note", el("h2", {}, t("original_title")), text(t("external_notice")), original));
    }
    root.append(discussion(id, count, signal));
    return root;
}
