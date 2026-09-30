"""Timing pulley tooth profiles and outline construction.

The pulley outline is built directly as a closed chain of arcs and lines, one
groove per tooth, so there are no booleans and the cost is linear in the tooth
count. Each groove is the belt tooth grown by the fit clearance:

    GT2  tooth tip arc, two flank arcs (each centered on the land line, offset
         across the tooth axis), and a root fillet into the outside diameter.
    HTD  round bottom, then straight sides parallel to the tooth axis up to a
         root fillet. The belt tooth's round part is wider than its base, so
         straight sides keep the groove from being undercut.

Outside diameter: OD = N * pitch / pi - 2 * PLD (pitch line differential).

Dimensions in cm (Fusion's internal unit). Sources, all in mm:
    tooth depth: Pfeifer Industries "Timing Belt Tooth Profiles and Pitches"
        (GT2 2mm 0.76, GT2 3mm 1.14, HTD 3M 1.22, HTD 5M 2.08); SDP-SI HTD 5M
        belt catalog 2.08; SIT HTD catalog 1.2 / 2.1.
    GT2 radii (tip R, flank R, flank offset b, root R): the Gates 2GT/3GT tooth
        drawing values as commonly cited. Consistency check: tip and flank arcs
        are tangent, |flank center - tip center| = flank R - tip R, which these
        satisfy to rounding.
    HTD 5M radii: tooth R1.49, root R0.43, 3.05 wide (SDP-SI, via Capolight).
    HTD 3M: the 5M shape scaled by the depth ratio 1.22 / 2.08; its width
        comes out 1.79, against a separately cited 1.78.
"""

import math

import adsk.core
import adsk.fusion


class PulleyError(Exception):
    pass


# Stored on the feature by index, so only append.
PROFILES = [
    ('gt2_2', 'GT2 2mm', {'kind': 'gt', 'pitch': 0.2, 'pld': 0.0254,
                          'depth': 0.075, 'tip_r': 0.0555, 'flank_r': 0.100, 'flank_b': 0.040, 'root_r': 0.015}),
    ('gt2_3', 'GT2 3mm', {'kind': 'gt', 'pitch': 0.3, 'pld': 0.0381,
                          'depth': 0.114, 'tip_r': 0.085, 'flank_r': 0.152, 'flank_b': 0.061, 'root_r': 0.025}),
    ('htd_3', 'HTD 3mm', {'kind': 'htd', 'pitch': 0.3, 'pld': 0.0381,
                          'depth': 0.122, 'tooth_r': 0.149 * 1.22 / 2.08, 'root_r': 0.043 * 1.22 / 2.08}),
    ('htd_5', 'HTD 5mm', {'kind': 'htd', 'pitch': 0.5, 'pld': 0.05715,
                          'depth': 0.208, 'tooth_r': 0.149, 'root_r': 0.043}),
]


def profile(key):
    return next(p for k, _, p in PROFILES if k == key)


def outside_radius(spec, teeth):
    return teeth * spec['pitch'] / (2 * math.pi) - spec['pld']


def _p(x, y):
    return adsk.core.Point3D.create(x, y, 0)


def _unit(dx, dy):
    d = math.hypot(dx, dy)
    return dx / d, dy / d


def _arc(center, radius, start, end):
    """Minor arc on a circle through start and end."""
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
    am = a0 + da / 2
    mid = (center[0] + radius * math.cos(am), center[1] + radius * math.sin(am))
    return ('arc', start, mid, end)


def _fillet_center(flank_center, flank_r, od_r, root_r):
    """Center of the root fillet: tangent inside the OD circle and outside
    the flank circle, on the +x side."""
    a = od_r - root_r                  # |C| = a
    d = flank_r + root_r               # |C - F| = d
    fx, fy = flank_center
    dist = math.hypot(fx, fy)
    # Intersection of circle(O, a) and circle(F, d).
    t = (a * a - d * d + dist * dist) / (2 * dist)
    hh = a * a - t * t
    if hh < 0:
        raise PulleyError('Too few teeth for this profile.')
    h = math.sqrt(hh)
    ux, uy = fx / dist, fy / dist
    cands = [(t * ux - h * uy, t * uy + h * ux), (t * ux + h * uy, t * uy - h * ux)]
    return max(cands, key=lambda c: c[0])


