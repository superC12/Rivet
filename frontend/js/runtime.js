const ICONS = {
  auto: '<svg viewBox="0 0 18 18" aria-hidden="true"><circle cx="4" cy="9" r="2"/><circle cx="14" cy="4" r="2"/><circle cx="14" cy="14" r="2"/><path d="M6 9h3m0 0 3.5-4M9 9l3.5 4"/></svg>',
  local: '<svg viewBox="0 0 18 18" aria-hidden="true"><rect x="2.5" y="3.5" width="13" height="11" rx="2"/><path d="m5.5 7 2 2-2 2M9 11h3.5"/></svg>',
  cloud: '<svg viewBox="0 0 18 18" aria-hidden="true"><path d="M5.2 14h8a3 3 0 0 0 .4-6A4.6 4.6 0 0 0 5 6.7 3.7 3.7 0 0 0 5.2 14Z"/></svg>',
  api: '<svg viewBox="0 0 18 18" aria-hidden="true"><path d="m6.5 4-4 5 4 5M11.5 4l4 5-4 5M10 3 8 15"/></svg>',
  action: '<svg viewBox="0 0 18 18" aria-hidden="true"><path d="M9 2.5v4m0 5v4M2.5 9h4m5 0h4M4.4 4.4l2.8 2.8m3.6 3.6 2.8 2.8m0-9.2-2.8 2.8m-3.6 3.6-2.8 2.8"/></svg>',
  model: '<svg viewBox="0 0 18 18" aria-hidden="true"><path d="m9 2.5 5.5 3.2v6.6L9 15.5l-5.5-3.2V5.7L9 2.5Z"/><path d="m3.7 5.9 5.3 3 5.3-3M9 9v6"/></svg>',
  link: '<svg viewBox="0 0 18 18" aria-hidden="true"><path d="M9 3v12M3 9h12"/></svg>',
};

function icon(kind) { return ICONS[kind] || ICONS.model; }
function providerKind(provider) {
  if (provider.type === "openrouter") return "cloud";
  if (provider.type === "ollama" || provider.node) return "local";
  return "api";
}
function providerLabel(provider) {
  return { ollama: "Local LLM", openrouter: "Cloud", openai_compatible: "API" }[provider.type] || provider.id;
}
function create(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = text;
  return element;
}

export class RouteControl {
  constructor({ select, trigger, menu, onLinkProvider }) {
    this.select = select;
    this.trigger = trigger;
    this.menu = menu;
    this.onLinkProvider = onLinkProvider;
    this.entries = [];
    this.models = [];
    this.providers = [];
    trigger.addEventListener("click", event => { event.stopPropagation(); this.toggle(); });
    menu.addEventListener("click", event => {
      const choice = event.target.closest("[data-route-value]");
      if (choice) this.choose(choice.dataset.routeValue);
      const link = event.target.closest("[data-link-provider]");
      if (link) { this.close(); this.onLinkProvider(); }
    });
    document.addEventListener("click", event => { if (!event.target.closest("#route-control")) this.close(); });
    document.addEventListener("keydown", event => { if (event.key === "Escape") this.close(); });
  }

