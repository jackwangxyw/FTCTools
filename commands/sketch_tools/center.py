"""Center Distance: dimension two sketch entities to a belt's center distance.

Click two points or circles (their centers), or two parallel lines. Pick the
profile, both pulley tooth counts, and the belt's tooth count or length. A
user parameter <Name> (CC1, CC2, ...) solves the center distance from the
tooth-count and belt parameters, and the dimension is just "<Name>", so its
edit box stays short:

    C0 = (b + sqrt(b^2 - 8 d^2)) / 4,   b = L - pi (r1 + r2),  d = r2 - r1
    C  = one Newton step from C0 on the exact belt length
         L(C) = 2 C cos(phi) + pi (r1 + r2) + 2 phi d,  sin(phi) = d / C

C0 is inlined, so the parameters added are <Name>, the belt's (<Name>_BeltTeeth
or <Name>_BeltLength) and tooth counts for picks that aren't Pulley Diameter
circles. One step is within 0.002 mm of exact even for a 5:1 ratio packed
tight, and ~1e-9 mm for normal layouts.

Circles dimensioned with Pulley Diameter fill in the profile and tooth count,
and the expressions use their <Pulley>_Teeth parameters directly, so a pulley
tooth change resizes the circle and moves the centers together.
"""

import json
import os

import adsk.core
import adsk.fusion

from .. import panel
from ..belt import body as belt_body
from ..pulley import profiles
from ..pulley.profiles import PulleyError
from . import common
from .common import SketchToolError

CMD_ID = 'FTCTools_CenterDistance'
ICONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', 'center')
MODES = [('teeth', 'Belt teeth'), ('length', 'Belt length')]
CC_ATTR = 'center:'   # design attribute per dimension name: profile and belt mode
DEFAULTS = {'profile': 'htd_5', 'teeth1': 24, 'teeth2': 36, 'mode': 'teeth', 'belt_teeth': 90, 'belt_length': '450 mm'}

_handlers = []


def start():
    cmd_def = common.ui.commandDefinitions.addButtonDefinition(
        CMD_ID, 'Center Distance', 'Dimension two points, circles or lines to a belt\'s center distance.', ICONS)
    common.on(_handlers, cmd_def.commandCreated, adsk.core.CommandCreatedEventHandler, _created, 'Center Distance')
    panel.get(sketch=True).controls.addCommand(cmd_def)


def stop():
    control = panel.get(sketch=True).controls.itemById(CMD_ID)
    if control:
        control.deleteMe()
    panel.remove_if_empty(sketch=True)
    cmd_def = common.ui.commandDefinitions.itemById(CMD_ID)
    if cmd_def:
        cmd_def.deleteMe()
    _handlers.clear()


def expression(key, t1, t2, length):
    """The center distance from tooth-count expressions t1, t2 (parameter
    names or numbers) and a belt pitch-length expression."""
    p = common.mm(profiles.profile(key)['pitch'])
    d = '((%s - %s) * %s / (2 * PI))' % (t2, t1, p)
    wrap = '(%s + %s) * %s / 2' % (t1, t2, p)             # pi (r1 + r2)
    b = '(%s - %s)' % (length, wrap)
    c0 = '(%s + sqrt(%s ^ 2 - 8 * %s ^ 2)) / 4' % (b, b, d)

    def newton(prev):
        phi = 'asin(%s / %s)' % (d, prev)
        return '%s - (2 * %s * cos(%s) + %s + 2 * (%s / 1 rad) * %s - %s) / (2 * cos(%s))' % (
            prev, prev, phi, wrap, phi, d, length, phi)
    return newton('(%s)' % c0)


# -------------------------------------------------------------------- dialog

def _created(args):
    cmd = args.command
    inputs = cmd.commandInputs
    for input_id, label in (('one', 'Pulley 1'), ('two', 'Pulley 2')):
        sel = inputs.addSelectionInput(input_id, label, 'Point, circle (its center) or line')
        for f in ('SketchPoints', 'SketchCircles', 'SketchLines'):
            sel.addSelectionFilter(f)
        sel.setSelectionLimits(1, 1)
    common.add_profile_dropdown(inputs, DEFAULTS['profile'])
    inputs.addIntegerSpinnerCommandInput('teeth1', 'Pulley 1 teeth', 6, 400, 1, DEFAULTS['teeth1'])
    inputs.addIntegerSpinnerCommandInput('teeth2', 'Pulley 2 teeth', 6, 400, 1, DEFAULTS['teeth2'])
    dd = inputs.addDropDownCommandInput('mode', 'Belt', adsk.core.DropDownStyles.TextListDropDownStyle)
    for k, label in MODES:
        dd.listItems.add(label, k == DEFAULTS['mode'])
    inputs.addIntegerSpinnerCommandInput('belt_teeth', 'Belt teeth', 20, 2000, 1, DEFAULTS['belt_teeth'])
    inputs.addValueInput('belt_length', 'Belt length', common.design().unitsManager.defaultLengthUnits,
                         adsk.core.ValueInput.createByString(DEFAULTS['belt_length']))
    inputs.itemById('belt_length').tooltip = 'Pitch length (circumference at the pitch line).'
    inputs.addStringValueInput('name', 'Name', common.unique_name('CC', ''))
    inputs.itemById('name').tooltip = 'The center distance parameter gets this name; the belt\'s is <Name>_BeltTeeth.'
    inputs.addTextBoxCommandInput('result', 'Center distance', '', 1, True)
    _refresh(inputs)

    common.on(_handlers, cmd.select, adsk.core.SelectionEventHandler, _on_select, 'Center Distance')
    common.on(_handlers, cmd.inputChanged, adsk.core.InputChangedEventHandler,
              lambda a: _refresh(a.input.parentCommand.commandInputs), 'Center Distance')
    common.on(_handlers, cmd.validateInputs, adsk.core.ValidateInputsEventHandler, _validate, 'Center Distance')
    common.on(_handlers, cmd.execute, adsk.core.CommandEventHandler, _execute, 'Center Distance')