def _groove(spec, od_r, clearance):
    """One groove as a list of segments, local frame: tooth axis +y, the
    outside diameter crosses the axis at (0, od_r), the groove cuts toward
    the origin. Ordered from the +x side to the -x side (counterclockwise)."""
    root_r = spec['root_r']
    if spec['kind'] == 'gt':
        tip_r = spec['tip_r'] + clearance
        flank_r = spec['flank_r'] + clearance
        tip_c = (0.0, od_r - (spec['depth'] - spec['tip_r']))
        halves = []
        for side in (1, -1):
            flank_c = (-side * spec['flank_b'], od_r)
            ux, uy = _unit(tip_c[0] - flank_c[0], tip_c[1] - flank_c[1])
            tangent = (flank_c[0] + ux * flank_r, flank_c[1] + uy * flank_r)
            fc = _fillet_center((side * flank_c[0], flank_c[1]), flank_r, od_r, root_r)
            fc = (side * fc[0], fc[1])
            fx, fy = _unit(fc[0] - flank_c[0], fc[1] - flank_c[1])
            on_flank = (flank_c[0] + fx * flank_r, flank_c[1] + fy * flank_r)
            ox, oy = _unit(*fc)
            on_od = (ox * od_r, oy * od_r)
            halves.append((on_od, fc, on_flank, flank_c, tangent))
        (od_a, fc_a, fl_a, flc_a, tan_a), (od_b, fc_b, fl_b, flc_b, tan_b) = halves
        bottom = (0.0, tip_c[1] - tip_r)
        return od_a, od_b, [
            _arc(fc_a, root_r, od_a, fl_a),
            _arc(flc_a, flank_r, fl_a, tan_a),
            ('arc', tan_a, bottom, tan_b),
            _arc(flc_b, flank_r, tan_b, fl_b),
            _arc(fc_b, root_r, fl_b, od_b),
        ]

    # HTD
    r = spec['tooth_r'] + clearance
    by = od_r - (spec['depth'] - spec['tooth_r'])
    bottom = (0.0, by - r)
    cx = r + root_r
    cy2 = (od_r - root_r) ** 2 - cx * cx
    if cy2 > 0 and math.sqrt(cy2) > by:
        # Straight sides from the bottom arc's widest point up to the fillet.
        cy = math.sqrt(cy2)
        ox, oy = _unit(cx, cy)
        od_a = (ox * od_r, oy * od_r)
        od_b = (-od_a[0], od_a[1])
        return od_a, od_b, [
            _arc((cx, cy), root_r, od_a, (r, cy)),
            ('line', (r, cy), (r, by)),
            ('arc', (r, by), bottom, (-r, by)),
            ('line', (-r, by), (-r, cy)),
            _arc((-cx, cy), root_r, (-r, cy), od_b),
        ]
    # Small pulleys: the OD curves in before the bottom arc reaches its widest
    # point, so the fillet runs straight into the bottom arc.
    fc = _fillet_center((0.0, by), r, od_r, root_r)
    ux, uy = _unit(fc[0], fc[1] - by)
    on_bottom = (ux * r, by + uy * r)
    ox, oy = _unit(*fc)
    od_a = (ox * od_r, oy * od_r)
    od_b = (-od_a[0], od_a[1])
    mirror = lambda p: (-p[0], p[1])
    return od_a, od_b, [
        _arc(fc, root_r, od_a, on_bottom),
        ('arc', on_bottom, bottom, mirror(on_bottom)),
        _arc(mirror(fc), root_r, mirror(on_bottom), od_b),
    ]


def _rotate(pt, angle):
    c, s = math.cos(angle), math.sin(angle)
    return (pt[0] * c - pt[1] * s, pt[0] * s + pt[1] * c)


def outline(key, teeth, clearance):
    """Closed chain of Curve3D in the z=0 plane, centered on the origin."""
    spec = profile(key)
    if teeth < 6:
        raise PulleyError('A pulley needs at least 6 teeth.')
    od_r = outside_radius(spec, teeth)
    od_a, od_b, segments = _groove(spec, od_r, clearance)

    # The OD land between grooves has to exist, or the grooves overlap.
    step = 2 * math.pi / teeth
    span = math.atan2(od_b[1], od_b[0]) - math.atan2(od_a[1], od_a[0])
    if span >= step:
        raise PulleyError('Too few teeth for this profile and clearance.')

    curves = []
    for k in range(teeth):
        angle = step * k - math.pi / 2  # local +y axis to this tooth's direction
        for seg in segments:
            pts = [_rotate(p, angle) for p in seg[1:]]
            if seg[0] == 'line':
                curves.append(adsk.core.Line3D.create(_p(*pts[0]), _p(*pts[1])))
            else:
                curves.append(adsk.core.Arc3D.createByThreePoints(_p(*pts[0]), _p(*pts[1]), _p(*pts[2])))
        # OD land from this groove to the next one.
        start = _rotate(od_b, angle)
        mid = _rotate(od_b, angle + (step - span) / 2)
        end = _rotate(od_a, angle + step)
        curves.append(adsk.core.Arc3D.createByThreePoints(_p(*start), _p(*mid), _p(*end)))
    return curves


def outline_face(key, teeth, clearance):
    """Planar sheet body bounded by the pulley outline, z=0, centered on the origin."""
    tb = adsk.fusion.TemporaryBRepManager.get()
    wire, _ = tb.createWireFromCurves(outline(key, teeth, clearance), False)
    if wire is None:
        raise PulleyError('Could not build the pulley outline.')
    face = tb.createFaceFromPlanarWires([wire])
    if face is None:
        raise PulleyError('Could not build the pulley face.')
    return face
