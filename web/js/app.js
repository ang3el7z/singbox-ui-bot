/**
 * Alpine.js application components.
 * Each section (server, clients, inbounds, etc.) is a self-contained Alpine component.
 */
import api, { getToken, setToken, clearToken } from "./api.js";

// ─── Root app ─────────────────────────────────────────────────────────────────

function appRoot() {
    return {
        page: "dashboard",
        username: localStorage.getItem("jwt_username") || "",
        loading: false,
        toast: null,

        init() {
            if (!getToken()) {
                this.page = "login";
            } else {
                this.page = "dashboard";
            }
        },

        async logout() {
            clearToken();
            this.page = "login";
            this.username = "";
        },

        showToast(msg, type = "success") {
            this.toast = { msg, type };
            setTimeout(() => { this.toast = null; }, 3500);
        },

        navigate(section) {
            this.page = section;
        },
    };
}

// ─── Login ────────────────────────────────────────────────────────────────────

function loginComponent() {
    return {
        username: "",
        password: "",
        error: "",
        loading: false,

        async submit() {
            this.loading = true;
            this.error = "";
            try {
                const res = await api.login(this.username, this.password);
                setToken(res.access_token);
                localStorage.setItem("jwt_username", res.username);
                this.$dispatch("login-success", { username: res.username });
            } catch (e) {
                this.error = e.message;
            } finally {
                this.loading = false;
            }
        },
    };
}

// ─── Dashboard ────────────────────────────────────────────────────────────────

function dashboardComponent() {
    return {
        status: null,
        clients: [],
        inbounds: [],
        loading: true,

        async init() {
            await this.refresh();
        },

        async refresh() {
            this.loading = true;
            try {
                [this.status, this.clients, this.inbounds] = await Promise.all([
                    api.serverStatus(),
                    api.clients(),
                    api.inbounds(),
                ]);
            } catch (e) {
                console.error(e);
            } finally {
                this.loading = false;
            }
        },
    };
}

// ─── Server ───────────────────────────────────────────────────────────────────

