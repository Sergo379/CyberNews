import {api, InputError, query} from "../api.js";
import {date, label, t} from "../i18n.js";
import {go, refresh} from "../router.js";
import {button, dialog, div, el, failed, field, form, loading, pagination, state, toast} from "../components/dom.js";

export const PAGE_SIZE = 20;

export function adminApi(service, path, options) {
    return api(service, path, {...options, admin: true});
}

export function empty() {
    return state(t("no_records"), t("no_records_help"));
}

export function badge(status) {
    return el("span", {class: "pill", "data-status": status}, label("status", status));
}

export function stamp(value) {
    return value ? el("time", {datetime: value}, date(value, true)) : "—";
}

export function identifier(id) {
    return id ? el("code", {}, id) : "—";
}

export function facts(fields) {
    return el("dl", {class: "kv"},
        fields.map(([key, value]) => [el("dt", {}, t(key)), el("dd", {}, value ?? "—")]));
}

export function table(caption, columns, rows) {
    return div("table-scroll", el("table", {class: "admin-table"},
        el("caption", {class: "sr-only"}, t(caption)),
        el("thead", {}, el("tr", {}, columns.map(key => el("th", {scope: "col"}, t(key))))),
        el("tbody", {}, rows.map(row => el("tr", {}, row.map(cell => el("td", {}, cell)))))));
}

export function action(key, handler) {
    return button(t(key), handler, {variant: "quiet"});
}

export function detail(title, load) {
    return dialog(t(title), panel => {
        const root = div("stack", loading());
        async function show() {
            try {
                const node = await load(panel);
                if (panel.open) root.replaceChildren(node);
            } catch (error) {
                if (panel.open) root.replaceChildren(failed(error, show));
            }
        }
        queueMicrotask(show);
        return root;
    });
}

export function reasonField(required = true) {
    return field(t("reason"), "reason", {tag: "textarea", required, rows: 3, maxlength: 500});
}

export function reasonDialog(title, description, handler, {required = true, success, danger = false, reusePanel = null} = {}) {
    reusePanel?.close();
    const panel = dialog(t(title), current => {
        const controls = form(title, [reasonField(required)], t(title), async ({reason}) => {
            if (required && !reason.trim()) throw new InputError("error_422");
            await handler(reason.trim() || null);
            current.close();
            if (success) toast(t(success));
            refresh();
        });
        if (danger) controls.querySelector("button[type=submit]").classList.replace("primary", "danger");
        return div("stack", description, controls);
    });
    return panel;
}

export function listState(location) {
    const requested = Number(location.params.get("offset"));
    const offset = Number.isSafeInteger(requested) && requested > 0 ? Math.min(requested, 100000) : 0;
    function change(fields = {}) {
        const values = new URLSearchParams(location.params);
        values.delete("offset");
        for (const [key, value] of Object.entries(fields)) {
            if (value != null && value !== "") values.set(key, String(value));
            else values.delete(key);
        }
        go(query(location.path, Object.fromEntries(values)), {scroll: false});
    }
    return {
        offset, parameters: {offset, limit: PAGE_SIZE + 1}, change,
        pagination: length => pagination(offset, PAGE_SIZE, length > PAGE_SIZE, next => change({offset: next || null})),
    };
}

export function selectFilter(title, key, choices, value, apply) {
    const select = field(t(title), key, {tag: "select", choices, value});
    select.addEventListener("change", event => apply(event.target.value));
    return select;
}

export function searchable(records, terms, render) {
    const root = div("stack");
    const search = field(t("page_search"), "page_search", {type: "search", maxlength: 120});
    function update(value) {
        const term = value.trim().toLocaleLowerCase();
        const result = records.filter(item => terms(item).some(value => String(value ?? "").toLocaleLowerCase().includes(term)));
        root.replaceChildren(result.length ? render(result) : term ? state(t("no_page_matches")) : empty());
    }
    search.addEventListener("input", event => update(event.target.value));
    update("");
    return [search, root];
}

export function eventName(event) {
    return label("event", event.action, t("event_unknown"));
}

export function auditTable(events) {
    return table("audit", ["audit_action", "audit_actor", "audit_target", "reason", "audit_result", "sort_date", "audit_request"],
        events.map(event => [eventName(event), identifier(event.actor_id), identifier(event.target_id), event.reason || "—",
            badge(event.result), stamp(event.created_at), identifier(event.request_id)]));
}
