// Saved benchmark suites: pick one, edit it, run it, read the results.
//
// Everything is built with textContent rather than innerHTML. A suite
// holds user-authored prompts and a model's raw reply, and both end up
// on screen — neither is markup.

import { consumeEventStream } from "./stream.js";

// Each kind gets its own mark and phrasing so the two are told apart at
// a glance, rather than by reading the name carefully.
const KIND = {
  perf: {
    label: "Speed & Footprint",
    short: "Speed",
    question: "How fast it answers, and how much of the machine it takes.",
    icon: '<svg viewBox="0 0 18 18" aria-hidden="true"><path d="M9 15.5a6.5 6.5 0 1 1 6.5-6.5"/><path d="M9 9l3.6-3.1"/></svg>',
  },
  eval: {
    label: "Judgment & Limits",
    short: "Judgment",
    question: "Whether it follows your protocol, and admits what it cannot do.",
    icon: '<svg viewBox="0 0 18 18" aria-hidden="true"><path d="M9 2.5v13M4 6h10"/><path d="m4 6-1.8 4a2.2 2.2 0 0 0 3.6 0Zm10 0-1.8 4a2.2 2.2 0 0 0 3.6 0Z"/></svg>',
  },
};

function kindOf(kind) {
  return KIND[kind] || { label: kind, short: kind, question: "", icon: "" };
}

function create(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = text;
  return element;
}

function field(labelText, control, hint) {
  const label = create("label", "benchmark-field");
  label.append(create("span", "benchmark-field-label", labelText), control);
  if (hint) label.append(create("small", "", hint));
  return label;
}

