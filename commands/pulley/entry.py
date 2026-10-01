"""Pulley: parametric timing pulley (GT2 2mm, GT2 3mm, HTD 3mm, HTD 5mm).

Each pulley is its own component holding a Fusion custom feature that groups
one base feature: the pulley solid (teeth, optional flanges, bore, recesses).
Every size is a custom parameter, so it shows up in Change Parameters and
accepts expressions. The center point (and optional plane) are dependencies,
so moving the point moves the pulley.
"""

import json
import math
import os
import traceback

import adsk.core
import adsk.fusion

from .. import panel
from . import body, profiles
from .profiles import PulleyError

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = 'FTCTools_Pulley'
EDIT_CMD_ID = 'FTCTools_PulleyEdit'
FEATURE_ID = 'FTCToolsPulley'
ICONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources')
SETTINGS_PATH = os.path.join(os.getenv('APPDATA') or os.path.expanduser('~'), 'FTCTools', 'pulley.json')
SHORT_NAMES = {'gt2_2': 'GT2-2', 'gt2_3': 'GT2-3', 'htd_3': 'HTD3', 'htd_5': 'HTD5'}
OVERLAY_COLOR = (255, 210, 0)
SKETCH_CENTERS = (adsk.fusion.SketchPoint.classType(), adsk.fusion.SketchCircle.classType(),
                  adsk.fusion.SketchArc.classType())

# Sized parameters: (id, parameter name, dialog label, units kind, default).
SIZES = [
    ('width', 'Width', 'Width', 'length', '10 mm'),
    ('clearance', 'Clearance', 'Clearance', 'length', '0.05 mm'),
    ('flange_t', 'FlangeThickness', 'Flange thickness', 'length', '1 mm'),
    ('flange_h', 'FlangeHeight', 'Flange height', 'length', '1.5 mm'),
    ('flange_angle', 'FlangeAngle', 'Flange angle', 'angle', '30 deg'),
    ('bore_d', 'BoreDiameter', 'Bore diameter', 'length', '8 mm'),
    ('hex_af', 'HexWidth', 'Hex width', 'length', '7.15 mm'),
    ('bolt_circle', 'BoltCircle', 'Bolt circle', 'length', '16 mm'),
    ('hole_d', 'HoleDiameter', 'Hole diameter', 'length', '4.3 mm'),
    ('cb_d', 'CounterboreDiameter', 'Counterbore diameter', 'length', '7.5 mm'),
    ('cb_depth', 'CounterboreDepth', 'Counterbore depth', 'length', '4 mm'),
    ('layer_h', 'BridgeLayerHeight', 'Layer height', 'length', '0.2 mm'),
    ('bearing_od', 'BearingOD', 'Bearing OD', 'length', '14 mm'),
    ('bearing_depth', 'BearingDepth', 'Bearing depth', 'length', '4 mm'),
    ('hub_d', 'HubRecessDiameter', 'Hub recess diameter', 'length', '22 mm'),
    ('hub_depth', 'HubRecessDepth', 'Hub recess depth', 'length', '2 mm'),
]
# Counts: (id, parameter name, dialog label, min, max, default).
COUNTS = [('teeth', 'Teeth', 'Teeth', 6, 400, 24), ('hole_count', 'HoleCount', 'Hole count', 1, 16, 4)]
# Choices kept in hidden unitless parameters: (id, list of (key, label)).
CHOICES = [
    ('profile', [(k, l) for k, l, _ in profiles.PROFILES]),
    ('bore', body.BORES),
    ('pattern', [(k, l) for k, l, _ in body.PATTERNS]),
]
FLAGS = [('flip', 'Flip direction', False), ('flanges', 'Flanges', True),
         ('bearing', 'Bearing recess', False), ('bearing_flip', 'Flip bearing side', False),
         ('counterbore', 'Counterbore holes', False),
         ('bridging', 'Sequential bridging', False), ('hub_recess', 'Hub recess', False),
         ('hub_flip', 'Flip hub side', False)]
DEFAULTS = dict([(s[0], s[4]) for s in SIZES] + [(c[0], c[5]) for c in COUNTS] + [(f[0], f[2]) for f in FLAGS]
                + [('profile', 'htd_5'), ('bore', 'round'), ('pattern', 'gobilda')])