  configure(models = [], providers = []) {
    const previous = this.select.value;
    this.providers = providers;
    const active = providers.filter(provider => provider.status === "online");
    const activeIds = new Set(active.map(provider => provider.id));
    this.models = models.filter(model => activeIds.has(model.provider));
    const local = active.some(provider => providerKind(provider) === "local");
    const cloud = active.some(provider => providerKind(provider) === "cloud");
    const entries = [];
    if (active.length) entries.push({ value: "auto", label: "Auto route", detail: `${active.length} active ${active.length === 1 ? "provider" : "providers"}`, kind: "auto" });
    if (local) entries.push({ value: "local_only", label: "Local only", detail: "Keep prompt content on local compute", kind: "local" });
    if (cloud) entries.push({ value: "cloud", label: "Cloud", detail: "Use an authenticated cloud route", kind: "cloud" });
    this.models.forEach(model => {
      const provider = active.find(item => item.id === model.provider);
      entries.push({ value: `model:${model.provider}:${model.id}`, label: model.name, detail: providerLabel(provider || { id: model.provider }), kind: provider ? providerKind(provider) : "model" });
    });
    this.entries = entries;
    const selected = entries.some(entry => entry.value === previous) ? previous : entries[0]?.value || "auto";
    this.select.replaceChildren(...entries.map(entry => {
      const option = create("option", "", entry.label);
      option.value = entry.value;
      return option;
    }));
    if (!entries.length) {
      const option = create("option", "", "Link provider");
      option.value = "auto";
      this.select.append(option);
    }
    this.select.value = selected;
    this.renderMenu();
    this.renderTrigger();
    document.querySelector("#composer-shortcut").hidden = !entries.length;
  }

  selection() {
    const value = this.select.value || "auto";
    if (!value.startsWith("model:")) return { mode: value, model: null };
    return { mode: "auto", model: value.slice("model:".length) };
  }

  choose(value) {
    if (!this.entries.some(entry => entry.value === value)) return;
    this.select.value = value;
    this.renderMenu();
    this.renderTrigger();
    this.close();
  }

  chooseProvider(providerId) {
    const model = this.models.find(item => item.provider === providerId);
    if (model) return this.choose(`model:${model.provider}:${model.id}`);
    const provider = this.providers.find(item => item.id === providerId);
    if (provider) this.choose(providerKind(provider) === "cloud" ? "cloud" : "local_only");
  }

  renderTrigger() {
    const selected = this.entries.find(entry => entry.value === this.select.value);
    const iconTarget = document.querySelector("#route-icon");
    iconTarget.innerHTML = icon(selected?.kind || "auto");
    this.trigger.classList.toggle("unavailable", !selected);
    this.trigger.setAttribute("aria-label", selected ? `Route: ${selected.label}` : "Link an execution provider");
    this.trigger.dataset.tooltip = selected
      ? `${selected.label}. Click to choose from active execution targets.`
      : "No active execution provider. Click to open Connections.";
  }

  renderMenu() {
    this.menu.replaceChildren();
    if (this.entries.length) {
      const heading = create("p", "route-menu-heading", "EXECUTION TARGET");
      this.menu.append(heading);
      this.entries.forEach(entry => {
        const button = create("button", "route-menu-item");
        button.type = "button";
        button.setAttribute("role", "menuitemradio");
        button.setAttribute("aria-checked", String(entry.value === this.select.value));
        button.dataset.routeValue = entry.value;
        const symbol = create("span", "route-menu-icon");
        symbol.innerHTML = icon(entry.kind);
        const copy = create("span", "route-menu-copy");
        copy.append(create("strong", "", entry.label), create("small", "", entry.detail));
        const check = create("span", "route-menu-check", entry.value === this.select.value ? "✓" : "");
        button.append(symbol, copy, check);
        this.menu.append(button);
      });
    } else {
      this.menu.append(create("p", "route-menu-empty", "No configured provider is currently reachable."));
    }
    const link = create("button", "route-link-provider");
    link.type = "button";
    link.dataset.linkProvider = "true";
    const symbol = create("span", "route-menu-icon");
    symbol.innerHTML = icon("link");
    link.append(symbol, create("span", "", "Add manual connection"));
    this.menu.append(link);
  }

  toggle() { this.menu.hidden ? this.open() : this.close(); }
  open() { this.menu.hidden = false; this.trigger.setAttribute("aria-expanded", "true"); }
  close() { this.menu.hidden = true; this.trigger.setAttribute("aria-expanded", "false"); }
}

