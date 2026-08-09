// Execution origin and trace rendering.
//
// Kept out of chat.js because this is the one part of the interface that
// is allowed to be technical, and it has its own rules: subdued type, no
// badges, and never a claim the backend did not make. Everything here is
// built with textContent — model output must never reach innerHTML.

const ACTION_LABELS = {
  executed: "✓",
  failed: "failed",
  unconfirmed: "unconfirmed",
  unreachable: "unreachable",
  rejected: "refused",
  not_configured: "not configured",
};

function routeLabel(metadata, nodeNames) {
  const parts = [metadata.route];
  if (metadata.route === "ACTION") {
    parts.push("n8n");
    const status = ACTION_LABELS[metadata.action_status];
    if (status) parts.push(status);
    return parts;
  }
  if (metadata.node) parts.push(nodeNames?.[metadata.node] || metadata.node);
  if (metadata.provider && !metadata.node) parts.push(metadata.provider);
  if (metadata.model) parts.push(metadata.model);
  if (metadata.latency_ms != null) parts.push(`${(metadata.latency_ms / 1000).toFixed(1)}s`);
  return parts;
}

export function renderTelemetry(element, metadata, nodeNames) {
  const parts = routeLabel(metadata, nodeNames).filter(Boolean);
  element.textContent = parts.join(" · ");
  element.classList.toggle("telemetry-warn", metadata.action_status != null && metadata.action_status !== "executed");

  // Token counts are real but noisy, so they live in the tooltip rather
  // than the line. Absent counts stay absent; nothing is estimated.
  const tokens = [
    metadata.prompt_tokens != null ? `${metadata.prompt_tokens} in` : null,
    metadata.completion_tokens != null ? `${metadata.completion_tokens} out` : null,
  ].filter(Boolean);
  if (tokens.length) element.title = `${tokens.join(" · ")} tokens`;
  else element.removeAttribute("title");
}

export function renderTrace(toggle, panel, metadata) {
  const trace = metadata.trace || [];
  if (!trace.length) {
    toggle.hidden = true;
    return;
  }
  toggle.hidden = false;
  toggle.querySelector("span").textContent = `Executed ${trace.length} step${trace.length === 1 ? "" : "s"}`;
  toggle.setAttribute("aria-expanded", String(panel.classList.contains("open")));

  panel.replaceChildren();
  const title = document.createElement("div");
  title.className = "trace-title";
  title.textContent = `${metadata.route || "ROUTE"} ROUTE`;
  panel.append(title);

  trace.forEach(step => {
    const row = document.createElement("div");
    row.className = "trace-row";
    const time = document.createElement("time");
    time.textContent = step.time || "—";
    const text = document.createElement("span");
    text.textContent = step.message;
    row.append(time, text);
    panel.append(row);
  });

  toggle.onclick = () => {
    const open = panel.classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(open));
  };
}
