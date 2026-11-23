(() => {
  "use strict";

  const entries = (window.GAMES_DATA || []).slice().sort((a, b) => b.year - a.year);
  if (!entries.length) return;

  const byId = (id) => document.getElementById(id);
  const tabs = byId("year-tabs");
  const panel = byId("year-panel");
  const placeholder = byId("cover-placeholder");
  const mobile = window.matchMedia("(max-width: 760px)");
  const buttons = [];
  let selectedYear;

  const calendarIcon = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="4" y="5" width="16" height="16" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="M8 3v4m8-4v4M4 11h16" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>';

  function setText(id, value, emptyText = "") {
    const node = byId(id);
    const hasText = typeof value === "string" && value.trim().length > 0;
    node.textContent = hasText ? value : emptyText;
    node.classList.toggle("is-placeholder", !hasText);
  }

  function showEntry(entry) {
    const year = String(entry.year);
    if (selectedYear === year) return;
    selectedYear = year;

    buttons.forEach((button) => {
      const active = button.dataset.year === year;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    });
    panel.setAttribute("aria-labelledby", `year-tab-${year}`);
    ["selected-year", "banner-year", "cover-year"].forEach((id) => { byId(id).textContent = year; });
    byId("year-caption").textContent = `${year}年度游戏`;
    setText("game-title", entry.title, "To be chosen");
    setText("game-summary", entry.summary);
    ["why", "moments", "reflections"].forEach((key) => {
      setText(`note-${key}`, entry.notes?.[key]);
    });
    byId("cover-caption").textContent = `My ${year} selection · ${entry.title?.trim() || "To be revealed"}`;
    const coverSource = byId("cover-source");
    coverSource.hidden = !entry.coverSource;
    if (entry.coverSource) coverSource.href = entry.coverSource;
    else coverSource.removeAttribute("href");

    byId("cover-frame").querySelector("img")?.remove();
    placeholder.hidden = false;
    byId("cover-label").textContent = "Cover coming soon";
    if (entry.cover?.trim()) {
      const image = new Image();
      image.alt = entry.coverAlt?.trim() || `${entry.title?.trim() || year + " game of the year"} cover art`;
      image.hidden = true;
      image.addEventListener("load", () => {
        if (!image.isConnected) return;
        placeholder.hidden = true;
        image.hidden = false;
      });
      image.addEventListener("error", () => {
        if (image.isConnected) byId("cover-label").textContent = "Cover unavailable";
      });
      byId("cover-frame").append(image);
      image.src = entry.cover;
    }

    document.title = `${year} · My games of the year · Yuqi Liu`;
    byId("selection-status").textContent = `Showing the ${year} annual selection.`;
  }

  function activate(entry) {
    showEntry(entry);
    // A fragment makes each year bookmarkable and supports browser back/forward.
    if (window.location.hash !== `#${entry.year}`) window.location.hash = entry.year;
  }

  entries.forEach((entry) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "year-tab";
    button.id = `year-tab-${entry.year}`;
    button.dataset.year = String(entry.year);
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", "year-panel");
    button.innerHTML = calendarIcon;
    const label = document.createElement("span");
    label.textContent = entry.year;
    button.append(label);
    button.addEventListener("click", () => activate(entry));
    tabs.append(button);
    buttons.push(button);
  });

  tabs.addEventListener("keydown", (event) => {
    const current = buttons.indexOf(document.activeElement);
    if (current < 0) return;
    const previousKey = mobile.matches ? "ArrowLeft" : "ArrowUp";
    const nextKey = mobile.matches ? "ArrowRight" : "ArrowDown";
    let next;
    if (event.key === nextKey) next = (current + 1) % buttons.length;
    else if (event.key === previousKey) next = (current - 1 + buttons.length) % buttons.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = buttons.length - 1;
    else return;
    event.preventDefault();
    buttons[next].focus();
    activate(entries[next]);
  });

  function syncOrientation() {
    tabs.setAttribute("aria-orientation", mobile.matches ? "horizontal" : "vertical");
  }

  function readHash() {
    const year = window.location.hash.slice(1);
    showEntry(entries.find((entry) => String(entry.year) === year) || entries[0]);
  }

  document.querySelector(".skip-link").addEventListener("click", (event) => {
    // Move to the content without replacing the selected year's URL fragment.
    event.preventDefault();
    panel.focus({ preventScroll: true });
    panel.scrollIntoView({ block: "start" });
  });

  panel.setAttribute("role", "tabpanel");
  tabs.hidden = false;
  syncOrientation();
  mobile.addEventListener("change", syncOrientation);
  window.addEventListener("hashchange", readHash);
  byId("copyright-year").textContent = new Date().getFullYear();
  readHash();
})();
