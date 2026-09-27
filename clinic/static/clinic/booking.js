(() => {
  "use strict";
  const form = document.getElementById("beauty-booking-form");
  if (!form) return;
  const service = document.getElementById("book-service");
  const day = document.getElementById("book-day");
  const master = document.getElementById("book-master");
  const time = document.getElementById("book-time");
  const note = document.getElementById("availability-note");
  const error = document.getElementById("booking-error");
  const submit = document.getElementById("booking-submit");
  const csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;
  let masters = [];
  let requestNumber = 0;

  function reset(select, label) {
    select.replaceChildren(new Option(label, ""));
    select.disabled = true;
  }
  async function loadAvailability() {
    const current = ++requestNumber;
    masters = [];
    reset(master, "Загружаем мастеров…");
    reset(time, "Сначала выберите мастера");
    error.hidden = true;
    if (!service.value || !day.value) {
      reset(master, "Сначала выберите услугу и день");
      note.textContent = "Покажем только доступные часы выбранного дня.";
      return;
    }
    try {
      const params = new URLSearchParams({service: service.value, date: day.value});
      const response = await fetch(`/api/availability/?${params}`, {credentials: "same-origin"});
      const data = await response.json();
      if (current !== requestNumber) return;
      if (!response.ok) throw new Error(data.error || "Не удалось загрузить время.");
      masters = data.masters;
      reset(master, masters.length ? "Выберите мастера" : "На этот день свободных мастеров нет");
      masters.forEach((item) => master.add(new Option(`${item.name} · ${item.specialty}`, item.id)));
      master.disabled = !masters.length;
      if (masters.some((item) => String(item.id) === form.dataset.selectedMaster)) {
        master.value = form.dataset.selectedMaster;
        loadTimes();
      }
      note.textContent = masters.length
        ? `На этот день свободны ${masters.length} мастера. Выберите одного, чтобы увидеть часы.`
        : "Попробуйте соседний день или другую услугу.";
    } catch (cause) {
      reset(master, "Не удалось загрузить мастеров");
      note.textContent = cause.message;
    }
  }
  function loadTimes() {
    const selected = masters.find((item) => String(item.id) === master.value);
    reset(time, selected ? "Выберите время" : "Сначала выберите мастера");
    if (!selected) return;
    selected.slots.forEach((slot) => time.add(new Option(slot.time, slot.id)));
    time.disabled = false;
    note.textContent = `${selected.name}: доступно ${selected.slots.length} вариантов времени.`;
  }
  service.addEventListener("change", loadAvailability);
  day.addEventListener("change", loadAvailability);
  master.addEventListener("change", loadTimes);
  if (service.value && day.value) loadAvailability();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    submit.disabled = true;
    submit.textContent = "Создаём запись…";
    try {
      const response = await fetch("/api/appointments/", {
        method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRFToken": csrf},
        body: JSON.stringify({service: service.value, doctor: master.value, slot: time.value})
      });
      const data = await response.json();
      if (!response.ok) {
        if (response.status === 401) throw new Error("Чтобы записаться, войдите или зарегистрируйтесь.");
        throw new Error(data.error || "Не получилось записаться. Попробуйте ещё раз.");
      }
      form.hidden = true;
      document.getElementById("booking-success-text").textContent = `${data.message} Номер записи: ${data.id}.`;
      document.getElementById("booking-success").hidden = false;
    } catch (cause) {
      error.textContent = cause.message;
      error.hidden = false;
      if (cause.message.includes("время")) loadAvailability();
    } finally {
      submit.disabled = false;
      submit.textContent = "Подтвердить запись ↗";
    }
  });
})();
