"""Belt: closed timing belt around two pulleys (GT2 2mm, GT2 3mm, HTD 3mm, HTD 5mm).

The belt is its own component holding a Fusion custom feature that groups one
base feature: the belt solid. Belt teeth, both pulley tooth counts, width and
offset are custom parameters. The center distance follows from them and is
shown in the dialog. Placement: pulley 1 (a Pulley, or its center point and
optional plane, as for Pulley) and optionally pulley 2 (a Pulley or a point)
for the direction. Without pulley 2 the belt runs along the plane's x axis
(the sketch's x axis for a sketch point).
"""

import json
import math
import os
import traceback

import adsk.core
import adsk.fusion

from .. import panel
from ..pulley import entry as pulley_entry
from ..pulley import profiles
from ..pulley.profiles import PulleyError
from . import body

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = 'FTCTools_Belt'
EDIT_CMD_ID = 'FTCTools_BeltEdit'
FEATURE_ID = 'FTCToolsBelt'
ICONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources')
SETTINGS_PATH = os.path.join(os.getenv('APPDATA') or os.path.expanduser('~'), 'FTCTools', 'belt.json')
OVERLAY_COLOR = (255, 210, 0)
SKETCH_CENTERS = pulley_entry.SKETCH_CENTERS

SIZES = [('width', 'Width', 'Width', '6 mm'), ('offset', 'Offset', 'Offset', '0 mm')]
COUNTS = [('belt_teeth', 'BeltTeeth', 'Belt teeth', 20, 2000, 150),
          ('teeth1', 'Pulley1Teeth', 'Pulley 1 teeth', 6, 400, 20),
          ('teeth2', 'Pulley2Teeth', 'Pulley 2 teeth', 6, 400, 40)]
PROFILE_KEYS = [k for k, _, _ in profiles.PROFILES]
DEFAULTS = dict([(s[0], s[3]) for s in SIZES] + [(c[0], c[5]) for c in COUNTS] + [('profile', 'gt2_2'), ('flip', False)])

_handlers = []
_feature_def = None
_edit = {}
_overlay = []
_creating = [False]


# ----------------------------------------------------------------- lifecycle

def start():
    global _feature_def
    create_def = ui.commandDefinitions.addButtonDefinition(
        CMD_ID, 'Belt', 'Timing belt around two pulleys: GT2 2mm, GT2 3mm, HTD 3mm or HTD 5mm.', ICONS)
    _on(create_def.commandCreated, adsk.core.CommandCreatedEventHandler, _create_created)

    edit_def = ui.commandDefinitions.addButtonDefinition(EDIT_CMD_ID, 'Edit Belt', 'Edit a Belt feature.', ICONS)
    _on(edit_def.commandCreated, adsk.core.CommandCreatedEventHandler, _edit_created)

    _feature_def = adsk.fusion.CustomFeatureDefinition.create(FEATURE_ID, 'Belt', ICONS)
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
                ui.messageBox('Belt failed:\n' + traceback.format_exc())
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


def _build_inputs(cmd, values):
    inputs = cmd.commandInputs
    units = _design().unitsManager.defaultLengthUnits

    sel = inputs.addSelectionInput('center', 'Pulley 1', 'A Pulley, or its center: sketch point or circle, or any point with a plane')
    for f in ('SolidBodies', 'SketchPoints', 'SketchCircles', 'Vertices', 'ConstructionPoints'):
        sel.addSelectionFilter(f)
    sel.setSelectionLimits(1, 1)
    sel = inputs.addSelectionInput('toward', 'Pulley 2', 'Optional: a Pulley or a point toward it. Without it the belt runs along x.')
    for f in ('SolidBodies', 'SketchPoints', 'SketchCircles', 'Vertices', 'ConstructionPoints'):
        sel.addSelectionFilter(f)
    sel.setSelectionLimits(0, 1)
    sel = inputs.addSelectionInput('plane', 'Plane', 'Plane or face the belt starts on (optional for sketch points)')
    sel.addSelectionFilter('PlanarFaces')
    sel.addSelectionFilter('ConstructionPlanes')
    sel.setSelectionLimits(0, 1)

    dd = inputs.addDropDownCommandInput('profile', 'Profile', adsk.core.DropDownStyles.TextListDropDownStyle)
    for key, label, _ in profiles.PROFILES:
        dd.listItems.add(label, key == values['profile'])
    for input_id, _, label, lo, hi, _ in COUNTS:
        inputs.addIntegerSpinnerCommandInput(input_id, label, lo, hi, 1, int(values[input_id]))
    for input_id, _, label, _ in SIZES:
        inputs.addValueInput(input_id, label, units, adsk.core.ValueInput.createByString(values[input_id]))
    inputs.itemById('offset').tooltip = 'Distance from the plane to the belt, e.g. a pulley flange thickness.'
    inputs.addBoolValueInput('flip', 'Flip direction', True, '', bool(values['flip']))
    inputs.addTextBoxCommandInput('cc', 'Center distance', '', 1, True)


