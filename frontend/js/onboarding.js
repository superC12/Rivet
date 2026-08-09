export class Onboarding {
  constructor({ overlay, api, atmosphere, onComplete }) {
    this.overlay = overlay;
    this.api = api;
    this.atmosphere = atmosphere;
    this.onComplete = onComplete;
    this.step = 1;
    this.instanceName = "Your assistant";
    this.modelStates = new Map();
    this.progress = document.querySelector("#onboarding-progress");
    for (let index = 1; index <= 5; index++) this.progress.append(document.createElement("i"));
    overlay.querySelectorAll(".next-step").forEach(button => button.addEventListener("click", () => this.go(this.step + 1)));
    overlay.querySelectorAll(".previous-step").forEach(button => button.addEventListener("click", () => this.go(this.step - 1)));
    document.querySelector("#finish-onboarding").addEventListener("click", () => this.finish());
    document.querySelector("#setup-name").addEventListener("input", event => this.setInstanceName(event.target.value));
  }

  setInstanceName(value, syncInput = false) {
    const chosen = value.trim();
    const name = chosen || "Your assistant";
    this.instanceName = name;
    if (syncInput) document.querySelector("#setup-name").value = value;
    document.querySelector("#onboarding").setAttribute("aria-label", `${name} setup`);
    document.querySelector("#onboarding-platform").textContent = name.toUpperCase();
    document.querySelector("#onboarding-welcome").textContent = chosen ? `Welcome to ${name}.` : "Welcome.";
    document.querySelector("#onboarding-compute-title").textContent = `Where can ${name} think?`;
    document.querySelector("#onboarding-auto-copy").textContent = `Recommended · ${name} chooses the right source`;
    document.querySelector("#activation-name").textContent = name.toUpperCase().split("").join(" ");
  }

  async show() { this.overlay.hidden = false; this.atmosphere.configure({ mode: "ambient", intensity: .15 }); this.go(1); }

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
      models.forEach(model => {
        const key = `${model.provider}:${model.id}`;
        if (!this.modelStates.has(key)) this.modelStates.set(key, model.enabled !== false);
        const item = document.createElement("button"); item.type = "button"; item.className = "setup-model";
        item.dataset.modelKey = key;
        const dot = document.createElement("i"); const copy = document.createElement("div");
        const name = document.createElement("strong"); name.textContent = model.name;
        const meta = document.createElement("span"); meta.textContent = `${model.node ? "Local" : "Cloud"} · ${model.node || model.provider}`;
        const state = document.createElement("b");
        const render = () => {
          const enabled = this.modelStates.get(key) !== false;
          item.classList.toggle("excluded", !enabled);
          item.setAttribute("aria-pressed", String(enabled));
          item.setAttribute("aria-label", `${enabled ? "Exclude" : "Include"} ${model.name} from automatic routing`);
          state.textContent = enabled ? "✓" : "Off";
          this.updateModelChoiceNote();
        };
        item.addEventListener("click", () => { this.modelStates.set(key, this.modelStates.get(key) === false); render(); });
        copy.append(name, meta); item.append(dot, copy, state); list.append(item); render();
      });
      if (!models.length) document.querySelector("#model-choice-note").textContent = "No models detected yet. You can connect one later in Settings.";
    } catch { /* Auto route remains a useful default. */ }
  }

  updateModelChoiceNote() {
    if (!this.modelStates.size) return;
    const enabled = [...this.modelStates.values()].filter(Boolean).length;
    const total = this.modelStates.size;
    document.querySelector("#model-choice-note").textContent = `${enabled} of ${total} detected model${total === 1 ? "" : "s"} in automatic rotation.`;
  }

  async finish() {
    const name = document.querySelector("#setup-name").value.trim();
    const instructions = document.querySelector("#setup-instructions").value.trim();
    const disabledModels = [...this.modelStates].filter(([, enabled]) => !enabled).map(([key]) => key);
    const config = await this.api("/api/onboarding", { method: "POST", body: JSON.stringify({ assistant: { name, instructions }, router: { disabled_models: disabledModels } }) });
    this.overlay.style.opacity = "0";
    this.overlay.style.transition = "opacity .65s ease";
    setTimeout(() => { this.overlay.hidden = true; this.overlay.style = ""; }, 650);
    this.onComplete(config);
  }
}
