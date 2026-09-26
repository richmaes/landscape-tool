"""Flat pastel renderer (M5): the thinnest end-to-end path from a scene
document to a picture — "get the real backyard on screen" per TODO.md's
suggested order of attack.

`render_flat` is the shared rendering abstraction: it walks the resolved
scene in paint order, resolves each object's material, and issues cairo
draw calls onto whatever `cairo.Context` it's handed. The context's
surface — SVG, PDF, or an in-memory raster — is the caller's concern, not
this function's, since cairo's drawing API is identical across all three.
M6's hand-drawn mode is expected to reuse the same paint-order walk and
material resolution, swapping in textured fills for `ctx.fill_preserve()`.
"""

from __future__ import annotations

import math
from fractions import Fraction
from pathlib import Path

import cairo
from shapely.geometry.base import BaseGeometry

from .geometry import ResolvedObject, ResolvedScene
from .materials import Material, MaterialLibrary, _hex_to_rgb
from .schema import SceneDocument


def iter_paint_order_with_material(
    scene: ResolvedScene, materials: MaterialLibrary, include_annotations: bool = False
):
    """The shared scene-traversal walk: every object in paint order,
    paired with its resolved material. Annotations are excluded by
    default — they're not material-rendered, only shown in technical
    views (M2's decision)."""
    for obj in scene.paint_order():
        if obj.annotation and not include_annotations:
            continue
        yield obj, materials.resolve(obj.material)


def used_materials_in_scene(
    scene: ResolvedScene, materials: MaterialLibrary, include_annotations: bool = False
) -> list[Material]:
    """Every distinct material actually filled by `render_flat`, sorted by
    name — annotations, keepout zones, and unresolved (fallback) materials
    never appear on the legend. Factored out of `render_flat` so the
    legend's contents can be tested without rendering a page."""
    used: dict[str, Material] = {}
    for obj, material in iter_paint_order_with_material(scene, materials, include_annotations):
        if obj.annotation or obj.rule or material.id == "__fallback__":
            continue
        used[material.id] = material
    return sorted(used.values(), key=lambda m: m.name)


def _rgb01(hex_color: str) -> tuple[float, float, float]:
    r, g, b = _hex_to_rgb(hex_color)
    return (r / 255, g / 255, b / 255)


def _darken(hex_color: str, factor: float = 0.7) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return "#{:02X}{:02X}{:02X}".format(int(r * factor), int(g * factor), int(b * factor))


def _edge_color(material: Material) -> str:
    """A material's own edge color if it declared one, otherwise a darker
    shade of its fill — outlines are per-material via `edge`, not a
    single global stroke color."""
    return material.edge.get("color") or _darken(material.color)


def _draw_polygon_path(ctx: cairo.Context, geom: BaseGeometry, page_height: float) -> None:
    """Trace a Polygon (with holes) or MultiPolygon onto the current cairo
    path. Y is flipped: scene coordinates are +y-north/up, cairo is
    +y-down, so this is the one place that reconciles them."""
    polygons = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    for poly in polygons:
        for ring in (poly.exterior, *poly.interiors):
            coords = list(ring.coords)
            if not coords:
                continue
            ctx.move_to(coords[0][0], page_height - coords[0][1])
            for x, y in coords[1:]:
                ctx.line_to(x, page_height - y)
            ctx.close_path()


def _draw_line_path(ctx: cairo.Context, geom: BaseGeometry, page_height: float) -> None:
    lines = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
    for line in lines:
        coords = list(line.coords)
        if not coords:
            continue
        ctx.move_to(coords[0][0], page_height - coords[0][1])
        for x, y in coords[1:]:
            ctx.line_to(x, page_height - y)