_handlers = []
_feature_def = None
_edit = {}
_overlay = []
_creating = [False]


# ----------------------------------------------------------------- lifecycle

def start():
    global _feature_def
    create_def = ui.commandDefinitions.addButtonDefinition(
        CMD_ID, 'Pulley', 'Timing pulley: GT2 2mm, GT2 3mm, HTD 3mm or HTD 5mm.', ICONS)
    _on(create_def.commandCreated, adsk.core.CommandCreatedEventHandler, _create_created)

    edit_def = ui.commandDefinitions.addButtonDefinition(EDIT_CMD_ID, 'Edit Pulley', 'Edit a Pulley feature.', ICONS)
    _on(edit_def.commandCreated, adsk.core.CommandCreatedEventHandler, _edit_created)

    _feature_def = adsk.fusion.CustomFeatureDefinition.create(FEATURE_ID, 'Pulley', ICONS)
    _feature_def.editCommandId = EDIT_CMD_ID
    _on(_feature_def.customFeatureCompute, adsk.fusion.CustomFeatureEventHandler, _compute)

    control = panel.get().controls.addCommand(create_def)
    control.isPromotedByDefault = True
    control.isPromoted = True


def stop():
    _clear_overlay()
    control = panel.get().controls.itemById(CMD_ID)
    if control:
        control.deleteMe()
    panel.remove_if_empty()
    for cmd_id in (CMD_ID, EDIT_CMD_ID):
        cmd_def = ui.commandDefinitions.itemById(cmd_id)
        if cmd_def:
            cmd_def.deleteMe()
    _handlers.clear()


def _on(event, handler_base, fn):
    """Subscribe fn to a Fusion event. Unhandled errors are shown, never dropped."""
    class Handler(handler_base):
        def notify(self, args):
            try:
                fn(args)
            except Exception:
                ui.messageBox('Pulley failed:\n' + traceback.format_exc())
    handler = Handler()
    event.add(handler)
    _handlers.append(handler)


# ------------------------------------------------------------------ settings

def _load_settings():
    values = dict(DEFAULTS)
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
            values.update(json.load(f))
    return values


def _save_settings(v):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
        json.dump({k: v[k] for k in DEFAULTS}, f, indent=2)


# -------------------------------------------------------------------- dialog

def _design():
    return adsk.fusion.Design.cast(app.activeProduct)


def _units(kind):
    return _design().unitsManager.defaultLengthUnits if kind == 'length' else 'deg'


def _build_inputs(cmd, values):
    inputs = cmd.commandInputs

    sel = inputs.addSelectionInput('center', 'Center', 'Sketch point or circle, or any point with a plane')
    for f in ('SketchPoints', 'SketchCircles', 'Vertices', 'ConstructionPoints'):
        sel.addSelectionFilter(f)
    sel.setSelectionLimits(1, 1)
    sel = inputs.addSelectionInput('plane', 'Plane', 'Plane or face the pulley starts on (optional for sketch points)')
    sel.addSelectionFilter('PlanarFaces')
    sel.addSelectionFilter('ConstructionPlanes')
    sel.setSelectionLimits(0, 1)

    def dropdown(parent, input_id, label):
        dd = parent.addDropDownCommandInput(input_id, label, adsk.core.DropDownStyles.TextListDropDownStyle)
        for key, text in dict(CHOICES)[input_id]:
            dd.listItems.add(text, key == values[input_id])

    def size(parent, input_id):
        _, _, label, kind, _ = next(s for s in SIZES if s[0] == input_id)
        parent.addValueInput(input_id, label, _units(kind), adsk.core.ValueInput.createByString(values[input_id]))

    def flag(parent, input_id):
        label = next(f[1] for f in FLAGS if f[0] == input_id)
        parent.addBoolValueInput(input_id, label, True, '', bool(values[input_id]))

    def count(parent, input_id):
        _, _, label, lo, hi, _ = next(c for c in COUNTS if c[0] == input_id)
        parent.addIntegerSpinnerCommandInput(input_id, label, lo, hi, 1, int(values[input_id]))

    dropdown(inputs, 'profile', 'Profile')
    count(inputs, 'teeth')
    size(inputs, 'width')
    size(inputs, 'clearance')
    inputs.itemById('clearance').tooltip = 'Groove grows by this on every side, for print fit.'
    flag(inputs, 'flip')

    g = inputs.addGroupCommandInput('flange_group', 'Flanges').children
    flag(g, 'flanges')
    for i in ('flange_t', 'flange_h', 'flange_angle'):
        size(g, i)

    g = inputs.addGroupCommandInput('bore_group', 'Bore').children
    dropdown(g, 'bore', 'Bore')
    size(g, 'bore_d')
    size(g, 'hex_af')
    dropdown(g, 'pattern', 'Bolt pattern')
    size(g, 'bolt_circle')
    count(g, 'hole_count')
    size(g, 'hole_d')
    flag(g, 'counterbore')
    size(g, 'cb_d')
    size(g, 'cb_depth')
    flag(g, 'bridging')
    size(g, 'layer_h')
    flag(g, 'bearing')
    size(g, 'bearing_od')
    size(g, 'bearing_depth')
    flag(g, 'bearing_flip')
    flag(g, 'hub_recess')
    size(g, 'hub_d')
    size(g, 'hub_depth')
    flag(g, 'hub_flip')

    _update_visibility(inputs)


