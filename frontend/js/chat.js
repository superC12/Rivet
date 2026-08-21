import { consumeEventStream } from "./stream.js";
import { renderTelemetry, renderTrace } from "./telemetry.js";

function escapeHtml(value) {
  return value.replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function renderMarkdown(source) {
  let safe = escapeHtml(source);
  const codeBlocks = [];
  safe = safe.replace(/```(?:[\w-]+)?\n([\s\S]*?)```/g, (_, code) => {
    codeBlocks.push(`<pre><code>${code.trim()}</code></pre>`);
    return `@@RIVETCODE${codeBlocks.length - 1}@@`;
  });
  safe = safe.replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  safe = safe.split(/\n{2,}/).map(block => block.startsWith("<pre>") || /^<h\d>/.test(block) || block.startsWith("@@RIVETCODE") ? block : `<p>${block.replace(/\n/g, "<br>")}</p>`).join("");
  return safe.replace(/@@RIVETCODE(\d+)@@/g, (_, index) => codeBlocks[Number(index)]);
}

export class Chat {
  constructor({ atmosphere, accent, routeControl, trajectory, onConversation, onComplete }) {
    this.atmosphere = atmosphere;
    this.accent = accent;
    this.routeControl = routeControl;
    this.trajectory = trajectory;
    this.onConversation = onConversation;
    this.onComplete = onComplete;
    this.messages = document.querySelector("#messages");
    this.empty = document.querySelector("#empty-state");
    this.form = document.querySelector("#composer");
    this.input = document.querySelector("#message-input");
    this.send = document.querySelector("#send-button");
    this.thinking = document.querySelector("#thinking-toggle");
    this.steerButton = document.querySelector("#steer-button");
    this.mode = document.querySelector("#route-mode");
    this.activity = document.querySelector("#system-activity");
    this.conversationId = null;
    this.controller = null;
    this.currentRequest = null;
    this.streaming = false;
    this.steering = false;
    this.accentTimer = null;
    this.nodeNames = {};
    this.assistantName = "your assistant";
    this.thinkingEnabled = false;
    this.availableModels = [];
    this.defaultPlaceholder = this.input.placeholder;
    this.form.addEventListener("submit", event => { event.preventDefault(); this.submitFromComposer(); });
    this.thinking.addEventListener("click", () => this.setThinking(!this.thinkingEnabled));
    this.steerButton.addEventListener("click", () => this.beginSteering());
    document.addEventListener("rivet:route-changed", () => this.refreshThinkingVisibility());
    this.input.addEventListener("input", () => {
      this.resize();
      clearTimeout(this.accentTimer);
      const text = this.input.value.trim();
      this.accentTimer = setTimeout(() => text ? this.accent?.adaptTo(text) : this.accent?.reset(), 320);
    });
    this.input.addEventListener("keydown", event => {
      if (event.key === "Escape" && this.steering) { event.preventDefault(); this.cancelSteering(); return; }
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); this.submitFromComposer(); return; }
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); this.submitFromComposer(); }
    });
    document.querySelector("#composer-shortcut").textContent = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘ ↵" : "Ctrl ↵";
  }

  setAssistantName(name) { this.assistantName = name; this.input.setAttribute("aria-label", `Message ${name}`); }

  setThinking(enabled) {
    this.thinkingEnabled = Boolean(enabled);
    const state = this.thinkingEnabled ? "on" : "off";
    this.thinking.setAttribute("aria-pressed", String(this.thinkingEnabled));
    this.thinking.setAttribute("aria-label", `Thinking mode ${state}`);
    this.thinking.dataset.tooltip = this.thinkingEnabled
      ? "Thinking is on. Compatible models will use deeper reasoning."
      : "Thinking is off. Enable it to request deeper reasoning from compatible models.";
  }

  configureModels(models = []) {
    this.availableModels = models;
    this.refreshThinkingVisibility();
  }

  refreshThinkingVisibility() {
    const selected = this.routeSelection().model;
    const candidates = selected
      ? this.availableModels.filter(model => `${model.provider}:${model.id}` === selected || model.id === selected)
      : this.availableModels;
    const available = candidates.some(model => model.enabled !== false && (model.capabilities || []).includes("thinking"));
    this.thinking.hidden = !available;
    if (!available) this.setThinking(false);
  }

  submitFromComposer() {
    if (this.streaming) {
      if (this.steering && this.input.value.trim()) void this.steer();
      else if (!this.steering) this.stop();
      return;
    }
    if (!this.input.value.trim()) return;
    const task = this.submit();
    this.currentRequest = task;
    void task.finally(() => { if (this.currentRequest === task) this.currentRequest = null; });
  }

  beginSteering() {
    if (!this.streaming) return;
    this.steering = true;
    this.steerButton.setAttribute("aria-pressed", "true");
    this.steerButton.textContent = "Steering";
    this.input.placeholder = `Redirect ${this.assistantName}…`;
    this.send.classList.remove("stop");
    this.send.querySelector("span").textContent = "↑";
    this.send.setAttribute("aria-label", "Send steering instruction");
    this.input.focus();
  }

  cancelSteering() {
    this.steering = false;
    this.steerButton.setAttribute("aria-pressed", "false");
    this.steerButton.textContent = "Steer";
    this.input.placeholder = this.defaultPlaceholder;
    if (this.streaming) {
      this.send.classList.add("stop");
      this.send.querySelector("span").textContent = "";
      this.send.setAttribute("aria-label", "Stop response");
    }
  }

  async steer() {
    const instruction = this.input.value.trim();
    if (!instruction || !this.streaming) return;
    const active = this.currentRequest;
    this.controller?.abort();
    if (active) await active;
    this.input.value = instruction;
    this.resize();
    this.submitFromComposer();
  }

  routeSelection() { return this.routeControl.selection(); }
  primeInput(text) { this.input.value = text; this.resize(); this.accent?.adaptTo(text); this.input.focus(); }
  resize() { this.input.style.height = "auto"; this.input.style.height = `${Math.min(this.input.scrollHeight, 160)}px`; this.send.disabled = !this.input.value.trim() && !this.streaming; }
  newConversation() { this.stop(); this.trajectory.reset(); this.accent?.reset(); this.conversationId = null; this.messages.replaceChildren(); this.empty.hidden = false; this.input.focus(); }
  stop() { this.controller?.abort(); if (!this.streaming) this.finishStreaming(); }
  finishStreaming() { this.streaming = false; this.controller = null; this.form.classList.remove("executing"); this.send.classList.remove("stop"); this.send.querySelector("span").textContent = "↑"; this.send.setAttribute("aria-label", "Send message"); this.thinking.disabled = false; this.steerButton.hidden = true; this.cancelSteering(); this.activity.textContent = ""; this.resize(); }

  createPair(userText = "") {
    const pair = document.querySelector("#message-template").content.firstElementChild.cloneNode(true);
    pair.querySelector(".user-message").textContent = userText;
    this.messages.append(pair);
    this.empty.hidden = true;
    return pair;
  }

  renderConversation(conversation) {
    this.stop(); this.trajectory.reset(); this.conversationId = conversation.id; this.messages.replaceChildren(); this.empty.hidden = conversation.messages.length > 0;
    const latestPrompt = [...conversation.messages].reverse().find(message => message.role === "user");
    latestPrompt ? this.accent?.adaptTo(latestPrompt.content) : this.accent?.reset();
    const pendingPairs = [];
    conversation.messages.forEach(message => {
      if (message.role === "user") pendingPairs.push(this.createPair(message.content));
      if (message.role === "assistant") {
        const pair = pendingPairs.shift() || this.createPair("");
        pair.querySelector(".assistant-content").innerHTML = renderMarkdown(message.content);
        this.trajectory.restore(pair, pair.querySelector(".user-message").textContent, message);
        this.applyMetadata(pair, message);
      }
    });
    this.scrollBottom(false);
  }

  setNodeNames(names) { this.nodeNames = names; }

  applyMetadata(pair, metadata, state = "complete") {
    const toggle = pair.querySelector(".trace-toggle");
    toggle.dataset.tooltip = `Open the observable execution trajectory for this response.`;
    renderTrace(
      toggle,
      { ...metadata, hasTrajectory: Boolean(this.trajectory.find(pair)?.events.length) },
      () => this.trajectory.open(pair),
      state,
    );
    renderTelemetry(pair.querySelector(".telemetry"), metadata, this.nodeNames);
  }

  async submit() {
    const text = this.input.value.trim(); if (!text) return;
    this.accent?.adaptTo(text);
    const pair = this.createPair(text);
    this.trajectory.start(pair, text);
    const content = pair.querySelector(".assistant-content");
    const cursor = document.createElement("span"); cursor.className = "cursor"; content.append(cursor);
    this.input.value = ""; this.resize();
    this.streaming = true; this.form.classList.add("executing"); this.send.disabled = false; this.send.classList.add("stop"); this.send.querySelector("span").textContent = ""; this.send.setAttribute("aria-label", "Stop response"); this.thinking.disabled = true; this.steerButton.hidden = false;
    this.activity.textContent = "Choosing where to think…";
    this.atmosphere.setState("routing");
    this.controller = new AbortController();
    let fullText = "";
    try {
      const response = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: this.controller.signal,
        body: JSON.stringify({ conversation_id: this.conversationId, message: text, thinking: this.thinkingEnabled, ...this.routeSelection() }),
      });
      await consumeEventStream(response, {
        conversation: data => { this.conversationId = data.id; this.onConversation(data.id); },
        trajectory: data => this.trajectory.record(pair, data),
        route: data => { this.activity.textContent = data.route === "REMOTE" ? "Checking remote compute…" : `${data.route.toLowerCase().replace(/^./, c => c.toUpperCase())} route selected`; this.atmosphere.setState(data.route.toLowerCase()); this.trajectory.update(pair, data, "routing"); this.applyMetadata(pair, data, "routing"); },
        status: data => { this.activity.textContent = data.message; this.atmosphere.setState(data.state); this.trajectory.update(pair, {}, "routing"); },
        notice: message => { const notice = document.createElement("p"); notice.className = "notice-message"; notice.textContent = message; content.before(notice); },
        // The server abandoned a half-finished answer. Drop it here too,
        // or the dead fragment stays glued to the front of the real one.
        reset: () => { fullText = ""; content.innerHTML = '<span class="cursor"></span>'; this.atmosphere.setState("warning"); this.trajectory.update(pair, {}, "routing"); },
        token: token => { fullText += token; content.innerHTML = `${renderMarkdown(fullText)}<span class="cursor"></span>`; this.atmosphere.setState("generating"); this.trajectory.update(pair, {}, "generating"); this.scrollBottom(); },
        done: data => { content.innerHTML = renderMarkdown(fullText); this.trajectory.update(pair, data, "complete"); this.applyMetadata(pair, data, "complete"); this.atmosphere.setState("complete"); setTimeout(() => this.atmosphere.setState("idle"), 1000); },
        error: data => { content.innerHTML = ""; const error = document.createElement("p"); error.className = "error-message"; error.textContent = data.message; content.append(error); const metadata = { route: "ERROR", trajectory: data.trajectory || [] }; this.trajectory.update(pair, metadata, "error"); this.applyMetadata(pair, metadata, "error"); this.atmosphere.setState("error"); },
      }, this.controller.signal);
    } catch (error) {
      if (error.name === "AbortError") this.trajectory.update(pair, {}, "stopped");
      else { content.textContent = `I couldn't connect to ${this.assistantName}. ${error.message}`; this.trajectory.update(pair, {}, "error"); this.atmosphere.setState("error"); }
    } finally {
      content.querySelector(".cursor")?.remove(); this.finishStreaming(); this.onComplete(this.conversationId);
    }
  }

  scrollBottom(smooth = true) { document.querySelector("#conversation").scrollTo({ top: document.querySelector("#conversation").scrollHeight, behavior: smooth ? "smooth" : "auto" }); }
}
