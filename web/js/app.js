/**
 * Alpine.js application components.
 * Each section (server, clients, inbounds, etc.) is a self-contained Alpine component.
 */
import api, { getToken, setToken, clearToken } from "./api.js";

// в”Ђв”Ђв”Ђ Root app в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

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

// в”Ђв”Ђв”Ђ Login в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

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

// в”Ђв”Ђв”Ђ Dashboard в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

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

// в”Ђв”Ђв”Ђ Server в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

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

// в”Ђв”Ђв”Ђ Clients в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

function clientsComponent() {
    return {
        clients: [],
        inbounds: [],
        allTemplates: [],
        selected: null,
        showAdd: false,
        showTmpl: false,
        showSubUrl: false,
        subUrls: {},
        form: { name: "", inbound_tag: "", total_gb: 0, expire_days: 0 },
        loading: false,
        search: "",

        async init() {
            await this.load();
            try { this.allTemplates = await api.listTemplates(); } catch (e) {}
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

        templateLabel(c) {
            if (!c.template_id) return "в­ђ Default";
            const t = this.allTemplates.find(x => x.id === c.template_id);
            return t ? t.label : `Template #${c.template_id}`;
        },

        async assignTemplate(c, tid) {
            try {
                await api.updateClient(c.id, { template_id: tid === 0 ? null : tid });
                this.selected = await api.client(c.id);
                this.$dispatch("toast", { msg: "Template updated", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
            this.showTmpl = false;
        },

        openTemplatePicker(c) {
            this.showTmpl = true;
        },

        async openSubUrl(c) {
            try {
                const data = await api.clientSubUrl(c.id);
                this.subUrls = { url: data.url, windows_zip: data.windows_zip };
                this.showSubUrl = true;
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async copyUrl(url) {
            try {
                await navigator.clipboard.writeText(url);
                this.$dispatch("toast", { msg: "Copied!", type: "success" });
            } catch {
                this.$dispatch("toast", { msg: "Copy failed", type: "error" });
            }
        },

        openTemplatePicker(c) {
            this.tmplClientId = c.id;
            this.showTmpl = true;
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

// в”Ђв”Ђв”Ђ Inbounds в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

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

// в”Ђв”Ђв”Ђ Routing в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

function routingComponent() {
    return {
        rules: {},
        selectedKey: "domain",
        // Note: geosite/geoip are Xray concepts — use rule_set (SRS URL) for geo-based filtering
        ruleKeys: ["domain", "domain_suffix", "domain_keyword", "ip_cidr", "rule_set"],
        showAdd: false,
        form: { rule_key: "domain", value: "", outbound: "proxy" },
        outbounds: ["proxy", "direct", "block", "dns"],
        loading: false,
        importing: false,

        async init() {
            await this.loadRules();
            try {
                const data = await api.routeOutbounds();
                this.outbounds = data.outbounds || this.outbounds;
            } catch (e) { /* keep defaults */ }
        },

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
            try {
                const data = await api.exportRules();
                const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url; a.download = "routing_rules.json"; a.click();
                URL.revokeObjectURL(url);
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async importRules(event) {
            const file = event.target.files[0];
            if (!file) return;
            this.importing = true;
            try {
                const text = await file.text();
                const data = JSON.parse(text);
                await api.importRules(data);
                this.rules = {};
                await this.loadRules();
                this.$dispatch("toast", { msg: "Rules imported", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally {
                this.importing = false;
                event.target.value = "";
            }
        },
    };
}

// в”Ђв”Ђв”Ђ AdGuard в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

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
        showPassword: false,

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

        async delUpstream(u) {
            if (!confirm(`Remove upstream: ${u}?`)) return;
            try {
                await api.delUpstream(u);
                await this.load();
                this.$dispatch("toast", { msg: "Upstream removed", type: "success" });
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

        async delFilterRule(r) {
            if (!confirm(`Remove rule: ${r}?`)) return;
            try {
                await api.delFilterRule(r);
                await this.load();
                this.$dispatch("toast", { msg: "Rule removed", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async changePassword() {
            if (!this.newPassword.trim()) return;
            try {
                await api.adguardPassword(this.newPassword.trim());
                this.newPassword = "";
                this.showPassword = false;
                this.$dispatch("toast", { msg: "AdGuard password changed", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async syncClients() {
            try {
                await api.syncClients();
                this.$dispatch("toast", { msg: "Clients synced to AdGuard", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },
    };
}

// в”Ђв”Ђв”Ђ Nginx в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

function nginxComponent() {
    return {
        status: null,
        paths: null,
        logs: "",
        loading: false,
        showSslModal: false,
        sslEmail: "",

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

        openSslModal() {
            this.sslEmail = "";
            this.showSslModal = true;
        },
        async issueSSL() {
            const email = (this.sslEmail || "").trim();
            if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
                this.$dispatch("toast", { msg: "Invalid email format", type: "error" });
                return;
            }
            this.showSslModal = false;
            this.loading = true;
            try {
                await api.nginxSsl(email || undefined);
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
            if (!confirm("Delete public page files for '/'?")) return;
            try {
                await api.nginxDeleteOverride();
                this.$dispatch("toast", { msg: "Public page files removed", type: "success" });
                await this.load();
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async toggleSite() {
            const current = this.status?.site_enabled ?? false;
            const next = !current;
            const label = next ? "enable" : "disable";
            if (!confirm(`${label.charAt(0).toUpperCase() + label.slice(1)} public page on '/'? Nginx will be reloaded.`)) return;
            this.loading = true;
            try {
                await api.nginxSiteToggle(next);
                this.$dispatch("toast", { msg: `Page ${next ? "enabled" : "disabled"}`, type: "success" });
                await this.load();
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },
    };
}

// в”Ђв”Ђв”Ђ Federation в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

function federationComponent() {
    return {
        nodes: [],
        topology: null,
        localSecret: null,
        showAdd: false,
        showLocalSecret: false,
        showBridge: false,
        bridgeSelected: [],    // ordered list of node IDs for the bridge chain
        bridgeResult: null,
        bridgeLoading: false,
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
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },

        async pingNode(n) {
            try {
                const r = await api.pingNode(n.id);
                this.$dispatch("toast", { msg: r.online ? `${n.name}: online` : `${n.name}: offline`, type: r.online ? "success" : "error" });
                await this.load();
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async loadTopology() {
            this.loading = true;
            try {
                this.topology = await api.topology();
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },

        async loadLocalSecret() {
            this.loading = true;
            try {
                this.localSecret = await api.fedLocalSecret();
                this.showLocalSecret = true;
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },

        async copyLocalSecret() {
            if (!this.localSecret?.secret) return;
            try {
                await navigator.clipboard.writeText(this.localSecret.secret);
                this.$dispatch("toast", { msg: "Federation secret copied", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message || "Copy failed", type: "error" });
            }
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

        // Bridge creation
        openBridge() {
            this.bridgeSelected = [];
            this.bridgeResult = null;
            this.showBridge = true;
        },

        toggleBridgeNode(id) {
            const idx = this.bridgeSelected.indexOf(id);
            if (idx >= 0) this.bridgeSelected.splice(idx, 1);
            else this.bridgeSelected.push(id);
        },

        bridgeChain() {
            const names = this.bridgeSelected.map(id => {
                const n = this.nodes.find(n => n.id === id);
                return n ? n.name : id;
            });
            return ['(this server)', ...names, 'Internet'].join(' в†’ ');
        },

        async createBridge() {
            if (!this.bridgeSelected.length) return;
            this.bridgeLoading = true;
            try {
                const r = await api.createBridge(this.bridgeSelected);
                this.bridgeResult = r;
                this.$dispatch("toast", { msg: "Bridge created!", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.bridgeLoading = false; }
        },
    };
}

// в”Ђв”Ђв”Ђ Admin в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

function adminComponent() {
    return {
        admins: [],
        auditLog: [],
        newAdminId: "",
        loading: false,
        showChangePass: false,
        passForm: { current: "", next: "" },

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

        async changePassword() {
            if (!this.passForm.current || !this.passForm.next) return;
            try {
                await api.changePassword(this.passForm.current, this.passForm.next);
                this.passForm = { current: "", next: "" };
                this.showChangePass = false;
                this.$dispatch("toast", { msg: "Web password changed", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },
    };
}

// в”Ђв”Ђв”Ђ Settings в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

function settingsComponent() {
    return {
        s: { tz: "", bot_lang: "", domain: "", ssh_port: "22" },
        domainInput: "",
        domainNote: "",
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
                this.domainInput = this.s.domain || "";
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },

        async save(key, value) {
            if (value === undefined || value === null) return;
            if (key === "ssh_port") {
                const p = parseInt(String(value).trim(), 10);
                if (isNaN(p) || p < 1 || p > 65535) {
                    this.$dispatch("toast", { msg: "SSH port must be 1-65535", type: "error" });
                    return;
                }
                value = String(p);
            }
            this.saving = key;
            try {
                const r = await api.settingsSet(key, value);
                this.s[key] = r.value;
                this.$dispatch("toast", { msg: `${key} в†’ ${r.value}`, type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.saving = null; }
        },

        async saveDomain() {
            const d = this.domainInput.trim().replace(/^https?:\/\//,"").replace(/\/$/,"");
            if (!d) return;
            this.saving = "domain";
            this.domainNote = "";
            try {
                const r = await api.settingsSet("domain", d);
                this.s.domain = r.value;
                this.domainInput = r.value;
                this.domainNote = r.note || "Nginx reloaded.";
                this.$dispatch("toast", { msg: `Domain в†’ ${r.value}`, type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.saving = null; }
        },
    };
}

// в”Ђв”Ђв”Ђ Docs в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

function docsComponent() {
    return {
        docs: [],
        activeId: null,
        activeTitle: "",
        content: "",
        loading: false,
        loadingDoc: false,
        lang: "ru",
        markdownRenderer: null,

        async init() {
            // Language is set during /start wizard and stored in app_settings (DB)
            const s = await api.settingsAll();
            this.lang = s.bot_lang || "ru";

            this.loading = true;
            try {
                this.docs = await api.docsList(this.lang);
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
                this.content = await api.docGet(doc.id, this.lang);
            } catch (e) {
                this.content = `Error: ${e.message}`;
            } finally {
                this.loadingDoc = false;
            }
        },

        escapeHtml(text) {
            return String(text || "")
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;");
        },

        getRenderer() {
            if (this.markdownRenderer || typeof marked === "undefined") {
                return this.markdownRenderer;
            }
            const renderer = new marked.Renderer();

            const baseLink = renderer.link.bind(renderer);
            renderer.link = function (...args) {
                let html = baseLink(...args);
                if (!/\btarget=/.test(html)) {
                    html = html.replace(
                        "<a ",
                        '<a target="_blank" rel="noopener noreferrer" '
                    );
                }
                return html;
            };

            // Keep raw HTML from docs as plain text.
            renderer.html = (rawHtml) => {
                if (rawHtml && typeof rawHtml === "object" && "text" in rawHtml) {
                    return this.escapeHtml(rawHtml.text);
                }
                return this.escapeHtml(rawHtml);
            };
            this.markdownRenderer = renderer;
            return renderer;
        },

        // Render markdown to HTML using marked (loaded from CDN)
        rendered() {
            if (!this.content) return "";
            const renderer = this.getRenderer();
            if (renderer && typeof marked !== "undefined") {
                return marked.parse(this.content, {
                    renderer,
                    gfm: true,
                    breaks: true,
                    mangle: false,
                    headerIds: false,
                });
            }
            return `<pre style="white-space:pre-wrap;word-break:break-word">${this.escapeHtml(this.content)}</pre>`;
        },
    };
}

// в”Ђв”Ђв”Ђ Maintenance component в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

function maintenanceComponent() {
    return {
        status: null,
        logs: [],
        banned: [],
        suspicious: [],
        newIp: "",
        newReason: "manual",
        restoreFile: null,
        restoreCreateBackup: true,
        tab: "backup",   // backup | logs | ipban | windows | updates
        loading: false,
        msg: "",
        winStatus: null,
        winLoading: false,
        updateInfo: null,
        updateJob: null,
        updateLogs: "",
        updateBranch: "",
        updateLoading: false,

        get winReady() { return this.winStatus?.ready === true; },
        get updateRunning() { return this.updateJob?.running === true; },
        get updateActionLabel() {
            const action = String(this.updateJob?.action || "update").toLowerCase();
            const mode = String(this.updateJob?.mode || "preserve").toLowerCase();
            if (action !== "reinstall") return "Update";
            return mode === "clean" ? "Clean reinstall" : "Reinstall (keep data)";
        },
        get updateStatusLabel() {
            if (!this.updateJob) return "idle";
            const status = this.updateJob.status || (this.updateJob.running ? "running" : "idle");
            const exit = this.updateJob.exit_code;
            if (exit === null || exit === undefined) return status;
            return `${status} (exit: ${exit})`;
        },
        get updateHasUpdates() {
            return Boolean(this.updateInfo?.update_available_branch) || Boolean(this.updateInfo?.update_available_tag);
        },
        get updateTargetVersion() {
            return this.updateInfo?.latest_tag || this.updateInfo?.remote_branch_commit || "latest";
        },
        get suggestedBranch() {
            return this.updateInfo?.current_branch || "main";
        },

        async init() {
            await this.loadStatus();
        },

        async checkWinBinaries() {
            try { this.winStatus = await api.windowsBinariesStatus(); } catch(e) {}
        },

        async prefetchWin() {
            this.winLoading = true;
            try {
                await api.prefetchWindowsBinaries();
                this.winStatus = await api.windowsBinariesStatus();
                this.$dispatch("toast", { msg: "Binaries downloaded!", type: "success" });
            } catch(e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.winLoading = false; }
        },

        async loadStatus() {
            try {
                this.status = await api.maintStatus();
                this.logs = this.status?.logs?.files || [];
            } catch (e) {
                this.msg = "Error: " + e.message;
            }
        },

        async loadUpdateInfo(loadLogs = true) {
            this.updateLoading = true;
            try {
                const data = await api.maintUpdateInfo();
                this.updateInfo = data?.git || null;
                this.updateJob = data?.job || null;
                if (!this.updateBranch) {
                    this.updateBranch = this.updateInfo?.current_branch || "";
                }
                if (loadLogs) {
                    await this.loadUpdateLogs(false);
                }
            } catch (e) {
                this.msg = e.message;
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally {
                this.updateLoading = false;
            }
        },

        async loadUpdateLogs(showErrors = true) {
            try {
                const data = await api.maintUpdateLogs(220);
                this.updateJob = data || this.updateJob;
                this.updateLogs = (data?.logs || "").trim();
            } catch (e) {
                if (showErrors) {
                    this.msg = e.message;
                    this.$dispatch("toast", { msg: e.message, type: "error" });
                }
            }
        },

        async runUpdate(branchOverride = null) {
            if (this.updateRunning) {
                this.$dispatch("toast", { msg: "Another maintenance job is already running", type: "error" });
                return;
            }
            if (!this.updateHasUpdates) {
                this.$dispatch("toast", { msg: "No updates detected", type: "error" });
                return;
            }

            const branch = (branchOverride ?? this.updateBranch ?? this.suggestedBranch ?? "").trim();
            const targetBranch = branch || this.suggestedBranch;
            if (!confirm(`Run update for branch '${targetBranch}'?`)) return;

            this.updateLoading = true;
            try {
                const result = await api.maintUpdateRun(targetBranch || null);
                this.msg = `✅ Update started for branch: ${result.branch || targetBranch}`;
                this.$dispatch("toast", { msg: "Update started", type: "success" });
                await this.loadUpdateInfo(true);
            } catch (e) {
                this.msg = e.message;
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally {
                this.updateLoading = false;
            }
        },

        async runReinstall(mode = "preserve") {
            if (this.updateRunning) {
                this.$dispatch("toast", { msg: "Another maintenance job is already running", type: "error" });
                return;
            }

            const clean = mode === "clean";
            const question = clean
                ? "Run clean reinstall now? This will reset settings and data."
                : "Reinstall containers now? Settings and data will be preserved.";
            if (!confirm(question)) return;

            this.updateLoading = true;
            try {
                await api.maintReinstallRun(clean);
                this.msg = clean
                    ? "✅ Clean reinstall started. Settings and data will be reset."
                    : "✅ Reinstall started. Settings and data are preserved.";
                this.$dispatch("toast", {
                    msg: clean
                        ? "Clean reinstall started. Bot/Web can be unavailable for up to a minute."
                        : "Reinstall started. Bot/Web can be unavailable for up to a minute.",
                    type: "success",
                });
                await this.loadUpdateInfo(true);
            } catch (e) {
                this.msg = e.message;
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally {
                this.updateLoading = false;
            }
        },

        async cleanupUpdateJob() {
            if (this.updateRunning) {
                this.$dispatch("toast", { msg: "Job is still running", type: "error" });
                return;
            }
            try {
                await api.maintUpdateCleanup();
                await this.loadUpdateInfo(false);
                this.updateLogs = "";
                this.msg = "✅ Maintenance job state cleaned";
            } catch (e) {
                this.msg = e.message;
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async setBackupHours(h) {
            try { await api.maintSetBackupHours(parseInt(h)); await this.loadStatus(); }
            catch(e) { this.msg = e.message; }
        },

        async downloadBackup() {
            this.loading = true;
            try { await api.maintBackupDownload(); }
            catch(e) { this.msg = e.message; }
            finally { this.loading = false; }
        },

        async runBackup() {
            this.loading = true;
            try { await api.maintRunBackup(); this.msg = "✅ Backup sent to admins"; }
            catch(e) { this.msg = e.message; }
            finally { this.loading = false; }
        },

        pickRestoreFile(event) {
            this.restoreFile = event.target.files?.[0] || null;
        },

        async startRestore() {
            if (!this.restoreFile) {
                this.msg = "Select a recovery ZIP first";
                return;
            }
            if (!confirm("Restore from this ZIP? The stack will restart and the panel may disconnect for up to a minute.")) return;

            this.loading = true;
            try {
                const result = await api.maintRestore(this.restoreFile, this.restoreCreateBackup);
                this.msg = "✅ Restore started. Wait 30-60 seconds, then reconnect.";
                this.$dispatch("toast", { msg: result.message || "Restore started", type: "success" });
                this.restoreFile = null;
                if (this.$refs.restoreZipInput) this.$refs.restoreZipInput.value = "";
            } catch(e) {
                this.msg = e.message;
                this.$dispatch("toast", { msg: e.message, type: "error" });
            } finally { this.loading = false; }
        },

        async setCleanHours(h) {
            try { await api.maintSetCleanHours(parseInt(h)); await this.loadStatus(); }
            catch(e) { this.msg = e.message; }
        },

        async downloadLog(name) {
            try { await api.maintLogDownload(name); }
            catch(e) { this.msg = e.message; }
        },

        async clearLog(name) {
            try {
                await api.maintLogClearOne(name);
                await this.loadStatus();
                this.msg = `✅ ${name} cleared`;
            } catch(e) { this.msg = e.message; }
        },

        async clearAllLogs() {
            if (!confirm("Clear all log files?")) return;
            try {
                const r = await api.maintLogClearAll();
                this.msg = `✅ Cleared: ${r.cleared.join(", ")}`;
                await this.loadStatus();
            } catch(e) { this.msg = e.message; }
        },

        async loadBanned() {
            try { const d = await api.maintIpBanList(); this.banned = d.banned || []; }
            catch(e) { this.msg = e.message; }
        },

        async addBan() {
            if (!this.newIp.trim()) return;
            try {
                await api.maintIpBanAdd(this.newIp.trim(), this.newReason || "manual");
                this.newIp = "";
                await this.loadBanned();
                this.msg = "✅ IP banned";
            } catch(e) { this.msg = e.message; }
        },

        async unban(ip) {
            try {
                await api.maintIpBanRemove(ip);
                await this.loadBanned();
                this.msg = `✅ ${ip} unbanned`;
            } catch(e) { this.msg = e.message; }
        },

        async analyze() {
            this.loading = true;
            try { const d = await api.maintIpBanAnalyze(); this.suspicious = d.suspicious || []; }
            catch(e) { this.msg = e.message; }
            finally { this.loading = false; }
        },

        async banAll() {
            if (!this.suspicious.length) return;
            try {
                const r = await api.maintIpBanAll();
                this.msg = `✅ Banned ${r.banned} IPs`;
                this.suspicious = [];
                await this.loadBanned();
            } catch(e) { this.msg = e.message; }
        },

        async clearAutoBans() {
            if (!confirm("Remove all auto-added bans?")) return;
            try {
                const r = await api.maintIpBanClearAuto();
                this.msg = `✅ Removed ${r.removed} auto-bans`;
                await this.loadBanned();
            } catch(e) { this.msg = e.message; }
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
    Alpine.data("docsSection",         docsComponent);
    Alpine.data("settingsSection",     settingsComponent);
    Alpine.data("maintenanceSection",  maintenanceComponent);
    Alpine.data("templatesSection",    templatesComponent);
});

function templatesComponent() {
    return {
        templates: [],
        presets: [],
        selected: null,
        showCreate: false,
        showEdit: false,
        showPresets: false,
        form: { name: "", label: "", config_json: "" },
        editForm: { label: "", config_json: "" },
        loading: false,

        async init() {
            await this.load();
            try { this.presets = await api.listPresets(); } catch (e) {}
        },

        async load() {
            this.loading = true;
            try { this.templates = await api.listTemplates(); }
            finally { this.loading = false; }
        },

        isInstalled(presetName) {
            return this.templates.some(t => t.name === presetName);
        },

        async installPreset(preset) {
            try {
                await api.installPreset(preset.name);
                await this.load();
                this.$dispatch("toast", { msg: `Preset '${preset.label}' installed`, type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async select(t) {
            this.selected = await api.getTemplate(t.id);
            this.editForm = { label: this.selected.label, config_json: JSON.stringify(JSON.parse(this.selected.config_json), null, 2) };
            this.showEdit = true;
        },

        async create() {
            try {
                // Compact JSON before sending
                const cfg = JSON.parse(this.form.config_json);
                await api.createTemplate({ ...this.form, config_json: JSON.stringify(cfg) });
                this.showCreate = false;
                this.form = { name: "", label: "", config_json: "" };
                await this.load();
                this.$dispatch("toast", { msg: "Template created", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async save() {
            try {
                const cfg = JSON.parse(this.editForm.config_json);
                await api.updateTemplate(this.selected.id, { label: this.editForm.label, config_json: JSON.stringify(cfg) });
                this.showEdit = false;
                await this.load();
                this.$dispatch("toast", { msg: "Template saved", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async setDefault(t) {
            try {
                await api.setDefaultTmpl(t.id);
                await this.load();
                this.$dispatch("toast", { msg: `'${t.label}' is now default`, type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        async remove(t) {
            if (!confirm(`Delete template '${t.label}'?`)) return;
            try {
                await api.deleteTemplate(t.id);
                this.showEdit = false;
                await this.load();
                this.$dispatch("toast", { msg: "Deleted", type: "success" });
            } catch (e) {
                this.$dispatch("toast", { msg: e.message, type: "error" });
            }
        },

        downloadJson(t) {
            const blob = new Blob([JSON.stringify(JSON.parse(t.config_json), null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a"); a.href = url; a.download = `${t.name}.json`; a.click();
            URL.revokeObjectURL(url);
        },
    };
}


