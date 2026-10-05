"""Closed timing belt around two pulleys: center distance and belt solid.

Local frame: pulley 1 at the origin, pulley 2 at (C, 0), belt in the z=0
plane, extruded along +z. Dimensions in cm.

The belt is built on its pitch line, the path around both pitch circles
(N * pitch / (2 pi)) along the two outer tangents. Its length is

    L = 2 C cos(phi) + pi (r1 + r2) + 2 phi (r2 - r1),  sin(phi) = (r2 - r1) / C

and C is solved so L = belt teeth * pitch. The land (tooth root line) sits
PLD inside the pitch line, which puts it on each pulley's outside diameter,
and the back sits (height - tooth depth) outside the land.

Teeth are the pulley grooves at zero clearance, i.e. the belt tooth shape
the pulley grooves are made from, so belt and pulley match by construction.
On a pulley a tooth is built on that pulley's land circle; on a straight span
it is built on a land circle so large it is flat to 1e-6 cm. A tooth that
straddles a tangent point is built in the frame of the segment its center is
on, so its far edge is off the other segment's land by at most the arc's
sagitta over half a tooth (~0.05 mm on a small pulley), hidden by the union.
"""

import math

import adsk.core
import adsk.fusion

from ..lighten.geometry import prism
from ..pulley import profiles
from ..pulley.profiles import PulleyError

# Overall belt height (back to tooth tip), cm. Pfeifer Industries "Timing Belt
# Tooth Profiles and Pitches": 2MR/PGGT2 1.52 mm, 3MR/PGGT2 2.41 mm, 3M HTD
# 2.41 mm, 5M HTD 3.81 mm (SDP-SI 5M belts: 3.81 mm; SIT lists 3.6 mm).
# Only the back of the belt depends on it, not how it meshes.
HEIGHT = {'gt2_2': 0.152, 'gt2_3': 0.241, 'htd_3': 0.241, 'htd_5': 0.381}
FLAT_R = 1e4      # cm; land radius for teeth on a straight span
OVERLAP = 0.02    # cm; teeth reach this far into the band so the union is clean


def _tb():
    return adsk.fusion.TemporaryBRepManager.get()


def pitch_radius(spec, teeth):
    return teeth * spec['pitch'] / (2 * math.pi)


def _length(C, r1, r2):
    phi = math.asin((r2 - r1) / C)
    return 2 * C * math.cos(phi) + math.pi * (r1 + r2) + 2 * phi * (r2 - r1)


def center_distance(key, belt_teeth, t1, t2):
    """Center distance at which a belt of belt_teeth wraps both pulleys."""
    spec = profiles.profile(key)
    r1, r2 = pitch_radius(spec, t1), pitch_radius(spec, t2)
    L = belt_teeth * spec['pitch']
    # The pulleys (plus the belt's teeth between them) must not touch.
    lo = profiles.outside_radius(spec, t1) + profiles.outside_radius(spec, t2) + 2 * spec['depth']
    if _length(lo, r1, r2) >= L:
        raise PulleyError('Belt is too short for these pulleys.')
    hi = L / 2  # L >= 2C always
    # L grows monotonically with C (dL/dC = 2 cos(phi)), so bisect.
    for _ in range(80):
        mid = (lo + hi) / 2
        if _length(mid, r1, r2) < L:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def nearest_teeth(key, C, t1, t2):
    """The whole number of belt teeth whose center distance is closest to C."""
    spec = profiles.profile(key)
    r1, r2 = pitch_radius(spec, t1), pitch_radius(spec, t2)
    if C <= abs(r2 - r1):
        raise PulleyError('The pulleys are too close together for a belt.')
    exact = _length(C, r1, r2) / spec['pitch']
    best = None
    # Center distance grows with belt teeth, so the nearest is on one side or the other.
    for n in (math.floor(exact), math.ceil(exact)):
        try:
            gap = abs(center_distance(key, n, t1, t2) - C)
        except PulleyError:
            continue
        if best is None or gap < best[1]:
            best = (n, gap)
    if best is None:
        raise PulleyError('The pulleys are too close together for a belt.')
    return best[0]


def _path(C, r1, r2):
    """Pitch-line segments, counterclockwise from pulley 1's upper tangent point:
    ('arc', center, radius, start angle, end angle) or ('line', start, end)."""
    alpha = math.pi / 2 + math.asin((r2 - r1) / C)   # tangent-point normal angle
    o1, o2 = (0.0, 0.0), (C, 0.0)

    def at(o, r, a):
        return (o[0] + r * math.cos(a), o[1] + r * math.sin(a))

    return [
        ('arc', o1, r1, alpha, 2 * math.pi - alpha),
        ('line', at(o1, r1, -alpha), at(o2, r2, -alpha)),
        ('arc', o2, r2, -alpha, alpha),
        ('line', at(o2, r2, alpha), at(o1, r1, alpha)),
    ]


def _seg_length(seg):
    if seg[0] == 'arc':
        return seg[2] * (seg[4] - seg[3])
    return math.hypot(seg[2][0] - seg[1][0], seg[2][1] - seg[1][1])


def _loop(C, r1, r2, delta):
    """Closed wire of the pitch path offset outward by delta."""
    curves = []
    for seg in _path(C, r1 + delta, r2 + delta):
        if seg[0] == 'arc':
            _, o, r, a0, a1 = seg
            pts = [(o[0] + r * math.cos(a), o[1] + r * math.sin(a)) for a in (a0, (a0 + a1) / 2, a1)]
            curves.append(adsk.core.Arc3D.createByThreePoints(*[_p(*q) for q in pts]))
        else:
            curves.append(adsk.core.Line3D.create(_p(*seg[1]), _p(*seg[2])))
    wire, _ = _tb().createWireFromCurves(curves, False)
    if wire is None:
        raise PulleyError('Could not build the belt outline.')
    return wire


