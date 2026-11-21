import {api, query} from "../api.js";
import {category, date, number, t} from "../i18n.js";
import {go} from "../router.js";
import {viewer} from "../session.js";
import {button, div, el, external, failed, field, guard, image, link, loading, pagination, signInDialog, state, text, toast} from "../components/dom.js";
import {icon} from "../components/icons.js";

const PAGE_SIZE = 9;
let metadata;

export async function catalogMetadata(signal) {
    if (metadata) return metadata;
    metadata = await Promise.all([api("articles", "/categories", {signal, anonymous: true}),
        api("articles", "/sources", {signal, anonymous: true})]);
    return metadata;
}

export function bookmarkButton(articleId, isSaved, onChange = () => {}) {
    let saved = Boolean(isSaved);
    const control = el("button", {type: "button", class: "icon-button quiet"}, icon("bookmark"));
    const update = () => {
        const label = t(saved ? "remove_bookmark" : "save_bookmark");
        control.title = label;
        control.setAttribute("aria-label", label);
        control.setAttribute("aria-pressed", String(saved));
    };
    control.addEventListener("click", guard(async () => {
        if (!viewer()) { signInDialog(); return; }
        await api("community", `/articles/${articleId}/bookmark`, {method: saved ? "DELETE" : "PUT"});
        saved = !saved;
        update();
        onChange(saved);
        toast(t(saved ? "bookmark_saved" : "bookmark_removed"));
    }));
    update();
    return control;
}

export function metrics(stats) {
    if (!stats) return el("span", {class: "small muted"}, t("reactions_unavailable"));
    return div("cluster meta-line",
        [["comments", "comments", stats.comments], ["like", "like", stats.likes], ["dislike", "dislike", stats.dislikes]].map(
            ([glyph, key, value]) => el("span", {class: "metric", title: t(key), "aria-label": `${t(key)}: ${value}`}, icon(glyph), number(value))));
}

function card(article, stats) {
    return el("article", {class: "news-card", "data-article-id": article.id},
        image(article.image_url, "card-image"),
        div("cluster", el("span", {class: "pill category"}, category(article.category))),
        el("h3", {}, link(`/article/${article.id}`, article.title)),
        article.summary ? text(article.summary) : null,
        div("cluster meta-line", el("span", {}, article.source_name), el("time", {datetime: article.published_at}, date(article.published_at))),
        div("cluster card-actions", metrics(stats),
            viewer() && stats ? bookmarkButton(article.id, stats.bookmarked) : null));
}

function feature(article, stats) {
    return el("article", {class: "hero", "data-article-id": article.id},
        div("hero-content", div("hero-kicker", t("latest"), " · ", category(article.category)),
            el("h2", {}, link(`/article/${article.id}`, article.title)),
            article.summary ? text(article.summary) : null,
            div("cluster hero-meta", article.source_name, el("time", {datetime: article.published_at}, date(article.published_at))),
            div("cluster hero-meta", metrics(stats),
                viewer() && stats ? bookmarkButton(article.id, stats.bookmarked) : null)),
        el("div", {class: "hero-art", "aria-hidden": "true"}, icon("shield"), image(article.image_url, null, true)));
}

function filterValue(form, name) {
    return form.elements.namedItem(name)?.value || "";
}

function dateRange(value, last) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    const when = new Date(`${value}T${last ? "23:59:59.999" : "00:00:00"}`);
    return Number.isNaN(when.valueOf()) ? null : when.toISOString();
}

function cleanParams(params) {
    const offset = Number(params.get("offset"));
    return {
        q: (params.get("q") || "").slice(0, 160), category: params.get("category") || "",
        source_id: params.get("source_id") || "", from: params.get("from") || "", to: params.get("to") || "",
        sort: params.get("sort") === "oldest" ? "oldest" : "newest",
        offset: Number.isSafeInteger(offset) && offset > 0 ? Math.min(offset, 100000) : 0,
    };
}

function listLink(filters, additions = {}) {
    const params = {...filters, ...additions};
    if (params.sort === "newest") delete params.sort;
    if (!params.offset) delete params.offset;
    return query("/", params);
}