def _selection(inputs, input_id):
    sel = inputs.itemById(input_id)
    return sel.selection(0).entity if sel.selectionCount else None


def _read(inputs):
    return {'one': _selection(inputs, 'one'), 'two': _selection(inputs, 'two'),
            'profile': common.profile_key(inputs.itemById('profile').selectedItem.name),
            'teeth1': inputs.itemById('teeth1').value, 'teeth2': inputs.itemById('teeth2').value,
            'mode': next(k for k, l in MODES if l == inputs.itemById('mode').selectedItem.name),
            'belt_teeth': inputs.itemById('belt_teeth').value,
            'belt_length': inputs.itemById('belt_length').expression,
            'name': inputs.itemById('name').value.strip()}


def _refresh(inputs):
    v = _read(inputs)
    inputs.itemById('belt_teeth').isVisible = v['mode'] == 'teeth'
    inputs.itemById('belt_length').isVisible = v['mode'] == 'length'
    um = common.design().unitsManager
    try:
        C = center_distance(v)
        inputs.itemById('result').text = um.formatInternalValue(C, um.defaultLengthUnits, True)
    except (PulleyError, RuntimeError) as e:
        inputs.itemById('result').text = str(e)


def center_distance(v):
    pitch = profiles.profile(v['profile'])['pitch']
    if v['mode'] == 'teeth':
        belt_teeth = v['belt_teeth']
    else:
        um = common.design().unitsManager
        belt_teeth = um.evaluateExpression(v['belt_length'], um.defaultLengthUnits) / pitch
    return belt_body.center_distance(v['profile'], belt_teeth, v['teeth1'], v['teeth2'])


def _on_select(args):
    inputs = args.activeInput.parentCommand.commandInputs
    entity = args.selection.entity
    # A Pulley Diameter circle: take its profile and tooth count.
    tag = common.pulley_tag(entity)
    if tag is not None:
        common.select_item(inputs.itemById('profile'), common.profile_label(tag['profile']))
        teeth = common.design().userParameters.itemByName(tag['teeth'])
        inputs.itemById('teeth1' if args.activeInput.id == 'one' else 'teeth2').value = int(round(teeth.value))
    if args.activeInput.id == 'one':
        inputs.itemById('two').hasFocus = True
    # A pair this tool already dimensioned: load what it was made with.
    v = _read(inputs)
    if v['one'] is not None and v['two'] is not None:
        _load_existing(inputs, v)
    _refresh(inputs)


def _load_existing(inputs, v):
    try:
        dim = _existing_dimension(*_targets(v['one'], v['two']))
    except SketchToolError:
        return
    name = dim.parameter.expression.strip() if dim is not None else None
    attr = common.design().attributes.itemByName(common.ATTR_GROUP, CC_ATTR + name) if name else None
    if attr is None:
        return
    made = json.loads(attr.value)
    params = common.design().userParameters
    common.select_item(inputs.itemById('profile'), common.profile_label(made['profile']))
    common.select_item(inputs.itemById('mode'), dict(MODES)[made['mode']])
    # Tooth counts: a Pulley Diameter circle's parameter, else this one's own.
    for index, input_id, entity in ((1, 'teeth1', v['one']), (2, 'teeth2', v['two'])):
        tag = common.pulley_tag(entity)
        param = params.itemByName(tag['teeth'] if tag else '%s_Teeth%d' % (name, index))
        if param is not None:
            inputs.itemById(input_id).value = int(round(param.value))
    belt = params.itemByName(name + ('_BeltTeeth' if made['mode'] == 'teeth' else '_BeltLength'))
    if belt is not None and made['mode'] == 'teeth':
        inputs.itemById('belt_teeth').value = int(round(belt.value))
    elif belt is not None:
        inputs.itemById('belt_length').expression = belt.expression
    inputs.itemById('name').value = name


def _validate(args):
    v = _read(args.inputs)
    ok = v['one'] is not None and v['two'] is not None and bool(common.NAME_RE.match(v['name']))
    if ok and v['mode'] == 'length':
        ok = args.inputs.itemById('belt_length').isValidExpression
    args.areInputsValid = ok


