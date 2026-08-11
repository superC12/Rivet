const TAU = Math.PI * 2;

const STATE_PROFILES = Object.freeze({
  idle:       { pace: 0.28, amplitude: 0.58, turbulence: 0.28, lift: 0.00, focus: 0.00, energy: 0.82, tint: "accent" },
  routing:    { pace: 0.70, amplitude: 0.74, turbulence: 0.50, lift: 0.09, focus: 0.70, energy: 0.98, tint: "azure" },
  local:      { pace: 0.31, amplitude: 0.54, turbulence: 0.19, lift: 0.01, focus: 0.14, energy: 0.86, tint: "mint" },
  remote:     { pace: 0.60, amplitude: 0.72, turbulence: 0.48, lift: 0.07, focus: 0.44, energy: 0.96, tint: "azure" },
  waking:     { pace: 0.90, amplitude: 0.92, turbulence: 0.68, lift: 0.16, focus: 0.78, energy: 1.00, tint: "amber" },
  cloud:      { pace: 0.54, amplitude: 0.70, turbulence: 0.42, lift: 0.07, focus: 0.40, energy: 0.94, tint: "violet" },
  generating: { pace: 0.46, amplitude: 0.68, turbulence: 0.39, lift: 0.05, focus: 0.34, energy: 0.94, tint: "accent" },
  complete:   { pace: 0.22, amplitude: 0.66, turbulence: 0.14, lift: -0.04, focus: 0.00, energy: 0.90, tint: "mint" },
  warning:    { pace: 0.62, amplitude: 0.88, turbulence: 0.94, lift: 0.12, focus: 0.38, energy: 1.00, tint: "amber" },
  error:      { pace: 0.08, amplitude: 1.08, turbulence: 1.10, lift: 0.22, focus: 0.88, energy: 1.00, tint: "red" },
});

const TINTS = Object.freeze({
  accent: [0, 0, 0],
  mint: [82, 226, 158],
  amber: [228, 180, 95],
  azure: [99, 167, 255],
  violet: [166, 126, 255],
  red: [255, 91, 103],
});

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const mix = (from, to, amount) => from + (to - from) * amount;