def render_flat(
    ctx: cairo.Context,
    scene: ResolvedScene,
    materials: MaterialLibrary,
    page_height: float,
    show_annotations: bool = False,
    units: str = "ft",
) -> None:
    """Issue the flat-mode draw calls onto an existing cairo context. The
    caller owns the surface and its lifecycle (create, `finish()`/save) —
    this only draws, so the exact same call works for SVG, PDF, or PNG.
    (The legend box and scale indicator are drawn by `_draw_page`, which
    knows the document they're positioned in.)"""

    for obj, material in iter_paint_order_with_material(scene, materials, show_annotations):
        geom = obj.geometry
        if geom.is_empty:
            continue

        if obj.annotation or obj.rule:
            # A keepout's Keepout primitive "carries a rule rather than a
            # material" (M2's own words) — it's a constraint zone, not a
            # design surface, so it gets the same dashed/label treatment
            # as an annotation instead of a flat fill (which would just
            # be the "missing material" fallback color, misleadingly).
            label = f"{obj.id} ({obj.rule})" if obj.rule else obj.id
            _draw_annotation(ctx, obj, page_height, label=label)
            continue

        is_area = geom.geom_type in ("Polygon", "MultiPolygon")
        if is_area:
            _draw_polygon_path(ctx, geom, page_height)
            fill = "#DCD8CE" if (obj.model is not None and material.id == "__fallback__") else material.color
            ctx.set_source_rgb(*_rgb01(fill))  # a model's footprint: neutral, not the magenta fallback
            ctx.fill_preserve()
            weight = material.edge.get("weight", 1.0)
            if weight and weight > 0:
                ctx.set_source_rgb(*_rgb01(_edge_color(material)))
                ctx.set_line_width(weight)
                ctx.stroke()
            else:
                ctx.new_path()
            _draw_paver_joints(ctx, obj, material, page_height, units)
        else:
            _draw_line_path(ctx, geom, page_height)
            ctx.set_source_rgb(*_rgb01(_edge_color(material)))
            ctx.set_line_width(material.edge.get("weight") or 1.0)
            ctx.stroke()


def _draw_paver_joints(ctx: cairo.Context, obj: ResolvedObject, material: Material, page_height: float, units: str) -> None:
    """For a paver material, every brick's outline in a darker shade of its
    color (see pavers.py)."""
    from .pavers import bricks_for, paver_spec

    spec = paver_spec(material, obj.pattern, units)
    if spec is None:
        return
    for brick in bricks_for(obj.geometry, spec):
        _draw_polygon_path(ctx, brick, page_height)
    ctx.set_source_rgb(*_rgb01(_darken(material.color, 0.72)))
    ctx.set_line_width(spec.width * 0.06)  # joints about 1/4 in wide on a 4 in brick
    ctx.stroke()


def _draw_annotation(ctx: cairo.Context, obj: ResolvedObject, page_height: float, label: str | None = None) -> None:
    """Annotations (e.g. the 14x10 clearance marker) and keepout zones
    get a dashed outline plus a label — never a material fill."""
    geom = obj.geometry
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        _draw_polygon_path(ctx, geom, page_height)
    else:
        _draw_line_path(ctx, geom, page_height)
    ctx.set_source_rgb(0.25, 0.25, 0.25)
    ctx.set_line_width(0.05)
    ctx.set_dash([0.3, 0.2])
    ctx.stroke()
    ctx.set_dash([])

    cx, cy = geom.centroid.x, page_height - geom.centroid.y
    ctx.set_font_size(0.8)
    ctx.move_to(cx, cy)
    ctx.show_text(label if label is not None else obj.id)


