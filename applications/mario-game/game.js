// Fleet Runner: a small side-scrolling platformer. No dependencies.
"use strict";

const T = 32; // tile size in pixels
const W = 800, H = 480;
// Level map: '=' ground, '#' brick, '?' coin block, 'o' coin, 'g' walker, 'F' flag, 'P' start.
const LEVEL = [
  "                                                                                                                        ",
  "                                                                                                                        ",
  "                                                                                                                        ",
  "                    ?              o o o                                   ?#?#?                                     F  ",
  "                                  #######                     o o                                                   F  ",
  "                                                             #####           o  o  o                                 F  ",
  "          ?#?#?           o                     ##                         #########           ##                    F  ",
  "                         ###                   ###      g                                    ####                    F  ",
  "  P                  g           g    g       ####    ####        g   g                   g #####        g     g     F  ",
  "=====================================   ===========  ================   ======================================  ========",
  "=====================================   ===========  ================   ======================================  ========",
  "=====================================   ===========  ================   ======================================  ========",
];
const ROWS = LEVEL.length, COLS = Math.max(...LEVEL.map((row) => row.length));
const GRAVITY = 0.6, MAX_FALL = 12, ACCEL = 0.5, FRICTION = 0.82, MAX_RUN = 5, JUMP = -12.5;

const canvas = document.getElementById("game");
const ctx = canvas.getContext("2d");
const keys = {};
let state;

function reset(keepScore) {
  const tiles = LEVEL.map((row) => row.padEnd(COLS).split(""));
  const enemies = [], coins = [];
  let start = { x: 64, y: 0 };
  tiles.forEach((row, y) => row.forEach((c, x) => {
    if (c === "P") start = { x: x * T, y: y * T };
    if (c === "g") enemies.push({ x: x * T, y: y * T, w: 28, h: 28, vx: -1.2, vy: 0, alive: true });
    if (c === "o") coins.push({ x: x * T + 8, y: y * T + 8, taken: false });
    if ("Pgo".includes(c)) row[x] = " ";
  }));
  const prev = state || { score: 0, lives: 3 };
  state = {
    tiles, enemies, coins, pops: [],
    player: { x: start.x, y: start.y, w: 24, h: 30, vx: 0, vy: 0, ground: false, coyote: 0, face: 1 },
    camera: 0,
    score: keepScore ? prev.score : 0,
    lives: keepScore ? prev.lives : 3,
    coinCount: keepScore ? prev.coinCount || 0 : 0,
    time: 300, frames: 0, mode: "play",
  };
}

const solid = (c) => c === "=" || c === "#" || c === "?" || c === "B";
function tileAt(px, py) {
  const x = Math.floor(px / T), y = Math.floor(py / T);
  if (x < 0 || x >= COLS) return "=";
  if (y < 0 || y >= ROWS) return " ";
  return state.tiles[y][x];
}

// Move a body along one axis and stop it at solid tiles. Returns the tile it hit.
function move(b, dx, dy) {
  b.x += dx; b.y += dy;
  const x0 = Math.floor(b.x / T), x1 = Math.floor((b.x + b.w - 1) / T);
  const y0 = Math.floor(b.y / T), y1 = Math.floor((b.y + b.h - 1) / T);
  for (let ty = y0; ty <= y1; ty++) for (let tx = x0; tx <= x1; tx++) {
    if (!solid(tileAt(tx * T, ty * T))) continue;
    if (dx > 0) b.x = tx * T - b.w; else if (dx < 0) b.x = (tx + 1) * T;
    if (dy > 0) b.y = ty * T - b.h; else if (dy < 0) b.y = (ty + 1) * T;
    return { tx, ty };
  }
  return null;
}

function hitBlock(tx, ty) {
  const c = state.tiles[ty][tx];
  if (c === "?") {
    state.tiles[ty][tx] = "B";
    state.coinCount++; state.score += 200;
    state.pops.push({ x: tx * T + 8, y: ty * T - 8, t: 30 });
  }
}

function overlaps(a, b) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

function loseLife() {
  state.lives--;
  if (state.lives <= 0) { state.mode = "over"; return; }
  reset(true);
}