function bytes(value) {
  if (!value) return "—";
  const gb = value / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(2)} GB` : `${Math.round(value / 1024 ** 2)} MB`;
}

function percent(value) {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

export class BenchmarksPanel {
  constructor({ api, onEmptied }) {
    this.api = api;
    // Called when the last benchmark is removed, so the panel can be put
    // away rather than left as an empty room.
    this.onEmptied = onEmptied || (() => {});
    this.suites = [];
    this.targets = { providers: [], graders: [] };
    this.current = null;
    this.controller = null;
    this.picker = document.querySelector("#benchmark-picker");
    this.editor = document.querySelector("#benchmark-editor");
    this.results = document.querySelector("#benchmark-results");
    this.status = document.querySelector("#benchmark-status");
    this.form = document.querySelector("#new-benchmark-form");
    this.newName = document.querySelector("#new-benchmark-name");
    this.newKind = document.querySelector("#new-benchmark-kind");
    this.newHint = document.querySelector("#new-benchmark-hint");

    this.picker.addEventListener("change", () => this.select(this.picker.value));
    document.querySelector("#show-new-benchmark").addEventListener("click", () => this.toggleForm());
    document.querySelector("#cancel-new-benchmark").addEventListener("click", () => this.closeForm());
    document.querySelector("#create-new-benchmark").addEventListener("click", () => this.create());
    this.newKind.addEventListener("change", () => this.describeKind());
    this.describeKind();
  }

  describeKind() {
    this.newHint.textContent = kindOf(this.newKind.value).question;
  }

  toggleForm() {
    this.form.hidden ? this.openForm() : this.closeForm();
  }

  openForm() {
    this.form.hidden = false;
    document.querySelector("#show-new-benchmark").setAttribute("aria-expanded", "true");
    this.describeKind();
    this.newName.focus();
  }

  closeForm() {
    this.form.hidden = true;
    document.querySelector("#show-new-benchmark").setAttribute("aria-expanded", "false");
    this.newName.value = "";
  }

  say(message, tone = "") {
    this.status.textContent = message;
    this.status.className = `benchmark-status ${tone}`;
  }

  async load() {
    try {
      const [suites, targets] = await Promise.all([
        this.api("/api/benchmarks"),
        this.api("/api/benchmarks/targets"),
      ]);
      this.suites = suites;
      this.targets = targets;
      this.renderPicker();
      const keep = this.current && suites.find(s => s.id === this.current.id);
      await this.select(keep ? this.current.id : suites[0]?.id);
    } catch (error) {
      this.say(`Could not load benchmarks. ${error.message}`, "error");
    }
  }

  renderPicker() {
    this.picker.replaceChildren(...this.suites.map(suite => {
      const option = create("option", "", `${suite.name} · ${kindOf(suite.kind).short}`);
      option.value = suite.id;
      return option;
    }));
    if (!this.suites.length) {
      const option = create("option", "", "No saved benchmarks");
      option.value = "";
      this.picker.append(option);
    }
  }

  async select(id) {
    this.results.replaceChildren();
    if (!id) {
      this.current = null;
      this.editor.replaceChildren(create("p", "field-note", "Create a suite to get started."));
      return;
    }
    try {
      this.current = await this.api(`/api/benchmarks/${encodeURIComponent(id)}`);
      this.picker.value = id;
      this.renderEditor();
      this.renderHistory();
    } catch (error) {
      this.say(`Could not open that suite. ${error.message}`, "error");
    }
  }

  async create() {
    const kind = this.newKind.value;
    const name = this.newName.value.trim() || `My ${kindOf(kind).short.toLowerCase()} benchmark`;
    const definition = kind === "perf"
      ? { models: [], cold_start: true, prompt_tokens: 2000, prompt_text: "" }
      : { models: [], system_prompt: "", tool_schema: "", tests: [] };
    try {
      const suite = await this.api("/api/benchmarks", {
        method: "POST",
        body: JSON.stringify({ name, kind, description: "", definition }),
      });
      this.closeForm();
      await this.load();
      await this.select(suite.id);
      this.say(kind === "perf" ? "Created. Pick models, then Run." : "Created. Add test cases, pick models, then Run.");
    } catch (error) {
      this.say(`Could not create that benchmark. ${error.message}`, "error");
    }
  }

  async restoreStarters() {
    const body = await this.api("/api/benchmarks/restore", { method: "POST" });
    await this.load();
    return body.created;
  }

  // --- editor --------------------------------------------------------

  renderEditor() {
    const suite = this.current;
    const definition = suite.definition || {};
    this.editor.replaceChildren();

    const name = create("input");
    name.value = suite.name;
    name.maxLength = 80;
    const description = create("input");
    description.value = suite.description || "";
    description.maxLength = 280;

    const kind = kindOf(suite.kind);
    const identity = create("div", `benchmark-identity kind-${suite.kind}`);
    const mark = create("span", "benchmark-identity-mark");
    mark.innerHTML = kind.icon;
    const copy = create("div", "benchmark-identity-copy");
    copy.append(create("strong", "", kind.label), create("small", "", kind.question));
    identity.append(mark, copy);
    this.editor.append(identity);

    const head = create("div", "benchmark-grid");
    head.append(field("Name", name), field("Description", description));
    this.editor.append(head);
    this.editor.append(this.providerField(definition), this.modelField(definition));

    const body = create("div", "benchmark-body");
    if (suite.kind === "perf") this.renderPerfFields(body, definition);
    else this.renderEvalFields(body, definition);
    this.editor.append(body);

    const actions = create("div", "benchmark-actions");
    const run = create("button", "benchmark-run", "Run");
    run.type = "button";
    const save = create("button", "", "Save");
    save.type = "button";
    const remove = create("button", "benchmark-delete", "Delete");
    remove.type = "button";
    actions.append(remove, save, run);
    this.editor.append(actions);

    this.collect = () => ({
      name: name.value.trim() || suite.name,
      description: description.value.trim(),
      definition: this.collectDefinition(definition),
    });
    save.addEventListener("click", () => this.save());
    remove.addEventListener("click", () => this.remove());
    run.addEventListener("click", () => (this.controller ? this.stop() : this.run(run)));
    this.runButton = run;
  }

  providerField(definition) {
    const select = create("select");
    const providers = this.targets.providers || [];
    if (!providers.length) {
      const option = create("option", "", "No Ollama connection configured");
      option.value = "";
      select.append(option);
      select.disabled = true;
    } else {
      providers.forEach(provider => {
        const option = create("option", "", `${provider.name} · ${provider.endpoint}`);
        option.value = provider.id;
        select.append(option);
      });
      select.value = definition.provider || providers[0].id;
    }
    select.addEventListener("change", () => this.renderEditor());
    this.providerSelect = select;
    return field("Run against", select, "Benchmarks read Ollama's own timing and memory accounting, so they target Ollama connections.");
  }

  // The "auto dropdown" — every model Ollama actually reports, so a
  // suite can never name one that is not installed.
  modelField(definition) {
    const provider = (this.targets.providers || []).find(p => p.id === (this.providerSelect?.value || ""));
    const available = provider?.models || [];
    const chosen = new Set(definition.models || []);
    const wrap = create("div", "benchmark-models");

    if (!available.length) {
      wrap.append(create("p", "field-note", "No models detected on this connection. Pull one in Ollama, then reopen this panel."));
    }
    available.forEach(model => {
      const item = create("label", "benchmark-model");
      const box = create("input");
      box.type = "checkbox";
      box.value = model;
      box.checked = chosen.has(model);
      item.append(box, create("span", "", model));
      wrap.append(item);
    });

    // Models chosen earlier that this connection no longer reports stay
    // visible and selected rather than vanishing silently.
    (definition.models || []).filter(m => !available.includes(m)).forEach(model => {
      const item = create("label", "benchmark-model missing");
      const box = create("input");
      box.type = "checkbox";
      box.value = model;
      box.checked = true;
      item.append(box, create("span", "", `${model} (not detected)`));
      wrap.append(item);
    });

    this.modelBoxes = wrap;
    return field("Models", wrap, "Detected automatically from the selected connection.");
  }

  renderPerfFields(container, definition) {
    const cold = create("input");
    cold.type = "checkbox";
    cold.checked = definition.cold_start !== false;
    const coldRow = create("label", "toggle-row");
    const coldCopy = create("span");
    coldCopy.append(create("b", "", "Cold start"), create("small", "", "Evict every loaded model first, so load time is included."));
    coldRow.append(coldCopy, cold);

    const tokens = create("input");
    tokens.type = "number";
    tokens.min = "1";
    tokens.max = "200000";
    tokens.value = definition.prompt_tokens ?? 2000;

    const text = create("textarea");
    text.rows = 4;
    text.value = definition.prompt_text || "";

    container.append(
      coldRow,
      field("Prompt size (approx. tokens)", tokens, "Used only when no custom prompt is supplied."),
      field("Custom prompt", text, "Leave blank to generate filler of the size above."),
    );
    this.perfInputs = { cold, tokens, text };
  }

  renderEvalFields(container, definition) {
    const system = create("textarea");
    system.rows = 5;
    system.value = definition.system_prompt || "";
    const tool = create("textarea");
    tool.rows = 3;
    tool.value = definition.tool_schema || "";

    container.append(
      field("System prompt", system, "Sent before every test except tool-call tests."),
      field("Tool schema", tool, "Used instead of the system prompt for tests in the tool_call category."),
    );

    const list = create("div", "benchmark-tests");
    (definition.tests || []).forEach(test => list.append(this.testRow(test)));
    container.append(field("Test cases", list));

    const add = create("button", "benchmark-add-test", "＋ Add test");
    add.type = "button";
    add.addEventListener("click", () => list.append(this.testRow({ grading: "manual" })));
    container.append(add);

    this.evalInputs = { system, tool, list };
  }

  testRow(test) {
    const row = create("div", "benchmark-test");
    const id = create("input");
    id.value = test.id || "";
    id.placeholder = "id";
    const category = create("input");
    category.value = test.category || "";
    category.placeholder = "category";
    const prompt = create("textarea");
    prompt.rows = 2;
    prompt.value = test.prompt || "";
    prompt.placeholder = "Prompt sent to the model";
    const expected = create("input");
    expected.value = test.expected || "";
    expected.placeholder = "expected";
    const grading = create("select");
    (this.targets.graders || []).forEach(name => {
      const option = create("option", "", name);
      option.value = name;
      grading.append(option);
    });
    grading.value = test.grading || "manual";
    const remove = create("button", "benchmark-test-remove", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", "Remove this test");
    remove.addEventListener("click", () => row.remove());

    row.append(id, category, prompt, expected, grading, remove);
    row.dataset.testRow = "true";
    return row;
  }

  collectDefinition(previous) {
    const models = [...this.modelBoxes.querySelectorAll("input[type=checkbox]")]
      .filter(box => box.checked)
      .map(box => box.value);
    const definition = { ...previous, models, provider: this.providerSelect?.value || undefined };

    if (this.current.kind === "perf") {
      definition.cold_start = this.perfInputs.cold.checked;
      definition.prompt_tokens = Number(this.perfInputs.tokens.value) || 2000;
      definition.prompt_text = this.perfInputs.text.value;
      return definition;
    }

    definition.system_prompt = this.evalInputs.system.value;
    definition.tool_schema = this.evalInputs.tool.value;
    definition.tests = [...this.evalInputs.list.querySelectorAll("[data-test-row]")].map(row => {
      const [id, category, prompt, expected, grading] = row.children;
      return {
        id: id.value.trim(),
        category: category.value.trim(),
        prompt: prompt.value,
        expected: expected.value,
        grading: grading.value,
      };
    }).filter(test => test.prompt.trim());
    return definition;
  }

  async save() {
    try {
      await this.api(`/api/benchmarks/${encodeURIComponent(this.current.id)}`, {
        method: "PUT",
        body: JSON.stringify(this.collect()),
      });
      await this.load();
      this.say("Saved.");
    } catch (error) {
      this.say(`Could not save. ${error.message}`, "error");
    }
  }

  async remove() {
    const last = this.suites.length === 1;
    const warning = last
      ? "\n\nThis is the last one, so the Benchmarks panel will be hidden. Switch it back on in Advanced."
      : "";
    if (!confirm(`Delete “${this.current.name}”?\n\nThis also removes its saved run history.${warning}`)) return;
    try {
      await this.api(`/api/benchmarks/${encodeURIComponent(this.current.id)}`, { method: "DELETE" });
      this.current = null;
      await this.load();
      this.say("Deleted.");
      // Nothing left to measure with, so put the panel away rather than
      // leaving an empty section in the navigation.
      if (!this.suites.length) await this.onEmptied();
    } catch (error) {
      this.say(`Could not delete. ${error.message}`, "error");
    }
  }

  // --- running -------------------------------------------------------

  stop() {
    this.controller?.abort();
    // Keep the controller set until the fetch settles so repeated clicks
    // cannot start a second run while the first is still cancelling.
    this.runButton.disabled = true;
    this.runButton.textContent = "Stopping…";
    this.say("Stopping…");
  }

  async run(button) {
    const payload = this.collect();
    if (!payload.definition.models.length) {
      this.say("Select at least one model first.", "error");
      return;
    }
    // Save first, so what ran is what is stored.
    try {
      await this.api(`/api/benchmarks/${encodeURIComponent(this.current.id)}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
    } catch (error) {
      this.say(`Could not save before running. ${error.message}`, "error");
      return;
    }

    this.results.replaceChildren();
    const table = this.current.kind === "perf" ? this.perfTable() : this.evalTable();
    this.results.append(table.element);
    this.controller = new AbortController();
    button.textContent = "Stop";
    this.say("Starting…");

    try {
      const response = await fetch(`/api/benchmarks/${encodeURIComponent(this.current.id)}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: this.controller.signal,
        body: JSON.stringify({ provider: payload.definition.provider, models: payload.definition.models }),
      });
      await consumeEventStream(response, {
        started: data => this.say(`Running ${data.models.length} model(s) on ${data.provider}…`),
        progress: data => this.say(data.total ? `${data.message} (${data.current}/${data.total})` : data.message),
        result: result => table.add(result),
        error: data => this.say(data.message, "error"),
        done: data => {
          this.say(data.summary || "Finished.");
          this.loadHistoryLater();
        },
      }, this.controller.signal);
    } catch (error) {
      if (error.name !== "AbortError") this.say(`The run failed. ${error.message}`, "error");
    } finally {
      this.controller = null;
      button.disabled = false;
      button.textContent = "Run";
      if (this.status.textContent === "Stopping…") this.say("Stopped.");
    }
  }

  loadHistoryLater() {
    this.api(`/api/benchmarks/${encodeURIComponent(this.current.id)}`)
      .then(suite => { this.current = suite; this.renderHistory(); })
      .catch(() => { /* the results on screen are still valid */ });
  }

  perfTable() {
    const element = create("table", "benchmark-table");
    const head = create("thead");
    const headRow = create("tr");
    ["Model", "Gen tok/s", "Prompt tok/s", "Load", "Resident", "On GPU"].forEach(
      title => headRow.append(create("th", "", title)),
    );
    head.append(headRow);
    const body = create("tbody");
    element.append(head, body);
    return {
      element,
      add(result) {
        const row = create("tr");
        if (result.error) {
          row.append(create("td", "", result.model));
          const cell = create("td", "benchmark-error", result.error);
          cell.colSpan = 5;
          row.append(cell);
        } else {
          [
            result.model,
            result.gen_tok_s ?? "—",
            result.prompt_tok_s ?? "—",
            result.load_ms != null ? `${(result.load_ms / 1000).toFixed(1)}s` : "—",
            bytes(result.size_bytes),
            percent(result.gpu_offload),
          ].forEach(value => row.append(create("td", "", String(value))));
        }
        body.append(row);
      },
    };
  }

  evalTable() {
    const element = create("div", "benchmark-eval-results");
    return {
      element,
      add(result) {
        const card = create("article", "benchmark-eval-model");
        const score = result.score || {};
        const heading = create("h4", "", result.model);
        const summary = create("p", "benchmark-score",
          `${score.passed ?? 0}/${score.graded ?? 0} auto-graded` +
          (score.review ? ` · ${score.review} to review` : "") +
          (score.errors ? ` · ${score.errors} errored` : ""));
        card.append(heading, summary);
        (result.tests || []).forEach(test => {
          const row = create("div", `benchmark-eval-test status-${test.status}`);
          row.append(
            create("span", "benchmark-eval-status", test.status),
            create("span", "benchmark-eval-id", test.id || test.category || ""),
            create("span", "benchmark-eval-response", test.error || test.response || ""),
          );
          card.append(row);
        });
        element.append(card);
      },
    };
  }

  renderHistory() {
    const runs = (this.current?.runs || []).filter(run => run.status !== "running");
    if (!runs.length) return;
    const history = create("div", "benchmark-history");
    history.append(create("h4", "", "Recent runs"));
    runs.slice(0, 5).forEach(run => {
      const row = create("div", "benchmark-history-row");
      row.append(
        create("time", "", new Date(run.started_at).toLocaleString()),
        create("span", "", run.summary || run.status),
      );
      history.append(row);
    });
    this.results.append(history);
  }
}
