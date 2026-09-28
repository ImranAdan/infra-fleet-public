"use strict";

const LABEL = { running: "Running", starting: "Starting", sleeping: "Not running" };
const COLORS = ["#e74c3c", "#8e44ad", "#16a085", "#d35400", "#2980b9", "#c0392b", "#27ae60"];
const APP_URL = "https://localhost:8443/"; // the selected app, via ./fleet access --service app

function color(name) {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return COLORS[hash % COLORS.length];
}

function card(app) {
  const el = document.createElement("article");
  el.className = `card ${app.state}`;
  const status = app.phase ? `${LABEL[app.state]} · canary ${app.phase}` : LABEL[app.state];
  el.innerHTML = `
    <div class="top">
      <div class="icon"></div>
      <div><h2></h2><div class="name"></div></div>
    </div>
    <p class="desc"></p>
    <div class="status"><span class="dot"></span><span class="label"></span></div>
    <a class="btn"></a>`;
  el.querySelector(".icon").textContent = app.title[0].toUpperCase();
  el.querySelector(".icon").style.background = color(app.name);
  el.querySelector("h2").textContent = app.title;
  el.querySelector(".name").textContent = app.name;
  el.querySelector(".desc").textContent = app.description;
  el.querySelector(".label").textContent = status;
  const btn = el.querySelector(".btn");
  if (app.state === "running") {
    btn.textContent = "Open";
    btn.href = APP_URL;
    btn.target = "_blank";
    btn.rel = "noopener";
  } else {
    // Launching on demand is the control plane's next step.
    btn.textContent = app.state === "starting" ? "Starting…" : "Launch (coming next)";
    btn.setAttribute("aria-disabled", "true");
  }
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
