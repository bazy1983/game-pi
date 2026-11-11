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
  sumo: [
    ["Sumo match on!", "Two colors, one strip. Who'll get pushed off? 👀"],
    ["Push! Push! Push!", "Fingers are flying. Watch the strip!"],
    ["Clash of colors", "Cheer for red or blue 🍿"],
  ],
  simon: [
    ["Memory test in progress", "Shhh… they're counting colors. Watch the strip! 🧠"],
    ["Simon is talking", "Can they remember it all? Watch and see."],
    ["Brains at work", "Don't shout out the colors 🤫"],
  ],
  morse: [
    ["Decoding in progress", "Dots and dashes everywhere. Can they read it? 📡"],
    ["Beep… beeeep… beep", "Someone is reading the strip. Try it yourself!"],
    ["Secret message!", "Watch the strip: short and long flashes spell a word 🕵️"],
  ],
  red_light: [
    ["Race in progress!", "Green means go, red means FREEZE. Watch the strip! 🚦"],
    ["Don't move!", "Someone's about to get caught. Grab a seat 🍿"],
    ["Who's creeping up?", "Watch the dots climb the strip 👀"],
  ],
  hot_potato: [
    ["Hot potato!", "Who's holding it when it blows? Watch the strip! 🥔"],
    ["Tick… tick… tick…", "Someone's about to get burned. Grab a seat 🍿"],
    ["Pass it on!", "The potato is flying around the strip 🔥"],
  ],
  ping_pong: [
    ["Rally in progress!", "Back and forth, faster and faster. Watch the strip! 🏓"],
    ["Ping… pong… ping…", "Don't blink, the ball speeds up."],
    ["Match point?", "Grab a seat and cheer 🍿"],
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

let lastRtt = null; // reported with the next ping, for the server's performance trace

function ping() {
  send({ type: "ping", t0: performance.now(), rtt: lastRtt });
}

function onPong(msg) {
  const t1 = performance.now();
  const rtt = t1 - msg.t0;
  lastRtt = Math.round(rtt);
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
      morseReset();
      rlHolding = false;
      hpLast = { holder: null, out: false };
    }
    sawPlaying = true;
    if (s.role !== "player") renderSpectate(s);
    else if (s.game.id === "fast_tap") renderTap(s);
    else if (s.game.id === "sumo") renderSumo(s);
    else if (s.game.id === "simon") renderSimon(s);
    else if (s.game.id === "ping_pong") renderPong(s);
    else if (s.game.id === "morse") renderMorse(s);
    else if (s.game.id === "red_light") renderRedLight(s);
    else if (s.game.id === "hot_potato") renderHotPotato(s);
    else renderPlay(s.state);
  } else if (s.phase === "ended" && sawPlaying) {
    if (wasPhase !== "ended") lockResult();
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
      ? `Friends on the same Wi-Fi can open this page to join. Or start now to play solo${s.game.id === "fast_tap" ? " (best of 3)" : ""}.`
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

// --- sumo -----------------------------------------------------------------------

function sumoName(st, i, you) {
  if (st.players[i].cpu) return "Computer";
  return i === you ? "You" : capitalize(st.players[i].color);
}

function renderTug(st, you) {
  const [a, b] = st.players;
  for (const [el, p] of [[$("tug-a"), a], [$("tug-b"), b]]) {
    el.style.width = `${(100 * p.lights) / st.leds}%`;
    el.style.background = p.hex;
  }
  $("tug-name-a").textContent = `${sumoName(st, 0, you)} · bottom`;
  $("tug-name-b").textContent = `top · ${sumoName(st, 1, you)}`;
}

let sumoPadsKey = "";

function renderSumo(s) {
  show("sumo");
  const st = s.state;
  const me = st.players[s.you];
  const other = st.players[1 - s.you];
  $("sumo-quit").classList.toggle("hidden", !s.host);
  $("sumo-label").textContent = st.solo ? `You vs the computer · ${s.difficulty}` : `You're ${me.color.toUpperCase()}`;
  renderTug(st, s.you);

  // One big pad, or numbered buttons to tap in order.
  const pads = $("sumo-pads");
  const key = `${st.buttons}/${me.hex}`;
  if (key !== sumoPadsKey) {
    sumoPadsKey = key;
    pads.innerHTML = "";
    pads.classList.toggle("many", st.buttons > 1);
    for (let i = 0; i < st.buttons; i++) {
      const b = document.createElement("button");
      b.className = "pad";
      b.style.background = me.hex;
      b.innerHTML = `<span>${st.buttons > 1 ? i + 1 : "TAP!"}</span>`;
      b.addEventListener("pointerdown", (e) => sumoTap(e, b, i));
      pads.appendChild(b);
    }
  }
  [...pads.children].forEach((b, i) => {
    b.classList.toggle("next", i === me.next);
    b.classList.toggle("dim", st.countdown > 0);
  });

  const msg = $("sumo-msg");
  msg.classList.toggle("count", st.countdown > 0);
  if (st.countdown > 0) {
    msg.textContent = st.countdown;
    const order = [...Array(st.buttons).keys()].map((i) => i + 1).join(" → ");
    $("sumo-sub").textContent =
      `You start at the ${s.you === 0 ? "bottom" : "top"}. ` +
      (st.buttons > 1 ? `Tap ${order}, then again` : "Get ready…");
  } else {
    const ahead = me.lights - other.lights;
    msg.textContent = st.buttons > 1 ? `Next: ${me.next + 1}` : "TAP! TAP! TAP!";
    $("sumo-sub").textContent =
      me.lights + other.lights < st.leds ? "Grab the strip!" : ahead > 0 ? "Push them off!" : ahead < 0 ? "Push back!" : "Dead even!";
  }
}

function sumoTap(e, pad, button) {
  e.preventDefault();
  // Always send: the Pi decides whether it was the right button.
  send({ type: "input", action: { tap: true, button, at: serverNow() } });
  if (navigator.vibrate) navigator.vibrate(10);
  pad.classList.add("pressed");
  setTimeout(() => pad.classList.remove("pressed"), 80);
}

// --- simon says ---------------------------------------------------------------

function simonBoard(st) {
  // In turns mode, only the player whose turn it is is highlighted.
  const players = st.players.map((p, i) => ({ ...p, wins: 0, active: st.mode !== "turns" || i === st.turn }));
  return { players, solo: st.mode === "solo" };
}

function simonNames(st, list, you) {
  return list.map((i) => playerName(st.players, i, you)).join(", ");
}

let simonKey = "";

function renderSimon(s) {
  show("simon");
  const st = s.state;
  const me = st.players[s.you];
  const turns = st.mode === "turns";
  const myTurn = turns && st.turn === s.you;
  $("simon-quit").classList.toggle("hidden", !s.host);
  $("simon-label").textContent = turns
    ? `${st.length} of ${st.target} colors · ${s.difficulty}`
    : `Round ${st.length} of ${st.target} · ${s.difficulty}`;
  renderBoard($("simon-board"), simonBoard(st), s.you);

  // Rebuilt when the order changes (hard shuffles it every round).
  const box = $("simon-buttons");
  const key = st.buttons.map((b) => b.name).join();
  if (key !== simonKey) {
    simonKey = key;
    box.innerHTML = "";
    for (const b of st.buttons) {
      const t = document.createElement("button");
      t.className = "tile";
      t.style.background = b.hex;
      t.setAttribute("aria-label", b.name);
      t.addEventListener("pointerdown", (e) => simonPress(e, t, b.name));
      box.appendChild(t);
    }
  }
  const canPress = st.stage === "input" && !me.out && (turns ? myTurn : !me.done && !me.failed);
  box.classList.toggle("dim", !canPress);

  let msg, sub;
  const turnName = turns ? playerName(st.players, st.turn, s.you) : "";
  if (st.stage === "intro") {
    msg = "Get ready…";
    sub = turns
      ? (myTurn ? "You go first: pick a color" : `${turnName} goes first. Watch the strip!`)
      : "Watch the strip, then repeat the colors";
  } else if (st.stage === "show") {
    [msg, sub] = ["Watch the strip!", `${st.length} color${st.length === 1 ? "" : "s"}`];
  } else if (st.stage === "input") {
    if (me.out) {
      [msg, sub] = ["You're out", "Watch the others"];
    } else if (turns) {
      if (!myTurn) [msg, sub] = [`${turnName}'s turn`, "Watch the strip and remember"];
      else if (st.length === 0) [msg, sub] = ["Pick the first color", "Anything you like"];
      else if (st.entered < st.length) [msg, sub] = ["Your turn: repeat it", `${st.entered} of ${st.length}`];
      else [msg, sub] = ["Now add a color!", "Pick any color to make it longer"];
    } else if (me.failed) {
      [msg, sub] = ["Oops!", "Waiting for the others…"];
    } else if (me.done) {
      [msg, sub] = ["Got it! ✓", "Waiting for the others…"];
    } else {
      [msg, sub] = ["Your turn!", `${me.progress} of ${st.length}`];
    }
  } else {
    const last = st.last || { out: [] };
    if (last.replay) {
      [msg, sub] = ["Everyone missed!", "Same round again, new last color"];
    } else if (last.out.includes(s.you)) {
      [msg, sub] = ["Wrong! You're out", "Watch the others"];
    } else if (last.out.length) {
      [msg, sub] = [`${simonNames(st, last.out, s.you)} ${last.out.length === 1 ? "is" : "are"} out`, turns ? `${turnName}'s turn next` : "Next round: one more color"];
    } else if (last.left !== undefined) {
      [msg, sub] = [`${capitalize(st.players[last.left].color)} left`, `${turnName}'s turn next`];
    } else if (turns) {
      [msg, sub] = [last.added === s.you ? "Nice! ✓" : `${playerName(st.players, last.added, s.you)} added a color`, `${turnName}'s turn next`];
    } else {
      [msg, sub] = ["Correct! ✓", "Next round: one more color"];
    }
  }
  $("simon-msg").textContent = msg;
  $("simon-sub").textContent = sub;
}

function simonPress(e, tile, color) {
  e.preventDefault();
  if ($("simon-buttons").classList.contains("dim")) return;
  send({ type: "input", action: { press: color } });
  if (navigator.vibrate) navigator.vibrate(12);
  tile.classList.add("pressed");
  setTimeout(() => tile.classList.remove("pressed"), 120);
}

// --- morse code ---------------------------------------------------------------

const MORSE = {
  A: ".-", B: "-...", C: "-.-.", D: "-..", E: ".", F: "..-.", G: "--.", H: "....", I: "..", J: ".---",
  K: "-.-", L: ".-..", M: "--", N: "-.", O: "---", P: ".--.", Q: "--.-", R: ".-.", S: "...", T: "-",
  U: "..-", V: "...-", W: ".--", X: "-..-", Y: "-.--", Z: "--..",
};

let morseWrong = 0;     // my wrong guesses so far, to notice a new one
let morseErrorUntil = 0;

function morseReset() {
  morseWrong = 0;
  morseErrorUntil = 0;
  $("morse-input").value = "";
}

(function buildMorseChart() {
  const chart = $("morse-chart");
  for (const [letter, code] of Object.entries(MORSE)) {
    const d = document.createElement("div");
    d.innerHTML = `<b>${letter}</b><span>${code.replaceAll(".", "·").replaceAll("-", "–")}</span>`;
    chart.appendChild(d);
  }
})();

function renderMorse(s) {
  show("morse");
  const st = s.state;
  const me = st.players[s.you];
  $("morse-quit").classList.toggle("hidden", !s.host);
  $("morse-label").textContent = `${st.length} letters · ${s.difficulty}`;
  renderBoard($("morse-board"), { players: st.players.map((p) => ({ ...p, wins: 0, active: true })), solo: st.solo }, s.you);

  if (me.wrong > morseWrong) { // the Pi said my last guess was wrong
    morseWrong = me.wrong;
    morseErrorUntil = performance.now() + 2500;
    const form = $("morse-form");
    form.classList.remove("error");
    void form.offsetWidth; // restart the shake
    form.classList.add("error");
    $("morse-input").select();
    if (navigator.vibrate) navigator.vibrate([60, 40, 60]);
    setTimeout(() => {
      if (session.phase === "playing" && session.game.id === "morse" && session.role === "player") renderMorse(session);
    }, 2600); // clear the error
  }

  const input = $("morse-input");
  input.maxLength = st.length;
  input.disabled = me.out;
  renderMorseSlots(st);
  $("morse-submit").disabled = me.out || st.stage === "intro" || input.value.length !== st.length;

  const guesses = `${me.attempts} guess${me.attempts === 1 ? "" : "es"} left`;
  let msg, sub;
  if (performance.now() < morseErrorUntil) {
    [msg, sub] = me.out ? ["Wrong! You're out", "Out of guesses. Watch the others"] : ["Wrong!", guesses];
  } else if (me.out) {
    [msg, sub] = ["Out of guesses", "Watch the others"];
  } else if (st.stage === "intro") {
    [msg, sub] = ["Get ready…", "Short flash = dot, long flash = dash"];
  } else if (st.stage === "last") {
    [msg, sub] = [`Last chance: ${st.last_chance}`, `The strip won't play it again · ${guesses}`];
  } else {
    const play = st.plays ? `Play ${st.play} of ${st.plays}` : `Play ${st.play}`;
    msg = st.letter === null ? "End of word" : `Letter ${st.letter + 1} of ${st.length}`;
    sub = `${play} · ${guesses}`;
  }
  $("morse-msg").textContent = msg;
  $("morse-sub").textContent = sub;
}

function renderMorseSlots(st) {
  const box = $("morse-slots");
  const typed = $("morse-input").value;
  if (box.children.length !== st.length) {
    box.innerHTML = "";
    for (let i = 0; i < st.length; i++) box.appendChild(document.createElement("div"));
  }
  [...box.children].forEach((d, i) => {
    d.textContent = typed[i] || "";
    d.classList.toggle("playing", st.stage === "play" && st.letter === i);
  });
}

$("morse-input").addEventListener("input", (e) => {
  const st = session.state;
  e.target.value = e.target.value.replace(/[^a-z]/gi, "").toUpperCase().slice(0, st ? st.length : 6);
  if (session.game && session.game.id === "morse" && st) {
    renderMorseSlots(st);
    $("morse-submit").disabled = e.target.value.length !== st.length || st.stage === "intro";
  }
});

$("morse-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const st = session.state;
  const guess = $("morse-input").value;
  if (!st || guess.length !== st.length || st.stage === "intro") return;
  send({ type: "input", action: { guess } });
});

