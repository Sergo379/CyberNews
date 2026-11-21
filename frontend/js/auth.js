import {api} from "./api.js";
import {accessToken, adminSession, clearAdmin, clearSession, setAdmin, setProfile, setToken} from "./session.js";

export async function verifyProfile(signal) {
    if (!accessToken()) return null;
    const profile = await api("auth", "/me", {signal});
    setProfile(profile);
    return profile;
}

export async function signIn(email, password) {
    const result = await api("auth", "/login", {method: "POST", body: {email, password}, anonymous: true});
    setToken(result.access_token);
    try {
        return await verifyProfile();
    } catch (error) {
        clearSession();
        throw error;
    }
}

export async function signOut() {
    try {
        if (adminSession()) await api("auth", "/admin/lock", {method: "POST", admin: true, signal: AbortSignal.timeout(3000)});
    } catch {
        // The browser must discard both credentials even when Auth is unavailable.
    } finally {
        clearSession("logout");
    }
}

export async function unlock(password) {
    const session = await api("auth", "/admin/unlock", {method: "POST", body: {admin_password: password}});
    setAdmin(session);
    try {
        await api("auth", "/admin/session", {admin: true, checkAdmin: false});
    } catch (error) {
        clearAdmin();
        throw error;
    }
}

export async function lock() {
    try {
        if (adminSession()) await api("auth", "/admin/lock", {method: "POST", admin: true, checkAdmin: false});
    } finally {
        clearAdmin();
    }
}
