"""An object's editable size, and reshaping it — independently in width and
height, not just by the object's uniform `transform.scale`.

Sizes are the object's *own* dimensions (a rect's width x height, an
ellipse's two diameters, a polygon's extent in its own frame) times its
scale, so they read the same as the size shown while dragging the resize
handle and typing "10 ft" gives 10 ft. Reshaping rewrites the primitive's
own fields — a rect's `width`/`height`, an ellipse's `rx`/`ry`, a
polygon's `points` — and keeps the shape's centre where it was, so the
object grows or shrinks in place. Qt-free, like `editor_session.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .schema import (
    Circle,
    Ellipse,
    FenceLine,
    Keepout,
    Line,
    Polygon,
    Primitive,
    Rect,
    RegularPolygon,
    SceneObject,
    WavyPath,
    Walkway,
)

_POINT_KINDS = (Polygon, WavyPath, Walkway, FenceLine)


@dataclass
class Dimensions:
    width: float | None  # after the object's scale; None if that dimension can't be edited
    height: float | None
    diameter_only: bool = False  # one value: a circle's or regular polygon's diameter


def object_dimensions(obj: SceneObject) -> Dimensions | None:
    """The editable size of `obj`, or None if it can't be resized here (an
    instance of a shared `definitions` entry: its shape belongs to the
    definition, not the object)."""
    if obj.definition:
        return None
    raw = _primitive_dimensions(obj.primitive)
    if raw is None:
        return None
    s = obj.transform.scale
    return Dimensions(
        width=raw.width * s if raw.width else None,
        height=raw.height * s if raw.height else None,
        diameter_only=raw.diameter_only,
    )


def _primitive_dimensions(p: Primitive) -> Dimensions | None:
    if isinstance(p, Rect):
        return Dimensions(p.width, p.height)
    if isinstance(p, Ellipse):
        return Dimensions(2 * p.rx, 2 * p.ry)
    if isinstance(p, Circle):
        return Dimensions(2 * p.r, 2 * p.r, diameter_only=True)
    if isinstance(p, RegularPolygon):
        return Dimensions(2 * p.size, 2 * p.size, diameter_only=True)
    if isinstance(p, Keepout):
        return _primitive_dimensions(p.shape) if p.shape is not None else None
    points = _points(p)
    if points is not None:
        xs, ys = [x for x, _ in points], [y for _, y in points]
        return Dimensions(max(xs) - min(xs), max(ys) - min(ys))
    return None


def resized_primitive(obj: SceneObject, width: float | None = None, height: float | None = None) -> Primitive:
    """`obj`'s primitive reshaped to `width` and/or `height` (after its
    scale, like `object_dimensions`), centre unchanged. A dimension left
    as None keeps its current value. Raises ValueError if the object can't
    be resized, or a size isn't positive."""
    for value in (width, height):
        if value is not None and value <= 0:
            raise ValueError("a size must be greater than zero")
    if obj.definition:
        raise ValueError(f"'{obj.id}' takes its shape from definition '{obj.definition}'")
    s = obj.transform.scale
    w = width / s if width is not None else None
    h = height / s if height is not None else None
    return _resize(obj.primitive, w, h, obj.id)


def _resize(p: Primitive, w: float | None, h: float | None, object_id: str) -> Primitive:
    if isinstance(p, Rect):
        new_w, new_h = w if w is not None else p.width, h if h is not None else p.height
        cx, cy = p.x + p.width / 2, p.y + p.height / 2
        return replace(p, x=_num(cx - new_w / 2), y=_num(cy - new_h / 2), width=_num(new_w), height=_num(new_h))
    if isinstance(p, Ellipse):
        return replace(p, rx=_num(w / 2) if w is not None else p.rx, ry=_num(h / 2) if h is not None else p.ry)
    if isinstance(p, Circle):
        d = w if w is not None else h
        return replace(p, r=_num(d / 2)) if d is not None else p
    if isinstance(p, RegularPolygon):
        d = w if w is not None else h
        return replace(p, size=_num(d / 2)) if d is not None else p
    if isinstance(p, Keepout):
        return replace(p, shape=_resize(p.shape, w, h, object_id))
    points = _points(p)
    if points is None:
        raise ValueError(f"'{object_id}' ({p.kind}) can't be resized by its dimensions")
    xs, ys = [x for x, _ in points], [y for _, y in points]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    old_w, old_h = max(xs) - min(xs), max(ys) - min(ys)
    fx = w / old_w if (w is not None and old_w) else 1.0
    fy = h / old_h if (h is not None and old_h) else 1.0
    moved = [(_num(cx + (x - cx) * fx), _num(cy + (y - cy) * fy)) for x, y in points]
    if isinstance(p, Line):
        (x1, y1), (x2, y2) = moved
        return replace(p, x1=x1, y1=y1, x2=x2, y2=y2)
    return replace(p, points=moved)


def _points(p: Primitive) -> list[tuple[float, float]] | None:
    if isinstance(p, Line):
        return [(p.x1, p.y1), (p.x2, p.y2)]
    if isinstance(p, _POINT_KINDS) and p.points:
        return list(p.points)
    return None


def _num(value: float) -> float | int:
    """Rounded for the YAML: 3 decimals (about 1/100 in), whole numbers as
    integers so a hand-written `x: 2` doesn't come back as `2.0`."""
    value = round(value, 3)
    return int(value) if float(value).is_integer() else value
