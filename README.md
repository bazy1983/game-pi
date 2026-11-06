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

### Sumo (1–2 players)
A tapping tug-of-war. Red starts with the bottom quarter of the strip, blue
with the top quarter, after a 3-second countdown. Every tap lights one more
LED of your color. Once the colors meet, each tap pushes the other color back
one LED. Push the other player off the strip (your color fills it) to win.

- Two players: the host is red, the second phone is blue. If one leaves, the
  other wins. Easy has one big button. Medium has buttons 1 and 2, and hard
  has 1, 2 and 3: only the next button in the sequence (1, 2, 3, 1, 2, …)
  lights an LED, so hammering one button does nothing.
- Solo: you're red against the computer, which taps 3 times a second on easy,
  5 on medium and 7 on hard.

### Simon Says (1–6 players)
The strip plays a sequence of colors; repeat it with the color buttons on
your phone. Each round adds one color. Reach the target length to win; solo,
one mistake ends the game.

| Difficulty | Colors | Strip | Target |
|---|---|---|---|
| Easy | 4 | one zone per color (dim, the step flashes bright) | 8 |
| Normal | 4 | zones, faster playback | 12 |
| Hard | 5 | whole strip flashes, buttons shuffle every round | 16 |

Playback speeds up as the sequence grows. On easy and normal the phone's
buttons are stacked in the same order as the zones (top button = top zone).

With friends, pick a mode:
- **All at once:** everyone repeats the same sequence on their own phone.
  A mistake knocks you out. If everyone still in misses, nobody is out and the
  round is replayed with a new last color. Presses don't show on the strip.
- **Take turns:** no playback. On your turn, repeat the sequence from memory
  and add a color of your own; every press lights the strip so the others can
  learn it. A mistake knocks you out and the next player gets the same sequence.

Last one standing wins; everyone still in at the target shares the win.
Not pressing for 10 seconds counts as a mistake.

### Ping Pong (1–2 players)
Red's racket is the bottom 3 LEDs, blue's the top 3; the ball is white with a
fading trail. Tap to swing: the racket grows to 6 LEDs over 0.3 s and shrinks
back over 0.3 s, and you can't swing again until it's back. The ball only
bounces off a racket while it's growing. Let it past your end and the other
side scores; first to 5 wins.

- Each point starts at 100 LEDs per second, 10% faster every 10 hits.
- After a point the strip flashes the scorer's color and shows the score as
  dots at each end, then serves from the middle toward whoever lost it.
- Two players: the host is red, the second phone is blue. Solo: you're red
  and the computer returns 70% (easy), 80% (medium) or 93% (hard) of balls.

## Lights

Ambient effects that play on the strip whenever nobody is playing: ✨ Lights
on the home screen. A game takes over the strip; when it's over, the lights
fade back in. The choice is saved on the unit, so it survives a reboot.

- Effects: Flow, Aurora, Fire (rises from the bottom), Twinkle, Meteor,
  Ripples, Bouncing balls, Chase, Breathe, Still (the palette spread over the
  strip; with one color, a solid color).
- Colors: Rainbow, Fire, Ocean, Forest, Sunset, Party, Ice, or a color of
  your own. Every effect works with every palette.
- Speed (4× slower to 4× faster) and brightness (on top of the strip's own
  brightness and current limit).

To add an effect, write a class in `ledgames/effects/ambient.py` and add it to
`EFFECTS`. The Pi Zero has about 33 ms per frame for everything: keep per-LED
work in list comprehensions over precomputed tables (each effect takes
1–6 ms for 250 LEDs).

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

To try the Wi-Fi setup flow, run with `--wifi fake`: after 3 seconds the
simulator pretends it has no network and every page sends you to the setup
page. "Home Wi-Fi" with the password `password123` is the network that works.

## Options

Every option can be passed as a flag or an environment variable.

