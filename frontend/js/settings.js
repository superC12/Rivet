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
    document.querySelectorAll(".side-link").forEach(button => button.addEventListener("click", () => this.open(button.dataset.panel)));
    document.querySelector("#close-settings").addEventListener("click", () => this.dialog.close());
    document.querySelector("#close-settings-mobile").addEventListener("click", () => this.dialog.close());
    this.dialog.querySelectorAll("[data-settings-section]").forEach(button => button.addEventListener("click", () => this.section(button.dataset.settingsSection)));
    document.querySelector("#save-settings").addEventListener("click", () => this.save());
    document.querySelector("#settings-intensity").addEventListener("input", event => document.querySelector("#intensity-output").value = `${Math.round(event.target.value * 100)}%`);
    document.querySelector("#settings-speed").addEventListener("input", event => document.querySelector("#speed-output").value = `${Number(event.target.value).toFixed(1)}×`);
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
    document.querySelector("#show-manual-provider").addEventListener("click", () => this.manualForm.hidden ? this.showManualProvider() : this.hideManualProvider());
    document.querySelector("#cancel-manual-provider").addEventListener("click", () => this.hideManualProvider());
    document.querySelector("#save-manual-provider").addEventListener("click", () => this.saveManualProvider());
    this.manualType.addEventListener("change", () => this.updateManualProviderFields(true));
  }

  async open(section = "assistant") {
    document.querySelector("#app").classList.remove("sidebar-open");
    this.dialog.showModal(); this.section(section);
    try {
      const [config, nodes, providers, status] = await Promise.all([this.api("/api/settings"), this.api("/api/nodes"), this.api("/api/providers"), this.api("/api/status")]);
      this.config = config; this.populate(config); this.renderCompute(nodes); this.renderConnections(providers);
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

  section(name) {
    this.dialog.querySelectorAll("[data-settings-section]").forEach(button => button.classList.toggle("active", button.dataset.settingsSection === name));
    this.dialog.querySelectorAll("[data-section]").forEach(panel => panel.classList.toggle("active", panel.dataset.section === name));
    const heading = this.dialog.querySelector(`[data-section="${name}"] h2`);
    if (this.dialog.open && heading) { heading.tabIndex = -1; heading.focus({ preventScroll: true }); }
  }

  populate(config) {
    const motion = config.interface.motion;
    const intensity = Math.min(.18, Math.max(.08, Number(motion.intensity)));
    const accent = config.interface.accent || { mode: "adaptive", color: "#e4b45f" };
    document.querySelector("#settings-name").value = config.assistant.name;
    document.querySelector("#settings-tagline").value = config.assistant.tagline;
    document.querySelector("#settings-instructions").value = config.assistant.instructions;
    document.querySelector("#settings-theme").value = config.interface.appearance;
    document.querySelector("#settings-accent-mode").value = accent.mode;
    this.setAccentColor(accent.color);
    document.querySelector("#settings-motion").value = motion.mode;
    document.querySelector("#settings-intensity").value = intensity;
    document.querySelector("#settings-speed").value = motion.speed;
    document.querySelector("#intensity-output").value = `${Math.round(intensity * 100)}%`;
    document.querySelector("#speed-output").value = `${Number(motion.speed).toFixed(1)}×`;
    document.querySelector("#settings-strategy").value = config.router.strategy;
    document.querySelector("#settings-prefer-local").checked = config.router.prefer_local;
    document.querySelector("#settings-affinity").checked = config.router.session_affinity;
    document.querySelector("#settings-local-only").checked = config.router.privacy_mode === "local_only";

    const n8n = config.actions?.n8n || {};
    document.querySelector("#settings-n8n-enabled").checked = Boolean(n8n.enabled);
    // The endpoint is write-only, so the field starts empty and only
    // reports whether one is already stored.
    document.querySelector("#settings-n8n-endpoint").value = "";
    document.querySelector("#n8n-configured-note").textContent = n8n.configured ? "· a webhook is saved" : "· not set";
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
      const meta = document.createElement("p"); meta.textContent = provider.endpoint || (provider.node ? `Provider on ${provider.node}` : "Cloud provider"); copy.append(title, meta);
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
        motion: { mode: document.querySelector("#settings-motion").value, intensity: Number(document.querySelector("#settings-intensity").value), speed: Number(document.querySelector("#settings-speed").value) },
      },
      router: { strategy: document.querySelector("#settings-strategy").value, prefer_local: document.querySelector("#settings-prefer-local").checked, session_affinity: document.querySelector("#settings-affinity").checked, privacy_mode: document.querySelector("#settings-local-only").checked ? "local_only" : "standard" },
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
