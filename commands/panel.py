"""The shared "FTC Tools" panels in the Design workspace: one on the Solid tab,
and one on the Sketch tab (shown while a sketch is being edited)."""

import adsk.core

WORKSPACE_ID = 'FusionSolidEnvironment'
TAB_ID = 'SolidTab'
PANEL_ID = 'FTCToolsPanel'
SKETCH_TAB_ID = 'SketchTab'
SKETCH_PANEL_ID = 'FTCToolsSketchPanel'
PANEL_NAME = 'FTC TOOLS'


def _ids(sketch):
    return (SKETCH_TAB_ID, SKETCH_PANEL_ID) if sketch else (TAB_ID, PANEL_ID)


def get(sketch=False):
    tab_id, panel_id = _ids(sketch)
    ui = adsk.core.Application.get().userInterface
    tab = ui.workspaces.itemById(WORKSPACE_ID).toolbarTabs.itemById(tab_id)
    panel = tab.toolbarPanels.itemById(panel_id)
    if panel is None:
        panel = tab.toolbarPanels.add(panel_id, PANEL_NAME)
    return panel


def remove_if_empty(sketch=False):
    tab_id, panel_id = _ids(sketch)
    ui = adsk.core.Application.get().userInterface
    tab = ui.workspaces.itemById(WORKSPACE_ID).toolbarTabs.itemById(tab_id)
    panel = tab.toolbarPanels.itemById(panel_id)
    if panel is not None and panel.controls.count == 0:
        panel.deleteMe()
