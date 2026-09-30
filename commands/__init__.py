from .lighten import entry as lighten
from .pulley import entry as pulley
from .belt import entry as belt

# Every tool module exposes start() and stop(). Add new tools here.
COMMANDS = [lighten, pulley, belt]