def _selection(inputs, input_id):
    sel = inputs.itemById(input_id)
    return sel.selection(0).entity if sel.selectionCount else None


def _read_inputs(inputs):
    label = inputs.itemById('profile').selectedItem.name
    v = {'center': _selection(inputs, 'center'), 'toward': _selection(inputs, 'toward'),
         'plane': _selection(inputs, 'plane'),
         'profile': next(k for k, l, _ in profiles.PROFILES if l == label),
         'flip': inputs.itemById('flip').value}
    for s in SIZES:
        v[s[0]] = inputs.itemById(s[0]).expression
    for c in COUNTS:
        v[c[0]] = inputs.itemById(c[0]).value
    return v


def _validate(args):
    inputs = args.inputs
    center = _selection(inputs, 'center')
    ok = center is not None
    if ok and center.objectType not in SKETCH_CENTERS and _pulley_feature(center) is None:
        ok = inputs.itemById('plane').selectionCount == 1
    w = inputs.itemById('width')
    off = inputs.itemById('offset')
    ok = ok and w.isValidExpression and w.value > 0 and off.isValidExpression
    args.areInputsValid = ok
    if not ok:
        _clear_overlay()


def _pre_select(args):
    # Bodies are only accepted when they are Pulleys.
    entity = args.selection.entity
    if entity.objectType == adsk.fusion.BRepBody.classType() and _pulley_feature(entity) is None:
        args.isSelectable = False


def _on_select(args):
    inputs = args.activeInput.parentCommand.commandInputs
    entity = args.selection.entity
    pulley = _pulley_feature(entity)
    if args.activeInput.id == 'center':
        if pulley is not None:
            _fill_from_pulley(inputs, pulley)
            inputs.itemById('toward').hasFocus = True
        elif entity.objectType not in SKETCH_CENTERS:
            # A plane is only needed for points that aren't in a sketch.
            inputs.itemById('plane').hasFocus = True
    elif args.activeInput.id == 'toward' and pulley is not None:
        inputs.itemById('teeth2').value = int(round(pulley.parameters.itemById('teeth').value))


def _fill_from_pulley(inputs, pulley):
    """Match the belt to a picked pulley 1: its profile, teeth, side, and an
    offset that clears its flange. Copied once; the belt doesn't track them."""
    p = pulley.parameters
    key = profiles.PROFILES[int(round(p.itemById('profile').value))][0]
    for item in inputs.itemById('profile').listItems:
        item.isSelected = item.name == next(l for k, l, _ in profiles.PROFILES if k == key)
    inputs.itemById('teeth1').value = int(round(p.itemById('teeth').value))
    inputs.itemById('flip').value = p.itemById('flip').value > 0.5
    flanges = p.itemById('flanges')
    inputs.itemById('offset').expression = (p.itemById('flange_t').expression
                                            if flanges is not None and flanges.value > 0.5 else '0 mm')


def _connect_dialog(cmd, preview, execute, destroy):
    _on(cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _validate)
    _on(cmd.preSelect, adsk.core.SelectionEventHandler, _pre_select)
    _on(cmd.select, adsk.core.SelectionEventHandler, _on_select)
    _on(cmd.executePreview, adsk.core.CommandEventHandler, preview)
    _on(cmd.execute, adsk.core.CommandEventHandler, execute)
    _on(cmd.destroy, adsk.core.CommandEventHandler, destroy)


def _show_center_distance(inputs, v):
    um = _design().unitsManager
    try:
        C = body.center_distance(v['profile'], v['belt_teeth'], v['teeth1'], v['teeth2'])
        inputs.itemById('cc').text = um.formatInternalValue(C, um.defaultLengthUnits, True)
    except PulleyError as e:
        inputs.itemById('cc').text = str(e)


def _preview(args):
    _draw_preview(args.command.commandInputs)


def _draw_preview(inputs):
    """Outline the belt solid's edges. Inputs that can't make a belt show nothing."""
    _clear_overlay()
    v = _read_inputs(inputs)
    _show_center_distance(inputs, v)
    try:
        comp, frame, phase = _placement(v['center'], v['plane'], v['toward'], v['flip'])
        solid = _solid(_options(v, phase), frame)
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
    # In the component the belt goes in: its space, and not ghosted when active.
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


