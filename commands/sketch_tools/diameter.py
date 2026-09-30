"""Pulley Diameter: dimension a sketch circle as a timing pulley's pitch,
outside or root diameter, driven by a tooth-count user parameter.

Click a circle, pick the profile, tooth count and which diameter. The tooth
count becomes a user parameter named for the profile and count (HTD5_24T; a
second 24T HTD5 pulley gets HTD5_24T_2), and the circle's diameter dimension
is an expression on it, e.g.

    pitch    HTD5_24T * 5 mm / PI
    outside  HTD5_24T * 5 mm / PI - 2 * 0.5715 mm      (2 * PLD)
    root     outside - 2 * 2.08 mm                       (2 * tooth depth)

To edit one, double-click its dimension (or right-click it or the circle,
Edit Pulley Diameter), or run the tool on the circle again. The parameter is
renamed to match (Fusion updates every expression that uses it).
"""

import math
import os

import adsk.core
import adsk.fusion

from .. import panel
from ..pulley import profiles
from . import common
from .common import SketchToolError

CMD_ID = 'FTCTools_PulleyDiameter'
EDIT_CMD_ID = 'FTCTools_PulleyDiameterEdit'
ICONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', 'diameter')
KINDS = [('pitch', 'Pitch'), ('outside', 'Outside'), ('root', 'Root')]
SHORT = {'gt2_2': 'GT2_2', 'gt2_3': 'GT2_3', 'htd_3': 'HTD3', 'htd_5': 'HTD5'}  # parameter-name safe
DEFAULTS = {'profile': 'htd_5', 'teeth': 24, 'kind': 'pitch'}

_handlers = []
_ui_handlers = []   # (UI event, handler): these outlive commands and must come off in stop
_edit_event = []
_editing = {}


def start():
    cmd_def = common.ui.commandDefinitions.addButtonDefinition(
        CMD_ID, 'Pulley Diameter', 'Dimension a circle as a timing pulley\'s pitch, outside or root diameter.', ICONS)
    common.on(_handlers, cmd_def.commandCreated, adsk.core.CommandCreatedEventHandler, _created, 'Pulley Diameter')
    panel.get(sketch=True).controls.addCommand(cmd_def)
    edit_def = common.ui.commandDefinitions.addButtonDefinition(
        EDIT_CMD_ID, 'Edit Pulley Diameter', 'Reopen the Pulley Diameter dialog for this circle.', ICONS)
    common.on(_handlers, edit_def.commandCreated, adsk.core.CommandCreatedEventHandler, _edit_created, 'Pulley Diameter')
    _edit_event.append(common.install_editing(_ui_handlers, _handlers, 'Pulley Diameter', EDIT_CMD_ID, _match))


def stop():
    control = panel.get(sketch=True).controls.itemById(CMD_ID)
    if control:
        control.deleteMe()
    panel.remove_if_empty(sketch=True)
    for cmd_id in (CMD_ID, EDIT_CMD_ID):
        cmd_def = common.ui.commandDefinitions.itemById(cmd_id)
        if cmd_def:
            cmd_def.deleteMe()
    if _edit_event:
        common.remove_editing(_ui_handlers, _edit_event.pop())
    _handlers.clear()


def _match(entity):
    """The tagged circle behind a diameter/radius dimension or the circle itself."""
    if entity.objectType in (adsk.fusion.SketchDiameterDimension.classType(),
                             adsk.fusion.SketchRadialDimension.classType()):
        entity = entity.entity
    return entity if common.pulley_tag(entity) else None


def _edit_created(args):
    _editing['circle'] = common.editing_target(EDIT_CMD_ID, _match)
    _created(args)
    common.on(_handlers, args.command.activate, adsk.core.CommandEventHandler, _edit_activate, 'Pulley Diameter')


def _edit_activate(args):
    # Selections can only be added once the dialog is up.
    circle = _editing.pop('circle', None)
    if circle is None:
        return
    inputs = args.command.commandInputs
    inputs.itemById('circle').addSelection(circle)
    _load_tag(inputs, circle)


def expression(key, teeth_param, kind):
    spec = profiles.profile(key)
    expr = '%s * %s / PI' % (teeth_param, common.mm(spec['pitch']))
    if kind in ('outside', 'root'):
        expr += ' - 2 * %s' % common.mm(spec['pld'])
    if kind == 'root':
        expr += ' - 2 * %s' % common.mm(spec['depth'])
    return expr


def diameter(key, teeth, kind):
    spec = profiles.profile(key)
    d = teeth * spec['pitch'] / math.pi
    if kind in ('outside', 'root'):
        d -= 2 * spec['pld']
    if kind == 'root':
        d -= 2 * spec['depth']
    return d


# -------------------------------------------------------------------- dialog

