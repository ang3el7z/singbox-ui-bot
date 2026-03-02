/**
 * Fetch wrapper for /api/* endpoints.
 * Reads JWT from localStorage; redirects to login on 401.
 */

const BASE = "";

function getToken() {
    return localStorage.getItem("jwt_token");
}

function setToken(token) {
    localStorage.setItem("jwt_token", token);
}

function clearToken() {
    localStorage.removeItem("jwt_token");
    localStorage.removeItem("jwt_username");
}

async function apiFetch(method, path, body = null, stream = false) {
    const token = getToken();
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const opts = { method, headers };
    if (body !== null) opts.body = JSON.stringify(body);

    const res = await fetch(BASE + path, opts);

    if (res.status === 401) {
        clearToken();
        window.location.href = "/web/#/login";
        throw new Error("Unauthenticated");
    }

    if (!res.ok) {
        let detail = res.statusText;
        try { detail = (await res.json()).detail || detail; } catch {}
        throw new Error(detail);
    }

    if (stream) return res;
    if (res.headers.get("content-type")?.includes("application/json")) return res.json();
    if (res.headers.get("content-type")?.includes("application/zip")) return res.blob();
    return res.text();
}

const api = {
    get:    (path)              => apiFetch("GET",    path),
    post:   (path, body)        => apiFetch("POST",   path, body),
    patch:  (path, body)        => apiFetch("PATCH",  path, body),
    delete: (path)              => apiFetch("DELETE", path),

    // Auth
    login: (username, password) =>
        apiFetch("POST", "/api/auth/login", { username, password }),
    me:    ()                   => apiFetch("GET",  "/api/auth/me"),
    changePassword: (current_password, new_password) =>
        apiFetch("POST", "/api/auth/change-password", { current_password, new_password }),

    // Server
    serverStatus:  ()           => apiFetch("GET",  "/api/server/status"),
    serverLogs:    (lines=100)  => apiFetch("GET",  `/api/server/logs?lines=${lines}`),
    serverRestart: ()           => apiFetch("POST", "/api/server/restart"),
    serverReload:  ()           => apiFetch("POST", "/api/server/reload"),
    serverConfig:  ()           => apiFetch("GET",  "/api/server/config"),
    keypair:       ()           => apiFetch("GET",  "/api/server/keypair"),

    // Clients
    clients:       ()               => apiFetch("GET",  "/api/clients/"),
    client:        (id)             => apiFetch("GET",  `/api/clients/${id}`),
    createClient:  (data)           => apiFetch("POST", "/api/clients/", data),
    updateClient:  (id, data)       => apiFetch("PATCH", `/api/clients/${id}`, data),
    deleteClient:  (id)             => apiFetch("DELETE", `/api/clients/${id}`),
    resetStats:    (id)             => apiFetch("POST", `/api/clients/${id}/reset-stats`),
    clientTemplates: ()             => apiFetch("GET",  "/api/clients/templates"),
    subscription:  (id, tmpl="tun") => apiFetch("GET",  `/api/clients/${id}/subscription?template=${tmpl}`),

    // Inbounds
    inbounds:      ()           => apiFetch("GET",  "/api/inbounds/"),
    inbound:       (tag)        => apiFetch("GET",  `/api/inbounds/${tag}`),
    createInbound: (data)       => apiFetch("POST", "/api/inbounds/", data),
    deleteInbound: (tag)        => apiFetch("DELETE", `/api/inbounds/${tag}`),

    // Routing
    route:         ()           => apiFetch("GET",  "/api/routing/"),
    routeRules:    (key)        => apiFetch("GET",  `/api/routing/rules/${key}`),
    addRule:       (data)       => apiFetch("POST", "/api/routing/rules", data),
    deleteRule:    (key, val)   => apiFetch("DELETE", `/api/routing/rules?rule_key=${encodeURIComponent(key)}&value=${encodeURIComponent(val)}`),
    routeOutbounds:()           => apiFetch("GET",  "/api/routing/outbounds"),
    exportRules:   ()           => apiFetch("GET",  "/api/routing/export"),
    importRules:   (data)       => apiFetch("POST", "/api/routing/import", data),
    addRuleSet:    (data)       => apiFetch("POST", "/api/routing/rule-sets", data),
    deleteRuleSet: (tag)        => apiFetch("DELETE", `/api/routing/rule-sets/${tag}`),

    // AdGuard
    adguardStatus:   ()         => apiFetch("GET",  "/api/adguard/status"),
    adguardStats:    ()         => apiFetch("GET",  "/api/adguard/stats"),
    adguardToggle:   (on)       => apiFetch("POST", `/api/adguard/protection?enabled=${on}`),
    adguardDns:      ()         => apiFetch("GET",  "/api/adguard/dns"),
    addUpstream:     (u)        => apiFetch("POST", "/api/adguard/dns/upstream", { upstream: u }),
    delUpstream:     (u)        => apiFetch("DELETE", `/api/adguard/dns/upstream?upstream=${encodeURIComponent(u)}`),
    adguardRules:    ()         => apiFetch("GET",  "/api/adguard/rules"),
    addFilterRule:   (r)        => apiFetch("POST", "/api/adguard/rules", { rule: r }),
    delFilterRule:   (r)        => apiFetch("DELETE", `/api/adguard/rules?rule=${encodeURIComponent(r)}`),
    adguardPassword: (p)        => apiFetch("POST", "/api/adguard/password", { password: p }),
    syncClients:     ()         => apiFetch("POST", "/api/adguard/sync-clients"),

    // Nginx
    nginxStatus:     ()         => apiFetch("GET",  "/api/nginx/status"),
    nginxConfigure:  ()         => apiFetch("POST", "/api/nginx/configure"),
    nginxSsl:        ()         => apiFetch("POST", "/api/nginx/ssl"),
    nginxPaths:      ()         => apiFetch("GET",  "/api/nginx/paths"),
    nginxLogs:       (n=50)     => apiFetch("GET",  `/api/nginx/logs?lines=${n}`),
    nginxDeleteOverride: ()     => apiFetch("DELETE", "/api/nginx/override"),
    nginxSiteToggle: (enabled)  => apiFetch("POST",   `/api/nginx/site/toggle?enabled=${enabled}`),

    async nginxUpload(file) {
        const token = getToken();
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetch(BASE + "/api/nginx/override/upload", {
            method: "POST",
            headers: { "Authorization": `Bearer ${token}` },
            body: fd,
        });
        if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
        return res.json();
    },

    // Federation
    fedNodes:     ()            => apiFetch("GET",  "/api/federation/"),
    addFedNode:   (data)        => apiFetch("POST", "/api/federation/", data),
    deleteFedNode:(id)          => apiFetch("DELETE", `/api/federation/${id}`),
    pingNode:     (id)          => apiFetch("POST", `/api/federation/${id}/ping`),
    pingAll:      ()            => apiFetch("POST", "/api/federation/ping-all"),
    createBridge: (ids)         => apiFetch("POST", "/api/federation/bridge", { node_ids: ids }),
    topology:     ()            => apiFetch("GET",  "/api/federation/topology"),

    // Settings
    settingsAll:  ()            => apiFetch("GET",  "/api/settings/"),
    settingsGet:  (key)         => apiFetch("GET",  `/api/settings/${key}`),
    settingsSet:  (key, value)  => apiFetch("POST", `/api/settings/${key}`, { value }),

    // Docs  (lang = "ru" | "en", passed as query param)
    docsList: (lang="ru")       => apiFetch("GET", `/api/docs/?lang=${lang}`),
    docGet:   (id, lang="ru")   => apiFetch("GET", `/api/docs/${id}?lang=${lang}`),

    // Maintenance
    maintStatus:          ()        => apiFetch("GET",  "/api/maintenance/status"),
    maintSetBackupHours:  (h)       => apiFetch("POST", "/api/maintenance/backup/settings", { hours: h }),
    maintRunBackup:       ()        => apiFetch("POST", "/api/maintenance/backup/run"),
    maintLogsList:        ()        => apiFetch("GET",  "/api/maintenance/logs/list"),
    maintLogClearOne:     (n)       => apiFetch("POST", `/api/maintenance/logs/clear/${n}`),
    maintLogClearAll:     ()        => apiFetch("POST", "/api/maintenance/logs/clear-all"),
    maintSetCleanHours:   (h)       => apiFetch("POST", "/api/maintenance/logs/settings", { hours: h }),
    maintIpBanList:       ()        => apiFetch("GET",  "/api/maintenance/ip-ban/list"),
    maintIpBanAdd:        (ip, r)   => apiFetch("POST", "/api/maintenance/ip-ban/add", { ip, reason: r }),
    maintIpBanRemove:     (ip)      => apiFetch("DELETE", `/api/maintenance/ip-ban/${ip}`),
    maintIpBanAnalyze:    ()        => apiFetch("POST", "/api/maintenance/ip-ban/analyze"),
    maintIpBanAll:        ()        => apiFetch("POST", "/api/maintenance/ip-ban/ban-analyzed"),
    maintIpBanClearAuto:  ()        => apiFetch("POST", "/api/maintenance/ip-ban/clear-auto"),

    async maintBackupDownload() {
        const token = getToken();
        const res = await fetch(BASE + "/api/maintenance/backup/download", {
            headers: { "Authorization": `Bearer ${token}` },
        });
        if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `backup_${new Date().toISOString().slice(0, 16).replace("T", "_")}.zip`;
        a.click();
        URL.revokeObjectURL(url);
    },

    async maintLogDownload(name) {
        const token = getToken();
        const res = await fetch(BASE + `/api/maintenance/logs/download/${name}`, {
            headers: { "Authorization": `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(res.statusText);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = name;
        a.click();
        URL.revokeObjectURL(url);
    },

    // Admin
    admins:       ()            => apiFetch("GET",  "/api/admin/admins"),
    addAdmin:     (data)        => apiFetch("POST", "/api/admin/admins", data),
    deleteAdmin:  (tgId)        => apiFetch("DELETE", `/api/admin/admins/${tgId}`),
    auditLog:     (limit=50)    => apiFetch("GET",  `/api/admin/audit-log?limit=${limit}`),

    async backup() {
        const res = await apiFetch("GET", "/api/admin/backup", null, true);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `backup_${new Date().toISOString().slice(0, 10)}.zip`;
        a.click();
        URL.revokeObjectURL(url);
    },
};

export default api;
export { getToken, setToken, clearToken };