def _options(v, phase):
    um = _design().unitsManager
    units = um.defaultLengthUnits
    return {'profile': v['profile'], 'belt_teeth': v['belt_teeth'], 'teeth1': v['teeth1'], 'teeth2': v['teeth2'],
            'width': um.evaluateExpression(v['width'], units), 'offset': um.evaluateExpression(v['offset'], units),
            'phase': phase}


# -------------------------------------------------------------------- create

def _create_created(args):
    cmd = args.command
    _build_inputs(cmd, _load_settings())
    _connect_dialog(cmd, _preview, _create_execute, lambda a: _clear_overlay())


def _create_execute(args):
    _clear_overlay()
    v = _read_inputs(args.command.commandInputs)
    try:
        parent, frame, phase = _placement(v['center'], v['plane'], v['toward'], v['flip'])
        solid = _solid(_options(v, phase), frame)
    except PulleyError as e:
        ui.messageBox(str(e), 'Belt')
        return
    _create_feature(v, parent, solid)
    _save_settings(v)


def _belt_name(key, teeth):
    return '%s %dT Belt' % (pulley_entry.SHORT_NAMES[key], teeth)


def _create_feature(v, parent, solid):
    """New component under the placement's component, holding the belt feature.
    Its occurrence has an identity transform, so the solid needs no transform."""
    occ = parent.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = _belt_name(v['profile'], v['belt_teeth'])
    units = _design().unitsManager.defaultLengthUnits

    base = comp.features.baseFeatures.add()
    base.startEdit()
    comp.bRepBodies.add(solid, base).name = comp.name
    base.finishEdit()
    base.name = 'Belt Body'

    cf_input = comp.features.customFeatures.createInput(_feature_def)
    for input_id, name, _, _ in SIZES:
        cf_input.addCustomParameter(input_id, name, adsk.core.ValueInput.createByString(v[input_id]), units, True)
    for input_id, name, _, _, _, _ in COUNTS:
        cf_input.addCustomParameter(input_id, name, adsk.core.ValueInput.createByReal(v[input_id]), '', True)
    # Choices live in hidden parameters so compute can read them during add.
    cf_input.addCustomParameter('profile', 'profile', adsk.core.ValueInput.createByReal(PROFILE_KEYS.index(v['profile'])), '', False)
    cf_input.addCustomParameter('flip', 'flip', adsk.core.ValueInput.createByReal(1 if v['flip'] else 0), '', False)
    _add_dependencies(cf_input.addDependency, v)
    cf_input.setStartAndEndFeatures(base, base)
    # Fusion computes once inside add; the base feature already holds this solid.
    _creating[0] = True
    try:
        return comp.features.customFeatures.add(cf_input)
    finally:
        _creating[0] = False


def _add_dependencies(add, v):
    add('center', v['center'])
    if v['toward'] is not None:
        add('toward', v['toward'])
    if v['plane'] is not None:
        add('plane', v['plane'])


# ---------------------------------------------------------------------- edit

def _feature_values(feature):
    p = feature.parameters
    v = {'profile': PROFILE_KEYS[int(round(p.itemById('profile').value))], 'flip': p.itemById('flip').value > 0.5}
    for input_id, _, _, _ in SIZES:
        v[input_id] = p.itemById(input_id).expression
    for input_id, _, _, _, _, _ in COUNTS:
        v[input_id] = int(round(p.itemById(input_id).value))
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
    deps = _dependencies(feature, skip_lost=True)
    _edit['populating'] = True
    try:
        for input_id in ('center', 'toward', 'plane'):
            if deps.get(input_id) is not None:
                inputs.itemById(input_id).addSelection(deps[input_id])
    finally:
        _edit['populating'] = False
    _draw_preview(inputs)


def _edit_execute(args):
    feature = _edit['feature']
    _clear_overlay()
    feature.timelineObject.rollTo(True)
    v = _read_inputs(args.command.commandInputs)

    # Rolled back to before this feature: one recompute when it rolls forward.
    feature.dependencies.deleteAll()
    _add_dependencies(feature.dependencies.add, v)
    p = feature.parameters
    for input_id, _, _, _ in SIZES:
        p.itemById(input_id).expression = v[input_id]
    for input_id, _, _, _, _, _ in COUNTS:
        p.itemById(input_id).value = v[input_id]
    p.itemById('profile').value = PROFILE_KEYS.index(v['profile'])
    p.itemById('flip').value = 1 if v['flip'] else 0
    feature.parentComponent.name = _belt_name(v['profile'], v['belt_teeth'])

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
        deps = _dependencies(feature)
        v = _feature_values(feature)
        _, frame, phase = _placement(deps['center'], deps.get('plane'), deps.get('toward'), v['flip'])
        p = feature.parameters
        o = {'profile': v['profile'], 'belt_teeth': v['belt_teeth'], 'teeth1': v['teeth1'], 'teeth2': v['teeth2'],
             'width': p.itemById('width').value, 'offset': p.itemById('offset').value, 'phase': phase}
        solid = _solid(o, frame)
        base.startEdit()
        try:
            updated = base.updateBody(base.bodies.item(0), solid)
        finally:
            base.finishEdit()
        if not updated:
            raise PulleyError('Could not update the belt body.')
    except PulleyError as e:
        # Custom feature compute errors can't carry custom text, so the reason
        # goes to the Text Commands log and the feature gets Fusion's message.
        app.log('Belt (%s): %s' % (feature.name, e))
        args.computeStatus.statusMessages.addError('API_COMPUTE_ERROR', '')
    except Exception:
        # A modal dialog here would block Fusion mid-recompute.
        app.log('Belt (%s) failed:\n%s' % (feature.name, traceback.format_exc()))
        args.computeStatus.statusMessages.addError('API_COMPUTE_ERROR', '')


