import { create as make } from "./dom.js";

function clock(timestamp = Date.now()) {
  return new Date(timestamp).toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function short(value, length = 82) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}

function traceKind(message) {
  const value = String(message || "").toLowerCase();
  if (/fallback|retry|unavailable|offline|did not respond/.test(value)) return "branch";
  if (/n8n|workflow|wake|action|tool|search/.test(value)) return "tool";
  if (/model|selected|affinity|thinking/.test(value)) return "model";
  return "route";
}

function terminal(state) { return ["complete", "failed", "stopped"].includes(state); }

function durationLabel(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  const ms = Number(value);
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
}

function laneFor(kind) {
  if (["tool", "retry"].includes(kind)) return 2;
  if (kind === "response") return 1;
  return 0;
}

function safeEntries(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value).filter(([, item]) => item !== null && item !== undefined && item !== "");
}

export class Trajectory {
  constructor() {
    this.tabs = document.querySelector("#run-view-tabs");
    this.chatView = document.querySelector("#chat-view");
    this.view = document.querySelector("#trajectory-view");
    this.graph = document.querySelector("#trajectory-graph");
    this.summary = document.querySelector("#trajectory-summary");
    this.metrics = document.querySelector("#trajectory-metrics");
    this.timeline = document.querySelector("#trajectory-timeline-track");
    this.inspector = document.querySelector("#trajectory-inspector");
    this.select = document.querySelector("#trajectory-run-select");
    this.runs = [];
    this.activeId = null;
    this.counter = 0;
    this.tabs.addEventListener("click", event => {
      const button = event.target.closest("[data-run-view]");
      if (button) this.show(button.dataset.runView);
    });
    this.select.addEventListener("change", () => { this.activeId = this.select.value; this.render(); });
  }

  reset() {
    this.runs = [];
    this.activeId = null;
    this.counter = 0;
    this.tabs.hidden = true;
    this.tabs.dataset.active = "false";
    this.show("chat");
  }

  start(pair, prompt, { restored = false } = {}) {
    const id = `run-${Date.now()}-${++this.counter}`;
    const run = {
      id, number: this.counter, prompt, state: restored ? "complete" : "routing",
      metadata: { trace: [] }, events: [], history: [], selectedEventId: null,
      userSelected: false, startedAt: Date.now(),
    };
    pair.dataset.trajectoryId = id;
    this.runs.push(run);
    this.activeId = id;
    this.tabs.hidden = false;
    this.tabs.dataset.active = String(!restored);
    this.renderSelect();
    this.render();
    return run;
  }

  restore(pair, prompt, metadata) {
    const run = this.start(pair, prompt, { restored: true });
    run.metadata = { ...metadata };
    const ledger = Array.isArray(metadata.trajectory) ? metadata.trajectory : [];
    ledger.forEach(event => this.record(pair, event, { render: false }));
    if (ledger.length) {
      run.startedAt = Math.min(...ledger.map(event => Number(event.timestamp_ms) || Date.now()));
      run.selectedEventId = run.events.at(-1)?.id || null;
    }
    if ((metadata.trace || []).some(step => /response ended early/i.test(step.message || ""))) run.state = "stopped";
    this.renderSelect();
    this.render();
  }

  update(pair, metadata = {}, state = null) {
    const run = this.find(pair);
    if (!run) return;
    const stateChanged = Boolean(state && state !== run.state);
    const metadataChanged = Object.keys(metadata).length > 0;
    if (!stateChanged && !metadataChanged) return;
    run.metadata = { ...run.metadata, ...metadata, trace: metadata.trace || run.metadata.trace || [] };
    if (state) run.state = state;
    if (["complete", "error", "stopped"].includes(run.state)) {
      const finalState = run.state === "error" ? "failed" : run.state;
      run.events = run.events.map(item => item.state === "active" ? {
        ...item, state: finalState, endedAt: Date.now(),
        detail: run.state === "stopped" ? "Response interrupted before completion" : item.detail,
      } : item);
      this.tabs.dataset.active = "false";
    }
    this.renderSelect();
    this.render();
  }

  record(pair, event, { render = true } = {}) {
    const run = this.find(pair);
    if (!run || !event?.id) return;
    const timestamp = Number(event.timestamp_ms) || Date.now();
    const transition = { ...event, timestamp_ms: timestamp };
    run.history.push(transition);
    const index = run.events.findIndex(item => item.id === event.id);
    const previous = index >= 0 ? run.events[index] : null;
    const startedAt = previous?.startedAt ?? (event.state === "active" ? timestamp : timestamp - (Number(event.duration_ms) || 0));
    const endedAt = terminal(event.state) ? timestamp : previous?.endedAt;
    const current = {
      ...previous, ...event, timestamp_ms: timestamp, startedAt, endedAt,
      duration_ms: event.duration_ms ?? (endedAt != null ? Math.max(0, endedAt - startedAt) : undefined),
      observedAt: previous?.observedAt || clock(timestamp),
    };
    if (index >= 0) run.events[index] = current;
    else run.events.push(current);
    if (event.state === "active") {
      run.state = event.kind === "response" ? "generating" : "routing";
      if (!run.userSelected) run.selectedEventId = event.id;
    }
    if (event.state === "failed") run.state = "error";
    if (!run.selectedEventId) run.selectedEventId = event.id;
    this.tabs.dataset.active = String(!terminal(event.state));
    if (render) this.render();
  }

