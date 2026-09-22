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
    show_legend: bool = False,
    show_annotations: bool = False,
) -> None:
    """Issue the flat-mode draw calls onto an existing cairo context. The
    caller owns the surface and its lifecycle (create, `finish()`/save) —
    this only draws, so the exact same call works for SVG, PDF, or PNG."""

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
            ctx.set_source_rgb(*_rgb01(material.color))
            ctx.fill_preserve()
            weight = material.edge.get("weight", 1.0)
            if weight and weight > 0:
                ctx.set_source_rgb(*_rgb01(_edge_color(material)))
                ctx.set_line_width(weight)
                ctx.stroke()
            else:
                ctx.new_path()
        else:
            _draw_line_path(ctx, geom, page_height)
            ctx.set_source_rgb(*_rgb01(_edge_color(material)))
            ctx.set_line_width(material.edge.get("weight") or 1.0)
            ctx.stroke()

    if show_legend:
        _draw_legend(ctx, used_materials_in_scene(scene, materials, show_annotations), page_height)


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


def _draw_legend(ctx: cairo.Context, materials: list[Material], page_height: float) -> None:
    """An optional legend keyed to the materials actually used, drawn in
    the bottom-left corner. Font/box sizes are in scene units so it scales
    sensibly with `ctx`'s own transform."""
    materials = sorted(materials, key=lambda m: m.name)
    swatch = 0.4
    line_height = 0.55
    x = 0.5
    y = page_height - 0.5 - len(materials) * line_height
    ctx.set_font_size(0.35)
    for material in materials:
        ctx.set_source_rgb(*_rgb01(material.color))
        ctx.rectangle(x, y, swatch, swatch)
        ctx.fill()
        ctx.set_source_rgb(0.1, 0.1, 0.1)
        ctx.rectangle(x, y, swatch, swatch)
        ctx.set_line_width(0.02)
        ctx.stroke()
        ctx.move_to(x + swatch + 0.15, y + swatch * 0.85)
        ctx.show_text(material.name)
        y += line_height


# ---------------------------------------------------------------------------
# Vector-native / raster export
# ---------------------------------------------------------------------------


def render_scene_to_svg(
    doc: SceneDocument, scene: ResolvedScene, materials: MaterialLibrary, path: str | Path, **kwargs
) -> None:
    width, height = doc.page_width * doc.scale, doc.page_height * doc.scale
    surface = cairo.SVGSurface(str(path), width, height)
    ctx = cairo.Context(surface)
    ctx.scale(doc.scale, doc.scale)
    render_flat(ctx, scene, materials, doc.page_height, **kwargs)
    surface.finish()


def render_scene_to_pdf(
    doc: SceneDocument, scene: ResolvedScene, materials: MaterialLibrary, path: str | Path, **kwargs
) -> None:
    width, height = doc.page_width * doc.scale, doc.page_height * doc.scale
    surface = cairo.PDFSurface(str(path), width, height)
    ctx = cairo.Context(surface)
    ctx.scale(doc.scale, doc.scale)
    render_flat(ctx, scene, materials, doc.page_height, **kwargs)
    surface.finish()


def render_scene_to_png(
    doc: SceneDocument,
    scene: ResolvedScene,
    materials: MaterialLibrary,
    path: str | Path,
    dpi_scale: float = 1.0,
    **kwargs,
) -> None:
    """Raster export. `dpi_scale` multiplies the base `doc.scale` (points
    per real-world unit) for a higher-resolution PNG; M7 owns picking a
    real DPI value, this just needs a knob for it to turn."""
    width = int(doc.page_width * doc.scale * dpi_scale)
    height = int(doc.page_height * doc.scale * dpi_scale)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(1, 1, 1)
    ctx.paint()
    ctx.scale(doc.scale * dpi_scale, doc.scale * dpi_scale)
    render_flat(ctx, scene, materials, doc.page_height, **kwargs)
    surface.write_to_png(str(path))
