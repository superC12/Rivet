import { BenchmarksPanel } from "./benchmarks.js";

function clampChannel(value) { return Math.min(255, Math.max(0, Number.parseInt(value, 10) || 0)); }

function hexToRgb(color) {
  const value = color.replace("#", "");
  return [0, 2, 4].map(index => Number.parseInt(value.slice(index, index + 2), 16));
}

function rgbToHex(channels) {
  return `#${channels.map(value => clampChannel(value).toString(16).padStart(2, "0")).join("")}`;
}

export class SettingsPanel {
  constructor({ api, onSave }) {
    this.api = api;
    this.onSave = onSave;
    this.dialog = document.querySelector("#settings-dialog");
    this.config = null;
    this.benchmarks = new BenchmarksPanel({ api, onEmptied: () => this.setBenchmarksVisible(false) });
    document.querySelector("#settings-show-benchmarks").addEventListener("change", event =>
      this.setBenchmarksVisible(event.target.checked, { restore: true }));
    document.querySelectorAll(".side-link").forEach(button => button.addEventListener("click", () => this.open(button.dataset.panel)));
    document.querySelector("#close-settings").addEventListener("click", () => this.dialog.close());
    document.querySelector("#close-settings-mobile").addEventListener("click", () => this.dialog.close());
    this.dialog.querySelectorAll("[data-settings-section]").forEach(button => button.addEventListener("click", () => this.section(button.dataset.settingsSection)));
    document.querySelector("#save-settings").addEventListener("click", () => this.save());
    document.querySelector("#settings-intensity").addEventListener("input", event => document.querySelector("#intensity-output").value = `${Math.round(event.target.value)}`);
    document.querySelector("#settings-speed").addEventListener("input", event => document.querySelector("#speed-output").value = `${Math.round(event.target.value)}`);
    this.accentPicker = document.querySelector("#settings-accent-picker");
    this.accentChannels = ["r", "g", "b"].map(channel => document.querySelector(`#settings-accent-${channel}`));
    this.accentPicker.addEventListener("input", event => this.setAccentColor(event.target.value));
    this.accentChannels.forEach(input => input.addEventListener("input", () => this.setAccentColor(rgbToHex(this.accentChannels.map(channel => channel.value)))));
    document.querySelectorAll("[data-accent-preset]").forEach(button => button.addEventListener("click", () => this.setAccentColor(button.dataset.accentPreset)));
    this.manualForm = document.querySelector("#manual-provider-form");
    this.manualType = document.querySelector("#manual-provider-type");
    this.manualName = document.querySelector("#manual-provider-name");
    this.manualEndpoint = document.querySelector("#manual-provider-endpoint");
    this.manualLocation = document.querySelector("#manual-provider-location");
    this.manualKeyEnv = document.querySelector("#manual-provider-key-env");
    this.manualStatus = document.querySelector("#manual-provider-status");
    this.routerDialog = document.querySelector("#router-assistant-dialog");
    this.routerModelSelect = document.querySelector("#settings-router-model");
    this.routerModelSelect.addEventListener("change", () => this.syncRoutingModelState());
    document.querySelector("#close-router-assistant").addEventListener("click", () => this.routerDialog.close());
    document.querySelector("#save-router-assistant").addEventListener("click", () => this.saveRouterAssistant());
    document.querySelector("#refresh-providers").addEventListener("click", event => this.refreshProviders(event.currentTarget));
    document.querySelector("#show-manual-provider").addEventListener("click", () => this.manualForm.hidden ? this.showManualProvider() : this.hideManualProvider());
    document.querySelector("#cancel-manual-provider").addEventListener("click", () => this.hideManualProvider());
    document.querySelector("#save-manual-provider").addEventListener("click", () => this.saveManualProvider());
    this.manualType.addEventListener("change", () => this.updateManualProviderFields(true));
  }