def _choice(inputs, input_id):
    label = inputs.itemById(input_id).selectedItem.name
    return next(k for k, l in dict(CHOICES)[input_id] if l == label)


def _relevant(v):
    """Which inputs matter for these choices. Drives both dialog and parameter visibility."""
    bore = v['bore']
    return {
        'flange_t': v['flanges'], 'flange_h': v['flanges'], 'flange_angle': v['flanges'],
        'bore_d': bore in ('round', 'hub'), 'hex_af': bore == 'hex',
        'pattern': bore == 'hub',
        'bolt_circle': bore == 'hub' and v['pattern'] == 'custom',
        'hole_count': bore == 'hub' and v['pattern'] == 'custom',
        'hole_d': bore == 'hub' and v['pattern'] == 'custom',
        'bearing': bore in ('round', 'hub'),
        'bearing_od': bore in ('round', 'hub') and v['bearing'],
        'bearing_depth': bore in ('round', 'hub') and v['bearing'],
        'bearing_flip': bore in ('round', 'hub') and v['bearing'],
        'hub_recess': bore != 'none',
        'hub_d': bore != 'none' and v['hub_recess'],
        'hub_depth': bore != 'none' and v['hub_recess'],
        'counterbore': bore == 'hub',
        'cb_d': bore == 'hub' and v['counterbore'],
        'cb_depth': bore == 'hub' and v['counterbore'],
        'bridging': bore == 'hub' and v['counterbore'],
        'layer_h': bore == 'hub' and v['counterbore'] and v['bridging'],
        # Which end the hub sits on: moves the hub recess, and the
        # counterbores (screw heads) go on the other end.
        'hub_flip': (bore != 'none' and v['hub_recess']) or (bore == 'hub' and v['counterbore']),
    }


def _update_visibility(inputs):
    v = {'bore': _choice(inputs, 'bore'), 'pattern': _choice(inputs, 'pattern'),
         'flanges': inputs.itemById('flanges').value, 'bearing': inputs.itemById('bearing').value,
         'hub_recess': inputs.itemById('hub_recess').value, 'counterbore': inputs.itemById('counterbore').value,
         'bridging': inputs.itemById('bridging').value}
    for input_id, shown in _relevant(v).items():
        inputs.itemById(input_id).isVisible = shown


def _selection(inputs, input_id):
    sel = inputs.itemById(input_id)
    return sel.selection(0).entity if sel.selectionCount else None


def _read_inputs(inputs):
    v = {'center': _selection(inputs, 'center'), 'plane': _selection(inputs, 'plane')}
    for input_id, _ in CHOICES:
        v[input_id] = _choice(inputs, input_id)
    for s in SIZES:
        v[s[0]] = inputs.itemById(s[0]).expression
    for c in COUNTS:
        v[c[0]] = inputs.itemById(c[0]).value
    for f in FLAGS:
        v[f[0]] = inputs.itemById(f[0]).value
    return v


