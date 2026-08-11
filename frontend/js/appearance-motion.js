const motionSelect = document.querySelector("#settings-motion");
const speedControl = document.querySelector("#settings-speed-control");
const speedInput = document.querySelector("#settings-speed");
const speedOutput = document.querySelector("#speed-output");
const reactionControl = document.querySelector("#settings-reaction-control");
const reactionInput = document.querySelector("#settings-reaction");
const reactionOutput = document.querySelector("#reaction-output");
const modeNote = document.querySelector("#motion-mode-note");
const motionButton = document.querySelector("#motion-status");
const settingsDialog = document.querySelector("#settings-dialog");

const modeNotes = {
  static: "Static holds one polished atmospheric frame and uses no continuous animation.",
  ambient: "Ambient moves as a calm, organic field without reacting to work or system state.",
  dynamic: "Dynamic breathes continuously and reacts to routing, generation, completion, warnings, and errors.",
};

function syncMotionSettings() {
  const appMode = document.querySelector("#app")?.dataset.motion || "dynamic";
  const mode = settingsDialog?.open ? motionSelect?.value || appMode : appMode;
  const staticMode = mode === "static";
  const dynamicMode = mode === "dynamic";
  if (speedInput) speedInput.disabled = staticMode;
  if (reactionInput) reactionInput.disabled = !dynamicMode;
  speedControl?.classList.toggle("is-disabled", staticMode);
  reactionControl?.classList.toggle("is-disabled", !dynamicMode);
  if (modeNote) modeNote.textContent = modeNotes[mode];
  if (speedInput && speedOutput) speedOutput.textContent = `${Math.round(Number(speedInput.value))}`;
  if (motionButton) {
    const order = ["static", "ambient", "dynamic"];
    const nextMode = order[(order.indexOf(mode) + 1) % order.length];
    motionButton.dataset.tooltip = `${modeNotes[mode]} Click to switch to ${nextMode[0].toUpperCase()}${nextMode.slice(1)}.`;
  }
}

if (reactionInput) {
  reactionOutput.textContent = `${Math.round(Number(reactionInput.value))}`;
  reactionInput.addEventListener("input", () => {
    const reaction = Number(reactionInput.value) / 50;
    reactionOutput.textContent = `${Math.round(Number(reactionInput.value))}`;
    document.dispatchEvent(new CustomEvent("rivet:atmosphere-config", { detail: { reaction } }));
  });
}

motionSelect?.addEventListener("change", syncMotionSettings);
speedInput?.addEventListener("input", syncMotionSettings);
motionButton?.addEventListener("click", () => {
  requestAnimationFrame(() => requestAnimationFrame(syncMotionSettings));
});
new MutationObserver(syncMotionSettings).observe(document.querySelector("#app"), {
  attributes: true,
  attributeFilter: ["data-motion"],
});
if (settingsDialog) {
  new MutationObserver(() => {
    if (settingsDialog.open) requestAnimationFrame(() => requestAnimationFrame(syncMotionSettings));
  }).observe(settingsDialog, { attributes: true, attributeFilter: ["open"] });
}
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-section-target='appearance'], [data-settings-section='appearance']")) {
    requestAnimationFrame(() => requestAnimationFrame(syncMotionSettings));
  }
});
syncMotionSettings();
setTimeout(syncMotionSettings, 600);