  open(pair) {
    const run = this.find(pair);
    if (run) this.activeId = run.id;
    this.renderSelect();
    this.show("trajectory");
  }

  find(pair) { return this.runs.find(run => run.id === pair.dataset.trajectoryId); }

  show(name) {
    const trajectory = name === "trajectory" && this.runs.length;
    this.chatView.hidden = Boolean(trajectory);
    this.view.hidden = !trajectory;
    this.tabs.querySelectorAll("[data-run-view]").forEach(button => button.setAttribute("aria-selected", String(button.dataset.runView === (trajectory ? "trajectory" : "chat"))));
    if (trajectory) this.render();
  }

  renderSelect() {
    this.select.replaceChildren(...this.runs.map(run => {
      const model = run.metadata.model ? ` · ${run.metadata.model}` : "";
      const option = make("option", "", `Run ${run.number}${model}`);
      option.value = run.id;
      return option;
    }));
    if (this.activeId) this.select.value = this.activeId;
  }

  render() {
    const run = this.runs.find(item => item.id === this.activeId) || this.runs.at(-1);
    if (!run) return;
    const metadata = run.metadata || {};
    const activeLabel = { routing: "Routing", generating: "Generating", complete: "Complete", error: "Failed", stopped: "Interrupted" }[run.state] || "Waiting";
    this.summary.replaceChildren(
      make("i"), make("strong", "", activeLabel),
      make("span", "", metadata.route ? `${metadata.route} · ${metadata.model || metadata.provider || "execution path"}` : "Inspecting the request and available routes"),
    );
    const nodes = this.nodes(run);
    this.renderMetrics(run, nodes);
    this.renderTimeline(run, nodes);
    this.graph.replaceChildren(...nodes.map(node => {
      const row = make("button", `trajectory-node state-${node.state}${node.branch ? " branch" : ""}${run.selectedEventId === node.id ? " selected" : ""}`);
      row.type = "button";
      row.dataset.eventId = node.id;
      row.setAttribute("aria-pressed", String(run.selectedEventId === node.id));
      const dot = make("i", "trajectory-dot");
      const copy = make("span", "trajectory-copy");
      copy.append(make("strong", "", node.label), make("small", "", node.detail));
      row.append(dot, copy, make("time", "", node.duration_ms != null ? durationLabel(node.duration_ms) : node.time || ""));
      row.addEventListener("click", () => {
        run.selectedEventId = node.id;
        run.userSelected = true;
        this.render();
      });
      return row;
    }));
    this.renderInspector(run, nodes.find(node => node.id === run.selectedEventId) || nodes.at(-1));
  }

  renderMetrics(run, nodes) {
    const metadata = run.metadata || {};
    const values = [
      ["Duration", durationLabel(metadata.latency_ms ?? this.elapsed(nodes))],
      ["Stages", String(nodes.length)],
      ["Models", String(nodes.filter(node => node.kind === "model").length)],
      ["Tools", String(nodes.filter(node => node.kind === "tool").length)],
    ];
    const retries = nodes.filter(node => node.kind === "retry").length;
    if (retries) values.push(["Retries", String(retries)]);
    this.metrics.replaceChildren(...values.map(([label, value]) => {
      const item = make("span", "trajectory-metric");
      item.append(make("small", "", label), make("strong", "", value));
      return item;
    }));
  }

  elapsed(nodes) {
    const starts = nodes.map(node => node.startedAt).filter(Number.isFinite);
    const ends = nodes.map(node => node.endedAt).filter(Number.isFinite);
    if (!starts.length || !ends.length) return null;
    return Math.max(...ends) - Math.min(...starts);
  }

  renderTimeline(run, nodes) {
    const timed = nodes.filter(node => Number.isFinite(node.startedAt));
    if (!timed.length) {
      this.timeline.replaceChildren(make("span", "trajectory-timeline-empty", "Timing appears as execution events arrive."));
      return;
    }
    const start = Math.min(...timed.map(node => node.startedAt));
    const finished = timed.map(node => node.endedAt).filter(Number.isFinite);
    const end = Math.max(start + 1, ...(finished.length ? finished : [start + 1]));
    const span = Math.max(1, end - start);
    this.timeline.replaceChildren(...timed.map(node => {
      const markerOnly = !Number.isFinite(node.endedAt);
      const left = Math.max(0, Math.min(100, ((node.startedAt - start) / span) * 100));
      const width = markerOnly ? 0 : Math.max(0.65, ((node.endedAt - node.startedAt) / span) * 100);
      const bar = make("button", `trajectory-span lane-${laneFor(node.kind)} state-${node.state}${markerOnly ? " marker" : ""}`);
      bar.type = "button";
      bar.style.left = `${left}%`;
      if (!markerOnly) bar.style.width = `${Math.min(100 - left, width)}%`;
      bar.setAttribute("aria-label", `${node.label}, ${markerOnly ? "active" : durationLabel(node.duration_ms)}`);
      bar.addEventListener("click", () => {
        run.selectedEventId = node.id;
        run.userSelected = true;
        this.render();
      });
      return bar;
    }));
  }

