"""The shared "FTC Tools" panel on the Solid tab of the Design workspace."""

import adsk.core

WORKSPACE_ID = 'FusionSolidEnvironment'
TAB_ID = 'SolidTab'
PANEL_ID = 'FTCToolsPanel'
PANEL_NAME = 'FTC TOOLS'


def get():
    ui = adsk.core.Application.get().userInterface
    tab = ui.workspaces.itemById(WORKSPACE_ID).toolbarTabs.itemById(TAB_ID)
    panel = tab.toolbarPanels.itemById(PANEL_ID)
    if panel is None:
        panel = tab.toolbarPanels.add(PANEL_ID, PANEL_NAME)
    return panel


def remove_if_empty():
    ui = adsk.core.Application.get().userInterface
    tab = ui.workspaces.itemById(WORKSPACE_ID).toolbarTabs.itemById(TAB_ID)
    panel = tab.toolbarPanels.itemById(PANEL_ID)
    if panel is not None and panel.controls.count == 0:
        panel.deleteMe()
