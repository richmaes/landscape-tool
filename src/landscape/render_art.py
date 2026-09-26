"""Hand-drawn pastel art renderer (M6): the scene as a watercolor-and-pencil
drawing — Rich's north star is "simulate watercolor pastel drawings."

A raster pipeline, because the effects that make watercolor read as
watercolor are inherently per-pixel: soft bleeding edges, pigment pooling
at a wash's rim, granulation, paper grain showing through. It works on a
float RGB canvas (paper white = 1.0) and composites every layer with a
*multiply* blend, the way transparent pigment actually behaves: a wash
over a wash deepens rather than covering.

Order, bottom to top:
  1. paper tone
  2. soft drop shadows under structures
  3. a watercolor wash per object, in paint order
  4. pencil textures per material recipe (hatch, stipple, ripple)
  5. wobbly pencil outlines
  6. paper grain over everything

Every size is in scene units (feet) or inches and converted with the
render's own pixels-per-unit, so the look is the same at any DPI; every
random choice comes from `ArtStyle.seed`, so a scene reproduces exactly.
Texture recipes come from each material's `texture:` entry in
`assets/materials.yaml` (`style: hatch | stipple | ripple | none`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cairo
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
from shapely import affinity
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry

from .geometry import ResolvedObject, ResolvedScene
from .materials import Material, MaterialLibrary, _hex_to_rgb
from .render_flat import iter_paint_order_with_material
from .schema import SceneDocument

_FALLBACK_ID = "__fallback__"


@dataclass
class ArtStyle:
    """Knobs for the look. Lengths are in scene units (feet) unless named
    `_in` (inches on paper, for things like pencil width that should look
    the same whatever the scene's scale)."""

    seed: int = 7
    wash: str = "diffuse"  # "diffuse" (soft, blurred, pooled edges) or "layered" (many hard translucent glazes)
    paper_color: str = "#F8F3E6"
    pencil_color: str = "#3A3833"
    wobble: float = 0.07  # how far edges wander from the true outline
    wash_layers: int = 4
    wash_strength: float = 0.8
    edge_pooling: float = 0.45  # pigment darkening at a wash's rim
    granulation: float = 0.16
    variation: float = 0.14  # large, soft unevenness across a wash
    lift_overlap: float = 0.04  # lower washes show through this far inside an upper object's edge
    pencil_width_in: float = 0.007
    pencil: float = 0.65  # overall weight of every pencil mark (outlines, hatching, ripples, stipple); 1.0 = heavy
    grain: float = 0.07
    shadow_layers: tuple[str, ...] = ("structures",)
    # A real paper/canvas scan (PNG/JPEG) to paint on instead of the
    # procedural paper, tiled at `paper_image_width_in` inches wide per
    # tile so its texture keeps its true size at any DPI.
    paper_image: str | None = None
    paper_image_width_in: float = 6.0
    extras: dict = field(default_factory=dict)


class _Noise:
    """Smooth, seeded 2D displacement from a handful of random sinusoids —
    cheap, vectorised, and deterministic, which is all edge wobble needs."""

    def __init__(self, rng: np.random.Generator, wavelengths: tuple[float, ...]):
        n = len(wavelengths)
        angles = rng.uniform(0, 2 * math.pi, size=(2, n))
        self.k = np.stack([np.cos(angles), np.sin(angles)], axis=-1) * (2 * math.pi / np.array(wavelengths))[None, :, None]
        self.phase = rng.uniform(0, 2 * math.pi, size=(2, n))
        self.norm = 1 / math.sqrt(n / 2)

    def displace(self, pts: np.ndarray, amplitude: float) -> np.ndarray:
        out = pts.copy()
        for axis in (0, 1):
            arg = pts @ self.k[axis].T + self.phase[axis]
            out[:, axis] += amplitude * self.norm * np.sin(arg).sum(axis=1)
        return out


def _wobble(geom: BaseGeometry, noise: _Noise, amplitude: float, step: float) -> BaseGeometry:
    """Densify, then push every vertex along a smooth noise field. Rings
    are re-closed explicitly: vectorised maths can give a ring's first and
    last point (the same coordinates) results that differ in the last bit,
    which GEOS rejects as an unclosed ring."""
    import shapely
    from shapely.geometry import LinearRing, MultiPolygon, Polygon

    def ring(coords) -> list:
        pts = noise.displace(np.asarray(coords)[:-1], amplitude)
        return [*map(tuple, pts), tuple(pts[0])]

    def polygon(poly: Polygon) -> Polygon:
        return Polygon(ring(poly.exterior.coords), [ring(r.coords) for r in poly.interiors])

    dense = shapely.segmentize(geom, step)
    if dense.geom_type == "Polygon":
        return polygon(dense)
    if dense.geom_type == "MultiPolygon":
        return MultiPolygon([polygon(p) for p in dense.geoms])
    if dense.geom_type == "LinearRing":
        return LinearRing(ring(dense.coords))
    if hasattr(dense, "geoms"):
        return type(dense)([_wobble(part, noise, amplitude, step) for part in dense.geoms])
    return shapely.transform(dense, lambda pts: noise.displace(pts, amplitude))


class _Canvas:
    """A float RGB page plus the raster helpers every layer shares."""

    def __init__(self, doc: SceneDocument, dpi: float, style: "ArtStyle"):
        self.ppu = doc.scale / 72.0 * dpi  # pixels per scene unit
        self.units_per_inch = 72.0 / doc.scale  # scene units per inch of paper
        self.page_height = doc.page_height
        self.w = round(doc.page_width * self.ppu)
        self.h = round(doc.page_height * self.ppu)
        # The bare paper, kept separately so `lift` can restore it exactly —
        # a scan's own texture included, not just a flat tone.
        if style.paper_image:
            self.paper = _tiled_paper(style.paper_image, style.paper_image_width_in * dpi, (self.h, self.w))
        else:
            self.paper = np.ones((self.h, self.w, 3), np.float32) * _rgb(style.paper_color)
        self.rgb = self.paper.copy()

    def crop_for(self, geom: BaseGeometry, margin: float) -> tuple[int, int, int, int] | None:
        minx, miny, maxx, maxy = geom.bounds
        x0 = max(int((minx - margin) * self.ppu), 0)
        x1 = min(int(math.ceil((maxx + margin) * self.ppu)), self.w)
        y0 = max(int((self.page_height - maxy - margin) * self.ppu), 0)
        y1 = min(int(math.ceil((self.page_height - miny + margin) * self.ppu)), self.h)
        if x1 <= x0 or y1 <= y0:
            return None
        return x0, y0, x1, y1

    def _context(self, crop) -> tuple[cairo.ImageSurface, cairo.Context]:
        x0, y0, x1, y1 = crop
        surface = cairo.ImageSurface(cairo.FORMAT_A8, x1 - x0, y1 - y0)
        ctx = cairo.Context(surface)
        ctx.translate(-x0, -y0)
        ctx.scale(self.ppu, self.ppu)
        return surface, ctx

    @staticmethod
    def _read(surface: cairo.ImageSurface) -> np.ndarray:
        surface.flush()
        w, h, stride = surface.get_width(), surface.get_height(), surface.get_stride()
        data = np.frombuffer(surface.get_data(), np.uint8).reshape(h, stride)[:, :w]
        return data.astype(np.float32) / 255.0

    def _trace(self, ctx: cairo.Context, geom: BaseGeometry) -> None:
        """Trace any line-like geometry (or a polygon's rings) as open paths."""
        if geom.is_empty:
            return
        if geom.geom_type == "Polygon":
            for ring in (geom.exterior, *geom.interiors):
                self._trace(ctx, ring)
            return
        if hasattr(geom, "geoms"):
            for part in geom.geoms:
                self._trace(ctx, part)
            return
        coords = list(geom.coords)
        ctx.move_to(coords[0][0], self.page_height - coords[0][1])
        for x, y in coords[1:]:
            ctx.line_to(x, self.page_height - y)

    def _trace_area(self, ctx: cairo.Context, geom: BaseGeometry) -> None:
        polygons = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon"]
        for poly in polygons:
            for ring in (poly.exterior, *poly.interiors):
                coords = list(ring.coords)
                ctx.move_to(coords[0][0], self.page_height - coords[0][1])
                for x, y in coords[1:]:
                    ctx.line_to(x, self.page_height - y)
                ctx.close_path()

    def fill_mask(self, geom: BaseGeometry, crop, alpha: float = 1.0) -> np.ndarray:
        surface, ctx = self._context(crop)
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        self._trace_area(ctx, geom)
        ctx.set_source_rgba(0, 0, 0, alpha)
        ctx.fill()
        return self._read(surface)

    def stroke_mask(self, lines: list[BaseGeometry], crop, width: float, alpha: float) -> np.ndarray:
        surface, ctx = self._context(crop)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.set_line_width(width)
        ctx.set_source_rgba(0, 0, 0, alpha)
        for line in lines:
            self._trace(ctx, line)
            ctx.stroke()
        return self._read(surface)

    def dots_mask(self, points: np.ndarray, radii: np.ndarray, crop, alpha: float) -> np.ndarray:
        surface, ctx = self._context(crop)
        ctx.set_source_rgba(0, 0, 0, alpha)
        for (x, y), r in zip(points, radii):
            ctx.arc(x, self.page_height - y, r, 0, 2 * math.pi)
            ctx.fill()
        return self._read(surface)

    def lift(self, crop, mask: np.ndarray) -> None:
        """Take the canvas back toward bare paper under `mask` — the way a
        painter leaves an area unpainted, or lifts a wash, rather than
        glazing the deck on top of the sand. Without this, multiply-blended
        washes stack into mud wherever objects overlap."""
        x0, y0, x1, y1 = crop
        m = np.clip(mask, 0, 1)[..., None]
        self.rgb[y0:y1, x0:x1] = self.rgb[y0:y1, x0:x1] * (1 - m) + self.paper[y0:y1, x0:x1] * m

    def multiply(self, crop, density: np.ndarray, rgb: np.ndarray) -> None:
        """Transparent pigment: at density d, each channel keeps
        1 - d * (1 - pigment) of whatever is underneath."""
        x0, y0, x1, y1 = crop
        d = np.clip(density, 0, 1)[..., None]
        self.rgb[y0:y1, x0:x1] *= 1 - d * (1 - rgb)


def _tiled_paper(path: str, tile_width_px: float, shape: tuple[int, int]) -> np.ndarray:
    """A paper scan, scaled so one copy is `tile_width_px` wide and tiled
    across the page from its top-left corner."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        tile_w = max(1, round(tile_width_px))
        tile_h = max(1, round(img.height * tile_w / img.width))
        tile = np.asarray(img.resize((tile_w, tile_h), Image.LANCZOS), np.float32) / 255.0
    h, w = shape
    reps = (math.ceil(h / tile_h), math.ceil(w / tile_w), 1)
    return np.tile(tile, reps)[:h, :w].copy()


def _rgb(hex_color: str) -> np.ndarray:
    return np.array(_hex_to_rgb(hex_color), np.float32) / 255.0


def _pigment(material: Material) -> np.ndarray:
    """Pastel fills are pale; as a transparent pigment they'd barely show
    through a few glazes. Deepen the color a little so the *finished*
    wash lands near the material's own pastel."""
    rgb = _rgb(material.color)
    return np.clip(1 - (1 - rgb) * 1.15, 0, 1)


_COARSE_SIGMA_PX = 3.0  # blurs wider than this run on a coarse grid (see _blur)


def _resize(arr: np.ndarray, shape: tuple[int, int], resample) -> np.ndarray:
    h, w = shape
    return np.asarray(Image.fromarray(arr.astype(np.float32), mode="F").resize((w, h), resample), np.float32)


def _blur(arr: np.ndarray, sigma_px: float) -> np.ndarray:
    """A Gaussian blur that stays cheap when it's wide. A wide blur leaves
    nothing but low frequencies, so it can run on a grid shrunk until the
    blur is ~3 px there, then be scaled back up — visually identical, and
    at 300 DPI the difference between minutes and seconds (the full-size
    version was 94% of an art render's time)."""
    if sigma_px <= _COARSE_SIGMA_PX * 2:
        return gaussian_filter(arr, sigma_px)
    factor = sigma_px / _COARSE_SIGMA_PX
    h, w = arr.shape
    small = (max(1, round(h / factor)), max(1, round(w / factor)))
    coarse = gaussian_filter(_resize(arr, small, Image.BOX), _COARSE_SIGMA_PX)
    return _resize(coarse, (h, w), Image.BILINEAR)


def _cloud(rng: np.random.Generator, shape: tuple[int, int], sigma_px: float) -> np.ndarray:
    """Smooth random field in roughly [-1, 1]. A wide one is drawn on a
    coarse grid whose cell count depends only on the field's size relative
    to its smoothness — so the same seed gives the same pattern at any DPI
    — then scaled up."""
    h, w = shape
    if sigma_px <= _COARSE_SIGMA_PX * 2:
        field_ = gaussian_filter(rng.standard_normal(shape).astype(np.float32), max(sigma_px, 0.5))
    else:
        factor = sigma_px / _COARSE_SIGMA_PX
        small = (max(1, round(h / factor)), max(1, round(w / factor)))
        coarse = gaussian_filter(rng.standard_normal(small).astype(np.float32), _COARSE_SIGMA_PX)
        field_ = _resize(coarse, shape, Image.BICUBIC)
    std = field_.std() or 1.0
    return np.clip(field_ / (2.5 * std), -1, 1)


# ---------------------------------------------------------------------------
# Wash techniques
# ---------------------------------------------------------------------------


def _wash_diffuse(canvas: _Canvas, geom, crop, style: ArtStyle, rng, clouds) -> np.ndarray:
    ppu = canvas.ppu
    x0, y0, x1, y1 = crop
    density = np.zeros((y1 - y0, x1 - x0), np.float32)
    for _ in range(style.wash_layers):
        noise = _Noise(rng, (0.6, 1.1, 1.9, 3.3, 5.2))
        layer_geom = _wobble(geom, noise, style.wobble, step=0.08)
        mask = canvas.fill_mask(layer_geom, crop)
        soft = _blur(mask, 0.035 * ppu)
        rim = np.clip(soft - _blur(soft, 0.22 * ppu), 0, None) * 2.2
        density += soft * style.wash_strength / style.wash_layers + rim * style.edge_pooling / style.wash_layers
    variation, gran = clouds
    density *= 1 + style.variation * variation[y0:y1, x0:x1]
    density *= 1 - style.granulation * (0.5 + 0.5 * gran[y0:y1, x0:x1])
    return density


def _deform(coords: np.ndarray, rng, depth: int, spread: float) -> np.ndarray:
    """Tyler Hobbs-style recursive polygon deformation: insert a displaced
    midpoint on every edge, `depth` times, shrinking the spread each time."""
    for _ in range(depth):
        nxt = np.roll(coords, -1, axis=0)
        mid = (coords + nxt) / 2 + rng.normal(0, spread, size=coords.shape)
        out = np.empty((len(coords) * 2, 2))
        out[0::2], out[1::2] = coords, mid
        coords = out
        spread *= 0.55
    return coords


def _wash_layered(canvas: _Canvas, geom, crop, style: ArtStyle, rng, clouds) -> np.ndarray:
    from shapely.geometry import Polygon

    x0, y0, x1, y1 = crop
    density = np.zeros((y1 - y0, x1 - x0), np.float32)
    polygons = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon"]
    layers = 18
    for _ in range(layers):
        for poly in polygons:
            base = np.array(poly.simplify(0.02).exterior.coords)[:-1]
            if len(base) < 3:
                continue
            ring = _deform(base, rng, depth=4, spread=style.wobble * 1.6)
            glaze = Polygon(ring).buffer(0)
            density += canvas.fill_mask(glaze, crop, alpha=1.0) * (style.wash_strength * 1.9 / layers)
    variation, gran = clouds
    density *= 1 + style.variation * 0.6 * variation[y0:y1, x0:x1]
    density *= 1 - style.granulation * 0.5 * (0.5 + 0.5 * gran[y0:y1, x0:x1])
    return density


_WASHES = {"diffuse": _wash_diffuse, "layered": _wash_layered}


# ---------------------------------------------------------------------------
# Pencil textures (per-material recipes)
# ---------------------------------------------------------------------------


def _scallop(geom: BaseGeometry, rng: np.random.Generator) -> BaseGeometry:
    """A tree/shrub crown as a bumpy blob: overlapping circles set just
    inside the outline, unioned with the solid core. Bump size scales with
    the crown, so a big tree and a small shrub both read as foliage."""
    from shapely.ops import unary_union

    r = float(np.clip(math.sqrt(geom.area) * 0.15, 0.2, 0.8))
    core = geom.buffer(-r)
    if core.is_empty:
        return geom
    circles = [core]
    for ring in [g.exterior for g in getattr(core, "geoms", [core])]:
        count = max(5, int(ring.length / (r * 1.4)))
        for i in range(count):
            p = ring.interpolate((i + rng.uniform(-0.2, 0.2)) / count, normalized=True)
            circles.append(p.buffer(r * rng.uniform(0.8, 1.15)))
    blob = unary_union(circles)
    if blob.geom_type == "MultiPolygon":
        blob = max(blob.geoms, key=lambda g: g.area)
    return blob


def _leaf_clumps(geom: BaseGeometry, rng: np.random.Generator) -> list[BaseGeometry]:
    """A few short pencil arcs inside a crown, suggesting leaf clusters."""
    r = float(np.clip(math.sqrt(geom.area) * 0.15, 0.2, 0.8))
    inner = geom.buffer(-r * 1.2)
    if inner.is_empty:
        return []
    minx, miny, maxx, maxy = inner.bounds
    arcs = []
    for _ in range(max(3, int(inner.area / (r * r * 3)))):
        x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        if not inner.contains(Point(x, y)):
            continue
        start = rng.uniform(0, 2 * math.pi)
        t = np.linspace(start, start + rng.uniform(1.6, 2.6), 12)
        arcs.append(LineString(np.column_stack([x + r * 0.5 * np.cos(t), y + r * 0.5 * np.sin(t)])))
    return arcs


def _paint_fence_posts(canvas: _Canvas, obj: ResolvedObject, material: Material, crop, style: ArtStyle,
                       units: str) -> None:
    """A fence's posts (every 8 ft): a darker dab of its colour, outlined in pencil."""
    from .fences import fence_centerline, fence_posts, fence_spec

    spec = fence_spec(material, units)
    if spec is None:
        return
    posts = fence_posts(fence_centerline(obj.geometry), spec.post_spacing, spec.post_size)
    for post in posts:
        canvas.multiply(crop, canvas.fill_mask(post, crop) * 0.7, np.clip(_rgb(material.color) * 0.55, 0, 1))
    width = style.pencil_width_in * canvas.units_per_inch
    canvas.multiply(crop, canvas.stroke_mask([p.exterior for p in posts], crop, width, 0.7 * style.pencil),
                    _rgb(style.pencil_color))


def _paint_pavers(canvas: _Canvas, obj: ResolvedObject, material: Material, crop, style: ArtStyle, rng,
                  units: str) -> None:
    """Over a paver material's wash: each brick a slightly different tone
    (by the material's `variation` — a red blend far more than a single
    red), then light pencil joints."""
    from .pavers import bricks_for, paver_spec

    spec = paver_spec(material, obj.pattern, units)
    if spec is None:
        return
    bricks = bricks_for(obj.geometry, spec)
    if not bricks:
        return
    surface, ctx = canvas._context(crop)
    for brick, tone in zip(bricks, rng.uniform(0, 1, len(bricks))):
        canvas._trace_area(ctx, brick)
        ctx.set_source_rgba(0, 0, 0, float(tone))
        ctx.fill()
    canvas.multiply(crop, canvas._read(surface) * spec.variation * 2.0, _pigment(material))
    joints = canvas.stroke_mask([b.exterior for b in bricks], crop, spec.width * 0.05, 0.45 * style.pencil)
    canvas.multiply(crop, joints, np.clip(_rgb(material.color) * 0.6, 0, 1))


def _hatch_lines(geom, direction_deg: float, spacing: float, overshoot: float) -> list[BaseGeometry]:
    """Parallel lines across the region at `direction_deg`, clipped to it
    grown by `overshoot` — letting strokes run slightly past the edge is
    what sells the hand-drawn look."""
    region = geom.buffer(overshoot)
    cx, cy = region.centroid.x, region.centroid.y
    minx, miny, maxx, maxy = region.bounds
    reach = math.hypot(maxx - minx, maxy - miny)
    lines = []
    n = int(reach / spacing) + 1
    for i in range(-n, n + 1):
        offset = i * spacing
        line = LineString([(cx - reach, cy + offset), (cx + reach, cy + offset)])
        lines.append(affinity.rotate(line, direction_deg, origin=(cx, cy)))
    clipped = region.intersection(MultiLineString(lines))
    return [g for g in getattr(clipped, "geoms", [clipped]) if not g.is_empty and g.length > spacing * 0.3]


def _texture(canvas: _Canvas, obj: ResolvedObject, material: Material, crop, style: ArtStyle, rng) -> None:
    recipe = material.texture or {}
    kind = recipe.get("style", "none")
    geom = obj.geometry
    width = style.pencil_width_in * canvas.units_per_inch
    pigment = np.clip(_rgb(material.color) * 0.55, 0, 1)

    if kind == "hatch":
        direction = float(recipe.get("direction", 45))
        directions = [direction, direction + 90] if recipe.get("cross") else [direction]
        for angle in directions:
            lines = _hatch_lines(geom, angle, float(recipe.get("spacing", 0.34)), 0.06)
            noise = _Noise(rng, (0.8, 1.7, 3.1))
            lines = [_wobble(line, noise, style.wobble * 0.35, step=0.1) for line in lines]
            mask = canvas.stroke_mask(lines, crop, width * 0.8, alpha=0.55 * style.pencil)
            canvas.multiply(crop, mask, pigment)
    elif kind == "scallop":
        mask = canvas.stroke_mask(_leaf_clumps(geom, rng), crop, width * 0.9, alpha=0.5 * style.pencil)
        canvas.multiply(crop, mask, pigment)
    elif kind == "stipple":
        area = geom.area
        count = int(area * 60 * float(recipe.get("density", 0.4)))
        minx, miny, maxx, maxy = geom.bounds
        pts = np.column_stack([rng.uniform(minx, maxx, count * 2), rng.uniform(miny, maxy, count * 2)])
        region = geom.buffer(0.03)
        pts = np.array([p for p in pts if region.contains(Point(p))][:count] or np.empty((0, 2)))
        radii = rng.uniform(0.015, 0.045, len(pts))
        mask = canvas.dots_mask(pts, radii, crop, alpha=0.6 * style.pencil)
        canvas.multiply(crop, mask, pigment)
    elif kind == "ripple":
        minx, miny, maxx, maxy = geom.bounds
        spacing = float(recipe.get("spacing", 0.55))
        lines = []
        y = miny + spacing * 0.7
        while y < maxy:
            xs = np.linspace(minx, maxx, 60)
            ys = y + 0.05 * np.sin(xs * 2 * math.pi / 0.9 + rng.uniform(0, 6.3))
            lines.append(LineString(np.column_stack([xs, ys])))
            y += spacing
        inner = geom.buffer(-0.2)
        clipped = [inner.intersection(line) for line in lines] if not inner.is_empty else []
        dashes = []
        for c in clipped:
            for part in getattr(c, "geoms", [c]):
                if part.is_empty or part.length < 0.2:
                    continue
                # break each ripple into a couple of short strokes, as drawn
                a = rng.uniform(0.05, 0.35)
                b = min(a + rng.uniform(0.25, 0.55), 0.98)
                from shapely.ops import substring

                dashes.append(substring(part, a, b, normalized=True))
        mask = canvas.stroke_mask(dashes, crop, width * 0.9, alpha=0.6 * style.pencil)
        edge = _rgb(material.edge.get("color") or material.color)
        canvas.multiply(crop, mask, np.clip(edge * 0.8, 0, 1))


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def render_art_image(
    doc: SceneDocument,
    scene: ResolvedScene,
    materials: MaterialLibrary,
    dpi: float = 150.0,
    style: ArtStyle | None = None,
    show_annotations: bool = False,
    show_legend: bool = False,
    scale_indicator: bool = False,
) -> Image.Image:
    """The scene as a watercolor-and-pencil painting. `show_legend` /
    `scale_indicator` paint the drawing's legend box and scale indicator at
    their saved (or default) positions, in the same pencil and wash."""
    style = style or ArtStyle()
    rng = np.random.default_rng(style.seed)
    canvas = _Canvas(doc, dpi, style)
    ppu = canvas.ppu
    clouds = (_cloud(rng, (canvas.h, canvas.w), 1.2 * ppu), _cloud(rng, (canvas.h, canvas.w), 0.012 * dpi))
    if style.wash not in _WASHES:
        raise ValueError(f"unknown wash style '{style.wash}' (use one of: {', '.join(sorted(_WASHES))})")
    wash = _WASHES[style.wash]
    pencil = _rgb(style.pencil_color)
    width = style.pencil_width_in * canvas.units_per_inch

    objects = list(iter_paint_order_with_material(scene, materials, show_annotations))

    for obj, material in objects:
        geom = obj.geometry
        is_area = geom.geom_type in ("Polygon", "MultiPolygon")
        if geom.is_empty or obj.annotation or obj.rule:
            continue
        if is_area and (material.texture or {}).get("style") == "scallop":
            geom = _scallop(geom, rng)
            obj = ResolvedObject(obj.id, geom, obj.material, obj.layer, obj.z, obj.annotation, obj.rule)
        crop = canvas.crop_for(geom, margin=0.6)
        if crop is None:
            continue

        if is_area and obj.layer in style.shadow_layers:
            shadow = affinity.translate(geom, 0.12, -0.12)
            mask = _blur(canvas.fill_mask(shadow, crop), 0.1 * ppu)
            canvas.multiply(crop, mask * 0.22, np.array([0.45, 0.48, 0.58], np.float32))

        if is_area:
            inner = geom.buffer(-style.lift_overlap)
            if not inner.is_empty:
                canvas.lift(crop, _blur(canvas.fill_mask(inner, crop), 0.03 * ppu))
        if is_area and material.id != _FALLBACK_ID:
            canvas.multiply(crop, wash(canvas, geom, crop, style, rng, clouds), _pigment(material))
            _texture(canvas, obj, material, crop, style, rng)
            _paint_pavers(canvas, obj, material, crop, style, rng, doc.units)
            _paint_fence_posts(canvas, obj, material, crop, style, doc.units)

        # pencil outline: two slightly different passes, like a sketched line
        outline = geom.boundary if is_area else geom
        for alpha, amp in ((0.8, 0.35), (0.35, 0.6)):
            noise = _Noise(rng, (0.9, 1.6, 2.8, 4.4))
            stroke = _wobble(outline, noise, style.wobble * amp, step=0.08)
            mask = canvas.stroke_mask([stroke], crop, width, alpha * style.pencil)
            canvas.multiply(crop, mask, pencil)
        if not is_area and material.id != _FALLBACK_ID:
            mask = canvas.stroke_mask([geom], crop, width * 2.5, 0.5)
            canvas.multiply(crop, mask, _pigment(material))

    # annotations / keepouts: a light dashed pencil line, if shown at all
    for obj, _material in objects:
        if not (obj.annotation or obj.rule) or obj.geometry.is_empty:
            continue
        crop = canvas.crop_for(obj.geometry, margin=0.3)
        if crop is None:
            continue
        outline = obj.geometry.boundary if obj.geometry.geom_type in ("Polygon", "MultiPolygon") else obj.geometry
        dashes = _dash(outline, 0.35, 0.2)
        canvas.multiply(crop, canvas.stroke_mask(dashes, crop, width, 0.5 * style.pencil), pencil)

    if show_legend or scale_indicator:
        _paint_overlays(canvas, doc, scene, materials, style, rng, clouds, wash, show_legend, scale_indicator)

    if not style.paper_image:  # a scan brings its own grain
        grain = _cloud(rng, (canvas.h, canvas.w), 0.004 * dpi)
        tooth = _cloud(rng, (canvas.h, canvas.w), 0.03 * dpi)
        canvas.rgb *= 1 - style.grain * (0.6 * (0.5 + 0.5 * grain) + 0.4 * (0.5 + 0.5 * tooth))[..., None]

    return Image.fromarray((np.clip(canvas.rgb, 0, 1) * 255).astype(np.uint8), "RGB")


def _text_mask(canvas: _Canvas, crop, text: str, size: float, x: float, baseline_y: float) -> np.ndarray:
    from .overlays import FONT_FAMILY

    surface, ctx = canvas._context(crop)
    ctx.select_font_face(FONT_FAMILY)
    ctx.set_font_size(size)
    ctx.move_to(x, canvas.page_height - baseline_y)
    ctx.set_source_rgba(0, 0, 0, 1)
    ctx.show_text(text)
    return canvas._read(surface)


def _paint_overlays(canvas: _Canvas, doc, scene, materials, style: ArtStyle, rng, clouds, wash,
                    show_legend: bool, scale_indicator: bool) -> None:
    """The legend box and scale indicator, drawn like the rest of the
    painting: the paper lifted clean inside the box so it reads over
    whatever is beneath, a wobbly pencil frame, swatches washed in each
    material's watercolor (circles for unassigned items, pencil only), and
    graphite text. Layout comes from `overlays.py`, same as the editor's."""
    import dataclasses

    from shapely.geometry import box as rect

    from .overlays import legend_entries, legend_layout, scale_indicator_layout

    pencil = _rgb(style.pencil_color)
    width = style.pencil_width_in * canvas.units_per_inch
    ink = max(style.pencil, 0.75)  # text and frames must stay legible even with light pencil

    def pencil_lines(geoms, crop, alpha, amp=0.15):
        noise = _Noise(rng, (0.9, 1.6, 2.8))
        wobbled = [_wobble(g, noise, style.wobble * amp, step=0.05) for g in geoms]
        canvas.multiply(crop, canvas.stroke_mask(wobbled, crop, width, alpha), pencil)

    if show_legend:
        layout = legend_layout(doc, legend_entries(scene, materials))
        frame = rect(layout.x, layout.y - layout.height, layout.x + layout.width, layout.y)
        crop = canvas.crop_for(frame, margin=0.3)
        if crop is not None:
            canvas.lift(crop, canvas.fill_mask(frame, crop))
            pencil_lines([frame.exterior], crop, 0.8 * ink)
            pencil_lines([frame.exterior], crop, 0.3 * ink, amp=0.3)
            canvas.multiply(crop, _text_mask(canvas, crop, layout.title, layout.title_size, layout.title_x,
                                             layout.title_baseline_y) * 0.9 * ink, pencil)
            swatch_style = dataclasses.replace(style, wobble=layout.rows[0].swatch * 0.04 if layout.rows else 0.01)
            for row in layout.rows:
                if row.entry.shape == "square":
                    shape = rect(row.swatch_x, row.swatch_y - row.swatch, row.swatch_x + row.swatch, row.swatch_y)
                    material = materials.resolve(row.entry.material_id)
                    canvas.multiply(crop, wash(canvas, shape, crop, swatch_style, rng, clouds), _pigment(material))
                    outline = shape.exterior
                else:
                    centre = Point(row.swatch_x + row.swatch / 2, row.swatch_y - row.swatch / 2)
                    outline = centre.buffer(row.swatch / 2, 32).exterior
                pencil_lines([outline], crop, 0.7 * ink, amp=0.05)
                canvas.multiply(crop, _text_mask(canvas, crop, row.entry.label, layout.text_size, row.text_x,
                                                 row.baseline_y) * 0.85 * ink, pencil)

    if scale_indicator:
        bar = scale_indicator_layout(doc)
        line = LineString([(bar.x, bar.y + bar.tick), (bar.x, bar.y), (bar.x + bar.length, bar.y),
                           (bar.x + bar.length, bar.y + bar.tick)])
        crop = canvas.crop_for(line.buffer(bar.text_size * 2), margin=0.2)
        if crop is not None:
            pencil_lines([line], crop, 0.85 * ink, amp=0.08)
            pencil_lines([line], crop, 0.35 * ink, amp=0.15)
            canvas.multiply(crop, _text_mask(canvas, crop, bar.label, bar.text_size, bar.label_x,
                                             bar.label_baseline_y) * 0.9 * ink, pencil)


def _dash(line: BaseGeometry, on: float, off: float) -> list[BaseGeometry]:
    from shapely.ops import substring

    parts = []
    for part in getattr(line, "geoms", [line]):
        pos = 0.0
        while pos < part.length:
            parts.append(substring(part, pos, min(pos + on, part.length)))
            pos += on + off
    return parts


# ---------------------------------------------------------------------------
# Export (M6 + M7): PNG, and PDF/SVG as an honest raster-vector hybrid
# ---------------------------------------------------------------------------
#
# The painting is inherently raster — soft washes, granulation and paper
# grain have no vector equivalent — so PDF and SVG exports *embed* it as an
# image at `dpi`, the painting's resolution. What stays vector is
# everything that's crisp by nature: the scale bar, north arrow and legend
# (the same code flat mode uses). The page keeps its true print size either
# way. `dpi` therefore matters for every art format, not just PNG.

ART_DEFAULT_DPI = 200.0


def _art_page(
    ctx: cairo.Context,
    doc: SceneDocument,
    scene: ResolvedScene,
    materials: MaterialLibrary,
    painting: Image.Image,
    scale_bar: bool,
    north_arrow: bool,
    north_deg: float,
    show_legend: bool,
    show_annotations: bool,
) -> None:
    """Paint the rendered image over the drawing area of a context already
    scaled to scene units, then the vector strip on top. (The legend box and
    scale indicator are part of the painting itself.)"""
    from .render_flat import _draw_decoration_strip

    rgba = painting.convert("RGBA")
    # cairo wants premultiplied BGRA; an opaque image needs only the swizzle
    bgra = np.asarray(rgba, np.uint8)[..., [2, 1, 0, 3]].copy()
    source = cairo.ImageSurface.create_for_data(
        memoryview(bgra), cairo.FORMAT_ARGB32, rgba.width, rgba.height, rgba.width * 4
    )
    ctx.save()
    ctx.scale(doc.page_width / rgba.width, doc.page_height / rgba.height)
    ctx.set_source_surface(source, 0, 0)
    ctx.get_source().set_filter(cairo.FILTER_GOOD)
    ctx.paint()
    ctx.restore()
    source.finish()

    if scale_bar or north_arrow:
        _draw_decoration_strip(ctx, doc, scale_bar, north_arrow, north_deg)


def _export_art(surface_factory, doc, scene, materials, path, dpi, style, scale_bar, north_arrow, north_deg,
                show_legend, show_annotations, scale_indicator=False):
    from .render_flat import _page_size_pt

    painting = render_art_image(doc, scene, materials, dpi=dpi, style=style, show_annotations=show_annotations,
                                show_legend=show_legend, scale_indicator=scale_indicator)
    width, height = _page_size_pt(doc, scale_bar or north_arrow)
    surface = surface_factory(str(path), width, height)
    ctx = cairo.Context(surface)
    ctx.scale(doc.scale, doc.scale)
    _art_page(ctx, doc, scene, materials, painting, scale_bar, north_arrow, north_deg, show_legend, show_annotations)
    surface.finish()


def render_art_to_pdf(doc, scene, materials, path, dpi: float = ART_DEFAULT_DPI, style: ArtStyle | None = None,
                      scale_bar=False, north_arrow=False, north_deg=0.0, show_legend=False, show_annotations=False,
                      scale_indicator=False):
    _export_art(cairo.PDFSurface, doc, scene, materials, path, dpi, style, scale_bar, north_arrow, north_deg,
                show_legend, show_annotations, scale_indicator)


def render_art_to_svg(doc, scene, materials, path, dpi: float = ART_DEFAULT_DPI, style: ArtStyle | None = None,
                      scale_bar=False, north_arrow=False, north_deg=0.0, show_legend=False, show_annotations=False,
                      scale_indicator=False):
    def svg_surface(p, w, h):
        surface = cairo.SVGSurface(p, w, h)
        surface.set_document_unit(cairo.SVGUnit.PT)
        return surface

    _export_art(svg_surface, doc, scene, materials, path, dpi, style, scale_bar, north_arrow, north_deg,
                show_legend, show_annotations, scale_indicator)


def render_art_to_png(doc, scene, materials, path, dpi: float = ART_DEFAULT_DPI, style: ArtStyle | None = None,
                      scale_bar=False, north_arrow=False, north_deg=0.0, show_legend=False, show_annotations=False,
                      scale_indicator=False):
    """Same page as the PDF, rasterised at `dpi`, with the DPI recorded in
    the file (see render_flat.render_scene_to_png)."""
    import io

    from .render_flat import _page_size_pt

    painting = render_art_image(doc, scene, materials, dpi=dpi, style=style, show_annotations=show_annotations,
                                show_legend=show_legend, scale_indicator=scale_indicator)
    width_pt, height_pt = _page_size_pt(doc, scale_bar or north_arrow)
    px_per_point = dpi / 72.0
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, round(width_pt * px_per_point), round(height_pt * px_per_point))
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(1, 1, 1)
    ctx.paint()
    ctx.scale(doc.scale * px_per_point, doc.scale * px_per_point)
    _art_page(ctx, doc, scene, materials, painting, scale_bar, north_arrow, north_deg, show_legend, show_annotations)
    buffer = io.BytesIO()
    surface.write_to_png(buffer)
    buffer.seek(0)
    with Image.open(buffer) as img:
        img.convert("RGB").save(str(path), format="PNG", dpi=(dpi, dpi))
