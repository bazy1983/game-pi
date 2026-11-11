"""The microphone (an INMP441 on I2S, see the README): how loud it is right
now, for the sound-reactive lights.

`arecord` runs only while a sound effect is showing. Nothing is recorded or
kept: each 20 ms of sound becomes one loudness number, then it's gone.

The level adapts to the room (see Loudness), so a quiet room and a loud
party both use the whole strip.
"""

import asyncio
import contextlib
import logging
import math
from array import array
from collections.abc import Callable, Sequence
from pathlib import Path

log = logging.getLogger(__name__)

RATE = 16_000
CHUNK = RATE // 50  # frames per reading: 20 ms
FRAME = 8  # bytes per frame: 2 channels of 32 bits (the INMP441 is on the left)
SETTLE = 0.3  # s: the mic's first moments after it starts are noise
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
    """How many dB above the quiet moments fill the strip: 32 at the least
    sensitive (0), 20 in the middle, 8 at the most sensitive (1)."""
    return 32 - 24 * sensitivity


class Loudness:
    """Turns sound into a 0–1 level that adapts to the room.

    `floor` follows the quietest moments (it drops at once and creeps back
    up), `peak` the loudest (it jumps at once and slowly sinks), and the level
    is where the sound is between them. They're kept at least `min_range` dB
    apart so background hiss doesn't fill the strip."""

    FLOOR_RISE = 3.0  # dB/s
    PEAK_FALL = 4.0  # dB/s
    FALL = 2.5  # how fast the level can drop, full scale per second

    def __init__(self):
        self.floor = -60.0
        self.min_range = 20.0  # dB; see sensitivity_range
        self.peak = self.floor + self.min_range
        self.level = 0.0

    def feed(self, samples: Sequence[int], dt: float) -> float:
        mean = sum(samples) / len(samples)  # the mic has a DC offset
        power = sum((s - mean) ** 2 for s in samples) / len(samples)
        db = 10 * math.log10(power / 2**62 + 1e-12)  # dB below a full-scale 32-bit signal
        self.floor = db if db < self.floor else self.floor + self.FLOOR_RISE * dt
        self.peak = max(db, self.peak - self.PEAK_FALL * dt, self.floor + self.min_range)
        target = min(1.0, max(0.0, (db - self.floor) / (self.peak - self.floor)))
        self.level = max(target, self.level - self.FALL * dt)  # jumps up, falls smoothly
        return self.level


class Microphone:
    def __init__(self, device: str = "auto"):
        self.device = find_device() if device == "auto" else device
        self.level = 0.0  # 0–1, while listening
        self.sensitivity = 0.5  # 0–1, set on the device page

    @property
    def available(self) -> bool:
        return self.device is not None

    async def run(self, wanted: Callable[[], bool]) -> None:
        """Listen whenever `wanted()` says a sound effect is showing."""
        while True:
            if self.device and wanted():
                await self._listen(wanted)
            self.level = 0.0
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
                samples = array("i")
                samples.frombytes(await proc.stdout.readexactly(CHUNK * FRAME))
                loudness.min_range = sensitivity_range(self.sensitivity)
                level = loudness.feed(samples[0::2], dt)
                if settle:
                    settle -= 1
                else:
                    self.level = level
        except asyncio.IncompleteReadError:
            log.warning("microphone: arecord stopped (exit %s)", await proc.wait())
            await asyncio.sleep(RETRY)
        finally:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
