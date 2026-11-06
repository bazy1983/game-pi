from .base import Game
from .color_shooter import ColorShooter
from .fast_tap import FastTap
from .ping_pong import PingPong
from .simon import Simon
from .sumo import Sumo

# Register new games here.
GAMES: dict[str, type[Game]] = {g.info.id: g for g in [ColorShooter, FastTap, Sumo, Simon, PingPong]}
