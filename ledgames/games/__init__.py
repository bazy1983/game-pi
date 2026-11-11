from .base import Game
from .color_shooter import ColorShooter
from .fast_tap import FastTap
from .hot_potato import HotPotato
from .morse import Morse
from .ping_pong import PingPong
from .red_light import RedLight
from .simon import Simon
from .sumo import Sumo

# Register new games here.
GAMES: dict[str, type[Game]] = {g.info.id: g for g in [ColorShooter, FastTap, Sumo, Simon, PingPong, Morse, RedLight, HotPotato]}