// --- red light, green light ------------------------------------------------------

let rlHolding = false;

function rlName(st, i, you) {
  return sumoName(st, i, you);
}

function renderRedLight(s) {
  show("rl");
  const st = s.state;
  const me = st.players[s.you];
  $("rl-quit").classList.toggle("hidden", !s.host);
  const mode = st.mode === "clock" ? "Beat the clock" : st.mode === "computer" ? "vs the computer" : `${st.players.length} players`;
  $("rl-label").textContent = `${mode} · ${s.difficulty}`;

  const lanes = $("rl-lanes");
  if (lanes.children.length !== st.players.length) {
    lanes.innerHTML = "";
    for (const _ of st.players) {
      const lane = document.createElement("div");
      lane.className = "rl-lane";
      lane.innerHTML = `<span></span><div class="track"><div class="fill"></div></div>`;
      lanes.appendChild(lane);
    }
  }
  st.players.forEach((p, i) => {
    const lane = lanes.children[i];
    lane.className = "rl-lane" + (i === s.you ? " you" : "") + (p.caught ? " caught" : "") + (p.left ? " left" : "");
    lane.querySelector("span").textContent = rlName(st, i, s.you) + (p.left ? " · left" : "");
    const fill = lane.querySelector(".fill");
    fill.style.width = `${Math.max(2, p.progress)}%`;
    fill.style.background = p.hex;
  });

  const pad = $("rl-pad");
  pad.className = `pad rl-pad ${st.light}` + (rlHolding ? " holding" : "") + (me.caught ? " caught" : "");
  let text, msg, sub;
  if (st.stage === "countdown") {
    [text, msg, sub] = [st.countdown, "Get ready…", "Hold the button to climb, let go on red"];
  } else if (me.caught) {
    [text, msg, sub] = ["CAUGHT!", "You moved on red", "Wait for green"];
  } else if (st.light === "red") {
    [text, msg, sub] = ["STOP!", "Red light!", "Don't move"];
  } else if (st.light === "yellow") {
    [text, msg, sub] = ["SLOW…", "Yellow!", "Red is coming"];
  } else {
    [text, msg, sub] = [rlHolding ? "GO! GO!" : "HOLD", "Green light!", "Hold to climb"];
  }
  if (st.time_left !== null && st.stage === "race") sub = `${st.time_left} s left`;
  $("rl-pad-text").textContent = text;
  $("rl-msg").textContent = msg;
  $("rl-sub").textContent = sub;
}

