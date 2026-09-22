"""Geometry engine (M3): scene document to resolved shapely geometry.

`resolve_scene` walks a `SceneDocument` in its `resolution_order` (computed
by `scene_io` during validation) and produces a `ResolvedScene` — one
shapely geometry per object, with every relation, boolean op, and
object-level transform already applied. Nothing here mutates the source
document; resolution is a pure function of the scene, so the same scene and
seed always produce the same geometry (see `test_determinism.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians, sin

import numpy as np
from opensimplex import OpenSimplex
from scipy.interpolate import splev, splprep
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .schema import (
    Circle,
    Ellipse,
    FenceLine,
    Keepout,
    Line,
    Polygon as PolygonPrimitive,
    Primitive,
    Rect,
    RegularPolygon,
    SceneDocument,
    SceneObject,
    Transform,
    WavyPath,
    Walkway,
)


class GeometryError(Exception):
    """Raised when a primitive or relation cannot be resolved to geometry
    (as opposed to `SchemaError`, which is a malformed document)."""


# Circles/ellipses are polygon-approximated (shapely has no true curve type).
# The default buffer resolution (8 segments/quadrant, a 32-gon) is visibly
# coarse and not accurate enough for M3b's clearance rules, which need to
# reproduce real-plan distances to within a hundredth of a foot.
_CURVE_RESOLUTION = 32


# ---------------------------------------------------------------------------
# Resolved scene
# ---------------------------------------------------------------------------


@dataclass
class ResolvedObject:
    id: str
    geometry: BaseGeometry
    material: str | None
    layer: str
    z: int
    annotation: bool
    rule: str | None = None  # set for keepout objects


@dataclass
class ResolvedScene:
    objects: list[ResolvedObject]

    def get(self, object_id: str) -> ResolvedObject:
        for obj in self.objects:
            if obj.id == object_id:
                return obj
        raise GeometryError(f"no resolved object with id '{object_id}'")

    def paint_order(self) -> list[ResolvedObject]:
        """Objects in the order they should be painted: ascending z, then
        id as a stable tie-break. Later entries paint over earlier ones."""
        return sorted(self.objects, key=lambda o: (o.z, o.id))

    def bounds(self) -> tuple[float, float, float, float]:
        """(minx, miny, maxx, maxy) over every object, annotations included."""
        if not self.objects:
            return (0.0, 0.0, 0.0, 0.0)
        return unary_union([o.geometry for o in self.objects]).bounds

    def crop(self, x: float, y: float, width: float, height: float) -> "ResolvedScene":
        """Clip every object's geometry to an explicit window. Objects
        that fall entirely outside the window are dropped."""
        window = Polygon.from_bounds(x, y, x + width, y + height)
        cropped = []
        for obj in self.objects:
            clipped = obj.geometry.intersection(window)
            if not clipped.is_empty:
                cropped.append(
                    ResolvedObject(
                        id=obj.id,
                        geometry=clipped,
                        material=obj.material,
                        layer=obj.layer,
                        z=obj.z,
                        annotation=obj.annotation,
                        rule=obj.rule,
                    )
                )
        return ResolvedScene(objects=cropped)


def resolve_scene(doc: SceneDocument) -> ResolvedScene:
    raw_geometry: dict[str, BaseGeometry] = {}
    rules: dict[str, str | None] = {}

    order = doc.resolution_order or [obj.id for obj in doc.objects]
    by_id = {obj.id: obj for obj in doc.objects}

    for object_id in order:
        obj = by_id[object_id]
        geom, rule = _resolve_object_geometry(obj, raw_geometry)
        geom = _apply_transform(geom, obj.transform)
        raw_geometry[object_id] = geom
        rules[object_id] = rule

    resolved = [
        ResolvedObject(
            id=obj.id,
            geometry=raw_geometry[obj.id],
            material=obj.material,
            layer=obj.layer,
            z=obj.z,
            annotation=obj.annotation,
            rule=rules[obj.id],
        )
        for obj in doc.objects
    ]
    return ResolvedScene(objects=resolved)


def _resolve_object_geometry(
    obj: SceneObject, resolved: dict[str, BaseGeometry]
) -> tuple[BaseGeometry, str | None]:
    primitive = obj.primitive
    rule = primitive.rule if isinstance(primitive, Keepout) else None

    if obj.relation is not None:
        geom = _apply_relation(obj, primitive, resolved)
    else:
        geom = primitive_to_geometry(primitive)

    if obj.boolean is not None:
        geom = _apply_boolean(geom, obj.boolean, resolved)

    return geom, rule


# ---------------------------------------------------------------------------
# Primitive -> raw geometry (no relation, no object-level transform)
# ---------------------------------------------------------------------------


def primitive_to_geometry(primitive: Primitive) -> BaseGeometry:
    if isinstance(primitive, Circle):
        return Point(primitive.cx, primitive.cy).buffer(primitive.r, quad_segs=_CURVE_RESOLUTION)
    if isinstance(primitive, Ellipse):
        circle = Point(primitive.cx, primitive.cy).buffer(1.0, quad_segs=_CURVE_RESOLUTION)
        return affinity.scale(circle, xfact=primitive.rx, yfact=primitive.ry, origin=(primitive.cx, primitive.cy))
    if isinstance(primitive, Rect):
        return _rect_geometry(primitive)
    if isinstance(primitive, PolygonPrimitive):
        return Polygon(primitive.points)
    if isinstance(primitive, RegularPolygon):
        return _regular_polygon_geometry(primitive)
    if isinstance(primitive, Line):
        return LineString([(primitive.x1, primitive.y1), (primitive.x2, primitive.y2)])
    if isinstance(primitive, FenceLine):
        return LineString(primitive.points).buffer(primitive.post_size / 2, cap_style="flat")
    if isinstance(primitive, WavyPath):
        return _wavy_path_geometry(primitive)
    if isinstance(primitive, Walkway):
        return LineString(primitive.points).buffer(primitive.width / 2, cap_style="flat")
    if isinstance(primitive, Keepout):
        if primitive.shape is None:
            raise GeometryError("keepout has no shape to resolve")
        return primitive_to_geometry(primitive.shape)
    raise GeometryError(f"no geometry resolver for primitive kind '{getattr(primitive, 'kind', type(primitive))}'")


def _rect_geometry(rect: Rect) -> BaseGeometry:
    x, y, w, h, r = rect.x, rect.y, rect.width, rect.height, rect.corner_r
    if r <= 0:
        geom: BaseGeometry = Polygon([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
    else:
        r = min(r, w / 2, h / 2)
        inset = Polygon(
            [(x + r, y + r), (x + w - r, y + r), (x + w - r, y + h - r), (x + r, y + h - r)]
        )
        geom = inset.buffer(r, join_style="round", quad_segs=16)
    if rect.rotation:
        geom = affinity.rotate(geom, rect.rotation, origin=(x + w / 2, y + h / 2))
    return geom


def _regular_polygon_geometry(rp: RegularPolygon) -> BaseGeometry:
    """`size` is the circumradius (center-to-vertex distance)."""
    if rp.sides < 3:
        raise GeometryError(f"regular_polygon needs at least 3 sides, got {rp.sides}")
    points = []
    for i in range(rp.sides):
        angle = radians(rp.rotation) + 2 * np.pi * i / rp.sides
        points.append((rp.cx + rp.size * cos(angle), rp.cy + rp.size * sin(angle)))
    return Polygon(points)


def _wavy_path_geometry(wp: WavyPath) -> BaseGeometry:
    """Fit a spline through the control points, sample it densely, then
    perturb each sample along its local normal by opensimplex noise.
    `waviness` in [0, 1] maps linearly to amplitude as a fraction of
    `wavelength`; deterministic per `seed`."""

    if len(wp.points) < 2:
        raise GeometryError("wavy_path needs at least 2 control points")

    points = list(wp.points)
    if wp.closed and points[0] != points[-1]:
        points = points + [points[0]]

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    degree = min(3, len(points) - 1)
    tck, _ = splprep([xs, ys], s=0, k=degree, per=wp.closed)

    samples_per_segment = 24
    n_samples = max(len(points) * samples_per_segment, 64)
    u = np.linspace(0, 1, n_samples, endpoint=not wp.closed)
    spline_x, spline_y = splev(u, tck)

    amplitude = wp.waviness * wp.wavelength * 0.5
    noise = OpenSimplex(seed=wp.seed)

    du = 1.0 / n_samples
    perturbed = []
    for i in range(n_samples):
        dx = (splev(min(u[i] + du, 1.0), tck)[0] - splev(max(u[i] - du, 0.0), tck)[0])
        dy = (splev(min(u[i] + du, 1.0), tck)[1] - splev(max(u[i] - du, 0.0), tck)[1])
        length = (dx**2 + dy**2) ** 0.5
        if length == 0:
            nx, ny = 0.0, 0.0
        else:
            nx, ny = -dy / length, dx / length  # unit normal

        n = noise.noise2(u[i] * wp.wavelength * 4, wp.seed * 0.0001)
        offset = n * amplitude
        perturbed.append((spline_x[i] + nx * offset, spline_y[i] + ny * offset))

    if wp.closed:
        return Polygon(perturbed)
    return LineString(perturbed)


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------


def _anchor(primitive: Primitive) -> tuple[float, float]:
    """The point a `relative_to` offset is measured from — the primitive's
    own defining origin, not its centroid."""
    if isinstance(primitive, Rect):
        return (primitive.x, primitive.y)
    if isinstance(primitive, (Circle, Ellipse, RegularPolygon)):
        return (primitive.cx, primitive.cy)
    if isinstance(primitive, Line):
        return (primitive.x1, primitive.y1)
    if isinstance(primitive, (PolygonPrimitive, FenceLine, WavyPath, Walkway)):
        if not primitive.points:
            raise GeometryError("primitive has no points to anchor on")
        return tuple(primitive.points[0])
    raise GeometryError(f"no anchor defined for primitive {primitive}")


def _apply_relation(
    obj: SceneObject, primitive: Primitive, resolved: dict[str, BaseGeometry]
) -> BaseGeometry:
    relation = obj.relation
    if relation.ref not in resolved:
        raise GeometryError(
            f"'{obj.id}' relation references '{relation.ref}', which hasn't been resolved yet "
            "(resolution_order is out of date with the document)"
        )
    target = resolved[relation.ref]

    kind = type(relation).__name__
    if kind == "CenterOf":
        own = primitive_to_geometry(primitive)
        tc, oc = target.centroid, own.centroid
        return affinity.translate(own, xoff=tc.x - oc.x, yoff=tc.y - oc.y)

    if kind == "MirrorOf":
        if relation.about_x is not None:
            return affinity.scale(target, xfact=-1, yfact=1, origin=(relation.about_x, 0))
        return affinity.scale(target, xfact=1, yfact=-1, origin=(0, relation.about_y))

    if kind == "RelativeTo":
        own = primitive_to_geometry(primitive)
        ax, ay = _anchor(primitive)
        tx, ty = target.centroid.x, target.centroid.y
        return affinity.translate(own, xoff=(tx + relation.dx) - ax, yoff=(ty + relation.dy) - ay)

    if kind == "ChordOf":
        return _chord_geometry(primitive, target, relation.offset, relation.angle_deg)

    raise GeometryError(f"unhandled relation kind '{kind}'")  # pragma: no cover


def _chord_geometry(primitive: Primitive, target: BaseGeometry, offset: float, angle_deg: float) -> BaseGeometry:
    """A line/fence spanning the chord of `target` at perpendicular
    distance `offset` from its centroid, in the direction `angle_deg`
    (0 = horizontal chord, offset south is negative)."""

    center = target.centroid
    angle = radians(angle_deg)
    normal = (sin(angle), cos(angle))  # perpendicular to the chord direction
    along = (cos(angle), -sin(angle))

    chord_point = (center.x + normal[0] * offset, center.y + normal[1] * offset)
    reach = max(target.bounds[2] - target.bounds[0], target.bounds[3] - target.bounds[1])
    p1 = (chord_point[0] - along[0] * reach, chord_point[1] - along[1] * reach)
    p2 = (chord_point[0] + along[0] * reach, chord_point[1] + along[1] * reach)
    long_line = LineString([p1, p2])

    chord = long_line.intersection(target.boundary)
    endpoints = _line_endpoints(chord)
    if endpoints is None:
        raise GeometryError("chord_of: target boundary does not cross the offset line")

    if isinstance(primitive, FenceLine):
        return LineString(endpoints).buffer(primitive.post_size / 2, cap_style="flat")
    return LineString(endpoints)


def _line_endpoints(geom: BaseGeometry) -> tuple[tuple[float, float], tuple[float, float]] | None:
    if geom.geom_type == "MultiPoint" and len(geom.geoms) >= 2:
        pts = [(p.x, p.y) for p in geom.geoms]
        return (pts[0], pts[-1])
    if geom.geom_type in ("Point",):
        return None
    coords = list(getattr(geom, "coords", []))
    if len(coords) >= 2:
        return (coords[0], coords[-1])
    return None


# ---------------------------------------------------------------------------
# Boolean ops
# ---------------------------------------------------------------------------


def _apply_boolean(geom: BaseGeometry, boolean, resolved: dict[str, BaseGeometry]) -> BaseGeometry:
    for target_id in boolean.targets:
        if target_id not in resolved:
            raise GeometryError(
                f"boolean op references '{target_id}', which hasn't been resolved yet"
            )
        target = resolved[target_id]
        if boolean.op == "union":
            geom = geom.union(target)
        elif boolean.op == "difference":
            geom = geom.difference(target)
        elif boolean.op == "intersection":
            geom = geom.intersection(target)
        else:  # pragma: no cover - validated in schema.BooleanOp
            raise GeometryError(f"unknown boolean op '{boolean.op}'")
    return geom


# ---------------------------------------------------------------------------
# Object-level transform
# ---------------------------------------------------------------------------


def _apply_transform(geom: BaseGeometry, transform: Transform) -> BaseGeometry:
    if transform.scale != 1.0:
        geom = affinity.scale(geom, xfact=transform.scale, yfact=transform.scale, origin="centroid")
    if transform.rotation:
        geom = affinity.rotate(geom, transform.rotation, origin="centroid")
    if transform.tx or transform.ty:
        geom = affinity.translate(geom, xoff=transform.tx, yoff=transform.ty)
    return geom
