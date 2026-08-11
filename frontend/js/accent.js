const CONTEXTS = [
  {
    name: "Creative",
    color: "#ff6b6b",
    patterns: [/\b(story|poem|creative|design|illustrat|artwork|music|lyrics|brainstorm|character|novel|screenplay|logo|visual)\b/gi],
  },
  {
    name: "Math & science",
    color: "#5fd39f",
    patterns: [/\b(math|equation|calculate|algebra|geometry|calculus|physics|chemistry|biology|science|statistics|probability|theorem|formula|dataset)\b/gi],
  },
  {
    name: "Code & systems",
    color: "#63a7ff",
    patterns: [/\b(code|coding|debug|python|javascript|typescript|api|docker|linux|server|database|sql|function|class|repository|deploy|network|homelab)\b/gi],
  },
  {
    name: "Analysis & planning",
    color: "#a88cff",
    patterns: [/\b(analy[sz]e|analysis|research|compare|strategy|plan|evaluate|review|reason|investigate|decision|outline)\b/gi],
  },
  {
    name: "Action & automation",
    color: "#e4b45f",
    patterns: [/\b(add|create|send|schedule|book|remind|delete|remove|cancel|automate|automation|workflow|n8n|task|calendar|email)\b/gi],
  },
];

function score(text, context) {
  return context.patterns.reduce((total, pattern) => total + (text.match(pattern)?.length || 0), 0);
}

export class AccentController {
  constructor(label) {
    this.label = label;
    this.mode = "adaptive";
    this.baseColor = "#e4b45f";
    this.lastText = "";
    this.assistantName = "Your assistant";
  }

  setAssistantName(name) { this.assistantName = name; }

  clear() {
    this.lastText = "";
    document.documentElement.style.setProperty("--accent", "transparent");
    document.documentElement.dataset.accentContext = "unconfigured";
    if (this.label) {
      this.label.textContent = "Accent · Not configured";
      this.label.dataset.tooltip = "Choose an assistant identity before its visual accent becomes active.";
    }
    dispatchEvent(new CustomEvent("rivet:accentchange", { detail: { color: "transparent", context: "Unconfigured" } }));
  }

  configure(config = {}) {
    this.mode = config.mode === "fixed" ? "fixed" : "adaptive";
    this.baseColor = /^#[0-9a-f]{6}$/i.test(config.color || "") ? config.color : "#e4b45f";
    if (this.mode === "adaptive" && this.lastText) this.adaptTo(this.lastText);
    else this.apply(this.baseColor, this.mode === "adaptive" ? "Ready" : this.baseColor.toUpperCase());
  }

  adaptTo(text) {
    this.lastText = text;
    if (this.mode === "fixed") return this.apply(this.baseColor, this.baseColor.toUpperCase());
    const ranked = CONTEXTS.map(context => ({ context, score: score(text, context) }))
      .sort((left, right) => right.score - left.score);
    const match = ranked[0].score ? ranked[0].context : null;
    return this.apply(match?.color || this.baseColor, match?.name || "Ready");
  }

  reset() {
    this.lastText = "";
    return this.apply(this.baseColor, this.mode === "adaptive" ? "Ready" : this.baseColor.toUpperCase());
  }

  apply(color, context) {
    document.documentElement.style.setProperty("--accent", color);
    document.documentElement.dataset.accentContext = context.toLowerCase().replaceAll(" ", "-");
    if (this.label) {
      this.label.textContent = `${this.mode === "adaptive" ? "Adaptive" : "Fixed"} · ${context}`;
      this.label.dataset.tooltip = this.mode === "adaptive"
        ? `${this.assistantName} matched this request to ${context.toLowerCase()} work and adjusted the interface accent.`
        : "The interface is using your fixed accent color from Appearance settings.";
    }
    dispatchEvent(new CustomEvent("rivet:accentchange", { detail: { color, context } }));
    return { color, context };
  }
}

export { CONTEXTS };