| Flag | Env | Default | |
|---|---|---|---|
| `--leds` | `LED_COUNT` | 250 | number of LEDs; a count saved on the device page wins over `LED_COUNT` (not over `--leds`) |
| `--backend` | `LED_BACKEND` | `sim` | `sim` or `ws281x` |
| `--pin` | `LED_PIN` | 18 | GPIO data pin |
| `--brightness` | `LED_BRIGHTNESS` | 0.5 | global brightness 0–1 |
| `--max-ma` | `LED_MAX_MA` | 0 | current budget in mA; frames are dimmed to stay under it (0 = off) |
| `--port` | `PORT` | 8080 | |
| `--wifi` | `WIFI` | `off` | Wi-Fi setup hotspot: `nm` (NetworkManager plus hostapd, on the Pi), `fake` (simulator), `off` |
| `--updates` | `UPDATES` | `auto` | over-the-air updates: `auto`, `manual` (device page button) or `off` |
| | `UPDATE_URL` | GitHub | where to look for releases (for testing) |
| | `LEDGAMES_STATE` | `/var/lib/ledgames` | unit identity (`device.json`) and device page settings (`settings.json`) |

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

On a fresh Raspberry Pi OS Lite (Bookworm or newer, with NetworkManager), copy
this project to the Pi and run the installer:

```sh
rsync -a --exclude .venv --exclude .git ./ pi@<pi>.local:ledgames-src/
ssh pi@<pi>.local 'sudo sh ledgames-src/deploy/install.sh'
```

It installs the packages, a Python environment in `/opt/ledgames/.venv`, the
code as a release in `/opt/ledgames/releases/<version>` (with
`/opt/ledgames/current` pointing at it) and the `ledgames` service. Run it
again to deploy changes; `RELEASE_NAME=dev` installs them as `releases/dev`
instead of under the version number.

Then open `http://<pi-hostname>.local` on your phone.

## Making a unit to sell

1. Flash Raspberry Pi OS Lite, set the Wi-Fi country, and run the installer
   (above).
2. Give the unit its identity and print its sticker:
   ```sh
   cd /opt/ledgames/current
   sudo /opt/ledgames/.venv/bin/python -m ledgames.provision --hostname --sticker ~/sticker.svg
   ```
   This renames the Pi to `ledgames` (so it's at http://ledgames.local) and
   makes a random password for its setup hotspot `LED Games <ID>`, where the
   ID comes from its serial number. The 70 × 35 mm
   sticker has a QR code that joins the hotspot.
3. Remove the factory Wi-Fi (`sudo nmcli con delete <name>`) so the unit
   starts in setup mode for its buyer.

### Wi-Fi setup

With no network to join (45 s after boot, or 2 minutes after losing it), the
unit starts its hotspot and the bottom of the strip breathes blue. A phone
that joins it gets the setup page by itself; the customer picks their network
and types the password. The strip flashes green when it's connected, red if
the password was wrong (and the hotspot comes back). If nobody uses the setup
page, the unit retries its saved networks every 5 minutes, so a router reboot
doesn't strand it.

The hotspot runs on hostapd and dnsmasq rather than NetworkManager's own
hotspot mode: on the Pi Zero W's Wi-Fi chip, phones never complete the WPA2
handshake with NetworkManager's. While it's up, NetworkManager lets go of
`wlan0`.

To move a unit to another network: Device settings → Change Wi-Fi network.

### LED strip

Device settings → LED strip sets how many LEDs the strip has (up to 1000);
it's saved on the unit and takes effect right away. Saving, or tapping
**Test LEDs**, plays a wiring check: a red dot climbs from the bottom to the
top, the strip turns red, green and blue, then the first and last LEDs blink
white. If the blinking LED isn't the top of the strip, the count is wrong.
Neither works during a game.

### Updates

Units check GitHub Releases every 6 hours and install new versions when
nobody has played for 10 minutes (or from Device settings). A release is
only installed if it's signed with the release key; if a new version crashes
before running for a minute, the unit goes back to the previous one.

To publish a release:

1. Bump `__version__` in `ledgames/__init__.py`, commit and push.
2. `.venv/bin/python tools/release.py --publish`

The signing key is `~/.config/ledgames/release-key.pem` on the computer that
made it. **Back it up**: units only accept releases signed with it. Updates
carry code only; a version that needs new system packages has to be installed
by hand.

## Adding a game

1. Create `ledgames/games/<name>.py` with a subclass of `Game` (see
   `games/base.py`): `update(dt)`, `render(pixels)`, `on_input(player, action)`,
   `state()`. Set `max_players` and `player_colors` in its `info` for a
   multiplayer game; the engine handles the lobby.
2. Register it in `ledgames/games/__init__.py`.

The game list, difficulty and settings screens are generated from the game's
`info`. Reusable animations live in `ledgames/effects/`.
