(() => {
  "use strict";
  const widget = document.getElementById("concierge");
  if (!widget) return;
  const toggle = document.getElementById("concierge-toggle");
  const close = document.getElementById("concierge-close");
  const reset = document.getElementById("concierge-reset");
  const log = document.getElementById("concierge-log");
  const form = document.getElementById("concierge-form");
  const input = document.getElementById("concierge-input");
  const csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;
  let busy = false;

  function setOpen(open) {
    widget.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    if (open) input.focus();
  }
  toggle.addEventListener("click", () => setOpen(widget.hidden));
  close.addEventListener("click", () => setOpen(false));
  reset.addEventListener("click", async () => {
    if (busy) return;
    try {
      const response = await fetch("/api/chat/reset/", {
        method: "POST", credentials: "same-origin", headers: {"X-CSRFToken": csrf}
      });
      if (!response.ok) throw new Error("Не удалось начать новый диалог.");
      log.replaceChildren();
      bubble("Начнём заново. Какая услуга вас интересует?");
      input.focus();
    } catch (error) { bubble(error.message); }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !widget.hidden) setOpen(false);
  });

  function bubble(text, mine = false) {
    const item = document.createElement("div");
    item.className = "chat-bubble" + (mine ? " user" : "");
    item.textContent = text;
    log.append(item);
    log.scrollTop = log.scrollHeight;
    return item;
  }
  async function ask(text) {
    if (!text || busy) return;
    busy = true;
    bubble(text, true);
    const pending = bubble("Подбираю подходящую услугу…");
    try {
      const response = await fetch("/api/chat/", {
        method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRFToken": csrf},
        body: JSON.stringify({message: text})
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не получилось ответить. Попробуйте ещё раз.");
      pending.textContent = data.reply;
      if (data.recommended_service) {
        const link = document.createElement("a");
        link.href = `/booking/?service=${encodeURIComponent(data.recommended_service.id)}`;
        link.className = "button button-dark mt-2";
        link.textContent = "Выбрать день и мастера ↗";
        pending.append(document.createElement("br"), link);
      }
    } catch (error) {
      pending.textContent = error.message;
    } finally {
      busy = false;
      input.focus();
    }
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    input.value = "";
    ask(text);
  });
  document.querySelectorAll("[data-prompt]").forEach((item) => {
    item.addEventListener("click", () => { setOpen(true); ask(item.dataset.prompt); });
  });

  const telegram = window.Telegram?.WebApp;
  if (telegram?.initData) {
    telegram.ready();
    telegram.expand();
    telegram.setHeaderColor("#fff6f7");
    telegram.setBackgroundColor("#fff8f7");
  }
})();
