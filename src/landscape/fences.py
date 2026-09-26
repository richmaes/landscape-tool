"""Fences with character: white vinyl slats or cedar boards, and posts
every 8 ft (Rich, 2026-09-25).

A fence material's texture recipe (`style: fence` in materials.yaml) gives
the boards (`vinyl` or `cedar`), their width and gap (inches), and the post
spacing (feet) and size (inches). Pure geometry here, no drawing: the plan
views draw the posts as small squares, the 3D view builds a textured panel
between taller posts, all from these helpers.

A fence's line is found from its shape — a thin rect (the back fence) or a
buffered `fence_line` — as the centre line along its long side, so it
follows moves, turns and relations like any other object. (A fence with
bends is treated as one straight run along its overall long side.)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely import affinity

_INCHES_PER_UNIT = {"ft": 12.0, "in": 1.0, "yd": 36.0, "m": 1000 / 25.4}


@dataclass
class FenceSpec:
    boards: str  # "vinyl" or "cedar": how the 3D panel is textured
    slat_width: float  # scene units
    gap: float
    post_spacing: float
    post_size: float


def fence_spec(material, units: str = "ft") -> FenceSpec | None:
    """How to build a fence of `material`, or None if it isn't a fence
    material with a recipe."""
    recipe = material.texture or {}
    if recipe.get("style") != "fence":
        return None
    per_unit = _INCHES_PER_UNIT.get(units, 12.0)
    feet_per_unit = per_unit / 12.0
    return FenceSpec(
        boards=recipe.get("boards", "vinyl"),
        slat_width=float(recipe.get("slat_width_in", 6)) / per_unit,
        gap=float(recipe.get("gap_in", 0.25)) / per_unit,
        post_spacing=float(recipe.get("post_spacing", 8)) / feet_per_unit,
        post_size=float(recipe.get("post_size_in", 5)) / per_unit,
    )


def fence_centerline(geom: BaseGeometry) -> LineString:
    """The line down the middle of a fence's shape, along its long side."""
    import shapely

    with np.errstate(divide="ignore", invalid="ignore"):  # Shapely's own harmless noise on axis-aligned edges
        rect = shapely.minimum_rotated_rectangle(geom)
    corners = np.asarray(rect.exterior.coords)[:4]
    sides = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    lengths = [np.hypot(*(b - a)) for a, b in sides]
    short = int(np.argmin(lengths))  # the two short ends are sides `short` and `short + 2`
    a0, a1 = sides[short]
    b0, b1 = sides[(short + 2) % 4]
    return LineString([(a0 + a1) / 2, (b0 + b1) / 2])


def fence_posts(line: LineString, spacing: float, size: float) -> list[Polygon]:
    """Square posts every `spacing` along `line` from its start, plus one at
    the end (so the last bay may be shorter, as built)."""
    length = line.length
    stations = list(np.arange(0.0, length, spacing)) if spacing > 0 else [0.0]
    if not stations or length - stations[-1] > 1e-6:
        stations.append(length)
    (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
    angle = math.degrees(math.atan2(y1 - y0, x1 - x0))
    posts = []
    for s in stations:
        p = line.interpolate(s)
        square = box(p.x - size / 2, p.y - size / 2, p.x + size / 2, p.y + size / 2)
        posts.append(affinity.rotate(square, angle, origin=(p.x, p.y)))
    return posts


def board_texture(spec: FenceSpec, color: str, px: int = 256) -> np.ndarray:
    """An RGB texture of the fence's boards, one texture width = 4 boards
    (plus gaps), to be tiled along the fence: crisp white vinyl slats with
    fine shadow lines, or cedar boards with grain and darker seams."""
    rng = np.random.default_rng(11 if spec.boards == "vinyl" else 5)
    base = np.array([int(color[i : i + 2], 16) for i in (1, 3, 5)], float)
    img = np.ones((px, px, 3)) * base
    board_px = px / 4
    gap_px = max(2, int(round(board_px * spec.gap / (spec.slat_width + spec.gap))))
    for k in range(4):
        start = int(k * board_px)
        end = int((k + 1) * board_px)
        if spec.boards == "cedar":
            img[:, start:end] *= rng.uniform(0.85, 1.12)  # each board its own tone
            grain = rng.normal(0, 1, end - start)  # streaks running up the board
            img[:, start:end] *= (1 + 0.05 * grain)[None, :, None]
            shade = 0.45
        else:
            img[:, start : start + 3] *= 0.93  # a soft highlight/shadow on each slat's edge
            shade = 0.62
        img[:, start : start + gap_px] = base * shade  # the gap between boards
    return np.uint8(np.clip(img, 0, 255))
