export class Sidebar {
  constructor({ app, list, onSelect, onNew, onDelete }) {
    this.app = app;
    this.list = list;
    this.onSelect = onSelect;
    this.onDelete = onDelete;
    this.activeId = null;
    this.collapseButton = document.querySelector("#collapse-sidebar");
    this.collapseButton.addEventListener("click", () => {
      if (innerWidth <= 760) return;
      app.classList.toggle("sidebar-collapsed");
      localStorage.setItem("rivet-sidebar-collapsed", String(app.classList.contains("sidebar-collapsed")));
      this.syncCollapseControl();
    });
    document.querySelector("#open-sidebar").addEventListener("click", () => app.classList.add("sidebar-open"));
    document.querySelector("#close-sidebar").addEventListener("click", () => app.classList.remove("sidebar-open"));
    document.querySelector("#scrim").addEventListener("click", () => app.classList.remove("sidebar-open"));
    document.querySelector("#new-chat").addEventListener("click", () => { app.classList.remove("sidebar-open"); onNew(); });
    if (localStorage.getItem("rivet-sidebar-collapsed") === "true") app.classList.add("sidebar-collapsed");
    this.syncCollapseControl();
  }

  syncCollapseControl() {
    const collapsed = this.app.classList.contains("sidebar-collapsed");
    this.collapseButton.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
    this.collapseButton.dataset.tooltip = collapsed
      ? "Expand the conversation sidebar."
      : "Collapse the conversation sidebar to leave more room for the current session.";
  }

  groupDate(dateString) {
    const date = new Date(dateString);
    const today = new Date();
    const yesterday = new Date(); yesterday.setDate(today.getDate() - 1);
    if (date.toDateString() === today.toDateString()) return "Today";
    if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
    return "Earlier";
  }

  render(conversations) {
    this.list.replaceChildren();
    if (!conversations.length) {
      const empty = document.createElement("div");
      empty.className = "empty-chats nav-label";
      empty.textContent = "Your conversations will appear here.";
      this.list.append(empty);
      return;
    }
    const groups = Object.groupBy ? Object.groupBy(conversations, c => this.groupDate(c.updated_at)) : conversations.reduce((acc, c) => ((acc[this.groupDate(c.updated_at)] ||= []).push(c), acc), {});
    for (const [label, items] of Object.entries(groups)) {
      const group = document.createElement("div"); group.className = "conversation-group nav-label";
      const title = document.createElement("div"); title.className = "conversation-group-title"; title.textContent = label; group.append(title);
      items.forEach(conversation => {
        const row = document.createElement("div");
        row.className = `conversation-row${conversation.id === this.activeId ? " active" : ""}`;
        const button = document.createElement("button");
        button.className = "conversation-item";
        button.textContent = conversation.title;
        button.title = conversation.title;
        button.addEventListener("click", () => { this.app.classList.remove("sidebar-open"); this.onSelect(conversation.id); });
        const remove = document.createElement("button");
        remove.className = "conversation-delete";
        remove.type = "button";
        remove.textContent = "×";
        remove.setAttribute("aria-label", `Delete conversation: ${conversation.title}`);
        remove.addEventListener("click", async event => {
          event.stopPropagation();
          if (!confirm(`Delete “${conversation.title}”?\n\nThis permanently removes the conversation and its messages.`)) return;
          remove.disabled = true;
          await this.onDelete(conversation);
        });
        row.append(button, remove);
        group.append(row);
      });
      this.list.append(group);
    }
  }
}
