from .lighten import entry as lighten
from .pulley import entry as pulley

# Every tool module exposes start() and stop(). Add new tools here.
COMMANDS = [lighten, pulley]