def _options(v):
    """Evaluated build options (cm, radians) from dialog values."""
    um = _design().unitsManager
    o = {k: v[k] for k in ('profile', 'bore', 'pattern', 'teeth', 'hole_count', 'flanges', 'bearing', 'bearing_flip', 'counterbore', 'bridging', 'hub_recess', 'hub_flip', 'flip')}
    for input_id, _, _, kind, _ in SIZES:
        value = um.evaluateExpression(v[input_id], _units(kind))
        o[input_id] = value  # angles evaluate to radians
    return o


def _input_changed(args):
    if args.input.id in ('bore', 'pattern', 'flanges', 'bearing', 'hub_recess', 'counterbore', 'bridging'):
        # args.inputs is only the changed input's group; look up from the command.
        _update_visibility(args.input.parentCommand.commandInputs)


def _validate(args):
    inputs = args.inputs
    center = _selection(inputs, 'center')
    ok = center is not None
    if ok and center.objectType not in SKETCH_CENTERS:
        ok = inputs.itemById('plane').selectionCount == 1
    for input_id, _, _, _, _ in SIZES:
        i = inputs.itemById(input_id)
        if not i.isVisible and input_id not in ('width', 'clearance'):
            continue
        minimum_ok = i.value >= 0 if input_id in ('clearance', 'flange_angle') else i.value > 0
        ok = ok and i.isValidExpression and minimum_ok
    args.areInputsValid = ok
    if not ok:
        _clear_overlay()


def _on_select(args):
    # After the center is picked, a plane is only needed for non-sketch points.
    if args.activeInput.id == 'center' and args.selection.entity.objectType not in SKETCH_CENTERS:
        args.activeInput.parentCommand.commandInputs.itemById('plane').hasFocus = True


def _connect_dialog(cmd, preview, execute, destroy):
    _on(cmd.inputChanged, adsk.core.InputChangedEventHandler, _input_changed)
    _on(cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _validate)
    _on(cmd.select, adsk.core.SelectionEventHandler, _on_select)
    _on(cmd.executePreview, adsk.core.CommandEventHandler, preview)
    _on(cmd.execute, adsk.core.CommandEventHandler, execute)
    _on(cmd.destroy, adsk.core.CommandEventHandler, destroy)


def _preview(args):
    _draw_preview(args.command.commandInputs)


def _draw_preview(inputs):
    """Outline the pulley solid's edges. Inputs that can't make a pulley show nothing."""
    _clear_overlay()
    v = _read_inputs(inputs)
    try:
        comp, frame = _placement(v['center'], v['plane'])
        solid = _solid(_options(v), frame)
    except PulleyError:
        return
    points = []
    indices = []
    for edge in solid.edges:
        _, t0, t1 = edge.evaluator.getParameterExtents()
        _, strokes = edge.evaluator.getStrokes(t0, t1, 0.002)
        start = len(points) // 3
        for p in strokes:
            points += [p.x, p.y, p.z]
        for i in range(len(strokes) - 1):
            indices += [start + i, start + i + 1]
    # In the component the pulley goes in: its space, and not ghosted when active.
    group = comp.customGraphicsGroups.add()
    lines = group.addLines(adsk.fusion.CustomGraphicsCoordinates.create(points), indices, False)
    lines.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(*OVERLAY_COLOR, 255))
    lines.weight = 1
    _overlay.append(group)


def _clear_overlay():
    while _overlay:
        group = _overlay.pop()
        if group.isValid:
            group.deleteMe()


# -------------------------------------------------------------------- create

def _create_created(args):
    cmd = args.command
    _build_inputs(cmd, _load_settings())
    _connect_dialog(cmd, _preview, _create_execute, lambda a: _clear_overlay())


def _create_execute(args):
    _clear_overlay()
    v = _read_inputs(args.command.commandInputs)
    try:
        parent, frame = _placement(v['center'], v['plane'])
        solid = _solid(_options(v), frame)
    except PulleyError as e:
        ui.messageBox(str(e), 'Pulley')
        return
    _create_feature(v, parent, solid)
    _save_settings(v)


def _pulley_name(key, teeth):
    return '%s %dT' % (SHORT_NAMES[key], teeth)