  renderInspector(run, node) {
    this.inspector.replaceChildren();
    if (!node) {
      this.inspector.append(make("p", "trajectory-inspector-empty", "Select a stage to inspect its observable inputs, outputs, timing, and dependency."));
      return;
    }
    this.inspector.append(
      make("span", "trajectory-inspector-eyebrow", node.kind || "stage"),
      make("h3", "", node.label),
      make("p", "trajectory-inspector-detail", node.detail || "No additional detail reported."),
    );
    const facts = make("dl", "trajectory-facts");
    [["State", node.state], ["Started", node.startedAt ? clock(node.startedAt) : "—"], ["Duration", durationLabel(node.duration_ms)], ["Depends on", node.parent || "—"]]
      .forEach(([label, value]) => facts.append(make("dt", "", label), make("dd", "", value)));
    this.inspector.append(facts);
    const input = node.kind === "prompt" ? [["Prompt", short(run.prompt, 260)]] : safeEntries(node.input);
    this.renderPayload("Input", input);
    this.renderPayload("Output", safeEntries(node.output));
    if (node.kind === "response" && (run.metadata.prompt_tokens != null || run.metadata.completion_tokens != null)) {
      this.renderPayload("Usage", [["Prompt tokens", run.metadata.prompt_tokens ?? "—"], ["Completion tokens", run.metadata.completion_tokens ?? "—"]]);
    }
  }

  renderPayload(label, entries) {
    if (!entries.length) return;
    const section = make("section", "trajectory-payload");
    section.append(make("h4", "", label));
    entries.forEach(([key, value]) => {
      const row = make("div", "trajectory-payload-row");
      const rendered = typeof value === "object" ? JSON.stringify(value) : String(value);
      row.append(make("span", "", key.replaceAll("_", " ")), make("code", "", short(rendered, 260)));
      section.append(row);
    });
    this.inspector.append(section);
  }

  nodes(run) {
    const metadata = run.metadata || {};
    const trace = metadata.trace || [];
    if (run.events.length) {
      return run.events.map(event => ({
        ...event, label: event.label, detail: event.detail || event.kind,
        state: event.state === "failed" ? "failed" : event.state || "waiting",
        time: event.observedAt || "",
        branch: event.id.startsWith("routing-detail-") || Boolean(event.parent && !["prompt", "routing", "execution"].includes(event.parent)) || ["retry", "tool"].includes(event.kind),
      }));
    }
    const routeReady = Boolean(metadata.route);
    const finished = ["complete", "error", "stopped"].includes(run.state);
    const nodes = [
      { id: "prompt", kind: "prompt", label: "Prompt", detail: short(run.prompt), state: "complete", time: trace[0]?.time || clock(), startedAt: run.startedAt, endedAt: run.startedAt, duration_ms: 0 },
      { id: "routing", kind: "route", label: "Routing", detail: routeReady ? `${metadata.route} · ${metadata.reason || "route selected"}` : "Classifying intent and applying route policy", state: routeReady ? "complete" : "active", time: trace[0]?.time || "", parent: "prompt" },
    ];
    trace.forEach((step, index) => {
      const kind = traceKind(step.message);
      nodes.push({ id: `trace-${index}`, kind, label: kind === "tool" ? "Tool / action" : kind === "model" ? "Model decision" : kind === "branch" ? "Recovery path" : "Route step", detail: step.message, state: "complete", time: step.time, branch: kind === "branch", parent: "routing" });
    });
    if (metadata.model || metadata.provider) {
      const thinking = metadata.thinking === true ? " · thinking on" : metadata.thinking === false ? " · thinking off" : "";
      nodes.push({ id: "execution", kind: "model", label: "Execution", detail: `${metadata.provider || "provider"} · ${metadata.model || "model"}${thinking}`, state: run.state === "generating" ? "active" : finished ? "complete" : "waiting", time: "", parent: "routing" });
    }
    nodes.push({ id: "response", kind: "response", label: "Response", detail: run.state === "error" ? "Execution ended with an error" : run.state === "stopped" ? "Response interrupted before completion" : run.state === "complete" ? `Delivered${metadata.latency_ms != null ? ` in ${(metadata.latency_ms / 1000).toFixed(1)}s` : ""}` : "Waiting for the response stream", state: run.state === "error" ? "failed" : run.state === "complete" || run.state === "stopped" ? "complete" : run.state === "generating" ? "active" : "waiting", time: "", parent: "execution" });
    return nodes;
  }
}
