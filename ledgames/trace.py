"""Optional performance trace, for finding out why things feel slow.

Set LEDGAMES_TRACE=<file> and the server appends one JSON line per event,
with `t` on the server's clock (time.monotonic, like the game clock):

  frame  one game loop pass: `gap` since the previous one started, `work`
         spent updating and rendering, `show` sending it to the strip (ms)
  msg    a WebSocket message arrived: `type`, `client`; for inputs, `at` is
         when the phone says it happened (server clock, so t - at ≈ how long
         the network took) and `rtt` the phone's latest ping round trip
  send   a session update went out to `clients` phones: `ms` to build it

Off (and free) unless the variable is set.
"""

import json
import os
import time

_path = os.environ.get("LEDGAMES_TRACE")
_file = open(_path, "a", buffering=1 << 16) if _path else None
_flushed = 0.0

enabled = _file is not None


def event(kind: str, **fields) -> None:
    global _flushed
    if _file is None:
        return
    now = time.monotonic()
    _file.write(json.dumps({"t": round(now, 4), "e": kind, **fields}) + "\n")
    if now - _flushed >= 1:  # don't lose more than a second if the service is stopped
        _file.flush()
        _flushed = now