def _create_feature(v, parent, solid):
    """New component under the placement's component, holding the pulley feature.

    The new occurrence has an identity transform, so the new component's space
    is the parent's space and the solid needs no further transform."""
    occ = parent.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = _pulley_name(v['profile'], v['teeth'])

    base = comp.features.baseFeatures.add()
    base.startEdit()
    solid_body = comp.bRepBodies.add(solid, base)
    base.finishEdit()
    base.name = 'Pulley Body'
    solid_body.name = comp.name

    relevant = _relevant(v)
    cf_input = comp.features.customFeatures.createInput(_feature_def)
    for input_id, name, _, kind, _ in SIZES:
        cf_input.addCustomParameter(input_id, name, adsk.core.ValueInput.createByString(v[input_id]),
                                    _units(kind), relevant.get(input_id, True))
    for input_id, name, _, _, _, _ in COUNTS:
        cf_input.addCustomParameter(input_id, name, adsk.core.ValueInput.createByReal(v[input_id]), '',
                                    relevant.get(input_id, True))
    # Choices and on/off switches live in hidden parameters so compute can read
    # them even during customFeatures.add, before any other state could be stored.
    for input_id, items in CHOICES:
        index = [k for k, _ in items].index(v[input_id])
        cf_input.addCustomParameter(input_id, input_id, adsk.core.ValueInput.createByReal(index), '', False)
    for input_id, _, _ in FLAGS:
        cf_input.addCustomParameter(input_id, input_id, adsk.core.ValueInput.createByReal(1 if v[input_id] else 0), '', False)
    _add_dependencies(cf_input.addDependency, v)
    cf_input.setStartAndEndFeatures(base, base)
    # Fusion computes the feature once inside add. The base feature already
    # holds exactly this solid, so that compute is skipped.
    _creating[0] = True
    try:
        return comp.features.customFeatures.add(cf_input)
    finally:
        _creating[0] = False


def _add_dependencies(add, v):
    add('center', v['center'])
    if v['plane'] is not None:
        add('plane', v['plane'])


# ---------------------------------------------------------------------- edit

# What a pulley made by an older version has for the parameters it lacks
# (anything not listed falls back to DEFAULTS). Custom parameters can only be
# added when a feature is created.
LEGACY = {'flanges': False, 'bore': 'none', 'bearing': False, 'hub_recess': False}


def _feature_values(feature):
    """Dialog values (expressions, counts, keys, flags) from a feature's parameters."""
    p = feature.parameters
    v = {}
    for input_id, _, _, _, default in SIZES:
        param = p.itemById(input_id)
        v[input_id] = param.expression if param else default
    for input_id, _, _, _, _, default in COUNTS:
        param = p.itemById(input_id)
        v[input_id] = int(round(param.value)) if param else default
    for input_id, items in CHOICES:
        param = p.itemById(input_id)
        v[input_id] = items[int(round(param.value))][0] if param else LEGACY.get(input_id, DEFAULTS[input_id])
    for input_id, _, _ in FLAGS:
        param = p.itemById(input_id)
        v[input_id] = param.value > 0.5 if param else LEGACY.get(input_id, DEFAULTS[input_id])
    return v


def _edit_created(args):
    feature = adsk.fusion.CustomFeature.cast(ui.activeSelections.item(0).entity)
    _edit.clear()
    _edit.update({'feature': feature, 'restore': None, 'rolled': False, 'populated': False})
    timeline = _design().timeline
    if timeline.markerPosition > 0:
        _edit['restore'] = timeline.item(timeline.markerPosition - 1)
    # Roll back before the dialog records changes, so previews (whose changes
    # Fusion undoes) can't undo the roll with them.
    feature.timelineObject.rollTo(True)
    _edit['rolled'] = True

    cmd = args.command
    _build_inputs(cmd, _feature_values(feature))
    _connect_dialog(cmd, _edit_preview, _edit_execute, _edit_destroy)
    _on(cmd.activate, adsk.core.CommandEventHandler, _edit_activate)


def _edit_preview(args):
    if _edit.get('populating'):
        return
    _edit['feature'].timelineObject.rollTo(True)
    _draw_preview(args.command.commandInputs)


def _edit_activate(args):
    if _edit.get('populated'):
        return
    _edit['populated'] = True
    feature = _edit['feature']
    feature.timelineObject.rollTo(True)
    inputs = args.command.commandInputs
    center, plane = _dependencies(feature, skip_lost=True)
    _edit['populating'] = True
    try:
        if center is not None:
            inputs.itemById('center').addSelection(center)
        if plane is not None:
            inputs.itemById('plane').addSelection(plane)
    finally:
        _edit['populating'] = False
    _draw_preview(inputs)


