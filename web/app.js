"use strict";

const $ = (id) => document.getElementById(id);

const clientId = localStorage.clientId || (localStorage.clientId = Math.random().toString(36).slice(2) + Date.now().toString(36));
const prefs = JSON.parse(localStorage.prefs || "{}"); // per-game {difficulty, settings}

const SPECTATE_LINES = [
  ["A battle is raging!", "Someone is fighting the snake right now. Grab some popcorn 🍿"],
  ["Fight in progress!", "The snake is hungry and the shooter is busy. Watch the lights!"],
  ["Shhh… a duel is on", "Don't distract the shooter. Cheer quietly."],
  ["The snake has a challenger!", "Will they survive? Look at the strip and find out."],
];

let ws = null;
let games = [];
let session = { phase: "idle" };
let view = "games";        // local navigation when not in a game
let selectedGame = null;
let sawPlaying = false;    // show the result screen only for games we watched/played
let spectateLine = null;
let coolingUntil = 0;
let tilesKey = "";

// --- connection -------------------------------------------------------------

function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => {
    $("conn").classList.add("hidden");
    send({ type: "hello", clientId });
  };
  ws.onclose = () => {
    $("conn").classList.remove("hidden");
    setTimeout(connect, 1000);
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "games") {
      games = msg.games;
      renderGameList();
    } else if (msg.type === "session") {
      onSession(msg);
    } else if (msg.type === "error") {
      toast(msg.message);
    }
  };
}

function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

// --- views --------------------------------------------------------------------

function show(name) {
  for (const v of document.querySelectorAll(".view")) v.classList.toggle("hidden", v.id !== `view-${name}`);
}

function onSession(s) {
  const wasPhase = session.phase;
  session = s;
  if (s.phase === "playing") {
    if (wasPhase !== "playing") spectateLine = SPECTATE_LINES[Math.floor(Math.random() * SPECTATE_LINES.length)];
    sawPlaying = true;
    if (s.role === "player") renderPlay(s.state);
    else renderSpectate(s.state);
  } else if (s.phase === "ended" && sawPlaying) {
    renderResult(s);
  } else {
    sawPlaying = false;
    show(view);
  }
}

function renderGameList() {
  const list = $("game-list");
  list.innerHTML = "";
  for (const g of games) {
    list.appendChild(card(g.name, g.description, false, () => openSetup(g)));
  }
}

function card(title, desc, selected, onClick) {
  const b = document.createElement("button");
  b.className = "card" + (selected ? " selected" : "");
  b.innerHTML = `<div class="title"></div><div class="desc"></div>`;
  b.querySelector(".title").textContent = title;
  b.querySelector(".desc").textContent = desc || "";
  b.onclick = onClick;
  return b;
}

function gamePrefs(g) {
  const p = prefs[g.id] || (prefs[g.id] = { difficulty: g.default_difficulty, settings: {} });
  for (const s of g.settings) if (!(s.id in p.settings)) p.settings[s.id] = s.default;
  return p;
}

function savePrefs() {
  localStorage.prefs = JSON.stringify(prefs);
}

function openSetup(g) {
  selectedGame = g;
  view = "setup";
  renderSetup();
  if (session.phase !== "playing") show("setup");
}

function renderSetup() {
  const g = selectedGame;
  const p = gamePrefs(g);
  $("setup-title").textContent = g.name;
  $("setup-desc").textContent = g.description;

  const dl = $("difficulty-list");
  dl.innerHTML = "";
  for (const d of g.difficulties) {
    dl.appendChild(card(d.label, d.description, p.difficulty === d.id, () => {
      p.difficulty = d.id;
      savePrefs();
      renderSetup();
    }));
  }

  const box = $("settings");
  box.innerHTML = "";
  for (const s of g.settings) {
    const h = document.createElement("h2");
    h.textContent = s.label;
    const row = document.createElement("div");
    row.className = "segmented";
    for (const o of s.options) {
      row.appendChild(card(o.label, o.description, p.settings[s.id] === o.id, () => {
        p.settings[s.id] = o.id;
        savePrefs();
        renderSetup();
      }));
    }
    box.append(h, row);
  }
}

function startGame(g) {
  const p = gamePrefs(g);
  send({ type: "start", game: g.id, difficulty: p.difficulty, settings: p.settings });
}

function setScore(el, score) {
  el.textContent = score;
  el.classList.toggle("negative", score < 0);
}

function renderPlay(state) {
  show("play");
  setScore($("score"), state.score);
  $("goal").textContent = state.goal;
  $("danger-bar").style.width = `${state.danger * 100}%`;

  const key = state.colors.map((c) => c.name).join();
  if (key === tilesKey) return;
  tilesKey = key;
  const tiles = $("tiles");
  tiles.className = `tiles count-${state.colors.length}`;
  tiles.innerHTML = "";
  for (const c of state.colors) {
    const t = document.createElement("button");
    t.className = "tile";
    t.style.background = c.hex;
    t.setAttribute("aria-label", c.name);
    t.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      fire(c.name, t);
    });
    tiles.appendChild(t);
  }
}

function fire(color, tile) {
  const cooldown = (session.state && session.state.cooldown) || 0;
  const now = performance.now();
  if (now < coolingUntil) return;
  send({ type: "input", action: { fire: color } });
  if (navigator.vibrate) navigator.vibrate(12);
  tile.classList.add("pressed");
  setTimeout(() => tile.classList.remove("pressed"), 90);
  if (cooldown > 0) {
    coolingUntil = now + cooldown * 1000;
    $("tiles").classList.add("cooling");
    setTimeout(() => $("tiles").classList.remove("cooling"), cooldown * 1000);
  }
}

function renderSpectate(state) {
  show("spectate");
  $("spectate-title").textContent = spectateLine[0];
  $("spectate-sub").textContent = spectateLine[1];
  setScore($("spectate-score"), state.score);
  $("spectate-goal").textContent = state.goal;
  $("spectate-danger-bar").style.width = `${state.danger * 100}%`;
}

function renderResult(s) {
  show("result");
  tilesKey = "";
  const won = s.state.status === "won";
  const mine = s.role === "player";
  $("result-emoji").textContent = won ? "🎆" : "🐍";
  $("result-title").textContent = won
    ? (mine ? "You won!" : "The challenger won!")
    : (mine ? "The snake got you" : "The snake won this round");
  $("result-sub").textContent = `Final score: ${s.state.score} / ${s.state.goal} · ${s.difficulty}`;
}

function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.add("hidden"), 2500);
}

// --- buttons -------------------------------------------------------------------

$("start-btn").onclick = () => startGame(selectedGame);
$("quit-btn").onclick = () => {
  if (confirm("Quit this game?")) send({ type: "stop" });
};
$("again-btn").onclick = () => {
  const g = games.find((x) => x.id === session.game.id);
  if (g) startGame(g);
};
$("home-btn").onclick = () => {
  sawPlaying = false;
  view = "games";
  show("games");
};
for (const b of document.querySelectorAll("[data-nav]")) {
  b.onclick = () => {
    view = b.dataset.nav;
    show(view);
  };
}

connect();