def _execute(args):
    v = _read(args.command.commandInputs)
    try:
        center_distance(v)
        apply(v)
    except (SketchToolError, PulleyError) as e:
        common.ui.messageBox(str(e), 'Center Distance')


def apply(v):
    name = v['name']
    common.check_name(name)
    one, two = _targets(v['one'], v['two'])
    dim = _existing_dimension(one, two)
    # Reusing a name is only rerunning this tool on the parameter it made.
    taken = common.design().allParameters.itemByName(name)
    ours = common.design().attributes.itemByName(common.ATTR_GROUP, CC_ATTR + name) is not None
    if taken is not None and not ours:
        raise SketchToolError('A parameter named %s already exists. Pick another name.' % name)
    params = common.design().userParameters

    # Tooth counts: a Pulley Diameter circle's own parameter, else ours.
    teeth = []
    for index, entity, count in ((1, v['one'], v['teeth1']), (2, v['two'], v['teeth2'])):
        tag = common.pulley_tag(entity)
        if tag is not None:
            if tag['profile'] != v['profile']:
                raise SketchToolError('Pulley %d is %s, not %s. Change one of them to match.' % (
                    index, common.profile_label(tag['profile']), common.profile_label(v['profile'])))
            common.set_param(tag['teeth'], str(int(count)), '')
            teeth.append(tag['teeth'])
        else:
            own = '%s_Teeth%d' % (name, index)
            common.set_param(own, str(int(count)), '', 'Pulley tooth count (FTC Tools)')
            teeth.append(own)

    if v['mode'] == 'teeth':
        common.set_param(name + '_BeltTeeth', str(int(v['belt_teeth'])), '', 'Belt tooth count (FTC Tools)')
        length = '%s_BeltTeeth * %s' % (name, common.mm(profiles.profile(v['profile'])['pitch']))
        unused = name + '_BeltLength'
    else:
        common.set_param(name + '_BeltLength', v['belt_length'], 'mm', 'Belt pitch length (FTC Tools)')
        length = name + '_BeltLength'
        unused = name + '_BeltTeeth'

    common.set_param(name, expression(v['profile'], teeth[0], teeth[1], length), 'mm', 'Center distance (FTC Tools)')
    try:
        if dim is None:
            dim = _add_dimension(one, two)
        dim.parameter.expression = name
    except RuntimeError as e:
        raise SketchToolError('Could not dimension them (are they already constrained?):\n%s' % e)
    # Switching between belt teeth and length leaves the other one unused.
    old = params.itemByName(unused)
    if old is not None:
        old.deleteMe()
    common.design().attributes.add(common.ATTR_GROUP, CC_ATTR + name, json.dumps(
        {'profile': v['profile'], 'mode': v['mode']}))
    return dim


def _targets(one, two):
    """What the dimension goes between: two sketch points (a circle means its
    center) or two lines, in the same sketch."""
    def point_or_line(entity):
        entity = common.native(entity)
        if entity.objectType == adsk.fusion.SketchCircle.classType():
            return entity.centerSketchPoint
        return entity
    a, b = point_or_line(one), point_or_line(two)
    if a.parentSketch != b.parentSketch:
        raise SketchToolError('Pick both in the same sketch.')
    lines = [e.objectType == adsk.fusion.SketchLine.classType() for e in (a, b)]
    if any(lines) and not all(lines):
        raise SketchToolError('Pick two points/circles, or two parallel lines.')
    if a == b:
        raise SketchToolError('Pick two different entities.')
    return a, b


def _dimension_entities(dim):
    for first, second in (('entityOne', 'entityTwo'), ('line', 'entityTwo')):
        try:
            return getattr(dim, first), getattr(dim, second)
        except AttributeError:
            continue
    return None, None


def _existing_dimension(a, b):
    """A driving distance dimension already between a and b, if any."""
    for dim in a.parentSketch.sketchDimensions:
        if not dim.isDriving or dim.objectType not in (adsk.fusion.SketchLinearDimension.classType(),
                                                  adsk.fusion.SketchOffsetDimension.classType()):
            continue
        e1, e2 = _dimension_entities(dim)
        if (e1 == a and e2 == b) or (e1 == b and e2 == a):
            return dim
    return None


def _add_dimension(a, b):
    dims = a.parentSketch.sketchDimensions
    if a.objectType == adsk.fusion.SketchLine.classType():
        m = a.startSketchPoint.geometry
        n = b.startSketchPoint.geometry
        return dims.addOffsetDimension(a, b, adsk.core.Point3D.create((m.x + n.x) / 2 + 0.5, (m.y + n.y) / 2, 0))
    m, n = a.geometry, b.geometry
    text = adsk.core.Point3D.create((m.x + n.x) / 2, (m.y + n.y) / 2 + 0.5, 0)
    return dims.addDistanceDimension(a, b, adsk.fusion.DimensionOrientations.AlignedDimensionOrientation, text)
