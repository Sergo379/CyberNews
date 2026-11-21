let locale = localStorage.getItem("cybernews.lang") === "en" ? "en" : "ru";
let strings = {};
const dictionaries = new Map();

export function language() {
    return locale;
}

export async function setLanguage(value = locale) {
    const chosen = value === "en" ? "en" : "ru";
    if (!dictionaries.has(chosen)) {
        const response = await fetch(`/locales/${chosen}.json`);
        if (!response.ok) throw new Error("locale unavailable");
        dictionaries.set(chosen, await response.json());
    }
    strings = dictionaries.get(chosen);
    locale = chosen;
    document.documentElement.lang = locale;
    localStorage.setItem("cybernews.lang", locale);
}

export function t(key, args = {}) {
    return (strings[key] ?? key).replace(/\{(\w+)\}/g, (_, name) => String(args[name] ?? ""));
}

export function category(id) {
    return t(`category_${id || "other"}`);
}

export function date(value, showTime = false) {
    const when = value ? new Date(value) : null;
    if (!when || Number.isNaN(when.valueOf())) return t("date_unknown");
    const options = showTime ? {dateStyle: "medium", timeStyle: "short"} : {dateStyle: "medium"};
    return new Intl.DateTimeFormat(locale, options).format(when);
}

export function number(value) {
    return new Intl.NumberFormat(locale).format(value);
}

export function label(prefix, value, fallback = "—") {
    if (!value) return fallback;
    const key = `${prefix}_${value}`;
    return strings[key] ?? fallback;
}
