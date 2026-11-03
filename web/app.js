"use strict";

const $ = (id) => document.getElementById(id);

// ?as=<name> gives this tab its own player, to test multiplayer from one computer.
const testAs = new URLSearchParams(location.search).get("as");
const clientId = testAs
  ? `as-${testAs}`
  : localStorage.clientId || (localStorage.clientId = Math.random().toString(36).slice(2) + Date.now().toString(36));
const prefs = JSON.parse(localStorage.prefs || "{}"); // per-game {difficulty, settings}

const SPECTATE_LINES = {
  color_shooter: [
    ["A battle is raging!", "Someone is fighting the snake right now. Grab some popcorn 🍿"],
    ["Fight in progress!", "The snake is hungry and the shooter is busy. Watch the lights!"],
    ["Shhh… a duel is on", "Don't distract the shooter. Cheer quietly."],
    ["The snake has a challenger!", "Will they survive? Look at the strip and find out."],
  ],
  fast_tap: [
    ["A showdown is on!", "Fastest finger wins. Watch the strip! 👀"],
    ["Quick-draw in progress", "Nobody blink. You can join the next game."],
    ["Reflexes are being tested", "Red means wait, green means GO. Grab a seat 🍿"],
  ],
};

let ws = null;
let games = [];
let session = { phase: "idle" };
let view = "games";        // local navigation when not in a game
let selectedGame = null;
let sawPlaying = false;    // show the result screen only for games we watched/played
let spectateLine = null;
let coolingUntil = 0;
let tilesKey = "";
let lastPoisonHits = 0;

// --- clock sync ---------------------------------------------------------------
// Fast Tap taps carry the time they happened on the Pi's clock, so a player
// with slower Wi-Fi isn't penalized. Keep the offset from the fastest
// recent ping (least affected by network delay).

let clockSamples = [];
let clockOffset = 0; // ms to add to performance.now() to get server time

function ping() {
  send({ type: "ping", t0: performance.now() });
}

function onPong(msg) {
  const t1 = performance.now();
  const rtt = t1 - msg.t0;
  clockSamples.push({ rtt, offset: msg.server * 1000 + rtt / 2 - t1 });
  clockSamples = clockSamples.slice(-10);
  clockOffset = clockSamples.reduce((a, b) => (b.rtt < a.rtt ? b : a)).offset;
}

function serverNow() {
  return (performance.now() + clockOffset) / 1000;
}

// --- connection -------------------------------------------------------------

function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => {
    $("conn").classList.add("hidden");
    send({ type: "hello", clientId });
    clockSamples = [];
    for (let i = 0; i < 5; i++) setTimeout(ping, i * 150);
  };
  ws.onclose = () => {
    $("conn").classList.remove("hidden");
    setTimeout(connect, 1000);
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "pong") {
      onPong(msg);
    } else if (msg.type === "games") {
      games = msg.games;
      renderGameList();
    } else if (msg.type === "session") {
      onSession(msg);
    } else if (msg.type === "error") {
      toast(msg.message);
    }
  };
}
setInterval(ping, 3000);

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
  if (s.phase === "lobby") {
    sawPlaying = false;
    renderLobby(s);
  } else if (s.phase === "playing") {
    if (wasPhase !== "playing") {
      const lines = SPECTATE_LINES[s.game.id] || SPECTATE_LINES.color_shooter;
      spectateLine = lines[Math.floor(Math.random() * lines.length)];
    }
    sawPlaying = true;
    if (s.role !== "player") renderSpectate(s);
    else if (s.game.id === "fast_tap") renderTap(s);
    else renderPlay(s.state);
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
    const players = g.max_players > 1 ? ` · 1–${g.max_players} players` : "";
    list.appendChild(card(g.name, g.description + players, false, () => openSetup(g)));
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
  if (!g.difficulties.some((d) => d.id === p.difficulty)) p.difficulty = g.default_difficulty;
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
  if (session.phase === "idle" || session.phase === "ended") show("setup");
}

