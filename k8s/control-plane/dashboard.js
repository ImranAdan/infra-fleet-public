"use strict";

const LABEL = { running: "Running", starting: "Starting", sleeping: "Not running" };
const COLORS = ["#e74c3c", "#8e44ad", "#16a085", "#d35400", "#2980b9", "#c0392b", "#27ae60"];
// Every app answers on its own host through this dashboard's port-forward.
const appUrl = (name) => `${location.protocol}//${name}.localhost:${location.port}/`;

function color(name) {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return COLORS[hash % COLORS.length];
}

async function act(name, action) {
  // The custom header proves the request came from this page, not another site.
  const response = await fetch(`/api/apps/${name}/${action}`, {
    method: "POST",
    headers: { "X-Fleet-Action": "1" },
  });
  if (!response.ok) alert((await response.json()).error || response.statusText);
  refresh();
}

function button(text, onClick, secondary) {
  const b = document.createElement("button");
  b.className = secondary ? "btn secondary" : "btn";
  b.textContent = text;
  if (onClick) b.addEventListener("click", onClick);
  else b.setAttribute("aria-disabled", "true");
  return b;
}

function card(app) {
  const el = document.createElement("article");
  el.className = `card ${app.state}`;
  el.innerHTML = `
    <div class="top">
      <div class="icon"></div>
      <div><h2></h2><div class="name"></div></div>
    </div>
    <p class="desc"></p>
    <div class="status"><span class="dot"></span><span class="label"></span></div>
    <div class="actions"></div>`;
  el.querySelector(".icon").textContent = app.title[0].toUpperCase();
  el.querySelector(".icon").style.background = color(app.name);
  el.querySelector("h2").textContent = app.title;
  el.querySelector(".name").textContent = app.selected ? `${app.name} · default` : app.name;
  el.querySelector(".desc").textContent = app.description;
  el.querySelector(".label").textContent =
    app.phase ? `${LABEL[app.state]} · canary ${app.phase}` : LABEL[app.state];

  const actions = el.querySelector(".actions");
  if (app.state === "running") {
    const open = document.createElement("a");
    open.className = "btn";
    open.textContent = "Open";
    open.href = appUrl(app.name);
    open.target = "_blank";
    open.rel = "noopener";
    actions.append(open);
  } else if (app.state === "starting") {
    actions.append(button("Deploying stack…"));
  } else {
    actions.append(button("Launch", () => act(app.name, "launch")));
  }
  if (app.launched) actions.append(button("Stop", () => act(app.name, "stop"), true));
  return el;
}

async function refresh() {
  const main = document.getElementById("apps");
  try {
    const response = await fetch("/api/apps", { cache: "no-store" });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || response.statusText);
    main.replaceChildren(...body.apps.map(card));
  } catch (error) {
    const note = document.createElement("p");
    note.className = "error";
    note.textContent = `Cannot read the fleet: ${error.message}`;
    main.replaceChildren(note);
  }
}

refresh();
setInterval(refresh, 3000);