export class RuntimeDashboard {
  constructor({ api, routeControl, onOpenSettings, onPrompt, atmosphere }) {
    this.api = api;
    this.routeControl = routeControl;
    this.onOpenSettings = onOpenSettings;
    this.onPrompt = onPrompt;
    this.atmosphere = atmosphere;
    this.config = null;
    this.data = null;
    this.button = document.querySelector("#connection-status");
    this.popover = document.querySelector("#connection-popover");
    document.querySelector("#open-compute-overview").addEventListener("click", () => this.onOpenSettings("compute"));
    this.button.addEventListener("click", event => { event.stopPropagation(); this.popover.hidden ? this.openDiagnostics() : this.closeDiagnostics(); });
    document.querySelector("#refresh-diagnostics").addEventListener("click", event => { event.stopPropagation(); this.refresh(this.config); });
    document.addEventListener("click", event => { if (!event.target.closest(".header-status")) this.closeDiagnostics(); });
    document.addEventListener("keydown", event => { if (event.key === "Escape") this.closeDiagnostics(); });
  }

  async refresh(config = this.config) {
    this.config = config;
    try {
      const pingStarted = performance.now();
      const ping = this.api("/health").then(() => Math.round(performance.now() - pingStarted));
      const [status, models, roundTrip] = await Promise.all([this.api("/api/status"), this.api("/api/models"), ping]);
      this.data = { status, models, roundTrip };
      this.routeControl.configure(models, status.providers || []);
      this.renderMatrix();
      this.renderDiagnostics();
      this.setConnection(status.status === "ok" ? "Connected" : "Degraded", status.status === "ok");
      if (status.status !== "ok") this.atmosphere.setState("warning");
    } catch (error) {
      this.data = null;
      this.routeControl.configure([], []);
      this.renderUnavailable(error);
      this.setConnection("Offline", false);
      this.atmosphere.setState("error");
    }
  }

  setConnection(label, online) {
    document.querySelector("#connection-label").textContent = label;
    document.querySelector("#connection-dot").classList.toggle("online", online);
    this.button.setAttribute("aria-label", `${label}. Open connection diagnostics`);
  }

  renderMatrix() {
    const { status, roundTrip } = this.data;
    const providers = status.providers || [];
    const active = providers.filter(provider => provider.status === "online");
    const n8n = this.config?.actions?.n8n || {};
    const matrixSummary = active.length
      ? `${active.length} active ${active.length === 1 ? "engine" : "engines"} · ${roundTrip} ms control path`
      : `Control path ready · ${roundTrip} ms · compute unavailable`;
    document.querySelector("#matrix-summary").textContent = matrixSummary;
    document.querySelector("#canvas-summary").textContent = active.length
      ? `${active.length} ${active.length === 1 ? "engine" : "engines"} online · auto route ready`
      : "No compute online · link a provider";
    const matrix = document.querySelector("#execution-matrix");
    matrix.replaceChildren();
    const router = this.matrixNode({ label: "Rivet Router", detail: status.router?.strategy || "auto", status: active.length ? "ready" : "waiting", kind: "auto", primary: true });
    router.addEventListener("click", () => active.length ? this.routeControl.choose("auto") : this.onOpenSettings("connections"));
    const engines = create("div", "matrix-engines");
    engines.append(this.matrixNode({ label: "Rivet API", detail: `${roundTrip} ms`, status: "online", kind: "api" }));
    providers.forEach(provider => {
      const node = this.matrixNode({
        label: providerLabel(provider),
        detail: `${provider.id} · ${provider.latency_ms} ms`,
        status: provider.status,
        kind: providerKind(provider),
      });
      node.addEventListener("click", () => provider.status === "online" ? this.routeControl.chooseProvider(provider.id) : this.onOpenSettings("connections"));
      engines.append(node);
    });
    const actionReady = Boolean(n8n.enabled && n8n.configured);
    const actionNode = this.matrixNode({ label: "n8n Actions", detail: actionReady ? "gateway linked" : "link in Connections", status: actionReady ? "online" : "unlinked", kind: "action" });
    actionNode.addEventListener("click", () => actionReady ? this.prime("Deploy n8n workflow") : this.onOpenSettings("connections"));
    engines.append(actionNode);
    matrix.append(router, engines);
    this.renderTriggers(active, actionReady);
  }