function rlHold(hold) {
  if (hold === rlHolding) return;
  rlHolding = hold;
  send({ type: "input", action: { hold, at: serverNow() } });
  if (hold && navigator.vibrate) navigator.vibrate(10);
  if (session.phase === "playing" && session.game.id === "red_light" && session.role === "player") renderRedLight(session);
}

{
  const pad = $("rl-pad");
  pad.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    pad.setPointerCapture(e.pointerId); // keep holding even if the finger slides off
    rlHold(true);
  });
  for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) pad.addEventListener(ev, () => rlHold(false));
  pad.addEventListener("contextmenu", (e) => e.preventDefault()); // long press
  // Switching apps or locking the phone lets go.
  document.addEventListener("visibilitychange", () => { if (document.hidden) rlHold(false); });
  window.addEventListener("blur", () => rlHold(false));
}

// --- hot potato ---------------------------------------------------------------

let hpLast = { holder: null, out: false }; // to buzz when the potato lands on you or you go out

function hpName(st, i, you) {
  const p = st.players[i];
  if (p.cpu) return `${capitalize(p.color)} 🤖`;
  return i === you ? "You" : capitalize(p.color);
}

// The pad's color, from orange to red as the potato heats up.
function hpHeatColor(heat) {
  return `rgb(255, ${Math.round(150 * (1 - heat))}, ${Math.round(40 * (1 - heat))})`;
}