function update() {
  if (state.mode !== "play") {
    // Enter, R or Jump (the touch pad's button) restarts, but only on a fresh
    // press: a jump still held when the round ended must not skip the result.
    const restart = keys.Enter || keys.KeyR || keys.Space;
    if (restart && state.released) reset(false);
    if (!restart) state.released = true;
    return;
  }
  const p = state.player;
  const left = keys.ArrowLeft || keys.KeyA, right = keys.ArrowRight || keys.KeyD;
  const jump = keys.Space || keys.ArrowUp || keys.KeyW;

  if (left) { p.vx -= ACCEL; p.face = -1; }
  if (right) { p.vx += ACCEL; p.face = 1; }
  if (!left && !right) p.vx *= FRICTION;
  p.vx = Math.max(-MAX_RUN, Math.min(MAX_RUN, p.vx));
  p.coyote = p.ground ? 6 : p.coyote - 1;
  if (jump && p.coyote > 0 && !p.jumpHeld) { p.vy = JUMP; p.coyote = 0; }
  if (!jump && p.vy < -4) p.vy = -4; // release early for a short hop
  p.jumpHeld = jump;
  p.vy = Math.min(MAX_FALL, p.vy + GRAVITY);

  move(p, p.vx, 0);
  const wasFalling = p.vy > 0;
  const hit = move(p, 0, p.vy);
  p.ground = false;
  if (hit) {
    if (wasFalling) p.ground = true; else hitBlock(hit.tx, hit.ty);
    p.vy = 0;
  }
  if (p.x < state.camera) p.x = state.camera;
  if (p.y > ROWS * T) return loseLife();

  for (const e of state.enemies) {
    if (!e.alive) continue;
    e.vy = Math.min(MAX_FALL, e.vy + GRAVITY);
    if (move(e, e.vx, 0)) e.vx = -e.vx;
    if (move(e, 0, e.vy)) e.vy = 0;
    // Turn at ledges instead of walking off them.
    const ahead = e.vx > 0 ? e.x + e.w + 1 : e.x - 1;
    if (!solid(tileAt(ahead, e.y + e.h + 1))) e.vx = -e.vx;
    if (!overlaps(p, e)) continue;
    if (p.vy > 0 && p.y + p.h - e.y < 14) {
      e.alive = false; p.vy = JUMP * 0.6; state.score += 100;
      state.pops.push({ x: e.x, y: e.y, t: 30, text: "100" });
    } else return loseLife();
  }

  for (const c of state.coins) {
    if (!c.taken && overlaps(p, { x: c.x, y: c.y, w: 16, h: 16 })) {
      c.taken = true; state.coinCount++; state.score += 100;
    }
  }
  if (tileAt(p.x + p.w / 2, p.y + p.h / 2) === "F") {
    state.mode = "won"; state.score += state.time * 10;
  }
  state.pops = state.pops.filter((s) => --s.t > 0);
  state.camera = Math.max(0, Math.min(COLS * T - W, p.x - W / 3));
  if (++state.frames % 60 === 0 && --state.time <= 0) loseLife();
}