  matrixNode({ label, detail, status, kind, primary = false }) {
    const button = create("button", `matrix-node${primary ? " matrix-router" : ""} status-${status}`);
    button.type = "button";
    const symbol = create("span", "matrix-node-icon");
    symbol.innerHTML = icon(kind);
    const copy = create("span", "matrix-node-copy");
    copy.append(create("strong", "", label), create("small", "", detail));
    const state = create("span", "matrix-node-state", status);
    button.append(symbol, copy, state);
    return button;
  }

  renderTriggers(active, actionReady) {
    const triggers = [];
    if (active.some(provider => providerKind(provider) === "local")) triggers.push(["⌁", "Analyze local repo architecture"]);
    if (actionReady) triggers.push(["↗", "Deploy n8n workflow"]);
    triggers.push(["{ }", "Trace API payload"]);
    if (active.some(provider => providerKind(provider) === "cloud")) triggers.push(["☁", "Compare model route latency"]);
    if (triggers.length < 3) triggers.push(["◇", "Inspect configured execution routes"]);
    const container = document.querySelector("#action-triggers");
    container.replaceChildren(create("span", "trigger-label", "QUICK TRIGGERS"));
    triggers.slice(0, 3).forEach(([glyph, prompt]) => {
      const button = create("button", "action-trigger");
      button.type = "button";
      button.append(create("i", "", glyph), create("span", "", prompt));
      button.addEventListener("click", () => this.prime(prompt));
      container.append(button);
    });
  }

  prime(prompt) { this.onPrompt(prompt); }

  renderDiagnostics() {
    if (!this.data) return;
    const { status, roundTrip } = this.data;
    const list = document.querySelector("#diagnostic-list");
    list.replaceChildren();
    this.diagnosticRow(list, "Rivet endpoint", status.status, `${roundTrip} ms`);
    this.diagnosticRow(list, "Stream channel", "ready", "HTTP/SSE");
    this.diagnosticRow(list, "Router", status.router?.status || "unknown", status.router?.strategy || "auto");
    this.diagnosticRow(list, "Database", status.database?.status || "unknown", "local");
    (status.providers || []).forEach(provider => this.diagnosticRow(list, providerLabel(provider), provider.status, `${provider.latency_ms} ms`));
  }

  diagnosticRow(container, label, status, value) {
    const row = create("div", "diagnostic-row");
    const name = create("span", "diagnostic-name");
    name.append(create("i", status === "ok" || status === "online" || status === "ready" ? "online" : ""), create("span", "", label));
    const reading = create("span", "diagnostic-reading");
    reading.append(create("strong", "", status), create("small", "", value));
    row.append(name, reading);
    container.append(row);
  }

  renderUnavailable(error) {
    document.querySelector("#matrix-summary").textContent = "Rivet runtime unavailable";
    document.querySelector("#canvas-summary").textContent = "Control path unavailable · open Compute";
    const matrix = document.querySelector("#execution-matrix");
    matrix.replaceChildren(this.matrixNode({ label: "Connection lost", detail: error.message, status: "offline", kind: "api", primary: true }));
    document.querySelector("#action-triggers").replaceChildren();
    const list = document.querySelector("#diagnostic-list");
    list.replaceChildren();
    this.diagnosticRow(list, "Rivet endpoint", "offline", "no response");
  }

  async openDiagnostics() {
    this.popover.hidden = false;
    this.button.setAttribute("aria-expanded", "true");
    await this.refresh(this.config);
  }

  closeDiagnostics() { this.popover.hidden = true; this.button.setAttribute("aria-expanded", "false"); }
}
