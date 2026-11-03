# LED Games

Games for a vertical WS2812B LED strip driven by a Raspberry Pi Zero W and
played from a phone browser.

## Games

### Color Shooter
A colored snake creeps down from the top of the strip toward the white shooter
(bottom 3 LEDs). Tap a color to shoot it upward; a shot crosses the whole strip in 2 seconds.

- Shot matches the snake's bottom LED: that LED is eaten, **+1 point**.
- Shot doesn't match: it joins the snake, **−1 point** (score can go negative).
- Reach the goal: fireworks. Snake touches the shooter: the strip fills red.

| Difficulty | Colors | New segment every | Goal |
|---|---|---|---|
| Easy | 3 | 2.5 s | 100 |
| Normal | 4 | 2.0 s | 150 |
| Hard | 5 | 1.5 s | 200, spits poison |
| Insane | 5 | 1.5 s | 250, spits poison; snake shows white and flashes its colors for 0.3 s every 2 s |

**Poison (Hard and Insane):** every 5–10 s the snake spits a colored poison
down at the shooter, a bit slower than a shot (2.5 s to cross the strip). A
shot of the same color destroys it; other colors pass through each other. If
the poison reaches the shooter, the shooter flashes the poison color and can't
fire for 3 s.

Fire mode: **Rapid fire** (no limit) or **Cooldown** (0.3 s between shots).

Only one person plays at a time; anyone else who opens the page watches.

### Fast Tap (1–6 players)
One phone opens a lobby; anyone else on the Wi-Fi opens the page and taps
**Join**. Each player gets a color (blue, yellow, magenta, cyan, white,
orange) shown on the strip. The host starts the game.

The strip flashes red at random moments, then green. The first player to tap
during green wins the round (confetti in their color). Tapping at any other
time knocks you out of that round. If nobody taps green, the flashes keep
coming until someone wins the round or everyone is out.

- 3 rounds; most round wins takes the game. Ties go to sudden-death rounds
  between the leaders. The game ends early when nobody can catch the leader.
- Solo: best of 3; lose 2 rounds and the strip fills red.
- Easy: red flashes only, green lasts 0.5 s. Hard: fake flashes in other
  colors, green lasts 0.3 s.
- Fair over Wi-Fi: phones keep their clock in sync with the Pi and each tap
  carries the time it happened, so a laggier connection doesn't lose.

## Run on your computer (simulator)

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m ledgames --leds 250
```

- Controller: http://localhost:8080 (or `http://<your-computer-ip>:8080` from your phone)
- Virtual strip: http://localhost:8080/sim

Tests: `.venv/bin/python -m unittest`

To test multiplayer from one computer, give each tab its own player with
`?as=<name>`, e.g. http://localhost:8080/?as=1 and http://localhost:8080/?as=2.

## Options

Every option can be passed as a flag or an environment variable.

| Flag | Env | Default | |
|---|---|---|---|
| `--leds` | `LED_COUNT` | 250 | number of LEDs |
| `--backend` | `LED_BACKEND` | `sim` | `sim` or `ws281x` |
| `--pin` | `LED_PIN` | 18 | GPIO data pin |
| `--brightness` | `LED_BRIGHTNESS` | 0.5 | global brightness 0–1 |
| `--max-ma` | `LED_MAX_MA` | 0 | current budget in mA; frames are dimmed to stay under it (0 = off) |
| `--port` | `PORT` | 8080 | |

## Hardware

```
 5V PSU (+) ──────────────┬──────────────── strip 5V
                          ═ 1000µF
 5V PSU (−) ──────────────┴──────┬───────── strip GND
                                 │
 Pi GND ─────────────────────────┤
 Pi GPIO18 ── 74AHCT125 ── 330Ω ─┴───────── strip DIN   (LED 0 at the bottom)
```

- Power the strip from its own 5 V supply, **not** from the Pi. 250–300 LEDs can
  draw up to 15–18 A at full white; a 10 A supply plus `LED_MAX_MA` and
  brightness 0.5 is plenty for these games.
- The Pi and the strip must share ground.
- The 74AHCT125 level shifter (powered from 5 V) brings the Pi's 3.3 V data up
  to 5 V. It sometimes works without one, but it's flaky.
- For 250+ LEDs, inject power at both ends of the strip.

## Deploy to the Pi

```sh
# on the Pi (Raspberry Pi OS Lite)
sudo apt install -y python3-venv git
sudo mkdir -p /opt/ledgames && sudo chown $USER /opt/ledgames
# copy this project to /opt/ledgames (git clone or rsync), then:
cd /opt/ledgames
python3 -m venv .venv
.venv/bin/pip install -r requirements-pi.txt
sudo cp deploy/ledgames.service /etc/systemd/system/
sudo systemctl enable --now ledgames
```

Then open `http://<pi-hostname>.local` on your phone.

## Adding a game

1. Create `ledgames/games/<name>.py` with a subclass of `Game` (see
   `games/base.py`): `update(dt)`, `render(pixels)`, `on_input(player, action)`,
   `state()`. Set `max_players` and `player_colors` in its `info` for a
   multiplayer game; the engine handles the lobby.
2. Register it in `ledgames/games/__init__.py`.

The game list, difficulty and settings screens are generated from the game's
`info`. Reusable animations live in `ledgames/effects/`.
