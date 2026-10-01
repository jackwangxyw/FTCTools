"""The pulley solid: toothed section, optional flanges, bore and recesses.

Built in a local frame with the pulley axis on +z and the part starting at
z = 0. With flanges the toothed section runs from z = t to t + width, so a
6.5 mm pulley with 1 mm flanges is 8.5 mm long. Everything is cylinders,
cones and one prism, combined with temporary booleans, so it stays fast.

Dimensions in cm (Fusion's internal unit).
"""

import math

import adsk.core
import adsk.fusion

from ..lighten.geometry import prism
from . import profiles
from .profiles import PulleyError

UNION = adsk.fusion.BooleanTypes.UnionBooleanType
DIFFERENCE = adsk.fusion.BooleanTypes.DifferenceBooleanType
THROUGH = 1.0  # cm past each end, so cuts never leave a skin
EPS = 1e-4  # cm; flange features shorter than this are treated as zero

# Hub bolt patterns, stored on the feature by index, so only append.
# goBILDA: 4x M4 on a 16 mm square, so a 16*sqrt(2) mm circle starting at 45 deg.
# REV: 4x M3 on a 16 mm circle. The pulley gets clearance holes for those screws.
PATTERNS = [
    ('gobilda', 'goBILDA', {'count': 4, 'circle': 1.6 * math.sqrt(2), 'angle': math.pi / 4, 'hole': 0.43}),
    ('rev', 'REV', {'count': 4, 'circle': 1.6, 'angle': 0.0, 'hole': 0.34}),
    ('custom', 'Custom', None),
]
BORES = [('none', 'None'), ('round', 'Round'), ('hex', 'Hex'), ('hub', 'Hub')]


def _tb():
    return adsk.fusion.TemporaryBRepManager.get()


def _merge(target, tool, op):
    if not _tb().booleanOperation(target, tool, op):
        raise PulleyError('Could not combine the pulley geometry.')


def _pt(x, y, z):
    return adsk.core.Point3D.create(x, y, z)


def _cylinder(radius, z0, z1, x=0.0, y=0.0):
    return _tb().createCylinderOrCone(_pt(x, y, z0), radius, _pt(x, y, z1), radius)


def _flange(od_r, z_face, outward, thickness, height, angle):
    """Flange touching the toothed section at z_face and extending `thickness`
    away from it (outward = -1 or +1). The belt side is beveled: it leaves the
    tooth tops at the OD and slopes away from the belt as it rises by `height`."""
    drop = height * math.tan(angle)
    if drop > thickness + EPS:
        raise PulleyError('Flange angle too steep for its thickness and height.')
    rim_r = od_r + height
    z_outer = z_face + outward * thickness
    if drop < EPS:
        return _cylinder(rim_r, z_face, z_outer)
    if thickness - drop < EPS:
        # All bevel, down to a knife-edge rim: no flat part to add (a
        # zero-length cylinder is invalid geometry).
        return _tb().createCylinderOrCone(_pt(0, 0, z_face), od_r, _pt(0, 0, z_outer), rim_r)
    z_rim = z_face + outward * drop
    body = _cylinder(rim_r, z_rim, z_outer)
    cone = _tb().createCylinderOrCone(_pt(0, 0, z_face), od_r, _pt(0, 0, z_rim), rim_r)
    _merge(body, cone, UNION)
    return body


def _hex_prism(across_flats, z0, z1):
    r = across_flats / 2 / math.cos(math.pi / 6)  # corner radius
    corners = [_pt(r * math.cos(math.pi / 3 * i), r * math.sin(math.pi / 3 * i), z0) for i in range(6)]
    lines = [adsk.core.Line3D.create(corners[i], corners[(i + 1) % 6]) for i in range(6)]
    wire, _ = _tb().createWireFromCurves(lines, False)
    face = _tb().createFaceFromPlanarWires([wire])
    return prism(face, adsk.core.Vector3D.create(0, 0, z1 - z0))


