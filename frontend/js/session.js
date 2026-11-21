const storageKey = "cybernews.access";
const events = new EventTarget();
let token = sessionStorage.getItem(storageKey);
let profile = null;
let admin = null;
let accessTimer;
let adminTimer;

function tokenExpiry(value) {
    try {
        const parts = value.split(".");
        return JSON.parse(atob(parts[1].replaceAll("-", "+").replaceAll("_", "/"))).exp * 1000;
    } catch {
        return 0;
    }
}

function emit(type, reason) {
    events.dispatchEvent(new CustomEvent(type, {detail: reason}));
}

export function listen(type, handler) {
    events.addEventListener(type, handler);
}

export function accessToken() {
    if (token && !(tokenExpiry(token) > Date.now())) clearSession("expired");
    return token;
}

export function viewer() {
    return profile;
}

export function adminSession() {
    if (admin && !(Date.parse(admin.expires_at) > Date.now())) clearAdmin("expired");
    return admin;
}

export function setProfile(value) {
    profile = value;
    emit("profile");
}

export function setToken(value) {
    clearTimeout(accessTimer);
    token = value;
    sessionStorage.setItem(storageKey, value);
    accessTimer = setTimeout(() => clearSession("expired"), Math.max(0, tokenExpiry(token) - Date.now()));
}

export function setAdmin(value) {
    clearTimeout(adminTimer);
    admin = value;
    adminTimer = setTimeout(() => clearAdmin("expired"), Math.max(0, Date.parse(admin.expires_at) - Date.now()));
    emit("admin");
}

export function clearAdmin(reason) {
    clearTimeout(adminTimer);
    if (!admin) return;
    admin = null;
    emit("admin", reason);
}

export function clearSession(reason) {
    clearTimeout(accessTimer);
    clearTimeout(adminTimer);
    sessionStorage.removeItem(storageKey);
    if (!token && !profile && !admin) return;
    token = profile = admin = null;
    emit("session", reason);
}

if (token) {
    const left = tokenExpiry(token) - Date.now();
    if (left > 0) accessTimer = setTimeout(() => clearSession("expired"), left);
    else clearSession("expired");
}