  async open(section = "assistant") {
    document.querySelector("#app").classList.remove("sidebar-open");
    this.dialog.showModal(); this.section(section);
    try {
      const [config, nodes, providers, status, models] = await Promise.all([this.api("/api/settings"), this.api("/api/nodes"), this.api("/api/providers"), this.api("/api/status"), this.api("/api/models")]);
      this.config = config; this.populate(config); this.renderCompute(nodes); this.renderConnections(providers); this.renderRoutingModels(models);
      // Read the running version rather than hardcoding it, so About
      // cannot drift out of step with the build it is describing.
      document.querySelector("#about-version").textContent = `Version ${status.version}`;
    } catch { document.querySelector("#settings-saved").textContent = "Status unavailable"; }
  }

  async openManualConnection() {
    const loading = this.open("connections");
    this.showManualProvider();
    await loading;
  }

  async openRouterAssistant() {
    document.querySelector("#app").classList.remove("sidebar-open");
    if (this.dialog.open) this.dialog.close();
    if (!this.routerDialog.open) this.routerDialog.showModal();
    const status = document.querySelector("#router-assistant-saved");
    status.textContent = "Loading available models…";
    try {
      const [config, models] = await Promise.all([
        this.api("/api/settings"),
        this.api("/api/models"),
      ]);
      this.config = config;
      this.routingModels = models.map(model => ({ ...model }));
      document.querySelector("#settings-thinking-policy").value = config.router.routing_model?.thinking_policy || "auto";
      this.renderRouterModelOptions(this.routingModels);
      status.textContent = "";
      requestAnimationFrame(() => this.routerModelSelect.focus({ preventScroll: true }));
    } catch (error) {
      status.textContent = `Router settings unavailable. ${error.message}`;
    }
  }

  async saveRouterAssistant() {
    const button = document.querySelector("#save-router-assistant");
    const status = document.querySelector("#router-assistant-saved");
    button.disabled = true;
    status.textContent = "Saving…";
    try {
      const result = await this.api("/api/settings", {
        method: "POST",
        body: JSON.stringify({
          router: {
            routing_model: {
              enabled: Boolean(this.routerModelSelect.value),
              model: this.routerModelSelect.value,
              thinking_policy: document.querySelector("#settings-thinking-policy").value,
            },
          },
        }),
      });
      this.config = result;
      this.onSave(result);
      this.syncRoutingModelState();
      status.textContent = "Saved";
      setTimeout(() => { if (status.textContent === "Saved") status.textContent = ""; }, 1800);
    } catch (error) {
      status.textContent = `Could not save. ${error.message}`;
    } finally {
      button.disabled = false;
    }
  }

  section(name) {
    this.dialog.classList.toggle("benchmarks-active", name === "benchmarks");
    this.dialog.querySelectorAll("[data-settings-section]").forEach(button => button.classList.toggle("active", button.dataset.settingsSection === name));
    this.dialog.querySelectorAll("[data-section]").forEach(panel => panel.classList.toggle("active", panel.dataset.section === name));
    const heading = this.dialog.querySelector(`[data-section="${name}"] h2`);
    if (this.dialog.open && heading) { heading.tabIndex = -1; heading.focus({ preventScroll: true }); }
    // Benchmarks read the live model list, so they load when the panel
    // is opened rather than on every settings fetch.
    if (name === "benchmarks") this.benchmarks?.load();
  }

  applyBenchmarkVisibility(visible) {
    const tab = this.dialog.querySelector('[data-settings-section="benchmarks"]');
    const panel = this.dialog.querySelector('[data-section="benchmarks"]');
    if (tab) tab.hidden = !visible;
    if (panel) panel.hidden = !visible;
    document.querySelector("#settings-show-benchmarks").checked = visible;
    document.querySelector("#benchmarks-restore-note").textContent = visible
      ? ""
      : "Switching this on restores the two starter benchmarks if you have none saved. Your own benchmarks are never deleted by hiding the panel.";
    // Never leave the user staring at a section that is now hidden.
    if (!visible && panel?.classList.contains("active")) this.section("assistant");
  }

  async setBenchmarksVisible(visible, { restore = false } = {}) {
    this.applyBenchmarkVisibility(visible);
    try {
      // Turning it back on with nothing saved would open an empty panel,
      // so the starters come back with it.
      if (visible && restore) await this.benchmarks.restoreStarters();
      const config = await this.api("/api/settings", {
        method: "POST",
        body: JSON.stringify({ interface: { show_benchmarks: visible } }),
      });
      this.config = config;
      if (visible) this.benchmarks.load();
    } catch (error) {
      document.querySelector("#benchmarks-restore-note").textContent = `Could not save that. ${error.message}`;
    }
  }