export async function catalog(location, signal) {
    const initial = cleanParams(location.params);
    const [categories, sources] = await catalogMetadata(signal);
    let filters = initial;
    const display = div("stack");
    const featureHost = div("feature-host");
    const results = el("p", {class: "small muted", "aria-live": "polite"}, t("loading"));
    const total = el("strong", {}, "—");
    const cardHeader = div("cluster-wide", el("h2", {}, t("feed")), results);
    const search = field(t("search_news"), "q", {id: "feed-query", type: "search", maxlength: 160, placeholder: t("search_placeholder"), value: initial.q});
    const searchInput = search.querySelector("input");
    const controls = el("form", {class: "feed-tools", "data-form": "catalog"},
        div("feed-search", search, button([icon("search"), t("search")], null, {variant: "primary", type: "submit"})),
        el("details", {class: "filters", open: Boolean(initial.source_id || initial.from || initial.to || initial.sort !== "newest")},
            el("summary", {}, t("filter")),
            div("filter-grid",
                field(t("source"), "source_id", {tag: "select", value: initial.source_id,
                    choices: [["", t("all_sources")], ...sources.filter(item => item.id).map(item => [item.id, item.name])]}),
                field(t("date_from"), "from", {type: "date", value: initial.from}),
                field(t("date_to"), "to", {type: "date", value: initial.to}),
                field(t("sort"), "sort", {tag: "select", value: initial.sort, choices: [["newest", t("newest")], ["oldest", t("oldest")]]}),
                div("cluster filter-actions", button(t("apply"), null, {variant: "primary", type: "submit"}),
                    button(t("clear"), () => go("/#feed"), {variant: "quiet"})))));
    const categoryPairs = [["", t("all_categories")], ...categories.map(item => [item.id, category(item.id)])];
    const rows = () => categoryPairs.map(([id, name]) => link(listLink(filters, {category: id, offset: 0}) + "#feed", name, {
        "aria-current": filters.category === id ? "true" : null,
    }));
    const categoryPanel = div("category-links", rows());
    const mobileSelect = field(t("categories"), "mobile-category", {tag: "select", value: initial.category,
        choices: categoryPairs, on: {change: event => go(listLink(filters, {category: event.currentTarget.value, offset: 0}) + "#feed")}});
    const navigation = el("aside", {class: "news-aside"},
        el("section", {class: "panel"}, el("h2", {}, t("categories")), categoryPanel),
        el("section", {class: "panel"}, el("h2", {}, t("sources")),
            el("ul", {class: "source-list"}, sources.map(source => el("li", {},
                external(source.url, source.name) || el("span", {}, source.name))))));

    let activeRequest;
    let pending;
    async function fetchPage(params) {
        activeRequest?.abort();
        activeRequest = new AbortController();
        const requestSignal = AbortSignal.any([signal, activeRequest.signal]);
        filters = params;
        categoryPanel.replaceChildren(...rows());
        display.replaceChildren(loading());
        results.textContent = t("loading");
        const q = query("/", {
            q: params.q, category: params.category, source_id: params.source_id,
            published_from: dateRange(params.from, false), published_to: dateRange(params.to, true),
            sort: params.sort, limit: PAGE_SIZE, offset: params.offset,
        });
        try {
            const page = await api("articles", q, {signal: requestSignal, anonymous: true});
            let stats = new Map();
            if (page.items.length) {
                try {
                    const records = await api("community", "/articles/stats", {
                        method: "POST", body: {ids: page.items.map(item => item.id)}, signal: requestSignal,
                    });
                    stats = new Map(records.map(item => [item.article_id, item]));
                } catch (error) {
                    if (error.name === "AbortError") return;
                }
            }
            if (requestSignal.aborted) return;
            total.textContent = t("articles_count", {count: number(page.total)});
            results.textContent = t("result_count", {count: number(page.total)});
            const front = !params.offset && !params.q && !params.category && !params.source_id &&
                !params.from && !params.to && params.sort === "newest" && page.items.length;
            const items = front ? page.items.slice(1) : page.items;
            featureHost.replaceChildren(front ? feature(page.items[0], stats.get(page.items[0].id)) : document.createTextNode(""));
            const pages = pagination(params.offset, PAGE_SIZE, page.total > params.offset + PAGE_SIZE,
                offset => go(listLink(params, {offset}) + "#feed"));
            display.replaceChildren(items.length
                ? div("card-grid", items.map(article => card(article, stats.get(article.id))))
                : front ? document.createTextNode("") : state(t("no_news"), t("no_news_help"), link("/#feed", t("clear"), {class: "button"})),
            pages || document.createTextNode(""));
        } catch (error) {
            if (error.name === "AbortError" || requestSignal.aborted) return;
            results.textContent = t("error_title");
            display.replaceChildren(failed(error, () => fetchPage(params)));
        }
    }
    const readFilters = () => ({...filters, offset: 0, q: searchInput.value.trim(),
        source_id: filterValue(controls, "source_id"), from: filterValue(controls, "from"),
        to: filterValue(controls, "to"), sort: filterValue(controls, "sort")});
    controls.addEventListener("submit", event => {
        event.preventDefault();
        if (!controls.reportValidity()) return;
        clearTimeout(pending);
        go(listLink(readFilters()) + "#feed", {scroll: false});
    });
    searchInput.addEventListener("input", () => {
        clearTimeout(pending);
        pending = setTimeout(() => {
            if (signal.aborted) return;
            const next = readFilters();
            history.replaceState({}, "", listLink(next) + location.hash);
            fetchPage(next);
        }, 300);
    });
    signal.addEventListener("abort", () => clearTimeout(pending), {once: true});
    fetchPage(initial);
    return [
        div("cluster-wide edition-head", div("", el("h1", {}, t("news_title")), text(t("news_intro"))),
            div("edition-meta", total)),
        featureHost,
        el("div", {class: "mobile-categories", id: "categories-mobile"}, mobileSelect),
        el("div", {class: "news-layout", id: "categories"}, navigation,
            el("section", {class: "feed", id: "feed"}, controls, cardHeader, display)),
    ];
}
