"""Shared pieces of the sketch tools: parameters, pulley tags and dimensions.

The sketch tools are parametric through user parameters. Pulley Diameter
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


def native(entity):
    return entity.nativeObject if entity.assemblyContext else entity


def mm(cm):
    """A length in cm as an expression literal in mm, e.g. '0.5715 mm'."""
    return '%s mm' % repr(round(cm * 10, 6)).rstrip('0').rstrip('.')


def profile_label(key):
    return next(l for k, l, _ in profiles.PROFILES if k == key)


def profile_key(label):
    return next(k for k, l, _ in profiles.PROFILES if l == label)


def add_profile_dropdown(inputs, selected):
    dd = inputs.addDropDownCommandInput('profile', 'Profile', adsk.core.DropDownStyles.TextListDropDownStyle)
    for key, label, _ in profiles.PROFILES:
        dd.listItems.add(label, key == selected)
    return dd


def select_item(dropdown, name):
    for item in dropdown.listItems:
        item.isSelected = item.name == name


def check_name(name):
    if not NAME_RE.match(name):
        raise SketchToolError('"%s" is not a valid parameter name: letters, digits and _, not starting with a digit.' % name)


def unique_name(prefix, suffix):
    """First prefix + n (n = 1, 2, ...) whose prefix + n + suffix parameter doesn't exist."""
    params = design().allParameters
    n = 1
    while params.itemByName('%s%d%s' % (prefix, n, suffix)) is not None:
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
    """The Pulley Diameter tag on a sketch circle, or None:
    {'profile', 'teeth' (parameter name), 'kind'}."""
    if entity is None or entity.objectType != adsk.fusion.SketchCircle.classType():
        return None
    attr = native(entity).attributes.itemByName(ATTR_GROUP, PULLEY_ATTR)
    if attr is None:
        return None
    tag = json.loads(attr.value)
    # A tag whose parameter was deleted no longer links anything.
    if design().userParameters.itemByName(tag['teeth']) is None:
        return None
    return tag


def set_pulley_tag(circle, tag):
    native(circle).attributes.add(ATTR_GROUP, PULLEY_ATTR, json.dumps(tag))
