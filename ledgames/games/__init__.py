from .base import Game
from .color_shooter import ColorShooter
from .fast_tap import FastTap

# Register new games here.
GAMES: dict[str, type[Game]] = {g.info.id: g for g in [ColorShooter, FastTap]}