function renderHotPotato(s) {
  show("hp");
  const st = s.state;
  const me = st.players[s.you];
  $("hp-quit").classList.toggle("hidden", !s.host);
  const mode = st.mode === "computer" ? `vs ${st.players.length - 1} computers` : `${st.players.length} players`;
  $("hp-label").textContent = `${mode} · ${s.difficulty}` + (st.round ? ` · round ${st.round}` : "");

  const chips = $("hp-players");
  chips.innerHTML = "";
  st.players.forEach((p, i) => {
    const c = document.createElement("div");
    c.className = "hp-chip" + (i === s.you ? " you" : "") + (i === st.holder ? " holder" : "") + (p.out || p.left ? " out" : "");
    c.innerHTML = "<i></i><span></span>";
    c.querySelector("i").style.background = p.hex;
    c.querySelector("span").textContent = hpName(st, i, s.you) + (i === st.holder ? " 🥔" : "");
    chips.appendChild(c);
  });

  const mine = st.holder === s.you;
  if (mine && hpLast.holder !== s.you && navigator.vibrate) navigator.vibrate(60);
  if (me.out && !hpLast.out && navigator.vibrate) navigator.vibrate([200, 80, 300]);
  hpLast = { holder: st.holder, out: me.out };

  const pad = $("hp-pad");
  let cls = "", text, msg, sub;
  if (st.stage === "countdown") {
    [text, msg, sub] = [st.countdown, "Get ready…", "When the potato lands on you, tap to throw it on"];
  } else if (me.out) {
    cls = "out";
    [text, msg, sub] = ["OUT", "Boom! You're out", "Watch who's next"];
  } else if (st.stage === "boom") {
    [text, msg, sub] = ["💥", `${hpName(st, st.victim, s.you)} ${st.victim === s.you ? "are" : "is"} out!`, "Next round coming…"];
  } else if (mine && st.ready) {
    cls = "hot";
    [text, msg, sub] = ["THROW!", "It's yours!", "Tap to get rid of it"];
  } else if (mine) {
    cls = "catching";
    [text, msg, sub] = [st.flying ? "INCOMING!" : "CATCHING…", "It's coming to you!", "Get ready to throw"];
  } else {
    const who = st.holder === null ? "" : hpName(st, st.holder, s.you);
    [text, msg, sub] = ["Safe…", "…for now", who ? `${who} ${st.flying ? "is getting" : "has"} the potato` : ""];
  }
  pad.className = "pad hp-pad" + (cls ? ` ${cls}` : "");
  pad.style.setProperty("--heat", hpHeatColor(st.heat));
  $("hp-pad-text").textContent = text;
  $("hp-msg").textContent = msg;
  $("hp-sub").textContent = sub;
}