def _draw_overlays(
    ctx: cairo.Context,
    doc: SceneDocument,
    scene: ResolvedScene,
    materials: MaterialLibrary,
    show_legend: bool,
    scale_indicator: bool,
) -> None:
    """The drawing's legend box and scale indicator, at their saved (or
    default) positions — the same layout the editor canvas and the art
    renderer use (`overlays.py`)."""
    from .overlays import FONT_FAMILY, legend_entries, legend_layout, scale_indicator_layout

    h = doc.page_height
    ink = (0.17, 0.16, 0.15)
    thin = 0.5 / doc.scale  # half a point, in scene units (doc.scale is points per unit)
    ctx.select_font_face(FONT_FAMILY)
    if show_legend:
        layout = legend_layout(doc, legend_entries(scene, materials))
        ctx.rectangle(layout.x, h - layout.y, layout.width, layout.height)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill_preserve()
        ctx.set_source_rgb(*ink)
        ctx.set_line_width(thin * 1.5)
        ctx.stroke()
        ctx.set_font_size(layout.title_size)
        ctx.move_to(layout.title_x, h - layout.title_baseline_y)
        ctx.show_text(layout.title)
        ctx.set_font_size(layout.text_size)
        for row in layout.rows:
            top = h - row.swatch_y
            if row.entry.shape == "square":
                ctx.rectangle(row.swatch_x, top, row.swatch, row.swatch)
            else:
                ctx.new_sub_path()
                ctx.arc(row.swatch_x + row.swatch / 2, top + row.swatch / 2, row.swatch / 2, 0, 2 * math.pi)
            ctx.set_source_rgb(*(_rgb01(row.entry.color) if row.entry.color else (1, 1, 1)))
            ctx.fill_preserve()
            ctx.set_source_rgb(*ink)
            ctx.set_line_width(thin)
            ctx.stroke()
            ctx.move_to(row.text_x, h - row.baseline_y)
            ctx.show_text(row.entry.label)
    if scale_indicator:
        bar = scale_indicator_layout(doc)
        y = h - bar.y
        ctx.set_source_rgb(*ink)
        ctx.set_line_width(thin * 2)
        ctx.move_to(bar.x, y - bar.tick)
        ctx.line_to(bar.x, y)
        ctx.line_to(bar.x + bar.length, y)
        ctx.line_to(bar.x + bar.length, y - bar.tick)
        ctx.stroke()
        ctx.set_font_size(bar.text_size)
        ctx.move_to(bar.label_x, h - bar.label_baseline_y)
        ctx.show_text(bar.label)


# ---------------------------------------------------------------------------
# Scale bar and north arrow (M7)
# ---------------------------------------------------------------------------
#
# The drawing fills its page edge to edge (the backyard's site circle
# touches all four sides), so there's no corner that's reliably free for
# these in every scene. They go in a strip *below* the drawing instead —
# the page grows taller by DECORATION_STRIP_PT, while the drawing itself
# stays at exactly its print scale. Sizes here are in points, converted to
# scene units (`/ doc.scale`), so the strip looks the same whatever the
# scene's scale.

DECORATION_STRIP_PT = 72  # one inch
_POINTS_PER_INCH = 72.0
_INCHES_PER_UNIT = {"ft": 12.0, "in": 1.0, "yd": 36.0, "m": 1000 / 25.4}


def nice_scale_bar_length(page_width: float) -> float:
    """The largest round length (1, 2, 2.5 or 5 x a power of ten) no
    longer than a quarter of the page width."""
    target = page_width / 4
    best = None
    for exponent in range(-3, 7):
        for mantissa in (1, 2, 2.5, 5):
            candidate = mantissa * 10**exponent
            if candidate <= target and (best is None or candidate > best):
                best = candidate
    return best if best is not None else target


def print_scale_label(scale: float, units: str) -> str:
    """E.g. 36 pt per ft -> '1/2 in = 1 ft (1:24)'. The ratio is only
    given for units with a known length in inches."""
    inches = Fraction(scale / _POINTS_PER_INCH).limit_denominator(64)
    inches_text = f"{inches.numerator}/{inches.denominator}" if inches.denominator != 1 else f"{inches.numerator}"
    label = f"{inches_text} in = 1 {units}"
    unit_inches = _INCHES_PER_UNIT.get(units)
    if unit_inches is not None:
        label += f" (1:{unit_inches / (scale / _POINTS_PER_INCH):g})"
    return label


def _pt(doc: SceneDocument, points: float) -> float:
    return points / doc.scale


def scale_bar_geometry(doc: SceneDocument) -> tuple[float, float, float]:
    """(left x, top y, length) of the scale bar, in scene units, with y
    measured down from the top of the drawing (cairo page coordinates)."""
    x0 = _pt(doc, 36)
    y = doc.page_height + _pt(doc, DECORATION_STRIP_PT * 0.3)
    return x0, y, nice_scale_bar_length(doc.page_width)


def _format_length(value: float, units: str) -> str:
    return f"{value:g} {units}"