  populate(config) {
    const motion = config.interface.motion;
    const intensity = Math.min(.36, Math.max(0, Number(motion.intensity)));
    const reaction = Math.min(2, Math.max(0, Number(motion.reaction ?? .9)));
    const accent = config.interface.accent || { mode: "adaptive", color: "#e4b45f" };
    document.querySelector("#settings-name").value = config.assistant.name;
    document.querySelector("#settings-tagline").value = config.assistant.tagline;
    document.querySelector("#settings-instructions").value = config.assistant.instructions;
    document.querySelector("#settings-theme").value = config.interface.appearance;
    document.querySelector("#settings-accent-mode").value = accent.mode;
    this.setAccentColor(accent.color);
    document.querySelector("#settings-motion").value = motion.mode;
    document.querySelector("#settings-intensity").value = Math.round(intensity / .18 * 50);
    document.querySelector("#settings-speed").value = Math.round(Number(motion.speed) * 50);
    document.querySelector("#settings-reaction").value = Math.round(reaction * 50);
    document.querySelector("#intensity-output").value = `${Math.round(intensity / .18 * 50)}`;
    document.querySelector("#speed-output").value = `${Math.round(Number(motion.speed) * 50)}`;
    document.querySelector("#reaction-output").value = `${Math.round(reaction * 50)}`;
    document.querySelector("#settings-strategy").value = config.router.strategy;
    document.querySelector("#settings-prefer-local").checked = config.router.prefer_local;
    document.querySelector("#settings-affinity").checked = config.router.session_affinity;
    document.querySelector("#settings-local-only").checked = config.router.privacy_mode === "local_only";
    document.querySelector("#settings-thinking-policy").value = config.router.routing_model?.thinking_policy || "auto";

    const n8n = config.actions?.n8n || {};
    document.querySelector("#settings-n8n-enabled").checked = Boolean(n8n.enabled);
    // The endpoint is write-only, so the field starts empty and only
    // reports whether one is already stored.
    document.querySelector("#settings-n8n-endpoint").value = "";
    document.querySelector("#n8n-configured-note").textContent = n8n.configured ? "· a webhook is saved" : "· not set";

    this.applyBenchmarkVisibility(config.interface.show_benchmarks !== false);
  }

  renderCompute(nodes) {
    const list = document.querySelector("#compute-list"); list.replaceChildren();
    if (!nodes.length) { list.textContent = "No compute nodes are configured."; return; }
    nodes.forEach(node => {
      const card = document.createElement("article"); card.className = "compute-card";
      const head = document.createElement("div"); head.className = "compute-card-head";
      const copy = document.createElement("div"); const title = document.createElement("h3"); title.textContent = node.display_name;
      const meta = document.createElement("p"); meta.textContent = `${node.type} · ${node.always_on ? "Always on" : node.wake_capable ? "Wake-on-LAN available" : "On demand"} · ${node.provider_count} provider${node.provider_count === 1 ? "" : "s"}`;
      copy.append(title, meta);
      const status = document.createElement("span"); status.className = `status-label ${node.reachable ? "online" : ""}`; status.innerHTML = `<i></i><span>${node.state[0].toUpperCase() + node.state.slice(1)}</span>`;
      head.append(copy, status); card.append(head);
      if (!node.reachable && node.wake_capable) { const wake = document.createElement("button"); wake.className = "wake-button"; wake.textContent = "Wake"; wake.addEventListener("click", async () => { wake.disabled = true; wake.textContent = "Wake sent"; try { await this.api(`/api/nodes/${encodeURIComponent(node.id)}/wake`, { method: "POST" }); } catch { wake.textContent = "Couldn't wake"; } }); card.append(wake); }
      list.append(card);
    });
  }

