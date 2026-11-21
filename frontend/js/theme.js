const systemTheme = matchMedia("(prefers-color-scheme: dark)");
let choice = localStorage.getItem("cybernews.theme");

if (!["light", "dark", "system"].includes(choice)) choice = "system";

export function theme() {
    return choice;
}

function apply() {
    document.documentElement.dataset.theme = choice === "system" ? (systemTheme.matches ? "dark" : "light") : choice;
}

export function setTheme(next) {
    choice = ["light", "dark"].includes(next) ? next : "system";
    localStorage.setItem("cybernews.theme", choice);
    apply();
}

systemTheme.addEventListener("change", apply);
apply();
