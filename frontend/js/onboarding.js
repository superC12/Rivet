export class Onboarding {
  constructor({ overlay, api, atmosphere, onComplete }) {
    this.overlay = overlay;
    this.api = api;
    this.atmosphere = atmosphere;
    this.onComplete = onComplete;
    this.step = 1;
    this.instanceName = "Your assistant";
    this.modelStates = new Map();
    this.modelPriority = [];
    this.draggingModel = null;
    this.ignoreModelClick = false;
    this.previewMode = false;
    this.defaultInstructions = document.querySelector("#setup-instructions").value;
    this.progress = document.querySelector("#onboarding-progress");
    this.nameNext = overlay.querySelector('.onboarding-step[data-step="1"] .next-step');
    for (let index = 1; index <= 5; index++) this.progress.append(document.createElement("i"));
    overlay.querySelectorAll(".next-step").forEach(button => button.addEventListener("click", () => this.go(this.step + 1)));
    overlay.querySelectorAll(".previous-step").forEach(button => button.addEventListener("click", () => this.go(this.step - 1)));
    document.querySelector("#finish-onboarding").addEventListener("click", () => this.finish());
    document.querySelector("#close-onboarding-preview").addEventListener("click", () => this.closePreview());
    document.addEventListener("keydown", event => { if (event.key === "Escape" && this.previewMode && !this.overlay.hidden) this.closePreview(); });
    document.querySelector("#setup-name").addEventListener("input", event => this.setInstanceName(event.target.value));
  }

  setInstanceName(value, syncInput = false) {
    const chosen = value.trim();
    const name = chosen || "Your assistant";
    this.instanceName = name;
    this.nameNext.disabled = !chosen;
    if (syncInput) document.querySelector("#setup-name").value = value;
    document.querySelector("#onboarding").setAttribute("aria-label", `${name} setup`);
    document.querySelector("#onboarding-platform").textContent = name.toUpperCase();
    document.querySelector("#onboarding-welcome").textContent = chosen ? `Welcome to ${name}.` : "Welcome.";
    document.querySelector("#onboarding-compute-title").textContent = `Where can ${name} think?`;
    document.querySelector("#onboarding-auto-copy").textContent = `Recommended · ${name} chooses the right source`;
    document.querySelector("#activation-name").textContent = name.toUpperCase().split("").join(" ");
  }

  async show() {
    this.previewMode = false;
    document.querySelector("#close-onboarding-preview").hidden = true;
    this.overlay.hidden = false;
    this.atmosphere.configure({ mode: "ambient", intensity: .15 });
    this.go(1);
  }

  async openPreview() {
    this.previewMode = true;
    this.modelStates.clear();
    this.modelPriority = [];
    this.setInstanceName("", true);
    document.querySelector("#setup-instructions").value = this.defaultInstructions;
    document.querySelector("#close-onboarding-preview").hidden = false;
    this.overlay.hidden = false;
    this.overlay.style = "";
    this.atmosphere.configure({ mode: "ambient", intensity: .15 });
    await this.go(1);
    document.querySelector("#setup-name").focus();
  }

  closePreview() {
    if (!this.previewMode) return;
    this.previewMode = false;
    this.overlay.hidden = true;
    this.overlay.style = "";
  }

  async go(step) {
    if (step > 1 && !document.querySelector("#setup-name").value.trim()) { document.querySelector("#setup-name").focus(); return; }
    this.step = Math.max(1, Math.min(5, step));
    this.overlay.querySelectorAll(".onboarding-step").forEach(panel => panel.classList.toggle("active", Number(panel.dataset.step) === this.step));
    [...this.progress.children].forEach((dot, index) => dot.classList.toggle("active", index < this.step));
    if (this.step === 3) await this.discover();
    if (this.step === 4) await this.models();
    if (this.step === 5) {
      const name = document.querySelector("#setup-name").value.trim();
      this.setInstanceName(name);
    }
  }

  async discover() {
    const dot = document.querySelector("#ollama-discovery");
    const label = document.querySelector("#ollama-discovery-label");
    label.textContent = "Checking for Ollama…";
    try {
      const providers = await this.api("/api/providers?refresh=true");
      const ollama = providers.find(provider => provider.type === "ollama");
      if (ollama?.status === "online") { dot.classList.add("online"); label.textContent = `Ollama detected · ${ollama.endpoint}`; }
      else { dot.classList.remove("online"); label.textContent = "Ollama not detected"; }
    } catch { label.textContent = "Discovery unavailable"; }
  }

  async models() {
    const list = document.querySelector("#setup-models");
    [...list.querySelectorAll(".setup-model:not(:first-child)")].forEach(item => item.remove());
    try {
      const models = await this.api("/api/models");
      const byKey = new Map(models.map(model => [`${model.provider}:${model.id}`, model]));
      this.modelPriority = [
        ...this.modelPriority.filter(key => byKey.has(key)),
        ...models.map(model => `${model.provider}:${model.id}`).filter(key => !this.modelPriority.includes(key)),
      ];
      this.modelPriority.map(key => byKey.get(key)).filter(Boolean).forEach(model => {
        const key = `${model.provider}:${model.id}`;
        if (!this.modelStates.has(key)) this.modelStates.set(key, model.enabled !== false);
        const item = document.createElement("button"); item.type = "button"; item.className = "setup-model";
        item.dataset.modelKey = key;
        item.draggable = true;
        const dot = document.createElement("i"); const copy = document.createElement("div");
        const name = document.createElement("strong"); name.textContent = model.name;
        const source = `${model.node ? "Local" : "Cloud"} · ${model.node || model.provider}`;
        const meta = document.createElement("span"); meta.className = "model-meta"; meta.dataset.source = source;
        const state = document.createElement("b");
        const handle = document.createElement("span"); handle.className = "model-drag-handle"; handle.textContent = "⠿"; handle.setAttribute("aria-hidden", "true");
        const render = () => {
          const enabled = this.modelStates.get(key) !== false;
          item.classList.toggle("excluded", !enabled);
          item.setAttribute("aria-pressed", String(enabled));
          item.setAttribute("aria-label", `${enabled ? "Exclude" : "Include"} ${model.name} from automatic routing. Drag to change priority; Alt plus arrow keys also reorders.`);
          state.textContent = enabled ? "✓" : "Off";
          this.updateModelChoiceNote();
        };
        item.addEventListener("click", () => {
          if (this.ignoreModelClick) return;
          this.modelStates.set(key, this.modelStates.get(key) === false); render();
        });
        item.addEventListener("dragstart", event => {
          this.draggingModel = item;
          item.classList.add("dragging");
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", key);
        });
        item.addEventListener("dragover", event => {
          if (!this.draggingModel || this.draggingModel === item) return;
          event.preventDefault();
          const bounds = item.getBoundingClientRect();
          list.insertBefore(this.draggingModel, event.clientY < bounds.top + bounds.height / 2 ? item : item.nextSibling);
          this.captureModelPriority(list);
        });
        item.addEventListener("drop", event => { event.preventDefault(); this.captureModelPriority(list); });
        item.addEventListener("dragend", () => {
          item.classList.remove("dragging");
          this.draggingModel = null;
          this.ignoreModelClick = true;
          // Browsers may emit a click immediately after a completed drag.
          // Keep it from accidentally toggling the model that was moved.
          setTimeout(() => { this.ignoreModelClick = false; }, 200);
          this.captureModelPriority(list);
        });
        item.addEventListener("keydown", event => {
          if (!event.altKey || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
          event.preventDefault();
          const sibling = event.key === "ArrowUp" ? item.previousElementSibling : item.nextElementSibling;
          if (!sibling?.dataset.modelKey) return;
          if (event.key === "ArrowUp") list.insertBefore(item, sibling);
          else list.insertBefore(sibling, item);
          this.captureModelPriority(list);
          item.focus();
        });
        copy.append(name, meta); item.append(dot, copy, state, handle); list.append(item); render();
      });
      this.captureModelPriority(list);
      if (!models.length) document.querySelector("#model-choice-note").textContent = "No models detected yet. You can connect one later in Settings.";
    } catch { /* Auto route remains a useful default. */ }
  }

  captureModelPriority(list = document.querySelector("#setup-models")) {
    const items = [...list.querySelectorAll("[data-model-key]")];
    this.modelPriority = items.map(item => item.dataset.modelKey);
    items.forEach((item, index) => {
      const meta = item.querySelector(".model-meta");
      if (meta) meta.textContent = `Priority ${index + 1} · ${meta.dataset.source}`;
    });
    this.updateModelChoiceNote();
  }

  updateModelChoiceNote() {
    if (!this.modelStates.size) return;
    const enabled = [...this.modelStates.values()].filter(Boolean).length;
    const total = this.modelStates.size;
    document.querySelector("#model-choice-note").textContent = `${enabled} of ${total} detected model${total === 1 ? "" : "s"} in rotation. Drag to reorder; the top model has highest priority.`;
  }

  async finish() {
    if (this.previewMode) {
      this.closePreview();
      return;
    }
    const name = document.querySelector("#setup-name").value.trim();
    const instructions = document.querySelector("#setup-instructions").value.trim();
    const disabledModels = [...this.modelStates].filter(([, enabled]) => !enabled).map(([key]) => key);
    const config = await this.api("/api/onboarding", { method: "POST", body: JSON.stringify({ assistant: { name, instructions }, router: { disabled_models: disabledModels, model_priority: this.modelPriority } }) });
    this.overlay.style.opacity = "0";
    this.overlay.style.transition = "opacity .65s ease";
    setTimeout(() => { this.overlay.hidden = true; this.overlay.style = ""; }, 650);
    this.onComplete(config);
  }
}