def _edit_execute(args):
    feature = _edit['feature']
    _clear_overlay()
    feature.timelineObject.rollTo(True)
    v = _read_inputs(args.command.commandInputs)
    # Values that can't make a pulley: say why, as create does, and change nothing.
    try:
        _solid(_options(v), _placement(v['center'], v['plane'])[1])
    except PulleyError as e:
        ui.messageBox(str(e), 'Pulley')
        return

    # Rolled back to before this feature: one recompute when it rolls forward.
    feature.dependencies.deleteAll()
    _add_dependencies(feature.dependencies.add, v)
    p = feature.parameters
    relevant = _relevant(v)
    missing = []
    for input_id, _, _, _, _ in SIZES:
        param = p.itemById(input_id)
        if param is None:
            missing.append(input_id)
            continue
        param.expression = v[input_id]
        param.isVisible = relevant.get(input_id, True)
    for input_id, _, _, _, _, _ in COUNTS:
        param = p.itemById(input_id)
        if param is None:
            missing.append(input_id)
            continue
        param.value = v[input_id]
        param.isVisible = relevant.get(input_id, True)
    for input_id, items in CHOICES:
        param = p.itemById(input_id)
        if param is None:
            missing.append(input_id)
            continue
        param.value = [k for k, _ in items].index(v[input_id])
    for input_id, _, _ in FLAGS:
        param = p.itemById(input_id)
        if param is None:
            missing.append(input_id)
            continue
        param.value = 1 if v[input_id] else 0
    if missing:
        ui.messageBox('This pulley was made with an older version of the tool, so these settings were '
                      'not saved: %s. Delete it and create it again to use them.' % ', '.join(missing), 'Pulley')
    feature.parentComponent.name = _pulley_name(v['profile'], v['teeth'])

    _restore_timeline()
    _save_settings(v)


def _edit_destroy(args):
    # Cancel leaves the timeline rolled back; put it where the user had it.
    _clear_overlay()
    _restore_timeline()
    _edit.clear()


def _restore_timeline():
    if not _edit.get('rolled'):
        return
    restore = _edit.get('restore')
    if restore is not None:
        restore.rollTo(False)
    else:
        _design().timeline.moveToEnd()
    _edit['rolled'] = False


# ------------------------------------------------------------------- compute

def _compute(args):
    feature = args.customFeature
    if _creating[0]:
        return
    try:
        base = next(f for f in feature.features if f.objectType == adsk.fusion.BaseFeature.classType())
        center, plane = _dependencies(feature)
        _, frame = _placement(center, plane)
        solid = _solid(_feature_options(feature), frame)
        base.startEdit()
        try:
            updated = base.updateBody(base.bodies.item(0), solid)
        finally:
            base.finishEdit()
        if not updated:
            raise PulleyError('Could not update the pulley body.')
    except PulleyError as e:
        # Custom feature compute errors can't carry custom text, so the reason
        # goes to the Text Commands log and the feature gets Fusion's message.
        app.log('Pulley (%s): %s' % (feature.name, e))
        args.computeStatus.statusMessages.addError('API_COMPUTE_ERROR', '')
    except Exception:
        # A modal dialog here would block Fusion mid-recompute.
        app.log('Pulley (%s) failed:\n%s' % (feature.name, traceback.format_exc()))
        args.computeStatus.statusMessages.addError('API_COMPUTE_ERROR', '')


def _feature_options(feature):
    """Build options (cm, radians) straight from the feature's parameter values."""
    v = _feature_values(feature)
    o = {k: v[k] for k in ('profile', 'bore', 'pattern', 'teeth', 'hole_count', 'flanges', 'bearing', 'bearing_flip', 'counterbore', 'bridging', 'hub_recess', 'hub_flip', 'flip')}
    um = _design().unitsManager
    for input_id, _, _, kind, default in SIZES:
        param = feature.parameters.itemById(input_id)
        # internal units: cm, radians
        o[input_id] = param.value if param else um.evaluateExpression(default, _units(kind))
    return o


