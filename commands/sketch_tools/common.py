"""Shared pieces of the sketch tools: parameters, pulley tags and dimensions.

The sketch tools are parametric through user parameters. Pulley & Gear Diameter
drives a circle's diameter dimension with an expression on a tooth-count
parameter (e.g. Pulley1_Teeth), and tags the circle with an attribute naming
that parameter and the profile. Center Distance reads those tags, so its
expressions reference the same tooth-count parameters.
"""

import json
import re
import traceback

import adsk.core
import adsk.fusion

from ..pulley import profiles

app = adsk.core.Application.get()
ui = app.userInterface

ATTR_GROUP = 'FTCTools'
PULLEY_ATTR = 'pulley'
GEAR = 'gear'            # the "profile" of a spur gear circle; its tag also has 'module' (cm)
GEAR_LABEL = 'Gear'
NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


class SketchToolError(Exception):
    pass


def design():
    return adsk.fusion.Design.cast(app.activeProduct)


def on(handlers, event, handler_base, fn, title):
    """Subscribe fn to a Fusion event. Unhandled errors are shown, never dropped."""
    class Handler(handler_base):
        def notify(self, args):
            try:
                fn(args)
            except Exception:
                ui.messageBox('%s failed:\n%s' % (title, traceback.format_exc()))
    handler = Handler()
    event.add(handler)
    handlers.append(handler)
    return handler


def native(entity):
    return entity.nativeObject if entity.assemblyContext else entity


def mm(cm):
    """A length in cm as an expression literal in mm, e.g. '0.5715 mm'."""
    return '%s mm' % repr(round(cm * 10, 6)).rstrip('0').rstrip('.')


def _labels():
    return [(k, l) for k, l, _ in profiles.PROFILES] + [(GEAR, GEAR_LABEL)]


def profile_label(key):
    return next(l for k, l in _labels() if k == key)


def profile_key(label):
    return next(k for k, l in _labels() if l == label)


def add_profile_dropdown(inputs, selected, gear=False):
    dd = inputs.addDropDownCommandInput('profile', 'Profile', adsk.core.DropDownStyles.TextListDropDownStyle)
    for key, label in (_labels() if gear else _labels()[:-1]):
        dd.listItems.add(label, key == selected)
    return dd


def select_item(dropdown, name):
    for item in dropdown.listItems:
        item.isSelected = item.name == name


def check_name(name):
    if not NAME_RE.match(name):
        raise SketchToolError('"%s" is not a valid parameter name: letters, digits and _, not starting with a digit.' % name)


def unique_name(prefix):
    """First prefix + n (n = 1, 2, ...) that no parameter has."""
    params = design().allParameters
    n = 1
    while params.itemByName('%s%d' % (prefix, n)) is not None:
        n += 1
    return '%s%d' % (prefix, n)


def free_name(base, current=None):
    """base, or base_2, base_3, ... if taken by a parameter other than current."""
    params = design().allParameters
    name, n = base, 2
    while True:
        taken = params.itemByName(name)
        if taken is None or (current is not None and taken.name == current.name):
            return name
        name = '%s_%d' % (base, n)
        n += 1


def set_param(name, expression, units, comment=''):
    """Create or update a user parameter."""
    params = design().userParameters
    param = params.itemByName(name)
    if param is None:
        return params.add(name, adsk.core.ValueInput.createByString(expression), units, comment)
    if param.unit != units:
        raise SketchToolError('Parameter %s already exists with other units.' % name)
    param.expression = expression
    return param


def pulley_tag(entity):
    """The Pulley & Gear Diameter tag on a sketch circle, or None:
    {'profile', 'teeth' (parameter name), 'kind', and 'module' for a gear}."""
    # Right-click hands over whatever is selected (a component, a body, ...);
    # only sketch points and circles can carry the tag.
    if entity is None or entity.objectType not in (adsk.fusion.SketchPoint.classType(),
                                                   adsk.fusion.SketchCircle.classType()):
        return None
    entity = native(entity)
    if entity.objectType == adsk.fusion.SketchPoint.classType():
        # A dimension to a circle is really to its center point.
        entity = next((c for c in entity.parentSketch.sketchCurves.sketchCircles
                       if c.centerSketchPoint == entity and c.attributes.itemByName(ATTR_GROUP, PULLEY_ATTR)), None)
        if entity is None:
            return None
    if entity.objectType != adsk.fusion.SketchCircle.classType():
        return None
    attr = entity.attributes.itemByName(ATTR_GROUP, PULLEY_ATTR)
    if attr is None:
        return None
    tag = json.loads(attr.value)
    # A tag whose parameter was deleted no longer links anything.
    if design().userParameters.itemByName(tag['teeth']) is None:
        return None
    return tag


def set_pulley_tag(circle, tag):
    native(circle).attributes.add(ATTR_GROUP, PULLEY_ATTR, json.dumps(tag))


# ------------------------------------------------------------------- editing
# Double-clicking a sketch dimension starts this Fusion command, which shows
# its inline value box (seen in a commandStarting log, with the dimension as
# the active selection).
EDIT_DIMENSION_CMD = 'SketchEditDimensionCmdDef'
_pending = {}


def install_editing(ui_handlers, handlers, title, edit_cmd_id, match):
    """Double-click and right-click editing for a sketch tool.

    match(entity) returns the entity to edit (truthy) for the dimensions and
    geometry this tool made. Double-clicking such a dimension cancels Fusion's
    value box and runs edit_cmd_id instead; right-clicking offers it in the
    menu. The command is started from a custom event, because a command can't
    be started while another one is starting.
    """
    event_id = edit_cmd_id + '_Launch'
    custom = app.registerCustomEvent(event_id)

    def add(event, base, fn):
        ui_handlers.append((event, on(handlers, event, base, fn, title)))

    def launch(args):
        ui.commandDefinitions.itemById(edit_cmd_id).execute()

    def selected():
        sel = ui.activeSelections
        return match(sel.item(0).entity) if sel.count == 1 else None

    def starting(args):
        if args.commandId != EDIT_DIMENSION_CMD:
            return
        target = selected()
        if target:
            args.isCanceled = True
            _pending[edit_cmd_id] = target
            app.fireCustomEvent(event_id)

    def marking_menu(args):
        if selected():
            controls = args.linearMarkingMenu.controls
            if controls.itemById(edit_cmd_id) is None:
                controls.addCommand(ui.commandDefinitions.itemById(edit_cmd_id))

    add(custom, adsk.core.CustomEventHandler, launch)
    add(ui.commandStarting, adsk.core.ApplicationCommandEventHandler, starting)
    add(ui.markingMenuDisplaying, adsk.core.MarkingMenuEventHandler, marking_menu)
    return event_id


def editing_target(edit_cmd_id, match):
    """What the edit command was started for: the double-clicked entity, or
    the right-clicked selection."""
    target = _pending.pop(edit_cmd_id, None)
    if target is None and ui.activeSelections.count == 1:
        target = match(ui.activeSelections.item(0).entity)
    return target


def remove_editing(ui_handlers, event_id):
    for event, handler in ui_handlers:
        event.remove(handler)
    ui_handlers.clear()
    app.unregisterCustomEvent(event_id)