function draw() {
  const cam = state.camera;
  const sky = ctx.createLinearGradient(0, 0, 0, H);
  sky.addColorStop(0, "#5c94fc"); sky.addColorStop(1, "#9cc4ff");
  ctx.fillStyle = sky; ctx.fillRect(0, 0, W, H);

  ctx.fillStyle = "#3aa13a"; // far hills, slower than the camera
  for (let i = 0; i < 12; i++) {
    const x = i * 360 - (cam * 0.4) % 360;
    ctx.beginPath(); ctx.arc(x, H - 90, 110, Math.PI, 0); ctx.fill();
  }
  ctx.fillStyle = "#fff";
  for (let i = 0; i < 10; i++) {
    const x = i * 300 + 60 - (cam * 0.2) % 300;
    ctx.beginPath(); ctx.arc(x, 70 + (i % 3) * 25, 22, 0, 7); ctx.arc(x + 26, 62 + (i % 3) * 25, 28, 0, 7); ctx.arc(x + 54, 70 + (i % 3) * 25, 22, 0, 7); ctx.fill();
  }

  ctx.save(); ctx.translate(-Math.round(cam), 0);
  const c0 = Math.floor(cam / T), c1 = c0 + Math.ceil(W / T) + 1;
  for (let y = 0; y < ROWS; y++) for (let x = c0; x <= c1 && x < COLS; x++) {
    const c = state.tiles[y][x], px = x * T, py = y * T;
    if (c === "=") {
      ctx.fillStyle = y > 0 && state.tiles[y - 1][x] !== "=" ? "#c84c0c" : "#a0400a";
      ctx.fillRect(px, py, T, T); ctx.strokeStyle = "#5a2000"; ctx.strokeRect(px + 0.5, py + 0.5, T - 1, T - 1);
    } else if (c === "#") {
      ctx.fillStyle = "#b8501c"; ctx.fillRect(px, py, T, T);
      ctx.fillStyle = "#6b2a08"; ctx.fillRect(px, py + 15, T, 2); ctx.fillRect(px + 15, py, 2, 15);
    } else if (c === "?" || c === "B") {
      ctx.fillStyle = c === "?" ? "#f8b800" : "#8c6c3c"; ctx.fillRect(px + 1, py + 1, T - 2, T - 2);
      if (c === "?") { ctx.fillStyle = "#6b2a08"; ctx.font = "bold 22px monospace"; ctx.fillText("?", px + 10, py + 24); }
    } else if (c === "F") {
      ctx.fillStyle = "#ddd"; ctx.fillRect(px + 14, py, 4, T);
      if (y === 3) { ctx.fillStyle = "#2ecc40"; ctx.beginPath(); ctx.moveTo(px + 14, py); ctx.lineTo(px - 14, py + 12); ctx.lineTo(px + 14, py + 24); ctx.fill(); }
    }
  }
  for (const c of state.coins) if (!c.taken) {
    ctx.fillStyle = "#ffd700"; ctx.beginPath(); ctx.ellipse(c.x + 8, c.y + 8, 6, 9, 0, 0, 7); ctx.fill();
  }
  for (const e of state.enemies) if (e.alive) {
    ctx.fillStyle = "#8b4513"; ctx.beginPath(); ctx.arc(e.x + 14, e.y + 14, 14, Math.PI, 0); ctx.fill();
    ctx.fillRect(e.x, e.y + 14, 28, 8); ctx.fillStyle = "#000"; ctx.fillRect(e.x + 2, e.y + 22, 10, 6); ctx.fillRect(e.x + 16, e.y + 22, 10, 6);
    ctx.fillStyle = "#fff"; ctx.fillRect(e.x + 7, e.y + 8, 5, 6); ctx.fillRect(e.x + 16, e.y + 8, 5, 6);
  }
  const p = state.player; // red cap, face, blue overalls
  ctx.fillStyle = "#e52521"; ctx.fillRect(p.x, p.y, p.w, 8); ctx.fillRect(p.x + (p.face > 0 ? 12 : 0), p.y + 4, 12, 4);
  ctx.fillStyle = "#fbd0a0"; ctx.fillRect(p.x + 3, p.y + 8, p.w - 6, 8);
  ctx.fillStyle = "#000"; ctx.fillRect(p.x + (p.face > 0 ? 15 : 6), p.y + 10, 3, 3);
  ctx.fillStyle = "#2038ec"; ctx.fillRect(p.x + 2, p.y + 16, p.w - 4, 10);
  ctx.fillStyle = "#6b2a08"; ctx.fillRect(p.x, p.y + 26, 10, 4); ctx.fillRect(p.x + 14, p.y + 26, 10, 4);
  ctx.fillStyle = "#fff"; ctx.font = "bold 14px monospace";
  for (const s of state.pops) ctx.fillText(s.text || "+200", s.x, s.y - (30 - s.t));
  ctx.restore();

  ctx.fillStyle = "#fff"; ctx.font = "bold 18px monospace";
  ctx.fillText(`SCORE ${String(state.score).padStart(6, "0")}`, 16, 28);
  ctx.fillText(`COINS ${state.coinCount}`, 240, 28);
  ctx.fillText(`LIVES ${state.lives}`, 420, 28);
  ctx.fillText(`TIME ${state.time}`, 620, 28);
  if (state.mode !== "play") {
    ctx.fillStyle = "rgba(0,0,0,0.6)"; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.font = "bold 44px monospace";
    ctx.fillText(state.mode === "won" ? "COURSE CLEAR!" : "GAME OVER", W / 2, H / 2 - 10);
    ctx.font = "20px monospace"; ctx.fillText(`Score ${state.score}  ·  Enter or Jump to play again`, W / 2, H / 2 + 30);
    ctx.textAlign = "left";
  }
}

addEventListener("keydown", (e) => { keys[e.code] = true; if (e.code.startsWith("Arrow") || e.code === "Space") e.preventDefault(); });
addEventListener("keyup", (e) => { keys[e.code] = false; });
for (const b of document.querySelectorAll("[data-key]")) {
  const set = (v) => (e) => { e.preventDefault(); keys[b.dataset.key] = v; };
  b.addEventListener("touchstart", set(true)); b.addEventListener("touchend", set(false));
  b.addEventListener("touchcancel", set(false)); // a gesture can end a touch without touchend
  b.addEventListener("mousedown", set(true)); b.addEventListener("mouseup", set(false));
  b.addEventListener("mouseleave", set(false)); // released outside the button
}
// A key released while the window is unfocused never sends keyup.
addEventListener("blur", () => { for (const code in keys) keys[code] = false; });

reset(false);
// Physics and the clock advance in fixed 60 Hz steps whatever the display's
// refresh rate; the catch-up is capped so a background tab cannot lurch.
const STEP = 1000 / 60;
let last = performance.now(), lag = 0;
(function loop(now) {
  lag += Math.min(250, now - last);
  last = now;
  while (lag >= STEP) { update(); lag -= STEP; }
  draw();
  requestAnimationFrame(loop);
})(last);
