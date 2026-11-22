"""The speaker (a MAX98357A amplifier on I2S, see the README): plays sounds
through pygame's mixer, at the volume set on the device page.

The amplifier switches itself off when the sound card stops its clock, and
on again when it starts, and each switch knocks in the speaker. So the
mixer keeps the sound card open all the time, playing silence between
sounds. It mixes in a thread of its own (in C), and decodes MP3s.

The sound card runs at RATE the whole time; the microphone shares its clock,
so it records at the same rate (see audio.py).

Loading pygame takes ~8 s on a Pi Zero, so `start()` does it in a thread
once the server is up; sounds play from then on.
"""

import asyncio
import logging
import math
import os
import re
from array import array
from pathlib import Path

log = logging.getLogger(__name__)

RATE = 48_000
BUFFER = 1024  # frames the mixer works ahead: ~21 ms
LOUDEST = 0.9  # of full scale, at volume 1: headroom so sounds that add up don't clip


def find_device(pcm: Path = Path("/proc/asound/pcm"), cards: Path = Path("/proc/asound/cards")) -> str | None:
    """The first sound card that can play, other than HDMI, as an ALSA device name."""
    try:
        pcm_lines = pcm.read_text().splitlines()
        card_text = cards.read_text()
    except OSError:
        return None
    # " 0 [vc4hdmi        ]: vc4-hdmi - vc4-hdmi"
    hdmi = {int(n) for n, name in re.findall(r"^\s*(\d+) \[(\S+)\s*\]", card_text, re.M) if "hdmi" in name.lower()}
    for line in pcm_lines:  # "01-00: Google voiceHAT ... : playback 1 : capture 1"
        if "playback" in line:
            card, dev = line.split(":")[0].split("-")
            if int(card) not in hdmi:
                return f"plughw:{int(card)},{int(dev)}"
    return None


def chime() -> list[float]:
    """The test sound: three rising notes that ring out, -1 to 1."""
    notes = [(523.25, 0.0), (659.25, 0.12), (783.99, 0.24)]  # C5, E5, G5 and when each starts
    length = 0.9
    out = [0.0] * int(RATE * length)
    for freq, start in notes:
        step = 2 * math.pi * freq / RATE
        first = int(start * RATE)
        for i in range(first, len(out)):
            t = (i - first) / RATE
            attack = min(1.0, t / 0.005)  # 5 ms, no click
            out[i] += 0.33 * attack * math.exp(-t * 5) * math.sin(step * (i - first))
    return out


SOUNDS = {"chime": chime}  # name → its samples (mono, RATE a second, -1 to 1)


def to_pcm(sound: list[float]) -> bytes:
    """16-bit samples, at full volume less LOUDEST's headroom."""
    gain = 32767 * LOUDEST
    return array("h", [int(s * gain) for s in sound]).tobytes()


def volume_level(volume: float) -> float:
    """The mixer's level for a volume setting: loudness follows it more
    evenly squared, the way volume knobs feel."""
    return volume * volume


def open_mixer(device: str):
    """pygame's mixer, playing on `device` (blocks for seconds)."""
    os.environ.update(SDL_AUDIODRIVER="alsa", AUDIODEV=device, PYGAME_HIDE_SUPPORT_PROMPT="1")
    import pygame.mixer as mixer

    mixer.pre_init(frequency=RATE, size=-16, channels=1, buffer=BUFFER)
    mixer.init()
    return mixer


class Speaker:
    def __init__(self, device: str = "auto", opener=open_mixer):
        self.device = find_device() if device == "auto" else device
        self.on = True
        self.volume = 0.5  # 0–1, set on the device page
        self.mixer = None  # pygame.mixer, once it's open
        self._open = opener
        self._sounds: dict = {}  # name → the mixer's Sound

    @property
    def available(self) -> bool:
        return self.device is not None

    @property
    def playing(self) -> bool:
        return bool(self.mixer and self.mixer.get_busy())

    def settings(self) -> dict:
        return {"on": self.on, "volume": self.volume}

    def update(self, changes: dict) -> str | None:
        """Apply some settings. Returns an error message (and changes
        nothing) if any of them is invalid."""
        on, volume = changes.get("on", self.on), changes.get("volume", self.volume)
        if not isinstance(on, bool):
            return "Invalid on."
        if not isinstance(volume, (int, float)) or isinstance(volume, bool) or not 0 <= volume <= 1:
            return "Invalid volume."
        self.on, self.volume = on, float(volume)
        if not on:
            self.stop()
        return None

    async def start(self) -> None:
        """Open the sound card, and keep it open."""
        if not self.available:
            return
        try:
            self.mixer = await asyncio.to_thread(self._open, self.device)
        except Exception as e:  # pygame missing, or the sound card won't open
            log.warning("speaker: %s", e)
            return
        log.info("speaker: ready on %s", self.device)

    def play(self, name: str) -> bool:
        """Play one of SOUNDS, cutting off any sound still playing. Returns
        False if it can't play (no speaker, sound off, or not ready yet)."""
        if not (self.mixer and self.on):
            return False
        sound = self._sounds.get(name)
        if sound is None:
            sound = self._sounds[name] = self.mixer.Sound(buffer=to_pcm(SOUNDS[name]()))
        self.mixer.stop()
        sound.set_volume(volume_level(self.volume))
        sound.play()
        return True

    def stop(self) -> None:
        if self.mixer:
            self.mixer.stop()

    def close(self) -> None:
        if self.mixer:
            self.mixer.quit()
            self.mixer = None