function serverComponent() {
    return {
        status: null,
        logs: [],
        loading: false,

        async init() {
            await this.loadStatus();
        },

        async loadStatus() {
            this.loading = true;
            try {
                this.status = await api.serverStatus();
            } finally { this.loading = false; }
        },

        async loadLogs() {
            this.loading = true;
            try {
                const data = await api.serverLogs(100);
                this.logs = data.logs || [];
            } finally { this.loading = false; }
        },

        async restart() {
            if (!confirm("Restart Sing-Box?")) return;
            this.loading = true;
            try {
                await api.serverRestart();
                this.$dispatch("toast", { msg: "Restarted", type: "success" });
                await this.loadStatus();
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },

        async reload() {
            this.loading = true;
            try {
                await api.serverReload();
                this.$dispatch("toast", { msg: "Config reloaded", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },
    };
}

// ─── Clients ──────────────────────────────────────────────────────────────────

function clientsComponent() {
    return {
        clients: [],
        inbounds: [],
        selected: null,
        showAdd: false,
        form: { name: "", inbound_tag: "", total_gb: 0, expire_days: 0 },
        loading: false,
        search: "",

        async init() {
            await this.load();
        },

        async load() {
            this.loading = true;
            try {
                [this.clients, this.inbounds] = await Promise.all([api.clients(), api.inbounds()]);
            } finally { this.loading = false; }
        },

        get filtered() {
            if (!this.search) return this.clients;
            return this.clients.filter(c =>
                c.name.toLowerCase().includes(this.search.toLowerCase())
            );
        },

        async select(c) {
            this.selected = await api.client(c.id);
        },

        async create() {
            this.loading = true;
            try {
                await api.createClient(this.form);
                this.showAdd = false;
                this.form = { name: "", inbound_tag: "", total_gb: 0, expire_days: 0 };
                await this.load();
                this.$dispatch("toast", { msg: "Client created", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },

        async toggleEnable(c) {
            try {
                await api.updateClient(c.id, { enable: !c.enable });
                await this.load();
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async deleteClient(c) {
            if (!confirm(`Delete ${c.name}?`)) return;
            try {
                await api.deleteClient(c.id);
                this.selected = null;
                await this.load();
                this.$dispatch("toast", { msg: "Deleted", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async resetStats(c) {
            await api.resetStats(c.id);
            await this.select(c);
            this.$dispatch("toast", { msg: "Stats reset", type: "success" });
        },

        async downloadSub(c) {
            try {
                const cfg = await api.subscription(c.id);
                const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: "application/json" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `${c.name}.json`;
                a.click();
                URL.revokeObjectURL(url);
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        formatBytes(bytes) {
            if (!bytes) return "0 B";
            const u = ["B", "KB", "MB", "GB", "TB"];
            let i = 0;
            while (bytes >= 1024 && i < u.length - 1) { bytes /= 1024; i++; }
            return `${bytes.toFixed(1)} ${u[i]}`;
        },
    };
}

// ─── Inbounds ─────────────────────────────────────────────────────────────────

function inboundsComponent() {
    return {
        inbounds: [],
        selected: null,
        showAdd: false,
        form: { tag: "", protocol: "vless_reality", listen_port: 443 },
        protocols: ["vless_reality", "vless_ws", "vmess_ws", "trojan", "shadowsocks", "hysteria2", "tuic"],
        loading: false,

        async init() { await this.load(); },

        async load() {
            this.loading = true;
            try { this.inbounds = await api.inbounds(); }
            finally { this.loading = false; }
        },

        async create() {
            this.loading = true;
            try {
                await api.createInbound(this.form);
                this.showAdd = false;
                this.form = { tag: "", protocol: "vless_reality", listen_port: 443 };
                await this.load();
                this.$dispatch("toast", { msg: "Inbound created", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },

        async deleteInbound(ib) {
            if (!confirm(`Delete inbound ${ib.tag}?`)) return;
            try {
                await api.deleteInbound(ib.tag);
                this.selected = null;
                await this.load();
                this.$dispatch("toast", { msg: "Deleted", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },
    };
}

// ─── Routing ──────────────────────────────────────────────────────────────────

function routingComponent() {
    return {
        rules: {},
        selectedKey: "domain",
        ruleKeys: ["domain", "domain_suffix", "domain_keyword", "ip_cidr", "geosite", "geoip", "rule_set"],
        showAdd: false,
        form: { rule_key: "domain", value: "", outbound: "proxy" },
        loading: false,

        async init() { await this.loadRules(); },

        async loadRules() {
            this.loading = true;
            try {
                const data = await api.routeRules(this.selectedKey);
                this.rules[this.selectedKey] = data;
            } catch (e) {
                this.rules[this.selectedKey] = [];
            } finally { this.loading = false; }
        },

        async selectKey(key) {
            this.selectedKey = key;
            if (!this.rules[key]) await this.loadRules();
        },

        async addRule() {
            this.loading = true;
            try {
                await api.addRule(this.form);
                this.showAdd = false;
                delete this.rules[this.form.rule_key];
                await this.loadRules();
                this.$dispatch("toast", { msg: "Rule added", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },

        async deleteRule(rule) {
            if (!confirm(`Delete rule: ${rule.value}?`)) return;
            try {
                await api.deleteRule(this.selectedKey, rule.value);
                delete this.rules[this.selectedKey];
                await this.loadRules();
                this.$dispatch("toast", { msg: "Deleted", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async exportRules() {
            const data = await api.exportRules();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url; a.download = "routing_rules.json"; a.click();
            URL.revokeObjectURL(url);
        },
    };
}

// ─── AdGuard ──────────────────────────────────────────────────────────────────

function adguardComponent() {
    return {
        status: null,
        stats: null,
        dns: null,
        rules: [],
        loading: false,
        newUpstream: "",
        newRule: "",
        newPassword: "",

        async init() { await this.load(); },

        async load() {
            this.loading = true;
            try {
                [this.status, this.stats, this.dns] = await Promise.all([
                    api.adguardStatus(),
                    api.adguardStats(),
                    api.adguardDns(),
                ]);
                const r = await api.adguardRules();
                this.rules = r.rules || [];
            } catch (e) {
                console.error("AdGuard:", e.message);
            } finally { this.loading = false; }
        },

        async toggle(on) {
            try {
                await api.adguardToggle(on);
                await this.load();
                this.$dispatch("toast", { msg: `Protection ${on ? "enabled" : "disabled"}`, type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async addUpstream() {
            if (!this.newUpstream) return;
            try {
                await api.addUpstream(this.newUpstream);
                this.newUpstream = "";
                await this.load();
                this.$dispatch("toast", { msg: "Upstream added", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async addFilterRule() {
            if (!this.newRule) return;
            try {
                await api.addFilterRule(this.newRule);
                this.newRule = "";
                await this.load();
                this.$dispatch("toast", { msg: "Rule added", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },
    };
}

// ─── Nginx ────────────────────────────────────────────────────────────────────

function nginxComponent() {
    return {
        status: null,
        paths: null,
        logs: "",
        loading: false,

        async init() { await this.load(); },

        async load() {
            this.loading = true;
            try {
                [this.status, this.paths] = await Promise.all([api.nginxStatus(), api.nginxPaths()]);
            } finally { this.loading = false; }
        },

        async configure() {
            this.loading = true;
            try {
                const res = await api.nginxConfigure();
                this.$dispatch("toast", { msg: res.message || "Configured", type: res.success ? "success" : "error" });
                await this.load();
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },

        async issueSSL() {
            if (!confirm("Issue SSL certificate? Make sure domain is pointed to this server.")) return;
            this.loading = true;
            try {
                await api.nginxSsl();
                this.$dispatch("toast", { msg: "SSL issued", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },

        async loadLogs() {
            const data = await api.nginxLogs(100);
            this.logs = data.logs || "";
        },

        async uploadSite(event) {
            const file = event.target.files[0];
            if (!file) return;
            this.loading = true;
            try {
                const res = await api.nginxUpload(file);
                this.$dispatch("toast", { msg: res.detail, type: "success" });
                await this.load();
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },

        async removeOverride() {
            if (!confirm("Remove custom site?")) return;
            try {
                await api.nginxDeleteOverride();
                this.$dispatch("toast", { msg: "Override removed", type: "success" });
                await this.load();
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async toggleSite() {
            const current = this.status?.site_enabled ?? false;
            const next = !current;
            const label = next ? "enable" : "disable";
            if (!confirm(`${label.charAt(0).toUpperCase() + label.slice(1)} the public site? Nginx will be reloaded.`)) return;
            this.loading = true;
            try {
                await api.nginxSiteToggle(next);
                this.$dispatch("toast", { msg: `Site ${next ? "enabled" : "disabled"}`, type: "success" });
                await this.load();
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },
    };
}

// ─── Federation ───────────────────────────────────────────────────────────────

function federationComponent() {
    return {
        nodes: [],
        topology: null,
        showAdd: false,
        form: { name: "", url: "", secret: "", role: "node" },
        loading: false,

        async init() { await this.load(); },

        async load() {
            this.loading = true;
            try {
                this.nodes = await api.fedNodes();
            } finally { this.loading = false; }
        },

        async addNode() {
            this.loading = true;
            try {
                await api.addFedNode(this.form);
                this.showAdd = false;
                this.form = { name: "", url: "", secret: "", role: "node" };
                await this.load();
                this.$dispatch("toast", { msg: "Node added", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },

        async pingAll() {
            this.loading = true;
            try {
                const results = await api.pingAll();
                this.$dispatch("toast", { msg: `Pinged ${results.length} nodes`, type: "success" });
                await this.load();
            } finally { this.loading = false; }
        },

        async loadTopology() {
            this.topology = await api.topology();
        },

        async deleteNode(n) {
            if (!confirm(`Delete ${n.name}?`)) return;
            try {
                await api.deleteFedNode(n.id);
                await this.load();
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },
    };
}

// ─── Admin ────────────────────────────────────────────────────────────────────

function adminComponent() {
    return {
        admins: [],
        auditLog: [],
        newAdminId: "",
        loading: false,

        async init() { await this.load(); },

        async load() {
            this.loading = true;
            try {
                [this.admins, this.auditLog] = await Promise.all([api.admins(), api.auditLog(30)]);
            } finally { this.loading = false; }
        },

        async addAdmin() {
            if (!this.newAdminId) return;
            try {
                await api.addAdmin({ telegram_id: parseInt(this.newAdminId) });
                this.newAdminId = "";
                await this.load();
                this.$dispatch("toast", { msg: "Admin added", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async deleteAdmin(a) {
            if (!confirm(`Remove admin ${a.telegram_id}?`)) return;
            try {
                await api.deleteAdmin(a.telegram_id);
                await this.load();
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async backup() {
            try { await api.backup(); }
            catch (e) { this.$dispatch("toast", { msg: e.message, type: "error" }); }
        },
    };
}

// ─── Settings ─────────────────────────────────────────────────────────────────

function settingsComponent() {
    return {
        s: { tz: "", bot_lang: "" },
        loading: false,
        saving: null,
        // Grouped timezones — same catalog as the bot
        tzGroups: [
            { group: "🇷🇺 Russia / СНГ", zones: [
                { label: "Moscow (UTC+3)",       value: "Europe/Moscow" },
                { label: "Kyiv (UTC+2/+3)",      value: "Europe/Kyiv" },
                { label: "Minsk (UTC+3)",         value: "Europe/Minsk" },
                { label: "Almaty (UTC+5)",        value: "Asia/Almaty" },
                { label: "Tashkent (UTC+5)",      value: "Asia/Tashkent" },
                { label: "Baku (UTC+4)",          value: "Asia/Baku" },
                { label: "Tbilisi (UTC+4)",       value: "Asia/Tbilisi" },
                { label: "Yerevan (UTC+4)",       value: "Asia/Yerevan" },
                { label: "Novosibirsk (UTC+7)",   value: "Asia/Novosibirsk" },
                { label: "Krasnoyarsk (UTC+7)",   value: "Asia/Krasnoyarsk" },
                { label: "Irkutsk (UTC+8)",       value: "Asia/Irkutsk" },
                { label: "Vladivostok (UTC+10)",  value: "Asia/Vladivostok" },
            ]},
            { group: "🌍 Europe", zones: [
                { label: "Berlin (UTC+1/+2)",     value: "Europe/Berlin" },
                { label: "London (UTC+0/+1)",     value: "Europe/London" },
                { label: "Paris (UTC+1/+2)",      value: "Europe/Paris" },
                { label: "Amsterdam (UTC+1/+2)",  value: "Europe/Amsterdam" },
                { label: "Warsaw (UTC+1/+2)",     value: "Europe/Warsaw" },
            ]},
            { group: "🌎 Americas", zones: [
                { label: "New York (UTC-5/-4)",   value: "America/New_York" },
                { label: "Los Angeles (UTC-8/-7)", value: "America/Los_Angeles" },
                { label: "Chicago (UTC-6/-5)",    value: "America/Chicago" },
                { label: "Toronto (UTC-5/-4)",    value: "America/Toronto" },
            ]},
            { group: "🌏 Asia / Pacific", zones: [
                { label: "Shanghai (UTC+8)",      value: "Asia/Shanghai" },
                { label: "Tokyo (UTC+9)",         value: "Asia/Tokyo" },
                { label: "Seoul (UTC+9)",         value: "Asia/Seoul" },
                { label: "Dubai (UTC+4)",         value: "Asia/Dubai" },
                { label: "Singapore (UTC+8)",     value: "Asia/Singapore" },
                { label: "Bangkok (UTC+7)",       value: "Asia/Bangkok" },
                { label: "Kolkata (UTC+5:30)",    value: "Asia/Kolkata" },
                { label: "Sydney (UTC+10/+11)",   value: "Australia/Sydney" },
            ]},
            { group: "🌐 Universal", zones: [
                { label: "UTC",                   value: "UTC" },
            ]},
        ],

        async init() {
            this.loading = true;
            try {
                this.s = await api.settingsAll();
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },

        async save(key, value) {
            if (!value) return;
            this.saving = key;
            try {
                const r = await api.settingsSet(key, value);
                this.s[key] = r.value;
                this.$dispatch("toast", { msg: `${key} → ${r.value}`, type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.saving = null; }
        },
    };
}

// ─── Docs ─────────────────────────────────────────────────────────────────────

function docsComponent() {
    return {
        docs: [],
        activeId: null,
        activeTitle: "",
        content: "",
        loading: false,
        loadingDoc: false,

        async init() {
            this.loading = true;
            try {
                this.docs = await api.docsList();
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally {
                this.loading = false;
            }
        },

        async open(doc) {
            this.activeId = doc.id;
            this.activeTitle = doc.title;
            this.content = "";
            this.loadingDoc = true;
            try {
                this.content = await api.docGet(doc.id);
            } catch (e) {
                this.content = `Error: ${e.message}`;
            } finally {
                this.loadingDoc = false;
            }
        },

        // Render markdown to safe HTML using marked (loaded from CDN)
        rendered() {
            if (!this.content) return "";
            if (typeof marked !== "undefined") {
                return marked.parse(this.content);
            }
            // Fallback: basic escaping + pre block
            return `<pre style="white-space:pre-wrap;word-break:break-word">${this.content.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</pre>`;
        },
    };
}

// Register components globally
document.addEventListener("alpine:init", () => {
    Alpine.data("appRoot",        appRoot);
    Alpine.data("loginComponent", loginComponent);
    Alpine.data("dashboard",      dashboardComponent);
    Alpine.data("serverSection",  serverComponent);
    Alpine.data("clientsSection", clientsComponent);
    Alpine.data("inboundsSection",inboundsComponent);
    Alpine.data("routingSection", routingComponent);
    Alpine.data("adguardSection", adguardComponent);
    Alpine.data("nginxSection",   nginxComponent);
    Alpine.data("federationSection", federationComponent);
    Alpine.data("adminSection",   adminComponent);
    Alpine.data("docsSection",     docsComponent);
    Alpine.data("settingsSection", settingsComponent);
});
