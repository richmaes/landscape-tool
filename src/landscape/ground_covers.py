"""Textured ground covers: river rock and turf grass (Rich, 2026-09-25: "for
the big circle, add a river rock texture option and a turf grass option").

A ground-cover material's texture recipe (`style: river_rock` or
`style: turf` in materials.yaml) says how it looks:

  river_rock  `stone_in` (a typical stone's size, inches) and `variation`
              (stone-to-stone tone): rounded stones packed over the area,
              each its own size, turn and tone
  turf        `stripe_ft` (mowing stripe width, feet) and `variation`
              (how much lighter/darker the alternate stripes are)

Pure geometry and pixels, no drawing: the design canvas, the flat and art
renderers draw the stones and stripes from the same shapes here, and the 3D
view tiles a texture made here across the surface. Layouts are seeded from
the area's own shape, so a drawing looks the same every time and changes
only when the shape does.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry

STYLES = ("river_rock", "turf")
_INCHES_PER_UNIT = {"ft": 12.0, "in": 1.0, "yd": 36.0, "m": 1000 / 25.4}
_ELLIPSE_POINTS = 14


@dataclass(frozen=True)
class GroundSpec:
    kind: str  # "river_rock" or "turf"
    stone_size: float  # river rock: a typical stone, scene units
    stripe_width: float  # turf: one mowing stripe, scene units
    variation: float  # 0..1


def ground_spec(material, units: str = "ft") -> GroundSpec | None:
    """How `material` covers the ground, or None if it isn't a textured
    ground cover."""
    recipe = material.texture or {}
    kind = recipe.get("style")
    if kind not in STYLES:
        return None
    per_unit = _INCHES_PER_UNIT.get(units, 12.0)
    return GroundSpec(
        kind=kind,
        stone_size=float(recipe.get("stone_in", 4)) / per_unit,
        stripe_width=float(recipe.get("stripe_ft", 3)) * 12.0 / per_unit,
        variation=float(recipe.get("variation", 0.15)),
    )


# --- river rock --------------------------------------------------------------------------


def river_rocks(geom: BaseGeometry, spec: GroundSpec) -> list[tuple[Polygon, float]]:
    """Every stone over `geom`, with its tone in -1..1 (darker..lighter),
    cached: the canvas redraws on every edit, and the 24 ft circle is a few
    thousand stones. Keyed by the geometry's bytes."""
    return list(_cached_rocks(geom.wkb, spec.stone_size))


@lru_cache(maxsize=16)
def _cached_rocks(wkb: bytes, size: float) -> tuple[tuple[Polygon, float], ...]:
    region = shapely.from_wkb(wkb)
    if region.is_empty or size <= 0:
        return ()
    rng = np.random.default_rng(zlib.crc32(wkb))
    minx, miny, maxx, maxy = region.bounds
    # a jittered hex grid, one stone per cell, so stones pack without big gaps
    row = size * 0.8
    ys = np.arange(miny - row, maxy + row, row)
    centres = []
    for k, y in enumerate(ys):
        xs = np.arange(minx - size, maxx + size, size * 0.9) + (size * 0.45 if k % 2 else 0)
        centres.append(np.column_stack([xs, np.full_like(xs, y)]))
    pts = np.concatenate(centres)
    pts += rng.uniform(-0.18, 0.18, pts.shape) * size
    shapely.prepare(region)
    pts = pts[shapely.contains_xy(region, pts[:, 0], pts[:, 1])]
    n = len(pts)
    if n == 0:
        return ()
    scale = rng.uniform(0.7, 1.25, n)  # stones vary in size ...
    rx = 0.5 * size * scale * rng.uniform(0.85, 1.0, n)
    ry = rx * rng.uniform(0.6, 0.95, n)  # ... are oval ...
    turn = rng.uniform(0, math.pi, n)  # ... and lie every which way
    t = np.linspace(0, 2 * math.pi, _ELLIPSE_POINTS, endpoint=False)
    ex, ey = rx[:, None] * np.cos(t), ry[:, None] * np.sin(t)
    cos, sin = np.cos(turn)[:, None], np.sin(turn)[:, None]
    rings = np.stack([pts[:, :1] + ex * cos - ey * sin, pts[:, 1:] + ex * sin + ey * cos], axis=-1)
    stones = shapely.polygons(rings)
    inside = shapely.within(stones, region)
    stones[~inside] = shapely.intersection(stones[~inside], region)  # stones cut by the edge
    tones = rng.uniform(-1, 1, n)
    return tuple((s, float(tone)) for s, tone in zip(stones, tones)
                 if s.geom_type == "Polygon" and not s.is_empty and s.area > 1e-6)


# --- turf ----------------------------------------------------------------------------------


