# Game ideas

Ideas for new games on the vertical LED strip, played from phones. Most work
with 1–6 players and don't depend on split-second taps, since the Pi Zero W's
Wi-Fi still stalls now and then (taps carry a timestamp, which covers most of
that).

## Party games for a group

### 1. Red Light, Green Light race (built)
Each player is a dot of their color at the bottom of the strip. Hold your
button to climb while the strip glows green. When it turns red, anyone still
holding after a short grace period slides back down. The first to reach the
top wins.

- Simple, tense, and works for 6 players.
- The timestamped taps we already have make it fair over Wi-Fi.

### 2. Hot Potato (built)
A glowing "potato" bounces between the players' color zones on the strip.
Tap to throw it on when it's in your zone. A hidden fuse runs out at a random
moment, and whoever holds it is out, until one player is left. The pace
speeds up each round.

### 3. Freeze
The strip plays a lively animation, then suddenly freezes. The last player to
tap is out. A quick, funny elimination game that's easy to explain.

## Skill games, solo or taking turns

### 4. Tower stack
A block of LEDs slides up and down above your tower. Tap to drop it: whatever
hangs past the block below is cut off, so the blocks shrink and keep getting
faster. Build as high as you can, or take turns and compare heights.

- Very visual on a tall strip.
- The best of these to play alone.

### 5. Stop the light
A dot races up the strip toward a marked target zone. Tap to stop it as close
to the target as you can; points depend on how close you get, and the target
shrinks every round. A precision cousin of Fast Tap.

### 6. Inner clock
The strip lights up for a few seconds, then goes dark. Tap when you think the
same amount of time has passed. The closest player wins the round. Wi-Fi
delays don't matter here at all.

## Thinking games, where timing doesn't matter

### 7. Color match
The strip shows a target color. Mix it on your phone with red, green and blue
sliders, and your guess appears on part of the strip next to the target. The
closest mix wins. Surprisingly hard, and it makes people laugh.

### 8. Hot and cold
One LED is secretly the treasure. Players take turns picking a spot on a
slider; the strip glows from blue (cold) to red (hot) depending on how close
the pick is. The fewest guesses wins.

## Not a good fit

- **Shake or tilt games:** phone motion sensors need HTTPS, and the unit
  serves plain HTTP.

## Picks

- **Red Light, Green Light** for groups: instantly understood and exciting
  with 6 phones.
- **Tower stack** for playing alone: looks great on a tall strip.