def build(o):
    """o: dict with profile, teeth, width, clearance, flanges, flange_t,
    flange_h, flange_angle, bore, bore_d, hex_af, pattern, bolt_circle,
    hole_d, hole_count, counterbore, cb_d, cb_depth, bridging, layer_h, bearing, bearing_flip,
    bearing_od, bearing_depth, hub_recess, hub_flip, hub_d, hub_depth. Lengths in cm, angle in radians."""
    spec = profiles.profile(o['profile'])
    od_r = profiles.outside_radius(spec, o['teeth'])
    t = o['flange_t'] if o['flanges'] else 0.0
    z0, z1 = t, t + o['width']
    length = z1 + t

    face = profiles.outline_face(o['profile'], o['teeth'], o['clearance'])
    m = adsk.core.Matrix3D.create()
    m.translation = adsk.core.Vector3D.create(0, 0, z0)
    _tb().transform(face, m)
    solid = prism(face, adsk.core.Vector3D.create(0, 0, o['width']))

    if o['flanges']:
        for z_face, outward in ((z0, -1), (z1, 1)):
            _merge(solid, _flange(od_r, z_face, outward, t, o['flange_h'], o['flange_angle']), UNION)

    # Everything cut from the center has to leave material under the teeth.
    root_r = od_r - spec['depth'] - o['clearance']
    bore = o['bore']
    if bore == 'round':
        _cut_round(solid, o['bore_d'] / 2, root_r, length)
    elif bore == 'hex':
        if o['hex_af'] / 2 / math.cos(math.pi / 6) >= root_r:
            raise PulleyError('Hex bore is larger than the pulley.')
        _merge(solid, _hex_prism(o['hex_af'], -THROUGH, length + THROUGH), DIFFERENCE)
    elif bore == 'hub':
        _cut_round(solid, o['bore_d'] / 2, root_r, length)
        pattern = next(p for k, _, p in PATTERNS if k == o['pattern'])
        count, circle, start, hole = ((o['hole_count'], o['bolt_circle'], 0.0, o['hole_d']) if pattern is None
                                      else (pattern['count'], pattern['circle'], pattern['angle'], pattern['hole']))
        if circle / 2 + hole / 2 >= root_r:
            raise PulleyError('Bolt holes fall outside the pulley.')
        if circle / 2 - hole / 2 <= o['bore_d'] / 2:
            raise PulleyError('Bolt holes run into the bore. Shrink the bore or widen the bolt circle.')
        centers = [(circle / 2 * math.cos(start + 2 * math.pi * i / count),
                    circle / 2 * math.sin(start + 2 * math.pi * i / count)) for i in range(int(count))]
        for x, y in centers:
            _merge(solid, _cylinder(hole / 2, -THROUGH, length + THROUGH, x, y), DIFFERENCE)
        if o['counterbore']:
            r, d = o['cb_d'] / 2, o['cb_depth']
            if r <= hole / 2:
                raise PulleyError('Counterbore must be wider than the bolt holes.')
            if circle / 2 + r >= root_r:
                raise PulleyError('Counterbores fall outside the pulley.')
            layers = 2 * o['layer_h'] if o['bridging'] else 0.0
            if d + layers >= length:
                raise PulleyError('Counterbore is deeper than the pulley.')
            # Screw heads go on the end away from the hub. `inward` points from
            # that end into the part; `floor` is the counterbore's floor.
            inward, floor = (1, d) if o['hub_flip'] else (-1, length - d)
            z_open = -THROUGH if o['hub_flip'] else length + THROUGH
            for x, y in centers:
                _merge(solid, _cylinder(r, min(z_open, floor), max(z_open, floor), x, y), DIFFERENCE)
                if o['bridging']:
                    _bridge_layers(solid, x, y, r, hole, floor, inward, o['layer_h'])

    if o['bearing'] and bore in ('round', 'hub'):
        r = o['bearing_od'] / 2
        if r >= root_r:
            raise PulleyError('Bearing recess is larger than the pulley.')
        d = o['bearing_depth']
        # One end: the start end, or the far end when flipped.
        if o['bearing_flip']:
            _merge(solid, _cylinder(r, length - d, length + THROUGH), DIFFERENCE)
        else:
            _merge(solid, _cylinder(r, -THROUGH, d), DIFFERENCE)

    if o['hub_recess'] and bore != 'none':
        r = o['hub_d'] / 2
        if r >= root_r:
            raise PulleyError('Hub recess is larger than the pulley.')
        d = o['hub_depth']
        if o['hub_flip']:
            _merge(solid, _cylinder(r, length - d, length + THROUGH), DIFFERENCE)
        else:
            _merge(solid, _cylinder(r, -THROUGH, d), DIFFERENCE)

    return solid


def _bridge_layers(solid, x, y, cb_r, hole_d, floor, inward, h):
    """Sequential bridging above a counterbore floor, for printing it facing
    the bed: the first layer cuts a slot the bolt hole's width (leaving two
    bridges across the counterbore), the second a square of that width (two
    bridges the other way). The round hole then starts on solid layers."""
    tb = _tb()
    for k, (length, width) in enumerate(((2 * cb_r, hole_d), (hole_d, hole_d))):
        za, zb = floor + inward * k * h, floor + inward * (k + 1) * h
        box = tb.createBox(adsk.core.OrientedBoundingBox3D.create(
            _pt(x, y, (za + zb) / 2), adsk.core.Vector3D.create(1, 0, 0), adsk.core.Vector3D.create(0, 1, 0),
            length, width, abs(zb - za)))
        # Stay inside the counterbore's circle, so the slot's corners don't
        # cut into the wall around it.
        _merge(box, _cylinder(cb_r, min(za, zb), max(za, zb), x, y), adsk.fusion.BooleanTypes.IntersectionBooleanType)
        _merge(solid, box, DIFFERENCE)


def _cut_round(solid, radius, root_r, length):
    if radius >= root_r:
        raise PulleyError('Bore is larger than the pulley.')
    _merge(solid, _cylinder(radius, -THROUGH, length + THROUGH), DIFFERENCE)
