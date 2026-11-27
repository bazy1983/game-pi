"""The speaker (a MAX98357A amplifier on I2S, see the README): plays sounds
through pygame's mixer, at the volume set on the device page.

The amplifier switches itself off when the sound card stops its clock, and
on again when it starts, and each switch knocks in the speaker. So the
mixer keeps the sound card open all the time, playing silence between
sounds. It mixes in a thread of its own (in C), and decodes MP3s.

It plays through ALSA's dmix, not straight to the card: if the Pi is too
busy to keep the mixer fed (an "underrun"), the card itself would stop, and
knock. dmix keeps the card running and fills the gap with silence instead.
dmix is always stereo, so sounds are made stereo to match.

The sound card runs at RATE the whole time; the microphone shares its clock,
so it records at the same rate (see audio.py).

Loading pygame takes ~8 s on a Pi Zero, and making the sounds (see
sounds.py) ~35 s more, so `start()` does both in a thread once the server
is up; sounds play from then on. The made sounds are kept in `cache` (one
file, remade whenever sounds.py changes), so that's only after an update.
"""

import asyncio
import hashlib
import logging
import os
import pickle
import re
from array import array
from pathlib import Path

from . import sounds
from .sounds import RATE, SOUNDS

log = logging.getLogger(__name__)

CHANNELS = 16  # sounds playing at once (rapid fire adds up)
BUFFER = 1024  # frames the mixer works ahead: ~21 ms
LOUDEST = 0.9  # of full scale, at volume 1: headroom so sounds that add up don't clip


def find_device(pcm: Path = Path("/proc/asound/pcm"), cards: Path = Path("/proc/asound/cards")) -> str | None:
    """The first sound card that can play, other than HDMI, as its ALSA dmix
    device (dmix only knows cards by name)."""
    try:
        pcm_lines = pcm.read_text().splitlines()
        card_text = cards.read_text()
    except OSError:
        return None
    # " 1 [sndrpigooglevoi]: RPi-simple - snd_rpi_googlevoicehat_soundcar"
    names = {int(n): name for n, name in re.findall(r"^\s*(\d+) \[(\S+)\s*\]", card_text, re.M)}
    for line in pcm_lines:  # "01-00: Google voiceHAT ... : playback 1 : capture 1"
        if "playback" in line:
            card, dev = (int(x) for x in line.split(":")[0].split("-"))
            name = names.get(card)
            if name and "hdmi" not in name.lower():
                return f"dmix:CARD={name},DEV={dev}"
    return None


def to_pcm(sound: list[float]) -> bytes:
    """16-bit samples, at full volume less LOUDEST's headroom."""
    gain = 32767 * LOUDEST
    return array("h", [int(s * gain) for s in sound]).tobytes()


def stereo(pcm: bytes) -> bytes:
    """Mono 16-bit samples as stereo: each one twice, left and right."""
    mono = array("h", pcm)
    both = array("h", bytes(len(pcm) * 2))
    both[0::2] = mono
    both[1::2] = mono
    return both.tobytes()


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
    mixer.set_num_channels(CHANNELS)
    return mixer


def made_sounds(cache: Path | None) -> dict[str, bytes]:
    """Every sound in SOUNDS as 16-bit samples, from `cache` if it's from
    this sounds.py, else made (and saved there)."""
    version = hashlib.sha256(Path(sounds.__file__).read_bytes()).hexdigest()
    if cache:
        try:
            saved = pickle.loads(cache.read_bytes())
            if saved["version"] == version and set(saved["sounds"]) == set(SOUNDS):
                return saved["sounds"]
        except (OSError, ValueError, KeyError, TypeError, pickle.UnpicklingError, EOFError):
            pass
    made = {name: to_pcm(make()) for name, make in SOUNDS.items()}
    if cache:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".tmp")
            tmp.write_bytes(pickle.dumps({"version": version, "sounds": made}))
            tmp.replace(cache)
        except OSError as e:
            log.warning("speaker: couldn't save the sounds: %s", e)
    return made


class Speaker:
    def __init__(self, device: str = "auto", opener=open_mixer, cache: Path | None = None):
        self.device = find_device() if device == "auto" else device
        self.cache = cache  # where the made sounds are kept
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
            mixer = await asyncio.to_thread(self._open, self.device)
            self._sounds = await asyncio.to_thread(self._make, mixer, self.cache)
        except Exception as e:  # pygame missing, or the sound card won't open
            log.warning("speaker: %s", e)
            return
        self.mixer = mixer
        log.info("speaker: ready on %s", self.device)

    @staticmethod
    def _make(mixer, cache: Path | None) -> dict:
        channels = mixer.get_init()[2]  # dmix opens in stereo, whatever's asked
        return {
            name: mixer.Sound(buffer=stereo(pcm) if channels == 2 else pcm) for name, pcm in made_sounds(cache).items()
        }

    def play(self, name: str, alone: bool = False) -> bool:
        """Play one of SOUNDS, over whatever else is playing; the same sound
        starts over if it's still playing (rapid fire). `alone` cuts off
        every other sound first. Returns False if it can't play (no speaker,
        sound off, not ready yet, or no such sound)."""
        sound = self._sounds.get(name)
        if not (self.mixer and self.on and sound):
            return False
        if alone:
            self.mixer.stop()
        else:
            sound.stop()
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
