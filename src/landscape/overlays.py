"""The drawing's own overlays: a legend box and a scale indicator.

Pure layout and contents, no drawing — the editor canvas (Qt), the flat
renderer and the art renderer (cairo) each draw from the same numbers, so
the three can't disagree about where a row or a swatch goes.

Everything is sized in inches *on paper* and converted to scene units with
the document's scale, so the legend looks the same size on a 1:24 plan as
on a 1:48 one. Positions are scene units (+y north): the legend's origin is
its box's top-left corner, the scale indicator's is the left end of its
line. Until the designer moves one, it sits at a default spot — legend
bottom-left, scale indicator bottom-right.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import cairo

from .geometry import ResolvedScene
from .materials import MaterialLibrary
from .schema import SceneDocument

FALLBACK_ID = "__fallback__"
FONT_FAMILY = "Sans"
TEXT_PT = 9.0
TITLE_PT = 10.0
SWATCH_IN = 0.16
ROW_IN = 0.24
PAD_IN = 0.1
GAP_IN = 0.08
MARGIN_IN = 0.15
TICK_IN = 0.05


@dataclass
class LegendEntry:
    shape: str  # "square" for a material, "circle" for an item with none chosen yet
    color: str | None
    label: str
    material_id: str | None = None  # the material a square stands for


@dataclass
class LegendRow:
    entry: LegendEntry
    swatch_x: float  # swatch's top-left corner, scene units (+y north)
    swatch_y: float
    swatch: float  # side / diameter
    text_x: float
    baseline_y: float  # text baseline


@dataclass
class LegendLayout:
    x: float  # box top-left, scene units
    y: float
    width: float
    height: float
    title: str
    title_x: float
    title_baseline_y: float
    text_size: float  # font size in scene units
    title_size: float
    rows: list[LegendRow] = field(default_factory=list)


@dataclass
class ScaleIndicatorLayout:
    x: float  # left end of the line
    y: float
    length: float
    label: str
    label_x: float  # label baseline, centred above the line
    label_baseline_y: float
    tick: float  # end-tick height
    text_size: float


def _units_per_inch(doc: SceneDocument) -> float:
    return 72.0 / doc.scale


def _item_group(object_id: str) -> str:
    """'water_feature_a' and 'water_feature_b' are one kind of thing."""
    return re.sub(r"[_-](?:[a-z]|\d+)$", "", object_id)


def legend_entries(scene: ResolvedScene, materials: MaterialLibrary, hidden_layers=()) -> list[LegendEntry]:
    """Every material in use (a square in its color), then every item with
    no material yet (a circle: the firepit, the water features), grouped by
    name. Annotations and keep-out zones aren't design surfaces and are
    left out, as are objects on hidden layers."""
    hidden = set(hidden_layers)
    squares: dict[str, LegendEntry] = {}
    circles: dict[str, LegendEntry] = {}
    for obj in scene.objects:
        if obj.annotation or obj.rule or obj.layer in hidden or obj.geometry.is_empty:
            continue
        material = materials.resolve(obj.material)
        if material.id == FALLBACK_ID:
            if obj.geometry.geom_type not in ("Polygon", "MultiPolygon"):
                continue  # seams and other linework are drawing detail, not items
            group = _item_group(obj.id)
            circles.setdefault(group, LegendEntry("circle", None, group.replace("_", " ").capitalize()))
        else:
            squares.setdefault(material.id, LegendEntry("square", material.color, material.name, material.id))
    return sorted(squares.values(), key=lambda e: e.label) + sorted(circles.values(), key=lambda e: e.label)


def _text_width(text: str, size: float) -> float:
    surface = cairo.ImageSurface(cairo.FORMAT_A8, 1, 1)
    ctx = cairo.Context(surface)
    ctx.select_font_face(FONT_FAMILY)
    ctx.set_font_size(size)
    return ctx.text_extents(text).x_advance


def legend_layout(doc: SceneDocument, entries: list[LegendEntry]) -> LegendLayout:
    u = _units_per_inch(doc)
    pad, swatch, row, gap = PAD_IN * u, SWATCH_IN * u, ROW_IN * u, GAP_IN * u
    text_size, title_size = TEXT_PT / 72 * u, TITLE_PT / 72 * u
    title = "Legend"
    widest = max([_text_width(e.label, text_size) for e in entries] + [0.0])
    width = pad * 2 + max(swatch + gap + widest, _text_width(title, title_size))
    height = pad * 2 + row * (len(entries) + 1)
    if doc.legend is not None:
        x, y = doc.legend.x, doc.legend.y
    else:
        x, y = MARGIN_IN * u, MARGIN_IN * u + height
    layout = LegendLayout(
        x=x, y=y, width=width, height=height, title=title, title_x=x + pad,
        title_baseline_y=y - pad - row * 0.7, text_size=text_size, title_size=title_size,
    )
    for i, entry in enumerate(entries):
        row_top = y - pad - row * (i + 1)
        swatch_top = row_top - (row - swatch) / 2
        layout.rows.append(
            LegendRow(entry, x + pad, swatch_top, swatch, x + pad + swatch + gap, swatch_top - swatch * 0.8)
        )
    return layout


def scale_indicator_layout(doc: SceneDocument) -> ScaleIndicatorLayout:
    from .render_flat import nice_scale_bar_length

    u = _units_per_inch(doc)
    length = nice_scale_bar_length(doc.page_width)
    text_size = TEXT_PT / 72 * u
    label = f"{length:g} {doc.units}"
    if doc.scale_indicator is not None:
        x, y = doc.scale_indicator.x, doc.scale_indicator.y
    else:
        x, y = doc.page_width - MARGIN_IN * u - length, MARGIN_IN * u + 0.05 * u
    return ScaleIndicatorLayout(
        x=x, y=y, length=length, label=label,
        label_x=x + length / 2 - _text_width(label, text_size) / 2,
        label_baseline_y=y + TICK_IN * u + 0.05 * u, tick=TICK_IN * u, text_size=text_size,
    )