function renderSetup() {
  const g = selectedGame;
  const p = gamePrefs(g);
  $("setup-title").textContent = g.name;
  $("setup-desc").textContent = g.description;
  $("start-btn").textContent = g.max_players > 1 ? "Open lobby" : "Start";

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

function startGame(g, again = false) {
  const p = gamePrefs(g);
  // "Play again" keeps the difficulty of the game that was just played.
  const difficulty = again ? session.difficulty : p.difficulty;
  send({ type: "start", game: g.id, difficulty, settings: p.settings, again });
}

function capitalize(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function playerName(players, idx, you) {
  return idx === you ? "You" : capitalize(players[idx].color);
}

// --- lobby ----------------------------------------------------------------------

function renderLobby(s) {
  show("lobby");
  $("lobby-title").textContent = s.game.name;
  $("lobby-sub").textContent = `${capitalize(s.difficulty)} · ${s.players.length} of ${s.game.max_players} players`;

  const grid = $("lobby-players");
  grid.innerHTML = "";
  for (let i = 0; i < s.game.max_players; i++) {
    const p = s.players[i];
    const slot = document.createElement("div");
    slot.className = "slot" + (p ? "" : " empty") + (i === s.you ? " you" : "");
    if (p) {
      slot.style.background = p.hex;
      slot.innerHTML = `<div></div><div class="tag"></div>`;
      slot.firstChild.textContent = i === s.you ? "You" : capitalize(p.color);
      slot.lastChild.textContent = i === 0 ? "Host" : "";
    } else {
      slot.textContent = "Open";
    }
    grid.appendChild(slot);
  }

  const main = $("lobby-main");
  const second = $("lobby-second");
  const full = s.players.length >= s.game.max_players;
  main.disabled = false;
  second.classList.remove("hidden");
  if (s.host) {
    $("lobby-hint").textContent = s.players.length === 1
      ? "Friends on the same Wi-Fi can open this page to join. Or start now to play solo (best of 3)."
      : "Everyone ready? Watch the strip, not your phone!";
    main.textContent = s.players.length === 1 ? "Play solo" : `Start with ${s.players.length} players`;
    main.onclick = () => send({ type: "begin" });
    second.textContent = "Cancel";
    second.onclick = () => send({ type: "stop" });
  } else if (s.role === "player") {
    $("lobby-hint").textContent = `You're ${capitalize(s.players[s.you].color)}. Waiting for the host to start…`;
    main.textContent = "Waiting for host…";
    main.disabled = true;
    second.textContent = "Leave";
    second.onclick = () => send({ type: "leave" });
  } else {
    $("lobby-hint").textContent = full ? "This game is full. You can watch and join the next one." : "A game is about to start!";
    main.textContent = full ? "Game full" : "Join";
    main.disabled = full;
    main.onclick = () => send({ type: "join" });
    second.classList.add("hidden");
  }
}

// --- color shooter ----------------------------------------------------------------

function setScore(el, score) {
  el.textContent = score;
  el.classList.toggle("negative", score < 0);
}

function renderPlay(state) {
  show("play");
  setScore($("score"), state.score);
  $("goal").textContent = state.goal;
  $("danger-bar").style.width = `${state.danger * 100}%`;
  renderPoison(state);

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

function renderPoison(state) {
  $("tiles").classList.toggle("poisoned", state.poisoned);
  $("poison").classList.toggle("hidden", !state.poisoned);
  if (state.poisoned && state.poison_hits !== lastPoisonHits) {
    // New hit (or a repeat hit while poisoned): restart the countdown bar.
    const fill = $("poison-fill");
    fill.classList.remove("draining");
    void fill.offsetWidth;
    fill.style.animationDuration = `${state.poison_duration}s`;
    fill.classList.add("draining");
    if (navigator.vibrate) navigator.vibrate([80, 40, 80]);
  }
  lastPoisonHits = state.poison_hits;
}

function fire(color, tile) {
  const cooldown = (session.state && session.state.cooldown) || 0;
  const now = performance.now();
  if (now < coolingUntil || session.state.poisoned) return;
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

// --- fast tap -------------------------------------------------------------------

function renderBoard(el, st, you) {
  el.innerHTML = "";
  if (st.solo) return;
  st.players.forEach((p, i) => {
    const chip = document.createElement("div");
    chip.className = "chip" + (i === you ? " you" : "") + (p.out || p.left ? " out" : "") + (p.active ? "" : " inactive");
    chip.innerHTML = `<span class="dot"></span><span class="name"></span><span class="stars"></span>`;
    chip.querySelector(".dot").style.background = p.hex;
    chip.querySelector(".name").textContent = playerName(st.players, i, you) + (p.left ? " · left" : "");
    chip.querySelector(".stars").textContent = "★".repeat(p.wins);
    el.appendChild(chip);
  });
}

function roundLabel(st) {
  return st.tiebreak ? "Sudden death!" : `Round ${st.round} of ${st.rounds}`;
}

function renderTap(s) {
  show("tap");
  const st = s.state;
  const me = st.players[s.you];
  $("tap-round").textContent = roundLabel(st) + (st.solo ? ` · ${"★".repeat(me.wins) || "no wins yet"}` : "");
  $("tap-quit").classList.toggle("hidden", !s.host);
  renderBoard($("tap-board"), st, s.you);

  const pad = $("tap-pad");
  pad.style.background = me.hex;
  pad.classList.toggle("out", me.out || !me.active);
  pad.classList.toggle("dim", st.stage !== "armed" && !me.out);

  let msg, sub;
  if (st.stage === "intro") {
    msg = roundLabel(st);
    sub = "Get ready… tap only when the strip turns GREEN";
  } else if (st.stage === "armed") {
    if (!me.active) {
      const leaders = st.players.filter((p) => p.active).map((p) => capitalize(p.color)).join(" vs ");
      [msg, sub] = ["Sudden death", `${leaders}. Watch them go!`];
    } else if (me.out) {
      [msg, sub] = ["Too early!", "You're out this round"];
    } else {
      [msg, sub] = ["Watch the strip!", "Tap on GREEN"];
    }
  } else {
    const r = st.last_round;
    if (r.winner === null) {
      [msg, sub] = st.solo ? ["Too early!", "That round goes to the strip"] : ["Everyone was out!", "Nobody wins this round"];
    } else if (r.winner === s.you) {
      [msg, sub] = ["You got it! 🎉", `${r.reaction_ms} ms`];
    } else {
      [msg, sub] = [`${capitalize(st.players[r.winner].color)} wins the round`, `${r.reaction_ms} ms`];
    }
  }
  $("tap-msg").textContent = msg;
  $("tap-sub").textContent = sub;
}

$("tap-pad").addEventListener("pointerdown", (e) => {
  e.preventDefault();
  // Always send: the Pi decides whether the tap was in time.
  send({ type: "input", action: { tap: true, at: serverNow() } });
  if (navigator.vibrate) navigator.vibrate(15);
  const pad = $("tap-pad");
  pad.classList.add("pressed");
  setTimeout(() => pad.classList.remove("pressed"), 100);
});

// --- spectate & result -------------------------------------------------------------

function renderSpectate(s) {
  show("spectate");
  const st = s.state;
  $("spectate-title").textContent = spectateLine[0];
  $("spectate-sub").textContent = spectateLine[1];
  const shooter = s.game.id === "color_shooter";
  $("spectate-shooter").classList.toggle("hidden", !shooter);
  $("spectate-board").classList.toggle("hidden", shooter);
  if (shooter) {
    setScore($("spectate-score"), st.score);
    $("spectate-goal").textContent = st.goal;
    $("spectate-danger-bar").style.width = `${st.danger * 100}%`;
  } else {
    renderBoard($("spectate-board"), { ...st, solo: false }, null);
  }
}

function renderResult(s) {
  show("result");
  tilesKey = "";
  const st = s.state;
  const won = st.status === "won";
  const mine = s.role === "player";
  if (s.game.id === "fast_tap") {
    if (st.solo) {
      $("result-emoji").textContent = won ? "🎊" : "🐢";
      $("result-title").textContent = won ? (mine ? "You win!" : "They won!") : "Not this time";
    } else {
      const winner = st.players[st.winner];
      $("result-emoji").textContent = "🎊";
      $("result-title").textContent = st.winner === s.you ? "You win! 🏆" : `${capitalize(winner.color)} wins!`;
    }
    $("result-sub").textContent = st.players.map((p, i) => `${playerName(st.players, i, s.you)} ${p.wins}`).join(" · ");
    return;
  }
  $("result-emoji").textContent = won ? "🎆" : "🐍";
  $("result-title").textContent = won
    ? (mine ? "You won!" : "The challenger won!")
    : (mine ? "The snake got you" : "The snake won this round");
  $("result-sub").textContent = `Final score: ${st.score} / ${st.goal} · ${s.difficulty}`;
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
$("quit-btn").onclick = $("tap-quit").onclick = () => {
  if (confirm("Quit this game?")) send({ type: "stop" });
};
$("again-btn").onclick = () => {
  const g = games.find((x) => x.id === session.game.id);
  if (g) startGame(g, true);
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
