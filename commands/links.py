"""Links between the tools. A Pulley's or Belt's count parameter follows a
sketch tool's user parameter (HTD5_24T, CC1_BeltTeeth) or another feature's
parameter (a Belt's pulley teeth naming a Pulley's d20) by having that name
as its expression, so Fusion recomputes it when the source changes and
renames it with the source. Profiles have no parameter to reference, so a
profile change is pushed along the same links."""

import adsk.core
import adsk.fusion

from .pulley import profiles

app = adsk.core.Application.get()
PULLEY = 'FTCToolsPulley'
BELT = 'FTCToolsBelt'


def _design():
    return adsk.fusion.Design.cast(app.activeProduct)


def features():
    """Every Pulley and Belt feature in the design, from the timeline: while a
    sketch is being edited the timeline is rolled back to it, and the
    features after it are missing from their components' feature lists but
    can still be read and written through their timeline items."""
    timeline = _design().timeline
    for i in range(timeline.count):
        item = timeline.item(i)
        for entry in ([item.item(j) for j in range(item.count)] if item.isGroup else [item]):
            feature = entry.entity
            if (feature is not None and feature.objectType == adsk.fusion.CustomFeature.classType()
                    and feature.definition is not None and feature.definition.id in (PULLEY, BELT)):
                yield feature


def referencing(expr):
    """(feature, parameter) for every Pulley and Belt parameter whose expression is expr."""
    return [(f, p) for f in features() for p in f.parameters if p.expression == expr]


def param(feature, param_id):
    """A feature's custom parameter by id, or None if it hasn't got one.
    Features made by an older version lack newer parameters, and itemById
    raises for those instead of returning None."""
    params = feature.parameters
    for i in range(params.count):
        if params.item(i).id == param_id:
            return params.item(i)
    return None


def evaluate(expr):
    """A unitless link expression's current value. (isValidExpression says a
    bare parameter name is invalid, though it evaluates fine.)"""
    return _design().unitsManager.evaluateExpression(expr, '')


def relink(old, new):
    """Point every parameter whose expression is `old` at `new` instead."""
    for _, param in referencing(old):
        param.expression = new


def unlink(expr):
    """Parameters following expr keep its current value and stop following."""
    for _, param in referencing(expr):
        param.expression = str(int(round(param.value)))


def push_profile(expr, key):
    """Set the profile of every Pulley and Belt linked to expr, and of the
    Belts linked to those Pulleys."""
    index = [k for k, _, _ in profiles.PROFILES].index(key)
    for feature, param in referencing(expr):
        profile = feature.parameters.itemById('profile')
        if int(round(profile.value)) != index:
            profile.value = index
        if feature.definition.id == PULLEY and param.id == 'teeth':
            push_profile(param.name, key)
