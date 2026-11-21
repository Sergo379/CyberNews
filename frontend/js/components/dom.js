import {t} from "../i18n.js";
import {errorText} from "../api.js";
import {go} from "../router.js";
import {icon} from "./icons.js";

let fieldId = 0;

export function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(props)) {
        if (value == null || value === false || name === "value") continue;
        if (name === "on") {
            for (const [event, handler] of Object.entries(value)) node.addEventListener(event, handler);
        } else node.setAttribute(name, value === true ? "" : String(value));
    }
    for (const child of children.flat(Infinity)) {
        if (child != null && child !== false) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    if (props.value != null) node.value = props.value;
    return node;
}

export const div = (className, ...children) => el("div", {class: className}, ...children);
export const text = (value, className) => el("p", {class: className}, value);

export function link(path, content, props = {}) {
    return el("a", {href: path, "data-route": "", ...props}, content);
}

export function safeUrl(value) {
    if (!value) return null;
    try {
        const url = new URL(value);
        if (["http:", "https:"].includes(url.protocol) && !url.username && !url.password) return url.href;
    } catch {
        return null;
    }
    return null;
}

export function external(value, content, className) {
    const href = safeUrl(value);
    return href ? el("a", {href, target: "_blank", rel: "noopener noreferrer", class: className}, content) : null;
}

export function image(value, className, eager = false) {
    const src = safeUrl(value);
    return src ? el("img", {
        src, alt: "", class: className, loading: eager ? "eager" : "lazy", decoding: "async",
        referrerpolicy: "no-referrer", on: {error: event => event.currentTarget.remove()},
    }) : null;
}

export function button(content, handler = null, {variant = "", type = "button", ...props} = {}) {
    return el("button", {
        class: `button ${variant}`, type, ...props,
        on: handler ? {click: handler} : props.on,
    }, content);
}

export function iconButton(name, title, handler, props = {}) {
    return el("button", {
        class: "icon-button quiet", type: "button", title, "aria-label": title, ...props,
        on: handler ? {click: handler} : props.on,
    }, icon(name));
}

export function field(caption, name, options = {}) {
    const {tag = "input", choices = [], help, reveal, id = `field-${++fieldId}`, ...props} = options;
    const input = el(tag, {name, id, "aria-describedby": help ? `${id}-help` : undefined, ...props},
        choices.map(([key, label]) => el("option", {value: key}, label)));
    const label = el("label", {for: id}, caption);
    let control = input;
    if (reveal) {
        const toggle = iconButton("eye", t("show_password"), () => {
            const shown = input.type === "password";
            input.type = shown ? "text" : "password";
            toggle.title = t(shown ? "hide_password" : "show_password");
            toggle.setAttribute("aria-label", toggle.title);
            toggle.setAttribute("aria-pressed", String(shown));
        }, {"aria-pressed": "false", "aria-controls": id});
        control = div("password-row", input, toggle);
    }
    return div("field", label, control, help ? el("span", {id: `${id}-help`, class: "field-help"}, help) : null);
}

export function check(label, name, checked = false) {
    return el("label", {class: "cluster check"}, el("input", {type: "checkbox", name, checked}), label);
}

export function toast(message, danger = false) {
    const notice = div(`toast${danger ? " error" : ""}`, message);
    if (danger) notice.setAttribute("role", "alert");
    const stack = document.querySelector("#toasts");
    if (stack.childElementCount >= 3) stack.firstElementChild.remove();
    stack.append(notice);
    setTimeout(() => notice.remove(), 5500);
}

export function form(key, fields, label, submit, overrides = {}) {
    const error = el("p", {class: "form-error", role: "alert", hidden: true});
    const save = button(label, null, {variant: "primary", type: "submit"});
    const node = el("form", {class: "field-stack", "data-form": key}, fields, error, div("cluster", save));
    node.addEventListener("submit", async event => {
        event.preventDefault();
        if (save.disabled) return;
        const data = Object.fromEntries(new FormData(node));
        error.hidden = true;
        save.disabled = true;
        try { await submit(data, node); }
        catch (failure) {
            if (failure.name !== "AbortError") {
                error.textContent = errorText(failure, overrides);
                error.hidden = false;
            }
        } finally { save.disabled = false; }
    });
    return node;
}

export function guard(handler, overrides = {}) {
    return async event => {
        const control = event.currentTarget;
        if (control.disabled) return;
        control.disabled = true;
        try { await handler(event); }
        catch (error) { if (error.name !== "AbortError") toast(errorText(error, overrides), true); }
        finally { control.disabled = false; }
    };
}

export function dialog(title, content, className = "") {
    const opener = document.activeElement;
    const id = `dialog-${++fieldId}`;
    const panel = el("dialog", {class: className, "aria-labelledby": id});
    const close = iconButton("close", t("close"), () => panel.close(), {class: "icon-button quiet dialog-close"});
    panel.append(div("dialog-inner stack",
        div("cluster-wide dialog-head", el("h2", {id}, title), close),
        typeof content === "function" ? content(panel) : content));
    panel.addEventListener("close", () => {
        panel.remove();
        if (opener?.isConnected) opener.focus({preventScroll: true});
    }, {once: true});
    document.body.append(panel);
    panel.showModal();
    const initial = panel.querySelector("form input:not([type=hidden]), form textarea, [data-initial-focus]");
    initial?.focus();
    return panel;
}

export function confirmAction(title, detail, action, handler) {
    return dialog(title, panel => {
        const confirmation = form("confirmation", [text(detail)], action, async () => {
            await handler();
            panel.close();
        });
        const submit = confirmation.querySelector("button[type=submit]");
        submit.classList.replace("primary", "danger");
        submit.before(button(t("cancel"), () => panel.close(), {"data-initial-focus": ""}));
        return confirmation;
    });
}

export function loading() {
    return el("section", {class: "state loading", "aria-busy": "true", "aria-live": "polite"},
        text(t("loading")), el("div", {class: "skeleton", "aria-hidden": "true"}, el("span"), el("span"), el("span")));
}

export function state(title, body, action = null) {
    return el("section", {class: "state"}, el("h2", {}, title), body ? text(body) : null, action);
}

export function failed(error, retry) {
    return state(t("error_title"), errorText(error), button(t("retry"), retry, {variant: "primary"}));
}

export function pagination(offset, limit, hasNext, change) {
    if (!hasNext && offset <= 0) return null;
    return el("nav", {class: "cluster pagination", "aria-label": t("page", {page: Math.floor(offset / limit) + 1})},
        button(t("previous"), () => change(Math.max(0, offset - limit)), {disabled: offset <= 0}),
        el("span", {class: "small page-number"}, t("page", {page: Math.floor(offset / limit) + 1})),
        button(t("next"), () => change(offset + limit), {disabled: !hasNext}));
}

export function signInDialog() {
    return dialog(t("sign_in_required"), panel => div("stack",
        text(t("sign_in_help")),
        button(t("login"), () => {
            panel.close();
            go(`/login?next=${encodeURIComponent(location.pathname + location.search)}`);
        }, {variant: "primary"})));
}

export function heading(title, detail = null) {
    return div("page-heading", el("h1", {}, title), detail ? text(detail) : null);
}