def _dependencies(feature, skip_lost=False):
    """Center and plane. A reference to deleted geometry is an error for the
    recompute; edit passes skip_lost, since editing is how it gets fixed."""
    center = plane = None
    for i in range(feature.dependencies.count):
        dep = feature.dependencies.item(i)
        if dep.entity is None:
            if skip_lost:
                continue
            raise PulleyError('Lost the reference "%s". Edit the feature and reselect it.' % dep.id)
        if dep.id == 'center':
            center = dep.entity
        elif dep.id == 'plane':
            plane = dep.entity
    if center is None and not skip_lost:
        raise PulleyError('The pulley has no center.')
    return center, plane


# ------------------------------------------------------------------ geometry

def _native(entity):
    if entity.assemblyContext:
        return entity.nativeObject
    return entity


def _other_copy(a, b):
    """a and b were picked in different copies (occurrences) of the same component."""
    return bool(a.assemblyContext and b.assemblyContext
                and a.assemblyContext.fullPathName != b.assemblyContext.fullPathName)


def _owner(native):
    t = native.objectType
    if t in SKETCH_CENTERS:
        return native.parentSketch.parentComponent
    if t in (adsk.fusion.BRepVertex.classType(), adsk.fusion.BRepFace.classType()):
        return native.body.parentComponent
    return native.component  # construction point or plane


def _placement(center, plane):
    """(component, (origin, x, y, z)) with the frame in that component's space.

    The component is the one that owns the center, and the pulley goes in a
    new component under it. With a sketch center and no plane, the frame is
    the sketch's; otherwise the plane's, with the center projected onto it.
    """
    if center is None:
        raise PulleyError('Pick a center.')
    native = _native(center)
    comp = _owner(native)
    t = native.objectType
    if t == adsk.fusion.SketchPoint.classType():
        origin = native.worldGeometry
    elif t in SKETCH_CENTERS:
        origin = native.centerSketchPoint.worldGeometry
    else:
        origin = native.geometry

    if plane is None:
        if t not in SKETCH_CENTERS:
            raise PulleyError('Pick a plane for a point that is not in a sketch.')
        _, x, y, z = native.parentSketch.transform.getAsCoordinateSystem()
        return comp, (origin, x, y, z)

    geom = _plane_in(plane, center, comp)
    z = geom.normal.copy()
    z.normalize()
    dist = geom.origin.vectorTo(origin).dotProduct(z)
    along = z.copy()
    along.scaleBy(-dist)
    origin = origin.copy()
    origin.translateBy(along)
    x = geom.uDirection.copy()
    x.normalize()
    y = z.crossProduct(x)
    return comp, (origin, x, y, z)


def _plane_in(plane, center, comp):
    """Plane geometry in comp's space. A face's normal points out of its body,
    so the pulley builds outward from a face."""
    native = _native(plane)
    geom = native.geometry.copy()
    if native.objectType == adsk.fusion.BRepFace.classType():
        _, n = native.evaluator.getNormalAtPoint(native.pointOnFace)
        geom.normal = n
    owner = _owner(native)
    if owner == comp:
        if _other_copy(plane, center):
            raise PulleyError('The plane is in another copy of %s than the center. The pulley goes in %s, '
                              'so every copy gets one: pick both in the same copy.' % (comp.name, comp.name))
        return geom
    # Different components: go through root space.
    if plane.assemblyContext:
        geom.transformBy(plane.assemblyContext.transform2)
    elif owner != _design().rootComponent:
        raise PulleyError('Pick the plane in the assembly, not inside another component.')
    if center.assemblyContext:
        to_comp = center.assemblyContext.transform2.copy()
        to_comp.invert()
        geom.transformBy(to_comp)
    return geom


def _solid(o, frame):
    """The pulley solid placed on the frame; Flip builds it the other way."""
    origin, x, y, z = frame
    if o['flip']:
        z = z.copy()
        z.scaleBy(-1)
        y = y.copy()
        y.scaleBy(-1)  # keep the frame right-handed
    solid = body.build(o)
    m = adsk.core.Matrix3D.create()
    m.setWithCoordinateSystem(origin, x, y, z)
    adsk.fusion.TemporaryBRepManager.get().transform(solid, m)
    return solid