def _created(args):
    cmd = args.command
    inputs = cmd.commandInputs
    sel = inputs.addSelectionInput('circle', 'Circle', 'Sketch circle to dimension')
    sel.addSelectionFilter('SketchCircles')
    sel.setSelectionLimits(1, 1)
    common.add_profile_dropdown(inputs, DEFAULTS['profile'])
    inputs.addIntegerSpinnerCommandInput('teeth', 'Teeth', 6, 400, 1, DEFAULTS['teeth'])
    dd = inputs.addDropDownCommandInput('kind', 'Diameter', adsk.core.DropDownStyles.TextListDropDownStyle)
    for k, label in KINDS:
        dd.listItems.add(label, k == DEFAULTS['kind'])
    inputs.addTextBoxCommandInput('result', 'Result', '', 1, True)
    _show_result(inputs)

    common.on(_handlers, cmd.select, adsk.core.SelectionEventHandler, _on_select, 'Pulley Diameter')
    common.on(_handlers, cmd.inputChanged, adsk.core.InputChangedEventHandler,
              lambda a: _show_result(a.input.parentCommand.commandInputs), 'Pulley Diameter')
    common.on(_handlers, cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _validate, 'Pulley Diameter')
    common.on(_handlers, cmd.execute, adsk.core.CommandEventHandler, _execute, 'Pulley Diameter')


def _read(inputs):
    sel = inputs.itemById('circle')
    return {'circle': sel.selection(0).entity if sel.selectionCount else None,
            'profile': common.profile_key(inputs.itemById('profile').selectedItem.name),
            'teeth': inputs.itemById('teeth').value,
            'kind': next(k for k, l in KINDS if l == inputs.itemById('kind').selectedItem.name)}


def _show_result(inputs):
    v = _read(inputs)
    um = common.design().unitsManager
    d = diameter(v['profile'], v['teeth'], v['kind'])
    inputs.itemById('result').text = um.formatInternalValue(d, um.defaultLengthUnits, True)


def _on_select(args):
    _load_tag(args.activeInput.parentCommand.commandInputs, args.selection.entity)


def _load_tag(inputs, circle):
    # A circle this tool already dimensioned: load what it was made with.
    tag = common.pulley_tag(circle)
    if tag is None:
        return
    common.select_item(inputs.itemById('profile'), common.profile_label(tag['profile']))
    common.select_item(inputs.itemById('kind'), dict(KINDS)[tag['kind']])
    teeth = common.design().userParameters.itemByName(tag['teeth'])
    inputs.itemById('teeth').value = int(round(teeth.value))
    _show_result(inputs)


def _validate(args):
    v = _read(args.inputs)
    args.areInputsValid = v['circle'] is not None


def _execute(args):
    v = _read(args.command.commandInputs)
    try:
        apply(v['circle'], v['profile'], v['teeth'], v['kind'])
    except SketchToolError as e:
        common.ui.messageBox(str(e), 'Pulley Diameter')


def param_base(key, teeth):
    return '%s_%dT' % (SHORT[key], int(teeth))


def apply(circle, key, teeth, kind):
    tag = common.pulley_tag(circle)
    params = common.design().userParameters
    current = params.itemByName(tag['teeth']) if tag is not None else None
    teeth_param = common.free_name(param_base(key, teeth), current)
    if current is None:
        common.set_param(teeth_param, str(int(teeth)), '', 'Pulley tooth count (FTC Tools)')
    else:
        if current.name != teeth_param:
            current.name = teeth_param  # Fusion updates the expressions using it
        current.expression = str(int(teeth))
    expr = expression(key, teeth_param, kind)
    circle = common.native(circle)
    dim = _existing_dimension(circle)
    try:
        if dim is None:
            c = circle.centerSketchPoint.geometry
            r = circle.radius
            text = adsk.core.Point3D.create(c.x + r * 0.9, c.y + r * 0.9, 0)
            dim = circle.parentSketch.sketchDimensions.addDiameterDimension(circle, text)
            dim.parameter.expression = expr
        elif dim.objectType == adsk.fusion.SketchRadialDimension.classType():
            dim.parameter.expression = '(%s) / 2' % expr
        else:
            dim.parameter.expression = expr
    except RuntimeError as e:
        raise SketchToolError('Could not dimension the circle (is it already fully constrained?):\n%s' % e)
    common.set_pulley_tag(circle, {'profile': key, 'teeth': teeth_param, 'kind': kind})
    return dim


def _existing_dimension(circle):
    """The circle's driving diameter or radius dimension, if it has one."""
    for dim in circle.parentSketch.sketchDimensions:
        if dim.objectType in (adsk.fusion.SketchDiameterDimension.classType(),
                              adsk.fusion.SketchRadialDimension.classType()):
            if dim.entity == circle and dim.isDriving:
                return dim
    return None
