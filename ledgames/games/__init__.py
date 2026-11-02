from .base import Game
from .color_shooter import ColorShooter

# Register new games here.
GAMES: dict[str, type[Game]] = {g.info.id: g for g in [ColorShooter]}