  setAccentColor(color) {
    const normalized = /^#[0-9a-f]{6}$/i.test(color || "") ? color.toLowerCase() : "#e4b45f";
    const channels = hexToRgb(normalized);
    this.accentPicker.value = normalized;
    this.accentChannels.forEach((input, index) => { input.value = channels[index]; });
    document.querySelector("#accent-editor").style.setProperty("--preview-accent", normalized);
    document.querySelectorAll("[data-accent-preset]").forEach(button => button.classList.toggle("selected", button.dataset.accentPreset.toLowerCase() === normalized));
  }

  renderConnections(providers) {
    const list = document.querySelector("#connections-list"); list.replaceChildren();
    providers.forEach(provider => {
      const card = document.createElement("article"); card.className = "connection-card";
      const copy = document.createElement("div"); const title = document.createElement("h3"); title.textContent = provider.name || (provider.type === "openrouter" ? "OpenRouter" : provider.id);
      if (provider.manual) { const origin = document.createElement("span"); origin.className = "connection-origin"; origin.textContent = "MANUAL"; title.append(origin); }
      else if (provider.auto_detect) { const origin = document.createElement("span"); origin.className = "connection-origin"; origin.textContent = "AUTO"; title.append(origin); }
      const meta = document.createElement("p"); meta.textContent = provider.endpoint || (provider.node ? `Provider on ${provider.node}` : "Cloud provider");
      if (provider.detected) meta.textContent += " · detected automatically";
      copy.append(title, meta);
      const actions = document.createElement("div"); actions.className = "connection-actions";
      const status = document.createElement("span"); status.className = `status-label ${provider.status === "online" ? "online" : ""}`; status.innerHTML = `<i></i><span>${provider.status}</span>`;
      actions.append(status);
      if (provider.manual) {
        const remove = document.createElement("button"); remove.type = "button"; remove.className = "connection-delete"; remove.textContent = "Remove";
        remove.setAttribute("aria-label", `Remove manual connection: ${provider.name || provider.id}`);
        remove.addEventListener("click", () => this.deleteManualProvider(provider, remove));
        actions.append(remove);
      }
      card.append(copy, actions); list.append(card);
    });
  }