{
  const pad = $("hp-pad");
  pad.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    send({ type: "input", action: { throw: true, at: serverNow() } });
    pad.classList.add("pressed");
    if (navigator.vibrate) navigator.vibrate(10);
  });
  for (const ev of ["pointerup", "pointercancel", "pointerleave"]) pad.addEventListener(ev, () => pad.classList.remove("pressed"));
  pad.addEventListener("contextmenu", (e) => e.preventDefault());
}

// --- ping pong ----------------------------------------------------------------

function pongName(st, i, you) {
  return sumoName(st, i, you);
}

function renderPongScore(st, you) {
  const [a, b] = st.players;
  $("pong-score-a").textContent = a.score;
  $("pong-score-a").style.color = a.hex;
  $("pong-score-b").textContent = b.score;
  $("pong-score-b").style.color = b.hex;
  $("pong-name-a").textContent = `${pongName(st, 0, you)} · bottom`;
  $("pong-name-b").textContent = `${pongName(st, 1, you)} · top`;
}

function renderPong(s) {
  show("pong");
  const st = s.state;
  const me = st.players[s.you];
  $("pong-quit").classList.toggle("hidden", !s.host);
  $("pong-label").textContent = st.solo
    ? `You vs the computer · ${s.difficulty} · first to ${st.target}`
    : `You're ${me.color.toUpperCase()} · first to ${st.target}`;
  renderPongScore(st, s.you);
  $("pong-pad").style.background = me.hex;

  let msg, sub;
  if (st.stage === "serve") {
    if (st.last_point === null) {
      [msg, sub] = ["Get ready…", `Your racket is at the ${s.you === 0 ? "bottom" : "top"}`];
    } else {
      msg = st.last_point === s.you ? "Point! 🎉" : `${pongName(st, st.last_point, s.you)} scores`;
      sub = "Next serve coming…";
    }
  } else {
    [msg, sub] = ["Watch the ball!", "Swing as it reaches your racket"];
  }
  $("pong-msg").textContent = msg;
  $("pong-sub").textContent = sub;
}

let pongCoolUntil = 0;

$("pong-pad").addEventListener("pointerdown", (e) => {
  e.preventDefault();
  const now = performance.now();
  if (now < pongCoolUntil) return; // the Pi would ignore it anyway
  const cooldown = (session.state && session.state.cooldown) || 0;
  pongCoolUntil = now + cooldown * 1000;
  send({ type: "input", action: { tap: true, at: serverNow() } });
  if (navigator.vibrate) navigator.vibrate(12);
  const pad = $("pong-pad");
  pad.classList.add("cooling");
  setTimeout(() => pad.classList.remove("cooling"), cooldown * 1000);
});

// --- spectate & result -------------------------------------------------------------

