const paths = {
    search: ["M21 21l-4.35-4.35", "M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z"],
    bookmark: ["M6 4h12v16l-6-4-6 4V4Z"],
    bell: ["M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9", "M10 21h4"],
    menu: ["M4 6h16M4 12h16M4 18h16"],
    close: ["m6 6 12 12M18 6 6 18"],
    sun: ["M12 7a5 5 0 1 1 0 10 5 5 0 0 1 0-10Z", "M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M19 5l-1.5 1.5m-11 11L5 19"],
    moon: ["M20 15a8 8 0 0 1-11-11 8.5 8.5 0 1 0 11 11Z"],
    shield: ["M12 2 21 6v6c0 5-4 8-9 10-5-2-9-5-9-10V6l9-4Z", "M8 9h8m-8 4h8m-8 4h5"],
    comments: ["M4 5h16v11H9l-5 3V5Z", "M8 9h8m-8 3h5"],
    like: ["M7 10v10H3V10h4l5-7c3 0 3 3 2 6h4c2 0 3 1 2.5 3l-1.3 6c-.3 1.2-1 2-2.5 2H7"],
    dislike: ["M7 14V4H3v10h4l5 7c3 0 3-3 2-6h4c2 0 3-1 2.5-3l-1.3-6c-.3-1.2-1-2-2.5-2H7"],
    flag: ["M5 22V3m0 2c4-4 9 4 14 0v10c-5 4-10-4-14 0"],
    user: ["M16 8a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z", "M4 21v-2a5 5 0 0 1 5-5h6a5 5 0 0 1 5 5v2"],
    eye: ["M2 12s4-6 10-6 10 6 10 6-4 6-10 6-10-6-10-6Z", "M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"],
    check: ["m4 12 5 5L20 6"],
    layers: ["m12 3 9 5-9 5-9-5 9-5Zm9 9-9 5-9-5m18 4-9 5-9-5"],
    rss: ["M4 4a16 16 0 0 1 16 16M4 10a10 10 0 0 1 10 10M5 18h.01"],
    audit: ["M6 3h12v18H6zM9 7h6m-6 5h6m-6 5h4"],
    history: ["M4 12a8 8 0 1 1 8 8M4 12V6m0 6h6m2-4v5l3 2"],
    article: ["M4 5h16v14H4zM8 9h8m-8 3h8m-8 3h4"],
};
const ns = "http://www.w3.org/2000/svg";

export function icon(name) {
    const svg = document.createElementNS(ns, "svg");
    for (const [key, value] of Object.entries({
        viewBox: "0 0 24 24", class: "icon", fill: "none", stroke: "currentColor", "stroke-width": "1.65",
        "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false",
    })) svg.setAttribute(key, value);
    for (const d of paths[name] ?? paths.article) {
        const path = document.createElementNS(ns, "path");
        path.setAttribute("d", d);
        svg.append(path);
    }
    return svg;
}