def _dependencies(feature, skip_lost=False):
    """center, toward and plane by id. A reference to deleted geometry is an
    error for the recompute; edit passes skip_lost, since editing fixes it."""
    deps = {}
    for i in range(feature.dependencies.count):
        dep = feature.dependencies.item(i)
        if dep.entity is None:
            if skip_lost:
                continue
            raise PulleyError('Lost the reference "%s". Edit the feature and reselect it.' % dep.id)
        deps[dep.id] = dep.entity
    if not skip_lost and 'center' not in deps:
        raise PulleyError('The belt needs pulley 1\'s center.')
    return deps


# ------------------------------------------------------------------ geometry

def _pulley_feature(entity):
    """The Pulley feature that made a body, or None."""
    if entity is None or entity.objectType != adsk.fusion.BRepBody.classType():
        return None
    native = entity.nativeObject if entity.assemblyContext else entity
    for feature in native.parentComponent.features.customFeatures:
        if feature.definition.id == pulley_entry.FEATURE_ID:
            return feature
    return None


def _center_and_plane(center, plane):
    """A picked Pulley stands for its own center and plane."""
    pulley = _pulley_feature(center)
    if pulley is not None:
        return pulley_entry._dependencies(pulley)
    return center, plane


def _point_in(entity, center, comp):
    """A point entity's position in comp's space (center: the entity comp's
    frame came from, for its assembly context)."""
    native = pulley_entry._native(entity)
    t = native.objectType
    if t == adsk.fusion.SketchPoint.classType():
        p = native.worldGeometry
    elif t in (adsk.fusion.SketchCircle.classType(), adsk.fusion.SketchArc.classType()):
        p = native.centerSketchPoint.worldGeometry
    else:
        p = native.geometry
    owner = pulley_entry._owner(native)
    if owner == comp:
        return p
    p = p.copy()
    if entity.assemblyContext:
        p.transformBy(entity.assemblyContext.transform2)
    elif owner != _design().rootComponent:
        raise PulleyError('Pick pulley 2 in the assembly, not inside another component.')
    if center.assemblyContext:
        to_comp = center.assemblyContext.transform2.copy()
        to_comp.invert()
        p.transformBy(to_comp)
    return p


def _placement(center, plane, toward, flip):
    """(component, (origin, x, y, z), phase). x points at pulley 2 (the plane's
    x axis without one); phase is the angle, in the belt's frame, of pulley 1's
    grooves, so a Pulley on the same center meshes with the belt."""
    center, plane = _center_and_plane(center, plane)
    comp, (origin, fx, fy, z) = pulley_entry._placement(center, plane)
    d = fx.copy()
    if toward is not None:
        target, _ = _center_and_plane(toward, None)
        d = origin.vectorTo(_point_in(target, center, comp))
        along = z.copy()
        along.scaleBy(d.dotProduct(z))
        d.subtract(along)
        if d.length < 1e-6:
            raise PulleyError('Pulley 2 is on pulley 1\'s center.')
        d.normalize()
    beta = math.atan2(d.dotProduct(fy), d.dotProduct(fx))
    z = z.copy()
    if flip:
        z.scaleBy(-1)
    y = z.crossProduct(d)
    # Pulley grooves sit at k * step from the pulley frame's x axis (either
    # flip). Seen from the belt frame that is -beta + k * step, or +beta when
    # the belt's frame is mirrored by the flip.
    return comp, (origin, d, y, z), (beta if flip else -beta)


def _solid(o, frame):
    origin, x, y, z = frame
    solid, _ = body.build(o)
    m = adsk.core.Matrix3D.create()
    m.setWithCoordinateSystem(origin, x, y, z)
    adsk.fusion.TemporaryBRepManager.get().transform(solid, m)
    return solid