  renderRoutingModels(models) {
    const list = document.querySelector("#settings-routing-models");
    list.replaceChildren();
    this.routingModels = models.map(model => ({ ...model }));
    this.renderRouterModelOptions(this.routingModels);
    if (!models.length) { list.textContent = "No models detected."; return; }
    models.forEach(model => {
      const row = document.createElement("label"); row.className = "routing-model-row";
      row.draggable = true; row.dataset.modelKey = `${model.provider}:${model.id}`;
      const handle = document.createElement("span"); handle.className = "routing-model-handle"; handle.textContent = "⠿"; handle.setAttribute("aria-hidden", "true");
      const copy = document.createElement("span"); const name = document.createElement("b"); name.textContent = model.name;
      const source = document.createElement("small"); source.textContent = model.node || model.provider;
      const toggle = document.createElement("input"); toggle.type = "checkbox"; toggle.checked = model.enabled !== false;
      toggle.dataset.modelKey = `${model.provider}:${model.id}`;
      toggle.addEventListener("change", () => {
        const selected = this.routerModelSelect.value;
        const current = this.routingModels.find(item => `${item.provider}:${item.id}` === toggle.dataset.modelKey);
        if (current) current.enabled = toggle.checked;
        this.renderRouterModelOptions(this.routingModels, toggle.checked ? selected : selected === toggle.dataset.modelKey ? "" : selected);
      });
      row.addEventListener("dragstart", event => {
        this.draggingRoutingModel = row;
        row.classList.add("dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", row.dataset.modelKey);
      });
      row.addEventListener("dragover", event => {
        if (!this.draggingRoutingModel || this.draggingRoutingModel === row) return;
        event.preventDefault();
        const bounds = row.getBoundingClientRect();
        list.insertBefore(this.draggingRoutingModel, event.clientY < bounds.top + bounds.height / 2 ? row : row.nextSibling);
      });
      row.addEventListener("drop", event => event.preventDefault());
      row.addEventListener("dragend", () => { row.classList.remove("dragging"); this.draggingRoutingModel = null; });
      row.addEventListener("keydown", event => {
        if (!event.altKey || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
        event.preventDefault();
        const sibling = event.key === "ArrowUp" ? row.previousElementSibling : row.nextElementSibling;
        if (!sibling?.dataset.modelKey) return;
        if (event.key === "ArrowUp") list.insertBefore(row, sibling);
        else list.insertBefore(sibling, row);
        toggle.focus();
      });
      copy.append(name, source); row.append(handle, copy, toggle); list.append(row);
    });
  }

  renderRouterModelOptions(models, selectedOverride = null) {
    const selected = selectedOverride ?? this.config?.router?.routing_model?.model ?? "";
    this.routerModelSelect.replaceChildren();
    const none = document.createElement("option"); none.value = ""; none.textContent = "None — use built-in rules";
    this.routerModelSelect.append(none);
    models.filter(model => model.enabled !== false).forEach(model => {
      const option = document.createElement("option");
      option.value = `${model.provider}:${model.id}`;
      option.textContent = `${model.name} · ${model.node || model.provider}`;
      this.routerModelSelect.append(option);
    });
    this.routerModelSelect.value = [...this.routerModelSelect.options].some(option => option.value === selected) ? selected : "";
    this.syncRoutingModelState();
  }

  syncRoutingModelState() {
    const selected = this.routerModelSelect.selectedOptions[0];
    document.querySelector("#settings-router-model-state").textContent = selected?.value
      ? `Assisted by ${selected.textContent}`
      : "Built-in rules active";
  }

  async refreshProviders(button) {
    button.disabled = true;
    const original = button.textContent;
    button.textContent = "Detecting…";
    try {
      const providers = await this.api("/api/providers?refresh=true");
      this.renderConnections(providers);
      const online = providers.filter(provider => provider.status === "online").length;
      const saved = document.querySelector("#settings-saved");
      saved.textContent = `${online} connection${online === 1 ? "" : "s"} online`;
    } catch {
      document.querySelector("#settings-saved").textContent = "Detection unavailable";
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  async deleteManualProvider(provider, button) {
    const name = provider.name || provider.id;
    if (!window.confirm(`Remove the manual connection “${name}”?`)) return;
    button.disabled = true;
    try {
      const result = await this.api(`/api/providers/manual/${encodeURIComponent(provider.id)}`, { method: "DELETE" });
      this.config = result.settings;
      this.onSave(result.settings);
      this.renderConnections(await this.api("/api/providers"));
      const saved = document.querySelector("#settings-saved");
      saved.textContent = "Connection removed";
      setTimeout(() => { if (saved.textContent === "Connection removed") saved.textContent = ""; }, 1800);
    } catch (error) {
      button.disabled = false;
      this.manualStatus.classList.add("error");
      this.manualStatus.textContent = `Could not remove ${name}. ${error.message}`;
    }
  }

  showManualProvider() {
    this.manualForm.hidden = false;
    document.querySelector("#show-manual-provider").setAttribute("aria-expanded", "true");
    this.updateManualProviderFields(false);
    this.manualForm.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setTimeout(() => this.manualName.focus({ preventScroll: true }), 180);
  }

  hideManualProvider() {
    this.manualForm.hidden = true;
    document.querySelector("#show-manual-provider").setAttribute("aria-expanded", "false");
    this.manualStatus.textContent = "";
    this.manualStatus.classList.remove("error");
  }

  updateManualProviderFields(resetName = false) {
    const type = this.manualType.value;
    const isOpenRouter = type === "openrouter";
    const isOllama = type === "ollama";
    document.querySelector("#manual-provider-endpoint-field").hidden = isOpenRouter;
    document.querySelector("#manual-provider-location-field").hidden = isOpenRouter;
    document.querySelector("#manual-provider-key-field").hidden = isOllama;
    this.manualEndpoint.required = !isOpenRouter;
    this.manualKeyEnv.disabled = isOpenRouter;
    this.manualKeyEnv.placeholder = isOpenRouter ? "OPENROUTER_API_KEY" : "OPENAI_COMPATIBLE_API_KEY";
    if (isOpenRouter) this.manualKeyEnv.value = "OPENROUTER_API_KEY";
    else if (this.manualKeyEnv.value === "OPENROUTER_API_KEY") this.manualKeyEnv.value = "";
    this.manualEndpoint.placeholder = isOllama ? "http://192.168.1.20:11434" : "http://192.168.1.20:1234";
    if (resetName || !this.manualName.value.trim()) this.manualName.value = { ollama: "Homelab Ollama", openai_compatible: "OpenAI-compatible API", openrouter: "OpenRouter" }[type];
  }

  async saveManualProvider() {
    if (!this.manualName.value.trim()) { this.manualName.reportValidity(); return; }
    if (!this.manualEndpoint.checkValidity()) { this.manualEndpoint.reportValidity(); return; }
    const button = document.querySelector("#save-manual-provider");
    button.disabled = true;
    this.manualStatus.classList.remove("error");
    this.manualStatus.textContent = "Saving and checking the endpoint…";
    const payload = {
      name: this.manualName.value.trim(),
      type: this.manualType.value,
      endpoint: this.manualType.value === "openrouter" ? null : this.manualEndpoint.value.trim(),
      location: this.manualType.value === "openrouter" ? "cloud" : this.manualLocation.value,
      api_key_env: this.manualType.value === "ollama" ? "" : this.manualKeyEnv.value.trim(),
    };
    try {
      const result = await this.api("/api/providers/manual", { method: "POST", body: JSON.stringify(payload) });
      this.onSave(result.settings);
      const providers = await this.api("/api/providers");
      this.renderConnections(providers);
      const saved = providers.find(provider => provider.id === result.provider_id);
      this.manualStatus.textContent = saved?.status === "online" ? "Connected. It is now available in the route menu." : "Saved. The endpoint is offline, but you can edit or retry it here.";
    } catch (error) {
      this.manualStatus.classList.add("error");
      this.manualStatus.textContent = typeof error.message === "string" ? error.message : "The connection could not be saved.";
    } finally {
      button.disabled = false;
    }
  }

  async save() {
    const payload = {
      assistant: { name: document.querySelector("#settings-name").value.trim(), tagline: document.querySelector("#settings-tagline").value.trim(), instructions: document.querySelector("#settings-instructions").value.trim() },
      interface: {
        appearance: document.querySelector("#settings-theme").value,
        accent: { mode: document.querySelector("#settings-accent-mode").value, color: this.accentPicker.value },
        motion: { mode: document.querySelector("#settings-motion").value, intensity: Number(document.querySelector("#settings-intensity").value) / 50 * .18, speed: Number(document.querySelector("#settings-speed").value) / 50, reaction: Number(document.querySelector("#settings-reaction").value) / 50 },
      },
      router: { strategy: document.querySelector("#settings-strategy").value, prefer_local: document.querySelector("#settings-prefer-local").checked, session_affinity: document.querySelector("#settings-affinity").checked, privacy_mode: document.querySelector("#settings-local-only").checked ? "local_only" : "standard", disabled_models: [...document.querySelectorAll("#settings-routing-models input[data-model-key]")].filter(input => !input.checked).map(input => input.dataset.modelKey), model_priority: [...document.querySelectorAll("#settings-routing-models .routing-model-row[data-model-key]")].map(row => row.dataset.modelKey), routing_model: { enabled: Boolean(this.routerModelSelect.value), model: this.routerModelSelect.value, thinking_policy: document.querySelector("#settings-thinking-policy").value } },
      actions: { n8n: { enabled: document.querySelector("#settings-n8n-enabled").checked } },
    };
    // Only send the endpoint when the user actually typed one; an empty
    // field means "keep what is stored", not "clear it".
    const endpoint = document.querySelector("#settings-n8n-endpoint").value.trim();
    if (endpoint) payload.actions.n8n.endpoint = endpoint;
    const result = await this.api("/api/settings", { method: "POST", body: JSON.stringify(payload) });
    this.onSave(result); const saved = document.querySelector("#settings-saved"); saved.textContent = "Saved"; setTimeout(() => saved.textContent = "", 1800);
  }
}
