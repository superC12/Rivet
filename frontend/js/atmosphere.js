function accentChannels(color) {
  const hex = String(color || "").match(/^#([0-9a-f]{6})$/i);
  if (hex) return [0, 2, 4].map(index => Number.parseInt(hex[1].slice(index, index + 2), 16));
  const channels = String(color || "").match(/[\d.]+/g);
  return channels?.length >= 3 ? channels.slice(0, 3).map(Number) : [228, 180, 95];
}

export class Atmosphere {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas?.getContext("2d", { alpha: true });
    this.mode = "dynamic";
    this.state = "idle";
    this.intensity = .18;
    this.speed = 1;
    this.time = 0;
    this.pointer = { x: .5, y: .7, active: false };
    this.frame = null;
    this.last = 0;
    this.visible = true;
    this.accent = [228, 180, 95];
    this.reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!canvas || !this.ctx) return;
    this.resize = this.resize.bind(this);
    this.draw = this.draw.bind(this);
    addEventListener("resize", this.resize, { passive: true });
    document.addEventListener("visibilitychange", () => {
      this.visible = !document.hidden;
      if (this.visible) this.start(); else this.stop();
    });
    addEventListener("rivet:accentchange", event => {
      this.accent = accentChannels(event.detail?.color);
      if (this.mode === "static") this.drawStatic();
    });
    if (!matchMedia("(pointer: coarse)").matches) {
      addEventListener("pointermove", event => {
        this.pointer.x = event.clientX / innerWidth;
        this.pointer.y = event.clientY / innerHeight;
        this.pointer.active = true;
      }, { passive: true });
      addEventListener("pointerleave", () => { this.pointer.active = false; });
    }
    this.resize();
  }

  configure({ mode, intensity, speed } = {}) {
    if (mode) this.mode = this.reduced ? "static" : mode;
    if (intensity != null) this.intensity = Math.min(.18, Math.max(.08, Number(intensity)));
    if (speed != null) this.speed = Number(speed);
    if (this.mode === "static") { this.stop(); this.drawStatic(); } else this.start();
  }

  setState(state) { this.state = state; }

  resize() {
    const scale = Math.min(devicePixelRatio || 1, innerWidth < 700 ? 1 : 1.35);
    this.canvas.width = Math.round(innerWidth * scale);
    this.canvas.height = Math.round(innerHeight * scale);
    this.canvas.style.width = `${innerWidth}px`;
    this.canvas.style.height = `${innerHeight}px`;
    this.ctx.setTransform(scale, 0, 0, scale, 0, 0);
    if (this.mode === "static") this.drawStatic();
  }

  start() {
    if (!this.frame && this.visible && this.mode !== "static") this.frame = requestAnimationFrame(this.draw);
  }

  stop() { if (this.frame) cancelAnimationFrame(this.frame); this.frame = null; }

  drawStatic() { this.paint(16); }

  draw(timestamp) {
    this.frame = null;
    if (timestamp - this.last < 32) { this.start(); return; }
    const delta = Math.min(50, timestamp - this.last || 16);
    this.last = timestamp;
    const stateSpeed = { idle: .16, routing: .55, local: .24, remote: .48, waking: .7, cloud: .44, generating: .3, complete: .18, warning: .22, error: .04 }[this.state] || .16;
    this.time += delta * .00035 * this.speed * stateSpeed;
    this.paint(this.time);
    this.start();
  }

  paint(t) {
    const { ctx } = this;
    const w = innerWidth, h = innerHeight;
    ctx.clearRect(0, 0, w, h);
    const isLight = document.documentElement.dataset.theme === "light";
    const contextualAccent = this.accent;
    const stateColor = this.state === "error"
      ? [255, 107, 107]
      : ["warning", "routing", "waking"].includes(this.state)
        ? [228, 180, 95]
        : [52, 199, 89];
    const palette = isLight
      ? [[98, 128, 166], contextualAccent, stateColor]
      : [[44, 122, 128], contextualAccent, stateColor];
    const energy = this.state === "warning" ? .86 : this.state === "error" ? .58 : 1;
    const baseY = this.state === "cloud" ? .64 : .76;
    const pointerForce = this.mode === "dynamic" && this.pointer.active ? .018 : 0;
    const alpha = Math.min(.18, Math.max(.08, this.intensity * (isLight ? .82 : 1) * energy));

    palette.forEach((color, index) => {
      const phase = t * (index % 2 ? -1 : 1) + index * 2.2;
      const px = (this.pointer.x - .5) * w * pointerForce * (index + 1);
      const py = (this.pointer.y - .65) * h * pointerForce;
      ctx.beginPath();
      ctx.moveTo(-80, h + 80);
      for (let x = -80; x <= w + 80; x += Math.max(22, w / 48)) {
        const normalized = x / w;
        const broad = Math.sin(normalized * Math.PI * (1.3 + index * .22) + phase) * h * (.055 + index * .012);
        const soft = Math.sin(normalized * Math.PI * 3.1 - phase * .48 + index) * h * .022;
        const converge = this.state === "routing" ? -Math.abs(normalized - .5) * h * .06 : 0;
        ctx.lineTo(x + px, h * (baseY + index * .045) + broad + soft + converge + py);
      }
      ctx.lineTo(w + 80, h + 80);
      ctx.closePath();
      const gradient = ctx.createLinearGradient(0, h * .5, w, h);
      gradient.addColorStop(0, `rgba(${color.join(",")},0)`);
      gradient.addColorStop(.22, `rgba(${color.join(",")},${alpha * .62})`);
      gradient.addColorStop(.62, `rgba(${color.join(",")},${alpha})`);
      gradient.addColorStop(1, `rgba(${color.join(",")},0)`);
      ctx.fillStyle = gradient;
      ctx.filter = `blur(${22 + index * 13}px)`;
      ctx.fill();
    });
    ctx.filter = "none";
  }
}
