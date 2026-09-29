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
    try:
        for command in reversed(COMMANDS):
            command.stop()
    except Exception:
        adsk.core.Application.get().userInterface.messageBox('FTCTools failed to stop:\n' + traceback.format_exc())
