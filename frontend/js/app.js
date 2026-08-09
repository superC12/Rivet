import { Atmosphere } from "./atmosphere.js";
import { AccentController } from "./accent.js";
import { Chat } from "./chat.js";
import { Onboarding } from "./onboarding.js";
import { SettingsPanel } from "./settings.js";
import { Sidebar } from "./sidebar.js";
import { ContextTooltip } from "./tooltip.js";
import { RouteControl, RuntimeDashboard } from "./runtime.js";

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  if (!response.ok) { let message = response.statusText; try { message = (await response.json()).detail || message; } catch {} throw new Error(message); }
  return response.status === 204 ? null : response.json();
}

const state = { config: null, conversations: [] };
const app = document.querySelector("#app");
const atmosphere = new Atmosphere(document.querySelector("#atmosphere"));
const onboardingAtmosphere = new Atmosphere(document.querySelector("#onboarding-atmosphere"));
const accent = new AccentController(document.querySelector("#accent-context"));
new ContextTooltip(document.querySelector("#context-tooltip"));

function applyTheme(appearance) {
  const resolved = appearance === "system" ? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : appearance;
  document.documentElement.dataset.theme = resolved;
}

function applyConfig(config) {
  state.config = config;
  const platform = config.platform.name || "Rivet";
  const name = config.assistant.name || "Atlas";
  const brandLetters = Array.from(platform.toUpperCase());
  document.querySelector("#platform-mark").textContent = brandLetters.shift() || "R";
  document.querySelector("#platform-wordmark").textContent = brandLetters.join(" ");
  document.querySelector("#onboarding-platform").textContent = platform.toUpperCase();
  document.querySelector("#onboarding-welcome").textContent = `Welcome to ${platform}.`;
  document.querySelector("#about-mark").textContent = platform.slice(0, 1).toUpperCase();
  document.querySelector("#about-platform").textContent = platform;
  document.title = name;
  chat.setAssistantName(name);
  applyTheme(config.interface.appearance);
  accent.configure(config.interface.accent);
  atmosphere.configure(config.interface.motion);
  app.dataset.motion = config.interface.motion.mode;
  const motionMode = config.interface.motion.mode;
  const motionLabel = motionMode.replace(/^./, char => char.toUpperCase());
  const motionDescriptions = {
    static: "Static holds the atmospheric backdrop still. Click to switch to Ambient.",
    ambient: "Ambient drifts slowly in the background. Click to switch to Dynamic.",
    dynamic: "Dynamic reacts to routing, generation, completion, and errors. Click to switch to Static.",
  };
  document.querySelector("#motion-label").textContent = motionLabel;
  document.querySelector("#motion-status").dataset.tooltip = motionDescriptions[motionMode];
}

async function loadConversations(activeId = sidebar.activeId) {
  try { state.conversations = await api("/api/conversations"); sidebar.activeId = activeId; sidebar.render(state.conversations); } catch { sidebar.render([]); }
}

const sidebar = new Sidebar({
  app, list: document.querySelector("#conversation-list"),
  onSelect: async id => { try { const conversation = await api(`/api/conversations/${encodeURIComponent(id)}`); sidebar.activeId = id; chat.renderConversation(conversation); await loadConversations(id); } catch {} },
  onNew: () => { sidebar.activeId = null; chat.newConversation(); loadConversations(); },
  onDelete: async conversation => {
    try {
      await api(`/api/conversations/${encodeURIComponent(conversation.id)}`, { method: "DELETE" });
      if (sidebar.activeId === conversation.id) {
        sidebar.activeId = null;
        chat.newConversation();
      }
      await loadConversations();
    } catch (error) {
      const activity = document.querySelector("#system-activity");
      activity.textContent = `Could not delete that conversation. ${error.message}`;
      setTimeout(() => { if (activity.textContent.startsWith("Could not delete")) activity.textContent = ""; }, 3500);
      await loadConversations();
    }
  },
});

let settings;
const routeControl = new RouteControl({
  select: document.querySelector("#route-mode"),
  trigger: document.querySelector("#route-trigger"),
  menu: document.querySelector("#route-menu"),
  onLinkProvider: () => settings.openManualConnection(),
});
const chat = new Chat({ atmosphere, accent, routeControl, onConversation: id => { sidebar.activeId = id; }, onComplete: id => loadConversations(id) });
const runtime = new RuntimeDashboard({
  api,
  routeControl,
  onOpenSettings: section => settings.open(section),
  onPrompt: prompt => chat.primeInput(prompt),
  atmosphere,
});
settings = new SettingsPanel({ api, onSave: config => { applyConfig(config); runtime.refresh(config); } });
const onboarding = new Onboarding({ overlay: document.querySelector("#onboarding"), api, atmosphere: onboardingAtmosphere, onComplete: config => { applyConfig(config); runtime.refresh(config); } });

document.querySelector("#motion-status").addEventListener("click", async () => {
  const modes = ["static", "ambient", "dynamic"];
  const current = state.config.interface.motion.mode;
  const mode = modes[(modes.indexOf(current) + 1) % modes.length];
  const config = await api("/api/settings", { method: "POST", body: JSON.stringify({ interface: { motion: { ...state.config.interface.motion, mode } } }) });
  applyConfig(config);
});

matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => { if (state.config?.interface.appearance === "system") applyTheme("system"); });

// Node display names and the model list are cosmetic, so a failure here
// must not stop the app from starting.
async function loadComputeLabels() {
  try {
    const nodes = await api("/api/nodes");
    chat.setNodeNames(Object.fromEntries(nodes.map(node => [node.id, node.display_name])));
  } catch { /* Auto routing works without these labels. */ }
}

async function bootstrap() {
  try {
    const [config] = await Promise.all([api("/api/settings"), loadConversations()]);
    applyConfig(config);
    if (!config.onboarding.complete) onboarding.show();
    await Promise.all([loadComputeLabels(), runtime.refresh(config)]);
  } catch (error) {
    document.querySelector("#connection-label").textContent = "Offline";
    document.querySelector("#system-activity").textContent = "Rivet could not finish starting. Refresh to try again.";
    console.error(error);
  }
}

bootstrap();
setInterval(() => { if (!document.hidden && state.config) runtime.refresh(state.config); }, 45000);
