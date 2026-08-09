export class ContextTooltip {
  constructor(element, delay = 950) {
    this.element = element;
    this.delay = delay;
    this.timer = null;
    this.target = null;

    document.addEventListener("pointerover", event => this.queue(event.target.closest?.("[data-tooltip]")));
    document.addEventListener("pointerout", event => {
      const target = event.target.closest?.("[data-tooltip]");
      if (target && !target.contains(event.relatedTarget)) this.hide();
    });
    document.addEventListener("focusin", event => this.queue(event.target.closest?.("[data-tooltip]"), 450));
    document.addEventListener("focusout", () => this.hide());
    document.addEventListener("click", () => this.hide());
    document.addEventListener("keydown", event => { if (event.key === "Escape") this.hide(); });
    addEventListener("scroll", () => this.hide(), { passive: true, capture: true });
    addEventListener("resize", () => this.hide(), { passive: true });
  }

  queue(target, delay = this.delay) {
    if (!target || target === this.target) return;
    this.hide();
    this.target = target;
    this.timer = setTimeout(() => this.show(target), delay);
  }

  show(target) {
    if (this.target !== target || !target.isConnected) return;
    this.element.textContent = target.dataset.tooltip;
    this.element.hidden = false;
    this.element.dataset.visible = "true";
    const anchor = target.getBoundingClientRect();
    const tip = this.element.getBoundingClientRect();
    const left = Math.min(innerWidth - tip.width - 12, Math.max(12, anchor.left + anchor.width / 2 - tip.width / 2));
    const below = anchor.bottom + 12;
    const top = below + tip.height <= innerHeight - 12 ? below : Math.max(12, anchor.top - tip.height - 12);
    this.element.style.left = `${left}px`;
    this.element.style.top = `${top}px`;
  }

  hide() {
    clearTimeout(this.timer);
    this.timer = null;
    this.target = null;
    this.element.hidden = true;
    delete this.element.dataset.visible;
  }
}
