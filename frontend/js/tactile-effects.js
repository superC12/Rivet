const app = document.querySelector("#app");
const settingsDialog = document.querySelector("#settings-dialog");
const settingsShell = settingsDialog?.querySelector(".settings-shell");
const routerAssistantDialog = document.querySelector("#router-assistant-dialog");
const routerAssistantShell = routerAssistantDialog?.querySelector(".router-assistant-shell");
const heartbeat = document.querySelector("#connection-heartbeat");

let lastHealth = { state: "healthy", latency: 120 };

app.dataset.originPanels = "subtle";
app.dataset.connectionWaveform = "live";

function animatePanelFrom(opener, dialog = settingsDialog, shell = settingsShell) {
  if (!dialog || !shell) return;
  const origin = opener.getBoundingClientRect();
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (!dialog.open) return;
    const panel = shell.getBoundingClientRect();
    const x = origin.left + origin.width / 2 - panel.left;
    const y = origin.top + origin.height / 2 - panel.top;
    dialog.style.setProperty("--panel-origin-x", `${x}px`);
    dialog.style.setProperty("--panel-origin-y", `${y}px`);
    dialog.classList.remove("origin-unfold");
    void shell.offsetWidth;
    dialog.classList.add("origin-unfold");
  }));
}

// Capture the control's geometry before its own click handler closes a menu
// or swaps dialogs; once hidden, its bounding box collapses to 0 × 0.
document.addEventListener("click", event => {
  const routerOpener = event.target.closest("[data-open-router-assistant]");
  if (routerOpener) animatePanelFrom(routerOpener, routerAssistantDialog, routerAssistantShell);

  const panelOpener = event.target.closest("[data-panel], #open-compute-overview");
  if (panelOpener) animatePanelFrom(panelOpener);
}, true);

function renderHealth(detail) {
  if (!heartbeat) return;
  lastHealth = { ...lastHealth, ...detail };
  const state = ["healthy", "degraded", "offline", "broken"].includes(lastHealth.state)
    ? lastHealth.state
    : "degraded";
  const latency = Number(lastHealth.latency);
  const period = Number.isFinite(latency)
    ? Math.min(5.2, Math.max(1.8, 1.8 + latency / 220))
    : 3.8;
  heartbeat.style.setProperty("--heartbeat-period", `${period.toFixed(2)}s`);
  heartbeat.classList.remove("healthy", "degraded", "offline", "broken");
  // Force one-shot offline interruption to restart when the state is retriggered.
  void heartbeat.offsetWidth;
  heartbeat.classList.add(state);
  heartbeat.dataset.healthState = state;
  heartbeat.dataset.latency = Number.isFinite(latency) ? String(latency) : "unknown";
}

document.addEventListener("rivet:connection-health", event => renderHealth(event.detail || {}));

heartbeat.hidden = false;
renderHealth(lastHealth);
