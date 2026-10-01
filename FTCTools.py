import traceback

import adsk.core

from .commands import COMMANDS


def run(context):
    try:
        for command in COMMANDS:
            command.start()
    except Exception:
        adsk.core.Application.get().userInterface.messageBox('FTCTools failed to start:\n' + traceback.format_exc())


def stop(context):
    # Stop every command even if one fails, so none stays registered and
    # breaks the next start.
    errors = []
    for command in reversed(COMMANDS):
        try:
            command.stop()
        except Exception:
            errors.append(traceback.format_exc())
    if errors:
        adsk.core.Application.get().userInterface.messageBox('FTCTools failed to stop:\n' + '\n'.join(errors))
