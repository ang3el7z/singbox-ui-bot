(function () {
  "use strict";

  const ui = {
    docsNav: document.getElementById("docsNav"),
    article: document.getElementById("article"),
    tocNav: document.getElementById("tocNav"),
    sidebar: document.getElementById("sidebar"),
    menuToggle: document.getElementById("menuToggle"),
    langToggle: document.getElementById("langToggle"),
    sidebarTitle: document.getElementById("sidebarTitle"),
    tocTitle: document.getElementById("tocTitle"),
    subtitle: document.getElementById("subtitle"),
  };

  const i18n = {
    ru: {
      sections: "\u0420\u0430\u0437\u0434\u0435\u043b\u044b",
      onPage: "\u041d\u0430 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0435",
      subtitle: "\u0410\u043a\u043a\u0443\u0440\u0430\u0442\u043d\u0430\u044f \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430\u0446\u0438\u044f \u0434\u043b\u044f \u0435\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u043e\u0439 \u0440\u0430\u0431\u043e\u0442\u044b",
      loading: "\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430\u0446\u0438\u0438...",
      empty: "\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442 \u043f\u043e\u043a\u0430 \u043f\u0443\u0441\u0442",
      fail: "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430\u0446\u0438\u044e",
    },
    en: {
      sections: "Sections",
      onPage: "On this page",
      subtitle: "Structured reference for daily operations",
      loading: "Loading documentation...",
      empty: "Document is empty",
      fail: "Failed to load documentation",
    },
  };

  const params = new URLSearchParams(window.location.search);
  const state = {
    lang: params.get("lang") === "en" ? "en" : "ru",
    docs: [],
    activeId: params.get("doc") || "overview",
  };

  function t(key) {
    return i18n[state.lang][key] || key;
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function slugify(text, seen) {
    const base = String(text || "")
      .toLowerCase()
      .replace(/[^\w\u0400-\u04FF-]+/g, "-")
      .replace(/--+/g, "-")
      .replace(/^-|-$/g, "") || "section";
    let slug = base;
    let index = 2;
    while (seen.has(slug)) {
      slug = `${base}-${index}`;
      index += 1;
    }
    seen.add(slug);
    return slug;
  }

  function withDocParam(docId) {
    const q = new URLSearchParams(window.location.search);
    q.set("lang", state.lang);
    q.set("doc", docId);
    return `${window.location.pathname}?${q.toString()}`;
  }

  async function apiGet(path) {
    const res = await fetch(path, { headers: { Accept: "application/json, text/plain" } });
    if (!res.ok) {
      throw new Error(`${res.status} ${res.statusText}`);
    }
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      return res.json();
    }
    return res.text();
  }

  function renderNav() {
    ui.docsNav.innerHTML = "";
    state.docs.forEach((doc) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `doc-link${doc.id === state.activeId ? " active" : ""}`;
      btn.textContent = doc.title;
      btn.addEventListener("click", async () => {
        state.activeId = doc.id;
        renderNav();
        await loadDoc(doc.id);
        history.replaceState(null, "", withDocParam(doc.id));
        ui.sidebar.classList.remove("open");
      });
      ui.docsNav.appendChild(btn);
    });
  }

  function renderToc() {
    ui.tocNav.innerHTML = "";
    const headings = Array.from(ui.article.querySelectorAll("h2, h3"));
    if (!headings.length) {
      return;
    }
    headings.forEach((heading) => {
      const a = document.createElement("a");
      a.className = `toc-link level-${heading.tagName === "H3" ? "3" : "2"}`;
      a.href = `#${heading.id}`;
      a.textContent = heading.textContent || "";
      ui.tocNav.appendChild(a);
    });
  }

  function markdownToHtml(source) {
    if (typeof marked === "undefined") {
      return `<pre>${escapeHtml(source)}</pre>`;
    }

    const renderer = new marked.Renderer();
    const baseLink = renderer.link ? renderer.link.bind(renderer) : null;

    renderer.link = function (...args) {
      const html = baseLink ? baseLink(...args) : "";
      if (!html.includes("target=")) {
        return html.replace("<a ", '<a target="_blank" rel="noopener noreferrer" ');
      }
      return html;
    };

    renderer.html = function (...args) {
      const token = args[0];
      if (token && typeof token === "object" && "text" in token) {
        return escapeHtml(token.text || "");
      }
      return escapeHtml(token);
    };

    return marked.parse(source, {
      renderer,
      gfm: true,
      breaks: false,
      mangle: false,
      headerIds: false,
    });
  }

  async function loadDoc(docId) {
    ui.article.innerHTML = `<p class="state">${escapeHtml(t("loading"))}</p>`;
    ui.tocNav.innerHTML = "";
    try {
      const source = await apiGet(`/api/docs/public/${encodeURIComponent(docId)}?lang=${state.lang}`);
      if (!String(source || "").trim()) {
        ui.article.innerHTML = `<p class="state">${escapeHtml(t("empty"))}</p>`;
        return;
      }
      ui.article.innerHTML = markdownToHtml(source);

      const seen = new Set();
      ui.article.querySelectorAll("h1, h2, h3").forEach((heading) => {
        const id = slugify(heading.textContent || "", seen);
        heading.id = id;
      });
      renderToc();
    } catch (err) {
      const msg = err && err.message ? err.message : "Error";
      ui.article.innerHTML = `<p class="state">${escapeHtml(t("fail"))}: ${escapeHtml(msg)}</p>`;
    }
  }

  async function loadList() {
    state.docs = await apiGet(`/api/docs/public?lang=${state.lang}`);
    if (!state.docs.some((d) => d.id === state.activeId)) {
      state.activeId = state.docs[0]?.id || "overview";
    }
    renderNav();
    await loadDoc(state.activeId);
  }

  function applyUiLocale() {
    document.documentElement.lang = state.lang;
    ui.sidebarTitle.textContent = t("sections");
    ui.tocTitle.textContent = t("onPage");
    ui.subtitle.textContent = t("subtitle");
  }

  async function toggleLang() {
    state.lang = state.lang === "ru" ? "en" : "ru";
    applyUiLocale();
    await loadList();
    history.replaceState(null, "", withDocParam(state.activeId));
  }

  function bindUi() {
    ui.langToggle.addEventListener("click", toggleLang);
    ui.menuToggle.addEventListener("click", () => {
      ui.sidebar.classList.toggle("open");
    });
    document.addEventListener("click", (event) => {
      if (!ui.sidebar.classList.contains("open")) return;
      const insideSidebar = ui.sidebar.contains(event.target);
      const isToggle = ui.menuToggle.contains(event.target);
      if (!insideSidebar && !isToggle) {
        ui.sidebar.classList.remove("open");
      }
    });
  }

  async function init() {
    applyUiLocale();
    bindUi();
    try {
      await loadList();
    } catch (err) {
      const msg = err && err.message ? err.message : "Error";
      ui.article.innerHTML = `<p class="state">${escapeHtml(t("fail"))}: ${escapeHtml(msg)}</p>`;
    }
  }

  init();
})();