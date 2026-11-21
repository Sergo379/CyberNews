import {accessToken, adminSession, clearAdmin, clearSession} from "./session.js";
import {t} from "./i18n.js";

export class ApiError extends Error {
    constructor(status, retry = null, idempotencyKey = null) {
        super("Request failed");
        this.status = status;
        this.retry = retry;
        this.idempotencyKey = idempotencyKey;
    }
}

export class InputError extends Error {
    constructor(key) {
        super(key);
        this.key = key;
    }
}

export async function api(service, path, {method = "GET", body, signal, admin = false, anonymous = false,
    keepOn401 = false, idempotencyKey, checkAdmin = true} = {}) {
    const bearer = anonymous ? null : accessToken();
    const elevation = admin ? adminSession() : null;
    if (admin && !elevation) throw new ApiError(403);
    const headers = {Accept: "application/json"};
    if (bearer) headers.Authorization = `Bearer ${bearer}`;
    if (elevation) headers["X-Admin-Session"] = elevation.admin_session;
    if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let response;
    try {
        const timeout = AbortSignal.timeout(18000);
        response = await fetch(`/api/v1/${service}${path}`, {
            method, headers, signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
            cache: "no-store", redirect: "error",
            body: body === undefined ? undefined : JSON.stringify(body),
        });
    } catch (error) {
        if (error.name === "AbortError") throw error;
        throw new ApiError(0);
    }

    if (!response.ok) {
        if (response.status === 401 && bearer && !keepOn401 && accessToken() === bearer) clearSession("expired");
        if (response.status === 403 && elevation && checkAdmin && adminSession() === elevation) {
            try {
                await api("auth", "/admin/session", {admin: true, checkAdmin: false, signal});
            } catch (error) {
                if ([401, 403].includes(error.status) && adminSession() === elevation) clearAdmin("expired");
            }
        }
        throw new ApiError(response.status, response.headers.get("Retry-After"), response.headers.get("Idempotency-Key"));
    }
    if (response.status === 204) return null;
    try {
        return await response.json();
    } catch (error) {
        if (error.name === "AbortError") throw error;
        throw new ApiError(0);
    }
}

export function errorText(error, overrides = {}) {
    if (error instanceof InputError) return t(error.key);
    const status = error.status;
    if (overrides[status]) return t(overrides[status]);
    if (status === 0) return t("error_network");
    if (status === 429) {
        const seconds = /^\d+$/.test(error.retry ?? "") ? Number(error.retry)
            : Math.ceil((Date.parse(error.retry) - Date.now()) / 1000);
        return seconds > 0 ? t("error_429", {seconds}) : t("error_429_generic");
    }
    return t([400, 401, 403, 404, 409, 422, 503].includes(status) ? `error_${status}` : "error_other");
}

export function query(path, params) {
    const queryString = new URLSearchParams();
    for (const [name, value] of Object.entries(params)) {
        if (value !== "" && value != null) queryString.set(name, String(value));
    }
    return `${path}${queryString.size ? `?${queryString}` : ""}`;
}
