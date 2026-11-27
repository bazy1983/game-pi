"""The microphone (an INMP441 on I2S, see the README): how loud it is right
now, for the sound-reactive lights.

`arecord` runs only while a sound effect is showing. Nothing is recorded or
kept: each 20 ms of sound becomes one loudness number, then it's gone.

The level adapts to the room (see Loudness), so a quiet room and a loud
party both use the whole strip.

The device page can watch what the mic hears (`watchers`, `reading()`): it
listens then too, so you can see the room's noise and the sensitivity at work.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence
from functools import lru_cache
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# The speaker keeps the sound card at 48 kHz, and the mic shares its clock
# (see speaker.py). Loudness only needs every third sample (16 kHz), which
# keeps the Pi's work the same as recording at 16 kHz.
RATE = 48_000
CHUNK = RATE // 50  # frames per reading: 20 ms
STEP = 3
LISTEN_RATE = RATE // STEP
FRAME = 8  # bytes per frame: 2 channels of 32 bits (the INMP441 is on the left)
SETTLE = 0.5  # s: the mic's first moments after it starts are noise
# What counts as sound: the mic also picks up a strong slow wobble, far below
# hearing (tens of dB over a quiet room's hiss), so only this band is measured.
LOW, HIGH = 125, 8000  # Hz
BANDS = 12  # for the device page's picture of the sound, LOW to HIGH
RETRY = 5.0  # s between tries when arecord fails


def find_device(pcm: Path = Path("/proc/asound/pcm")) -> str | None:
    """The first sound card that can record, as an ALSA device name."""
    try:
        lines = pcm.read_text().splitlines()
    except OSError:
        return None
    for line in lines:  # "01-00: Google voiceHAT ... : capture 1"
        if "capture" in line:
            card, dev = line.split(":")[0].split("-")
            return f"plughw:{int(card)},{int(dev)}"
    return None


def sensitivity_range(sensitivity: float) -> float:
    """How many dB over the room's quiet fill the strip: 32 at the least
    sensitive (0), 20 in the middle, 8 at the most sensitive (1)."""
    return 32 - 24 * sensitivity


@lru_cache
def _analysis(n: int):
    """For a window of n samples: its shape, the scale that turns the
    spectrum into power (full scale = 1), and which bins make each band."""
    window = np.blackman(n)  # its leakage is low enough to keep the wobble out
    scale = 2 / (n * np.sum(window**2))
    freqs = np.fft.rfftfreq(n, 1 / LISTEN_RATE)
    edges = np.geomspace(LOW, HIGH, BANDS + 1)
    bins = np.searchsorted(freqs, edges)
    return window, scale, bins


def _db(power) -> float:
    return 10 * np.log10(power + 1e-12)


class Loudness:
    """Turns sound into a 0–1 level that adapts to the room.

    Each reading is the sound's power from LOW to HIGH, over the last two
    chunks (40 ms). `floor` follows the quietest moments (it drops at once
    and creeps back up), `peak` the loudest (it jumps at once and slowly
    sinks). The lights start QUIET dB over the floor, so the room's own hiss
    stays dark, and are full at the peak, which is kept at least `min_range`
    dB over the floor."""

    FLOOR_RISE = 3.0  # dB/s
    PEAK_FALL = 4.0  # dB/s
    QUIET = 4.0  # dB over the floor that's still just the room
    FALL = 2.5  # how fast the level can drop, full scale per second

    def __init__(self):
        self.floor = -60.0
        self.min_range = 20.0  # dB; see sensitivity_range
        self.peak = self.floor + self.min_range
        self.level = 0.0
        self.db = -120.0  # the last reading
        self.bands = [-120.0] * BANDS  # and its power in each band, dB
        self._last = None  # the chunk before, for the window

    @property
    def quiet(self) -> float:
        """Where the lights start, dB."""
        return self.floor + self.QUIET

    def feed(self, samples: Sequence[int], dt: float) -> float:
        """One chunk of 32-bit samples at LISTEN_RATE."""
        chunk = np.asarray(samples, dtype=np.float64) / 2**31
        both = chunk if self._last is None else np.concatenate((self._last, chunk))
        self._last = chunk
        window, scale, bins = _analysis(len(both))
        spectrum = np.abs(np.fft.rfft((both - both.mean()) * window)) ** 2 * scale
        bands = np.add.reduceat(spectrum, bins)[:BANDS]  # (the mean takes out the mic's DC offset)
        db = self.db = float(_db(bands.sum()))
        self.bands = [round(float(b), 1) for b in _db(bands)]
        self.floor = db if db < self.floor else self.floor + self.FLOOR_RISE * dt
        self.peak = max(db, self.peak - self.PEAK_FALL * dt, self.floor + self.min_range)
        target = min(1.0, max(0.0, (db - self.quiet) / (self.peak - self.quiet)))
        self.level = max(target, self.level - self.FALL * dt)  # jumps up, falls smoothly
        return self.level


class Microphone:
    def __init__(self, device: str = "auto"):
        self.device = find_device() if device == "auto" else device
        self.level = 0.0  # 0–1, while listening
        self.sensitivity = 0.5  # 0–1, set on the device page
        self.watchers = 0  # device pages watching what it hears: it listens for them too
        self._loudness: Loudness | None = None  # while listening (and settled)

    @property
    def available(self) -> bool:
        return self.device is not None

    def reading(self) -> dict:
        """What it hears now, for the device page: the sound (dB below full
        scale, overall and in BANDS bands from LOW to HIGH), where the lights
        start (`quiet`) and are full (`full`), and the level they show."""
        loud = self._loudness
        if loud is None:
            return {"listening": False}
        return {
            "listening": True,
            "db": round(loud.db, 1),
            "quiet": round(loud.quiet, 1),
            "full": round(loud.peak, 1),
            "level": round(loud.level, 3),
            "bands": loud.bands,
        }

    async def run(self, wanted: Callable[[], bool]) -> None:
        """Listen whenever `wanted()` says a sound effect is showing, or a
        device page is watching."""
        listening = lambda: wanted() or self.watchers > 0  # noqa: E731
        while True:
            if self.device and listening():
                await self._listen(listening)
            self.level = 0.0
            self._loudness = None
            await asyncio.sleep(0.5)

    async def _listen(self, wanted: Callable[[], bool]) -> None:
        cmd = ["arecord", "-q", "-D", self.device, "-f", "S32_LE", "-r", str(RATE), "-c", "2", "-t", "raw"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
        except OSError as e:
            log.warning("microphone: %s", e)
            await asyncio.sleep(RETRY)
            return
        loudness = Loudness()
        dt = CHUNK / RATE
        settle = round(SETTLE / dt)
        try:
            while wanted():
                data = await proc.stdout.readexactly(CHUNK * FRAME)
                if settle:  # (its noise would throw off the floor and peak)
                    settle -= 1
                    continue
                samples = np.frombuffer(data, dtype="<i4")[0 :: 2 * STEP]  # left channel, every STEP-th
                loudness.min_range = sensitivity_range(self.sensitivity)
                self.level = loudness.feed(samples, dt)
                self._loudness = loudness
        except asyncio.IncompleteReadError:
            log.warning("microphone: arecord stopped (exit %s)", await proc.wait())
            await asyncio.sleep(RETRY)
        finally:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