function parseColor(value, fallback = [0, 0, 0]) {
  if (!value) return fallback;
  const rgb = value.match(/rgba?\(\s*([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)/i);
  if (rgb) return rgb.slice(1, 4).map(Number);
  const hex = value.trim().match(/^#([\da-f]{6})$/i);
  if (hex) return [0, 2, 4].map((offset) => parseInt(hex[1].slice(offset, offset + 2), 16));
  return fallback;
}

export class Atmosphere {
  constructor(canvas) {
    this.canvas = canvas;
    this.context = canvas?.getContext("2d", { alpha: true });
    this.mode = "dynamic";
    this.state = "idle";
    this.intensity = 0.18;
    this.speed = 1.1;
    this.reaction = 0.9;
    this.phase = 0;
    this.lastFrame = 0;
    this.stateAge = 0;
    this.impulse = 0;
    this.pointer = { x: 0.5, y: 0.74, active: 0 };
    this.accent = [0, 0, 0];
    this.currentTint = [...this.accent];
    this.motion = { ...STATE_PROFILES.idle };
    this.frame = 0;
    this.raf = 0;
    this.hidden = document.hidden;
    this.reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.accentObserver = new MutationObserver(() => {
      const inlineAccent = document.documentElement.style.getPropertyValue("--accent");
      this.refreshAccent(inlineAccent || undefined);
    });

    if (!canvas || !this.context) return;
    this.resizeObserver.observe(canvas);
    this.accentObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["style"],
    });
    document.addEventListener("visibilitychange", () => {
      this.hidden = document.hidden;
      if (!this.hidden && this.mode !== "static") this.start();
    });
    document.addEventListener("rivet:atmosphere-state", (event) => {
      this.setState(event.detail?.state, { retrigger: true });
    });
    document.addEventListener("rivet:atmosphere-config", (event) => {
      this.configure(event.detail || {});
    });
    document.addEventListener("rivet:accentchange", (event) => {
      this.accentChanged(event.detail?.color);
    });
    window.addEventListener("pointermove", (event) => {
      if (this.mode !== "dynamic") return;
      this.pointer.x = event.clientX / Math.max(innerWidth, 1);
      this.pointer.y = event.clientY / Math.max(innerHeight, 1);
      this.pointer.active = 1;
    }, { passive: true });
    this.reducedMotion.addEventListener?.("change", () => this.configure({ mode: this.mode }));
    this.refreshAccent(document.documentElement.style.getPropertyValue("--accent"));
    this.resize();
    this.start();
  }

  configure(motion = {}) {
    const requestedMode = motion.mode || this.mode || "dynamic";
    this.mode = this.reducedMotion.matches ? "static" : requestedMode;
    this.intensity = clamp(Number(motion.intensity ?? this.intensity), 0, 0.36);
    this.speed = clamp(Number(motion.speed ?? this.speed), 0, 2);
    const reaction = motion.reaction ?? this.reaction;
    this.reaction = clamp(Number(reaction), 0, 2);
    this.canvas.dataset.atmosphereMode = this.mode;
    this.canvas.dataset.atmosphereState = this.state;
    if (this.mode === "static") {
      this.stop();
      this.drawStatic();
    } else {
      this.start();
    }
    return this.mode;
  }

  setState(nextState = "idle", options = {}) {
    const state = STATE_PROFILES[nextState] ? nextState : "idle";
    const changed = state !== this.state;
    this.state = state;
    this.canvas.dataset.atmosphereState = state;
    if (changed || options.retrigger) this.stateAge = 0;

    if (this.mode === "dynamic") {
      if (state === "error") this.impulse = Math.max(this.impulse, 1.85);
      else if (state === "warning") this.impulse = Math.max(this.impulse, 1.05);
      else if (state === "complete") this.impulse = Math.max(this.impulse, 0.62);
      else if (state === "routing" || state === "waking") this.impulse = Math.max(this.impulse, 0.38);
      else if (state === "generating" && !changed) this.impulse = Math.min(0.38, this.impulse + 0.055);
    }

    if (this.mode === "static") this.drawStatic();
  }

  accentChanged(value) {
    if (!value) return;
    this.accent = value === "transparent" ? [0, 0, 0] : parseColor(value, this.accent);
    if (this.mode === "static") this.drawStatic();
  }

  setAccent(value) {
    this.accentChanged(value);
  }

  refreshAccent(value) {
    this.accentChanged(value);
  }

  invalidateAccent(value) {
    this.refreshAccent(value);
  }

  resize() {
    if (!this.canvas || !this.context) return;
    const rect = this.canvas.getBoundingClientRect();
    const scale = Math.min(devicePixelRatio || 1, 1.5);
    const width = Math.max(1, Math.round(rect.width * scale));
    const height = Math.max(1, Math.round(rect.height * scale));
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
    if (this.mode === "static") this.drawStatic();
  }

  start() {
    if (this.raf || this.hidden || this.mode === "static" || !this.context) return;
    this.lastFrame = performance.now();
    this.raf = requestAnimationFrame((time) => this.tick(time));
  }

  stop() {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  tick(time) {
    this.raf = 0;
    if (this.hidden || this.mode === "static") return;
    const elapsed = clamp((time - this.lastFrame) / 1000, 0, 0.08);
    if (elapsed < 0.030) {
      this.raf = requestAnimationFrame((next) => this.tick(next));
      return;
    }
    this.lastFrame = time;
    this.update(elapsed);
    this.paint();
    this.raf = requestAnimationFrame((next) => this.tick(next));
  }

  update(elapsed) {
    const base = STATE_PROFILES.idle;
    const requested = this.mode === "dynamic" ? STATE_PROFILES[this.state] : base;
    const response = this.mode === "dynamic" ? this.reaction : 0;
    const target = {};
    for (const key of ["pace", "amplitude", "turbulence", "lift", "focus", "energy"]) {
      target[key] = mix(base[key], requested[key], response);
      this.motion[key] = mix(this.motion[key], target[key], 1 - Math.exp(-elapsed * 2.2));
    }
    const targetTint = this.mode === "dynamic" && requested.tint !== "accent"
      ? TINTS[requested.tint]
      : this.accent;
    const tintEase = 1 - Math.exp(-elapsed * (this.state === "error" ? 12 : 3.8));
    this.currentTint = this.currentTint.map((channel, index) => mix(channel, targetTint[index], tintEase));

    this.stateAge += elapsed;
    const pressure = this.mode === "dynamic" && ["routing", "waking"].includes(this.state)
      ? Math.min(this.stateAge / 9, 1) * 0.16 * this.reaction
      : 0;
    this.phase += elapsed * this.speed * (0.50 + this.motion.pace + pressure);
    this.impulse *= Math.exp(-elapsed * (this.state === "error" ? 1.28 : 2.0));
    this.pointer.active *= Math.exp(-elapsed * 0.55);
  }

  drawStatic() {
    this.motion = { ...STATE_PROFILES.idle };
    const requested = STATE_PROFILES[this.state] || STATE_PROFILES.idle;
    const tint = requested.tint === "accent" ? this.accent : TINTS[requested.tint];
    this.currentTint = [...tint];
    this.paint(true);
  }

  paint(frozen = false) {
    const ctx = this.context;
    const width = this.canvas.width;
    const height = this.canvas.height;
    if (!width || !height) return;
    ctx.clearRect(0, 0, width, height);

    const t = frozen ? 2.15 : this.phase;
    const reaction = this.mode === "dynamic" ? this.reaction : 0;
    const impulse = frozen ? 0 : this.impulse * reaction;
    const pointerPull = this.mode === "dynamic" ? this.pointer.active * 0.055 : 0;
    const red = Math.round(this.currentTint[0]);
    const green = Math.round(this.currentTint[1]);
    const blue = Math.round(this.currentTint[2]);
    const alpha = Math.min(.18, Math.max(.08, this.intensity * this.motion.energy));
    const crash = this.mode === "dynamic" && this.state === "error"
      ? clamp(impulse / Math.max(reaction, 0.01), 0, 1.4)
      : 0;
    this.canvas.dataset.atmosphereCrash = crash > 0.025 ? "erupting" : "off";
    this.canvas.dataset.atmosphereTint = STATE_PROFILES[this.state]?.tint || "accent";
    this.canvas.dataset.atmosphereColor = `${red},${green},${blue}`;

    ctx.save();
    ctx.globalCompositeOperation = "source-over";
    const base = ctx.createLinearGradient(0, height * 0.38, 0, height);
    base.addColorStop(0, `rgba(${red}, ${green}, ${blue}, 0)`);
    base.addColorStop(1, `rgba(${red}, ${green}, ${blue}, ${alpha * 0.36})`);
    ctx.fillStyle = base;
    ctx.fillRect(0, height * 0.30, width, height * 0.70);
    ctx.restore();

    this.paintFog(ctx, width, height, t, alpha, [red, green, blue], impulse, pointerPull);
    this.paintCrash(ctx, width, height, alpha, crash);
    this.paintWaves(ctx, width, height, t, alpha, [red, green, blue], impulse, pointerPull, crash);

    this.frame += 1;
    this.canvas.dataset.atmosphereFrame = String(this.frame);
  }

  paintFog(ctx, width, height, t, alpha, color, impulse, pointerPull) {
    const [red, green, blue] = color;
    const blooms = [
      { x: 0.20 + Math.sin(t * 0.21 + 0.8) * 0.18, y: 0.82 + Math.cos(t * 0.16) * 0.09, r: 0.42, a: 0.38 },
      { x: 0.56 + Math.cos(t * 0.14 + 2.4) * 0.27, y: 0.76 + Math.sin(t * 0.23) * 0.11, r: 0.36, a: 0.30 },
      { x: 0.84 + Math.sin(t * 0.18 + 4.2) * 0.15, y: 0.88 + Math.cos(t * 0.12) * 0.07, r: 0.30, a: 0.24 },
    ];
    ctx.save();
    ctx.globalCompositeOperation = "screen";
    for (const bloom of blooms) {
      const x = width * mix(bloom.x, this.pointer.x, pointerPull);
      const y = height * (bloom.y - this.motion.lift - impulse * 0.05);
      const radius = Math.max(width, height) * bloom.r * (1 + impulse * 0.11);
      const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius);
      gradient.addColorStop(0, `rgba(${red}, ${green}, ${blue}, ${alpha * bloom.a})`);
      gradient.addColorStop(0.48, `rgba(${red}, ${green}, ${blue}, ${alpha * bloom.a * 0.42})`);
      gradient.addColorStop(1, `rgba(${red}, ${green}, ${blue}, 0)`);
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, width, height);
    }
    ctx.restore();
  }

  paintCrash(ctx, width, height, alpha, crash) {
    if (crash < 0.025) return;
    const strength = clamp(crash, 0, 1.25);
    const centerX = width * 0.54;
    const flash = ctx.createRadialGradient(centerX, height * 0.77, 0, centerX, height * 0.77, width * 0.44);
    flash.addColorStop(0, `rgba(255, 56, 74, ${alpha * strength * 0.72})`);
    flash.addColorStop(0.24, `rgba(255, 70, 86, ${alpha * strength * 0.30})`);
    flash.addColorStop(1, "rgba(255, 70, 86, 0)");
    ctx.save();
    ctx.globalCompositeOperation = "screen";
    ctx.fillStyle = flash;
    ctx.fillRect(0, 0, width, height);
    ctx.restore();

    // A narrow, vertically stretched bloom makes the field itself surge upward.
    ctx.save();
    ctx.globalCompositeOperation = "screen";
    ctx.translate(centerX, height * 0.79);
    ctx.scale(0.30 + (1 - strength) * 0.12, 1.65 + strength * 0.50);
    const plumeRadius = height * 0.26;
    const plume = ctx.createRadialGradient(0, 0, 0, 0, 0, plumeRadius);
    plume.addColorStop(0, `rgba(255, 66, 82, ${alpha * strength * 1.15})`);
    plume.addColorStop(0.32, `rgba(255, 70, 86, ${alpha * strength * 0.62})`);
    plume.addColorStop(1, "rgba(255, 70, 86, 0)");
    ctx.fillStyle = plume;
    ctx.filter = `blur(${Math.max(18, height * 0.028)}px)`;
    ctx.fillRect(-plumeRadius, -plumeRadius, plumeRadius * 2, plumeRadius * 2);
    ctx.restore();

    // Shape the same colored fog into a fast crest, without adding hard geometry.
    ctx.save();
    ctx.globalCompositeOperation = "screen";
    ctx.filter = `blur(${Math.max(16, height * 0.026)}px)`;
    const crestTop = height * (0.22 + (1 - Math.min(strength, 1)) * 0.22);
    const crest = ctx.createLinearGradient(0, crestTop, 0, height * 0.88);
    crest.addColorStop(0, `rgba(255, 72, 88, ${alpha * strength * 1.28})`);
    crest.addColorStop(0.48, `rgba(255, 62, 78, ${alpha * strength * 0.88})`);
    crest.addColorStop(1, "rgba(255, 62, 78, 0)");
    ctx.fillStyle = crest;
    ctx.beginPath();
    ctx.moveTo(centerX - width * 0.18, height * 0.94);
    ctx.bezierCurveTo(
      centerX - width * 0.11, height * 0.80,
      centerX - width * 0.038, height * 0.59,
      centerX, crestTop,
    );
    ctx.bezierCurveTo(
      centerX + width * 0.034, height * 0.60,
      centerX + width * 0.13, height * 0.81,
      centerX + width * 0.19, height * 0.94,
    );
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  paintWaves(ctx, width, height, t, alpha, color, impulse, pointerPull, crash = 0) {
    const [red, green, blue] = color;
    const warningChop = this.mode === "dynamic" && this.state === "warning" ? this.reaction : 0;
    const layers = [
      { y: 0.78, amp: 0.060, freq: 1.15, pace: 0.29, blur: 58, opacity: 0.46, phase: 0.4 },
      { y: 0.84, amp: 0.085, freq: 1.72, pace: -0.19, blur: 76, opacity: 0.34, phase: 2.1 },
      { y: 0.91, amp: 0.110, freq: 2.32, pace: 0.13, blur: 92, opacity: 0.25, phase: 4.7 },
    ];
    ctx.save();
    ctx.globalCompositeOperation = "screen";
    for (const layer of layers) {
      ctx.beginPath();
      const segments = 72;
      for (let index = 0; index <= segments; index += 1) {
        const normalized = index / segments;
        const organic =
          Math.sin(normalized * TAU * layer.freq + t * layer.pace + layer.phase) * 0.58 +
          Math.sin(normalized * TAU * (layer.freq * 0.47) - t * 0.17 + layer.phase * 1.7) * 0.27 +
          Math.sin(normalized * TAU * (layer.freq * 2.13) + t * 0.09) * 0.15;
        const focus = Math.exp(-Math.pow(normalized - 0.5, 2) / 0.055) * this.motion.focus;
        const pointerWave = Math.exp(-Math.pow(normalized - this.pointer.x, 2) / 0.018) * pointerPull;
        const turbulence = 1 + this.motion.turbulence * Math.sin(normalized * 17 + t * 0.31) * 0.16;
        const crashDistance = normalized - 0.54;
        const crashSpike = Math.exp(-Math.abs(crashDistance) * 30) * crash * 0.31;
        const crashRipple = Math.sin(crashDistance * 82 - t * 1.8) * Math.exp(-Math.abs(crashDistance) * 8) * crash * 0.045;
        const warningRipple = (
          Math.sin(normalized * 44 + t * 2.4) * 0.017 +
          Math.sin(normalized * 71 - t * 1.7) * 0.010
        ) * warningChop;
        const y = height * (
          layer.y - this.motion.lift -
          organic * layer.amp * this.motion.amplitude * turbulence -
          focus * 0.025 - pointerWave * 0.045 - impulse * Math.sin(normalized * Math.PI) * 0.055 -
          crashSpike - crashRipple - warningRipple
        );
        const x = normalized * width;
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.lineTo(width, height * 1.08);
      ctx.lineTo(0, height * 1.08);
      ctx.closePath();
      const gradient = ctx.createLinearGradient(0, height * 0.55, 0, height);
      gradient.addColorStop(0, `rgba(${red}, ${green}, ${blue}, 0)`);
      gradient.addColorStop(0.42, `rgba(${red}, ${green}, ${blue}, ${alpha * layer.opacity * 0.46})`);
      gradient.addColorStop(1, `rgba(${red}, ${green}, ${blue}, ${alpha * layer.opacity})`);
      ctx.filter = `blur(${layer.blur}px)`;
      ctx.fillStyle = gradient;
      ctx.fill();
    }
    ctx.filter = "none";
    ctx.restore();
  }
}

export { STATE_PROFILES };