def _draw_scale_bar(ctx: cairo.Context, doc: SceneDocument) -> None:
    """Alternating filled/open segments, labelled 0 and the full length,
    with the print scale stated beside it."""
    x0, y, length = scale_bar_geometry(doc)
    height = _pt(doc, 8)
    leading = float(f"{length:e}".split("e")[0])
    segments = 5 if leading in (2.5, 5) else 4
    segment = length / segments
    ctx.set_line_width(_pt(doc, 0.75))
    for i in range(segments):
        ctx.rectangle(x0 + i * segment, y, segment, height)
        ctx.set_source_rgb(*((0.1, 0.1, 0.1) if i % 2 == 0 else (1, 1, 1)))
        ctx.fill_preserve()
        ctx.set_source_rgb(0.1, 0.1, 0.1)
        ctx.stroke()

    ctx.set_font_size(_pt(doc, 9))
    baseline = y + height + _pt(doc, 12)
    ctx.move_to(x0, baseline)
    ctx.show_text("0")
    end_label = _format_length(length, doc.units)
    extents = ctx.text_extents(end_label)
    ctx.move_to(x0 + length - extents.x_advance / 2, baseline)
    ctx.show_text(end_label)
    ctx.move_to(x0 + length + _pt(doc, 36), baseline)  # same line as 0 / length, clear of the bar
    ctx.show_text(f"Scale {print_scale_label(doc.scale, doc.units)}")


def north_arrow_tip(cx: float, cy: float, size: float, north_deg: float) -> tuple[float, float]:
    """Where the arrow points, in cairo page coordinates (+y down):
    `north_deg` is degrees clockwise from page-up."""
    theta = math.radians(north_deg)
    return cx + size * math.sin(theta), cy - size * math.cos(theta)


def _draw_north_arrow(ctx: cairo.Context, doc: SceneDocument, north_deg: float) -> None:
    """A classic half-filled arrowhead with an 'N' beyond its tip. Assumes
    page-up is north unless `north_deg` says otherwise — whether it is for
    the real site is still an open question (extraction/objects.md)."""
    size = _pt(doc, 18)
    cx = doc.page_width - _pt(doc, 54)
    cy = doc.page_height + _pt(doc, DECORATION_STRIP_PT * 0.55)
    tip = north_arrow_tip(cx, cy, size, north_deg)
    tail = north_arrow_tip(cx, cy, -size * 0.6, north_deg)
    left = north_arrow_tip(cx, cy, size * 0.55, north_deg - 90)
    right = north_arrow_tip(cx, cy, size * 0.55, north_deg + 90)
    left_base = (left[0] + tail[0] - cx, left[1] + tail[1] - cy)
    right_base = (right[0] + tail[0] - cx, right[1] + tail[1] - cy)

    ctx.set_line_width(_pt(doc, 0.75))
    ctx.set_source_rgb(0.1, 0.1, 0.1)
    ctx.move_to(*tip)
    ctx.line_to(*left_base)
    ctx.line_to(cx, cy)
    ctx.close_path()
    ctx.fill_preserve()
    ctx.stroke()
    ctx.move_to(*tip)
    ctx.line_to(*right_base)
    ctx.line_to(cx, cy)
    ctx.close_path()
    ctx.stroke()

    ctx.set_font_size(_pt(doc, 11))
    label_at = north_arrow_tip(cx, cy, size + _pt(doc, 9), north_deg)
    extents = ctx.text_extents("N")
    ctx.move_to(label_at[0] - extents.x_advance / 2, label_at[1] + extents.height / 2)
    ctx.show_text("N")


def _draw_decoration_strip(
    ctx: cairo.Context, doc: SceneDocument, scale_bar: bool, north_arrow: bool, north_deg: float
) -> None:
    ctx.set_source_rgb(0.1, 0.1, 0.1)
    ctx.set_line_width(_pt(doc, 0.5))
    ctx.move_to(0, doc.page_height)
    ctx.line_to(doc.page_width, doc.page_height)
    ctx.stroke()
    if scale_bar:
        _draw_scale_bar(ctx, doc)
    if north_arrow:
        _draw_north_arrow(ctx, doc, north_deg)


def _page_size_pt(doc: SceneDocument, decorated: bool) -> tuple[float, float]:
    extra = DECORATION_STRIP_PT if decorated else 0
    return doc.page_width * doc.scale, doc.page_height * doc.scale + extra


