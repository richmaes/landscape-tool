"""Paver layouts: every individual brick of a paved area, as polygons.

Pure geometry, no drawing — the design canvas, the flat renderer and the
art renderer all draw joints (and, in art mode, per-brick tone) from the
same bricks. A field pattern is laid from the paved area's lower-left
corner so its joints line up with the area's edges, then clipped to it;
bricks cut by the edge come back cut, as they would be on site.

Patterns (for 2:1 pavers, e.g. the standard 8 x 4 in):
  herringbone_45  zig-zag laid diagonally to the edges
  herringbone_90  zig-zag square to the edges
  running_bond    rows offset by half a brick
  basketweave     pairs of bricks alternating direction, in squares
  sailor          one course of bricks laid lengthwise around a ring-shaped
                  area (the border around the sand circle)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import split

PATTERNS = ("herringbone_45", "herringbone_90", "running_bond", "basketweave", "sailor")
DEFAULT_PATTERN = "herringbone_45"
PATTERN_LABELS = {
    "herringbone_45": "Herringbone 45°",
    "herringbone_90": "Herringbone 90°",
    "running_bond": "Running bond",
    "basketweave": "Basketweave",
    "sailor": "Sailor course (border)",
}
_INCHES_PER_UNIT = {"ft": 12.0, "in": 1.0, "yd": 36.0, "m": 1000 / 25.4}


@dataclass
class PaverSpec:
    pattern: str
    length: float  # scene units
    width: float
    variation: float  # brick-to-brick tone variation, 0..1


def paver_spec(material, pattern_override: str | None, units: str) -> PaverSpec | None:
    """How to lay `material` (None if it isn't a paver): its texture
    recipe's brick size (inches) in scene units, and the object's own
    `pattern` if it chose one, else the material's default."""
    recipe = material.texture or {}
    if recipe.get("style") != "pavers":
        return None
    length_in, width_in = recipe.get("brick", [8, 4])
    per_unit = _INCHES_PER_UNIT.get(units, 12.0)
    return PaverSpec(
        pattern=pattern_override or recipe.get("pattern", DEFAULT_PATTERN),
        length=float(length_in) / per_unit,
        width=float(width_in) / per_unit,
        variation=float(recipe.get("variation", 0.05)),
    )


def bricks_for(geom: BaseGeometry, spec: PaverSpec) -> list[Polygon]:
    """`paver_bricks` for a drawn object, cached: the canvas redraws on
    every edit, and a 36 ft herringbone patio is ~6,000 bricks. Keyed by
    the geometry's bytes, so any change to the shape re-lays it."""
    return list(_cached_bricks(geom.wkb, spec.pattern, spec.length, spec.width))


@lru_cache(maxsize=32)
def _cached_bricks(wkb: bytes, pattern: str, length: float, width: float) -> tuple[Polygon, ...]:
    return tuple(paver_bricks(shapely.from_wkb(wkb), pattern, length, width))


def paver_bricks(region: BaseGeometry, pattern: str, length: float, width: float) -> list[Polygon]:
    """Every brick of `region` in `pattern`, for pavers `length` x `width`
    (scene units), clipped to the region."""
    if pattern not in PATTERNS:
        raise ValueError(f"unknown paver pattern '{pattern}' (use one of: {', '.join(PATTERNS)})")
    if region.is_empty:
        return []
    if pattern == "sailor":
        return _sailor(region, length, width)
    angle = 45.0 if pattern == "herringbone_45" else 0.0
    minx, miny, _, _ = region.bounds
    return _field(region, pattern, length, width, (minx, miny), angle)


# --- field patterns ---------------------------------------------------------------


def _field(region, pattern, length, width, origin, angle_deg) -> list[Polygon]:
    """Lay the pattern in its own frame (origin at the region's corner,
    rotated by `angle_deg`), clip, and bring the bricks back."""
    ox, oy = origin
    theta = math.radians(angle_deg)
    c, s = math.cos(theta), math.sin(theta)

    def to_local(pts):
        d = pts - (ox, oy)
        return np.column_stack([d[:, 0] * c + d[:, 1] * s, -d[:, 0] * s + d[:, 1] * c])

    def to_world(pts):
        return np.column_stack([pts[:, 0] * c - pts[:, 1] * s + ox, pts[:, 0] * s + pts[:, 1] * c + oy])

    local = shapely.transform(region, to_local)
    x0, y0, x1, y1 = local.bounds
    rects = _LAYOUTS[pattern](x0, y0, x1, y1, length, width)  # (n, 4): minx, miny, maxx, maxy
    bricks = shapely.box(rects[:, 0], rects[:, 1], rects[:, 2], rects[:, 3])
    bricks = bricks[shapely.intersects(bricks, local)]
    inside = shapely.within(bricks, local)
    clipped = np.where(inside, bricks, shapely.intersection(bricks, local))
    world = shapely.transform(clipped, to_world)
    return _polygons(world)


def _herringbone(x0, y0, x1, y1, length, width) -> np.ndarray:
    """A staircase of flat bricks, each followed by an upright one set
    `length` across and `width - length` up; staircases repeat along
    (width, width) and across along (length, -length)."""
    # a brick origin is i*(W, W) + j*(L, -L): solve the bbox corners for i, j
    corners = [(x0, y0), (x0, y1), (x1, y0), (x1, y1)]
    i_vals = [(x + y) / (2 * width) for x, y in corners]
    j_vals = [(x - y) / (2 * length) for x, y in corners]
    i = np.arange(math.floor(min(i_vals)) - 3, math.ceil(max(i_vals)) + 3)
    j = np.arange(math.floor(min(j_vals)) - 3, math.ceil(max(j_vals)) + 3)
    ii, jj = np.meshgrid(i, j)
    bx = (ii * width + jj * length).ravel()
    by = (ii * width - jj * length).ravel()
    flat = np.column_stack([bx, by, bx + length, by + width])
    ux, uy = bx + length, by + width - length
    upright = np.column_stack([ux, uy, ux + width, uy + length])
    return np.vstack([flat, upright])


def _running_bond(x0, y0, x1, y1, length, width) -> np.ndarray:
    rows = np.arange(math.floor(y0 / width) - 1, math.ceil(y1 / width) + 1)
    cols = np.arange(math.floor(x0 / length) - 2, math.ceil(x1 / length) + 2)
    rr, cc = np.meshgrid(rows, cols)
    bx = (cc * length + (rr % 2) * length / 2).ravel()
    by = (rr * width).ravel()
    return np.column_stack([bx, by, bx + length, by + width])


def _basketweave(x0, y0, x1, y1, length, width) -> np.ndarray:
    """Squares of `length` x `length`, each holding bricks side by side —
    lying flat in one square, standing in the next, like a checkerboard."""
    per_block = max(1, round(length / width))
    rows = np.arange(math.floor(y0 / length) - 1, math.ceil(y1 / length) + 1)
    cols = np.arange(math.floor(x0 / length) - 1, math.ceil(x1 / length) + 1)
    out = []
    for r in rows:
        for c in cols:
            bx, by = c * length, r * length
            for k in range(per_block):
                if (r + c) % 2 == 0:
                    out.append((bx, by + k * width, bx + length, by + (k + 1) * width))
                else:
                    out.append((bx + k * width, by, bx + (k + 1) * width, by + length))
    return np.array(out, float)


_LAYOUTS = {
    "herringbone_45": _herringbone,
    "herringbone_90": _herringbone,
    "running_bond": _running_bond,
    "basketweave": _basketweave,
}


# --- border course --------------------------------------------------------------


def _sailor(region, length, width) -> list[Polygon]:
    """One course of bricks laid lengthwise around a ring-shaped area:
    joints across the ring every brick length, measured along its middle,
    then the ring split along them."""
    bricks: list[Polygon] = []
    for part in getattr(region, "geoms", [region]):
        if part.geom_type != "Polygon" or not part.interiors:
            raise ValueError("the sailor pattern needs a ring-shaped area (a shape with a hole)")
        outer, inner = part.exterior, max(part.interiors, key=lambda r: Polygon(r).area)
        mid_length = (outer.length + inner.length) / 2
        count = max(3, round(mid_length / length))
        joints = []
        for k in range(count):
            p = outer.interpolate(k / count, normalized=True)
            q = inner.interpolate(inner.project(p))
            dx, dy = q.x - p.x, q.y - p.y
            reach = math.hypot(dx, dy) or width
            ux, uy = dx / reach, dy / reach
            joints.append(LineString([(p.x - ux * width, p.y - uy * width), (q.x + ux * width, q.y + uy * width)]))
        bricks.extend(_polygons(list(split(part, MultiLineString(joints)).geoms)))
    return bricks


def _polygons(geoms) -> list[Polygon]:
    out = []
    for g in geoms:
        if g is None or g.is_empty:
            continue
        for part in getattr(g, "geoms", [g]):
            if part.geom_type == "Polygon" and part.area > 1e-9:
                out.append(part)
    return out