def _p(x, y):
    return adsk.core.Point3D.create(x, y, 0)


def _tooth(spec, land_r, place, normal_at):
    """Tooth sheet: the zero-clearance groove on a land circle of land_r,
    mapped to the belt by place(local point); closed through the band."""
    od_a, od_b, segments = profiles._groove(spec, land_r, 0.0)
    curves = []
    for seg in segments:
        pts = [_p(*place(q)) for q in seg[1:]]
        if seg[0] == 'line':
            curves.append(adsk.core.Line3D.create(*pts))
        else:
            curves.append(adsk.core.Arc3D.createByThreePoints(*pts))
    a, b = place(od_a), place(od_b)
    na, nb = normal_at(od_a), normal_at(od_b)
    a_out = (a[0] + na[0] * OVERLAP, a[1] + na[1] * OVERLAP)
    b_out = (b[0] + nb[0] * OVERLAP, b[1] + nb[1] * OVERLAP)
    for p, q in ((b, b_out), (b_out, a_out), (a_out, a)):
        curves.append(adsk.core.Line3D.create(_p(*p), _p(*q)))
    wire, _ = _tb().createWireFromCurves(curves, False)
    face = _tb().createFaceFromPlanarWires([wire]) if wire else None
    if face is None:
        raise PulleyError('Could not build a belt tooth.')
    return face


def _teeth(spec, C, r1, r2, n, phase):
    """Tooth sheets along the pitch path, one tooth per pitch. The first sits on
    pulley 1 at the groove angle (phase + k * step) nearest the middle of its wrap."""
    path = _path(C, r1, r2)
    lengths = [_seg_length(s) for s in path]
    L = sum(lengths)
    pld = spec['pld']
    step = 2 * math.pi / round(2 * math.pi * r1 / spec['pitch'])
    k = round((math.pi - phase) / step)
    first = phase + k * step
    s0 = r1 * (first - path[0][3])
    faces = []
    for j in range(n):
        s = (s0 + j * L / n) % L
        i = 0
        while i < 3 and s > lengths[i]:
            s -= lengths[i]
            i += 1
        seg = path[i]
        if seg[0] == 'arc':
            _, o, r, a0, _ = seg
            theta = a0 + s / r
            rot = theta - math.pi / 2  # local +y to the tooth's outward direction
            c, sn = math.cos(rot), math.sin(rot)

            def place(q, o=o, c=c, sn=sn):
                return (o[0] + q[0] * c - q[1] * sn, o[1] + q[0] * sn + q[1] * c)

            def normal_at(q, c=c, sn=sn):
                d = math.hypot(*q)
                ux, uy = q[0] / d, q[1] / d
                return (ux * c - uy * sn, ux * sn + uy * c)

            faces.append(_tooth(spec, r - pld, place, normal_at))
        else:
            _, a, b = seg
            L_seg = lengths[i]
            tx, ty = (b[0] - a[0]) / L_seg, (b[1] - a[1]) / L_seg
            nx, ny = ty, -tx  # outward: the loop runs counterclockwise
            fx, fy = a[0] + tx * s - nx * pld, a[1] + ty * s - ny * pld  # on the land

            def place(q, fx=fx, fy=fy, tx=tx, ty=ty, nx=nx, ny=ny):
                return (fx + q[0] * tx + (q[1] - FLAT_R) * nx, fy + q[0] * ty + (q[1] - FLAT_R) * ny)

            faces.append(_tooth(spec, FLAT_R, place, lambda q, nx=nx, ny=ny: (nx, ny)))
    return faces


def _union_all(faces):
    """Balanced pairwise union: far fewer edges per boolean than folding one
    growing sheet."""
    while len(faces) > 1:
        merged = []
        for i in range(0, len(faces) - 1, 2):
            if not _tb().booleanOperation(faces[i], faces[i + 1], adsk.fusion.BooleanTypes.UnionBooleanType):
                raise PulleyError('Could not combine the belt teeth.')
            merged.append(faces[i])
        if len(faces) % 2:
            merged.append(faces[-1])
        faces = merged
    return faces[0]


def build(o):
    """o: profile, belt_teeth, teeth1, teeth2, width, offset, phase (radians).
    Returns (solid, center distance)."""
    spec = profiles.profile(o['profile'])
    C = center_distance(o['profile'], o['belt_teeth'], o['teeth1'], o['teeth2'])
    r1, r2 = pitch_radius(spec, o['teeth1']), pitch_radius(spec, o['teeth2'])
    back = HEIGHT[o['profile']] - spec['depth'] - spec['pld']
    band = _tb().createFaceFromPlanarWires([_loop(C, r1, r2, back), _loop(C, r1, r2, -spec['pld'])])
    if band is None:
        raise PulleyError('Could not build the belt band.')
    sheet = _union_all([band] + _teeth(spec, C, r1, r2, o['belt_teeth'], o['phase']))
    solid = prism(sheet, adsk.core.Vector3D.create(0, 0, o['width']))
    if o['offset']:
        m = adsk.core.Matrix3D.create()
        m.translation = adsk.core.Vector3D.create(0, 0, o['offset'])
        _tb().transform(solid, m)
    return solid, C