def turf_stripes(geom: BaseGeometry, spec: GroundSpec) -> list[Polygon]:
    """The darker of the two alternating mowing stripes, running north-south
    across `geom` (every other band of `stripe_width`)."""
    if geom.is_empty or spec.stripe_width <= 0:
        return []
    minx, miny, maxx, maxy = geom.bounds
    w = spec.stripe_width
    first = math.floor(minx / w) * w
    bands = [box(x, miny, x + w, maxy) for x in np.arange(first + w, maxx, 2 * w)]
    stripes = []
    for band in bands:
        part = band.intersection(geom)
        stripes += [p for p in getattr(part, "geoms", [part]) if p.geom_type == "Polygon" and not p.is_empty]
    return stripes


def turf_tufts(geom: BaseGeometry, spec: GroundSpec, spacing: float = 0.8) -> list[LineString]:
    """Little pencil tufts of grass for the art view: three short blades
    fanning up from a point, scattered over `geom` about `spacing` apart."""
    if geom.is_empty:
        return []
    rng = np.random.default_rng(zlib.crc32(geom.wkb))
    minx, miny, maxx, maxy = geom.bounds
    xs, ys = np.meshgrid(np.arange(minx, maxx, spacing), np.arange(miny, maxy, spacing))
    pts = np.column_stack([xs.ravel(), ys.ravel()]) + rng.uniform(-0.4, 0.4, (xs.size, 2)) * spacing
    inner = geom.buffer(-spacing * 0.15)
    if inner.is_empty:
        return []
    shapely.prepare(inner)
    pts = pts[shapely.contains_xy(inner, pts[:, 0], pts[:, 1])]
    blades = []
    for x, y in pts:
        h = spacing * rng.uniform(0.14, 0.22)
        for lean in (-0.5, 0.0, 0.5):
            blades.append(LineString([(x + lean * h * 0.3, y), (x + lean * h * 0.9, y + h * (1 - abs(lean) * 0.35))]))
    return blades


# --- 3D texture ------------------------------------------------------------------------------


@lru_cache(maxsize=8)
def ground_texture(spec: GroundSpec, color: str, px: int = 512) -> tuple[np.ndarray, float]:
    """An RGB texture of the ground cover that tiles seamlessly, and the
    size (scene units) one tile covers on the ground. Cached: the 3D view
    re-renders on every camera move."""
    base = np.array([int(color[i : i + 2], 16) for i in (1, 3, 5)], float)
    if spec.kind == "river_rock":
        return _rock_texture(spec, base, px), spec.stone_size * 8
    tile = 2 * spec.stripe_width if spec.stripe_width > 0 else 2.0
    return _turf_texture(spec, base, px), tile


def _rock_texture(spec: GroundSpec, base: np.ndarray, px: int) -> np.ndarray:
    """8 x 8 stones on a darker bed, each shaded lighter towards its top
    left so it reads as rounded; stones crossing an edge wrap round."""
    rng = np.random.default_rng(7)
    img = np.ones((px, px, 3)) * base * 0.45  # the shadowy gaps between stones
    cell = px / 8
    yy, xx = np.mgrid[0:px, 0:px].astype(float)
    for i in range(8):
        for j in range(8):
            cx = (j + 0.5 + (0.5 if i % 2 else 0) + rng.uniform(-0.15, 0.15)) * cell
            cy = (i + 0.5 + rng.uniform(-0.15, 0.15)) * cell
            rx = cell * rng.uniform(0.42, 0.58)
            ry = rx * rng.uniform(0.65, 0.95)
            turn = rng.uniform(0, math.pi)
            tone = base * (1 + spec.variation * rng.uniform(-1, 1))
            dx = (xx - cx + px / 2) % px - px / 2  # wrapped distance: the tile repeats seamlessly
            dy = (yy - cy + px / 2) % px - px / 2
            u = (dx * math.cos(turn) + dy * math.sin(turn)) / rx
            v = (-dx * math.sin(turn) + dy * math.cos(turn)) / ry
            d = u * u + v * v
            inside = d < 1
            shade = 1.08 - 0.18 * (dx + dy)[inside] / (rx + ry) - 0.12 * d[inside]  # lit from the top left
            img[inside] = tone * shade[:, None]
    return np.uint8(np.clip(img, 0, 255))


def _turf_texture(spec: GroundSpec, base: np.ndarray, px: int) -> np.ndarray:
    """Fine blade-by-blade noise, streaked along the mowing direction, with
    the right half one stripe darker."""
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 1, (px, px))
    streak = sum(np.roll(noise, k, axis=0) for k in range(-3, 4)) / math.sqrt(7)  # wraps: stays tileable
    img = base * (1 + 0.07 * streak[..., None] + 0.04 * noise[..., None])
    img[:, px // 2 :] *= 1 - spec.variation
    return np.uint8(np.clip(img, 0, 255))