def _draw_page(
    ctx: cairo.Context,
    doc: SceneDocument,
    scene: ResolvedScene,
    materials: MaterialLibrary,
    scale_bar: bool = False,
    north_arrow: bool = False,
    north_deg: float = 0.0,
    show_legend: bool = False,
    scale_indicator: bool = False,
    **kwargs,
) -> None:
    """Everything on the page — the drawing, its legend box and scale
    indicator if asked for, then the optional strip —
    onto a context already scaled to scene units. Shared by all three
    export formats so they can't drift apart.

    The drawing is clipped to its own page area: the page edge used to do
    that implicitly, but with a strip below it, anything reaching past the
    drawing's bottom edge (the site circle's outline, the original design's
    overhanging keep-out) would otherwise spill into the strip."""
    ctx.save()
    ctx.rectangle(0, 0, doc.page_width, doc.page_height)
    ctx.clip()
    render_flat(ctx, scene, materials, doc.page_height, units=doc.units, **kwargs)
    _draw_overlays(ctx, doc, scene, materials, show_legend, scale_indicator)
    ctx.restore()
    if scale_bar or north_arrow:
        _draw_decoration_strip(ctx, doc, scale_bar, north_arrow, north_deg)


# ---------------------------------------------------------------------------
# Vector-native / raster export
# ---------------------------------------------------------------------------
#
# Each takes `scale_bar=`, `north_arrow=` and `north_deg=` (see above) plus
# `show_legend=` / `scale_indicator=` (the drawing's own legend box and scale
# line) and `show_annotations=`.


def render_scene_to_svg(
    doc: SceneDocument, scene: ResolvedScene, materials: MaterialLibrary, path: str | Path, **kwargs
) -> None:
    """Vector-native SVG, sized in points (`width="864pt"`) so it prints and
    imports at the drawing's true size — cairo's default is unitless, which
    SVG reads as CSS pixels (96/in), shrinking a 12 in drawing to 9 in."""
    width, height = _page_size_pt(doc, kwargs.get("scale_bar") or kwargs.get("north_arrow"))
    surface = cairo.SVGSurface(str(path), width, height)
    surface.set_document_unit(cairo.SVGUnit.PT)
    ctx = cairo.Context(surface)
    ctx.scale(doc.scale, doc.scale)
    _draw_page(ctx, doc, scene, materials, **kwargs)
    surface.finish()


def render_scene_to_pdf(
    doc: SceneDocument, scene: ResolvedScene, materials: MaterialLibrary, path: str | Path, **kwargs
) -> None:
    width, height = _page_size_pt(doc, kwargs.get("scale_bar") or kwargs.get("north_arrow"))
    surface = cairo.PDFSurface(str(path), width, height)
    ctx = cairo.Context(surface)
    ctx.scale(doc.scale, doc.scale)
    _draw_page(ctx, doc, scene, materials, **kwargs)
    surface.finish()


def render_scene_to_png(
    doc: SceneDocument,
    scene: ResolvedScene,
    materials: MaterialLibrary,
    path: str | Path,
    dpi: float = 72.0,
    **kwargs,
) -> None:
    """Raster export at `dpi` pixels per inch of the drawing's *print*
    size. That size is fixed by the scene: `doc.scale` points per real-world
    unit at 72 points per inch — for the backyard, 24 ft at 36 pt/ft is a
    12 in square, the source PDF's own 1/2 in = 1 ft scale. The default,
    72 DPI, is one pixel per point (the size this produced before DPI was
    configurable).

    The DPI is also written into the PNG's resolution metadata (pHYs), so
    it prints at that true physical size rather than whatever DPI an image
    app or print dialog assumes — pixel count alone doesn't fix it. cairo
    can't write that chunk itself, so the image goes through Pillow."""
    import io

    from PIL import Image

    px_per_point = dpi / 72.0
    width_pt, height_pt = _page_size_pt(doc, kwargs.get("scale_bar") or kwargs.get("north_arrow"))
    width = round(width_pt * px_per_point)
    height = round(height_pt * px_per_point)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(1, 1, 1)
    ctx.paint()
    ctx.scale(doc.scale * px_per_point, doc.scale * px_per_point)
    _draw_page(ctx, doc, scene, materials, **kwargs)

    buffer = io.BytesIO()
    surface.write_to_png(buffer)
    buffer.seek(0)
    with Image.open(buffer) as img:
        img.save(str(path), format="PNG", dpi=(dpi, dpi))