function renderSpectate(s) {
  show("spectate");
  const st = s.state;
  $("spectate-title").textContent = spectateLine[0];
  $("spectate-sub").textContent = spectateLine[1];
  const shooter = s.game.id === "color_shooter";
  const simon = s.game.id === "simon";
  $("spectate-shooter").classList.toggle("hidden", !shooter && !simon);
  $("spectate-board").classList.toggle("hidden", shooter);
  $("spectate-label").textContent = simon ? "Sequence" : "Score";
  $("spectate-danger").classList.toggle("hidden", !shooter);
  if (simon) {
    setScore($("spectate-score"), st.length);
    $("spectate-goal").textContent = st.target;
    renderBoard($("spectate-board"), simonBoard(st), null);
  } else if (shooter) {
    setScore($("spectate-score"), st.score);
    $("spectate-goal").textContent = st.goal;
    $("spectate-danger-bar").style.width = `${st.danger * 100}%`;
  } else if (s.game.id === "sumo" || s.game.id === "ping_pong") {
    const players = st.players.map((p, i) => ({ ...p, color: sumoName(st, i, null), wins: p.score || 0, active: true }));
    renderBoard($("spectate-board"), { players, solo: false }, null);
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
  if (s.game.id === "sumo") {
    const w = st.winner;
    if (st.solo) {
      $("result-emoji").textContent = won ? "🏆" : "🤖";
      $("result-title").textContent = won ? (mine ? "You pushed it off!" : "The player won!") : "The computer won";
    } else {
      $("result-emoji").textContent = "🏆";
      $("result-title").textContent = w === s.you ? "You win! 🎉" : `${capitalize(st.players[w].color)} wins!`;
    }
    const taps = st.players.map((p, i) => `${sumoName(st, i, mine ? s.you : null)} ${p.taps} taps`).join(" · ");
    $("result-sub").textContent = st.forfeit ? "The other player left" : taps;
    return;
  }
  if (s.game.id === "ping_pong") {
    const w = st.winner;
    if (st.solo) {
      $("result-emoji").textContent = won ? "🏓" : "🤖";
      $("result-title").textContent = won ? (mine ? "You beat the computer!" : "The player won!") : "The computer won";
    } else {
      $("result-emoji").textContent = "🏆";
      $("result-title").textContent = w === s.you ? "You win! 🎉" : `${capitalize(st.players[w].color)} wins!`;
    }
    const score = st.players.map((p, i) => `${pongName(st, i, mine ? s.you : null)} ${p.score}`).join(" · ");
    $("result-sub").textContent = st.forfeit ? "The other player left" : score;
    return;
  }
  if (s.game.id === "simon") {
    const w = st.winners;
    if (st.mode === "solo") {
      $("result-emoji").textContent = won ? "🧠" : "🙊";
      $("result-title").textContent = won ? (mine ? "You beat Simon!" : "They beat Simon!") : "Simon got you";
      $("result-sub").textContent = won
        ? `All ${st.target} colors · ${s.difficulty}`
        : `Remembered ${st.reached} of ${st.target} · ${s.difficulty}`;
    } else if (w.length === 1) {
      $("result-emoji").textContent = "🏆";
      $("result-title").textContent = w[0] === s.you ? "You win! 🎉" : `${capitalize(st.players[w[0]].color)} wins!`;
      $("result-sub").textContent = `Last one standing · ${st.reached} colors`;
    } else {
      $("result-emoji").textContent = "🤝";
      $("result-title").textContent = w.includes(s.you) ? "You share the win! 🎉" : "Shared win!";
      $("result-sub").textContent = `${simonNames(st, w, s.you)} made it to ${st.target}`;
    }
    return;
  }
  if (s.game.id === "red_light") {
    const w = st.winner;
    const time = st.finish_time !== null ? `${st.finish_time} s` : "";
    const caught = (i) => `caught ${st.players[i].times_caught}×`;
    if (st.mode === "clock") {
      $("result-emoji").textContent = won ? "🏁" : "⏰";
      $("result-title").textContent = won ? (mine ? "You made it!" : "They made it!") : "Out of time";
      $("result-sub").textContent = won ? `${time} · ${caught(0)} · ${s.difficulty}` : `Got ${st.players[0].progress}% of the way · ${s.difficulty}`;
    } else if (st.mode === "computer") {
      $("result-emoji").textContent = won ? "🏁" : "🤖";
      $("result-title").textContent = won ? (mine ? "You beat the computer!" : "The player won!") : "The computer won";
      $("result-sub").textContent = `${time} · ${s.difficulty}`;
    } else {
      $("result-emoji").textContent = "🏁";
      $("result-title").textContent = w === s.you ? "You win! 🎉" : `${capitalize(st.players[w].color)} wins!`;
      $("result-sub").textContent = `${time} · ${caught(w)}`;
    }
    return;
  }
  if (s.game.id === "hot_potato") {
    const w = st.winner;
    if (st.mode === "computer") {
      $("result-emoji").textContent = won ? "🥔" : "💥";
      $("result-title").textContent = won ? (mine ? "You outlasted the computers!" : "The player won!") : "Boom! You're out";
      const left = st.players.filter((p) => p.cpu && !p.out).length;
      $("result-sub").textContent = won ? `${st.round} rounds · ${s.difficulty}` : `Round ${st.round} · ${left} computer${left === 1 ? "" : "s"} left · ${s.difficulty}`;
    } else if (w !== null) {
      $("result-emoji").textContent = "🏆";
      $("result-title").textContent = w === s.you ? "You win! 🎉" : `${capitalize(st.players[w].color)} wins!`;
      $("result-sub").textContent = `Last one standing · ${st.round} rounds`;
    } else {
      $("result-emoji").textContent = "💥";
      $("result-title").textContent = "Game over";
      $("result-sub").textContent = `${st.round} rounds`;
    }
    return;
  }
  if (s.game.id === "morse") {
    const word = (st.word || "").toUpperCase();
    const w = st.winners;
    if (won && st.solo) {
      $("result-emoji").textContent = "📡";
      $("result-title").textContent = mine ? "You cracked it!" : "They cracked it!";
    } else if (won) {
      $("result-emoji").textContent = "🏆";
      $("result-title").textContent = w[0] === s.you ? "You cracked it first! 🎉" : `${capitalize(st.players[w[0]].color)} cracked it!`;
    } else {
      $("result-emoji").textContent = "📻";
      $("result-title").textContent = st.solo ? (mine ? "Not this time" : "They didn't get it") : "Nobody got it";
    }
    $("result-sub").textContent = `The word was ${word} · ${s.difficulty}`;
    return;
  }
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

// Players are still tapping when the game ends: keep the buttons off for a
// moment so a late tap doesn't start a new game.
const RESULT_LOCK = 5;

function lockResult() {
  const again = $("again-btn");
  const home = $("home-btn");
  clearInterval(lockResult.timer);
  let left = RESULT_LOCK;
  const tick = () => {
    const locked = left > 0;
    again.disabled = home.disabled = locked;
    again.textContent = locked ? `Play again (${left})` : "Play again";
    left--;
    if (!locked) clearInterval(lockResult.timer);
  };
  tick();
  lockResult.timer = setInterval(tick, 1000);
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
$("quit-btn").onclick = $("tap-quit").onclick = $("sumo-quit").onclick = $("simon-quit").onclick = $("pong-quit").onclick = $("morse-quit").onclick = $("rl-quit").onclick = $("hp-quit").onclick = () => {
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
    if (view === "device") pollDevice();
    if (view === "lights") loadLights();
  };
}

// --- full screen ---------------------------------------------------------------

// iPhones only allow full screen for videos, so the button only shows where it works.
{
  const root = document.documentElement;
  const enter = root.requestFullscreen || root.webkitRequestFullscreen;
  const exit = document.exitFullscreen || document.webkitExitFullscreen;
  const current = () => document.fullscreenElement || document.webkitFullscreenElement;
  const btn = $("fullscreen-btn");
  // Corners pointing out (enter) or in (exit).
  const icon = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
  const ENTER = icon("M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5");
  const EXIT = icon("M9 4v5H4M20 9h-5V4M15 20v-5h5M4 15h5v5");
  const update = () => {
    btn.innerHTML = current() ? EXIT : ENTER;
    btn.setAttribute("aria-label", current() ? "Exit full screen" : "Full screen");
  };
  if (enter) {
    btn.classList.remove("hidden");
    btn.onclick = () => (current() ? exit.call(document) : enter.call(root))?.catch?.(() => {});
    document.addEventListener("fullscreenchange", update);
    document.addEventListener("webkitfullscreenchange", update);
    update();
  }
}

// --- invite --------------------------------------------------------------------

for (const b of document.querySelectorAll(".invite-btn")) {
  b.onclick = async () => {
    $("invite-qr").src = `/invite.svg?t=${Date.now()}`;
    $("invite-url").textContent = "";
    $("invite").classList.remove("hidden");
    try {
      const r = await (await fetch("/api/invite")).json();
      // The IP address works on every phone; also show the name if that's
      // what this phone used.
      $("invite-url").textContent = r.host_url !== r.url ? `${r.url}\nor ${r.host_url}` : r.url;
    } catch (err) {}
  };
}
$("invite-close").onclick = () => $("invite").classList.add("hidden");
$("invite").onclick = (e) => {
  if (e.target === $("invite")) $("invite").classList.add("hidden");
};

// --- device settings -------------------------------------------------------------

const UPDATE_TEXT = {
  off: () => "Updates are off on this unit (development install).",
  idle: () => "Checks for updates automatically.",
  checking: () => "Checking for updates…",
  up_to_date: () => "You have the latest version.",
  available: (u) => `Version ${u.latest} is available.` + (u.auto ? " It installs by itself when nobody is playing." : ""),
  installing: (u) => `Installing ${u.latest}… the strip shows purple dots.`,
  restarting: () => "Restarting with the new version…",
  error: (u) => u.error || "Something went wrong.",
};

async function postJSON(url, body = {}) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const res = await r.json().catch(() => ({}));
  if (res.error) toast(res.error);
  return res;
}

async function pollDevice() {
  clearTimeout(pollDevice.timer);
  if (view !== "device") return;
  try {
    renderDevice(await (await fetch("/api/device", { cache: "no-store" })).json());
  } catch (err) {}
  pollDevice.timer = setTimeout(pollDevice, 3000);
}

function renderDevice(d) {
  $("device-name").textContent = d.name;
  $("device-version").textContent = d.version;
  $("device-wifi").textContent = d.wifi ? (d.wifi.ssid || (d.wifi.mode === "online" ? "Ethernet" : d.wifi.mode)) : "—";
  $("device-address").textContent = d.local_url ? d.local_url.replace("http://", "") : location.host;
  const u = d.update;
  $("update-status").textContent = (UPDATE_TEXT[u.status] || UPDATE_TEXT.idle)(u);
  const btn = $("update-btn");
  btn.classList.toggle("hidden", u.status === "off");
  btn.disabled = ["checking", "installing", "restarting"].includes(u.status);
  if (u.status === "available") {
    btn.textContent = `Install ${u.latest} now`;
    btn.onclick = () => postJSON("/api/device/update", { action: "install" }).then(pollDevice);
  } else {
    btn.textContent = "Check for updates";
    btn.onclick = () => postJSON("/api/device/update", { action: "check" }).then(pollDevice);
  }
  const leds = $("leds-input");
  leds.max = d.max_leds;
  // Polling mustn't overwrite a number being typed.
  if (document.activeElement !== leds && !leds.dataset.edited) leds.value = d.leds;
  for (const id of ["leds-save", "leds-test"]) $(id).disabled = d.busy;
  $("mic-section").classList.toggle("hidden", !d.mic);
  if (d.mic) {
    $("mic-text").textContent = d.mic.available
      ? "How much sound it takes to fill the strip in the Sound level light effect. It still adjusts to how loud the room is."
      : "No microphone found. Check its wiring, then restart the unit.";
    $("mic-controls").classList.toggle("hidden", !d.mic.available);
    const s = $("mic-sensitivity");
    if (document.activeElement !== s && !micTimer) s.value = d.mic.sensitivity;
  }
  $("wifi-setup-btn").classList.toggle("hidden", !d.wifi);
  $("wifi-setup-btn").onclick = async () => {
    const msg = `${d.name} will leave this network. Then join the Wi-Fi network “${d.wifi.hotspot}” `
      + "(password on the sticker) to pick a new one.\n\nIf nobody does, it goes back to this network in about 5 minutes.";
    if (confirm(msg)) await postJSON("/api/device/wifi-setup");
  };
}

// --- lights --------------------------------------------------------------------

let lights = null;      // settings plus the effect and palette lists, from /api/lights
let lightsPending = {}; // changes not sent yet (sliders send at most ~8 times a second)
let lightsTimer = null;

async function loadLights() {
  try {
    lights = await (await fetch("/api/lights", { cache: "no-store" })).json();
    renderLights();
  } catch (err) {}
}

function setLights(changes) {
  Object.assign(lights, changes);
  Object.assign(lightsPending, changes);
  renderLights();
  if (!lightsTimer) lightsTimer = setTimeout(sendLights, 120);
}

async function sendLights() {
  const body = lightsPending;
  lightsPending = {};
  let res = {};
  try {
    res = await postJSON("/api/lights", body);
  } catch (err) {}
  lightsTimer = null;
  if (Object.keys(lightsPending).length) sendLights();
  else if (res.error === null) { lights = res; renderLights(); } // e.g. the custom swatch's new color
}

function renderLights() {
  if (!lights) return;
  const power = $("lights-power");
  power.textContent = lights.on ? "Turn off" : "Turn on";
  power.className = lights.on ? "secondary" : "primary";

  const fx = $("lights-effects");
  fx.innerHTML = "";
  for (const e of lights.effects) {
    // Picking an effect turns the lights on.
    const desc = !e.sound ? "" : lights.mic ? "🎤 Reacts to sound" : "Needs a microphone";
    fx.appendChild(card(e.name, desc, lights.on && lights.effect === e.id, () => setLights({ effect: e.id, on: true })));
  }

  const pal = $("lights-palettes");
  pal.innerHTML = "";
  for (const p of lights.palettes) {
    const b = document.createElement("button");
    b.className = "swatch" + (lights.palette === p.id ? " selected" : "");
    b.innerHTML = `<div class="bar"></div><span></span>`;
    b.querySelector(".bar").style.background = p.id === "custom" ? lights.color : p.css;
    b.querySelector("span").textContent = p.name;
    b.onclick = () => setLights({ palette: p.id });
    pal.appendChild(b);
  }
  $("lights-color-row").classList.toggle("hidden", lights.palette !== "custom");

  // Don't move a slider (or the color) under the finger.
  for (const [id, key] of [["lights-color", "color"], ["lights-speed", "speed"], ["lights-level", "level"]]) {
    if (document.activeElement !== $(id)) $(id).value = lights[key];
  }
}

$("lights-power").onclick = () => setLights({ on: !lights.on });
$("lights-color").oninput = (e) => setLights({ color: e.target.value });
$("lights-speed").oninput = (e) => setLights({ speed: Number(e.target.value) });
$("lights-level").oninput = (e) => setLights({ level: Number(e.target.value) });

$("leds-input").oninput = () => { $("leds-input").dataset.edited = "1"; };
$("leds-save").onclick = async () => {
  const input = $("leds-input");
  const count = Number(input.value);
  const res = await postJSON("/api/device/leds", { count });
  if (res.error === null) {
    delete input.dataset.edited;
    input.blur();
    toast(`Saved: ${count} LEDs. Watch the test on the strip.`);
  }
  pollDevice();
};
$("leds-test").onclick = () => postJSON("/api/device/test-leds");

// The slider sends at most ~8 changes a second.
let micTimer = null;
function sendMic() {
  if (micTimer) return;
  micTimer = setTimeout(async () => {
    const sensitivity = Number($("mic-sensitivity").value);
    await postJSON("/api/device/mic", { sensitivity });
    micTimer = null;
    if (Number($("mic-sensitivity").value) !== sensitivity) sendMic(); // moved while sending
  }, 120);
}
$("mic-sensitivity").oninput = sendMic;

connect();
